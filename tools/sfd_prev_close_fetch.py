# sfd_prev_close_fetch.py v3.0 (yfinance 배치)
# GitHub: sfd-pipeline/tools/sfd_prev_close_fetch.py

import os, sys, time, logging
from datetime import datetime, timedelta

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

print("\n========== SFD prev_close fetch v3.0 (yfinance) ==========")
print(f"실행 시각: {fetch_time}")

# ── 종목 리스트 수집 (FDR → 종목코드/이름만 사용)
records = []
for market, suffix in [("KOSPI", ".KS"), ("KOSDAQ", ".KQ")]:
    print(f"\n{market} 종목 리스트 수집 중...")
    try:
        listing = fdr.StockListing(market)
        listing.columns = [c.strip() for c in listing.columns]
        code_col = next((c for c in ["Code","Symbol","종목코드"] if c in listing.columns), None)
        name_col = next((c for c in ["Name","종목명"]             if c in listing.columns), None)
        if code_col is None:
            print(f"  ⚠️ {market} 코드 컬럼 없음")
            continue

        tickers_raw  = listing[code_col].astype(str).str.zfill(6).tolist()
        names        = listing[name_col].tolist() if name_col else [""] * len(tickers_raw)
        yf_tickers   = [f"{t}{suffix}" for t in tickers_raw]

        print(f"  {market}: {len(yf_tickers)}종목 → yfinance 배치 다운로드 시작...")

        # 300종목씩 배치 처리
        BATCH = 300
        close_map = {}
        ohlcv_map = {}

        for i in range(0, len(yf_tickers), BATCH):
            batch = yf_tickers[i:i+BATCH]
            try:
                data = yf.download(
                    batch,
                    period="3d",
                    auto_adjust=True,
                    progress=False,
                    threads=True
                )
                if data.empty:
                    continue

                close = data["Close"].iloc[-1]  if "Close"  in data.columns else pd.Series()
                open_ = data["Open"].iloc[-1]   if "Open"   in data.columns else pd.Series()
                high  = data["High"].iloc[-1]   if "High"   in data.columns else pd.Series()
                low   = data["Low"].iloc[-1]    if "Low"    in data.columns else pd.Series()
                vol   = data["Volume"].iloc[-1] if "Volume" in data.columns else pd.Series()

                for t in batch:
                    ohlcv_map[t] = {
                        "close":  close.get(t,  None) if hasattr(close,  "get") else None,
                        "open":   open_.get(t,  None) if hasattr(open_,  "get") else None,
                        "high":   high.get(t,   None) if hasattr(high,   "get") else None,
                        "low":    low.get(t,    None) if hasattr(low,    "get") else None,
                        "volume": vol.get(t,    None) if hasattr(vol,    "get") else None,
                    }
                print(f"    배치 {i//BATCH+1}: {len(batch)}종목 완료")
                time.sleep(1)  # rate limit 방지

            except Exception as e:
                print(f"    배치 {i//BATCH+1} 오류: {e}")
                for t in batch:
                    ohlcv_map[t] = {"close": None,"open": None,"high": None,"low": None,"volume": None}

        # 결과 취합
        for ticker_raw, name, yf_t in zip(tickers_raw, names, yf_tickers):
            d = ohlcv_map.get(yf_t, {})
            records.append({
                "ticker":      ticker_raw,
                "name":        name,
                "prev_close":  d.get("close"),
                "prev_open":   d.get("open"),
                "prev_high":   d.get("high"),
                "prev_low":    d.get("low"),
                "prev_volume": d.get("volume"),
                "prev_value":  None,
                "market":      market,
                "data_status": "OK" if d.get("close") else "NO_DATA"
            })

        ok = sum(1 for r in records if r["market"]==market and r["data_status"]=="OK")
        print(f"  {market} 완료: 성공 {ok}/{len(tickers_raw)}")
        logging.info(f"{market}: {ok}/{len(tickers_raw)}")

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

merged.to_csv(LATEST_PATH, index=False, encoding="utf-8-sig")
print(f"\n✅ latest : {LATEST_PATH}")

history_file = os.path.join(HISTORY_DIR, f"sfd_prev_close_{trade_day}.csv")
merged.to_csv(history_file, index=False, encoding="utf-8-sig")
print(f"✅ history: {history_file}")

input_df = merged[["ticker","prev_close"]].rename(columns={"ticker":"stock_code"})
input_df.to_csv(INPUT_PATH, index=False, encoding="utf-8-sig")
print(f"✅ input  : {INPUT_PATH}")

elapsed = round(time.time() - START_TIME)
ok_total = len(merged[merged["data_status"]=="OK"])
print(f"\n총 종목: {len(merged)} | 성공: {ok_total} | 소요: {elapsed}초")
logging.info(f"완료 | 총={len(merged)} | 성공={ok_total} | 소요={elapsed}s")
