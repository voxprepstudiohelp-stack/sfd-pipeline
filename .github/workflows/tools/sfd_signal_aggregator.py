# 파일명: sfd_signal_aggregator.py
# 작성: Claude (Anthropic) — v1.3 (GitHub Actions 호환)
# 변경: D:\ 하드코딩 경로 → config.py 기반 /tmp/sfd 경로
# 파일위치(GitHub): sfd-pipeline/tools/sfd_signal_aggregator.py

import os
import sys
import time
import logging
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import FinanceDataReader as fdr

# ── config.py에서 경로 로드
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BASE, LATEST_DIR, HISTORY_DIR, INPUT_DIR

LATEST_CSV   = os.path.join(LATEST_DIR, "sfd_master_signal_latest.csv")
INPUT_CSV    = os.path.join(INPUT_DIR,  "sfd_master_signal_input.csv")
LOG_PATH     = os.path.join(LATEST_DIR, "sfd_signal_aggregator.log")

PREV_CLOSE_CSV = os.path.join(LATEST_DIR, "sfd_prev_close_latest.csv")
INVESTOR_CSV   = os.path.join(LATEST_DIR, "sfd_investor_flow_latest.csv")
NEWS_CSV       = os.path.join(LATEST_DIR, "sfd_news_signal_latest.csv")

os.makedirs(LATEST_DIR,  exist_ok=True)
os.makedirs(HISTORY_DIR, exist_ok=True)
os.makedirs(INPUT_DIR,   exist_ok=True)

logging.basicConfig(filename=LOG_PATH, level=logging.INFO,
                    format="%(asctime)s | %(levelname)s | %(message)s", encoding="utf-8")

START_TIME = time.time()
now        = datetime.now()
fetch_time = now.strftime("%Y-%m-%d %H:%M:%S")

RSI_PERIOD    = 14
MA_SHORT      = 5
MA_MID        = 20
MA_LONG       = 60
VOL_PERIOD    = 20
TOP_VALUE_PCT = 0.20

THRESHOLD_RESERVE = 30
THRESHOLD_WATCH   = 20
MODE = "TEMP"
# 수급 복원 후: THRESHOLD_RESERVE=70, THRESHOLD_WATCH=50, MODE="ORIGINAL"

def find_recent_trade_date():
    for i in range(7):
        d = now - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        d_str = d.strftime("%Y-%m-%d")
        try:
            df = fdr.DataReader("005930", d_str, d_str)
            if df is not None and len(df) > 0:
                return d.strftime("%Y%m%d")
        except:
            pass
    return now.strftime("%Y%m%d")

def calc_rsi(series, period=14):
    delta    = series.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period-1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period-1, min_periods=period).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def get_technical_data(ticker, end_date):
    try:
        end   = datetime.strptime(end_date, "%Y%m%d")
        start = (end - timedelta(days=120)).strftime("%Y-%m-%d")
        df    = fdr.DataReader(ticker, start, end.strftime("%Y-%m-%d"))
        if df is None or len(df) < MA_LONG:
            return None
        df = df.sort_index()
        df["rsi"]              = calc_rsi(df["Close"], RSI_PERIOD)
        df[f"ma{MA_SHORT}"]   = df["Close"].rolling(MA_SHORT).mean()
        df[f"ma{MA_MID}"]     = df["Close"].rolling(MA_MID).mean()
        df[f"ma{MA_LONG}"]    = df["Close"].rolling(MA_LONG).mean()
        df["vol_avg"]         = df["Volume"].rolling(VOL_PERIOD).mean()
        last = df.iloc[-1]
        return {
            "rsi":      round(last["rsi"], 2) if not pd.isna(last["rsi"]) else None,
            "ma_short": last[f"ma{MA_SHORT}"],
            "ma_mid":   last[f"ma{MA_MID}"],
            "ma_long":  last[f"ma{MA_LONG}"],
            "volume":   last["Volume"],
            "vol_avg":  last["vol_avg"],
        }
    except:
        return None

def build_news_score_map(news_df):
    score_map = {}
    if news_df is None or news_df.empty:
        return score_map
    for _, row in news_df.iterrows():
        stocks_raw = row.get("detected_stocks", "")
        importance = row.get("importance_score", 0)
        if pd.isna(stocks_raw) or str(stocks_raw).strip() == "":
            continue
        try:
            importance = float(importance)
        except:
            importance = 0
        news_pts = round(importance * 0.3, 1)
        for t in str(stocks_raw).split(";"):
            t = t.strip().zfill(6)
            if t not in score_map:
                score_map[t] = 0
            score_map[t] = min(30, score_map[t] + news_pts)
    return score_map

def score_rsi(rsi):
    if rsi is None: return 0
    if rsi < 30:    return 15
    if rsi < 50:    return 10
    if rsi < 70:    return 5
    return 0

def score_ma(ma_short, ma_mid, ma_long):
    if None in [ma_short, ma_mid, ma_long]: return 0
    if ma_short > ma_mid > ma_long:         return 15
    if ma_short > ma_mid:                   return 8
    if ma_short > ma_long:                  return 4
    return 0

def score_volume(volume, vol_avg):
    if not vol_avg or vol_avg == 0: return 0
    r = volume / vol_avg
    if r >= 2.0: return 10
    if r >= 1.5: return 7
    if r >= 1.0: return 4
    return 0

def score_investor(ticker, investor_df):
    if investor_df is None or investor_df.empty: return 0
    row = investor_df[investor_df["ticker"] == ticker]
    if row.empty: return 0
    try:
        f = float(row.iloc[0].get("foreign_net_buy", 0))
        i = float(row.iloc[0].get("institution_net_buy", 0))
        return (10 if f > 0 else 0) + (10 if i > 0 else 0)
    except:
        return 0

def classify_signal(total_score):
    if total_score >= THRESHOLD_RESERVE: return "RESERVE_BUY"
    if total_score >= THRESHOLD_WATCH:   return "WATCH_ONLY"
    return "HOLD"

# ── 데이터 로드
print("\n========== SFD Signal Aggregator v1.3 ==========")
print(f"모드: {MODE} | RESERVE≥{THRESHOLD_RESERVE} / WATCH≥{THRESHOLD_WATCH}")

if not os.path.exists(PREV_CLOSE_CSV):
    print(f"❌ prev_close CSV 없음: {PREV_CLOSE_CSV}")
    sys.exit(1)

prev_df     = pd.read_csv(PREV_CLOSE_CSV, dtype={"ticker": str})
investor_df = pd.read_csv(INVESTOR_CSV, dtype={"ticker": str}) if os.path.exists(INVESTOR_CSV) else None
news_df     = pd.read_csv(NEWS_CSV)                             if os.path.exists(NEWS_CSV)     else None

prev_df["ticker"] = prev_df["ticker"].astype(str).str.zfill(6)
tickers           = prev_df["ticker"].tolist()

news_score_map = build_news_score_map(news_df)
trade_date     = find_recent_trade_date()

# ── 거래대금 상위 20% 산출
value_threshold = 0
if "prev_value" in prev_df.columns:
    val_series      = pd.to_numeric(prev_df["prev_value"], errors="coerce").dropna()
    value_threshold = val_series.quantile(1 - TOP_VALUE_PCT) if len(val_series) > 0 else 0

print(f"총 종목: {len(tickers)} | 거래일: {trade_date}")

results = []
for idx, ticker in enumerate(tickers):
    if idx % 100 == 0:
        print(f"  진행: {idx}/{len(tickers)}")

    tech = get_technical_data(ticker, trade_date)

    rsi      = tech["rsi"]      if tech else None
    ma_short = tech["ma_short"] if tech else None
    ma_mid   = tech["ma_mid"]   if tech else None
    ma_long  = tech["ma_long"]  if tech else None
    volume   = tech["volume"]   if tech else None
    vol_avg  = tech["vol_avg"]  if tech else None

    tech_score     = score_rsi(rsi) + score_ma(ma_short, ma_mid, ma_long) + score_volume(volume, vol_avg)
    news_score     = round(news_score_map.get(ticker, 0), 1)
    investor_score = score_investor(ticker, investor_df)

    prev_row   = prev_df[prev_df["ticker"] == ticker]
    prev_value = float(prev_row["prev_value"].values[0]) if not prev_row.empty and "prev_value" in prev_row.columns and not pd.isna(prev_row["prev_value"].values[0]) else 0
    theme_score = 10 if (value_threshold > 0 and prev_value >= value_threshold) else 0

    total_score = tech_score + news_score + investor_score + theme_score
    signal      = classify_signal(total_score)

    ma_label = "정배열" if (ma_short and ma_mid and ma_long and ma_short > ma_mid > ma_long) else \
               "역배열" if (ma_short and ma_mid and ma_long and ma_short < ma_mid < ma_long) else "혼합"

    name = prev_row["name"].values[0] if not prev_row.empty and "name" in prev_row.columns else ""

    results.append({
        "ticker": ticker, "name": name,
        "signal": signal, "total_score": total_score,
        "tech_score": tech_score, "news_score": news_score,
        "investor_score": investor_score, "theme_score": theme_score,
        "rsi": rsi, "ma_alignment": ma_label,
        "vol_ratio": round(volume / vol_avg, 2) if (volume and vol_avg and vol_avg > 0) else None,
        "trade_date": trade_date, "generated_at": fetch_time, "mode": MODE
    })

result_df = pd.DataFrame(results)
result_df  = result_df.sort_values("total_score", ascending=False).reset_index(drop=True)

result_df.to_csv(LATEST_CSV, index=False, encoding="utf-8-sig")
print(f"✅ latest: {LATEST_CSV}")

history_file = os.path.join(HISTORY_DIR, f"sfd_master_signal_{trade_date}.csv")
result_df.to_csv(history_file, index=False, encoding="utf-8-sig")
print(f"✅ history: {history_file}")

input_df = result_df[result_df["signal"].isin(["RESERVE_BUY", "WATCH_ONLY"])][["ticker", "name", "signal", "total_score"]].copy()
input_df.to_csv(INPUT_CSV, index=False, encoding="utf-8-sig")
print(f"✅ input  : {INPUT_CSV}")

reserve = len(result_df[result_df["signal"] == "RESERVE_BUY"])
watch   = len(result_df[result_df["signal"] == "WATCH_ONLY"])
elapsed = round(time.time() - START_TIME)
print(f"\nRESERVE: {reserve} | WATCH: {watch} | 소요: {elapsed}초")
logging.info(f"완료 | RESERVE={reserve} | WATCH={watch} | 소요={elapsed}s | MODE={MODE}")
