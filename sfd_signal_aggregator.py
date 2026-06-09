# sfd_signal_aggregator.py | v3.6 | Claude (Anthropic) 2026-06-09
# Deploy to: sfd-pipeline/sfd_signal_aggregator.py
#
# [v3.5 → v3.6 변경사항]
# - [BM-14] AI Candle Pattern Recognition 통합
#     calculate_candle_score() → -10 ~ +15pt
#     apply_candle_score_to_tech() → tech_score에 합산 후 85pt 캡 적용
#     신규 출력 컬럼: candle_score, candle_pattern
#     OHLCV 없을 경우 candle_score=0, candle_pattern='NONE' (graceful fallback)
#
# [스코어 아키텍처 현황 v3.6]
# total = tech(max85, candle 포함) + news(max30) + investor(max20)
#       + theme(max10) + fund(max15) + bias_filter(±5) + vol_surge(0~10)
#       + zone_pullback(0~15)  max=205pt
# 신호 오버라이드: NO_TRADE > SIGNAL_EXPIRED > raw_signal
#
# [v3.5 유지사항]
# - FIX-1~5: news/fund/investor 경로·컬럼 수정
# - tech_total_score 컬럼명 자동탐지
# - BM-13 Signal Timeout State Machine
# - BM-12 zone_pullback_score
# - BM-10 vol_surge_score
# - BM-5  no_trade 오버라이드
# - BM-3  bias_filter_score

import os
import sys
import json
import time
import logging
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import FinanceDataReader as fdr

# ── [BM-14] Candle Pattern ────────────────────────────────────────────────────
try:
    from tools.sfd_candle_pattern import calculate_candle_score, apply_candle_score_to_tech
    _HAS_CANDLE = True
except ImportError:
    _HAS_CANDLE = False

# ── 경로 설정 ──────────────────────────────────────────────────────────────────
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
# [FIX-1] 파일명 수정: sfd_news_sentiment_latest.csv → sfd_news_score_latest.csv
NEWS_SCORE_CSV      = os.path.join(LATEST_DIR, "sfd_news_score_latest.csv")
# [FIX-2] 파일명 수정: sfd_fundamental_watch_latest.csv → sfd_fundamental_latest.csv
FUNDAMENTAL_CSV     = os.path.join(LATEST_DIR, "sfd_fundamental_latest.csv")
TECH_DETAIL_CSV     = os.path.join(LATEST_DIR, "sfd_technical_latest.csv")
NO_TRADE_JSON       = os.path.join(LATEST_DIR, "sfd_no_trade_tickers.json")
ZONE_PULLBACK_CSV   = os.path.join(LATEST_DIR, "sfd_zone_pullback_latest.csv")
TIMEOUT_STATE_JSON  = os.path.join(LATEST_DIR, "signal_timeout_state.json")

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

# ── 파라미터 ───────────────────────────────────────────────────────────────────
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


# ── 최근 거래일 탐색 ──────────────────────────────────────────────────────────
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


# ── v2.2 fallback 기술 계산 ───────────────────────────────────────────────────
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
            "close":    last["Close"],
        }
    except: return None


# ── [BM-14] OHLCV DataFrame 취득 ─────────────────────────────────────────────
def get_ohlcv_df(ticker: str, end_date: str, n_bars: int = 25):
    """캔들 패턴 분석용 OHLCV DataFrame 반환 (최근 n_bars 봉)."""
    try:
        end   = datetime.strptime(end_date, "%Y%m%d")
        start = (end - timedelta(days=n_bars + 40)).strftime("%Y-%m-%d")
        df    = fdr.DataReader(ticker, start, end.strftime("%Y-%m-%d"))
        if df is None or len(df) < 5:
            return None
        return df.sort_index().tail(n_bars)
    except:
        return None


# ── 스코어 함수들 ──────────────────────────────────────────────────────────────
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
    [FIX-4] investor_score 컬럼 없음 → foreign_net_buy/institution_net_buy 직접 계산
    - data_status가 ZERO 또는 FAIL이면 0점
    - foreign_net_buy > 0: +10pt
    - institution_net_buy > 0: +10pt
    """
    if investor_df is None or investor_df.empty: return 0
    row = investor_df[investor_df["ticker"] == ticker]
    if row.empty: return 0
    try:
        status = str(row.iloc[0].get("data_status", "OK")).upper()
        if status in ("ZERO", "FAIL"): return 0
        f = float(row.iloc[0].get("foreign_net_buy", 0))
        i = float(row.iloc[0].get("institution_net_buy", 0))
        return (10 if f > 0 else 0) + (10 if i > 0 else 0)
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


# ── [BM-3] Bias Filter ────────────────────────────────────────────────────────
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


# ── [BM-5] no_trade_set 로드 ──────────────────────────────────────────────────
def load_no_trade_set() -> set:
    if not os.path.exists(NO_TRADE_JSON):
        logging.info(f"[BM-5] no_trade JSON 없음: {NO_TRADE_JSON}")
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
        logging.info(f"[BM-5] no_trade_set: {len(result)}건")
        return result
    except Exception as e:
        logging.warning(f"[BM-5] no_trade JSON 로드 실패: {e}")
        return set()


# ── [BM-12] zone_pullback_map 로드 ───────────────────────────────────────────
def load_zone_pullback_map() -> dict:
    if not os.path.exists(ZONE_PULLBACK_CSV):
        logging.info(f"[BM-12] zone_pullback CSV 없음: {ZONE_PULLBACK_CSV}")
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
        logging.info(f"[BM-12] zone_pullback_map: {len(result)}건")
        return result
    except Exception as e:
        logging.warning(f"[BM-12] zone_pullback_map 로드 실패: {e}")
        return {}


# ── [BM-13] Signal Timeout State Machine ─────────────────────────────────────
def load_timeout_state() -> dict:
    if not os.path.exists(TIMEOUT_STATE_JSON):
        return {}
    try:
        with open(TIMEOUT_STATE_JSON, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.warning(f"[BM-13] timeout_state 로드 실패: {e}")
        return {}

def save_timeout_state(state: dict):
    try:
        with open(TIMEOUT_STATE_JSON, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.warning(f"[BM-13] timeout_state 저장 실패: {e}")

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


# ── tech_detail_map 로드 ──────────────────────────────────────────────────────
def load_tech_detail_map() -> dict:
    if not os.path.exists(TECH_DETAIL_CSV):
        logging.warning(f"[v3.5] TECH_DETAIL_CSV not found")
        return {}
    try:
        df = pd.read_csv(TECH_DETAIL_CSV, encoding="utf-8-sig", dtype={"ticker": str})
        if "ticker" not in df.columns or "tech_detail_score" not in df.columns:
            return {}

        # [v3.4 유지] tech_total_score 컬럼명 자동탐지
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
                "tech_detail_score":   float(row.get("tech_detail_score",   0)),
                "vol_gap_score":       float(row.get("vol_gap_score",       0)) if has_vg    else 0.0,
                "std_bar_score":       float(row.get("std_bar_score",       0)) if has_sb    else 0.0,
                "vol_gap_label":       str(row.get("vol_gap_label",         "")) if has_label else "",
                "pullback_zone_score": pb_score,
                "vol_surge_score":     vs_score,
                "vol_surge_label":     vs_label,
                "poc_score":           float(row.get("poc_score",           0)),
                "sr_score":            float(row.get("sr_score",            0)),
                "rsi":                 float(row.get("rsi",                50)),
                "ma_label":            str(row.get("ma_label",             "")),
                "tech_source_ver":     tech_source_ver,
            }

        logging.info(f"[v3.5] tech_map: {len(tech_map)} tickers")
        return tech_map
    except Exception as e:
        logging.error(f"[v3.5] tech_map load failed: {e}")
        return {}


# ── [FIX-1] news_score_map 로드 ──────────────────────────────────────────────
def load_news_score_map() -> dict:
    """
    sfd_news_score_latest.csv 로드
    컬럼: ticker, name, news_score, article_cnt
    """
    if not os.path.exists(NEWS_SCORE_CSV):
        logging.warning(f"[v3.5] NEWS_SCORE_CSV not found: {NEWS_SCORE_CSV}")
        return {}
    try:
        df = pd.read_csv(NEWS_SCORE_CSV, encoding="utf-8-sig", dtype={"ticker": str})
        if "ticker" not in df.columns or "news_score" not in df.columns:
            logging.warning(f"[v3.5] NEWS_SCORE_CSV 컬럼 불일치: {list(df.columns)}")
            return {}
        result = dict(zip(
            df["ticker"].str.strip().str.zfill(6),
            pd.to_numeric(df["news_score"], errors="coerce").fillna(0)
        ))
        logging.info(f"[v3.5] news_score_map: {len(result)}건")
        return result
    except Exception as e:
        logging.warning(f"[v3.5] news_score_map 로드 실패: {e}")
        return {}


# ── [FIX-2,3] fund_score_map 로드 ────────────────────────────────────────────
def load_fund_score_map() -> dict:
    """
    sfd_fundamental_latest.csv 로드
    [FIX-3] adjusted_fund_score > fund_score > fundamental_score 순 자동탐지
    → ticker → normalized fund_score (0~15pt) 맵 반환
    """
    if not os.path.exists(FUNDAMENTAL_CSV):
        logging.warning(f"[v3.5] FUNDAMENTAL_CSV not found: {FUNDAMENTAL_CSV}")
        return {}
    try:
        df = pd.read_csv(FUNDAMENTAL_CSV, encoding="utf-8-sig", dtype={"ticker": str})
        if "ticker" not in df.columns:
            return {}

        score_col = next(
            (c for c in ["adjusted_fund_score", "fund_score", "fundamental_score"]
             if c in df.columns),
            None
        )
        if score_col is None:
            logging.warning(f"[v3.5] FUNDAMENTAL_CSV score 컬럼 없음. 컬럼: {list(df.columns)}")
            return {}

        logging.info(f"[v3.5] fund score_col 탐지: '{score_col}'")
        df["ticker"] = df["ticker"].str.strip().str.zfill(6)
        df["_norm"]  = (
            pd.to_numeric(df[score_col], errors="coerce")
            .fillna(0).clip(upper=100).div(100).mul(FUND_MAX_PT).round(2)
        )
        result = dict(zip(df["ticker"], df["_norm"]))
        logging.info(f"[v3.5] fund_score_map: {len(result)}건")
        return result
    except Exception as e:
        logging.warning(f"[v3.5] fund_score_map 로드 실패: {e}")
        return {}


# ── MAIN ───────────────────────────────────────────────────────────────────────
def main():
    logging.info("=== sfd_signal_aggregator v3.6 START ===")
    logging.info(f"BASE_DIR:   {BASE_DIR}")
    logging.info(f"THRESHOLD:  RESERVE={THRESHOLD_RESERVE} WATCH={THRESHOLD_WATCH}")
    logging.info(f"[BM-13] Signal Timeout: {TIMEOUT_BARS}봉 | 대상: {TIMEOUT_SIGNALS}")
    logging.info("[v3.5] FIX: news_path + fund_path + fund_col + investor_raw")
    logging.info(f"[BM-14] candle_pattern available={_HAS_CANDLE}")

    trade_date = find_recent_trade_date()
    logging.info(f"trade_date: {trade_date}")

    for path, label in [(INPUT_CSV, "INPUT_CSV"), (PREV_CLOSE_CSV, "PREV_CLOSE_CSV")]:
        if not os.path.exists(path):
            logging.error(f"{label} not found: {path}"); return

    input_df    = pd.read_csv(INPUT_CSV,       encoding="utf-8-sig", dtype={"ticker": str})
    prev_df     = pd.read_csv(PREV_CLOSE_CSV,  encoding="utf-8-sig", dtype={"ticker": str})
    investor_df = pd.read_csv(INVESTOR_CSV,    encoding="utf-8-sig", dtype={"ticker": str}) \
                  if os.path.exists(INVESTOR_CSV) else None

    if investor_df is not None:
        logging.info(f"[v3.5] investor_df: {len(investor_df)}행, 컬럼: {list(investor_df.columns)}")
    else:
        logging.warning(f"[v3.5] INVESTOR_CSV not found: {INVESTOR_CSV}")

    news_score_map    = load_news_score_map()
    fund_map          = load_fund_score_map()
    tech_detail_map   = load_tech_detail_map()
    no_trade_set      = load_no_trade_set()
    zone_pullback_map = load_zone_pullback_map()
    timeout_state     = load_timeout_state()

    use_tech_detail = len(tech_detail_map) > 0
    logging.info(
        f"[v3.5] use_tech_detail={use_tech_detail} | tech={len(tech_detail_map)} "
        f"| news={len(news_score_map)} | fund={len(fund_map)} "
        f"| investor={'있음' if investor_df is not None else '없음'} "
        f"| no_trade={len(no_trade_set)} | zp={len(zone_pullback_map)} "
        f"| timeout_tracked={len(timeout_state)}"
    )

    if "prev_value" in prev_df.columns:
        prev_df["prev_value"] = pd.to_numeric(prev_df["prev_value"], errors="coerce").fillna(0)

    has_close_col = "close" in prev_df.columns
    has_ma20_col  = "ma20"  in prev_df.columns
    has_ma60_col  = "ma60"  in prev_df.columns

    # ticker 컬럼명 자동탐지 (stock_code 호환)
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

        # ── tech_score 계산 ────────────────────────────────────────────────────
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

        # ── [BM-14] Candle Pattern Score ──────────────────────────────────
        candle_score   = 0
        candle_pattern = "NONE"
        if _HAS_CANDLE:
            ohlcv_df = get_ohlcv_df(ticker, trade_date)
            if ohlcv_df is not None:
                candle_result  = calculate_candle_score(ohlcv_df)
                t_score        = apply_candle_score_to_tech(t_score, candle_result)
                candle_score   = candle_result.get("candle_score", 0)
                candle_pattern = candle_result.get("pattern", "NONE")

        n_score   = score_news(ticker, news_score_map)
        i_score   = score_investor(ticker, investor_df)
        ths_score = score_theme(ticker, prev_df)
        f_score   = score_fundamental(ticker, fund_map)

        zp_data  = zone_pullback_map.get(ticker, {})
        zp_score = float(zp_data.get("zone_pullback_score", 0) or 0)
        zp_label = str(zp_data.get("zone_pullback_label", "") or "")

        total      = (t_score + n_score + i_score + ths_score + f_score
                     + bias_score + vs_score + zp_score)
        raw_signal = classify_signal(total)

        (timeout_signal, bars_elapsed, issued_date,
         is_timeout, updated_ts) = apply_signal_timeout(
             ticker, raw_signal, trade_date, timeout_state
         )
        if updated_ts is not None:
            new_timeout_state[ticker] = updated_ts

        if ticker in no_trade_set:
            signal         = "NO_TRADE"
            no_trade_flag  = True
        else:
            signal         = timeout_signal
            no_trade_flag  = False

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
            "candle_score":         candle_score,       # ★ BM-14
            "candle_pattern":       candle_pattern,     # ★ BM-14
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

    elapsed      = int(time.time() - START_TIME)
    reserve      = len(df_out[df_out["signal"] == "RESERVE_BUY"])
    watch        = len(df_out[df_out["signal"] == "WATCH_ONLY"])
    no_trade_ct  = len(df_out[df_out["no_trade"] == True])
    expired_ct   = len(df_out[df_out["signal_timeout"] == True])
    zp_nonzero   = len(df_out[df_out["zone_pullback_score"] > 0])
    vs_nonzero   = len(df_out[df_out["vol_surge_score"] > 0])
    bias_up      = len(df_out[df_out["bias_filter_score"] > 0])
    bias_down    = len(df_out[df_out["bias_filter_score"] < 0])
    news_nonzero = len(df_out[df_out["news_score"] > 0])
    fund_nonzero = len(df_out[df_out["fund_score"] > 0])
    inv_nonzero  = len(df_out[df_out["investor_score"] > 0])
    candle_hit   = len(df_out[df_out["candle_pattern"] != "NONE"]) if "candle_pattern" in df_out.columns else 0

    logging.info(
        f"DONE | RESERVE={reserve} WATCH={watch} NO_TRADE={no_trade_ct} "
        f"[BM-13]EXPIRED={expired_ct} [BM-12]zp={zp_nonzero} "
        f"[BM-10]vs={vs_nonzero} [BM-3]+{bias_up}/-{bias_down} "
        f"[BM-14]candle={candle_hit} "
        f"news={news_nonzero} fund={fund_nonzero} investor={inv_nonzero} "
        f"elapsed={elapsed}s MODE={MODE}"
    )
    print(
        f"[OK] RESERVE={reserve} | WATCH={watch} | NO_TRADE={no_trade_ct} | "
        f"[BM-13]EXPIRED={expired_ct} | [BM-12]zp={zp_nonzero} | "
        f"[BM-10]vs={vs_nonzero} | [BM-3]+{bias_up}/-{bias_down} | "
        f"[BM-14]candle={candle_hit} | "
        f"news={news_nonzero} | fund={fund_nonzero} | investor={inv_nonzero} | "
        f"elapsed={elapsed}s | MODE={MODE}"
    )
    print(f"  -> {LATEST_CSV}")
    print(f"  -> {TIMEOUT_STATE_JSON}")


if __name__ == "__main__":
    main()
