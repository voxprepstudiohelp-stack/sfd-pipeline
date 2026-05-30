# -*- coding: utf-8 -*-
"""
sfd_rerating_watch.py v1.3
SFD Pipeline — Layer 2.5 (Re-rating Watch Board)
리레이팅(밸류에이션 재설정) 가능성 종목 조기 포착

수정: Claude (Anthropic) 2026-05-30
  v1.2 → v1.3
  ① FATAL 수정: master_signal_latest.csv 컬럼 순서 의존성 제거
     → 컬럼 존재 여부만 체크, 없으면 0으로 대체 (cloud 순서 무관)
  ② SFD_BASE_DIR 환경변수 기반 경로 (클라우드 호환)
  ③ signal 컬럼: RESERVE_BUY / WATCH_ONLY 둘 다 허용
"""

import os
import pandas as pd
import numpy as np
from datetime import date, timedelta

_BASE = os.environ.get(
    "SFD_BASE_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)
_LATEST = os.path.join(_BASE, "outputs", "latest")
_DATA   = os.path.join(_BASE, "data")

SIGNAL_FILE  = os.path.join(_LATEST, "sfd_master_signal_latest.csv")
NEWS_FILE    = os.path.join(_LATEST, "sfd_news_score_latest.csv")
PRICE_FILE   = os.path.join(_LATEST, "sfd_prev_close_latest.csv")
HISTORY_FILE = os.path.join(_DATA,   "sfd_price_history.csv")
OUTPUT_FILE  = os.path.join(_LATEST, "sfd_rerating_watch_latest.csv")

TODAY        = date.today().isoformat()
HISTORY_DAYS = 10

TH = {
    "total_score_min":  70,
    "news_score_min":    5,
    "vol_ratio_min":   1.5,
    "rsi_min":          55,
    "ma_align_min":      3,
    "intraday_pct_min":2.0,
    "min_flags":         3,
    "strong_flags":      4,
}


def safe_load(path: str, label: str):
    try:
        df = pd.read_csv(path, encoding="utf-8-sig", dtype={"ticker": str})
        df["ticker"] = df["ticker"].astype(str).str.strip().str.zfill(6)
        print(f"[OK] {label}: {len(df)}행")
        return df
    except FileNotFoundError:
        print(f"[WARN] 파일 없음: {path}")
        return None
    except Exception as e:
        print(f"[ERROR] {label} 로드 실패: {e}")
        return None


def safe_col(df: pd.DataFrame, col: str, default=0.0):
    """컬럼이 없으면 default 값으로 채운 Series 반환 (v1.3 핵심 수정)"""
    if col in df.columns:
        return df[col]
    print(f"[WARN] 컬럼 없음 '{col}' → {default}으로 대체")
    return pd.Series([default] * len(df), index=df.index)


def calc_intraday(price_df: pd.DataFrame) -> pd.DataFrame:
    df = price_df[["ticker", "prev_close", "prev_open", "prev_volume"]].copy()
    df["intraday_pct"] = (
        (df["prev_close"] - df["prev_open"])
        / df["prev_open"].replace(0, np.nan)
        * 100
    ).round(2)
    return df[["ticker", "prev_close", "prev_volume", "intraday_pct"]]


def update_price_history(price_df: pd.DataFrame) -> pd.DataFrame:
    snap = price_df[["ticker", "prev_close"]].copy()
    snap.columns = ["ticker", "close"]
    snap["date"] = TODAY

    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    if os.path.exists(HISTORY_FILE):
        hist = pd.read_csv(HISTORY_FILE, encoding="utf-8-sig", dtype={"ticker": str})
        hist = hist[hist["date"] != TODAY]
    else:
        hist = pd.DataFrame(columns=["ticker", "close", "date"])

    hist = pd.concat([hist, snap], ignore_index=True)
    cutoff = (date.today() - timedelta(days=HISTORY_DAYS * 2)).isoformat()
    hist = hist[hist["date"] >= cutoff]
    hist.to_csv(HISTORY_FILE, index=False, encoding="utf-8-sig")
    print(f"[OK] 가격 히스토리: {hist['date'].nunique()}일치 누적")
    return hist


def calc_momentum_5d(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame(columns=["ticker", "momentum_5d", "consec_up"])

    history = history.sort_values(["ticker", "date"])
    results = []
    for ticker, grp in history.groupby("ticker"):
        grp = grp.tail(6)
        closes = grp["close"].values
        momentum_5d = round((closes[-1] - closes[0]) / closes[0] * 100, 2) \
                      if len(closes) >= 2 else 0.0
        daily_chg = pd.Series(closes).pct_change().dropna().values
        consec_up = 0
        for c in daily_chg[::-1]:
            if c > 0:
                consec_up += 1
            else:
                break
        results.append({"ticker": ticker, "momentum_5d": momentum_5d,
                         "consec_up": consec_up})
    return pd.DataFrame(results)


def evaluate_flags(row: pd.Series):
    flags = []
    if pd.notna(row.get("total_score")) and row["total_score"] >= TH["total_score_min"]:
        flags.append(f"SIG>={TH['total_score_min']}")
    if pd.notna(row.get("news_score")) and row["news_score"] >= TH["news_score_min"]:
        flags.append(f"NEWS>={TH['news_score_min']}")
    if pd.notna(row.get("vol_ratio")) and row["vol_ratio"] >= TH["vol_ratio_min"]:
        flags.append(f"VOL>={TH['vol_ratio_min']}x")
    rsi_ok      = pd.notna(row.get("rsi"))      and row["rsi"]      >= TH["rsi_min"]
    ma_align_ok = pd.notna(row.get("ma_align")) and row["ma_align"] >= TH["ma_align_min"]
    if rsi_ok or ma_align_ok:
        flags.append(f"RSI>={TH['rsi_min']}" if rsi_ok else f"MA_ALIGN>={TH['ma_align_min']}")

    n = len(flags)
    flag_str = "|".join(flags) if flags else "-"
    grade = ("STRONG" if n >= TH["strong_flags"]
             else "WATCH" if n >= TH["min_flags"]
             else "MONITOR" if n == 2 else "-")
    return n, flag_str, grade


def build_rerating_watch():
    print(f"\n{'='*55}")
    print(f"SFD Re-rating Watch Board v1.3 | {TODAY}")
    print(f"{'='*55}\n")

    signal_df = safe_load(SIGNAL_FILE, "Signal(sfd_master_signal)")
    news_df   = safe_load(NEWS_FILE,   "News(sfd_news_score)")
    price_df  = safe_load(PRICE_FILE,  "Price(sfd_prev_close)")

    if signal_df is None:
        print("[FATAL] Signal 파일 없음 — 종료")
        return

    # v1.3 핵심: 컬럼 flexible 로딩 (순서/존재 무관)
    base_cols = ["ticker"]
    for col, default in [
        ("name",        ""),
        ("total_score", 0.0),
        ("signal",      "HOLD"),
        ("news_score",  0.0),
        ("vol_ratio",   0.0),
        ("rsi",         0.0),
        ("ma_align",    0),
    ]:
        signal_df[col] = safe_col(signal_df, col, default)
        base_cols.append(col)

    base = signal_df[base_cols].copy()

    if news_df is not None:
        news_sub = news_df[["ticker"] +
                   [c for c in ["news_score", "article_cnt"]
                    if c in news_df.columns]].copy()
        if "news_score" not in base.columns or base["news_score"].sum() == 0:
            base = base.drop(columns=["news_score"], errors="ignore")
            base = base.merge(news_sub, on="ticker", how="left")

    if price_df is not None:
        intra = calc_intraday(price_df)
        base = base.merge(intra, on="ticker", how="left")
        history = update_price_history(price_df)
        momentum = calc_momentum_5d(history)
        base = base.merge(momentum, on="ticker", how="left")

    watch = base[base["signal"].isin(["RESERVE_BUY", "WATCH_ONLY"])].copy()
    if watch.empty:
        print("[INFO] 대상 종목 없음 (RESERVE_BUY/WATCH_ONLY)")
        watch.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
        return

    results = []
    for _, row in watch.iterrows():
        n, flags, grade = evaluate_flags(row)
        results.append({**row.to_dict(), "flag_count": n,
                        "flags": flags, "rerating_grade": grade})

    out = pd.DataFrame(results)
    out = out[out["rerating_grade"] != "-"].sort_values(
        ["rerating_grade", "total_score"], ascending=[True, False]
    )
    out.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")

    strong    = (out["rerating_grade"] == "STRONG").sum()
    watch_cnt = (out["rerating_grade"] == "WATCH").sum()
    monitor   = (out["rerating_grade"] == "MONITOR").sum()
    print(f"\n[결과] STRONG={strong} / WATCH={watch_cnt} / MONITOR={monitor}")
    print(f"✅ 저장: {OUTPUT_FILE}")


if __name__ == "__main__":
    build_rerating_watch()
