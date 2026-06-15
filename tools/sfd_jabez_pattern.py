#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sfd_jabez_pattern.py — BM-1 Jabez Pattern Detector v1.0
Detects Jabez accumulation pattern from technical + volume data.

Jabez pattern criteria (야베스 매매법 기반):
  1. Price below 20MA (oversold zone)
  2. RSI < 40 (oversold signal)
  3. Volume spike: today volume > 20-day avg volume * 1.5
  4. Price closes ABOVE open (buying pressure)
  5. Lower shadow >= 1.5x body (hammer candle)

Score: each condition = +1, max 5
JABEZ_SIGNAL triggered when score >= 4

Inputs:  outputs/latest/sfd_technical_latest.csv
Outputs: outputs/latest/sfd_jabez_latest.csv

Version: v1.0
Author:  Claude Sonnet 4.6 (2026-06-07)
"""

import os
import sys
from pathlib import Path

import pandas as pd

_HERE = Path(__file__).resolve().parent
_BASE = os.environ.get("SFD_BASE_DIR", str(_HERE.parent))
_LATEST = Path(_BASE) / "outputs" / "latest"

TECH_CSV   = _LATEST / "sfd_technical_latest.csv"
OUTPUT_CSV = _LATEST / "sfd_jabez_latest.csv"

JABEZ_THRESHOLD = 4   # min score to flag as JABEZ
MIN_VOLUME_MULT = 1.5  # volume spike multiplier


def score_jabez(row) -> int:
    score = 0
    try:
        # 1. Price below 20MA
        close = float(row.get("close", 0) or 0)
        ma20  = float(row.get("ma20", 0) or 0)
        if ma20 > 0 and close < ma20:
            score += 1

        # 2. RSI < 40
        rsi = float(row.get("rsi", 50) or 50)
        if rsi < 40:
            score += 1

        # 3. Volume spike
        vol     = float(row.get("volume", 0) or 0)
        vol_avg = float(row.get("volume_ma20", 0) or 0)
        if vol_avg > 0 and vol > vol_avg * MIN_VOLUME_MULT:
            score += 1

        # 4. Close > Open (bullish candle)
        open_p = float(row.get("open", 0) or 0)
        if open_p > 0 and close > open_p:
            score += 1

        # 5. Hammer candle: lower shadow >= 1.5x body
        low_p  = float(row.get("low", 0) or 0)
        high_p = float(row.get("high", 0) or 0)
        body   = abs(close - open_p)
        lower_shadow = min(close, open_p) - low_p if low_p > 0 else 0
        if body > 0 and lower_shadow >= body * 1.5:
            score += 1
    except Exception:
        pass
    return score


def run():
    print("[JABEZ] Jabez Pattern Detector v1.0")
    if not TECH_CSV.exists():
        print(f"[SKIP] Technical CSV not found: {TECH_CSV}")
        sys.exit(0)

    df = pd.read_csv(TECH_CSV, dtype={"ticker": str})
    df["ticker"] = df["ticker"].astype(str).str.zfill(6)
    print(f"[JABEZ] Loaded {len(df)} rows")

    df["jabez_score"]  = df.apply(score_jabez, axis=1)
    df["jabez_signal"] = df["jabez_score"] >= JABEZ_THRESHOLD

    hits = df[df["jabez_signal"]]
    print(f"[JABEZ] Pattern hits: {len(hits)} / {len(df)}")

    cols = ["ticker"] + (["name"] if "name" in df.columns else []) + ["jabez_score", "jabez_signal"]
    if "total_score" in df.columns:
        cols.append("total_score")

    hits_out = hits[cols].sort_values("jabez_score", ascending=False)
    if len(hits_out) > 0:
        print(hits_out.head(10).to_string(index=False))

    df[cols].to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"[JABEZ] Saved: {OUTPUT_CSV}")


if __name__ == "__main__":
    run()
