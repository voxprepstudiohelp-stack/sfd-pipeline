# sfd_prev_close_fetch.py v3.2
# GitHub: sfd-pipeline/sfd_prev_close_fetch.py
#
# v3.1 → v3.2 변경사항:
#   - [BM-3] ma20, ma60 컬럼 추가 (signal_aggregator v2.6 BM-3 Bias Filter 지원)
#     period="5d" → period="90d"  (MA60 계산에 최소 60거래일 필요)
#     배치 download 결과에서 MA20/MA60 계산 후 최신값 저장
#   - vol_avg 컬럼 추가 (20일 평균 거래량 — signal_aggregator L2.7 fallback용)
#   - v3.1 기존 컬럼 모두 유지 (하위 호환)
#
# 출력 컬럼 (v3.2):
#   ticker, name, prev_close, prev_open, prev_high, prev_low,
#   prev_volume, prev_value, prev_prev_close, prev_change_pct,
#   close, volume, vol_avg,                   ← signal_aggregator v2.5 호환
#   ma20, ma60,                               ← ★ v3.2 신규 (BM-3용)
#   market, fetch_date, fetched_at, data_status

import os, sys, time, logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf
import FinanceDataReader as fdr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import LATEST_DIR, HISTORY_DIR, INPUT_DIR

LATEST_PATH = os.path.join(LATEST_DIR, "sfd_prev_close_latest.csv")
INPUT_PATH  = os.path.join(INPUT_DIR,  "sfd_prev_close_input.csv")
LOG_PATH    = os.path.join(LATEST_DIR, "sfd_prev_close_fetch.log")

os.makedirs(LATEST_DIR,  exist_ok=True)
os.makedirs(HISTORY_DIR, exist_ok=True)
os.makedirs(INPUT_DIR,   exist_ok=True)

logging.basicConfig(filename=LOG_PATH, level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s", encoding="utf-8")

START_TIME = time.time()
now        = datetime.now()
fetch_time = now.strftime("%Y-%m-%d %H:%M:%S")

# ★ v3.2: MA60 계산을 위해 90d로 확장
FETCH_PERIOD   = "90d"
MA20_PERIOD    = 20
MA60_PERIOD    = 60
VOL_AVG_PERIOD = 20

print("\n========== SFD prev_close fetch v3.2 (yfinance) ==========")
print(f"실행 시각: {fetch_time}")
print(f"변경: period={FETCH_PERIOD}, ma20/ma60/vol_avg 추가 (BM-3 Bias Filter 지원)")


def calc_ma(series: pd.Series, period: int):
    """단순이동평균 최신값 반환. 데이터 부족 시 None."""
    if len(series.dropna()) < period:
        return None
    val = series.rolling(period).mean().iloc[-1]
    return round(float(val), 2) if not pd.isna(val) else None


# ── 종목 리스트 수집 및 OHLCV + MA 다운로드
records = []
for market, suffix in [("KOSPI", ".KS"), ("KOSDAQ", ".KQ")]:
    print(f"\n{market} 종목 리스트 수집 중...")
    try:
        listing = fdr.StockListing(market)
        listing.columns = [c.strip() for c in listing.columns]
        code_col = next((c for c in ["Code", "Symbol", "종목코드"] if c in listing.columns), None)
        name_col = next((c for c in ["Name", "종목명"]             if c in listing.columns), None)
        if code_col is None:
            print(f"  ⚠️ {market} 코드 컬럼 없음")
            continue

        tickers_raw = listing[code_col].astype(str).str.zfill(6).tolist()
        names       = listing[name_col].tolist() if name_col else [""] * len(tickers_raw)
        yf_tickers  = [f"{t}{suffix}" for t in tickers_raw]

        print(f"  {market}: {len(yf_tickers)}종목 → yfinance 배치 다운로드 시작...")

        BATCH = 300
        ohlcv_map = {}

        for i in range(0, len(yf_tickers), BATCH):
            batch = yf_tickers[i:i+BATCH]
            try:
                # ★ v3.2: period=90d
                data = yf.download(
                    batch,
                    period=FETCH_PERIOD,
                    auto_adjust=True,
                    progress=False,
                    threads=True,
                )
                if data.empty:
                    continue

                def get_col(col):
                    if isinstance(data.columns, pd.MultiIndex):
                        return data[col] if col in data.columns.get_level_values(0) else pd.DataFrame()
                    return data[[col]] if col in data.columns else pd.DataFrame()

                close_df  = get_col("Close")
                open_df   = get_col("Open")
                high_df   = get_col("High")
                low_df    = get_col("Low")
                volume_df = get_col("Volume")

                for t in batch:
                    def safe_get(df, ticker):
                        try:
                            if isinstance(df.columns, pd.MultiIndex):
                                s = df[ticker] if ticker in df.columns.get_level_values(1) else pd.Series()
                            else:
                                s = df[ticker] if ticker in df.columns else pd.Series()
                            return s.dropna()
                        except:
                            return pd.Series()

                    c_ser = safe_get(close_df,  t)
                    v_ser = safe_get(volume_df, t)

                    c1  = float(c_ser.iloc[-1]) if len(c_ser) >= 1 else None
                    c2  = float(c_ser.iloc[-2]) if len(c_ser) >= 2 else None
                    pcp = round((c1 - c2) / c2 * 100, 2) if c1 and c2 and c2 != 0 else None

                    # ★ v3.2: MA20 / MA60
                    ma20_val = calc_ma(c_ser, MA20_PERIOD)
                    ma60_val = calc_ma(c_ser, MA60_PERIOD)

                    # ★ v3.2: vol_avg
                    vol_avg_val = None
                    if len(v_ser) >= VOL_AVG_PERIOD:
                        va = v_ser.rolling(VOL_AVG_PERIOD).mean().iloc[-1]
                        vol_avg_val = round(float(va), 0) if not pd.isna(va) else None

                    def _get1(df, ticker):
                        try:
                            s = safe_get(df, ticker)
                            return float(s.iloc[-1]) if len(s) >= 1 else None
                        except:
                            return None

                    ohlcv_map[t] = {
                        "close":           c1,
                        "open":            _get1(open_df,   t),
                        "high":            _get1(high_df,   t),
                        "low":             _get1(low_df,    t),
                        "volume":          _get1(volume_df, t),
                        "prev_prev_close": c2,
                        "prev_change_pct": pcp,
                        "ma20":            ma20_val,    # ★ v3.2
                        "ma60":            ma60_val,    # ★ v3.2
                        "vol_avg":         vol_avg_val, # ★ v3.2
                    }

                print(f"    배치 {i//BATCH+1}: {len(batch)}종목 완료 (MA20/MA60 포함)")
                time.sleep(1)

            except Exception as e:
                print(f"    배치 {i//BATCH+1} 오류: {e}")
                for t in batch:
                    ohlcv_map[t] = {
                        "close": None, "open": None, "high": None,
                        "low": None, "volume": None,
                        "prev_prev_close": None, "prev_change_pct": None,
                        "ma20": None, "ma60": None, "vol_avg": None,
                    }

        # 결과 취합
        for ticker_raw, name, yf_t in zip(tickers_raw, names, yf_tickers):
            d = ohlcv_map.get(yf_t, {})
            records.append({
                "ticker":          ticker_raw,
                "name":            name,
                "prev_close":      d.get("close"),
                "prev_open":       d.get("open"),
                "prev_high":       d.get("high"),
                "prev_low":        d.get("low"),
                "prev_volume":     d.get("volume"),
                "prev_value":      None,
                "prev_prev_close": d.get("prev_prev_close"),
                "prev_change_pct": d.get("prev_change_pct"),
                "close":           d.get("close"),        # signal_aggregator 호환
                "volume":          d.get("volume"),       # signal_aggregator 호환
                "vol_avg":         d.get("vol_avg"),      # ★ v3.2
                "ma20":            d.get("ma20"),         # ★ v3.2 BM-3
                "ma60":            d.get("ma60"),         # ★ v3.2 BM-3
                "market":          market,
                "data_status":     "OK" if d.get("close") else "NO_DATA",
            })

        ok    = sum(1 for r in records if r["market"] == market and r["data_status"] == "OK")
        ma_ok = sum(1 for r in records if r["market"] == market and r.get("ma60") is not None)
        print(f"  {market} 완료: 성공 {ok}/{len(tickers_raw)} | MA60 유효 {ma_ok}건")
        logging.info(f"{market}: {ok}/{len(tickers_raw)} | ma60_ok={ma_ok}")

    except Exception as e:
        print(f"  {market} 전체 오류: {e}")
        logging.error(f"{market}: {e}")

if not records:
    print("❌ 데이터 없음")
    sys.exit(1)

merged = pd.DataFrame(records)
trade_day = (now - timedelta(days=1)).strftime("%Y%m%d")
merged["fetch_date"] = trade_day
merged["fetched_at"] = fetch_time

# ── 컬럼 순서
cols = [
    "ticker", "name",
    "prev_close", "prev_open", "prev_high", "prev_low",
    "prev_volume", "prev_value",
    "prev_prev_close", "prev_change_pct",
    "close", "volume", "vol_avg",   # signal_aggregator 호환
    "ma20", "ma60",                 # ★ v3.2 BM-3
    "market", "fetch_date", "fetched_at", "data_status",
]
cols = [c for c in cols if c in merged.columns]
merged = merged[cols]

merged.to_csv(LATEST_PATH, index=False, encoding="utf-8-sig")
print(f"\n✅ latest : {LATEST_PATH}")

history_file = os.path.join(HISTORY_DIR, f"sfd_prev_close_{trade_day}.csv")
merged.to_csv(history_file, index=False, encoding="utf-8-sig")
print(f"✅ history: {history_file}")

input_df = merged[["ticker", "prev_close"]].rename(columns={"ticker": "stock_code"})
input_df.to_csv(INPUT_PATH, index=False, encoding="utf-8-sig")
print(f"✅ input  : {INPUT_PATH}")

elapsed  = round(time.time() - START_TIME)
ok_total = len(merged[merged["data_status"] == "OK"])
ma60_ok  = merged["ma60"].notna().sum() if "ma60" in merged.columns else 0
pcp_ok   = merged["prev_change_pct"].notna().sum()
print(f"\n전체 종목: {len(merged)} | 성공: {ok_total} | MA60 유효: {ma60_ok}건 | prev_change_pct: {pcp_ok}건 | 경과: {elapsed}초")
logging.info(f"완료 | 전체={len(merged)} | 성공={ok_total} | ma60_ok={ma60_ok} | prev_change_pct={pcp_ok} | elapsed={elapsed}s")
