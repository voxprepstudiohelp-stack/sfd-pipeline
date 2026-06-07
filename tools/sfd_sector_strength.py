#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sfd_sector_strength.py — BM-6 Sector Strength Ranker v1.0
Standalone sector strength analysis tool.

Logic:
  1. Fetch KRX sector ETF 5-day returns vs KOSPI benchmark
  2. Rank sectors by relative strength score
  3. Compute dynamic multiplier for signal_aggregator
  4. Output: sfd_sector_strength_latest.json + console report

ETF coverage: 13 sectors including Physical AI (v1.6)

Usage:
  py tools/sfd_sector_strength.py           (fetch + report)
  py tools/sfd_sector_strength.py --days 10 (10-day window)
  py tools/sfd_sector_strength.py --mock    (offline test)

Version: v1.0
Author: Claude Sonnet 4.6 (2026-06-07)
"""

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BASE = os.environ.get("SFD_BASE_DIR", str(_HERE.parent))
_LATEST = Path(_BASE) / "outputs" / "latest"
OUTPUT_JSON = _LATEST / "sfd_sector_strength_latest.json"

# ── Sector ETF map ────────────────────────────────────────────
SECTOR_ETF_MAP = {
    "Physical AI/로봇/자율주행":    "394670",  # KODEX K-로봇액티브
    "반도체/반도체장비":            "091160",  # KODEX 반도체
    "원전/방산":                    "329200",  # KODEX K-방산&우주
    "조선/해양":                    "466920",  # KODEX K-조선해양
    "2차전지/배터리소재/이차전지":  "305720",  # KODEX 2차전지산업
    "소프트웨어/IT서비스/IT솔루션": "266360",  # KODEX K-게임&엔터
    "바이오/헬스케어":              "091230",  # TIGER 200 헬스케어
    "자동차/자동차부품":            "091180",  # KODEX 자동차
    "전력/전선/변압기":             "381170",  # KODEX K-뉴딜&그린인프라
    "신재생에너지/태양광풍력":      "381170",  # (동일 ETF)
    "철강/금속/비철금속":           "140710",  # KODEX 철강
    "건설/건자재":                  "102960",  # KODEX 건설
    "화학/정밀화학":                "100220",  # KODEX 화학
}
KOSPI_ETF = "069500"  # KODEX 200

# Static base multipliers (fallback)
BASE_MULTIPLIER = {
    "Physical AI/로봇/자율주행":    1.25,
    "반도체/반도체장비":            1.20,
    "원전/방산":                    1.20,
    "2차전지/배터리소재/이차전지":  1.20,
    "조선/해양":                    1.20,
    "소프트웨어/IT서비스/IT솔루션": 1.15,
    "신재생에너지/태양광풍력":      1.15,
    "바이오/헬스케어":              1.10,
    "자동차/자동차부품":            1.05,
    "철강/금속/비철금속":           1.05,
    "전력/전선/변압기":             1.05,
    "건설/건자재":                  1.00,
    "화학/정밀화학":                1.00,
}

TIER_LABELS = {
    (1.15, 99):  "🔥 SUPER",
    (1.05, 1.15): "⬆️  STRONG",
    (0.95, 1.05): "➡️  NEUTRAL",
    (0.0,  0.95): "⬇️  WEAK",
}


def get_tier(score: float) -> str:
    for (lo, hi), label in TIER_LABELS.items():
        if lo <= score < hi:
            return label
    return "➡️  NEUTRAL"


def fetch_etf_returns(days: int = 5) -> dict:
    """Fetch ETF returns. Returns {ticker: return_pct} or {} on failure."""
    try:
        import yfinance as yf
    except ImportError:
        print("[BM-6] yfinance not installed. Run: pip install yfinance")
        return {}

    period_map = {5: "10d", 10: "20d", 20: "30d"}
    period = period_map.get(days, "10d")

    all_etfs = list(set(SECTOR_ETF_MAP.values()) | {KOSPI_ETF})
    krx = [f"{t}.KS" for t in all_etfs]

    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            raw = yf.download(krx, period=period, interval="1d",
                              auto_adjust=True, progress=False, threads=True)
        if raw.empty:
            print("[BM-6] No ETF data received")
            return {}

        import pandas as pd
        close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw
        close = close.dropna(how="all")

        # Get last N trading days
        trading_days = close.dropna(how="all").index
        if len(trading_days) < 2:
            print("[BM-6] Insufficient trading days")
            return {}

        n = min(days, len(trading_days) - 1)
        latest = close.iloc[-1]
        base   = close.iloc[-(n+1)]
        ret    = ((latest - base) / base * 100).fillna(0)

        return {col.replace(".KS", ""): round(float(val), 3)
                for col, val in ret.items()}

    except Exception as e:
        print(f"[BM-6] ETF fetch error: {e}")
        return {}


def mock_returns() -> dict:
    """Mock data for offline testing."""
    return {
        "394670": 4.2,   # Physical AI
        "091160": 2.8,   # 반도체
        "329200": 6.1,   # 원전/방산
        "466920": 5.3,   # 조선
        "305720": -1.2,  # 2차전지
        "266360": 1.5,   # 소프트웨어
        "091230": 0.8,   # 바이오
        "091180": 3.1,   # 자동차
        "381170": 2.2,   # 전력
        "140710": -0.5,  # 철강
        "102960": 1.1,   # 건설
        "100220": -0.3,  # 화학
        "069500": 1.8,   # KOSPI
    }


def compute_scores(etf_returns: dict, days: int) -> list:
    kospi_ret = etf_returns.get(KOSPI_ETF, 0)
    results = []

    seen_etfs = set()
    for sector, etf in SECTOR_ETF_MAP.items():
        if etf in seen_etfs:
            # 같은 ETF 중복 섹터는 동일 점수 복사
            prev = next((r for r in results if r["etf"] == etf), None)
            rel_score = prev["relative_score"] if prev else 1.0
        else:
            etf_ret = etf_returns.get(etf, None)
            if etf_ret is None or kospi_ret == 0:
                rel_score = 1.0  # neutral fallback
            else:
                rel_score = round((1 + etf_ret/100) / (1 + kospi_ret/100), 4)
            seen_etfs.add(etf)

        base_mult = BASE_MULTIPLIER.get(sector, 1.0)
        # Dynamic multiplier: base * relative_score, capped [0.85, 1.35]
        dynamic_mult = round(min(max(base_mult * rel_score, 0.85), 1.35), 4)

        etf_ret_val = etf_returns.get(etf)
        results.append({
            "sector":          sector,
            "etf":             etf,
            "etf_return_pct":  round(etf_ret_val, 3) if etf_ret_val is not None else None,
            "kospi_return_pct": round(kospi_ret, 3),
            "relative_score":  rel_score,
            "base_multiplier": base_mult,
            "dynamic_multiplier": dynamic_mult,
            "tier":            get_tier(rel_score),
            "window_days":     days,
        })

    results.sort(key=lambda x: x["relative_score"], reverse=True)
    return results


def print_report(results: list, kospi_ret: float, days: int):
    print("\n" + "="*65)
    print(f"  BM-6 SECTOR STRENGTH RANKER  ({days}-day window)")
    print(f"  KOSPI baseline: {kospi_ret:+.2f}%")
    print("="*65)
    print(f"  {'Rank':<4} {'Sector':<32} {'ETF Ret':>7} {'RelScore':>9} {'DynMult':>8} {'Tier'}")
    print("  " + "-"*61)

    seen = set()
    rank = 1
    for r in results:
        key = r["sector"]
        if key in seen:
            continue
        seen.add(key)
        ret_str = f"{r['etf_return_pct']:+.2f}%" if r['etf_return_pct'] is not None else "  N/A"
        print(f"  {rank:<4} {r['sector']:<32} {ret_str:>7} "
              f"{r['relative_score']:>9.4f} {r['dynamic_multiplier']:>8.4f} "
              f"  {r['tier']}")
        rank += 1

    print("="*65)
    print()

    # Top 3 / Bottom 3 summary
    valid = [r for r in results if r['etf_return_pct'] is not None]
    if valid:
        print("  🔥 TOP 3 강세 섹터:")
        for r in valid[:3]:
            print(f"     {r['sector']} ({r['etf_return_pct']:+.2f}% | x{r['dynamic_multiplier']})")
        print()
        print("  ⬇️  BOTTOM 3 약세 섹터:")
        for r in valid[-3:]:
            print(f"     {r['sector']} ({r['etf_return_pct']:+.2f}% | x{r['dynamic_multiplier']})")
    print()


def run(days: int = 5, mock: bool = False):
    print(f"[BM-6] Sector Strength Ranker v1.0 | window={days}d | mock={mock}")

    etf_returns = mock_returns() if mock else fetch_etf_returns(days)
    if not etf_returns and not mock:
        print("[BM-6] Falling back to static multipliers (no ETF data)")

    kospi_ret = etf_returns.get(KOSPI_ETF, 0)
    results = compute_scores(etf_returns, days)

    print_report(results, kospi_ret, days)

    # Save JSON
    _LATEST.mkdir(parents=True, exist_ok=True)
    output = {
        "generated_at":    str(date.today()),
        "window_days":     days,
        "kospi_return_pct": round(kospi_ret, 3),
        "sectors":         results,
        "multiplier_map":  {r["sector"]: r["dynamic_multiplier"] for r in results},
    }
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"[BM-6] Saved: {OUTPUT_JSON}")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BM-6 Sector Strength Ranker v1.0")
    parser.add_argument("--days", type=int, default=5,
                        help="Return window in trading days (default: 5)")
    parser.add_argument("--mock", action="store_true",
                        help="Use mock data (offline test)")
    args = parser.parse_args()
    run(days=args.days, mock=args.mock)
