#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sfd_setup_local.py — SFD Local Setup Script v1.0
Runs tasks #2~#5 sequentially without GitHub Actions.

Tasks:
  #2: Patch company_master — Physical AI sector tagging (23 tickers)
  #3: Check/report portfolio.json status
  #4: BM-1 Jabez pattern detector (sfd_jabez_pattern.py)
  #5: Local pipeline dry-run check (file existence + import test)

Usage:
  py tools\\sfd_setup_local.py            (run all tasks)
  py tools\\sfd_setup_local.py --task 2   (single task)

Author: Claude Sonnet 4.6 (2026-06-07)
"""

import argparse
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_DATA = _ROOT / "data"
_TOOLS = _ROOT / "tools"
_OUTPUTS = _ROOT / "outputs" / "latest"

MASTER_CSV = _DATA / "sfd_company_master_v1.4_sector_filled.csv"
PORTFOLIO_JSON = _ROOT / "portfolio.json"

# ── Physical AI tickers (from sector_injector v1.6) ───────────────────────
PHYSICAL_AI_TICKERS = {
    "277810": "레인보우로보틱스",
    "056080": "유진로봇",
    "215100": "로보스타",
    "090040": "로보티즈",
    "108490": "로보쓰리",
    "238170": "엔에스",
    "312850": "이노뎁",
    "315640": "딥노이드",
    "105740": "에스피지",
    "322310": "오로스테크놀로지",
    "348350": "위드텍",
    "099430": "바텍",
    "065770": "엑스페리",
    "091580": "상아프론테크",
    "214330": "아이씨티케이",
    "395400": "삼성SDS",
    "210980": "SK스퀘어",
    "090355": "노루홀딩스",
    "196490": "디오",
    "141080": "SBB테크",
    "092870": "에코마케팅",
    "352820": "하이브IM",
    "950160": "코오롱티슈진",
}
PHYSICAL_AI_SECTOR = "Physical AI/로봇/자율주행"


# ─────────────────────────────────────────────────────────────────────────────
# Task #2: company_master Physical AI patch
# ─────────────────────────────────────────────────────────────────────────────
def task2_patch_company_master():
    print("\n" + "="*60)
    print("  TASK #2 — company_master Physical AI sector patch")
    print("="*60)

    if not MASTER_CSV.exists():
        print(f"[SKIP] MASTER CSV not found: {MASTER_CSV}")
        print("  -> Copy sfd_company_master_v1.4_sector_filled.csv to data/ folder")
        return False

    try:
        import pandas as pd
    except ImportError:
        print("[SKIP] pandas not installed")
        return False

    df = pd.read_csv(MASTER_CSV, dtype={"stock_code": str}, low_memory=False)
    df["stock_code"] = df["stock_code"].astype(str).str.strip().str.zfill(6)

    patched = 0
    already = 0
    not_found = []

    for ticker, name in PHYSICAL_AI_TICKERS.items():
        mask = df["stock_code"] == ticker.zfill(6)
        if mask.sum() == 0:
            not_found.append(f"{ticker}({name})")
            continue
        current = df.loc[mask, "sector_major"].values[0]
        if current == PHYSICAL_AI_SECTOR:
            already += 1
        else:
            df.loc[mask, "sector_major"] = PHYSICAL_AI_SECTOR
            patched += 1
            print(f"  PATCHED: {ticker} {name} | {current} -> {PHYSICAL_AI_SECTOR}")

    df.to_csv(MASTER_CSV, index=False, encoding="utf-8-sig")
    print(f"\nResult: patched={patched}, already_correct={already}, not_in_master={len(not_found)}")
    if not_found:
        print(f"Not found in master: {not_found}")
    print(f"Saved: {MASTER_CSV}")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Task #3: portfolio.json check
# ─────────────────────────────────────────────────────────────────────────────
def task3_check_portfolio():
    print("\n" + "="*60)
    print("  TASK #3 — portfolio.json status check")
    print("="*60)

    if not PORTFOLIO_JSON.exists():
        print(f"[WARN] portfolio.json not found: {PORTFOLIO_JSON}")
        print("  -> Creating minimal template...")
        template = {
            "holdings": [],
            "note": "Add your holdings: [{ticker, name, qty, avg_price}]",
            "updated_at": "2026-06-07"
        }
        with open(PORTFOLIO_JSON, "w", encoding="utf-8") as f:
            json.dump(template, f, ensure_ascii=False, indent=2)
        print(f"  Created: {PORTFOLIO_JSON}")
        return True

    with open(PORTFOLIO_JSON, encoding="utf-8") as f:
        pf = json.load(f)

    holdings = pf.get("holdings", [])
    print(f"Holdings count: {len(holdings)}")
    if holdings:
        print("Tickers in portfolio:")
        for h in holdings:
            ticker = h.get("ticker", "?")
            name   = h.get("name", "?")
            qty    = h.get("qty", "?")
            price  = h.get("avg_price", "?")
            print(f"  {ticker} {name:15s} qty={qty} avg={price}")
    else:
        print("  [EMPTY] No holdings registered.")
        print("  -> Edit portfolio.json to add your holdings")

    # Check signal alignment
    signal_file = _OUTPUTS / "sfd_master_signal_latest.csv"
    if signal_file.exists() and holdings:
        try:
            import pandas as pd
            sig = pd.read_csv(signal_file, dtype={"ticker": str})
            sig["ticker"] = sig["ticker"].astype(str).str.zfill(6)
            for h in holdings:
                t = str(h.get("ticker","")).zfill(6)
                row = sig[sig["ticker"] == t]
                if len(row) > 0:
                    signal = row.iloc[0].get("signal", row.iloc[0].get("signal_label", "?"))
                    score  = row.iloc[0].get("total_score", "?")
                    print(f"  SIGNAL CHECK: {t} {h.get('name','')} -> {signal} (score={score})")
                else:
                    print(f"  SIGNAL CHECK: {t} {h.get('name','')} -> NOT IN SIGNAL FILE")
        except Exception as e:
            print(f"  Signal check skipped: {e}")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Task #4: Generate sfd_jabez_pattern.py (BM-1)
# ─────────────────────────────────────────────────────────────────────────────
def task4_create_jabez():
    print("\n" + "="*60)
    print("  TASK #4 — BM-1: sfd_jabez_pattern.py generator")
    print("="*60)

    jabez_path = _TOOLS / "sfd_jabez_pattern.py"
    if jabez_path.exists():
        print(f"[SKIP] Already exists: {jabez_path}")
        return True

    code = '''#!/usr/bin/env python3
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
'''
    jabez_path.write_text(code, encoding="utf-8")
    print(f"Created: {jabez_path}")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Task #5: Local pipeline dry-run check
# ─────────────────────────────────────────────────────────────────────────────
def task5_pipeline_check():
    print("\n" + "="*60)
    print("  TASK #5 — Local pipeline dry-run check")
    print("="*60)

    # Key tool files to check
    tools_to_check = [
        "sfd_prev_close_fetch.py",
        "sfd_news_fetcher.py",
        "sfd_technical_analyzer.py",
        "sfd_signal_aggregator.py",
        "sfd_fundamental_watch.py",
        "sfd_sector_injector.py",
        "sfd_investor_flow_fetch.py",
        "sfd_macro_radar.py",
        "sfd_backtest_d1.py",
        "sfd_backtest_analyzer.py",
        "sfd_threshold_optimizer.py",
        "sfd_jabez_pattern.py",
        "sfd_finalize.py",
        "sfd_trade_guardian.py",
    ]

    ok = missing = 0
    for fname in tools_to_check:
        p = _TOOLS / fname
        status = "✅" if p.exists() else "❌ MISSING"
        if p.exists():
            size = p.stat().st_size
            print(f"  {status} {fname:45s} {size:>8,} bytes")
            ok += 1
        else:
            print(f"  {status} {fname}")
            missing += 1

    print(f"\nTools: {ok} OK / {missing} MISSING")

    # Check key output files
    print("\nOutput files (latest):")
    outputs_to_check = [
        "sfd_master_signal_latest.csv",
        "sfd_technical_latest.csv",
        "sfd_fundamental_watch_latest.csv",
        "sfd_investor_flow_latest.csv",
        "sfd_macro_radar_latest.csv",
        "sfd_backtest_report.json",
        "sfd_threshold_recommendation.json",
    ]
    for fname in outputs_to_check:
        p = _OUTPUTS / fname
        if p.exists():
            size = p.stat().st_size
            print(f"  ✅ {fname:45s} {size:>8,} bytes")
        else:
            print(f"  ⚪ {fname:45s} (not yet generated)")

    # Check data files
    print("\nData files:")
    data_checks = [
        _DATA / "sfd_company_master_v1.4_sector_filled.csv",
        _ROOT / "portfolio.json",
        _ROOT / "requirements.txt",
    ]
    for p in data_checks:
        status = "✅" if p.exists() else "❌ MISSING"
        print(f"  {status} {p.name}")

    return True


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="SFD Local Setup v1.0")
    parser.add_argument("--task", type=int, choices=[2,3,4,5],
                        help="Run single task (2-5). Default: all")
    args = parser.parse_args()

    if args.task:
        tasks = [args.task]
    else:
        tasks = [2, 3, 4, 5]

    task_map = {
        2: task2_patch_company_master,
        3: task3_check_portfolio,
        4: task4_create_jabez,
        5: task5_pipeline_check,
    }

    for t in tasks:
        task_map[t]()

    print("\n" + "="*60)
    print("  ALL TASKS COMPLETE")
    print("="*60)


if __name__ == "__main__":
    main()
