# sfd_prev_close_fetch.py v3.4
# GitHub: sfd-pipeline/tools/sfd_prev_close_fetch.py
#
# v3.3 -> v3.4 changes:
# - [P2] period 90d -> 5d (OHLCV 전용, ~2분 목표)
# - [P2] MA20/MA60/vol_avg: 전날 캐시 CSV에서 incremental update
#        공식: new_ma = prev_ma + (new_close - dropped_close) / period
#        캐시 없는 첫날만 period=90d full fetch (1회성 초기화)
# - [P2] ThreadPoolExecutor 제거 (rate limit 역효과 확인)
# - [P2] BATCH 200 -> 300 복원 (순차 최적)
# - time.sleep(0.5) 복원 (Yahoo rate limit 안전)
# - 모든 출력 컬럼 v3.2/v3.3 동일 (하위 호환 100%)
#
# MA 캐시 파일: outputs/latest/sfd_prev_close_ma_cache.csv
#   컬럼: ticker, ma20, ma60, vol_avg, ma20_buf(20개 종가), ma60_buf(60개 종가), vol_buf(20개 거래량)
#
# 실행 흐름:
#   [캐시 있음] period=5d fetch -> incremental MA update -> 저장 (~2분)
#   [캐시 없음] period=90d full fetch -> MA 계산 -> 캐시 생성 (~22분, 첫날 1회)

import io, os, sys, time, logging, json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf
import FinanceDataReader as fdr

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import LATEST_DIR, HISTORY_DIR, INPUT_DIR

LATEST_PATH   = os.path.join(LATEST_DIR, "sfd_prev_close_latest.csv")
MA_CACHE_PATH = os.path.join(LATEST_DIR, "sfd_prev_close_ma_cache.csv")
INPUT_PATH    = os.path.join(INPUT_DIR,  "sfd_prev_close_input.csv")
LOG_PATH      = os.path.join(LATEST_DIR, "sfd_prev_close_fetch.log")

os.makedirs(LATEST_DIR,  exist_ok=True)
os.makedirs(HISTORY_DIR, exist_ok=True)
os.makedirs(INPUT_DIR,   exist_ok=True)

logging.basicConfig(filename=LOG_PATH, level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s", encoding="utf-8")

START_TIME  = time.time()
now         = datetime.now()
fetch_time  = now.strftime("%Y-%m-%d %H:%M:%S")
today_str   = now.strftime("%Y%m%d")

BATCH_SIZE     = 300
MA20_PERIOD    = 20
MA60_PERIOD    = 60
VOL_AVG_PERIOD = 20
PERIOD_FAST    = "5d"   # 일반 실행
PERIOD_FULL    = "90d"  # 캐시 없을 때 초기화용

print("\n========== SFD prev_close fetch v3.4 (incremental MA) ==========")
print(f"Start: {fetch_time}")


# ── MA 캐시 로드
def load_ma_cache() -> dict:
    """
    Returns dict: {ticker -> {ma20, ma60, vol_avg, c_buf: [float,...], v_buf: [float,...]}}
    c_buf 길이 = MA60_PERIOD, v_buf 길이 = VOL_AVG_PERIOD
    """
    if not os.path.exists(MA_CACHE_PATH):
        return {}
    try:
        df = pd.read_csv(MA_CACHE_PATH, encoding="utf-8-sig", dtype={"ticker": str})
        cache = {}
        for _, row in df.iterrows():
            t = str(row["ticker"]).zfill(6) if len(str(row["ticker"])) <= 6 else str(row["ticker"])
            try:
                c_buf = json.loads(row["c_buf"]) if pd.notna(row.get("c_buf")) else []
                v_buf = json.loads(row["v_buf"]) if pd.notna(row.get("v_buf")) else []
            except Exception:
                c_buf, v_buf = [], []
            cache[t] = {
                "ma20":    float(row["ma20"])    if pd.notna(row.get("ma20"))    else None,
                "ma60":    float(row["ma60"])    if pd.notna(row.get("ma60"))    else None,
                "vol_avg": float(row["vol_avg"]) if pd.notna(row.get("vol_avg")) else None,
                "c_buf":   c_buf,
                "v_buf":   v_buf,
            }
        return cache
    except Exception as e:
        logging.warning(f"MA cache load failed: {e}")
        return {}


def save_ma_cache(cache: dict):
    rows = []
    for ticker, v in cache.items():
        rows.append({
            "ticker":  ticker,
            "ma20":    v.get("ma20"),
            "ma60":    v.get("ma60"),
            "vol_avg": v.get("vol_avg"),
            "c_buf":   json.dumps(v.get("c_buf", [])),
            "v_buf":   json.dumps(v.get("v_buf", [])),
        })
    pd.DataFrame(rows).to_csv(MA_CACHE_PATH, index=False, encoding="utf-8-sig")


def incremental_ma(c_buf: list, v_buf: list, new_close: float, new_vol: float):
    """
    c_buf: 최근 MA60_PERIOD개 종가 (oldest→newest)
    v_buf: 최근 VOL_AVG_PERIOD개 거래량
    Returns: (ma20, ma60, vol_avg, updated_c_buf, updated_v_buf)
    """
    c_buf = list(c_buf) + [new_close]
    if len(c_buf) > MA60_PERIOD:
        c_buf = c_buf[-MA60_PERIOD:]

    v_buf = list(v_buf) + [new_vol]
    if len(v_buf) > VOL_AVG_PERIOD:
        v_buf = v_buf[-VOL_AVG_PERIOD:]

    ma20    = round(float(np.mean(c_buf[-MA20_PERIOD:])),    2) if len(c_buf) >= MA20_PERIOD    else None
    ma60    = round(float(np.mean(c_buf[-MA60_PERIOD:])),    2) if len(c_buf) >= MA60_PERIOD    else None
    vol_avg = round(float(np.mean(v_buf[-VOL_AVG_PERIOD:])), 0) if len(v_buf) >= VOL_AVG_PERIOD else None

    return ma20, ma60, vol_avg, c_buf, v_buf


# ── yfinance 배치 다운로드 (공통)
def download_batches(yf_tickers: list, period: str) -> dict:
    """Returns {yf_ticker: {close, open, high, low, volume, prev_prev_close, prev_change_pct, c_series, v_series}}"""
    ohlcv_map = {}
    for i in range(0, len(yf_tickers), BATCH_SIZE):
        batch = yf_tickers[i:i + BATCH_SIZE]
        try:
            data = yf.download(batch, period=period, auto_adjust=True, progress=False, threads=True)
            if data.empty:
                for t in batch:
                    ohlcv_map[t] = None
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

            def safe_ser(df, t):
                try:
                    if isinstance(df.columns, pd.MultiIndex):
                        s = df[t] if t in df.columns.get_level_values(1) else pd.Series()
                    else:
                        s = df[t] if t in df.columns else pd.Series()
                    return s.dropna()
                except Exception:
                    return pd.Series()

            def get1(df, t):
                s = safe_ser(df, t)
                return float(s.iloc[-1]) if len(s) >= 1 else None

            for t in batch:
                c_ser = safe_ser(close_df,  t)
                v_ser = safe_ser(volume_df, t)
                c1 = float(c_ser.iloc[-1]) if len(c_ser) >= 1 else None
                c2 = float(c_ser.iloc[-2]) if len(c_ser) >= 2 else None
                pcp = round((c1 - c2) / c2 * 100, 2) if c1 and c2 and c2 != 0 else None
                ohlcv_map[t] = {
                    "close":           c1,
                    "open":            get1(open_df,   t),
                    "high":            get1(high_df,   t),
                    "low":             get1(low_df,    t),
                    "volume":          float(v_ser.iloc[-1]) if len(v_ser) >= 1 else None,
                    "prev_prev_close": c2,
                    "prev_change_pct": pcp,
                    "c_series":        c_ser.tolist(),  # full series for cache init
                    "v_series":        v_ser.tolist(),
                }
            print(f"  batch {i//BATCH_SIZE+1:02d}/{(len(yf_tickers)-1)//BATCH_SIZE+1:02d} done ({period})")

        except Exception as e:
            print(f"  batch {i//BATCH_SIZE+1:02d} ERROR: {e}")
            for t in batch:
                ohlcv_map[t] = None
        time.sleep(0.5)
    return ohlcv_map


# ── 메인
ma_cache   = load_ma_cache()
has_cache  = len(ma_cache) > 100  # 충분한 캐시 있으면 fast mode
fetch_mode = "FAST(5d)" if has_cache else "FULL(90d, init)"
period     = PERIOD_FAST if has_cache else PERIOD_FULL

print(f"  MA cache: {len(ma_cache)} tickers | mode: {fetch_mode}")

records    = []
new_cache  = {}

for market, suffix in [("KOSPI", ".KS"), ("KOSDAQ", ".KQ")]:
    print(f"\n[{market}] listing...")
    try:
        listing  = fdr.StockListing(market)
        listing.columns = [c.strip() for c in listing.columns]
        code_col = next((c for c in ["Code", "Symbol", "종목코드"] if c in listing.columns), None)
        name_col = next((c for c in ["Name", "종목명"]             if c in listing.columns), None)
        if code_col is None:
            continue

        tickers_raw = listing[code_col].astype(str).str.zfill(6).tolist()
        names       = listing[name_col].tolist() if name_col else [""] * len(tickers_raw)
        yf_tickers  = [f"{t}{suffix}" for t in tickers_raw]

        print(f"  [{market}] {len(yf_tickers)} tickers -> download {period}...")
        ohlcv_map = download_batches(yf_tickers, period)

        ok = 0
        for ticker_raw, name, yf_t in zip(tickers_raw, names, yf_tickers):
            d = ohlcv_map.get(yf_t)
            if d is None or d.get("close") is None:
                records.append({
                    "ticker": ticker_raw, "name": name,
                    "prev_close": None, "prev_open": None, "prev_high": None, "prev_low": None,
                    "prev_volume": None, "prev_value": None,
                    "prev_prev_close": None, "prev_change_pct": None,
                    "close": None, "volume": None, "vol_avg": None,
                    "ma20": None, "ma60": None,
                    "market": market, "data_status": "NO_DATA",
                })
                continue

            c1  = d["close"]
            vol = d["volume"] or 0.0

            if has_cache and ticker_raw in ma_cache:
                # incremental update
                cached = ma_cache[ticker_raw]
                ma20, ma60, vol_avg, c_buf, v_buf = incremental_ma(
                    cached["c_buf"], cached["v_buf"], c1, vol
                )
            else:
                # full series (초기화 또는 신규 종목)
                c_ser = d.get("c_series", [])
                v_ser = d.get("v_series", [])
                c_buf = c_ser[-MA60_PERIOD:]
                v_buf = v_ser[-VOL_AVG_PERIOD:]
                ma20    = round(float(np.mean(c_buf[-MA20_PERIOD:])),    2) if len(c_buf) >= MA20_PERIOD    else None
                ma60    = round(float(np.mean(c_buf[-MA60_PERIOD:])),    2) if len(c_buf) >= MA60_PERIOD    else None
                vol_avg = round(float(np.mean(v_buf[-VOL_AVG_PERIOD:])), 0) if len(v_buf) >= VOL_AVG_PERIOD else None

            new_cache[ticker_raw] = {
                "ma20": ma20, "ma60": ma60, "vol_avg": vol_avg,
                "c_buf": c_buf, "v_buf": v_buf,
            }

            records.append({
                "ticker":           ticker_raw,
                "name":             name,
                "prev_close":       c1,
                "prev_open":        d["open"],
                "prev_high":        d["high"],
                "prev_low":         d["low"],
                "prev_volume":      vol,
                "prev_value":       None,
                "prev_prev_close":  d["prev_prev_close"],
                "prev_change_pct":  d["prev_change_pct"],
                "close":            c1,
                "volume":           vol,
                "vol_avg":          vol_avg,
                "ma20":             ma20,
                "ma60":             ma60,
                "market":           market,
                "data_status":      "OK",
            })
            ok += 1

        print(f"  [{market}] OK={ok}/{len(tickers_raw)}")
        logging.info(f"{market}: {ok}/{len(tickers_raw)}")

    except Exception as e:
        print(f"  [{market}] FATAL: {e}")
        logging.error(f"{market}: {e}")

if not records:
    print("No records. Exit.")
    sys.exit(1)

# ── 저장
merged = pd.DataFrame(records)
trade_day = (now - timedelta(days=1)).strftime("%Y%m%d")
merged["fetch_date"] = today_str
merged["fetched_at"] = fetch_time

cols = [
    "ticker", "name",
    "prev_close", "prev_open", "prev_high", "prev_low",
    "prev_volume", "prev_value",
    "prev_prev_close", "prev_change_pct",
    "close", "volume", "vol_avg",
    "ma20", "ma60",
    "market", "fetch_date", "fetched_at", "data_status",
]
cols   = [c for c in cols if c in merged.columns]
merged = merged[cols]

merged.to_csv(LATEST_PATH, index=False, encoding="utf-8-sig")
history_file = os.path.join(HISTORY_DIR, f"sfd_prev_close_{trade_day}.csv")
merged.to_csv(history_file, index=False, encoding="utf-8-sig")

input_df = merged[["ticker", "prev_close"]].rename(columns={"ticker": "stock_code"})
input_df.to_csv(INPUT_PATH, index=False, encoding="utf-8-sig")

# MA 캐시 갱신
save_ma_cache(new_cache)

elapsed  = round(time.time() - START_TIME)
ok_total = len(merged[merged["data_status"] == "OK"])
ma60_ok  = merged["ma60"].notna().sum() if "ma60" in merged.columns else 0
print(f"\nTotal={len(merged)} | OK={ok_total} | MA60={ma60_ok} | elapsed={elapsed}s | mode={fetch_mode}")
logging.info(f"DONE | trade_day={today_str} | total={len(merged)} | success={ok_total} | fail={len(merged)-ok_total} | runtime={elapsed}s | mode={fetch_mode}")
