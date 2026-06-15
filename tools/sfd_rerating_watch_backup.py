"""
sfd_rerating_watch.py  v1.1
SFD Pipeline — Layer 2.5 (Re-rating Watch Board)
리레이팅(밸류에이션 재설정) 가능성 종목 조기 포착

Schedule : 메인 파이프라인 Layer 2 실행 직후 추가
Author   : Claude (Anthropic) — SFD Main Architect
Date     : 2026-05-22

[검증된 스키마]
SIGNAL  : sfd_master_signal_latest.csv
  → ticker, name, total_score, judge, tech_score, rsi, rsi_score,
     ma_align, ma_score, vol_ratio, vol_score, news_score,
     investor_score, theme_score, fetch_date, fetched_at

NEWS    : sfd_news_score_latest.csv  (보조 — article_count, top_tags)
  → ticker, stock_name, news_score, article_count, top_tags

PRICE   : sfd_prev_close_latest.csv  (등락률 계산용)
  → ticker, name, prev_close, prev_open, prev_high, prev_low,
     prev_volume, prev_value, fetch_date, fetched_at, data_status

[출력]
  outputs/latest/sfd_rerating_watch_latest.csv
"""

import os
import pandas as pd
import numpy as np
from datetime import date, timedelta

# ══════════════════════════════════════════════
# 파일 경로 (실제 검증 완료)
# ══════════════════════════════════════════════
SIGNAL_FILE  = "outputs/latest/sfd_master_signal_latest.csv"
NEWS_FILE    = "outputs/latest/sfd_news_score_latest.csv"
PRICE_FILE   = "outputs/latest/sfd_prev_close_latest.csv"
HISTORY_FILE = "data/sfd_price_history.csv"
OUTPUT_FILE  = "outputs/latest/sfd_rerating_watch_latest.csv"

TODAY        = date.today().isoformat()
HISTORY_DAYS = 10  # 히스토리 보관 영업일

# ══════════════════════════════════════════════
# 리레이팅 조건 임계값
# ══════════════════════════════════════════════
TH = {
    "total_score_min":   70,    # ① 종합 신호 점수
    "news_score_min":    5,     # ② 뉴스 감성 점수 (SIGNAL 내장값)
    "vol_ratio_min":     1.5,   # ③ 거래량 비율 (평균 대비)
    "rsi_min":           55,    # ④-A RSI 모멘텀
    "ma_align_min":      3,     # ④-B 이동평균 정배열 수
    "intraday_pct_min":  2.0,   # 당일 등락률 보조 필터 (%)
    "min_flags":         3,     # WATCH 등급 최소 조건 수
    "strong_flags":      4,     # STRONG 등급 조건 수
}


# ──────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────
def safe_load(path: str, label: str) -> pd.DataFrame | None:
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
        print(f"[OK] {label}: {len(df)} rows")
        return df
    except FileNotFoundError:
        print(f"[WARN] file not found: {path}")
        return None
    except Exception as e:
        print(f"[ERROR] {label} load failed: {e}")
        return None


# ──────────────────────────────────────────────
# [1] 당일 등락률 계산 (prev_open → prev_close)
# ──────────────────────────────────────────────
def calc_intraday(price_df: pd.DataFrame) -> pd.DataFrame:
    df = price_df[["ticker", "prev_close", "prev_open", "prev_volume"]].copy()
    df["intraday_pct"] = (
        (df["prev_close"] - df["prev_open"])
        / df["prev_open"].replace(0, np.nan)
        * 100
    ).round(2)
    return df[["ticker", "prev_close", "prev_volume", "intraday_pct"]]


# ──────────────────────────────────────────────
# [2] 가격 히스토리 누적 (5일 모멘텀용)
# ──────────────────────────────────────────────
def update_price_history(price_df: pd.DataFrame) -> pd.DataFrame:
    snap = price_df[["ticker", "prev_close"]].copy()
    snap.columns = ["ticker", "close"]
    snap["date"] = TODAY

    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    if os.path.exists(HISTORY_FILE):
        hist = pd.read_csv(HISTORY_FILE, encoding="utf-8-sig")
        hist = hist[hist["date"] != TODAY]  # 오늘 중복 제거
    else:
        hist = pd.DataFrame(columns=["ticker", "close", "date"])

    hist = pd.concat([hist, snap], ignore_index=True)

    # 오래된 데이터 정리
    cutoff = (date.today() - timedelta(days=HISTORY_DAYS * 2)).isoformat()
    hist   = hist[hist["date"] >= cutoff]
    hist.to_csv(HISTORY_FILE, index=False, encoding="utf-8-sig")

    print(f"[OK] price history: {hist['date'].nunique()} days accumulated")
    return hist


def calc_momentum_5d(history: pd.DataFrame) -> pd.DataFrame:
    """히스토리에서 5일 모멘텀 및 연속 상승일 계산"""
    if history.empty:
        return pd.DataFrame(columns=["ticker", "momentum_5d", "consec_up"])

    history = history.sort_values(["ticker", "date"])
    results = []
    for ticker, grp in history.groupby("ticker"):
        grp   = grp.tail(6)
        closes = grp["close"].values
        if len(closes) >= 2:
            momentum_5d = round((closes[-1] - closes[0]) / closes[0] * 100, 2)
        else:
            momentum_5d = 0.0
        daily_chg = pd.Series(closes).pct_change().dropna().values
        consec_up = 0
        for c in daily_chg[::-1]:
            if c > 0:
                consec_up += 1
            else:
                break
        results.append({"ticker": ticker, "momentum_5d": momentum_5d, "consec_up": consec_up})

    return pd.DataFrame(results)


# ──────────────────────────────────────────────
# [3] 리레이팅 조건 평가 (4개 조건)
# ──────────────────────────────────────────────
def evaluate_flags(row: pd.Series) -> tuple[int, str, str]:
    flags = []

    if pd.notna(row.get("total_score")) and row["total_score"] >= TH["total_score_min"]:
        flags.append(f"SIG≥{TH['total_score_min']}")

    if pd.notna(row.get("news_score")) and row["news_score"] >= TH["news_score_min"]:
        flags.append(f"NEWS≥{TH['news_score_min']}")

    if pd.notna(row.get("vol_ratio")) and row["vol_ratio"] >= TH["vol_ratio_min"]:
        flags.append(f"VOL≥{TH['vol_ratio_min']}x")

    rsi_ok      = pd.notna(row.get("rsi"))      and row["rsi"]      >= TH["rsi_min"]
    ma_align_ok = pd.notna(row.get("ma_align")) and row["ma_align"] >= TH["ma_align_min"]
    if rsi_ok or ma_align_ok:
        detail = f"RSI≥{TH['rsi_min']}" if rsi_ok else f"MA_ALIGN≥{TH['ma_align_min']}"
        flags.append(detail)

    n        = len(flags)
    flag_str = "|".join(flags) if flags else "-"

    if n >= TH["strong_flags"]:
        grade = "STRONG"
    elif n >= TH["min_flags"]:
        grade = "WATCH"
    elif n == 2:
        grade = "MONITOR"
    else:
        grade = "-"

    return n, flag_str, grade


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────
def build_rerating_watch():
    print(f"\n{'='*55}")
    print(f"SFD Re-rating Watch Board v1.1  |  {TODAY}")
    print(f"{'='*55}\n")

    signal_df = safe_load(SIGNAL_FILE, "Signal(sfd_master_signal)")
    news_df   = safe_load(NEWS_FILE,   "News(sfd_news_score)")
    price_df  = safe_load(PRICE_FILE,  "Price(sfd_prev_close)")

    if signal_df is None:
        print("[FATAL] Signal file not found — exiting")
        return

    base = signal_df[[
        "ticker", "name", "total_score", "judge",
        "news_score", "vol_ratio", "rsi", "ma_align",
        "investor_score", "tech_score", "fetch_date"
    ]].copy()

    # ── 숫자 컬럼 타입 강제 변환 (str → float, 오류는 NaN)
    numeric_cols = ["total_score", "news_score", "vol_ratio", "rsi",
                    "ma_align", "investor_score", "tech_score"]
    for col in numeric_cols:
        if col in base.columns:
            base[col] = pd.to_numeric(base[col], errors="coerce")

    if price_df is not None:
        intraday = calc_intraday(price_df)
        base     = base.merge(intraday, on="ticker", how="left")
        history  = update_price_history(price_df)
        momentum = calc_momentum_5d(history)
        base     = base.merge(momentum, on="ticker", how="left")
    else:
        base["intraday_pct"] = np.nan
        base["momentum_5d"]  = np.nan
        base["consec_up"]    = np.nan

    if news_df is not None:
        news_aux = news_df[["ticker", "article_count", "top_tags"]].copy()
        news_aux["ticker"] = news_aux["ticker"].astype(str).str.zfill(6)
        base = base.merge(news_aux, on="ticker", how="left")
    else:
        base["article_count"] = np.nan
        base["top_tags"]      = ""

    eval_result = base.apply(
        lambda r: pd.Series(
            evaluate_flags(r),
            index=["flags_met", "flag_detail", "rerating_grade"]
        ),
        axis=1
    )
    base = pd.concat([base, eval_result], axis=1)

    watch = (
        base[base["rerating_grade"] != "-"]
          .sort_values(["flags_met", "total_score"], ascending=[False, False])
          .reset_index(drop=True)
    )
    watch["date"] = TODAY

    out_cols = [
        "ticker", "name", "rerating_grade", "flags_met", "flag_detail",
        "total_score", "news_score", "vol_ratio", "rsi", "ma_align",
        "intraday_pct", "momentum_5d", "consec_up",
        "article_count", "top_tags", "judge", "investor_score",
        "fetch_date", "date"
    ]
    out_cols = [c for c in out_cols if c in watch.columns]
    watch    = watch[out_cols]

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    watch.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")

    print(f"\n{'─'*55}")
    print(f"[DONE] saved: {len(watch)} tickers → {OUTPUT_FILE}")
    print(f"\n[ Grade summary ]")
    grade_counts = watch["rerating_grade"].value_counts()
    for g in ["STRONG", "WATCH", "MONITOR"]:
        cnt = grade_counts.get(g, 0)
        print(f"  {g:8s}: {cnt:3d}  {'█' * min(cnt, 30)}")

    print(f"\n[ STRONG tickers TOP 10 ]")
    strong = watch[watch["rerating_grade"] == "STRONG"].head(10)
    if strong.empty:
        print("  none")
    else:
        print(strong[["ticker", "name", "total_score",
                       "news_score", "vol_ratio", "flag_detail"]].to_string(index=False))

    print(f"\n[ WATCH tickers TOP 10 ]")
    w_top = watch[watch["rerating_grade"] == "WATCH"].head(10)
    if w_top.empty:
        print("  none")
    else:
        print(w_top[["ticker", "name", "total_score",
                      "flag_detail"]].to_string(index=False))
    print(f"{'─'*55}\n")


if __name__ == "__main__":
    build_rerating_watch()
