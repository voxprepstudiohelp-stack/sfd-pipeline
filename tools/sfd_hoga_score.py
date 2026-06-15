import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sfd_hoga_score.py — BM-8 Pre-market Order Book Score v1.0
Fetches pre-market bid/ask ratio via KIS API and scores buy pressure.

Logic:
  hoga_ratio = total_bid_qty / total_ask_qty
  score:
    >= 2.0  -> +5pt (강한 매수 우위)
    >= 1.5  -> +3pt (매수 우위)
    >= 1.2  -> +1pt (약한 매수 우위)
    0.8~1.2 -> 0pt  (중립)
    < 0.8   -> -2pt (매도 우위)
    < 0.5   -> -4pt (강한 매도 우위)

Optimal run time: KST 08:30~08:55 (pre-market window)
Inputs:  KIS_APP_KEY, KIS_APP_SECRET, KIS_ACCOUNT_NO (env)
         outputs/latest/sfd_master_signal_latest.csv
Outputs: outputs/latest/sfd_hoga_latest.csv

Usage:
  py tools/sfd_hoga_score.py         (fetch live hoga)
  py tools/sfd_hoga_score.py --mock  (offline test)
  py tools/sfd_hoga_score.py --top 50 (top 50 WATCH+RESERVE only)

Version: v1.0
Author:  Claude Sonnet 4.6 (2026-06-07)
"""

import argparse
import os
import pathlib
import sys
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

_ENV = pathlib.Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV, override=True)

_HERE = Path(__file__).resolve().parent
_BASE = os.environ.get("SFD_BASE_DIR", str(_HERE.parent))
_LATEST = Path(_BASE) / "outputs" / "latest"

SIGNAL_CSV = _LATEST / "sfd_master_signal_latest.csv"
OUTPUT_CSV = _LATEST / "sfd_hoga_latest.csv"

KIS_APP_KEY    = os.environ.get("KIS_APP_KEY", "")
KIS_APP_SECRET = os.environ.get("KIS_APP_SECRET", "")
KIS_ACCOUNT_NO = os.environ.get("KIS_ACCOUNT_NO", "")

# KIS API endpoints
KIS_BASE_URL = "https://openapi.koreainvestment.com:9443"
TOKEN_URL    = f"{KIS_BASE_URL}/oauth2/tokenP"
HOGA_URL     = f"{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn"


def get_kis_token() -> str:
    try:
        import requests
        body = {
            "grant_type":  "client_credentials",
            "appkey":      KIS_APP_KEY,
            "appsecret":   KIS_APP_SECRET,
        }
        resp = requests.post(TOKEN_URL, json=body, timeout=10)
        data = resp.json()
        return data.get("access_token", "")
    except Exception as e:
        print(f"[BM-8] Token error: {e}")
        return ""


def fetch_hoga(ticker: str, token: str) -> dict:
    """Fetch pre-market order book for single ticker."""
    try:
        import requests
        headers = {
            "content-type":  "application/json",
            "authorization": f"Bearer {token}",
            "appkey":        KIS_APP_KEY,
            "appsecret":     KIS_APP_SECRET,
            "tr_id":         "FHKST01010200",
        }
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD":         ticker,
        }
        resp = requests.get(HOGA_URL, headers=headers, params=params, timeout=8)
        data = resp.json()

        if data.get("rt_cd") != "0":
            return {}

        output = data.get("output1", {})
        # Sum bid/ask quantities (10 levels)
        total_bid = sum(int(output.get(f"bidp_rsqn{i:02d}", 0) or 0) for i in range(1, 11))
        total_ask = sum(int(output.get(f"askp_rsqn{i:02d}", 0) or 0) for i in range(1, 11))

        return {
            "total_bid": total_bid,
            "total_ask": total_ask,
        }
    except Exception as e:
        return {}


def score_hoga(hoga_ratio: float) -> int:
    if hoga_ratio >= 2.0:  return +5
    if hoga_ratio >= 1.5:  return +3
    if hoga_ratio >= 1.2:  return +1
    if hoga_ratio >= 0.8:  return  0
    if hoga_ratio >= 0.5:  return -2
    return -4


def mock_data() -> list:
    import random
    random.seed(42)
    tickers = ["005930","006260","034020","052690","001440","171120",
               "000660","035420","035720","066570","207940","068270"]
    rows = []
    for t in tickers:
        bid = random.randint(50000, 500000)
        ask = random.randint(50000, 500000)
        ratio = round(bid / ask, 4) if ask > 0 else 1.0
        rows.append({
            "ticker":      t,
            "total_bid":   bid,
            "total_ask":   ask,
            "hoga_ratio":  ratio,
            "hoga_score":  score_hoga(ratio),
            "as_of_date":  str(date.today()),
        })
    return rows


def print_report(rows: list):
    print("\n" + "="*60)
    print("  BM-8 PRE-MARKET ORDER BOOK SCORE")
    print("="*60)
    print(f"  {'Ticker':<8} {'Bid':>10} {'Ask':>10} {'Ratio':>7} {'Score':>6}")
    print("  " + "-"*50)
    for r in sorted(rows, key=lambda x: x["hoga_score"], reverse=True):
        mark = "[HOT]" if r["hoga_score"] >= 3 else ("[DN]" if r["hoga_score"] <= -2 else "  ")
        print(f"  {r['ticker']:<8} {r['total_bid']:>10,} {r['total_ask']:>10,} "
              f"{r['hoga_ratio']:>7.3f} {r['hoga_score']:>+6}  {mark}")
    print("="*60)
    pos = sum(1 for r in rows if r["hoga_score"] > 0)
    neg = sum(1 for r in rows if r["hoga_score"] < 0)
    print(f"\n  Buy-side: {pos} tickers | Sell-side: {neg} tickers | Neutral: {len(rows)-pos-neg} tickers\n")


def run(mock: bool = False, top: int = 0):
    print(f"[BM-8] Hoga Score v1.0 | mock={mock} | top={top}")

    # Load tickers from signal file
    tickers = []
    if SIGNAL_CSV.exists():
        try:
            import pandas as pd
            sig = pd.read_csv(SIGNAL_CSV, dtype={"ticker": str})
            sig["ticker"] = sig["ticker"].astype(str).str.zfill(6)
            sig_col = "signal_label" if "signal_label" in sig.columns else "signal"
            # Priority: RESERVE_BUY > WATCH_ONLY > rest
            active = sig[sig[sig_col].isin(["RESERVE_BUY", "WATCH_ONLY"])]
            if top > 0:
                active = active.nlargest(top, "total_score")
            tickers = active["ticker"].tolist()
            print(f"[BM-8] Tickers: {len(tickers)} (RESERVE+WATCH)")
        except Exception as e:
            print(f"[BM-8] Signal load error: {e}")
    else:
        print(f"[BM-8] Signal CSV not found — using mock tickers")

    if mock:
        rows = mock_data()
        print(f"[BM-8] Mock mode: {len(rows)} tickers")
    else:
        if not KIS_APP_KEY:
            print("[BM-8] KIS_APP_KEY not set — cannot fetch hoga")
            print("  Set env: $env:KIS_APP_KEY = '...'")
            sys.exit(0)

        print("[BM-8] Getting KIS token...")
        token = get_kis_token()
        if not token:
            print("[BM-8] Token failed — check KIS credentials")
            sys.exit(1)
        print("[BM-8] Token OK")

        rows = []
        for i, ticker in enumerate(tickers):
            hoga = fetch_hoga(ticker, token)
            if not hoga:
                continue
            bid   = hoga.get("total_bid", 0)
            ask   = hoga.get("total_ask", 0)
            ratio = round(bid / ask, 4) if ask > 0 else 1.0
            rows.append({
                "ticker":     ticker,
                "total_bid":  bid,
                "total_ask":  ask,
                "hoga_ratio": ratio,
                "hoga_score": score_hoga(ratio),
                "as_of_date": str(date.today()),
            })
            if (i + 1) % 20 == 0:
                print(f"[BM-8] Progress: {i+1}/{len(tickers)}")
            time.sleep(0.05)  # KIS rate limit

        print(f"[BM-8] Fetched: {len(rows)}/{len(tickers)}")

    if not rows:
        print("[BM-8] No data")
        return

    print_report(rows)

    import pandas as pd
    _LATEST.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"[BM-8] Saved: {OUTPUT_CSV}")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BM-8 Hoga Score v1.0")
    parser.add_argument("--mock", action="store_true", help="Use mock data")
    parser.add_argument("--top",  type=int, default=0,
                        help="Limit to top N by score (0=all RESERVE+WATCH)")
    args = parser.parse_args()
    run(mock=args.mock, top=args.top)
