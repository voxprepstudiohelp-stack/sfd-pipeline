# sfd_prev_close_fetch.py v3.3
# GitHub: sfd-pipeline/tools/sfd_prev_close_fetch.py
#
# v3.2 -> v3.3 changes:
# - [P2] ThreadPoolExecutor batch parallelization (workers=5, 4~5x speedup)
# - [P2] Same-day cache: skip full fetch if latest CSV was written today
# - [P2] BATCH 300 -> 200 (smaller batches = better parallel throughput)
# - [P2] time.sleep(1) removed between batches (parallelization handles rate)
# - All v3.2 columns preserved (full backward compatibility)
#
# Output columns (v3.3) -- identical to v3.2:
#   ticker, name, prev_close, prev_open, prev_high, prev_low,
#   prev_volume, prev_value, prev_prev_close, prev_change_pct,
#   close, volume, vol_avg,
#   ma20, ma60,
#   market, fetch_date, fetched_at, data_status

import io
import os
import sys
import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf
import FinanceDataReader as fdr

# cp949 safe output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import LATEST_DIR, HISTORY_DIR, INPUT_DIR

LATEST_PATH = os.path.join(LATEST_DIR, "sfd_prev_close_latest.csv")
INPUT_PATH  = os.path.join(INPUT_DIR,  "sfd_prev_close_input.csv")
LOG_PATH    = os.path.join(LATEST_DIR, "sfd_prev_close_fetch.log")

os.makedirs(LATEST_DIR,  exist_ok=True)
os.makedirs(HISTORY_DIR, exist_ok=True)
os.makedirs(INPUT_DIR,   exist_ok=True)

logging.basicConfig(filename=LOG_PATH, level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s", encoding="utf-8")

START_TIME  = time.time()
now         = datetime.now()
fetch_time  = now.strftime("%Y-%m-%d %H:%M:%S")
today_str   = now.strftime("%Y%m%d")

# ── v3.3 constants
FETCH_PERIOD    = "90d"
MA20_PERIOD     = 20
MA60_PERIOD     = 60
VOL_AVG_PERIOD  = 20
BATCH_SIZE      = 200   # v3.3: 300 -> 200 for better parallelism
MAX_WORKERS     = 5     # v3.3: parallel batch workers
CACHE_ENABLED   = True  # v3.3: same-day cache

print("\n========== SFD prev_close fetch v3.3 (parallel) ==========")
print(f"Start: {fetch_time}")
print(f"Config: period={FETCH_PERIOD}, batch={BATCH_SIZE}, workers={MAX_WORKERS}, cache={CACHE_ENABLED}")


# ── v3.3: same-day cache check
def check_cache() -> bool:
    """Return True if latest CSV was already written today (skip full fetch)."""
    if not CACHE_ENABLED:
        return False
    if not os.path.exists(LATEST_PATH):
        return False
    try:
        df = pd.read_csv(LATEST_PATH, nrows=1, encoding="utf-8-sig")
        if "fetch_date" in df.columns:
            cached_date = str(df["fetch_date"].iloc[0]).strip()
            if cached_date == today_str:
                print(f"[CACHE HIT] Today's data already exists ({LATEST_PATH}). Skipping fetch.")
                logging.info(f"Cache hit: {today_str}, skipping fetch")
                return True
    except Exception:
        pass
    return False


def calc_ma(series: pd.Series, period: int):
    """Rolling mean latest value. Returns None if insufficient data."""
    if len(series.dropna()) < period:
        return None
    val = series.rolling(period).mean().iloc[-1]
    return round(float(val), 2) if not pd.isna(val) else None


# ── v3.3: single batch fetch (called in thread pool)
_print_lock = threading.Lock()

def fetch_batch(args):
    """
    Fetch one batch of yf tickers.
    Returns: dict {yf_ticker: {close, open, high, low, volume, prev_prev_close,
                                prev_change_pct, ma20, ma60, vol_avg}}
    """
    batch_idx, batch = args
    result = {}
    try:
        data = yf.download(
            batch,
            period=FETCH_PERIOD,
            auto_adjust=True,
            progress=False,
            threads=True,
        )
        if data.empty:
            return result

        def get_col(col):
            if isinstance(data.columns, pd.MultiIndex):
                return data[col] if col in data.columns.get_level_values(0) else pd.DataFrame()
            return data[[col]] if col in data.columns else pd.DataFrame()

        close_df  = get_col("Close")
        open_df   = get_col("Open")
        high_df   = get_col("High")
        low_df    = get_col("Low")
        volume_df = get_col("Volume")

        def safe_get(df, ticker):
            try:
                if isinstance(df.columns, pd.MultiIndex):
                    s = df[ticker] if ticker in df.columns.get_level_values(1) else pd.Series()
                else:
                    s = df[ticker] if ticker in df.columns else pd.Series()
                return s.dropna()
            except Exception:
                return pd.Series()

        def _get1(df, ticker):
            try:
                s = safe_get(df, ticker)
                return float(s.iloc[-1]) if len(s) >= 1 else None
            except Exception:
                return None

        for t in batch:
            c_ser = safe_get(close_df, t)
            v_ser = safe_get(volume_df, t)

            c1  = float(c_ser.iloc[-1]) if len(c_ser) >= 1 else None
            c2  = float(c_ser.iloc[-2]) if len(c_ser) >= 2 else None
            pcp = round((c1 - c2) / c2 * 100, 2) if c1 and c2 and c2 != 0 else None

            ma20_val = calc_ma(c_ser, MA20_PERIOD)
            ma60_val = calc_ma(c_ser, MA60_PERIOD)

            vol_avg_val = None
            if len(v_ser) >= VOL_AVG_PERIOD:
                va = v_ser.rolling(VOL_AVG_PERIOD).mean().iloc[-1]
                vol_avg_val = round(float(va), 0) if not pd.isna(va) else None

            result[t] = {
                "close":            c1,
                "open":             _get1(open_df,   t),
                "high":             _get1(high_df,   t),
                "low":              _get1(low_df,    t),
                "volume":           _get1(volume_df, t),
                "prev_prev_close":  c2,
                "prev_change_pct":  pcp,
                "ma20":             ma20_val,
                "ma60":             ma60_val,
                "vol_avg":          vol_avg_val,
            }

        with _print_lock:
            ok = sum(1 for v in result.values() if v.get("close"))
            print(f"  batch {batch_idx+1:02d}: {len(batch)} tickers -> {ok} OK")

    except Exception as e:
        with _print_lock:
            print(f"  batch {batch_idx+1:02d} ERROR: {e}")
        for t in batch:
            result[t] = {k: None for k in [
                "close","open","high","low","volume",
                "prev_prev_close","prev_change_pct","ma20","ma60","vol_avg"
            ]}
    return result


# ── main
if check_cache():
    # Cache hit: just re-output INPUT_PATH from LATEST_PATH
    try:
        merged = pd.read_csv(LATEST_PATH, encoding="utf-8-sig")
        input_df = merged[["ticker", "prev_close"]].rename(columns={"ticker": "stock_code"})
        input_df.to_csv(INPUT_PATH, index=False, encoding="utf-8-sig")
        print(f"  input refreshed from cache: {INPUT_PATH}")
    except Exception as e:
        print(f"  cache re-read failed: {e}")
    elapsed = round(time.time() - START_TIME)
    print(f"\nDone (cache): elapsed={elapsed}s")
    sys.exit(0)

# ── full fetch
records = []
for market, suffix in [("KOSPI", ".KS"), ("KOSDAQ", ".KQ")]:
    print(f"\n[{market}] listing...")
    try:
        listing = fdr.StockListing(market)
        listing.columns = [c.strip() for c in listing.columns]
        code_col = next((c for c in ["Code", "Symbol", "종목코드"] if c in listing.columns), None)
        name_col = next((c for c in ["Name", "종목명"]             if c in listing.columns), None)
        if code_col is None:
            print(f"  [{market}] code column not found")
            continue

        tickers_raw = listing[code_col].astype(str).str.zfill(6).tolist()
        names       = listing[name_col].tolist() if name_col else [""] * len(tickers_raw)
        yf_tickers  = [f"{t}{suffix}" for t in tickers_raw]

        # build batches
        batches = [
            (i // BATCH_SIZE, yf_tickers[i:i + BATCH_SIZE])
            for i in range(0, len(yf_tickers), BATCH_SIZE)
        ]
        print(f"  [{market}] {len(yf_tickers)} tickers -> {len(batches)} batches (workers={MAX_WORKERS})")

        # v3.3: parallel fetch
        ohlcv_map = {}
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(fetch_batch, b): b[0] for b in batches}
            for future in as_completed(futures):
                batch_result = future.result()
                ohlcv_map.update(batch_result)

        # aggregate
        for ticker_raw, name, yf_t in zip(tickers_raw, names, yf_tickers):
            d = ohlcv_map.get(yf_t, {})
            records.append({
                "ticker":           ticker_raw,
                "name":             name,
                "prev_close":       d.get("close"),
                "prev_open":        d.get("open"),
                "prev_high":        d.get("high"),
                "prev_low":         d.get("low"),
                "prev_volume":      d.get("volume"),
                "prev_value":       None,
                "prev_prev_close":  d.get("prev_prev_close"),
                "prev_change_pct":  d.get("prev_change_pct"),
                "close":            d.get("close"),
                "volume":           d.get("volume"),
                "vol_avg":          d.get("vol_avg"),
                "ma20":             d.get("ma20"),
                "ma60":             d.get("ma60"),
                "market":           market,
                "data_status":      "OK" if d.get("close") else "NO_DATA",
            })

        ok     = sum(1 for r in records if r["market"] == market and r["data_status"] == "OK")
        ma_ok  = sum(1 for r in records if r["market"] == market and r.get("ma60") is not None)
        print(f"  [{market}] done: OK={ok}/{len(tickers_raw)}, MA60={ma_ok}")
        logging.info(f"{market}: {ok}/{len(tickers_raw)} | ma60_ok={ma_ok}")

    except Exception as e:
        print(f"  [{market}] FATAL: {e}")
        logging.error(f"{market}: {e}")

if not records:
    print("No records. Exit.")
    sys.exit(1)

# ── save
merged = pd.DataFrame(records)
trade_day = (now - timedelta(days=1)).strftime("%Y%m%d")
merged["fetch_date"] = today_str      # v3.3: use today for cache key
merged["fetched_at"] = fetch_time

cols = [
    "ticker", "name",
    "prev_close", "prev_open", "prev_high", "prev_low",
    "prev_volume", "prev_value",
    "prev_prev_close", "prev_change_pct",
    "close", "volume", "vol_avg",
    "ma20", "ma60",
    "market", "fetch_date", "fetched_at", "data_status",
]
cols   = [c for c in cols if c in merged.columns]
merged = merged[cols]

merged.to_csv(LATEST_PATH, index=False, encoding="utf-8-sig")
print(f"\n[OK] latest : {LATEST_PATH}")

history_file = os.path.join(HISTORY_DIR, f"sfd_prev_close_{trade_day}.csv")
merged.to_csv(history_file, index=False, encoding="utf-8-sig")
print(f"[OK] history: {history_file}")

input_df = merged[["ticker", "prev_close"]].rename(columns={"ticker": "stock_code"})
input_df.to_csv(INPUT_PATH, index=False, encoding="utf-8-sig")
print(f"[OK] input  : {INPUT_PATH}")

elapsed   = round(time.time() - START_TIME)
ok_total  = len(merged[merged["data_status"] == "OK"])
ma60_ok   = merged["ma60"].notna().sum() if "ma60" in merged.columns else 0
pcp_ok    = merged["prev_change_pct"].notna().sum()
print(f"\nTotal: {len(merged)} | OK={ok_total} | MA60={ma60_ok} | pcp={pcp_ok} | elapsed={elapsed}s")
logging.info(f"Done | total={len(merged)} | ok={ok_total} | ma60_ok={ma60_ok} | elapsed={elapsed}s")
