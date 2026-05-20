# sfd_prev_close_fetch.py v2.0 (pykrx 일괄수집)
# GitHub: sfd-pipeline/tools/sfd_prev_close_fetch.py

import os, sys, time, logging
from datetime import datetime, timedelta

import pandas as pd
from pykrx import stock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import LATEST_DIR, HISTORY_DIR, INPUT_DIR

LATEST_PATH  = os.path.join(LATEST_DIR, "sfd_prev_close_latest.csv")
INPUT_PATH   = os.path.join(INPUT_DIR,  "sfd_prev_close_input.csv")
LOG_PATH     = os.path.join(LATEST_DIR, "sfd_prev_close_fetch.log")

os.makedirs(LATEST_DIR,  exist_ok=True)
os.makedirs(HISTORY_DIR, exist_ok=True)
os.makedirs(INPUT_DIR,   exist_ok=True)

logging.basicConfig(filename=LOG_PATH, level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s", encoding="utf-8")

START_TIME = time.time()
now        = datetime.now()
fetch_time = now.strftime("%Y-%m-%d %H:%M:%S")

def find_recent_trade_date():
    """최근 거래일 탐색 (최대 7일 이전)"""
    for i in range(7):
        d = now - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        d_str = d.strftime("%Y%m%d")
        try:
            df = stock.get_market_ohlcv_by_ticker(d_str, market="KOSPI")
            if df is not None and len(df) > 0:
                print(f"✅ 거래일 확인: {d_str}")
                logging.info(f"trade_day={d_str}")
                return d_str
        except Exception as e:
            print(f"  {d_str} 시도 실패: {e}")
    return None

def fetch_all_stocks(trade_day):
    records = []

    for market in ["KOSPI", "KOSDAQ"]:
        print(f"\n{market} 일괄 수집 중...")
        try:
            # 한 번의 호출로 전체 종목 OHLCV 수집
            ohlcv = stock.get_market_ohlcv_by_ticker(trade_day, market=market)
            # 종목명 수집
            names = stock.get_market_ticker_name

            for ticker in ohlcv.index:
                row = ohlcv.loc[ticker]
                try:
                    name = stock.get_market_ticker_name(ticker)
                except:
                    name = ""
                records.append({
                    "ticker":      ticker,
                    "name":        name,
                    "prev_close":  row.get("종가",  None),
                    "prev_open":   row.get("시가",  None),
                    "prev_high":   row.get("고가",  None),
                    "prev_low":    row.get("저가",  None),
                    "prev_volume": row.get("거래량", None),
                    "prev_value":  row.get("거래대금", None),
                    "market":      market,
                    "data_status": "OK"
                })
            print(f"  {market}: {len(ohlcv)}종목 완료")
            logging.info(f"{market}: {len(ohlcv)}종목")

        except Exception as e:
            print(f"  {market} 오류: {e}")
            logging.error(f"{market} error: {e}")

    return pd.DataFrame(records)

# ── 실행
print("\n========== SFD prev_close fetch v2.0 (pykrx) ==========")
print(f"실행 시각: {fetch_time}")

trade_day = find_recent_trade_date()
if trade_day is None:
    print("❌ 거래일 탐색 실패")
    sys.exit(1)

print(f"기준 거래일: {trade_day}")
merged = fetch_all_stocks(trade_day)

if merged.empty:
    print("❌ 데이터 없음")
    sys.exit(1)

merged["fetch_date"] = trade_day
merged["fetched_at"] = fetch_time

merged.to_csv(LATEST_PATH, index=False, encoding="utf-8-sig")
print(f"✅ latest : {LATEST_PATH}")

history_file = os.path.join(HISTORY_DIR, f"sfd_prev_close_{trade_day}.csv")
merged.to_csv(history_file, index=False, encoding="utf-8-sig")
print(f"✅ history: {history_file}")

input_df = merged[["ticker", "prev_close"]].rename(columns={"ticker": "stock_code"})
input_df.to_csv(INPUT_PATH, index=False, encoding="utf-8-sig")
print(f"✅ input  : {INPUT_PATH}")

elapsed = round(time.time() - START_TIME)
print(f"\n총 종목: {len(merged)} | 소요: {elapsed}초")
logging.info(f"완료 | 총={len(merged)} | 소요={elapsed}s")
