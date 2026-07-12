# sfd_regime_classifier.py V1.1 / 2026.07.13
"""EMA120 slope and Wilder ADX based market-regime classifier."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd


LOGGER = logging.getLogger(__name__)
SLOPE_STRONG = 0.0015
EMA_PERIOD = 120
ADX_PERIOD = 14
MIN_ROWS = 150


def _unknown_result() -> dict[str, Any]:
    """Return a fresh result for data that cannot be classified."""
    return {
        "regime": "UNKNOWN",
        "ema120_slope": float("nan"),
        "adx": float("nan"),
        "ema120_last": float("nan"),
        "slope_strong": False,
    }


def _wilder_adx(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Calculate standard Wilder ADX using period-14 recursive smoothing."""
    high = high.astype(float)
    low = low.astype(float)
    close = close.astype(float)

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=high.index,
        dtype=float,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=high.index,
        dtype=float,
    )

    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    true_range.iloc[0] = np.nan

    atr = _wilder_rma(true_range, ADX_PERIOD)
    smoothed_plus_dm = _wilder_rma(plus_dm.where(true_range.notna()), ADX_PERIOD)
    smoothed_minus_dm = _wilder_rma(minus_dm.where(true_range.notna()), ADX_PERIOD)

    plus_di = 100.0 * smoothed_plus_dm / atr
    minus_di = 100.0 * smoothed_minus_dm / atr
    denominator = plus_di + minus_di
    dx = 100.0 * (plus_di - minus_di).abs() / denominator
    dx = dx.where(denominator != 0, 0.0)
    return _wilder_rma(dx, ADX_PERIOD)


def _wilder_rma(values: pd.Series, period: int) -> pd.Series:
    """Wilder moving average seeded with the first period's arithmetic mean."""
    output = pd.Series(np.nan, index=values.index, dtype=float)
    valid_positions = np.flatnonzero(values.notna().to_numpy())
    if len(valid_positions) < period:
        return output

    seed_position = int(valid_positions[period - 1])
    previous = float(values.iloc[valid_positions[:period]].mean())
    output.iloc[seed_position] = previous
    for position in range(seed_position + 1, len(values)):
        current = values.iloc[position]
        if pd.isna(current):
            continue
        previous = (previous * (period - 1) + float(current)) / period
        output.iloc[position] = previous
    return output


def _decide_regime(slope: float, adx: float) -> str:
    """Map every finite slope/ADX pair to exactly one regime."""
    if slope <= 0 or adx < 20:
        return "C"
    if adx > 35:
        return "B"
    return "A"


def classify_regime(df: pd.DataFrame) -> dict[str, Any]:
    """Classify one ticker's OHLCV history into regime A, B, or C."""
    result = _unknown_result()
    try:
        if not isinstance(df, pd.DataFrame):
            raise TypeError("df must be a pandas DataFrame")
        if len(df) < MIN_ROWS:
            LOGGER.warning("Insufficient data: rows=%d, required=%d", len(df), MIN_ROWS)
            return result

        normalized = df.rename(columns=lambda column: str(column).strip().lower())
        required = {"date", "close", "high", "low"}
        missing = required.difference(normalized.columns)
        if missing:
            raise ValueError(f"Missing required columns: {sorted(missing)}")

        values = normalized[["close", "high", "low"]].apply(
            pd.to_numeric, errors="coerce"
        )
        ema120 = values["close"].ewm(span=EMA_PERIOD, adjust=False).mean()
        ema120_last = float(ema120.iloc[-1])
        ema120_base = float(ema120.iloc[-6])
        slope = float((ema120_last - ema120_base) / ema120_base)
        adx = float(
            _wilder_adx(values["high"], values["low"], values["close"]).iloc[-1]
        )

        if not np.isfinite([ema120_last, ema120_base, slope, adx]).all() or ema120_base == 0:
            LOGGER.warning("EMA/ADX contains NaN or a non-finite value")
            return result

        regime = _decide_regime(slope, adx)

        return {
            "regime": regime,
            "ema120_slope": slope,
            "adx": adx,
            "ema120_last": ema120_last,
            "slope_strong": bool(slope > SLOPE_STRONG),
        }
    except Exception as exc:  # Pipeline classifications must fail independently.
        LOGGER.warning("Regime classification failed: %s", exc)
        return result


def classify_regime_batch(ohlcv_dict: dict[str, pd.DataFrame]) -> dict[str, dict[str, Any]]:
    """Classify multiple tickers, skipping histories shorter than 150 rows."""
    results: dict[str, dict[str, Any]] = {}
    for ticker, df in ohlcv_dict.items():
        try:
            if not isinstance(df, pd.DataFrame) or len(df) < MIN_ROWS:
                rows = len(df) if hasattr(df, "__len__") else 0
                LOGGER.warning("ticker=%s skipped: insufficient data (%d rows)", ticker, rows)
                continue
            result = classify_regime(df)
            results[ticker] = result
            LOGGER.info(
                "ticker=%s regime=%s slope=%.6f adx=%.2f",
                ticker,
                result["regime"],
                result["ema120_slope"],
                result["adx"],
            )
        except Exception as exc:
            LOGGER.warning("ticker=%s classification failed: %s", ticker, exc)
            results[ticker] = _unknown_result()
    return results


def _download_sample() -> pd.DataFrame:
    """Download the 60-day Samsung Electronics sample required by the CLI spec."""
    import yfinance as yf

    sample = yf.download("005930.KS", period="60d", progress=False, auto_adjust=False)
    if isinstance(sample.columns, pd.MultiIndex):
        sample.columns = sample.columns.get_level_values(0)
    return sample.reset_index().rename(columns=lambda column: str(column).lower())


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    print(classify_regime(_download_sample()))
