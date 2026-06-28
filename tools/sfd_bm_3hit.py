# sfd_bm_3hit.py — BM-B 3-Hit Breakthrough 돌파 신호
# 확정 설계: Q3=복수후보[10,20,60] 최근접 저항선, Q5=score_delta+10
# Version: 1.0 | 2026-06-15

import pandas as pd
import numpy as np
from typing import Optional

RESISTANCE_LOOKBACKS = [10, 20, 60]
TOUCH_TOLERANCE_PCT  = 0.003
MIN_SIDEWAYS_RATIO   = 0.5
SCORE_DELTA          = 10


def detect_3hit_breakout(
    df: pd.DataFrame,
    lookback_touch: int = 20,
    tolerance_pct: float = TOUCH_TOLERANCE_PCT,
    min_sideways_ratio: float = MIN_SIDEWAYS_RATIO,
) -> dict:
    """
    BM-B: 3-Hit Breakthrough 돌파 신호

    로직:
    1. 복수 후보 저항선 산출 [10, 20, 60봉 전고점]
    2. 현재가 바로 위 최근접 저항선 선택
    3. lookback_touch 기간 내 터치 카운트 >= 3
    4. 횡보 비율 >= 0.5 (에너지 응축 확인)
    5. 최신 종가가 저항선 상향 돌파 확인
    """
    if df is None or len(df) < max(RESISTANCE_LOOKBACKS):
        return _empty_result()

    close = float(df['close'].iloc[-1])
    prev_close = float(df['close'].iloc[-2])

    resistance = _find_best_resistance(df, close)
    if resistance is None:
        return _empty_result(reason='no_valid_resistance')

    window = df.tail(lookback_touch)
    band_lo = resistance * (1 - tolerance_pct)
    band_hi = resistance * (1 + tolerance_pct * 2)

    touch_count = int(
        ((window['high'] >= band_lo) & (window['high'] <= band_hi)).sum()
    )

    sideways_mask = (
        (window['close'] >= resistance * 0.98) &
        (window['close'] <= resistance * 1.02)
    )
    sideways_ratio = round(float(sideways_mask.sum()) / lookback_touch, 3)

    breakout_threshold = resistance * 1.003
    breakout_confirmed = bool(
        (close > breakout_threshold) and (prev_close <= breakout_threshold)
    )

    signal = "3HIT_BREAKOUT" if (
        touch_count >= 3 and
        sideways_ratio >= min_sideways_ratio and
        breakout_confirmed
    ) else "NO_SIGNAL"

    score_delta = SCORE_DELTA if signal == "3HIT_BREAKOUT" else 0

    return {
        'bm_id':              'BM_3HIT',
        'signal':             signal,
        'resistance':         round(resistance, 2),
        'touch_count':        touch_count,
        'sideways_ratio':     sideways_ratio,
        'breakout_confirmed': breakout_confirmed,
        'score_delta':        score_delta,
        'reason':             'ok' if signal == "3HIT_BREAKOUT" else _diagnose(
                                  touch_count, sideways_ratio, breakout_confirmed),
    }


def _find_best_resistance(df: pd.DataFrame, close: float) -> Optional[float]:
    candidates = {}
    for lb in RESISTANCE_LOOKBACKS:
        if len(df) >= lb:
            val = float(df['high'].rolling(lb).max().iloc[-1])
            candidates[f'lb{lb}'] = val

    valid = {k: v for k, v in candidates.items() if v > close * 1.001}
    if not valid:
        return None
    return float(min(valid.values()))


def _diagnose(touch_count, sideways_ratio, breakout_confirmed) -> str:
    reasons = []
    if touch_count < 3:
        reasons.append(f'touch_insufficient({touch_count}<3)')
    if sideways_ratio < MIN_SIDEWAYS_RATIO:
        reasons.append(f'sideways_weak({sideways_ratio:.2f}<{MIN_SIDEWAYS_RATIO})')
    if not breakout_confirmed:
        reasons.append('breakout_not_confirmed')
    return '|'.join(reasons) if reasons else 'unknown'


def _empty_result(reason: str = 'insufficient_data') -> dict:
    return {
        'bm_id':              'BM_3HIT',
        'signal':             'NO_SIGNAL',
        'resistance':         None,
        'touch_count':        0,
        'sideways_ratio':     0.0,
        'breakout_confirmed': False,
        'score_delta':        0,
        'reason':             reason,
    }
