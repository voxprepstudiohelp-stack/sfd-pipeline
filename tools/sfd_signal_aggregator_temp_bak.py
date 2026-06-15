# sfd_signal_aggregator.py | v2.2 | Claude (Anthropic) 2026-05-23 hotfix
# Deploy to: D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline\tools\sfd_signal_aggregator.py
#
# [v2.2 hotfix] config.py dependency removed
# - config.BASE = "/tmp/sfd" is GitHub Actions path, breaks on local Windows
# - Replaced with __file__-based path detection (same pattern as sfd_fundamental_watch.py)
# - All path logic now self-contained, no external config required
#
# [v2.2 original changes]
# - FUNDAMENTAL_CSV: sfd_fundamental_latest.csv
# - FUND_MAX_PT = 15
# - load_fund_score_map() + score_fundamental()
# - "fund_score" column added to output

import os
import sys
import time
import logging
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import FinanceDataReader as fdr

# ── 경로 설정 (__file__ 기반, config.py 불필요)
# tools/sfd_signal_aggregator.py -> SFC_DataPipeline root
BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LATEST_DIR   = os.path.join(BASE_DIR, "outputs", "latest")
HISTORY_DIR  = os.path.join(BASE_DIR, "outputs", "history")
INPUT_DIR    = os.path.join(BASE_DIR, "inputs")

os.makedirs(LATEST_DIR,  exist_ok=True)
os.makedirs(HISTORY_DIR, exist_ok=True)
os.makedirs(INPUT_DIR,   exist_ok=True)

LATEST_CSV      = os.path.join(LATEST_DIR, "sfd_master_signal_latest.csv")
INPUT_CSV       = os.path.join(INPUT_DIR,  "sfd_master_signal_input.csv")
LOG_PATH        = os.path.join(LATEST_DIR, "sfd_signal_aggregator.log")
PREV_CLOSE_CSV  = os.path.join(LATEST_DIR, "sfd_prev_close_latest.csv")
INVESTOR_CSV    = os.path.join(LATEST_DIR, "sfd_investor_flow_latest.csv")
NEWS_SCORE_CSV  = os.path.join(LATEST_DIR, "sfd_news_score_latest.csv")
FUNDAMENTAL_CSV = os.path.join(LATEST_DIR, "sfd_fundamental_latest.csv")

logging.basicConfig(
    filename=LOG_PATH, level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s", encoding="utf-8",
)

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
# After investor data restored: THRESHOLD_RESERVE=70, THRESHOLD_WATCH=50, MODE="ORIGINAL"

FUND_MAX_PT = 15


def find_recent_trade_date():
    for i in range(7):
        d = now - timedelta(days=i)
        if d.weekday() >= 5: continue
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
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def get_technical_data(ticker, end_date):
    try:
        end   = datetime.strptime(end_date, "%Y%m%d")
        start = (end - timedelta(days=120)).strftime("%Y-%m-%d")
        df    = fdr.DataReader(ticker, start, end.strftime("%Y-%m-%d"))
        if df is None or len(df) < MA_LONG: return None
        df = df.sort_index()
        df["rsi"]           = calc_rsi(df["Close"], RSI_PERIOD)
        df[f"ma{MA_SHORT}"] = df["Close"].rolling(MA_SHORT).mean()
        df[f"ma{MA_MID}"]   = df["Close"].rolling(MA_MID).mean()
        df[f"ma{MA_LONG}"]  = df["Close"].rolling(MA_LONG).mean()
        df["vol_avg"]       = df["Volume"].rolling(VOL_PERIOD).mean()
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


def load_news_score_map() -> dict:
    if not os.path.exists(NEWS_SCORE_CSV):
        logging.warning(f"NEWS_SCORE_CSV not found: {NEWS_SCORE_CSV}")
        return {}
    try:
        df = pd.read_csv(NEWS_SCORE_CSV, encoding="utf-8-sig", dtype={"ticker": str})
        if "ticker" not in df.columns or "news_score" not in df.columns:
            logging.warning(f"NEWS_SCORE_CSV missing columns: {df.columns.tolist()}")
            return {}
        score_map = dict(zip(
            df["ticker"].str.strip().str.zfill(6),
            pd.to_numeric(df["news_score"], errors="coerce").fillna(0)
        ))
        logging.info(f"news_score_map loaded: {len(score_map)}")
        return score_map
    except Exception as e:
        logging.error(f"news_score_map load failed: {e}"); return {}


def load_fund_score_map() -> dict:
    if not os.path.exists(FUNDAMENTAL_CSV):
        logging.warning(f"FUNDAMENTAL_CSV not found: {FUNDAMENTAL_CSV}")
        return {}
    try:
        df = pd.read_csv(FUNDAMENTAL_CSV, encoding="utf-8-sig", dtype={"ticker": str})
        if "ticker" not in df.columns or "adjusted_fund_score" not in df.columns:
            logging.warning(f"FUNDAMENTAL_CSV missing columns: {df.columns.tolist()}")
            return {}
        df["ticker"] = df["ticker"].str.strip().str.zfill(6)
        df["_norm"] = (
            pd.to_numeric(df["adjusted_fund_score"], errors="coerce")
            .fillna(0).clip(upper=100).div(100).mul(FUND_MAX_PT).round(2)
        )
        fund_map = dict(zip(df["ticker"], df["_norm"]))
        logging.info(f"fund_score_map loaded: {len(fund_map)}")
        return fund_map
    except Exception as e:
        logging.error(f"fund_score_map load failed: {e}"); return {}


def score_rsi(rsi):
    if rsi is None: return 0
    if rsi < 30: return 15
    if rsi < 50: return 10
    if rsi < 70: return 5
    return 0

def score_ma(ma_short, ma_mid, ma_long):
    if None in [ma_short, ma_mid, ma_long]: return 0
    if ma_short > ma_mid > ma_long: return 15
    if ma_short > ma_mid:           return 8
    if ma_short > ma_long:          return 4
    return 0

def score_volume(volume, vol_avg):
    if not vol_avg or vol_avg == 0: return 0
    r = volume / vol_avg
    if r >= 2.0: return 10
    if r >= 1.5: return 7
    if r >= 1.0: return 4
    return 0

def score_news(ticker, news_score_map):
    return min(float(news_score_map.get(str(ticker).zfill(6), 0)), 30)

def score_fundamental(ticker, fund_map):
    return float(fund_map.get(str(ticker).zfill(6), 0))

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

def score_theme(ticker, prev_df):
    if prev_df is None or "prev_value" not in prev_df.columns: return 0
    try:
        threshold = prev_df["prev_value"].quantile(1 - TOP_VALUE_PCT)
        row = prev_df[prev_df["ticker"] == ticker]
        if row.empty: return 0
        return 10 if float(row.iloc[0]["prev_value"]) >= threshold else 0
    except:
        return 0

def classify_signal(total_score):
    if total_score >= THRESHOLD_RESERVE: return "RESERVE_BUY"
    if total_score >= THRESHOLD_WATCH:   return "WATCH_ONLY"
    return "HOLD"


def main():
    logging.info("=== sfd_signal_aggregator v2.2 START ===")
    logging.info(f"BASE_DIR:   {BASE_DIR}")
    logging.info(f"LATEST_DIR: {LATEST_DIR}")

    trade_date = find_recent_trade_date()
    logging.info(f"trade_date: {trade_date}")

    if not os.path.exists(INPUT_CSV):
        logging.error(f"INPUT_CSV not found: {INPUT_CSV}"); return
    if not os.path.exists(PREV_CLOSE_CSV):
        logging.error(f"PREV_CLOSE_CSV not found: {PREV_CLOSE_CSV}"); return

    input_df    = pd.read_csv(INPUT_CSV,      encoding="utf-8-sig", dtype={"ticker": str})
    prev_df     = pd.read_csv(PREV_CLOSE_CSV, encoding="utf-8-sig", dtype={"ticker": str})
    investor_df = pd.read_csv(INVESTOR_CSV,   encoding="utf-8-sig", dtype={"ticker": str}) \
                  if os.path.exists(INVESTOR_CSV) else None

    news_score_map = load_news_score_map()
    fund_map       = load_fund_score_map()

    if "prev_value" in prev_df.columns:
        prev_df["prev_value"] = pd.to_numeric(prev_df["prev_value"], errors="coerce").fillna(0)

    tickers = input_df["ticker"].dropna().astype(str).str.zfill(6).unique().tolist()
    logging.info(f"tickers: {len(tickers)}")

    results = []
    for ticker in tickers:
        tech = get_technical_data(ticker, trade_date)
        if tech is None: continue

        t_score  = score_rsi(tech["rsi"]) + score_ma(tech["ma_short"], tech["ma_mid"], tech["ma_long"]) + score_volume(tech["volume"], tech["vol_avg"])
        n_score  = score_news(ticker, news_score_map)
        i_score  = score_investor(ticker, investor_df)
        th_score = score_theme(ticker, prev_df)
        f_score  = score_fundamental(ticker, fund_map)
        total    = t_score + n_score + i_score + th_score + f_score
        signal   = classify_signal(total)

        name_row = input_df[input_df["ticker"] == ticker]
        name     = name_row.iloc[0].get("name", "") if not name_row.empty else ""

        results.append({
            "fetch_date": trade_date, "fetch_time": fetch_time,
            "ticker": ticker, "name": name, "signal": signal,
            "total_score": total, "tech_score": t_score,
            "news_score": round(n_score, 2), "investor_score": i_score,
            "theme_score": th_score,
            "fund_score": round(f_score, 2),
            "rsi": tech["rsi"],
            "ma_align": "up" if tech["ma_short"] and tech["ma_mid"] and tech["ma_long"]
                              and tech["ma_short"] > tech["ma_mid"] > tech["ma_long"] else "down",
            "vol_ratio": round(tech["volume"] / tech["vol_avg"], 2)
                         if tech["vol_avg"] and tech["vol_avg"] > 0 else 0,
            "mode": MODE,
        })

    df_out = pd.DataFrame(results).sort_values("total_score", ascending=False).reset_index(drop=True)
    df_out.to_csv(LATEST_CSV, index=False, encoding="utf-8-sig")
    df_out.to_csv(os.path.join(HISTORY_DIR, f"sfd_master_signal_{trade_date}.csv"), index=False, encoding="utf-8-sig")

    elapsed = int(time.time() - START_TIME)
    reserve = len(df_out[df_out["signal"] == "RESERVE_BUY"])
    watch   = len(df_out[df_out["signal"] == "WATCH_ONLY"])
    logging.info(f"DONE | RESERVE={reserve} WATCH={watch} elapsed={elapsed}s MODE={MODE}")
    print(f"[OK] RESERVE={reserve} | WATCH={watch} | elapsed={elapsed}s | MODE={MODE}")
    print(f"     -> {LATEST_CSV}")


if __name__ == "__main__":
    main()
