"""
sfd_candle_pattern.py
BM-14: AI Candle Pattern Recognition
SFD Pipeline - Pass2 technical score layer

Score range: -10 ~ +15pt
Integrates into sfd_signal_aggregator via tech_score (cap: 85pt)

Author: Claude (Architect)
Version: 1.0
Date: 2026-06-09
"""

import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Pattern definitions
# ─────────────────────────────────────────────
PATTERNS = {
    "MORNING_STAR":    +12,
    "HAMMER":          +10,
    "ENGULFING_BULL":  +8,
    "DOJI_REVERSAL":   +6,
    "DARK_CLOUD":      -8,
    "BEARISH_ENGULF":  -10,
}

SCORE_MAX =  15
SCORE_MIN = -10


# ─────────────────────────────────────────────
# Core detector
# ─────────────────────────────────────────────
def calculate_candle_score(df: pd.DataFrame) -> dict:
    """
    Detect candlestick patterns and return score.

    Args:
        df: DataFrame with columns [open, high, low, close, volume]
            Minimum 5 rows required, 20 rows recommended for vol_ma20.

    Returns:
        {
            'candle_score': float,   # -10 ~ +15
            'pattern':      str,     # detected pattern name
            'confidence':   float,   # 0.0 ~ 1.0
            'detail':       str      # human-readable explanation
        }
    """
    _null = {'candle_score': 0, 'pattern': 'NONE', 'confidence': 0.0, 'detail': 'insufficient data'}

    if df is None or len(df) < 5:
        return _null

    # Normalize column names
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    required = {'open', 'high', 'low', 'close', 'volume'}
    if not required.issubset(set(df.columns)):
        logger.warning("BM-14: missing columns %s", required - set(df.columns))
        return _null

    o = df['open'].astype(float)
    h = df['high'].astype(float)
    l = df['low'].astype(float)
    c = df['close'].astype(float)
    v = df['volume'].astype(float)

    vol_ma20 = v.rolling(min(20, len(df))).mean()
    vol_surge = v.iloc[-1] > vol_ma20.iloc[-1] * 1.3 if not pd.isna(vol_ma20.iloc[-1]) else False

    score   = 0
    pattern = 'NONE'
    detail  = ''

    # ── BEARISH patterns first (priority over bullish if both trigger) ──

    # BEARISH ENGULFING
    if (len(df) >= 2
            and c.iloc[-2] > o.iloc[-2]                 # 전봉 양봉
            and c.iloc[-1] < o.iloc[-1]                 # 현봉 음봉
            and o.iloc[-1] > c.iloc[-2]                 # 갭업 오픈
            and c.iloc[-1] < o.iloc[-2]):               # 전봉 시가 하회
        score   = PATTERNS["BEARISH_ENGULF"]
        pattern = "BEARISH_ENGULF"
        detail  = "bearish engulfing: prior candle fully covered by down-candle"

    # DARK CLOUD COVER
    elif (len(df) >= 2
            and c.iloc[-2] > o.iloc[-2]
            and o.iloc[-1] > c.iloc[-2]                 # 갭업
            and c.iloc[-1] < (c.iloc[-2] + o.iloc[-2]) / 2):  # 중간 이하 마감
        score   = PATTERNS["DARK_CLOUD"]
        pattern = "DARK_CLOUD"
        detail  = "dark cloud cover: gap-up open, closed below midpoint of prior candle"

    # ── BULLISH patterns ──

    # MORNING STAR (3봉)
    elif (len(df) >= 3):
        body3 = abs(c.iloc[-3] - o.iloc[-3])
        body2 = abs(c.iloc[-2] - o.iloc[-2])
        mid3  = (c.iloc[-3] + o.iloc[-3]) / 2
        if (c.iloc[-3] < o.iloc[-3]                     # 음봉
                and body2 < body3 * 0.3                 # 소형봉
                and c.iloc[-1] > o.iloc[-1]             # 양봉
                and c.iloc[-1] > mid3):                 # 중간 이상 회복
            boost  = 1.2 if vol_surge else 1.0
            score  = round(PATTERNS["MORNING_STAR"] * boost, 1)
            pattern = "MORNING_STAR"
            detail  = f"morning star{'(+vol)' if vol_surge else ''}: 3-candle reversal"

    # BULLISH ENGULFING
    if pattern == 'NONE' and len(df) >= 2:
        if (c.iloc[-2] < o.iloc[-2]                     # 전봉 음봉
                and c.iloc[-1] > o.iloc[-1]             # 현봉 양봉
                and o.iloc[-1] < c.iloc[-2]             # 전봉 종가 이하 오픈
                and c.iloc[-1] > o.iloc[-2]):           # 전봉 시가 돌파
            vol_bonus = 3 if vol_surge else 0
            score   = PATTERNS["ENGULFING_BULL"] + vol_bonus
            pattern = "ENGULFING_BULL"
            detail  = f"bullish engulfing{'(+vol)' if vol_surge else ''}"

    # HAMMER
    if pattern == 'NONE':
        body       = abs(c.iloc[-1] - o.iloc[-1])
        lower_wick = min(o.iloc[-1], c.iloc[-1]) - l.iloc[-1]
        upper_wick = h.iloc[-1] - max(o.iloc[-1], c.iloc[-1])
        if body > 0 and lower_wick >= body * 2 and upper_wick <= body * 0.3:
            # trend check: 직전 3봉 하락 중이어야 의미 있음
            if len(df) >= 4 and c.iloc[-4] > c.iloc[-2]:
                score   = PATTERNS["HAMMER"]
                pattern = "HAMMER"
                detail  = "hammer: long lower wick after downtrend"

    # DOJI REVERSAL
    if pattern == 'NONE' and len(df) >= 6:
        body  = abs(c.iloc[-1] - o.iloc[-1])
        range_ = h.iloc[-1] - l.iloc[-1]
        is_doji = range_ > 0 and body / range_ < 0.1
        prior_down = all(c.iloc[-(i+2)] < c.iloc[-(i+3)] for i in range(4))
        if is_doji and prior_down:
            score   = PATTERNS["DOJI_REVERSAL"]
            pattern = "DOJI_REVERSAL"
            detail  = "doji reversal: indecision candle after 4-bar downtrend"

    # ── Clamp & confidence ──
    score      = round(max(SCORE_MIN, min(SCORE_MAX, score)), 1)
    confidence = round(min(abs(score) / SCORE_MAX, 1.0), 2)

    return {
        'candle_score': score,
        'pattern':      pattern,
        'confidence':   confidence,
        'detail':       detail
    }


# ─────────────────────────────────────────────
# Batch scorer (for aggregator integration)
# ─────────────────────────────────────────────
def score_candles_batch(ohlcv_map: dict) -> dict:
    """
    Process multiple tickers.

    Args:
        ohlcv_map: {ticker: pd.DataFrame}

    Returns:
        {ticker: {'candle_score': float, 'pattern': str, 'confidence': float}}
    """
    results = {}
    for ticker, df in ohlcv_map.items():
        try:
            results[ticker] = calculate_candle_score(df)
        except Exception as e:
            logger.warning("BM-14 error for %s: %s", ticker, e)
            results[ticker] = {'candle_score': 0, 'pattern': 'NONE', 'confidence': 0.0, 'detail': str(e)}
    return results


# ─────────────────────────────────────────────
# Aggregator patch helper
# ─────────────────────────────────────────────
def apply_candle_score_to_tech(tech_score: float, candle_result: dict, tech_max: int = 85) -> float:
    """
    Pass2 통합: candle_score를 tech_score에 합산 후 cap 적용.

    Usage in sfd_signal_aggregator.py Pass2:
        from sfd_candle_pattern import apply_candle_score_to_tech, calculate_candle_score
        candle_result = calculate_candle_score(ohlcv_df)
        tech_score = apply_candle_score_to_tech(tech_score, candle_result)
    """
    candle_score = candle_result.get('candle_score', 0)
    new_score    = min(tech_score + candle_score, tech_max)
    new_score    = max(new_score, 0)
    logger.debug(
        "BM-14: tech %s + candle %s = %s (pattern=%s)",
        tech_score, candle_score, new_score, candle_result.get('pattern')
    )
    return round(new_score, 1)


# ─────────────────────────────────────────────
# CLI self-test
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import json

    print("=" * 60)
    print("BM-14 sfd_candle_pattern.py — self-test")
    print("=" * 60)

    # --- Synthetic MORNING STAR ---
    data_ms = {
        'open':   [110, 100, 101, 102, 103, 104, 105, 106, 107, 108,
                   109, 110, 111, 112, 113, 114, 115, 116,  95,  93,  96],
        'high':   [112, 102, 103, 104, 105, 106, 107, 108, 109, 110,
                   111, 112, 113, 114, 115, 116, 117, 118,  97,  94, 100],
        'low':    [108,  98,  99, 100, 101, 102, 103, 104, 105, 106,
                   107, 108, 109, 110, 111, 112, 113, 114,  93,  91,  95],
        'close':  [109,  99, 100, 101, 102, 103, 104, 105, 106, 107,
                   108, 109, 110, 111, 112, 113, 114, 115,  94,  92,  99],
        'volume': [1000]*18 + [1200, 800, 2000]
    }
    df_ms = pd.DataFrame(data_ms)
    r = calculate_candle_score(df_ms)
    print(f"\n[MORNING STAR test] {json.dumps(r, ensure_ascii=False)}")

    # --- Synthetic HAMMER ---
    data_hm = {
        'open':   [100, 98, 96, 94, 92, 91],
        'high':   [101, 99, 97, 95, 93, 92],
        'low':    [ 98, 96, 94, 92, 90, 85],
        'close':  [ 99, 97, 95, 93, 91, 91],
        'volume': [1000]*6
    }
    df_hm = pd.DataFrame(data_hm)
    r = calculate_candle_score(df_hm)
    print(f"[HAMMER test]       {json.dumps(r, ensure_ascii=False)}")

    # --- Synthetic BEARISH ENGULF ---
    data_be = {
        'open':   [90, 92, 94, 96, 98, 100,  99],
        'high':   [92, 94, 96, 98, 100, 102, 103],
        'low':    [89, 91, 93, 95, 97,  99,  91],
        'close':  [91, 93, 95, 97, 99, 101,  92],
        'volume': [1000]*7
    }
    df_be = pd.DataFrame(data_be)
    r = calculate_candle_score(df_be)
    print(f"[BEARISH ENGULF]    {json.dumps(r, ensure_ascii=False)}")

    # --- apply_candle_score_to_tech ---
    tech = 70.0
    result = calculate_candle_score(df_ms)
    new_tech = apply_candle_score_to_tech(tech, result)
    print(f"\n[tech patch] tech={tech} + candle={result['candle_score']} → {new_tech}")
    print("\n✅ BM-14 self-test complete")
