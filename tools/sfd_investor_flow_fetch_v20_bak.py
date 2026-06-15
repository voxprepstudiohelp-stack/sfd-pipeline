# 파일명: sfd_investor_flow_fetch.py
# 작성자: Claude (Anthropic) — v2.0
# 변경이력: v1.3 KRX OTP LOGOUT 오류 → pykrx 라이브러리 교체
# 실행방법: python sfd_investor_flow_fetch.py

import os
import time
import logging
from datetime import datetime, timedelta

import pandas as pd
from pykrx import stock

# ================================================================
# PATH
# ================================================================
BASE        = r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline"
LATEST_DIR  = os.path.join(BASE, r"outputs\latest")
HISTORY_DIR = os.path.join(BASE, r"outputs\history")
INPUT_DIR   = os.path.join(BASE, r"inputs")
LOG_PATH    = os.path.join(LATEST_DIR, "sfd_investor_flow_fetch.log")
LATEST_CSV  = os.path.join(LATEST_DIR, "sfd_investor_flow_latest.csv")
INPUT_CSV   = os.path.join(INPUT_DIR,  "sfd_investor_flow_input.csv")

os.makedirs(LATEST_DIR,  exist_ok=True)
os.makedirs(HISTORY_DIR, exist_ok=True)
os.makedirs(INPUT_DIR,   exist_ok=True)

# ================================================================
# 로깅
# ================================================================
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    encoding="utf-8"
)

START_TIME = time.time()
now        = datetime.now()
fetch_time = now.strftime("%Y-%m-%d %H:%M:%S")

print(f"\n========== SFD investor_flow fetch v2.0 (pykrx) ==========")
print(f"Run time: {fetch_time}")

# ================================================================
# 최근 거래일 탐지 (pykrx — 삼성전자 OHLCV 기준)
# ================================================================
def find_recent_trade_date():
    for i in range(7):
        d = now - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        d_str = d.strftime("%Y%m%d")
        try:
            df = stock.get_market_ohlcv(d_str, d_str, "005930")
            if df is not None and len(df) > 0:
                print(f"  Trade date confirmed: {d_str}")
                logging.info(f"trade_date={d_str}")
                return d_str
        except Exception:
            pass
    return now.strftime("%Y%m%d")

trade_date = find_recent_trade_date()
print(f"✅ Base trade date: {trade_date}")

# ================================================================
# 순매수 컬럼 탐지 (pykrx 버전 차이 대응)
# ================================================================
def get_net_col(df):
    """pykrx 반환 DataFrame에서 순매수 컬럼을 탐지"""
    candidates = ["순매수", "순매수량", "net", "Net"]
    for c in candidates:
        if c in df.columns:
            return df[c]
    # fallback: 마지막 숫자형 컬럼
    num_cols = df.select_dtypes(include="number").columns.tolist()
    if num_cols:
        return df[num_cols[-1]]
    return pd.Series(0, index=df.index)

# ================================================================
# pykrx 수급 데이터 수집
# 외국인합계 / 기관합계 / 개인 — KOSPI + KOSDAQ
# ================================================================
INVESTORS = {
    "foreign":     "외국인합계",
    "institution": "기관합계",
    "individual":  "개인",
}

def get_investor_flow(date):
    all_frames = []

    for market in ["KOSPI", "KOSDAQ"]:
        print(f"\n  [{market}] Collecting investor flow...")
        inv_data = {}

        for key, inv_name in INVESTORS.items():
            try:
                df = stock.get_market_net_purchases_of_equities_by_ticker(
                    date, date, market, inv_name
                )
                if df is None or df.empty:
                    print(f"    ⚠️  {inv_name}: empty data")
                    inv_data[key] = pd.Series(dtype=float)
                else:
                    inv_data[key] = get_net_col(df).rename(key)
                    inv_data[key].index = df.index.astype(str).str.zfill(6)
                    print(f"    ✅ {inv_name}: {len(inv_data[key])} tickers")
            except Exception as e:
                print(f"    ❌ {inv_name} ERROR: {e}")
                logging.error(f"{market}/{inv_name} fetch error: {e}")
                inv_data[key] = pd.Series(dtype=float)

        # 3개 시리즈 병합
        base_idx = (
            inv_data.get("foreign", pd.Series(dtype=float)).index
            .union(inv_data.get("institution", pd.Series(dtype=float)).index)
        )
        if len(base_idx) == 0:
            print(f"    ❌ {market}: no data — skip")
            continue

        mdf = pd.DataFrame(index=base_idx)
        mdf.index.name = "ticker"
        mdf["foreign_net_buy"]      = inv_data.get("foreign",     pd.Series(dtype=float))
        mdf["institution_net_buy"]  = inv_data.get("institution", pd.Series(dtype=float))
        mdf["individual_net_buy"]   = inv_data.get("individual",  pd.Series(dtype=float))
        mdf = mdf.fillna(0)

        # 금액 컬럼 — pykrx 순매수는 수량 기준 / 금액은 0 초기화 (추후 확장)
        mdf["foreign_net_value"]     = 0
        mdf["institution_net_value"] = 0
        mdf["individual_net_value"]  = 0

        mdf = mdf.reset_index()
        mdf["ticker"] = mdf["ticker"].astype(str).str.zfill(6)
        print(f"  [{market}] DONE: {len(mdf)} tickers")
        all_frames.append(mdf)

    if not all_frames:
        return pd.DataFrame()

    combined = pd.concat(all_frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["ticker"])
    return combined

print("\nCollecting KRX investor flow data (pykrx)...")
flow = get_investor_flow(trade_date)

# ================================================================
# 종목 마스터 (FDR → fallback: pykrx)
# ================================================================
print("\nCollecting ticker list...")
stocks = pd.DataFrame()
try:
    import FinanceDataReader as fdr
    kospi  = fdr.StockListing("KOSPI")[["Code", "Name"]]
    kosdaq = fdr.StockListing("KOSDAQ")[["Code", "Name"]]
    stocks = pd.concat([kospi, kosdaq]).drop_duplicates(subset=["Code"])
    stocks.columns = ["ticker", "name"]
    stocks["ticker"] = stocks["ticker"].astype(str).str.zfill(6)
    print(f"  tickers: {len(stocks)} (FDR)")
except Exception as e:
    print(f"  ⚠️  FDR FAIL: {e} — pykrx fallback")
    try:
        df_kp = stock.get_market_ticker_list(trade_date, market="KOSPI")
        df_kq = stock.get_market_ticker_list(trade_date, market="KOSDAQ")
        tickers = list(df_kp) + list(df_kq)
        stocks = pd.DataFrame({"ticker": [str(t).zfill(6) for t in tickers], "name": ""})
        print(f"  tickers: {len(stocks)} (pykrx fallback)")
    except Exception as e2:
        print(f"  ❌ Ticker list collection FAIL: {e2}")
        stocks = pd.DataFrame(columns=["ticker", "name"])

# ================================================================
# 병합 및 상태 부여
# ================================================================
if flow.empty:
    print("\n⚠️  No investor flow data — NO_DATA mode")
    result = stocks.copy()
    for col in ["foreign_net_buy", "foreign_net_value",
                "institution_net_buy", "institution_net_value",
                "individual_net_buy", "individual_net_value"]:
        result[col] = 0
    result["data_status"] = "NO_DATA"
else:
    result = stocks.merge(flow, on="ticker", how="left")
    result = result.fillna(0)
    result["data_status"] = "OK"
    zero_mask = (
        (result["foreign_net_buy"]     == 0) &
        (result["institution_net_buy"] == 0) &
        (result["individual_net_buy"]  == 0)
    )
    result.loc[zero_mask, "data_status"] = "NO_FLOW"

result["fetch_date"] = trade_date
result["fetched_at"] = fetch_time

# 컬럼 순서 확정
FINAL_COLS = [
    "ticker", "name",
    "foreign_net_buy", "foreign_net_value",
    "institution_net_buy", "institution_net_value",
    "individual_net_buy", "individual_net_value",
    "fetch_date", "fetched_at", "data_status"
]
FINAL_COLS = [c for c in FINAL_COLS if c in result.columns]
result = result[FINAL_COLS]

# ================================================================
# 저장 — latest / history / input
# ================================================================
result.to_csv(LATEST_CSV, index=False, encoding="utf-8-sig")
print(f"✅ latest : {LATEST_CSV}")

history_csv = os.path.join(HISTORY_DIR, f"sfd_investor_flow_{trade_date}.csv")
result.to_csv(history_csv, index=False, encoding="utf-8-sig")
print(f"✅ history: {history_csv}")

input_df = result[[
    "ticker", "foreign_net_buy", "foreign_net_value",
    "institution_net_buy", "institution_net_value",
    "individual_net_buy", "individual_net_value"
]].copy()
input_df.to_csv(INPUT_CSV, index=False, encoding="utf-8-sig")
print(f"✅ input  : {INPUT_CSV}")

# ================================================================
# 최종 결과
# ================================================================
ok      = len(result[result["data_status"] == "OK"])
no_flow = len(result[result["data_status"] == "NO_FLOW"])
no_data = len(result[result["data_status"] == "NO_DATA"])
runtime = round(time.time() - START_TIME, 2)

print(f"\n=========== SFD RESULT ===========")
print(f"Base trade date   : {trade_date}")
print(f"Total tickers     : {len(result)}")
print(f"OK            : {ok}")
print(f"NO_FLOW       : {no_flow}")
print(f"NO_DATA       : {no_data}")
print(f"Runtime           : {runtime} sec")
print(f"===================================\n")

logging.info(f"DONE | trade_date={trade_date} | total={len(result)} | ok={ok} | runtime={runtime}s")
