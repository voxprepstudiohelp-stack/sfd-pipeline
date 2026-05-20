# 파일명: sfd_prev_close_fetch.py
# 작성: Claude (Anthropic) — v1.4 (GitHub Actions 호환)
# 변경: D:\ 하드코딩 경로 → config.py 기반 /tmp/sfd 경로
# 파일위치(GitHub): sfd-pipeline/tools/sfd_prev_close_fetch.py

import os
import sys
import time
import logging
from datetime import datetime, timedelta

import pandas as pd
import FinanceDataReader as fdr

# ── config.py에서 경로 로드
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BASE, LATEST_DIR, HISTORY_DIR, INPUT_DIR

LATEST_PATH = os.path.join(LATEST_DIR, "sfd_prev_close_latest.csv")
INPUT_PATH  = os.path.join(INPUT_DIR,  "sfd_prev_close_input.csv")
LOG_PATH    = os.path.join(LATEST_DIR, "sfd_prev_close_fetch.log")

os.makedirs(LATEST_DIR,  exist_ok=True)
os.makedirs(HISTORY_DIR, exist_ok=True)
os.makedirs(INPUT_DIR,   exist_ok=True)

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    encoding="utf-8"
)

START_TIME = time.time()
today      = datetime.now()
fetch_time = today.strftime("%Y-%m-%d %H:%M:%S")

def find_recent_market_day():
    for i in range(14):
        d = (today - timedelta(days=i))
        if d.weekday() >= 5:
            continue
        d_str = d.strftime("%Y-%m-%d")
        try:
            df = fdr.DataReader("005930", d_str, d_str)
            if df is not None and len(df) > 0:
                result = d.strftime("%Y%m%d")
                print(f" 거래일 확인: {result}")
                logging.info(f"trade_day={result}")
                return result
        except Exception as e:
            print(f" {d_str} 시도 실패: {type(e).__name__}")
    return None

def fetch_all_stocks(trade_day):
    records  = []
    date_str = f"{trade_day[:4]}-{trade_day[4:6]}-{trade_day[6:]}"

    for market in ["KOSPI", "KOSDAQ"]:
        try:
            print(f" {market} 종목 리스트 수집 중...")
            listing = fdr.StockListing(market)
            listing.columns = [c.strip() for c in listing.columns]

            code_col = next((c for c in ["Code", "Symbol", "종목코드"] if c in listing.columns), None)
            name_col = next((c for c in ["Name", "종목명"]             if c in listing.columns), None)

            if code_col is None:
                print(f" ⚠️ {market} 코드 컬럼 없음: {list(listing.columns)}")
                continue

            print(f" {market} 종목수: {len(listing)} | 데이터 수집 중...")

            for _, row in listing.iterrows():
                ticker = str(row[code_col]).zfill(6)
                name   = str(row[name_col]) if name_col else ""
                try:
                    df = fdr.DataReader(ticker, date_str, date_str)
                    if df is not None and len(df) > 0:
                        r = df.iloc[-1]
                        records.append({
                            "ticker":      ticker,
                            "name":        name,
                            "prev_close":  r.get("Close",  None),
                            "prev_open":   r.get("Open",   None),
                            "prev_high":   r.get("High",   None),
                            "prev_low":    r.get("Low",    None),
                            "prev_volume": r.get("Volume", None),
                            "prev_value":  None,
                            "data_status": "OK"
                        })
                    else:
                        records.append({"ticker": ticker, "name": name,
                            "prev_close": None, "prev_open": None, "prev_high": None,
                            "prev_low": None, "prev_volume": None, "prev_value": None,
                            "data_status": "NO_DATA"})
                except Exception:
                    records.append({"ticker": ticker, "name": name,
                        "prev_close": None, "prev_open": None, "prev_high": None,
                        "prev_low": None, "prev_volume": None, "prev_value": None,
                        "data_status": "FETCH_ERR"})
        except Exception as e:
            print(f" {market} 전체 오류: {e}")
            logging.error(f"{market} listing error: {e}")

    return pd.DataFrame(records)

# ── 실행
print("\n========== SFD prev_close fetch v1.4 ==========")
print(f"실행 시각 : {fetch_time}")
print("거래일 탐색 중...")

trade_day = find_recent_market_day()

if trade_day is None:
    print("❌ 거래일 탐색 실패")
    logging.error("trade_day: not found")
    sys.exit(1)

print(f"✅ 기준 거래일: {trade_day}")
print("전종목 데이터 수집 중 (10~30분 소요)...")

merged = fetch_all_stocks(trade_day)

if merged.empty:
    print("❌ 데이터 수집 실패")
    sys.exit(1)

merged["fetch_date"] = trade_day
merged["fetched_at"] = fetch_time

cols = ["ticker", "name", "prev_close", "prev_open", "prev_high",
        "prev_low", "prev_volume", "prev_value", "fetch_date", "fetched_at", "data_status"]
cols   = [c for c in cols if c in merged.columns]
merged = merged[cols]

merged.to_csv(LATEST_PATH, index=False, encoding="utf-8-sig")
print(f"✅ latest : {LATEST_PATH}")

history_file = os.path.join(HISTORY_DIR, f"sfd_prev_close_{trade_day}.csv")
merged.to_csv(history_file, index=False, encoding="utf-8-sig")
print(f"✅ history: {history_file}")

input_df = merged[["ticker", "prev_close"]].copy()
input_df.columns = ["stock_code", "prev_close"]
input_df.to_csv(INPUT_PATH, index=False, encoding="utf-8-sig")
print(f"✅ input  : {INPUT_PATH}")

success = len(merged[merged["data_status"] == "OK"])
elapsed = round(time.time() - START_TIME)
print(f"\n총 종목: {len(merged)} | 성공: {success} | 소요: {elapsed}초")
logging.info(f"완료 | 총={len(merged)} | 성공={success} | 소요={elapsed}s")
