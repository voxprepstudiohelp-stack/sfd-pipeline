# sfd_signal_aggregator.py | v2.4 | Claude (Anthropic) 2026-05-30
# Deploy to: D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline\tools\sfd_signal_aggregator.py
#
# [v2.4 변경사항 — v2.3 대비 최소 수술]
# - load_tech_detail_map(): tech_total_score(max 65), vol_gap_score, std_bar_score 추가 로드
# - main() tech_score 계산: tech_total_score 존재 시 우선 적용 (L2.7 v1.1 연동)
#   └ tech_total_score 있으면 → t_score = tech_total_score (max 65)
#   └ tech_total_score 없고 tech_detail_score 있으면 → t_score = tech_detail_score (max 40, v2.3 호환)
#   └ 둘 다 없으면 → v2.2 fallback (fdr 직접 호출)
# - 출력 컬럼 추가: vol_gap_score, std_bar_score, vol_gap_label, tech_ver
# - THRESHOLD: 90/70 상향 조정 (v2.4 tech_total 65pt 확장 반영, RESERVE 8~12개 목표)
#
# [v2.3 → v2.4 점수 구조]
# v2.3: tech_score = poc+sr+rsi+ma          → max 40   [L2.7 v1.0]
# v2.4: tech_score = poc+sr+rsi+ma+vg+sb   → max 65   [L2.7 v1.1] ★
#        fallback1 = poc+sr+rsi+ma          → max 40   [L2.7 v1.0 CSV 있을 때]
#        fallback2 = rsi+ma+vol             → max 40   [L2.7 없을 때, v2.2]

import os
import sys
import time
import logging
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import FinanceDataReader as fdr

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

LATEST_CSV       = os.path.join(LATEST_DIR, "sfd_master_signal_latest.csv")
INPUT_CSV        = os.path.join(INPUT_DIR,  "sfd_master_signal_input.csv")
LOG_PATH         = os.path.join(LATEST_DIR, "sfd_signal_aggregator.log")
PREV_CLOSE_CSV   = os.path.join(LATEST_DIR, "sfd_prev_close_latest.csv")
INVESTOR_CSV     = os.path.join(LATEST_DIR, "sfd_investor_flow_latest.csv")
NEWS_SCORE_CSV   = os.path.join(LATEST_DIR, "sfd_news_score_latest.csv")
FUNDAMENTAL_CSV  = os.path.join(LATEST_DIR, "sfd_fundamental_latest.csv")
TECH_DETAIL_CSV  = os.path.join(LATEST_DIR, "sfd_technical_latest.csv")

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


# ── 최근 거래일 탐색 ───────────────────────────────────────────────────────────
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


# ── 기술적 데이터 수집 (v2.2 fallback용) ──────────────────────────────────────
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
    except: return None


# ── 스코어 함수 (v2.2 fallback용) ─────────────────────────────────────────────
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


# ── [v2.4] tech_detail_map 로드 — tech_total_score 우선 ★ ─────────────────────
def load_tech_detail_map() -> dict:
    """
    sfd_technical_latest.csv → {ticker: {effective_tech, ...}}
    v1.1: tech_total_score(max 65) 우선, 없으면 tech_detail_score(max 40) fallback
    """
    if not os.path.exists(TECH_DETAIL_CSV):
        logging.warning(f"[v2.4] TECH_DETAIL_CSV not found: {TECH_DETAIL_CSV}")
        logging.warning("[v2.4] Fallback to v2.2 basic tech_score")
        return {}
    try:
        df = pd.read_csv(TECH_DETAIL_CSV, encoding="utf-8-sig", dtype={"ticker": str})
        if "ticker" not in df.columns or "tech_detail_score" not in df.columns:
            logging.warning(f"[v2.4] TECH_DETAIL_CSV missing cols: {df.columns.tolist()}")
            return {}

        has_total = "tech_total_score" in df.columns
        has_vg    = "vol_gap_score"    in df.columns
        has_sb    = "std_bar_score"    in df.columns
        has_label = "vol_gap_label"    in df.columns
        logging.info(f"[v2.4] L2.7 cols: total={has_total} vg={has_vg} sb={has_sb}")

        tech_map = {}
        for _, row in df.iterrows():
            t = str(row["ticker"]).strip().zfill(6)

            # ★ tech_total_score(v1.1) 우선 — 없으면 tech_detail_score(v1.0) fallback
            if has_total and not pd.isna(row.get("tech_total_score")):
                effective_tech  = float(row["tech_total_score"])
                tech_source_ver = "L2.7_v1.1"
            else:
                effective_tech  = float(row.get("tech_detail_score", 0))
                tech_source_ver = "L2.7_v1.0"

            tech_map[t] = {
                "effective_tech":    effective_tech,
                "tech_total_score":  float(row.get("tech_total_score",  0)) if has_total else 0.0,
                "tech_detail_score": float(row.get("tech_detail_score", 0)),
                "vol_gap_score":     float(row.get("vol_gap_score",     0)) if has_vg   else 0.0,
                "std_bar_score":     float(row.get("std_bar_score",     0)) if has_sb   else 0.0,
                "vol_gap_label":     str(row.get("vol_gap_label", ""))      if has_label else "",
                "poc_score":         float(row.get("poc_score",         0)),
                "sr_score":          float(row.get("sr_score",          0)),
                "rsi":               float(row.get("rsi",               50)),
                "ma_label":          str(row.get("ma_label",            "")),
                "tech_source_ver":   tech_source_ver,
            }

        v11_cnt = sum(1 for v in tech_map.values() if v["tech_source_ver"] == "L2.7_v1.1")
        logging.info(f"[v2.4] tech_map: {len(tech_map)} tickers | v1.1={v11_cnt} v1.0={len(tech_map)-v11_cnt}")
        return tech_map

    except Exception as e:
        logging.error(f"[v2.4] tech_map load failed: {e}")
        return {}


# ── 보조 데이터 로드 ──────────────────────────────────────────────────────────
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


# ── 메인 ──────────────────────────────────────────────────────────────────────
def main():
    logging.info("=== sfd_signal_aggregator v2.4 START ===")
    logging.info(f"BASE_DIR:   {BASE_DIR}")
    logging.info(f"LATEST_DIR: {LATEST_DIR}")
    logging.info(f"THRESHOLD:  RESERVE={THRESHOLD_RESERVE} WATCH={THRESHOLD_WATCH}")

    trade_date = find_recent_trade_date()
    logging.info(f"trade_date: {trade_date}")

    for path, label in [(INPUT_CSV, "INPUT_CSV"), (PREV_CLOSE_CSV, "PREV_CLOSE_CSV")]:
        if not os.path.exists(path):
            logging.error(f"{label} not found: {path}"); return

    input_df    = pd.read_csv(INPUT_CSV,      encoding="utf-8-sig", dtype={"ticker": str})
    prev_df     = pd.read_csv(PREV_CLOSE_CSV, encoding="utf-8-sig", dtype={"ticker": str})
    investor_df = pd.read_csv(INVESTOR_CSV,   encoding="utf-8-sig", dtype={"ticker": str}) \
                  if os.path.exists(INVESTOR_CSV) else None

    news_score_map  = load_news_score_map()
    fund_map        = load_fund_score_map()
    tech_detail_map = load_tech_detail_map()

    use_tech_detail = len(tech_detail_map) > 0
    logging.info(f"[v2.4] use_tech_detail={use_tech_detail} | tickers_in_map={len(tech_detail_map)}")

    if "prev_value" in prev_df.columns:
        prev_df["prev_value"] = pd.to_numeric(prev_df["prev_value"], errors="coerce").fillna(0)

    # v2.5: ticker 컬럼명 유연 처리 (ticker / stock_code / 첫 번째 컬럼)
    _tcol = next((c for c in ["ticker","stock_code"] if c in input_df.columns), input_df.columns[0])
    tickers = input_df[_tcol].dropna().astype(str).str.zfill(6).unique().tolist()
    logging.info(f"tickers: {len(tickers)}")

    results = []
    for ticker in tickers:

        # ── [v2.4] tech_score 결정 ─────────────────────────────────────────
        if use_tech_detail and ticker in tech_detail_map:
            td          = tech_detail_map[ticker]
            t_score     = td["effective_tech"]     # ★ total(65) or detail(40) 자동 선택
            rsi_val     = td["rsi"]
            ma_align    = td["ma_label"]
            poc_s       = td["poc_score"]
            sr_s        = td["sr_score"]
            vg_score    = td["vol_gap_score"]
            sb_score    = td["std_bar_score"]
            vg_label    = td["vol_gap_label"]
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

        else:
            # v2.2 fallback
            tech = get_technical_data(ticker, trade_date)
            if tech is None: continue
            t_score     = score_rsi(tech["rsi"]) + score_ma(tech["ma_short"], tech["ma_mid"], tech["ma_long"]) + score_volume(tech["volume"], tech["vol_avg"])
            rsi_val     = tech["rsi"]
            ma_align    = "up" if tech["ma_short"] and tech["ma_mid"] and tech["ma_long"] \
                                   and tech["ma_short"] > tech["ma_mid"] > tech["ma_long"] else "down"
            vol_ratio   = round(tech["volume"] / tech["vol_avg"], 2) if tech["vol_avg"] and tech["vol_avg"] > 0 else 0
            poc_s = sr_s = vg_score = sb_score = 0
            vg_label    = ""
            tech_source = "v2.2"
            tech_ver    = "v2.2_fallback"

        n_score  = score_news(ticker, news_score_map)
        i_score  = score_investor(ticker, investor_df)
        th_score = score_theme(ticker, prev_df)
        f_score  = score_fundamental(ticker, fund_map)
        total    = t_score + n_score + i_score + th_score + f_score
        signal   = classify_signal(total)

        name_row = input_df[input_df["ticker"] == ticker]
        name     = name_row.iloc[0].get("name", "") if not name_row.empty else ""

        results.append({
            "fetch_date":      trade_date,
            "fetch_time":      fetch_time,
            "ticker":          ticker,
            "name":            name,
            "signal":          signal,
            "total_score":     total,
            "tech_score":      t_score,
            "poc_score":       poc_s,
            "sr_score":        sr_s,
            "tech_source":     tech_source,
            "news_score":      round(n_score, 2),
            "investor_score":  i_score,
            "theme_score":     th_score,
            "fund_score":      round(f_score, 2),
            "rsi":             rsi_val,
            "ma_align":        ma_align,
            "vol_ratio":       vol_ratio,
            "mode":            MODE,
            "vol_gap_score":   vg_score,
            "std_bar_score":   sb_score,
            "vol_gap_label":   vg_label,
            "tech_ver":        tech_ver,
        })

    df_out = pd.DataFrame(results).sort_values("total_score", ascending=False).reset_index(drop=True)
    df_out.to_csv(LATEST_CSV, index=False, encoding="utf-8-sig")
    df_out.to_csv(os.path.join(HISTORY_DIR, f"sfd_master_signal_{trade_date}.csv"), index=False, encoding="utf-8-sig")

    elapsed = int(time.time() - START_TIME)
    reserve = len(df_out[df_out["signal"] == "RESERVE_BUY"])
    watch   = len(df_out[df_out["signal"] == "WATCH_ONLY"])
    l27_cnt = len(df_out[df_out["tech_source"] == "L2.7"])
    v11_cnt = len(df_out[df_out["tech_ver"]    == "L2.7_v1.1"])

    logging.info(f"DONE | RESERVE={reserve} WATCH={watch} L2.7={l27_cnt}/{len(df_out)} v1.1={v11_cnt} elapsed={elapsed}s MODE={MODE}")
    print(f"[OK] RESERVE={reserve} | WATCH={watch} | L2.7={l27_cnt}/{len(df_out)} | v1.1={v11_cnt} | elapsed={elapsed}s | MODE={MODE}")
    print(f"  -> {LATEST_CSV}")


if __name__ == "__main__":
    main()

