# ============================================================
# 파일명: sfd_signal_aggregator.py
# 버전: v2.1
# 작성: Claude (Anthropic) — 2026-05-21
# GitHub 경로: voxprepstudiohelp-stack/sfd-pipeline/tools/sfd_signal_aggregator.py
#
# [v2.1 변경사항 — v1.3 대비]
# - NEWS_CSV: sfd_news_signal_latest.csv → sfd_news_score_latest.csv 로 변경
# - build_news_score_map() 복잡한 파싱 로직 제거
#   → load_news_score_map() 으로 교체: ticker/news_score 컬럼 직접 읽기
# - score_news() 함수: news_score_map dict 직접 조회로 단순화
# - 나머지 로직 v1.3과 동일 유지
# ============================================================

import os
import sys
import time
import logging
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import FinanceDataReader as fdr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BASE, LATEST_DIR, HISTORY_DIR, INPUT_DIR

LATEST_CSV     = os.path.join(LATEST_DIR, "sfd_master_signal_latest.csv")
INPUT_CSV      = os.path.join(INPUT_DIR,  "sfd_master_signal_input.csv")
LOG_PATH       = os.path.join(LATEST_DIR, "sfd_signal_aggregator.log")
PREV_CLOSE_CSV = os.path.join(LATEST_DIR, "sfd_prev_close_latest.csv")
INVESTOR_CSV   = os.path.join(LATEST_DIR, "sfd_investor_flow_latest.csv")
NEWS_SCORE_CSV = os.path.join(LATEST_DIR, "sfd_news_score_latest.csv")  # ★ v2.1 변경

os.makedirs(LATEST_DIR,  exist_ok=True)
os.makedirs(HISTORY_DIR, exist_ok=True)
os.makedirs(INPUT_DIR,   exist_ok=True)

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
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
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


def load_news_score_map() -> dict[str, float]:
    """
    ★ v2.1 신규: sfd_news_score_latest.csv → {ticker: news_score} dict
    (sfd_news_fetcher v2.0 출력 직접 소비)
    """
    if not os.path.exists(NEWS_SCORE_CSV):
        logging.warning(f"NEWS_SCORE_CSV 없음: {NEWS_SCORE_CSV}")
        return {}
    try:
        df = pd.read_csv(NEWS_SCORE_CSV, encoding="utf-8-sig", dtype={"ticker": str})
        if "ticker" not in df.columns or "news_score" not in df.columns:
            logging.warning(f"NEWS_SCORE_CSV 컬럼 오류: {df.columns.tolist()}")
            return {}
        score_map = dict(
            zip(
                df["ticker"].str.strip().str.zfill(6),
                pd.to_numeric(df["news_score"], errors="coerce").fillna(0),
            )
        )
        logging.info(f"뉴스점수 로드: {len(score_map)}종목")
        return score_map
    except Exception as e:
        logging.error(f"뉴스점수 로드 오류: {e}")
        return {}


def score_rsi(rsi):
    if rsi is None: return 0
    if rsi < 30:    return 15
    if rsi < 50:    return 10
    if rsi < 70:    return 5
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


def score_news(ticker: str, news_score_map: dict) -> float:
    """★ v2.1: dict 직접 조회 (파싱 로직 제거)"""
    return min(float(news_score_map.get(str(ticker).zfill(6), 0)), 30)


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
    logging.info("=== sfd_signal_aggregator v2.1 시작 ===")

    trade_date = find_recent_trade_date()
    logging.info(f"기준 거래일: {trade_date}")

    if not os.path.exists(INPUT_CSV):
        logging.error(f"INPUT_CSV 없음: {INPUT_CSV}")
        return
    if not os.path.exists(PREV_CLOSE_CSV):
        logging.error(f"PREV_CLOSE_CSV 없음: {PREV_CLOSE_CSV}")
        return

    input_df    = pd.read_csv(INPUT_CSV,      encoding="utf-8-sig", dtype={"ticker": str})
    prev_df     = pd.read_csv(PREV_CLOSE_CSV, encoding="utf-8-sig", dtype={"ticker": str})
    investor_df = pd.read_csv(INVESTOR_CSV,   encoding="utf-8-sig", dtype={"ticker": str}) \
                  if os.path.exists(INVESTOR_CSV) else None

    news_score_map = load_news_score_map()  # ★ v2.1

    if "prev_value" in prev_df.columns:
        prev_df["prev_value"] = pd.to_numeric(prev_df["prev_value"], errors="coerce").fillna(0)

    tickers = input_df["ticker"].dropna().astype(str).str.zfill(6).unique().tolist()
    logging.info(f"처리 대상 종목: {len(tickers)}개")

    results = []
    for ticker in tickers:
        tech = get_technical_data(ticker, trade_date)
        if tech is None:
            continue

        t_score  = score_rsi(tech["rsi"]) + score_ma(tech["ma_short"], tech["ma_mid"], tech["ma_long"]) + score_volume(tech["volume"], tech["vol_avg"])
        n_score  = score_news(ticker, news_score_map)
        i_score  = score_investor(ticker, investor_df)
        th_score = score_theme(ticker, prev_df)
        total    = t_score + n_score + i_score + th_score
        signal   = classify_signal(total)

        name_row = input_df[input_df["ticker"] == ticker]
        name     = name_row.iloc[0].get("name", "") if not name_row.empty else ""

        results.append({
            "fetch_date": trade_date, "fetch_time": fetch_time,
            "ticker": ticker, "name": name, "signal": signal,
            "total_score": total, "tech_score": t_score,
            "news_score": round(n_score, 2), "investor_score": i_score,
            "theme_score": th_score, "rsi": tech["rsi"],
            "ma_align": "정배열" if tech["ma_short"] and tech["ma_mid"] and tech["ma_long"]
                        and tech["ma_short"] > tech["ma_mid"] > tech["ma_long"] else "비정배열",
            "vol_ratio": round(tech["volume"] / tech["vol_avg"], 2)
                         if tech["vol_avg"] and tech["vol_avg"] > 0 else 0,
            "mode": MODE,
        })

    df_out = pd.DataFrame(results)
    df_out = df_out.sort_values("total_score", ascending=False).reset_index(drop=True)
    df_out.to_csv(LATEST_CSV, index=False, encoding="utf-8-sig")

    history_path = os.path.join(HISTORY_DIR, f"sfd_master_signal_{trade_date}.csv")
    df_out.to_csv(history_path, index=False, encoding="utf-8-sig")

    elapsed = int(time.time() - START_TIME)
    reserve = len(df_out[df_out["signal"] == "RESERVE_BUY"])
    watch   = len(df_out[df_out["signal"] == "WATCH_ONLY"])

    logging.info(f"완료 | RESERVE={reserve} | WATCH={watch} | 소요={elapsed}s | MODE={MODE}")
    print(f"[OK] RESERVE={reserve} | WATCH={watch} | 소요={elapsed}s | MODE={MODE}")
    print(f"     -> {LATEST_CSV}")


if __name__ == "__main__":
    main()
