# sfd_backtest_d1.py v1.0 - D+1 사후검증
# GitHub 저장경로: sfd-pipeline/tools/sfd_backtest_d1.py

import os, sys, time, glob, logging
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import LATEST_DIR, HISTORY_DIR, INPUT_DIR

VERIFY_DIR = os.path.join(HISTORY_DIR, "backtest")
LOG_PATH   = os.path.join(LATEST_DIR,  "sfd_backtest_d1.log")
os.makedirs(VERIFY_DIR, exist_ok=True)

logging.basicConfig(filename=LOG_PATH, level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s", encoding="utf-8")

START_TIME = time.time()
now        = datetime.now()
print(f"\n========== SFD D+1 사후검증 v1.0 ==========")
print(f"실행 시각: {now.strftime('%Y-%m-%d %H:%M:%S')}")

def find_yesterday_signal():
    files = sorted(glob.glob(os.path.join(HISTORY_DIR, "sfd_master_signal_*.csv")))
    today_str = now.strftime("%Y%m%d")
    candidates = [f for f in files if today_str not in f]
    if not candidates:
        return None, None
    latest = candidates[-1]
    date_str = os.path.basename(latest).replace("sfd_master_signal_","").replace(".csv","")
    return latest, date_str

signal_file, signal_date = find_yesterday_signal()

if signal_file is None:
    print("검증할 이전 신호 파일 없음 - 건너뜀")
    sys.exit(0)

print(f"검증 대상 신호일: {signal_date}")
signal_df = pd.read_csv(signal_file, dtype={"ticker": str})
signal_df["ticker"] = signal_df["ticker"].astype(str).str.zfill(6)

target_df = signal_df[signal_df["signal"].isin(["RESERVE_BUY", "WATCH_ONLY"])].copy()
print(f"검증 종목수: {len(target_df)}")

if target_df.empty:
    print("검증 종목 없음 - 건너뜀")
    sys.exit(0)

prev_file = os.path.join(HISTORY_DIR, f"sfd_prev_close_{signal_date}.csv")
if not os.path.exists(prev_file):
    prev_file = os.path.join(LATEST_DIR, "sfd_prev_close_latest.csv")

prev_df = pd.read_csv(prev_file, dtype={"ticker": str})
prev_df["ticker"] = prev_df["ticker"].astype(str).str.zfill(6)
prev_map = dict(zip(prev_df["ticker"], pd.to_numeric(prev_df["prev_close"], errors="coerce")))

def get_next_day_close(tickers_raw, market_suffix):
    close_map = {}
    if not tickers_raw:
        return close_map
    yf_tickers = [f"{t}{market_suffix}" for t in tickers_raw]
    start = (now - timedelta(days=5)).strftime("%Y-%m-%d")
    end   = now.strftime("%Y-%m-%d")
    try:
        data = yf.download(yf_tickers, start=start, end=end,
                           auto_adjust=True, progress=False, threads=True)
        if data.empty:
            return close_map
        if isinstance(data.columns, pd.MultiIndex):
            close_data = data["Close"]
        else:
            close_data = data[["Close"]].rename(columns={"Close": yf_tickers[0]})
        signal_dt = pd.to_datetime(signal_date, format="%Y%m%d")
        after = close_data[close_data.index > signal_dt]
        if after.empty:
            return close_map
        next_row  = after.iloc[0]
        next_date = after.index[0].strftime("%Y%m%d")
        for yf_t, raw_t in zip(yf_tickers, tickers_raw):
            val = next_row.get(yf_t) if hasattr(next_row, "get") else None
            if val is not None and not pd.isna(val):
                close_map[raw_t] = {"close": float(val), "date": next_date}
    except Exception as e:
        print(f"  yfinance 오류: {e}")
    return close_map

if "market" in signal_df.columns:
    ks_tickers = target_df[target_df["ticker"].isin(
        signal_df[signal_df["market"]=="KOSPI"]["ticker"])]["ticker"].tolist()
    kq_tickers = target_df[~target_df["ticker"].isin(ks_tickers)]["ticker"].tolist()
else:
    ks_tickers = target_df["ticker"].tolist()
    kq_tickers = []

print("\nD+1 종가 수집 중...")
next_map = {}
next_map.update(get_next_day_close(ks_tickers, ".KS"))
next_map.update(get_next_day_close(kq_tickers, ".KQ"))
print(f"D+1 종가 수집 완료: {len(next_map)}종목")

results = []
for _, row in target_df.iterrows():
    ticker   = row["ticker"]
    name     = row.get("name", "")
    signal   = row["signal"]
    score    = row.get("total_score", 0)
    d_close  = prev_map.get(ticker)
    d1_data  = next_map.get(ticker, {})
    d1_close = d1_data.get("close")
    d1_date  = d1_data.get("date", "")

    if d_close and d1_close and d_close > 0:
        chg_pct = round((d1_close - d_close) / d_close * 100, 2)
        hit     = "HIT"  if chg_pct > 0   else "MISS"
        hit_1   = "HIT"  if chg_pct >= 1.0 else "MISS"
        hit_2   = "HIT"  if chg_pct >= 2.0 else "MISS"
    else:
        chg_pct = None
        hit = hit_1 = hit_2 = "N/A"

    results.append({
        "signal_date": signal_date, "verify_date": d1_date,
        "ticker": ticker, "name": name, "signal": signal, "total_score": score,
        "d_close": d_close, "d1_close": d1_close, "chg_pct": chg_pct,
        "hit_0pct": hit, "hit_1pct": hit_1, "hit_2pct": hit_2,
    })

result_df = pd.DataFrame(results)

print("\n===== 적중률 요약 =====")
for sig in ["RESERVE_BUY", "WATCH_ONLY"]:
    sub = result_df[(result_df["signal"]==sig) & (result_df["hit_0pct"]!="N/A")]
    if sub.empty:
        continue
    h0  = round(len(sub[sub["hit_0pct"]=="HIT"]) / len(sub) * 100, 1)
    h1  = round(len(sub[sub["hit_1pct"]=="HIT"]) / len(sub) * 100, 1)
    h2  = round(len(sub[sub["hit_2pct"]=="HIT"]) / len(sub) * 100, 1)
    avg = round(sub["chg_pct"].mean(), 2)
    print(f"  {sig}: {len(sub)}종목 | 상승적중 {h0}% | 1%+ {h1}% | 2%+ {h2}% | 평균수익 {avg}%")
    logging.info(f"{sig}: n={len(sub)} hit0={h0}% hit1={h1}% hit2={h2}% avg={avg}%")

out_file = os.path.join(VERIFY_DIR, f"sfd_backtest_d1_{signal_date}.csv")
result_df.to_csv(out_file, index=False, encoding="utf-8-sig")
print(f"\n 검증 결과: {out_file}")

elapsed = round(time.time() - START_TIME)
print(f"소요: {elapsed}초")
logging.info(f"완료 | 소요={elapsed}s")
