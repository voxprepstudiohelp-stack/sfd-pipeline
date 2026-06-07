#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sfd_backtest_analyzer.py — SFD Backtest Analyzer v1.0
Offline analysis tool for accumulated D+1 backtest data.

Inputs:
  outputs/archive/{YYYYMMDD}/sfd_signal.csv   - daily signals
  outputs/archive/{YYYYMMDD}/sfd_prev_close.csv - entry prices
  outputs/latest/sfd_prev_close_latest.csv    - latest close (for most recent day)

Outputs:
  outputs/latest/sfd_backtest_report.json     - full analysis report
  outputs/latest/sfd_backtest_report.csv      - per-ticker summary

Usage:
  py tools/sfd_backtest_analyzer.py           (scan all archive dates)
  py tools/sfd_backtest_analyzer.py --days 30 (last 30 days only)
  py tools/sfd_backtest_analyzer.py --report  (print summary to console)

Version: v1.0
Author: Claude Sonnet 4.6 (2026-06-07)
"""

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

_HERE = Path(__file__).resolve().parent
_PIPELINE_ROOT = _HERE.parent
_OUTPUTS = _PIPELINE_ROOT / "outputs"
_LATEST = _OUTPUTS / "latest"
_ARCHIVE = _OUTPUTS / "archive"

REPORT_JSON = _LATEST / "sfd_backtest_report.json"
REPORT_CSV = _LATEST / "sfd_backtest_report.csv"

TIER_ORDER = ["RESERVE_BUY", "WATCH_ONLY", "HOLD"]

# Score bands for distribution analysis
SCORE_BANDS = [
    ("95-100", 95, 100),
    ("90-95",  90, 95),
    ("85-90",  85, 90),
    ("80-85",  80, 85),
    ("70-80",  70, 80),
    ("60-70",  60, 70),
    ("<60",     0, 60),
]

# Threshold simulation grid
RESERVE_RANGE = range(83, 98, 2)   # 83, 85, 87, 89, 91, 93, 95, 97
WATCH_RANGE   = range(63, 78, 2)   # 63, 65, 67, 69, 71, 73, 75, 77


def load_ticker_col(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize ticker column: support both 'ticker' and 'stock_code'."""
    if "ticker" in df.columns:
        df["ticker"] = df["ticker"].astype(str).str.zfill(6)
        return df
    if "stock_code" in df.columns:
        df = df.rename(columns={"stock_code": "ticker"})
        df["ticker"] = df["ticker"].astype(str).str.zfill(6)
        return df
    raise ValueError(f"No ticker/stock_code column. Columns: {list(df.columns)}")


def load_signal(path: Path) -> pd.DataFrame | None:
    try:
        df = pd.read_csv(path, dtype=str)
        df = load_ticker_col(df)
        # Support both signal_label and signal column names
        if "signal_label" not in df.columns and "signal" in df.columns:
            df["signal_label"] = df["signal"]
        if "signal_label" not in df.columns or "total_score" not in df.columns:
            return None
        df["total_score"] = pd.to_numeric(df["total_score"], errors="coerce")
        # Optional sector column
        if "sector" not in df.columns:
            df["sector"] = "UNKNOWN"
        return df[["ticker", "signal_label", "total_score", "sector"]].copy()
    except Exception as e:
        print(f"[ANALYZER] WARN: signal load failed {path}: {e}")
        return None


def load_close(path: Path, alias: str) -> pd.DataFrame | None:
    try:
        df = pd.read_csv(path, dtype=str)
        df = load_ticker_col(df)
        candidates = ["close", "prev_close", "close_price", "adjusted_close"]
        col = next((c for c in candidates if c in df.columns), None)
        if col is None:
            return None
        df = df[["ticker", col]].rename(columns={col: alias})
        df[alias] = pd.to_numeric(df[alias], errors="coerce")
        return df.dropna(subset=[alias])
    except Exception as e:
        print(f"[ANALYZER] WARN: close load failed {path}: {e}")
        return None


def scan_archive_dates(days_limit: int | None = None) -> list[str]:
    """Return sorted list of YYYYMMDD archive directories."""
    if not _ARCHIVE.exists():
        return []
    dirs = sorted([d.name for d in _ARCHIVE.iterdir()
                   if d.is_dir() and d.name.isdigit() and len(d.name) == 8])
    if days_limit:
        cutoff = (date.today() - timedelta(days=days_limit)).strftime("%Y%m%d")
        dirs = [d for d in dirs if d >= cutoff]
    return dirs


def build_paired_records(archive_dates: list[str]) -> pd.DataFrame:
    """
    For each archive date D, pair:
      entry_close = archive/D/sfd_prev_close.csv  (close on signal day)
      exit_close  = archive/D+1/sfd_prev_close.csv (next trading day close)
    Returns combined DataFrame with return_d1, win_flag columns.
    """
    records = []
    for i, date_str in enumerate(archive_dates):
        signal_path = _ARCHIVE / date_str / "sfd_signal.csv"
        entry_path  = _ARCHIVE / date_str / "sfd_prev_close.csv"

        signal_df = load_signal(signal_path)
        entry_df  = load_close(entry_path, "close_entry")

        if signal_df is None or signal_df.empty:
            continue

        # Find exit close: next available archive date
        exit_df = None
        for j in range(i + 1, min(i + 5, len(archive_dates))):
            exit_path = _ARCHIVE / archive_dates[j] / "sfd_prev_close.csv"
            if exit_path.exists():
                exit_df = load_close(exit_path, "close_exit")
                break

        # Also try latest file as exit for most recent date
        if exit_df is None and i == len(archive_dates) - 1:
            latest_close = _LATEST / "sfd_prev_close_latest.csv"
            if latest_close.exists():
                exit_df = load_close(latest_close, "close_exit")

        merged = signal_df.copy()
        merged["date"] = date_str

        if entry_df is not None:
            merged = merged.merge(entry_df, on="ticker", how="left")
        else:
            merged["close_entry"] = None

        if exit_df is not None:
            merged = merged.merge(exit_df, on="ticker", how="left")
        else:
            merged["close_exit"] = None

        # Calculate return
        if "close_entry" in merged.columns and "close_exit" in merged.columns:
            valid = merged["close_entry"].notna() & merged["close_exit"].notna() & (merged["close_entry"] > 0)
            merged.loc[valid, "return_d1"] = (
                (merged.loc[valid, "close_exit"] - merged.loc[valid, "close_entry"])
                / merged.loc[valid, "close_entry"] * 100
            )
            merged.loc[valid, "win_flag"] = merged.loc[valid, "return_d1"] > 0
        else:
            merged["return_d1"] = None
            merged["win_flag"] = None

        records.append(merged)

    if not records:
        return pd.DataFrame()
    return pd.concat(records, ignore_index=True)


def analyze_tiers(df: pd.DataFrame) -> dict:
    """Tier-level performance stats."""
    result = {}
    for tier in TIER_ORDER:
        sub = df[df["signal_label"] == tier]
        valid = sub[sub["return_d1"].notna()]
        result[tier] = {
            "count": int(len(sub)),
            "valid_count": int(len(valid)),
            "avg_return_d1": round(float(valid["return_d1"].mean()), 3) if len(valid) > 0 else None,
            "median_return_d1": round(float(valid["return_d1"].median()), 3) if len(valid) > 0 else None,
            "win_rate": round(float(valid["win_flag"].mean()) * 100, 1) if len(valid) > 0 else None,
            "max_return": round(float(valid["return_d1"].max()), 2) if len(valid) > 0 else None,
            "min_return": round(float(valid["return_d1"].min()), 2) if len(valid) > 0 else None,
        }
    return result


def analyze_score_bands(df: pd.DataFrame) -> dict:
    """Performance by score band."""
    result = {}
    valid = df[df["return_d1"].notna()]
    for label, lo, hi in SCORE_BANDS:
        sub = valid[(valid["total_score"] >= lo) & (valid["total_score"] < hi)]
        result[label] = {
            "count": int(len(sub)),
            "avg_return_d1": round(float(sub["return_d1"].mean()), 3) if len(sub) > 0 else None,
            "win_rate": round(float(sub["win_flag"].mean()) * 100, 1) if len(sub) > 0 else None,
        }
    return result


def analyze_sectors(df: pd.DataFrame) -> dict:
    """Sector-level performance (RESERVE_BUY + WATCH_ONLY only)."""
    active = df[df["signal_label"].isin(["RESERVE_BUY", "WATCH_ONLY"])]
    valid = active[active["return_d1"].notna()]
    if valid.empty:
        return {}
    result = {}
    for sector, grp in valid.groupby("sector"):
        result[str(sector)] = {
            "count": int(len(grp)),
            "avg_return_d1": round(float(grp["return_d1"].mean()), 3),
            "win_rate": round(float(grp["win_flag"].mean()) * 100, 1),
        }
    # Sort by avg_return desc
    result = dict(sorted(result.items(), key=lambda x: x[1]["avg_return_d1"] or -999, reverse=True))
    return result


def simulate_thresholds(df: pd.DataFrame) -> dict:
    """
    Simulate different RESERVE/WATCH thresholds.
    Returns grid of (reserve_thresh, watch_thresh) -> {precision, recall, win_rate}
    """
    valid = df[df["return_d1"].notna()].copy()
    if valid.empty:
        return {}

    results = {}
    for r_thresh in RESERVE_RANGE:
        for w_thresh in WATCH_RANGE:
            if w_thresh >= r_thresh:
                continue
            selected = valid[valid["total_score"] >= w_thresh]
            reserve = selected[selected["total_score"] >= r_thresh]
            watch = selected[(selected["total_score"] >= w_thresh) & (selected["total_score"] < r_thresh)]

            key = f"R{r_thresh}_W{w_thresh}"
            results[key] = {
                "reserve_thresh": r_thresh,
                "watch_thresh": w_thresh,
                "reserve_count": int(len(reserve)),
                "watch_count": int(len(watch)),
                "reserve_win_rate": round(float(reserve["win_flag"].mean()) * 100, 1) if len(reserve) > 0 else None,
                "watch_win_rate": round(float(watch["win_flag"].mean()) * 100, 1) if len(watch) > 0 else None,
                "combined_win_rate": round(float(selected["win_flag"].mean()) * 100, 1) if len(selected) > 0 else None,
                "reserve_avg_return": round(float(reserve["return_d1"].mean()), 3) if len(reserve) > 0 else None,
            }
    return results


def build_equity_curve(df: pd.DataFrame) -> list:
    """Daily portfolio return curve (equal-weight RESERVE+WATCH signals)."""
    active = df[df["signal_label"].isin(["RESERVE_BUY", "WATCH_ONLY"])]
    valid = active[active["return_d1"].notna()]
    if valid.empty:
        return []
    daily = valid.groupby("date")["return_d1"].mean().reset_index()
    daily = daily.sort_values("date")
    daily["cumulative_return"] = (1 + daily["return_d1"] / 100).cumprod() * 100 - 100
    return daily.rename(columns={"return_d1": "avg_return_d1"}).round(3).to_dict(orient="records")


def print_console_report(report: dict):
    print("\n" + "=" * 60)
    print("  SFD BACKTEST ANALYZER — REPORT")
    print("=" * 60)
    meta = report.get("meta", {})
    print(f"  Dates analyzed : {meta.get('date_range_start')} ~ {meta.get('date_range_end')}")
    print(f"  Total records  : {meta.get('total_records')}")
    print(f"  Valid (D+1)    : {meta.get('valid_return_count')}")
    print()

    print("[ TIER PERFORMANCE ]")
    for tier, stats in report.get("tiers", {}).items():
        wr = f"{stats['win_rate']}%" if stats['win_rate'] is not None else "N/A"
        ar = f"{stats['avg_return_d1']}%" if stats['avg_return_d1'] is not None else "N/A"
        print(f"  {tier:15s} count={stats['count']:4d}  win_rate={wr:6s}  avg_return={ar}")

    print()
    print("[ SCORE BAND ANALYSIS ]")
    for band, stats in report.get("score_bands", {}).items():
        wr = f"{stats['win_rate']}%" if stats['win_rate'] is not None else "N/A"
        ar = f"{stats['avg_return_d1']}%" if stats['avg_return_d1'] is not None else "N/A"
        print(f"  {band:8s}  count={stats['count']:4d}  win_rate={wr:6s}  avg_return={ar}")

    print()
    print("[ TOP SECTORS (RESERVE+WATCH) ]")
    for sector, stats in list(report.get("sectors", {}).items())[:8]:
        wr = f"{stats['win_rate']}%"
        ar = f"{stats['avg_return_d1']}%"
        print(f"  {sector:20s}  count={stats['count']:3d}  win_rate={wr:6s}  avg_return={ar}")

    print()
    print("[ THRESHOLD SIMULATION — Best 5 by Reserve Win Rate ]")
    thresh_data = report.get("threshold_simulation", {})
    sorted_thresh = sorted(
        thresh_data.values(),
        key=lambda x: (x.get("reserve_win_rate") or 0),
        reverse=True
    )[:5]
    for t in sorted_thresh:
        print(f"  R={t['reserve_thresh']:2d} / W={t['watch_thresh']:2d}  "
              f"reserve: {t['reserve_count']}건/{t.get('reserve_win_rate', 'N/A')}%  "
              f"watch: {t['watch_count']}건/{t.get('watch_win_rate', 'N/A')}%  "
              f"res_avg_ret={t.get('reserve_avg_return', 'N/A')}%")

    print("=" * 60 + "\n")


def run(days_limit: int | None = None, print_report: bool = False):
    print(f"[ANALYZER] Scanning archive: {_ARCHIVE}")
    archive_dates = scan_archive_dates(days_limit)
    print(f"[ANALYZER] Found {len(archive_dates)} archive dates")

    if not archive_dates:
        print("[ANALYZER] No archive data found. Run the pipeline first to accumulate data.")
        sys.exit(0)

    print("[ANALYZER] Building paired D+1 records...")
    df = build_paired_records(archive_dates)

    if df.empty:
        print("[ANALYZER] No valid records after pairing. Check signal/close CSV contents.")
        sys.exit(0)

    valid_count = int(df["return_d1"].notna().sum())
    print(f"[ANALYZER] Total records: {len(df)}, valid D+1 returns: {valid_count}")

    report = {
        "meta": {
            "generated_at": str(date.today()),
            "date_range_start": archive_dates[0] if archive_dates else None,
            "date_range_end": archive_dates[-1] if archive_dates else None,
            "total_dates": len(archive_dates),
            "total_records": int(len(df)),
            "valid_return_count": valid_count,
        },
        "tiers": analyze_tiers(df),
        "score_bands": analyze_score_bands(df),
        "sectors": analyze_sectors(df),
        "threshold_simulation": simulate_thresholds(df),
        "equity_curve": build_equity_curve(df),
    }

    # Save JSON report
    _LATEST.mkdir(parents=True, exist_ok=True)
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[ANALYZER] Report saved: {REPORT_JSON}")

    # Save CSV summary (per-ticker)
    df.to_csv(REPORT_CSV, index=False, encoding="utf-8-sig")
    print(f"[ANALYZER] CSV saved: {REPORT_CSV}")

    if print_report:
        print_console_report(report)

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SFD Backtest Analyzer v1.0")
    parser.add_argument("--days", type=int, default=None,
                        help="Analyze last N days only (default: all)")
    parser.add_argument("--report", action="store_true",
                        help="Print summary to console")
    args = parser.parse_args()
    run(days_limit=args.days, print_report=args.report)
