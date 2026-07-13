# sfd_ohlcv_store.py V1.0 / 2026.07.13
"""Persistent, incrementally updated OHLCV storage for the SFD pipeline."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf


LOGGER = logging.getLogger(__name__)

BASE_DIR = Path(
    os.environ.get("SFD_BASE_DIR", Path(__file__).resolve().parent.parent)
).resolve()
OHLCV_DIR = BASE_DIR / "data" / "ohlcv"
LAST_UPDATE_PATH = OHLCV_DIR / "last_update.json"
CSV_COLUMNS = ["date", "open", "high", "low", "close", "volume", "code"]
INITIAL_LOOKBACK_DAYS = 400
REQUEST_INTERVAL_SECONDS = 0.5
RETRY_DELAYS = (1, 2, 4)


def _normalize_code(code: str) -> str:
    normalized = str(code).strip().zfill(6)
    if len(normalized) != 6 or not normalized.isdigit():
        raise ValueError(f"Invalid stock code: {code!r}")
    return normalized


def _normalize_market(market: str) -> str:
    normalized = str(market).strip().upper()
    if normalized not in {"KS", "KQ"}:
        raise ValueError(f"Invalid market: {market!r}; expected KS or KQ")
    return normalized


def _csv_path(code: str) -> Path:
    return OHLCV_DIR / f"{code}.csv"


def _read_last_updates() -> dict[str, str]:
    if not LAST_UPDATE_PATH.exists():
        return {}
    try:
        with LAST_UPDATE_PATH.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
        if not isinstance(payload, dict):
            raise ValueError("root value must be an object")
        return {str(key): str(value) for key, value in payload.items()}
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        LOGGER.warning("Invalid last_update.json; starting with empty metadata: %s", exc)
        return {}


def _write_last_updates(updates: dict[str, str]) -> None:
    OHLCV_DIR.mkdir(parents=True, exist_ok=True)
    temporary_path = LAST_UPDATE_PATH.with_suffix(".json.tmp")
    with temporary_path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(updates, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    temporary_path.replace(LAST_UPDATE_PATH)


def _read_csv(code: str) -> pd.DataFrame:
    path = _csv_path(code)
    frame = pd.read_csv(path, dtype={"code": str})
    missing = set(CSV_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"Invalid OHLCV CSV {path}: missing {sorted(missing)}")
    frame = frame[CSV_COLUMNS].copy()
    frame["code"] = frame["code"].astype(str).str.zfill(6)
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.strftime(
        "%Y-%m-%d"
    )
    return frame.sort_values("date").reset_index(drop=True)


def _normalize_download(raw: pd.DataFrame, code: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame(columns=CSV_COLUMNS)

    frame = raw.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    frame = frame.reset_index()
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    if "date" not in frame.columns and "datetime" in frame.columns:
        frame = frame.rename(columns={"datetime": "date"})

    required = {"date", "open", "high", "low", "close", "volume"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"yfinance response missing columns: {sorted(missing)}")

    frame = frame[["date", "open", "high", "low", "close", "volume"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.strftime(
        "%Y-%m-%d"
    )
    for column in ["open", "high", "low", "close", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["date", "open", "high", "low", "close"])
    frame["code"] = code
    return frame[CSV_COLUMNS].sort_values("date").reset_index(drop=True)


def _download(code: str, market: str, start_date: date, end_date: date) -> pd.DataFrame:
    ticker = f"{code}.{market}"
    try:
        raw = yf.download(
            ticker,
            start=start_date.isoformat(),
            end=(end_date + timedelta(days=1)).isoformat(),
            auto_adjust=False,
            progress=False,
            threads=False,
        )
        return _normalize_download(raw, code)
    finally:
        time.sleep(REQUEST_INTERVAL_SECONDS)


def update_ohlcv(code: str, market: str = "KS") -> pd.DataFrame:
    """Download only missing dates, persist them, and return full ticker history."""
    code = _normalize_code(code)
    market = _normalize_market(market)
    OHLCV_DIR.mkdir(parents=True, exist_ok=True)

    path = _csv_path(code)
    existing = _read_csv(code) if path.exists() else pd.DataFrame(columns=CSV_COLUMNS)
    updates = _read_last_updates()
    today = date.today()

    if path.exists() and updates.get(code) == today.isoformat():
        LOGGER.info("ticker=%s SKIP already updated today", code)
        return existing

    if existing.empty:
        start_date = today - timedelta(days=INITIAL_LOOKBACK_DAYS)
    else:
        csv_last_date = pd.to_datetime(existing["date"].iloc[-1]).date()
        metadata_date = updates.get(code)
        try:
            last_date = date.fromisoformat(metadata_date) if metadata_date else csv_last_date
        except ValueError:
            LOGGER.warning("ticker=%s invalid last_update=%r; using CSV date", code, metadata_date)
            last_date = csv_last_date
        # Never let stale metadata cause duplicate wide downloads.
        start_date = max(last_date, csv_last_date) + timedelta(days=1)

    if start_date <= today:
        fresh = _download(code, market, start_date, today)
    else:
        fresh = pd.DataFrame(columns=CSV_COLUMNS)

    combined = pd.concat([existing, fresh], ignore_index=True)
    if not combined.empty:
        combined["code"] = code
        combined = (
            combined.drop_duplicates(subset="date", keep="last")
            .sort_values("date")
            .reset_index(drop=True)
        )
        combined.to_csv(path, columns=CSV_COLUMNS, index=False, encoding="utf-8")

    updates[code] = today.isoformat()
    _write_last_updates(updates)
    LOGGER.info("ticker=%s updated rows=%d total=%d", code, len(fresh), len(combined))
    return combined


def load_ohlcv(code: str, n: int = 120) -> pd.DataFrame:
    """Load the most recent n stored rows without making a network request."""
    code = _normalize_code(code)
    if n < 0:
        raise ValueError("n must be non-negative")
    path = _csv_path(code)
    if not path.exists():
        raise FileNotFoundError(path)
    return _read_csv(code).tail(n).reset_index(drop=True)


def update_universe(codes: list[dict[str, str]]) -> dict[str, list[str]]:
    """Update all tickers independently, retrying failures without stopping the pipeline."""
    result: dict[str, list[str]] = {"updated": [], "failed": [], "skipped": []}

    for item in codes:
        raw_code: Any = item.get("code") if isinstance(item, dict) else item
        try:
            code = _normalize_code(raw_code)
            market = _normalize_market(item.get("market", "KS"))
        except Exception as exc:
            label = str(raw_code)
            result["failed"].append(label)
            LOGGER.warning("ticker=%s FAIL invalid input: %s", label, exc)
            continue

        if _csv_path(code).exists() and _read_last_updates().get(code) == date.today().isoformat():
            result["skipped"].append(code)
            LOGGER.info("ticker=%s SKIP already updated today", code)
            continue

        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                update_ohlcv(code, market)
                result["updated"].append(code)
                break
            except Exception as exc:
                if attempt < len(RETRY_DELAYS):
                    delay = RETRY_DELAYS[attempt]
                    LOGGER.warning(
                        "ticker=%s attempt=%d FAIL %s; retry in %ds",
                        code,
                        attempt + 1,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
                else:
                    result["failed"].append(code)
                    LOGGER.warning("ticker=%s FAIL after retries: %s", code, exc)

    return result


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    universe = [
        {"code": "005930", "market": "KS"},
        {"code": "001440", "market": "KS"},
    ]
    for stock in universe:
        update_ohlcv(stock["code"], stock["market"])
        print(f"{stock['code']} rows={len(load_ohlcv(stock['code'], n=120))}")
    print("second_run=", update_universe(universe))
