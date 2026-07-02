# sfd_bm_waist.py — BM-3 Waist (허리) 바이어스 피벗
# 확정 설계: Q1=멀티lookback중위값, Q2=종가기준
# Version: 1.0 | 2026-06-15

import pandas as pd
import numpy as np
from typing import Optional

WAIST_LOOKBACKS = [10, 20, 40]  # 단기/중기/장기 마디 후보


def compute_waist_bias(
    df: pd.DataFrame,
    lookbacks: list = WAIST_LOOKBACKS,
    guardian_threshold_pct: float = -3.0
) -> dict:
    """
    BM-3 고도화: 허리(Waist) 바이어스 피벗 산출

    Args:
        df: OHLCV DataFrame (columns: open, high, low, close, volume)
        lookbacks: 마디 후보 lookback 리스트 [단기, 중기, 장기]
        guardian_threshold_pct: waist_pct 이 값 미만 시 Guardian 경고 (기본 -3.0%)

    Returns:
        dict:
            waist         - 확정 허리가격 (3개 중위값)
            waist_pct     - 현재가의 허리 대비 위치 (%)
            bias          - "LONG" | "BLOCK"
            guardian_warn - True if waist_pct < guardian_threshold_pct
            detail        - 각 lookback별 허리 상세
            score_delta   - 0 (게이트 역할, 직접 점수 없음)
            bm_id         - "BM_WAIST"
    """
    if df is None or len(df) < max(lookbacks):
        return _empty_result()

    close = df['close'].iloc[-1]

    # 각 lookback별 허리 산출
    waist_candidates = []
    detail = {}
    for lb in lookbacks:
        if len(df) < lb:
            continue
        madi_high = df['high'].rolling(lb).max().iloc[-1]
        madi_low  = df['low'].rolling(lb).min().iloc[-1]
        waist_lb  = (madi_high + madi_low) / 2.0
        waist_candidates.append(waist_lb)
        detail[f'lb{lb}'] = {
            'madi_high': round(float(madi_high), 2),
            'madi_low':  round(float(madi_low), 2),
            'waist':     round(float(waist_lb), 2),
        }

    if not waist_candidates:
        return _empty_result()

    # 중위값 선택 (Q1 확정)
    waist_final = float(np.median(waist_candidates))

    # 종가 기준 판정 (Q2 확정)
    bias = "LONG" if close > waist_final else "BLOCK"

    # 허리 대비 위치 (%)
    waist_pct = (close - waist_final) / waist_final * 100

    # Guardian 경고 여부
    guardian_warn = waist_pct < guardian_threshold_pct

    return {
        'bm_id':          'BM_WAIST',
        'waist':          round(waist_final, 2),
        'waist_pct':      round(waist_pct, 2),
        'bias':           bias,
        'guardian_warn':  guardian_warn,
        'detail':         detail,
        'score_delta':    0,   # 게이트 역할 — 직접 점수 없음
    }


def apply_waist_gate(bm_scores: dict, waist_result: dict) -> dict:
    """
    Waist BLOCK 시 BUY 계열 BM 점수 전량 억제.
    aggregator v4.1에서 호출.
    """
    if waist_result.get('bias') == 'BLOCK':
        BUY_BMS = {'BM_3HIT', 'BM_AF_TRAP', 'BM_ZONE_PULLBACK',
                   'BM_YEODOLMA', 'BM_JINGYEOK', 'BM_CHIRYANGCHEON'}
        for key in list(bm_scores.keys()):
            if key in BUY_BMS:
                bm_scores[key] = 0
        bm_scores['_waist_blocked'] = True
    else:
        bm_scores['_waist_blocked'] = False

    bm_scores['_guardian_warn'] = waist_result.get('guardian_warn', False)
    return bm_scores


def _empty_result() -> dict:
    return {
        'bm_id':         'BM_WAIST',
        'waist':         None,
        'waist_pct':     None,
        'bias':          'BLOCK',
        'guardian_warn': False,
        'detail':        {},
        'score_delta':   0,
    }
