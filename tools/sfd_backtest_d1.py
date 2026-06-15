#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sfd_backtest_d1.py — Layer 3  v1.3
SFD D+1 사후검증 (실수익률 계산 활성화)

변경점 v1.2 → v1.3:
  - archive 경로 형식 통일: str(today/candidate) → strftime("%Y%m%d")
  - Layer4(sfd_finalize.py)와 YYYYMMDD 형식 일치

변경점 v1.1 → v1.2:
  - SIGNAL_FILE: sfd_signal_latest.csv → sfd_master_signal_latest.csv (파일명 수정)

변경점 v1.0 → v1.1:
  - archive_today_signal(): sfd_prev_close_latest.csv 도 함께 아카이빙
  - calc_return_d1(): return_d1 / win_flag 실값 계산
  - summarize(): avg_return_d1 / win_rate_d1 실값 산출
  - GRACEFUL DEGRADATION: archive prev_close 없으면 return_d1=None 유지

D+1 수익률 계산 공식:
  close_entry  = archive/{어제YYYYMMDD}/sfd_prev_close.csv  (신호 당일 종가)
  close_exit   = sfd_prev_close_latest.csv (Layer 1이 오늘 저장 = 오늘 종가)
  return_d1    = (close_exit - close_entry) / close_entry * 100  (%)
  win_flag     = return_d1 > 0

흐름도:
  IN  : outputs/archive/{어제YYYYMMDD}/sfd_signal.csv      (어제 신호)
  IN  : outputs/archive/{어제YYYYMMDD}/sfd_prev_close.csv  (어제 → 신호 당일 종가)
  IN  : outputs/latest/sfd_prev_close_latest.csv   (오늘 종가 = 오늘 Layer1 저장)
  OUT : outputs/latest/sfd_backtest_d1_latest.csv
  OUT : outputs/latest/sfd_backtest_summary_latest.json
  SIDE: outputs/archive/{오늘YYYYMMDD}/sfd_signal.csv       (오늘 신호 아카이빙)
  SIDE: outputs/archive/{오늘YYYYMMDD}/sfd_prev_close.csv   (오늘 종가 아카이빙)

버전: v1.3
작성: Claude Sonnet 4.6 (2026-05-27)
"""

import json
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

_HERE          = Path(__file__).resolve().parent
_PIPELINE_ROOT = _HERE.parent
_OUTPUTS       = _PIPELINE_ROOT / "outputs"
_LATEST        = _OUTPUTS / "latest"
_ARCHIVE       = _OUTPUTS / "archive"

SIGNAL_FILE      = _LATEST / "sfd_master_signal_latest.csv"
PREV_CLOSE_FILE  = _LATEST / "sfd_prev_close_latest.csv"
BACKTEST_OUT     = _LATEST / "sfd_backtest_d1_latest.csv"
SUMMARY_OUT      = _LATEST / "sfd_backtest_summary_latest.json"

TIER_ORDER = ["RESERVE_BUY", "WATCH_ONLY", "HOLD"]


def get_today() -> date:
    return date.today()


def archive_today_signal(today: date) -> None:
    archive_dir = _ARCHIVE / today.strftime("%Y%m%d")   # v1.3 수정: str() → strftime
    archive_dir.mkdir(parents=True, exist_ok=True)

    if SIGNAL_FILE.exists():
        dest_signal = archive_dir / "sfd_signal.csv"
        shutil.copy2(SIGNAL_FILE, dest_signal)
        print(f"[Layer3] Today's signal archived: {dest_signal}")
    else:
        print(f"[Layer3] WARN: {SIGNAL_FILE} not found — signal archiving skip")

    if PREV_CLOSE_FILE.exists():
        dest_close = archive_dir / "sfd_prev_close.csv"
        shutil.copy2(PREV_CLOSE_FILE, dest_close)
        print(f"[Layer3] Today's close archived: {dest_close}")
    else:
        print(f"[Layer3] WARN: {PREV_CLOSE_FILE} not found — prev_close archiving skip")


def find_yesterday_archive(today: date):
    for delta in range(1, 5):
        candidate = today - timedelta(days=delta)
        signal_path = _ARCHIVE / candidate.strftime("%Y%m%d") / "sfd_signal.csv"   # v1.3 수정
        close_path  = _ARCHIVE / candidate.strftime("%Y%m%d") / "sfd_prev_close.csv"  # v1.3 수정
        if signal_path.exists():
            print(f"[Layer3] Yesterday's signal found: {signal_path}")
            if close_path.exists():
                print(f"[Layer3] Yesterday's close found: {close_path}")
            else:
                print(f"[Layer3] WARN: Yesterday's prev_close not found — return_d1=None kept")
            return signal_path, close_path if close_path.exists() else None
    return None, None


def load_signal(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"ticker": str})
    required = {"ticker", "total_score", "signal_label"}
    missing = required - set(df.columns)
    if missing:
        # signal_label 없으면 signal 컬럼으로 대체 (compat shim)
        if "signal_label" in missing and "signal" in df.columns:
            df["signal_label"] = df["signal"]
            missing.discard("signal_label")
    if missing:
        raise ValueError(f"signal CSV 누락 컬럼: {missing}")
    df["ticker"] = df["ticker"].str.zfill(6)
    return df[["ticker", "total_score", "signal_label"]].copy()


def load_close(path: Path, col_alias: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"ticker": str})
    df["ticker"] = df["ticker"].str.zfill(6)
    candidates = ["close", "prev_close", "close_price", "종가", "adjusted_close"]
    close_col = None
    for c in candidates:
        if c in df.columns:
            close_col = c
            break
    if close_col is None:
        raise ValueError(f"종가 컬럼 미발견. 컬럼 목록: {list(df.columns)}")
    df = df[["ticker", close_col]].rename(columns={close_col: col_alias})
    df[col_alias] = pd.to_numeric(df[col_alias], errors="coerce")
    df = df.dropna(subset=[col_alias])
    return df


def calc_return_d1(prev_signal, entry_close, exit_close) -> pd.DataFrame:
    merged = prev_signal.merge(exit_close, on="ticker", how="left")
    merged["as_of_date"] = str(get_today())

    if entry_close is None:
        merged["close_entry"] = None
        merged["return_d1"]   = None
        merged["win_flag"]    = None
        merged["matched"]     = merged["close_exit"].notna()
        print("[Layer3] WARN: close_entry not found — return_d1=None (GRACEFUL)")
    else:
        merged = merged.merge(entry_close, on="ticker", how="left")
        merged["matched"] = merged["close_exit"].notna() & merged["close_entry"].notna()
        valid = merged["matched"]
        merged.loc[valid, "return_d1"] = (
            (merged.loc[valid, "close_exit"] - merged.loc[valid, "close_entry"])
            / merged.loc[valid, "close_entry"] * 100
        ).round(4)
        merged.loc[~valid, "return_d1"] = None
        merged["win_flag"] = merged["return_d1"].apply(
            lambda x: bool(x > 0) if pd.notna(x) else None
        )
    return merged


def summarize(df: pd.DataFrame) -> dict:
    summary = {
        "as_of_date":          str(get_today()),
        "total_signals":       int(len(df)),
        "matched_count":       int(df["matched"].sum()) if "matched" in df.columns else None,
        "return_d1_available": bool(df["return_d1"].notna().any()) if "return_d1" in df.columns else False,
        "tiers": {}
    }
    if "signal_label" not in df.columns:
        return summary

    for tier in TIER_ORDER:
        sub = df[df["signal_label"] == tier]
        if len(sub) == 0:
            summary["tiers"][tier] = {"count": 0, "avg_score": None,
                                       "avg_return_d1": None, "win_rate_d1": None}
            continue
        avg_score = float(sub["total_score"].astype(float).mean())
        ret_series = sub["return_d1"].dropna().astype(float) if "return_d1" in sub.columns else pd.Series(dtype=float)
        win_series = sub["win_flag"].dropna() if "win_flag" in sub.columns else pd.Series(dtype=bool)
        summary["tiers"][tier] = {
            "count":         int(len(sub)),
            "avg_score":     round(avg_score, 2),
            "avg_return_d1": round(float(ret_series.mean()), 4) if len(ret_series) > 0 else None,
            "win_rate_d1":   round(float(win_series.mean()) * 100, 2) if len(win_series) > 0 else None,
            "ret_sample_n":  int(len(ret_series)),
        }
    return summary


def run() -> int:
    today = get_today()
    print(f"[Layer3] sfd_backtest_d1 v1.3 START | as_of={today}")

    archive_today_signal(today)

    yesterday_signal_path, yesterday_close_path = find_yesterday_archive(today)
    if yesterday_signal_path is None:
        print("[Layer3] SKIP: Yesterday's signal archive not found (first deploy day or weekend/holiday)")
        return 0

    if not PREV_CLOSE_FILE.exists():
        print(f"[Layer3] SKIP: {PREV_CLOSE_FILE} 없음")
        return 0

    try:
        prev_signal = load_signal(yesterday_signal_path)
        exit_close  = load_close(PREV_CLOSE_FILE, col_alias="close_exit")
        entry_close = load_close(yesterday_close_path, col_alias="close_entry") \
                      if yesterday_close_path else None
    except Exception as e:
        print(f"[Layer3] ERROR data load failed: {e}", file=sys.stderr)
        return 1

    print(f"[Layer3] Yesterday's signals: {len(prev_signal)} | Today's close: {len(exit_close)}")
    if entry_close is not None:
        print(f"[Layer3] Yesterday's close(entry): {len(entry_close)} → return_d1 calculation enabled")

    result  = calc_return_d1(prev_signal, entry_close, exit_close)
    summary = summarize(result)

    _LATEST.mkdir(parents=True, exist_ok=True)
    result.to_csv(BACKTEST_OUT, index=False, encoding="utf-8-sig")
    SUMMARY_OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[Layer3] Verification DONE")
    print(f"  - Yesterday's signals: {summary['total_signals']}")
    print(f"  - Close matched: {summary['matched_count']}")
    print(f"  - return_d1 enabled: {summary['return_d1_available']}")
    for tier, stat in summary["tiers"].items():
        ret_str = f"{stat['avg_return_d1']:+.2f}%" if stat['avg_return_d1'] is not None else "N/A"
        win_str = f"{stat['win_rate_d1']:.1f}%"   if stat['win_rate_d1']  is not None else "N/A"
        print(f"  - {tier}: {stat['count']}건 | avg_score={stat['avg_score']} "
              f"| avg_return={ret_str} | win_rate={win_str}")
    print(f"  → {BACKTEST_OUT}")
    print(f"  → {SUMMARY_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
