# sfd_signal_aggregator.py | v2.8 | Claude (Anthropic) 2026-06-01
# Deploy to: sfd-pipeline/sfd_signal_aggregator.py
#
# [v2.7 → v2.8 변경사항]
# - [BM-12] ZONE_PULLBACK 연동
#   sfd_zone_pullback_latest.csv 읽어서 zone_pullback_score (0~15pt) total에 가산
#   신규 컬럼: zone_pullback_score, zone_pullback_label
#   출력 로그: [BM-12]zp={n}건 출력
#
# [스코어 아키텍처 현황 v2.8]
# total = tech(max85) + news(max30) + investor(max20)
#       + theme(max10) + fund(max15) + bias_filter(±5) + vol_surge(0~10)
#       + zone_pullback(0~15)   ★ BM-12 신규
# 이론상 max = 85+30+20+10+15+5+10+15 = 190pt
# NO_TRADE 오버라이드: total_score 보존, signal만 변경

import os
import sys
import json
import time
import logging
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import FinanceDataReader as fdr

# ── 경로 설정 ─────────────────────────────────────────────────────────────────
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
NEWS_SCORE_CSV      = os.path.join(LATEST_DIR, "sfd_news_score_latest.csv")
FUNDAMENTAL_CSV     = os.path.join(LATEST_DIR, "sfd_fundamental_latest.csv")
TECH_DETAIL_CSV     = os.path.join(LATEST_DIR, "sfd_technical_latest.csv")
NO_TRADE_JSON       = os.path.join(LATEST_DIR, "sfd_no_trade_tickers.json")
ZONE_PULLBACK_CSV   = os.path.join(LATEST_DIR, "sfd_zone_pullback_latest.csv")  # ★ BM-12

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

# ── 파라미터 ──────────────────────────────────────────────────────────────────
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
BIAS_MA_MID    = 20
BIAS_MA_LONG   = 60
BIAS_UPPER_PCT = 1.05
BIAS_LOWER_PCT = 0.95
BIAS_UPPER_PT  = 5
BIAS_LOWER_PT  = -5


# ── 최근 거래일 ───────────────────────────────────────────────────────────────
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
        df["rsi"]          = calc_rsi(df["Close"], RSI_PERIOD)
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
    if investor_df is None or investor_df.empty: return 0
    row = investor_df[investor_df["ticker"] == ticker]
    if row.empty: return 0
    try:
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


# ── [BM-5] no_trade_set 로드 ─────────────────────────────────────────────────
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


# ── [BM-12] zone_pullback_map 로드 ────────────────────────────────────────────
def load_zone_pullback_map() -> dict:
    """
    sfd_zone_pullback_latest.csv → {ticker: {zone_pullback_score, zone_pullback_label}}
    score가 0인 종목은 파일에 없으므로 미존재 = 0점 처리
    """
    if not os.path.exists(ZONE_PULLBACK_CSV):
        logging.info(f"[BM-12] zone_pullback CSV 없음: {ZONE_PULLBACK_CSV}")
        return {}
    try:
        df = pd.read_csv(ZONE_PULLBACK_CSV, encoding="utf-8-sig", dtype={"ticker": str})
        if "ticker" not in df.columns or "zone_pullback_score" not in df.columns:
            logging.warning(f"[BM-12] zone_pullback CSV 컬럼 부족: {df.columns.tolist()}")
            return {}
        df["ticker"] = df["ticker"].str.strip().str.zfill(6)
        result = {}
        for _, row in df.iterrows():
            t = str(row["ticker"])
            result[t] = {
                "zone_pullback_score": float(row.get("zone_pullback_score", 0) or 0),
                "zone_pullback_label": str(row.get("zone_pullback_label", "") or ""),
            }
        logging.info(f"[BM-12] zone_pullback_map: {len(result)}건 로드")
        return result
    except Exception as e:
        logging.warning(f"[BM-12] zone_pullback_map 로드 실패: {e}")
        return {}


# ── tech_detail_map 로드 ──────────────────────────────────────────────────────
def load_tech_detail_map() -> dict:
    if not os.path.exists(TECH_DETAIL_CSV):
        logging.warning(f"[v2.8] TECH_DETAIL_CSV not found: {TECH_DETAIL_CSV}")
        return {}
    try:
        df = pd.read_csv(TECH_DETAIL_CSV, encoding="utf-8-sig", dtype={"ticker": str})
        if "ticker" not in df.columns or "tech_detail_score" not in df.columns:
            return {}

        has_total    = "tech_total_score"    in df.columns
        has_vg       = "vol_gap_score"       in df.columns
        has_sb       = "std_bar_score"       in df.columns
        has_label    = "vol_gap_label"       in df.columns
        has_pullback = "pullback_zone_score" in df.columns
        has_vs       = "vol_surge_score"     in df.columns
        has_vs_label = "vol_surge_label"     in df.columns

        tech_map = {}
        for _, row in df.iterrows():
            t = str(row["ticker"]).strip().zfill(6)

            pb_score = float(row.get("pullback_zone_score", 0)) if has_pullback \
                       and not pd.isna(row.get("pullback_zone_score")) else 0.0
            vs_score = float(row.get("vol_surge_score", 0)) if has_vs \
                       and not pd.isna(row.get("vol_surge_score")) else 0.0
            vs_label = str(row.get("vol_surge_label", "")) if has_vs_label else ""

            if has_total and not pd.isna(row.get("tech_total_score")):
                effective_tech = float(row["tech_total_score"])
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
                "tech_total_score":    float(row.get("tech_total_score",    0)) if has_total else 0.0,
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

        v13_cnt = sum(1 for v in tech_map.values() if "v1.3" in v["tech_source_ver"])
        logging.info(f"[v2.8] tech_map: {len(tech_map)} tickers | v1.3={v13_cnt}")
        return tech_map
    except Exception as e:
        logging.error(f"[v2.8] tech_map load failed: {e}")
        return {}


# ── 보조 데이터 로더 ──────────────────────────────────────────────────────────
def load_news_score_map() -> dict:
    if not os.path.exists(NEWS_SCORE_CSV): return {}
    try:
        df = pd.read_csv(NEWS_SCORE_CSV, encoding="utf-8-sig", dtype={"ticker": str})
        if "ticker" not in df.columns or "news_score" not in df.columns: return {}
        return dict(zip(
            df["ticker"].str.strip().str.zfill(6),
            pd.to_numeric(df["news_score"], errors="coerce").fillna(0)
        ))
    except: return {}

def load_fund_score_map() -> dict:
    if not os.path.exists(FUNDAMENTAL_CSV): return {}
    try:
        df = pd.read_csv(FUNDAMENTAL_CSV, encoding="utf-8-sig", dtype={"ticker": str})
        if "ticker" not in df.columns or "adjusted_fund_score" not in df.columns: return {}
        df["ticker"] = df["ticker"].str.strip().str.zfill(6)
        df["_norm"]  = (
            pd.to_numeric(df["adjusted_fund_score"], errors="coerce")
            .fillna(0).clip(upper=100).div(100).mul(FUND_MAX_PT).round(2)
        )
        return dict(zip(df["ticker"], df["_norm"]))
    except: return {}


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    logging.info("=== sfd_signal_aggregator v2.8 START ===")
    logging.info(f"BASE_DIR:   {BASE_DIR}")
    logging.info(f"THRESHOLD:  RESERVE={THRESHOLD_RESERVE} WATCH={THRESHOLD_WATCH}")
    logging.info("[v2.8] BM-12 zone_pullback(0~15pt) + BM-5 no_trade + BM-3 bias_filter + BM-10 vol_surge")

    trade_date = find_recent_trade_date()
    logging.info(f"trade_date: {trade_date}")

    for path, label in [(INPUT_CSV, "INPUT_CSV"), (PREV_CLOSE_CSV, "PREV_CLOSE_CSV")]:
        if not os.path.exists(path):
            logging.error(f"{label} not found: {path}"); return

    input_df    = pd.read_csv(INPUT_CSV,      encoding="utf-8-sig", dtype={"ticker": str})
    prev_df     = pd.read_csv(PREV_CLOSE_CSV, encoding="utf-8-sig", dtype={"ticker": str})
    investor_df = pd.read_csv(INVESTOR_CSV,   encoding="utf-8-sig", dtype={"ticker": str}) \
                  if os.path.exists(INVESTOR_CSV) else None

    news_score_map    = load_news_score_map()
    fund_map          = load_fund_score_map()
    tech_detail_map   = load_tech_detail_map()
    no_trade_set      = load_no_trade_set()
    zone_pullback_map = load_zone_pullback_map()   # ★ BM-12

    use_tech_detail = len(tech_detail_map) > 0
    logging.info(
        f"[v2.8] use_tech_detail={use_tech_detail} | tech={len(tech_detail_map)} "
        f"| no_trade={len(no_trade_set)} | zp={len(zone_pullback_map)}"
    )

    if "prev_value" in prev_df.columns:
        prev_df["prev_value"] = pd.to_numeric(prev_df["prev_value"], errors="coerce").fillna(0)

    has_close_col = "close" in prev_df.columns
    has_ma20_col  = "ma20"  in prev_df.columns
    has_ma60_col  = "ma60"  in prev_df.columns

    tickers = input_df["ticker"].dropna().astype(str).str.zfill(6).unique().tolist()
    logging.info(f"tickers: {len(tickers)}")

    results = []
    for ticker in tickers:

        # ── tech_score 계산 ──────────────────────────────────────────────────
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

            # [BM-3] Bias Filter
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
            # v2.2 fallback
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

        # ★ [BM-12] zone_pullback_score
        zp_data   = zone_pullback_map.get(ticker, {})
        zp_score  = float(zp_data.get("zone_pullback_score", 0) or 0)
        zp_label  = str(zp_data.get("zone_pullback_label", "") or "")

        # [v2.8] total
        total = (t_score + n_score + i_score + ths_score + f_score
                 + bias_score + vs_score + zp_score)

        raw_signal = classify_signal(total)

        # [BM-5] no_trade 오버라이드
        if ticker in no_trade_set:
            signal        = "NO_TRADE"
            no_trade_flag = True
        else:
            signal        = raw_signal
            no_trade_flag = False

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
            "vol_surge_score":      vs_score,           # BM-10
            "vol_surge_label":      vs_label,           # BM-10
            "bias_filter_score":    bias_score,         # BM-3
            "waist_line":           waist_line,         # BM-3
            "price_vs_waist_pct":   price_vs_waist_pct,# BM-3
            "zone_pullback_score":  zp_score,           # ★ BM-12
            "zone_pullback_label":  zp_label,           # ★ BM-12
            "tech_ver":             tech_ver,
        })

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
    zp_nonzero   = len(df_out[df_out["zone_pullback_score"] > 0])
    vs_nonzero   = len(df_out[df_out["vol_surge_score"] > 0])
    bias_up      = len(df_out[df_out["bias_filter_score"] > 0])
    bias_down    = len(df_out[df_out["bias_filter_score"] < 0])

    logging.info(
        f"DONE | RESERVE={reserve} WATCH={watch} NO_TRADE={no_trade_ct} "
        f"[BM-12]zp={zp_nonzero} [BM-10]vs={vs_nonzero} [BM-3]+{bias_up}/-{bias_down} "
        f"elapsed={elapsed}s MODE={MODE}"
    )
    print(
        f"[OK] RESERVE={reserve} | WATCH={watch} | NO_TRADE={no_trade_ct} | "
        f"[BM-12]zp={zp_nonzero} | [BM-10]vs={vs_nonzero} | "
        f"[BM-3]+{bias_up}/-{bias_down} | elapsed={elapsed}s | MODE={MODE}"
    )
    print(f"  -> {LATEST_CSV}")


if __name__ == "__main__":
    main()
