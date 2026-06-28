# sfd_bm_af_trap.py — BM-C AF_TRAP (Alpha-Fail Trap Reversal)
# 확정 설계: Q4=recovery_bars 5봉, Q5=score_delta +12
# 선결조건: Waist bias == "LONG" (하락추세 AF는 트랩으로 배제)
# Version: 1.0 | 2026-06-15

import pandas as pd
import numpy as np
from typing import Optional

RECOVERY_BARS       = 5
ATR_BREACH_RATIO    = 0.20
ATR_PERIOD          = 14
TARGET_MULTIPLIER   = 1.5
SCORE_DELTA         = 12
LOOKBACK_LOW        = 20


def detect_af_trap(
    df: pd.DataFrame,
    waist_bias: str = "LONG",
    recovery_bars: int = RECOVERY_BARS,
    atr_breach_ratio: float = ATR_BREACH_RATIO,
) -> dict:
    """
    BM-C: AF_TRAP (Alpha-Fail Trap Reversal) 반전 신호

    로직:
    1. [선결] Waist bias == "LONG" — 하락추세 AF는 트랩으로 배제
    2. 전저점(recent_low) 산출 (LOOKBACK_LOW 기간 내 피봇 저점)
    3. 현재 저가가 recent_low 하향 이탈
    4. 이탈 깊이 < ATR * 0.20 (얕은 이탈 = 속임수)
    5. recovery_bars(5봉) 내 종가가 recent_low 상향 복귀
    6. 회복봉 거래량 > 이탈봉 거래량 (매수세 확인)
    """
    if df is None or len(df) < LOOKBACK_LOW + recovery_bars:
        return _empty_result(reason='insufficient_data')

    if waist_bias != "LONG":
        return _empty_result(reason='waist_blocked')

    atr = _compute_atr(df, ATR_PERIOD)
    if atr is None or atr == 0:
        return _empty_result(reason='atr_unavailable')

    lookback_window = df.iloc[-(LOOKBACK_LOW + recovery_bars):-recovery_bars]
    recent_low = float(lookback_window['low'].min())

    current_low   = float(df['low'].iloc[-1])
    current_close = float(df['close'].iloc[-1])

    breach_depth  = recent_low - current_low
    atr_threshold = atr * atr_breach_ratio

    is_shallow_breach = bool(
        (current_low < recent_low) and
        (breach_depth > 0) and
        (breach_depth < atr_threshold)
    )

    recovery_window = df.tail(recovery_bars)
    recovered = bool((recovery_window['close'] > recent_low).any())

    vol_current  = float(df['volume'].iloc[-1])
    vol_previous = float(df['volume'].iloc[-2])
    vol_confirm  = bool(vol_current > vol_previous)

    signal = "AF_TRAP_REVERSAL" if (
        is_shallow_breach and recovered and vol_confirm
    ) else "NO_SIGNAL"

    score_delta       = SCORE_DELTA if signal == "AF_TRAP_REVERSAL" else 0
    target_multiplier = TARGET_MULTIPLIER if signal == "AF_TRAP_REVERSAL" else 1.0

    return {
        'bm_id':             'BM_AF_TRAP',
        'signal':            signal,
        'recent_low':        round(recent_low, 2),
        'breach_depth':      round(breach_depth, 2),
        'atr':               round(atr, 2),
        'atr_threshold':     round(atr_threshold, 2),
        'is_shallow_breach': is_shallow_breach,
        'recovered':         recovered,
        'vol_confirm':       vol_confirm,
        'target_multiplier': target_multiplier,
        'score_delta':       score_delta,
        'reason':            'ok' if signal == "AF_TRAP_REVERSAL" else _diagnose(
                                 is_shallow_breach, recovered, vol_confirm),
    }


def _compute_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> Optional[float]:
    if len(df) < period + 1:
        return None
    high  = df['high']
    low   = df['low']
    close = df['close']
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]
    return float(atr) if not np.isnan(atr) else None


def _diagnose(is_shallow, recovered, vol_confirm) -> str:
    reasons = []
    if not is_shallow:
        reasons.append('breach_too_deep_or_none')
    if not recovered:
        reasons.append(f'not_recovered_in_{RECOVERY_BARS}bars')
    if not vol_confirm:
        reasons.append('volume_not_confirmed')
    return '|'.join(reasons) if reasons else 'unknown'


def _empty_result(reason: str = 'unknown') -> dict:
    return {
        'bm_id':             'BM_AF_TRAP',
        'signal':            'NO_SIGNAL' if reason != 'waist_blocked' else 'BLOCKED_WAIST',
        'recent_low':        None,
        'breach_depth':      None,
        'atr':               None,
        'atr_threshold':     None,
        'is_shallow_breach': False,
        'recovered':         False,
        'vol_confirm':       False,
        'target_multiplier': 1.0,
        'score_delta':       0,
        'reason':            reason,
    }
