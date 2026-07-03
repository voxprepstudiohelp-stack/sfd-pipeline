# -*- coding: utf-8 -*-
# sfd_ohlcv_store.py | v1.0 | 2026.07.03
#
# [v1.0]
# - P1 OHLCV Store: master_input tickers → 200 days daily OHLCV → outputs/latest/ohlcv.db (SQLite)
# - Table: ohlcv_daily (ticker TEXT, date TEXT, open REAL, high REAL, low REAL,
#                        close REAL, volume INTEGER, PRIMARY KEY(ticker, date))
# - INSERT OR REPLACE on PK conflict
# - Meta JSON: ohlcv_store_meta.json (updated_at, ticker_count, row_count, failed[])
# - SFD_BASE_DIR env override for BASE_DIR resolution
# - Per-ticker failures logged + collected in meta.failed; no sys.exit on skip

import os
import sys
import csv
import json
import sqlite3
import logging
import traceback
from datetime import datetime, timedelta

import pandas as pd
import FinanceDataReader as fdr

# ── Path config ───────────────────────────────────────────────────────────────
_env_base = os.environ.get("SFD_BASE_DIR", "")
if _env_base and os.path.isdir(_env_base):
    BASE_DIR = _env_base
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

INPUT_DIR = os.path.join(BASE_DIR, "inputs")
LATEST_DIR = os.path.join(BASE_DIR, "outputs", "latest")
os.makedirs(LATEST_DIR, exist_ok=True)

INPUT_CSV       = os.path.join(INPUT_DIR, "sfd_master_signal_input.csv")
DB_PATH         = os.path.join(LATEST_DIR, "ohlcv.db")
META_PATH       = os.path.join(LATEST_DIR, "ohlcv_store_meta.json")
LOG_PATH        = os.path.join(LATEST_DIR, "sfd_ohlcv_store.log")

# ── Parameters ────────────────────────────────────────────────────────────────
OHLCV_DAYS       = 200          # lookback window (calendar days) — covers ~200 trading bars
MIN_BARS         = 40           # sanity floor for a "valid" fetch
TABLE_NAME       = "ohlcv_daily"

logging.basicConfig(
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


# ── Helpers ───────────────────────────────────────────────────────────────────
def load_tickers_from_master() -> list:
    """Read ticker column from inputs/sfd_master_signal_input.csv."""
    if not os.path.exists(INPUT_CSV):
        logging.error(f"[STORE] INPUT not found: {INPUT_CSV}")
        return []
    try:
        with open(INPUT_CSV, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            first_col = reader.fieldnames[0] if reader.fieldnames else None
            if first_col is None:
                return []
            # accept 'ticker' OR fallback to first column name
            col = "ticker" if "ticker" in reader.fieldnames else first_col
            seen = set()
            tickers = []
            for row in reader:
                raw = (row.get(col) or "").strip()
                if not raw:
                    continue
                t = raw.zfill(6)
                if t in seen:
                    continue
                seen.add(t)
                tickers.append(t)
        logging.info(f"[STORE] tickers loaded: {len(tickers)} (col={col})")
        return tickers
    except Exception as e:
        logging.error(f"[STORE] INPUT read failed: {e}")
        return []


def init_db(conn: sqlite3.Connection) -> None:
    """Create ohlcv_daily table if absent. Index for date scans."""
    cur = conn.cursor()
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            ticker TEXT NOT NULL,
            date   TEXT NOT NULL,
            open   REAL,
            high   REAL,
            low    REAL,
            close  REAL,
            volume INTEGER,
            PRIMARY KEY (ticker, date)
        )
        """
    )
    # Helpful secondary index when aggregating across tickers
    cur.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_date ON {TABLE_NAME}(date)"
    )
    conn.commit()


def fetch_one(conn: sqlite3.Connection, ticker: str) -> int:
    """Fetch 200 days OHLCV for one ticker and write via INSERT OR REPLACE.
    Returns number of rows written. Raises on fetch failure so caller logs to failed[].
    """
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=OHLCV_DAYS)
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")

    df = fdr.DataReader(ticker, start_str, end_str)
    if df is None or len(df) == 0:
        raise ValueError(f"empty OHLCV for {ticker}")

    # Normalize index → 'date' string column. FDR returns DatetimeIndex named None/Date.
    df = df.reset_index()
    # find date column robustly
    date_col = None
    for c in df.columns:
        if str(c).lower() in ("date", "index"):
            date_col = c
            break
    if date_col is None:
        # first unnamed column
        date_col = df.columns[0]
    df = df.rename(columns={date_col: "date"})
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

    # lower-case map + ticker fill
    rename_map = {c: c.lower() for c in df.columns if c.lower() in ("open", "high", "low", "close", "volume")}
    df = df.rename(columns=rename_map)

    needed = ["date", "open", "high", "low", "close", "volume"]
    for col in needed:
        if col not in df.columns:
            if col == "volume":
                df[col] = 0
            else:
                raise ValueError(f"missing column {col} for {ticker}")

    df["ticker"] = ticker
    # Order: ticker, date, ohlcv
    df = df[["ticker", "date", "open", "high", "low", "close", "volume"]]

    rows = [
        (
            str(r["ticker"]),
            str(r["date"]),
            None if pd.isna(r["open"])  else float(r["open"]),
            None if pd.isna(r["high"])  else float(r["high"]),
            None if pd.isna(r["low"])   else float(r["low"]),
            None if pd.isna(r["close"]) else float(r["close"]),
            None if pd.isna(r["volume"]) else int(r["volume"]),
        )
        for _, r in df.iterrows()
    ]

    cur = conn.cursor()
    cur.executemany(
        f"""
        INSERT OR REPLACE INTO {TABLE_NAME}
            (ticker, date, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def run() -> dict:
    started = datetime.now()
    logging.info(f"=== sfd_ohlcv_store v1.0 START ===")
    logging.info(f"BASE_DIR:   {BASE_DIR}")
    logging.info(f"DB_PATH:    {DB_PATH}")
    logging.info(f"META_PATH:  {META_PATH}")

    tickers = load_tickers_from_master()
    if not tickers:
        logging.warning("[STORE] no tickers to process — exiting gracefully")
        meta = {
            "updated_at":   started.strftime("%Y-%m-%d %H:%M:%S"),
            "ticker_count": 0,
            "row_count":    0,
            "failed":       [],
            "note":         "no tickers from master input",
        }
        with open(META_PATH, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return meta

    conn = sqlite3.connect(DB_PATH)
    try:
        init_db(conn)
    except Exception as e:
        logging.error(f"[STORE] DB init failed: {e}")
        conn.close()
        meta = {
            "updated_at":   started.strftime("%Y-%m-%d %H:%M:%S"),
            "ticker_count": 0,
            "row_count":    0,
            "failed":       tickers,
            "note":         f"db init failed: {e}",
        }
        with open(META_PATH, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return meta

    succeeded = 0
    row_count = 0
    failed = []

    for i, ticker in enumerate(tickers, 1):
        try:
            n = fetch_one(conn, ticker)
            if n < MIN_BARS:
                logging.warning(f"[STORE] {ticker}: rows={n} (<{MIN_BARS}) — recorded anyway")
            row_count += n
            succeeded += 1
            logging.info(f"[STORE] [{i}/{len(tickers)}] {ticker}: {n} rows")
        except Exception as e:
            logging.warning(f"[STORE] [{i}/{len(tickers)}] {ticker}: SKIP — {type(e).__name__}: {e}")
            failed.append(ticker)
        # soft yield, very small, avoid hammering FDR
        # (no sleep — fdr has its own internal throttle; keep fast path)

    conn.close()

    meta = {
        "updated_at":   started.strftime("%Y-%m-%d %H:%M:%S"),
        "ticker_count": succeeded,
        "row_count":    row_count,
        "failed":       failed,
    }
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    logging.info(
        f"=== DONE | tickers={succeeded}/{len(tickers)} "
        f"rows={row_count} failed={len(failed)} ==="
    )
    if failed:
        logging.info(f"[STORE] failed tickers: {failed}")
    return meta


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        # never sys.exit — write a fallback meta and let the caller continue
        logging.error(f"[STORE] unhandled error: {e}\n{traceback.format_exc()}")
        try:
            meta = {
                "updated_at":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "ticker_count": 0,
                "row_count":    0,
                "failed":       [],
                "note":         f"unhandled: {e}",
            }
            with open(META_PATH, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
