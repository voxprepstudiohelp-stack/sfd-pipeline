# -*- coding: utf-8 -*-
# sfd_signal_aggregator.py | v4.0 | Claude (Anthropic) 2026-06-15
# Deploy to: sfd-pipeline/tools/sfd_signal_aggregator.py
#
# [v3.9 -> v4.0 changes]
# - [TREND] load_trend_filter_map(): sfd_trend_filter_latest.csv 로드 (없으면 {} graceful)
# - [TREND] apply_trend_filter(): FAIL이면 RESERVE_BUY/WATCH_ONLY → TREND_FAIL 다운그레이드
# - trend_filter_pass, trend_filter_reason 컬럼 출력
# - DONE 로그에 TREND_FAIL 카운터 추가
#
# [v3.8 -> v3.9 changes]
# - [BM-19] score_investor(): 외국인+기관+연기금 3주체 동시 순매수 보너스 +15pt
#   -> investor_score 최대: +20pt → +35pt
#      (foreign +10 / institution +10 / BM-19 bonus +15)
#   -> pension_net_buy 컬럼 없으면 보너스 0pt (하위호환)
#
# [v3.7 -> v3.8 changes]
# - [FIX-A] FUNDAMENTAL_CSV: sfd_fundamental_watch_latest.csv (primary)
#           + sfd_fundamental_latest.csv (fallback) auto-detect
#   -> matches fundamental_watch.py v1.6 output filename
# - [FIX-B] score_investor(): auto-detect stock_code/ticker column
#   -> fix KIS API v2.1 output(stock_code) vs aggregator join mismatch
#
# [v3.5 features preserved as-is]
# - tech_total_score column name auto-detect
# - BM-13 Signal Timeout State Machine
# - BM-12 zone_pullback_score
# - BM-10 vol_surge_score
# - BM-5  no_trade override
# - BM-3  bias_filter_score
# - [FIX-1] news: sfd_news_score_latest.csv
# - [FIX-4] investor: direct foreign_net_buy/institution_net_buy calc
#           -> v3.9: pension_net_buy 추가 (pnsn_ntby_qty)
# - [FIX-5] theme: graceful handling
#
# 점수 아키텍처 (주요 구성요소 최대치)
# ─────────────────────────────────────────────────────
#  tech_score       최대  +30pt  (MA배열 +15 / 거래량 +10 / RSI +5)
#  news_score       최대  +30pt
#  fundamental_score 최대 +20pt
#  investor_score   최대  +35pt  (외국인 +10 / 기관 +10 / [BM-19] 연기금 동시 +15)
#  theme_score      최대  +20pt
#  BM-10 vol_surge  최대  +15pt
#  BM-12 pullback   최대  +10pt
#  BM-18 alpha_decay 최대 +10pt
# ─────────────────────────────────────────────────────

import os
import sys
import json
import time
import logging
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import FinanceDataReader as fdr

# -- Path config --────────────────────────────────────────────────────────────────
_env_base = os.environ.get("SFD_BASE_DIR", "")
if _env_base and os.path.isdir(_env_base):
    BASE_DIR = _env_base
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LATEST_DIR  = os.path.join(BASE_DIR, "outputs", "latest")
HISTORY_DIR = os.path.join(BASE_DIR, "outputs", "history")
INPUT_DIR   = os.path.join(BASE_DIR, "inputs")

os.makedirs(LATEST_DIR,  exist_ok=True)
os.makedirs(HISTORY_DIR, exist_ok=True)
os.makedirs(INPUT_DIR,   exist_ok=True)

LATEST_CSV          = os.path.join(LATEST_DIR, "sfd_master_signal_latest.csv")
INPUT_CSV           = os.path.join(INPUT_DIR,  "sfd_master_signal_input.csv")
LOG_PATH            = os.path.join(LATEST_DIR, "sfd_signal_aggregator.log")
PREV_CLOSE_CSV      = os.path.join(LATEST_DIR, "sfd_prev_close_latest.csv")
INVESTOR_CSV        = os.path.join(LATEST_DIR, "sfd_investor_flow_latest.csv")
# [FIX-1] news filename
NEWS_SCORE_CSV      = os.path.join(LATEST_DIR, "sfd_news_score_latest.csv")
# [FIX-A] fundamental: watch version primary, legacy fallback
FUNDAMENTAL_CSV_PRIMARY  = os.path.join(LATEST_DIR, "sfd_fundamental_watch_latest.csv")
FUNDAMENTAL_CSV_FALLBACK = os.path.join(LATEST_DIR, "sfd_fundamental_latest.csv")
TECH_DETAIL_CSV     = os.path.join(LATEST_DIR, "sfd_technical_latest.csv")
NO_TRADE_JSON       = os.path.join(LATEST_DIR, "sfd_no_trade_tickers.json")
ZONE_PULLBACK_CSV   = os.path.join(LATEST_DIR, "sfd_zone_pullback_latest.csv")
TIMEOUT_STATE_JSON  = os.path.join(LATEST_DIR, "signal_timeout_state.json")
ALPHA_DECAY_CSV     = os.path.join(LATEST_DIR, "bm18_alpha_decay.csv")  # [BM-18]
TREND_FILTER_CSV    = os.path.join(LATEST_DIR, "sfd_trend_filter_latest.csv")

logging.basicConfig(
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

START_TIME = time.time()
now        = datetime.now()
fetch_time = now.strftime("%Y-%m-%d %H:%M:%S")

# -- Parameters --─────────────────────────────────────────────────────────────────
RSI_PERIOD       = 14
MA_SHORT         = 5
MA_MID           = 20
MA_LONG          = 60
VOL_PERIOD       = 20
TOP_VALUE_PCT    = 0.20
FUND_MAX_PT      = 15

THRESHOLD_RESERVE = 90
THRESHOLD_WATCH   = 70
MODE = "ORIGINAL"

# [BM-3] Bias Filter
BIAS_UPPER_PCT = 1.05
BIAS_LOWER_PCT = 0.95
BIAS_UPPER_PT  = 5
BIAS_LOWER_PT  = -5

# [BM-13] Signal Timeout
TIMEOUT_BARS    = 5
TIMEOUT_SIGNALS = {"RESERVE_BUY", "WATCH_ONLY"}


# -- Find recent trade date --────────────────────────────────────────────────────────
def find_recent_trade_date():
    for i in range(7):
        d = now - timedelta(days=i)
        if d.weekday() >= 5: continue
        d_str = d.strftime("%Y-%m-%d")
        try:
            df = fdr.DataReader("005930", d_str, d_str)
            if df is not None and len(df) > 0:
                return d.strftime("%Y%m%d")
        except: pass
    return now.strftime("%Y%m%d")


# -- v2.2 fallback technical calc --─────────────────────────────────────────────────
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
        df["rsi"]          = calc_rsi(df["Close"], RSI_PERIOD)
        df[f"ma{MA_SHORT}"] = df["Close"].rolling(MA_SHORT).mean()
        df[f"ma{MA_MID}"]   = df["Close"].rolling(MA_MID).mean()
        df[f"ma{MA_LONG}"]  = df["Close"].rolling(MA_LONG).mean()
        df["vol_avg"]       = df["Volume"].rolling(VOL_PERIOD).mean()
        last = df.iloc[-1]
        return {
            "rsi":       round(last["rsi"], 2) if not pd.isna(last["rsi"]) else None,
            "ma_short":  last[f"ma{MA_SHORT}"],
            "ma_mid":    last[f"ma{MA_MID}"],
            "ma_long":   last[f"ma{MA_LONG}"],
            "volume":    last["Volume"],
            "vol_avg":   last["vol_avg"],
            "close":     last["Close"],
        }
    except: return None


# -- Score functions --──────────────────────────────────────────────────────────────
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
    """
    [FIX-B] auto-detect stock_code/ticker column name
    - KIS API v2.1 output: stock_code column
    - legacy version: ticker column
    - foreign_net_buy > 0:     +10pt
    - institution_net_buy > 0: +10pt
    - [BM-19] foreign_net_buy > 0 AND institution_net_buy > 0
              AND pension_net_buy > 0: +15pt 보너스 (최대 +35pt)
    - pension_net_buy 컬럼 없으면 보너스 0pt (하위호환)
    - data_status==ZERO/FAIL: 0pt
    """
    if investor_df is None or investor_df.empty: return 0
    # [FIX-B] column name auto-detect
    _icol = next((c for c in ["ticker", "stock_code"] if c in investor_df.columns), None)
    if _icol is None: return 0
    row = investor_df[investor_df[_icol] == ticker]
    if row.empty:
        # try zfill
        row = investor_df[investor_df[_icol] == str(ticker).zfill(6)]
    if row.empty: return 0
    try:
        status = str(row.iloc[0].get("data_status", "OK")).upper()
        if status in ("ZERO", "FAIL"): return 0
        f = float(row.iloc[0].get("foreign_net_buy", 0))
        i = float(row.iloc[0].get("institution_net_buy", 0))
        score = (10 if f > 0 else 0) + (10 if i > 0 else 0)
        # [BM-19] 외국인 + 기관 + 연기금 동시 순매수 보너스
        if "pension_net_buy" in investor_df.columns:
            pension = float(row.iloc[0].get("pension_net_buy", 0))
            if f > 0 and i > 0 and pension > 0:
                score += 15
        return score
    except: return 0

def score_theme(ticker, prev_df):
    if prev_df is None or "prev_value" not in prev_df.columns: return 0
    try:
        threshold = prev_df["prev_value"].quantile(1 - TOP_VALUE_PCT)
        row = prev_df[prev_df["ticker"] == ticker]
        if row.empty: return 0
        return 10 if float(row.iloc[0]["prev_value"]) >= threshold else 0
    except: return 0

def classify_signal(total_score):
    if total_score >= THRESHOLD_RESERVE: return "RESERVE_BUY"
    if total_score >= THRESHOLD_WATCH:   return "WATCH_ONLY"
    return "HOLD"


# -- [BM-3] Bias Filter --────────────────────────────────────────────────────
def calc_bias_filter(close, ma20, ma60):
    try:
        if pd.isna(ma20) or pd.isna(ma60) or ma20 <= 0 or ma60 <= 0:
            return 0, 0.0, 0.0
        waist = (ma20 + ma60) / 2
        pct   = round((close - waist) / waist * 100, 2)
        if close > waist * BIAS_UPPER_PCT:
            return BIAS_UPPER_PT, round(waist, 2), pct
        elif close < waist * BIAS_LOWER_PCT:
            return BIAS_LOWER_PT, round(waist, 2), pct
        else:
            return 0, round(waist, 2), pct
    except:
        return 0, 0.0, 0.0


# -- [BM-5] load no_trade_set --───────────────────────────────────────────────
def load_no_trade_set() -> set:
    if not os.path.exists(NO_TRADE_JSON):
        logging.info(f"[BM-5] no_trade JSON not found: {NO_TRADE_JSON}")
        return set()
    try:
        with open(NO_TRADE_JSON, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            tickers = data
        elif isinstance(data, dict):
            tickers = data.get("no_trade_tickers", data.get("tickers", []))
        else:
            tickers = []
        result = {str(t).strip().zfill(6) for t in tickers if t}
        logging.info(f"[BM-5] no_trade_set: {len(result)}rows")
        return result
    except Exception as e:
        logging.warning(f"[BM-5] no_trade JSON load failed: {e}")
        return set()


# -- [BM-12] load zone_pullback_map --────────────────────────────────────────
def load_zone_pullback_map() -> dict:
    if not os.path.exists(ZONE_PULLBACK_CSV):
        logging.info(f"[BM-12] zone_pullback CSV not found: {ZONE_PULLBACK_CSV}")
        return {}
    try:
        df = pd.read_csv(ZONE_PULLBACK_CSV, encoding="utf-8-sig", dtype={"ticker": str})
        if "ticker" not in df.columns or "zone_pullback_score" not in df.columns:
            return {}
        df["ticker"] = df["ticker"].str.strip().str.zfill(6)
        result = {}
        for _, row in df.iterrows():
            t = str(row["ticker"])
            result[t] = {
                "zone_pullback_score": float(row.get("zone_pullback_score", 0) or 0),
                "zone_pullback_label": str(row.get("zone_pullback_label", "") or ""),
            }
        logging.info(f"[BM-12] zone_pullback_map: {len(result)}rows")
        return result
    except Exception as e:
        logging.warning(f"[BM-12] zone_pullback_map load failed: {e}")
        return {}


# -- [BM-18] Alpha Decay --────────────────────────────────────────────────────
def load_decay_score_map() -> dict:
    if not os.path.exists(ALPHA_DECAY_CSV):
        logging.info("[BM-18] bm18_alpha_decay.csv 없음 → 전체 0점 처리")
        return {}
    try:
        df = pd.read_csv(ALPHA_DECAY_CSV, dtype={"stock_code": str})
        result = {}
        for _, row in df.iterrows():
            result[str(row["stock_code"])] = {
                "decay_score":  float(row.get("decay_score", 0) or 0),
                "decay_flag":   str(row.get("decay_flag", "FRESH")),
                "bars_elapsed": int(row.get("bars_elapsed", 0) or 0),
            }
        logging.info(f"[BM-18] decay_map: {len(result)}종목")
        return result
    except Exception as e:
        logging.warning(f"[BM-18] decay_map 로드 실패: {e}")
        return {}


# -- [TREND] Trend Filter --──────────────────────────────────────────────────
def load_trend_filter_map() -> dict:
    if not os.path.exists(TREND_FILTER_CSV):
        logging.info(f"[TREND] trend_filter CSV not found: {TREND_FILTER_CSV} → 전체 PASS")
        return {}
    try:
        df = pd.read_csv(TREND_FILTER_CSV, encoding="utf-8-sig", dtype={"ticker": str})
        if "ticker" not in df.columns:
            logging.warning(f"[TREND] ticker column missing in trend_filter CSV")
            return {}
        df["ticker"] = df["ticker"].str.strip().str.zfill(6)
        result = {}
        for _, row in df.iterrows():
            result[str(row["ticker"])] = {
                "trend_filter":        str(row.get("trend_filter",        "PASS")),
                "trend_filter_reason": str(row.get("trend_filter_reason", "")),
            }
        fail_ct = sum(1 for v in result.values() if v["trend_filter"].upper() == "FAIL")
        logging.info(f"[TREND] trend_filter_map: {len(result)}rows | FAIL={fail_ct}")
        return result
    except Exception as e:
        logging.warning(f"[TREND] trend_filter_map load failed: {e}")
        return {}


def apply_trend_filter(ticker: str, signal: str, trend_filter_map: dict) -> tuple:
    """FAIL이면 RESERVE_BUY/WATCH_ONLY → TREND_FAIL 다운그레이드. (NO_TRADE 제외)"""
    row    = trend_filter_map.get(ticker, {})
    status = str(row.get("trend_filter", "PASS")).upper()
    reason = str(row.get("trend_filter_reason", ""))
    if status == "FAIL" and signal in ("RESERVE_BUY", "WATCH_ONLY"):
        return "TREND_FAIL", False, reason
    return signal, True, reason


def load_dart_event_map() -> dict:
    """[BM-19] DART 이벤트 점수 맵 로드 — ticker → impact_score"""
    result = {}
    csv_path = os.path.join(LATEST_DIR, "sfd_dart_event_latest.csv")
    if not os.path.exists(csv_path):
        return result
    try:
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                ticker = row.get("ticker", "").zfill(6)
                score  = int(float(row.get("impact_score", 0) or 0))
                etype  = row.get("event_type", "")
                # 동일 종목 중복 시 절댓값 큰 것 우선
                if ticker not in result or abs(score) > abs(result[ticker]["score"]):
                    result[ticker] = {"score": score, "event_type": etype}
    except Exception as e:
        pass
    return result


# -- [BM-13] Signal Timeout State Machine --───────────────────────────────────
def load_timeout_state() -> dict:
    if not os.path.exists(TIMEOUT_STATE_JSON):
        return {}
    try:
        with open(TIMEOUT_STATE_JSON, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.warning(f"[BM-13] timeout_state load failed: {e}")
        return {}

def save_timeout_state(state: dict):
    try:
        with open(TIMEOUT_STATE_JSON, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.warning(f"[BM-13] timeout_state save failed: {e}")

def apply_signal_timeout(ticker: str, raw_signal: str, trade_date: str,
                         prev_state: dict) -> tuple:
    ticker_state = prev_state.get(ticker)

    if raw_signal in TIMEOUT_SIGNALS:
        new_state = {
            "signal":       raw_signal,
            "issued_date":  trade_date,
            "bars_elapsed": 0,
        }
        return raw_signal, 0, trade_date, False, new_state

    elif raw_signal == "HOLD":
        if ticker_state is None:
            return "HOLD", 0, "", False, None

        bars   = int(ticker_state.get("bars_elapsed", 0)) + 1
        issued = ticker_state.get("issued_date", trade_date)
        sig    = ticker_state.get("signal", "HOLD")

        if bars > TIMEOUT_BARS:
            new_state = {"signal": sig, "issued_date": issued, "bars_elapsed": bars}
            return "SIGNAL_EXPIRED", bars, issued, True, new_state
        else:
            new_state = {"signal": sig, "issued_date": issued, "bars_elapsed": bars}
            return sig, bars, issued, False, new_state

    else:
        return raw_signal, 0, "", False, None


# -- load tech_detail_map --────────────────────────────────────────────────────
def load_tech_detail_map() -> dict:
    if not os.path.exists(TECH_DETAIL_CSV):
        logging.warning(f"[v3.8] TECH_DETAIL_CSV not found")
        return {}
    try:
        df = pd.read_csv(TECH_DETAIL_CSV, encoding="utf-8-sig", dtype={"ticker": str})
        if "ticker" not in df.columns or "tech_detail_score" not in df.columns:
            return {}

        # [v3.4 preserved] tech_total_score column name auto-detect
        _tcol = next(
            (c for c in ["tech_total_score", "tech_score", "total_score"]
             if c in df.columns),
            None
        )

        has_vg      = "vol_gap_score"       in df.columns
        has_sb      = "std_bar_score"       in df.columns
        has_label   = "vol_gap_label"       in df.columns
        has_pullback= "pullback_zone_score" in df.columns
        has_vs      = "vol_surge_score"     in df.columns
        has_vs_lbl  = "vol_surge_label"     in df.columns

        tech_map = {}
        for _, row in df.iterrows():
            t = str(row["ticker"]).strip().zfill(6)

            pb_score = float(row.get("pullback_zone_score", 0)) if has_pullback \
                       and not pd.isna(row.get("pullback_zone_score")) else 0.0
            vs_score = float(row.get("vol_surge_score", 0)) if has_vs \
                       and not pd.isna(row.get("vol_surge_score")) else 0.0
            vs_label = str(row.get("vol_surge_label", "")) if has_vs_lbl else ""

            if _tcol and not pd.isna(row.get(_tcol)):
                effective_tech = float(row[_tcol])
                if has_pullback and pb_score > 0 and effective_tech <= 65.0:
                    effective_tech += pb_score; tech_source_ver = "L2.7_v1.2_patched"
                elif has_vs and vs_score > 0 and effective_tech <= 75.0:
                    effective_tech += vs_score; tech_source_ver = "L2.7_v1.3_patched"
                else:
                    tech_source_ver = "L2.7_v1.3" if has_vs else "L2.7_v1.2" if has_pullback else "L2.7_v1.1"
            else:
                effective_tech  = float(row.get("tech_detail_score", 0))
                tech_source_ver = "L2.7_v1.0"

            tech_map[t] = {
                "effective_tech":      effective_tech,
                "tech_total_score":    float(row.get(_tcol, 0)) if _tcol else 0.0,
                "tech_detail_score":   float(row.get("tech_detail_score",    0)),
                "vol_gap_score":       float(row.get("vol_gap_score",        0)) if has_vg    else 0.0,
                "std_bar_score":       float(row.get("std_bar_score",        0)) if has_sb    else 0.0,
                "vol_gap_label":       str(row.get("vol_gap_label",          "")) if has_label else "",
                "pullback_zone_score": pb_score,
                "vol_surge_score":     vs_score,
                "vol_surge_label":     vs_label,
                "poc_score":           float(row.get("poc_score",            0)),
                "sr_score":            float(row.get("sr_score",             0)),
                "rsi":                 float(row.get("rsi",                 50)),
                "ma_label":            str(row.get("ma_label",               "")),
                "tech_source_ver":     tech_source_ver,
            }

        logging.info(f"[v3.8] tech_map: {len(tech_map)} tickers")
        return tech_map
    except Exception as e:
        logging.error(f"[v3.8] tech_map load failed: {e}")
        return {}


# -- [FIX-1] load news_score_map --────────────────────────────────────────────
def load_news_score_map() -> dict:
    if not os.path.exists(NEWS_SCORE_CSV):
        logging.warning(f"[v3.8] NEWS_SCORE_CSV not found: {NEWS_SCORE_CSV}")
        return {}
    try:
        df = pd.read_csv(NEWS_SCORE_CSV, encoding="utf-8-sig", dtype={"ticker": str})
        if "ticker" not in df.columns or "news_score" not in df.columns:
            logging.warning(f"[v3.8] NEWS_SCORE_CSV column missing: {list(df.columns)}")
            return {}
        result = dict(zip(
            df["ticker"].str.strip().str.zfill(6),
            pd.to_numeric(df["news_score"], errors="coerce").fillna(0)
        ))
        logging.info(f"[v3.8] news_score_map: {len(result)}rows")
        return result
    except Exception as e:
        logging.warning(f"[v3.8] news_score_map load failed: {e}")
        return {}


# -- [FIX-A] load fund_score_map (watch primary, fallback) --─────────────────────
def load_fund_score_map() -> dict:
    """
    [FIX-A] fundamental CSV priority:
    1. sfd_fundamental_watch_latest.csv  (v1.6 output)
    2. sfd_fundamental_latest.csv        (legacy fallback)

    [FIX-3 preserved] score col: adjusted_fund_score > fund_score > fundamental_score
    -> normalize 0~100 to 0~15pt
    """
    # file selection
    fund_csv = None
    if os.path.exists(FUNDAMENTAL_CSV_PRIMARY):
        fund_csv = FUNDAMENTAL_CSV_PRIMARY
        logging.info(f"[v3.8][FIX-A] fund CSV (primary): {fund_csv}")
    elif os.path.exists(FUNDAMENTAL_CSV_FALLBACK):
        fund_csv = FUNDAMENTAL_CSV_FALLBACK
        logging.info(f"[v3.8][FIX-A] fund CSV (fallback): {fund_csv}")
    else:
        logging.warning(f"[v3.8][FIX-A] fundamental CSV not found (primary={FUNDAMENTAL_CSV_PRIMARY})")
        return {}

    try:
        df = pd.read_csv(fund_csv, encoding="utf-8-sig", dtype={"ticker": str})
        if "ticker" not in df.columns:
            return {}

        score_col = next(
            (c for c in ["adjusted_fund_score", "fund_score", "fundamental_score"]
             if c in df.columns),
            None
        )
        if score_col is None:
            logging.warning(f"[v3.8][FIX-A] fund score column not found. columns: {list(df.columns)}")
            return {}

        logging.info(f"[v3.8] fund score_col: '{score_col}'")
        df["ticker"] = df["ticker"].str.strip().str.zfill(6)
        df["_norm"]  = (
            pd.to_numeric(df[score_col], errors="coerce")
            .fillna(0).clip(upper=100).div(100).mul(FUND_MAX_PT).round(2)
        )
        result = dict(zip(df["ticker"], df["_norm"]))
        nonzero = sum(1 for v in result.values() if v > 0)
        logging.info(f"[v3.8] fund_score_map: {len(result)}rows | nonzero={nonzero}")
        return result
    except Exception as e:
        logging.warning(f"[v3.8] fund_score_map load failed: {e}")
        return {}


# -- MAIN --────────────────────────────────────────────────────────────────────
def main():
    logging.info("=== sfd_signal_aggregator v4.0 START ===")
    logging.info(f"BASE_DIR:   {BASE_DIR}")
    logging.info(f"THRESHOLD:  RESERVE={THRESHOLD_RESERVE} WATCH={THRESHOLD_WATCH}")
    logging.info(f"[BM-13] Signal Timeout: {TIMEOUT_BARS}bars | targets: {TIMEOUT_SIGNALS}")
    logging.info("[v3.8] FIX: fund_watch_primary + investor_stock_code_detect")

    trade_date = find_recent_trade_date()
    logging.info(f"trade_date: {trade_date}")

    for path, label in [(INPUT_CSV, "INPUT_CSV"), (PREV_CLOSE_CSV, "PREV_CLOSE_CSV")]:
        if not os.path.exists(path):
            logging.error(f"{label} not found: {path}"); return

    input_df    = pd.read_csv(INPUT_CSV,       encoding="utf-8-sig", dtype={"ticker": str})
    prev_df     = pd.read_csv(PREV_CLOSE_CSV,  encoding="utf-8-sig", dtype={"ticker": str})
    investor_df = pd.read_csv(INVESTOR_CSV,    encoding="utf-8-sig", dtype=str) \
                  if os.path.exists(INVESTOR_CSV) else None

    if investor_df is not None:
        logging.info(f"[v3.8] investor_df: {len(investor_df)} rows, columns: {list(investor_df.columns)}")
    else:
        logging.warning(f"[v3.8] INVESTOR_CSV not found: {INVESTOR_CSV}")

    news_score_map    = load_news_score_map()
    fund_map          = load_fund_score_map()
    tech_detail_map   = load_tech_detail_map()
    no_trade_set      = load_no_trade_set()
    zone_pullback_map = load_zone_pullback_map()
    timeout_state     = load_timeout_state()
    decay_map         = load_decay_score_map()  # [BM-18]
    trend_filter_map  = load_trend_filter_map()             # [TREND]
    dart_map          = load_dart_event_map()   # [BM-19]

    use_tech_detail = len(tech_detail_map) > 0
    logging.info(
        f"[v3.8] use_tech_detail={use_tech_detail} | tech={len(tech_detail_map)} "
        f"| news={len(news_score_map)} | fund={len(fund_map)} "
        f"| investor={'found' if investor_df is not None else 'not_found'} "
        f"| no_trade={len(no_trade_set)} | zp={len(zone_pullback_map)} "
        f"| timeout_tracked={len(timeout_state)}"
    )

    if "prev_value" in prev_df.columns:
        prev_df["prev_value"] = pd.to_numeric(prev_df["prev_value"], errors="coerce").fillna(0)

    has_close_col = "close" in prev_df.columns
    has_ma20_col  = "ma20"  in prev_df.columns
    has_ma60_col  = "ma60"  in prev_df.columns

    # ticker column auto-detect (stock_code support)
    _tcol_input = next(
        (c for c in ["ticker", "stock_code"] if c in input_df.columns),
        input_df.columns[0]
    )
    tickers = input_df[_tcol_input].dropna().astype(str).str.zfill(6).unique().tolist()
    if _tcol_input != "ticker":
        input_df = input_df.rename(columns={_tcol_input: "ticker"})
    logging.info(f"tickers: {len(tickers)}")

    results           = []
    new_timeout_state = {}

    for ticker in tickers:

        # -- tech_score calculation --
        if use_tech_detail and ticker in tech_detail_map:
            td          = tech_detail_map[ticker]
            t_score     = td["effective_tech"]
            rsi_val     = td["rsi"]
            ma_align    = td["ma_label"]
            poc_s       = td["poc_score"]
            sr_s        = td["sr_score"]
            vg_score    = td["vol_gap_score"]
            sb_score    = td["std_bar_score"]
            vg_label    = td["vol_gap_label"]
            pb_score    = td["pullback_zone_score"]
            vs_score    = td["vol_surge_score"]
            vs_label    = td["vol_surge_label"]
            tech_ver    = td["tech_source_ver"]
            tech_source = "L2.7"

            vol_ratio = 0.0
            pc_row = prev_df[prev_df["ticker"] == ticker]
            if not pc_row.empty and "volume" in pc_row.columns and "vol_avg" in pc_row.columns:
                try:
                    vol  = float(pc_row.iloc[0].get("volume", 0))
                    vavg = float(pc_row.iloc[0].get("vol_avg", 1))
                    vol_ratio = round(vol / vavg, 2) if vavg > 0 else 0.0
                except: pass

            bias_score = waist_line = price_vs_waist_pct = 0
            if not pc_row.empty and has_close_col and has_ma20_col and has_ma60_col:
                try:
                    close_val = float(pc_row.iloc[0].get("close", 0))
                    ma20_val  = float(pc_row.iloc[0].get("ma20",  0))
                    ma60_val  = float(pc_row.iloc[0].get("ma60",  0))
                    if close_val > 0 and ma20_val > 0 and ma60_val > 0:
                        bias_score, waist_line, price_vs_waist_pct = calc_bias_filter(
                            close_val, ma20_val, ma60_val
                        )
                except: pass

        else:
            tech = get_technical_data(ticker, trade_date)
            if tech is None: continue

            t_score  = (score_rsi(tech["rsi"])
                        + score_ma(tech["ma_short"], tech["ma_mid"], tech["ma_long"])
                        + score_volume(tech["volume"], tech["vol_avg"]))
            rsi_val  = tech["rsi"]
            ma_align = ("up" if tech["ma_short"] and tech["ma_mid"] and tech["ma_long"]
                        and tech["ma_short"] > tech["ma_mid"] > tech["ma_long"] else "down")
            vol_ratio = round(tech["volume"] / tech["vol_avg"], 2) \
                        if tech["vol_avg"] and tech["vol_avg"] > 0 else 0
            poc_s = sr_s = vg_score = sb_score = pb_score = vs_score = 0
            vg_label = vs_label = ""
            tech_source = "v2.2"; tech_ver = "v2.2_fallback"
            close_val = tech.get("close", 0)
            ma20_val  = tech.get("ma_mid", 0)
            ma60_val  = tech.get("ma_long", 0)
            if close_val > 0 and ma20_val > 0 and ma60_val > 0:
                bias_score, waist_line, price_vs_waist_pct = calc_bias_filter(close_val, ma20_val, ma60_val)
            else:
                bias_score = waist_line = price_vs_waist_pct = 0

        n_score   = score_news(ticker, news_score_map)
        i_score   = score_investor(ticker, investor_df)
        ths_score = score_theme(ticker, prev_df)
        f_score   = score_fundamental(ticker, fund_map)

        zp_data  = zone_pullback_map.get(ticker, {})
        zp_score = float(zp_data.get("zone_pullback_score", 0) or 0)
        zp_label = str(zp_data.get("zone_pullback_label", "") or "")

        dc_data     = decay_map.get(ticker, {})  # [BM-18]
        decay_score = float(dc_data.get("decay_score", 0))
        decay_flag  = str(dc_data.get("decay_flag", "FRESH"))

        # [BM-19] DART 이벤트 점수
        dart_hit   = dart_map.get(ticker, {})
        dart_score = dart_hit.get("score", 0)
        total      = (t_score + n_score + i_score + ths_score + f_score
                      + bias_score + vs_score + zp_score + decay_score + dart_score)
        raw_signal = classify_signal(total)

        (timeout_signal, bars_elapsed, issued_date,
         is_timeout, updated_ts) = apply_signal_timeout(
             ticker, raw_signal, trade_date, timeout_state
         )
        if updated_ts is not None:
            new_timeout_state[ticker] = updated_ts

        if ticker in no_trade_set:
            signal        = "NO_TRADE"
            no_trade_flag  = True
        else:
            signal        = timeout_signal
            no_trade_flag  = False

        # [TREND] trend_filter 적용 (NO_TRADE 제외)
        if signal not in ("NO_TRADE",):
            signal, tf_pass, tf_reason = apply_trend_filter(ticker, signal, trend_filter_map)
        else:
            tf_pass, tf_reason = True, ""

        name_row = input_df[input_df["ticker"] == ticker]
        name     = name_row.iloc[0].get("name", "") if not name_row.empty else ""

        results.append({
            "fetch_date":           trade_date,
            "fetch_time":           fetch_time,
            "ticker":               ticker,
            "name":                 name,
            "signal":               signal,
            "raw_signal":           raw_signal,
            "no_trade":             no_trade_flag,
            "signal_timeout":       is_timeout,
            "signal_bars_elapsed":  bars_elapsed,
            "signal_issued_date":   issued_date,
            "total_score":          total,
            "tech_score":           t_score,
            "poc_score":            poc_s,
            "sr_score":             sr_s,
            "tech_source":          tech_source,
            "news_score":           round(n_score, 2),
            "investor_score":       i_score,
            "theme_score":          ths_score,
            "fund_score":           round(f_score, 2),
            "rsi":                  rsi_val,
            "ma_align":             ma_align,
            "vol_ratio":            vol_ratio,
            "mode":                 MODE,
            "vol_gap_score":        vg_score,
            "std_bar_score":        sb_score,
            "vol_gap_label":        vg_label,
            "pullback_zone_score":  pb_score,
            "vol_surge_score":      vs_score,
            "vol_surge_label":      vs_label,
            "bias_filter_score":    bias_score,
            "waist_line":           waist_line,
            "price_vs_waist_pct":   price_vs_waist_pct,
            "zone_pullback_score":  zp_score,
            "zone_pullback_label":  zp_label,
            "decay_score":          decay_score,   # [BM-18]
            "decay_flag":           decay_flag,    # [BM-18]
            "trend_filter_pass":    tf_pass,       # [TREND]
            "trend_filter_reason":  tf_reason,     # [TREND]
            "tech_ver":             tech_ver,
        })

    save_timeout_state(new_timeout_state)

    df_out = (pd.DataFrame(results)
              .sort_values("total_score", ascending=False)
              .reset_index(drop=True))
    df_out.to_csv(LATEST_CSV, index=False, encoding="utf-8-sig")
    df_out.to_csv(
        os.path.join(HISTORY_DIR, f"sfd_master_signal_{trade_date}.csv"),
        index=False, encoding="utf-8-sig"
    )

    elapsed         = int(time.time() - START_TIME)
    reserve         = len(df_out[df_out["signal"] == "RESERVE_BUY"])
    watch           = len(df_out[df_out["signal"] == "WATCH_ONLY"])
    no_trade_ct     = len(df_out[df_out["no_trade"] == True])
    expired_ct      = len(df_out[df_out["signal_timeout"] == True])
    trend_fail_ct   = len(df_out[df_out["signal"] == "TREND_FAIL"])
    zp_nonzero      = len(df_out[df_out["zone_pullback_score"] > 0])
    vs_nonzero      = len(df_out[df_out["vol_surge_score"] > 0])
    bias_up         = len(df_out[df_out["bias_filter_score"] > 0])
    bias_down       = len(df_out[df_out["bias_filter_score"] < 0])
    news_nonzero    = len(df_out[df_out["news_score"] > 0])
    fund_nonzero    = len(df_out[df_out["fund_score"] > 0])
    inv_nonzero     = len(df_out[df_out["investor_score"] > 0])

    logging.info(
        f"DONE | RESERVE={reserve} WATCH={watch} NO_TRADE={no_trade_ct} "
        f"[BM-13]EXPIRED={expired_ct} [TREND]FAIL={trend_fail_ct} "
        f"[BM-12]zp={zp_nonzero} "
        f"[BM-10]vs={vs_nonzero} [BM-3]+{bias_up}/-{bias_down} "
        f"news={news_nonzero} fund={fund_nonzero} investor={inv_nonzero} "
        f"elapsed={elapsed}s MODE={MODE}"
    )
    print(
        f"[OK] RESERVE={reserve} | WATCH={watch} | NO_TRADE={no_trade_ct} | "
        f"[BM-13]EXPIRED={expired_ct} | [TREND]FAIL={trend_fail_ct} | "
        f"[BM-12]zp={zp_nonzero} | "
        f"[BM-10]vs={vs_nonzero} | [BM-3]+{bias_up}/-{bias_down} | "
        f"news={news_nonzero} | fund={fund_nonzero} | investor={inv_nonzero} | "
        f"elapsed={elapsed}s | MODE={MODE}"
    )
    print(f"  -> {LATEST_CSV}")
    print(f"  -> {TIMEOUT_STATE_JSON}")


if __name__ == "__main__":
    main()
