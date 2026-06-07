#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sfd_dart_booster.py — BM-7 DART Disclosure Booster v1.1
Fetches recent DART filings and scores signal boost per ticker.

Boost logic:
  +5pt  : 자기주식 취득 (buyback)
  +4pt  : 유상증자 결정 취소 / 전환사채 상환
  +3pt  : 영업이익 흑자전환 공시 / 실적 서프라이즈
  +3pt  : 대규모 수주 / 계약 체결
  +2pt  : 배당 결정 (중간/특별배당)
  +2pt  : 임원 자사주 매입
  -5pt  : 유상증자 결정 (신주 발행)
  -4pt  : 대규모 손실 / 영업손실 전환
  -3pt  : 불성실공시 / 조회공시 요구
  -2pt  : 소송 / 분쟁 공시

Neutral (0pt) — matched before boost rules:
   0pt  : 임원ㆍ주요주주 소유상황 보고서 (정례 공시, 매매 신호 아님)

Inputs:  DART_API_KEY (env), outputs/latest/sfd_master_signal_latest.csv
Outputs: outputs/latest/sfd_dart_boost_latest.csv

Usage:
  py tools/sfd_dart_booster.py           (today's filings)
  py tools/sfd_dart_booster.py --days 3  (last 3 days)
  py tools/sfd_dart_booster.py --mock    (offline test)

Version: v1.1
Author:  Claude Sonnet 4.6 (2026-06-07)
"""

import argparse
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BASE = os.environ.get("SFD_BASE_DIR", str(_HERE.parent))
_LATEST = Path(_BASE) / "outputs" / "latest"

SIGNAL_CSV   = _LATEST / "sfd_master_signal_latest.csv"
OUTPUT_CSV   = _LATEST / "sfd_dart_boost_latest.csv"
DART_API_KEY = os.environ.get("DART_API_KEY", "")

# ── Neutral keywords: matched first, always return 0pt ───────────────────
# 임원ㆍ주요주주 소유상황 보고서는 정례 공시(의무 제출)로 매매 신호가 아님.
# "임원" 키워드가 BOOST_RULES +2pt 룰에 걸리지 않도록 우선 차단.
NEUTRAL_KEYWORDS = [
    "소유상황보고서",
    "소유상황 보고서",
    "임원ㆍ주요주주",
    "임원·주요주주",
    "주요주주특정증권",
]

# ── Boost rules: keyword -> score ────────────────────────────────────────
BOOST_RULES = [
    # Positive
    (["자기주식 취득", "자사주 취득"],                        +5),
    (["전환사채 상환", "유상증자 결정 취소", "증자 철회"],      +4),
    (["흑자전환", "영업이익 증가", "실적 호전", "어닝 서프라이즈"], +3),
    (["수주", "계약 체결", "공급계약", "MOU"],                +3),
    (["배당 결정", "중간배당", "특별배당"],                    +2),
    (["임원", "대표이사", "자사주 매입"],                     +2),
    # Negative
    (["유상증자 결정", "신주 발행"],                          -5),
    (["대규모 손실", "영업손실 전환", "적자전환"],              -4),
    (["불성실공시", "조회공시"],                              -3),
    (["소송", "분쟁", "가처분"],                             -2),
]

# Report type priorities
REPORT_PRIORITY = {
    "A": 3,   # 정기공시
    "B": 5,   # 주요사항보고
    "C": 4,   # 발행공시
    "D": 2,   # 지분공시
    "E": 1,   # 기타공시
    "F": 3,   # 외부감사
    "G": 2,   # 펀드
    "H": 1,   # 자산유동화
    "I": 1,   # 거래소공시
    "J": 1,   # 공정공시
}


def score_report(report_name: str) -> int:
    """Score a single DART report by matching boost rules."""
    for nkw in NEUTRAL_KEYWORDS:
        if nkw in report_name:
            return 0, [f"{nkw}(neutral)"]
    total = 0
    matched = []
    for keywords, score in BOOST_RULES:
        for kw in keywords:
            if kw in report_name:
                total += score
                matched.append(f"{kw}({score:+d})")
                break
    return total, matched


def fetch_dart_filings(tickers: list, start_date: str, end_date: str) -> dict:
    """
    Fetch DART filings for given tickers.
    Returns {stock_code: [filing_list]}
    """
    if not DART_API_KEY:
        print("[BM-7] DART_API_KEY not set — skipping API fetch")
        return {}

    try:
        import requests
    except ImportError:
        print("[BM-7] requests not installed")
        return {}

    results = {}
    base_url = "https://opendart.fss.or.kr/api/list.json"

    for ticker in tickers:
        try:
            params = {
                "crtfc_key": DART_API_KEY,
                "stock_code": ticker,
                "bgn_de":     start_date,
                "end_de":     end_date,
                "page_count": 20,
            }
            resp = requests.get(base_url, params=params, timeout=10)
            data = resp.json()
            if data.get("status") == "000":
                results[ticker] = data.get("list", [])
            time.sleep(0.1)  # rate limit
        except Exception as e:
            print(f"[BM-7] WARN: {ticker} fetch error: {e}")

    return results


def mock_filings() -> dict:
    """Mock DART filings for offline testing."""
    return {
        "005930": [
            {"report_nm": "자기주식 취득 결정", "rcept_dt": "20260607"},
            {"report_nm": "주요사항보고서(자기주식취득결정)", "rcept_dt": "20260607"},
        ],
        "006260": [
            {"report_nm": "수주 계약 체결", "rcept_dt": "20260606"},
        ],
        "001440": [
            {"report_nm": "유상증자 결정", "rcept_dt": "20260607"},
        ],
        "034020": [
            {"report_nm": "영업이익 흑자전환 공시", "rcept_dt": "20260605"},
        ],
        "000660": [
            {"report_nm": "배당 결정", "rcept_dt": "20260606"},
        ],
    }


def compute_boosts(filings: dict) -> list:
    """Compute dart_boost score per ticker."""
    rows = []
    for ticker, reports in filings.items():
        if not reports:
            continue
        total_boost = 0
        all_matched = []
        report_names = []

        for r in reports:
            name = r.get("report_nm", "")
            report_names.append(name)
            score, matched = score_report(name)
            total_boost += score
            all_matched.extend(matched)

        # Cap: -8 ~ +8
        total_boost = max(min(total_boost, 8), -8)

        rows.append({
            "ticker":      ticker.zfill(6),
            "dart_boost":  total_boost,
            "report_count": len(reports),
            "matched_rules": ", ".join(all_matched) if all_matched else "",
            "latest_report": report_names[0] if report_names else "",
            "as_of_date":  str(date.today()),
        })

    rows.sort(key=lambda x: x["dart_boost"], reverse=True)
    return rows


def print_report(rows: list):
    print("\n" + "="*65)
    print("  BM-7 DART DISCLOSURE BOOSTER")
    print("="*65)
    print(f"  {'Ticker':<8} {'Boost':>6} {'Reports':>8}  Latest Filing")
    print("  " + "-"*60)
    for r in rows:
        boost = r["dart_boost"]
        mark = "🔥" if boost >= 3 else ("⬇️" if boost <= -3 else "  ")
        print(f"  {r['ticker']:<8} {boost:>+6}  {r['report_count']:>6}  "
              f"{mark} {r['latest_report'][:35]}")
    print("="*65)

    pos = [r for r in rows if r["dart_boost"] > 0]
    neg = [r for r in rows if r["dart_boost"] < 0]
    print(f"\n  Positive boost: {len(pos)}종목 | Negative boost: {len(neg)}종목")
    print()


def run(days: int = 1, mock: bool = False):
    print(f"[BM-7] DART Booster v1.0 | days={days} | mock={mock}")

    # Load signal tickers
    tickers = []
    if SIGNAL_CSV.exists():
        try:
            import pandas as pd
            sig = pd.read_csv(SIGNAL_CSV, dtype={"ticker": str})
            tickers = sig["ticker"].astype(str).str.zfill(6).tolist()
            print(f"[BM-7] Signal tickers loaded: {len(tickers)}")
        except Exception as e:
            print(f"[BM-7] Signal load error: {e}")
    else:
        print(f"[BM-7] Signal CSV not found: {SIGNAL_CSV}")
        print("[BM-7] Running with mock tickers")

    # Date range
    end_dt   = date.today()
    start_dt = end_dt - timedelta(days=days)
    start_str = start_dt.strftime("%Y%m%d")
    end_str   = end_dt.strftime("%Y%m%d")
    print(f"[BM-7] Date range: {start_str} ~ {end_str}")

    # Fetch filings
    if mock:
        filings = mock_filings()
        print(f"[BM-7] Mock filings: {len(filings)} tickers")
    else:
        if not tickers:
            print("[BM-7] No tickers to fetch")
            sys.exit(0)
        # Limit to RESERVE+WATCH for efficiency
        try:
            import pandas as pd
            sig = pd.read_csv(SIGNAL_CSV, dtype={"ticker": str})
            sig["ticker"] = sig["ticker"].astype(str).str.zfill(6)
            sig_col = "signal_label" if "signal_label" in sig.columns else "signal"
            active = sig[sig[sig_col].isin(["RESERVE_BUY", "WATCH_ONLY"])]
            tickers = active["ticker"].tolist()
            print(f"[BM-7] Active signal tickers: {len(tickers)}")
        except Exception:
            pass
        filings = fetch_dart_filings(tickers, start_str, end_str)
        print(f"[BM-7] Filings received: {len(filings)} tickers with data")

    # Compute boosts
    rows = compute_boosts(filings)
    if not rows:
        print("[BM-7] No boost data computed")
        # Save empty file
        import pandas as pd
        pd.DataFrame(columns=["ticker","dart_boost","report_count",
                               "matched_rules","latest_report","as_of_date"]
                    ).to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
        return

    print_report(rows)

    # Save CSV
    import pandas as pd
    _LATEST.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"[BM-7] Saved: {OUTPUT_CSV}")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BM-7 DART Booster v1.0")
    parser.add_argument("--days", type=int, default=1,
                        help="Lookback days (default: 1)")
    parser.add_argument("--mock", action="store_true",
                        help="Use mock data (offline test)")
    args = parser.parse_args()
    run(days=args.days, mock=args.mock)
