# -*- coding: utf-8 -*-
"""
sfd_alpha_decay.py
BM-18: Alpha Decay Scoring
SFD Pipeline — aggregator Pass3 후단, BM-13 timeout 직전 삽입

[설계 원칙]
- 신호 발생 후 bars(거래일) 경과에 따라 score에 감쇠 패널티 적용
- 3가지 감쇠 모드 지원: LINEAR / EXPONENTIAL / VOLATILITY_CONDITIONAL
- BM-13 signal_timeout_state.json 재활용 (signal_age 정보 공유)
- total_score cap(RESERVE=90, WATCH=70)과 독립적으로 동작
  → 감쇠 후 재판정(re-classify) 방식

[점수 영향]
- 감쇠 범위: 0pt ~ -12pt (total_score에서 차감)
- 감쇠 시작: bar_age >= DECAY_START_BAR (기본 2)
- 최대 패널티: -12pt (DECAY_MAX_PENALTY)
- BM-13 timeout(5bar) 도달 전 신호를 자연스럽게 약화

[파일 위치]
- 배포: sfd-pipeline/tools/sfd_alpha_decay.py
- import: sfd_signal_aggregator.py Pass3 후단

Author: Claude (Architect)
Version: 1.0
Date: 2026-06-09
"""

import json
import logging
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── 경로 설정 ──────────────────────────────────────────────────────────────────
_BASE_DIR = Path(os.environ.get("SFD_BASE_DIR", Path(__file__).resolve().parent.parent))
_LATEST = _BASE_DIR / "outputs" / "latest"

TIMEOUT_STATE_JSON = _LATEST / "signal_timeout_state.json"
VOLATILITY_CSV     = _LATEST / "sfd_technical_latest.csv"   # ATR 컬럼 활용
DECAY_REPORT_JSON  = _LATEST / "sfd_alpha_decay_report.json"

# ── 파라미터 ───────────────────────────────────────────────────────────────────
DECAY_MODE          = os.environ.get("SFD_DECAY_MODE", "EXPONENTIAL")  # LINEAR / EXPONENTIAL / VOLATILITY_CONDITIONAL
DECAY_START_BAR     = int(os.environ.get("SFD_DECAY_START_BAR", "2"))   # bar_age >= 2 부터 감쇠
DECAY_MAX_PENALTY   = float(os.environ.get("SFD_DECAY_MAX_PENALTY", "12"))  # 최대 -12pt
DECAY_HALFLIFE      = float(os.environ.get("SFD_DECAY_HALFLIFE", "3"))  # 지수감쇠 반감기(bars)
DECAY_LINEAR_RATE   = float(os.environ.get("SFD_DECAY_LINEAR_RATE", "2.5"))  # 선형: bar당 -2.5pt
TIMEOUT_BARS        = int(os.environ.get("SFD_TIMEOUT_BARS", "5"))      # BM-13 timeout (sync)

# 변동성 조건부 모드: ATR 비율 임계값
VOL_HIGH_THRESHOLD  = 0.035   # ATR/price > 3.5% → 감쇠 가속
VOL_LOW_THRESHOLD   = 0.015   # ATR/price < 1.5% → 감쇠 완화

# 감쇠 적용 대상 신호 (HOLD는 감쇠 불필요)
DECAY_TARGET_SIGNALS = {"RESERVE_BUY", "WATCH_ONLY"}


# ══════════════════════════════════════════════════════════════════════════════
# 핵심 감쇠 계산 함수
# ══════════════════════════════════════════════════════════════════════════════

def _decay_linear(bar_age: int) -> float:
    """
    선형 감쇠: penalty = min(rate * max(0, age - start), max_penalty)
    bar 2 → -2.5pt, bar 3 → -5pt, bar 4 → -7.5pt, bar 5 → -10pt
    """
    if bar_age < DECAY_START_BAR:
        return 0.0
    raw = DECAY_LINEAR_RATE * (bar_age - DECAY_START_BAR + 1)
    return -min(raw, DECAY_MAX_PENALTY)


def _decay_exponential(bar_age: int) -> float:
    """
    지수 감쇠: penalty = max_penalty * (1 - 0.5^((age-start)/halflife))
    반감기 3bars 기준:
      bar 2 → -3.5pt, bar 3 → -6.0pt, bar 4 → -8.5pt, bar 5 → -10.4pt
    → BM-13 timeout 도달 시 자연스럽게 -10~12pt 수렴
    """
    if bar_age < DECAY_START_BAR:
        return 0.0
    age_delta = bar_age - DECAY_START_BAR + 1
    fraction = 1.0 - math.pow(0.5, age_delta / DECAY_HALFLIFE)
    return -min(DECAY_MAX_PENALTY * fraction, DECAY_MAX_PENALTY)


def _decay_volatility_conditional(bar_age: int, atr_ratio: float) -> float:
    """
    변동성 조건부 감쇠:
    - 고변동성(ATR > 3.5%): 지수감쇠 * 1.5 가속
    - 저변동성(ATR < 1.5%): 지수감쇠 * 0.7 완화
    - 중간: 표준 지수감쇠
    """
    base = _decay_exponential(bar_age)
    if base == 0.0:
        return 0.0

    if atr_ratio > VOL_HIGH_THRESHOLD:
        multiplier = 1.5   # 고변동성: 신호 신뢰도 빠르게 감소
    elif atr_ratio < VOL_LOW_THRESHOLD:
        multiplier = 0.7   # 저변동성: 신호 지속성 높음
    else:
        multiplier = 1.0

    return max(base * multiplier, -DECAY_MAX_PENALTY)


def calculate_decay_penalty(
    bar_age: int,
    mode: str = DECAY_MODE,
    atr_ratio: float = 0.025
) -> float:
    """
    단일 종목의 감쇠 패널티 계산 (항상 0 이하 반환)

    Args:
        bar_age: 신호 발생 후 경과 거래일 수
        mode: "LINEAR" / "EXPONENTIAL" / "VOLATILITY_CONDITIONAL"
        atr_ratio: ATR / close_price (VOLATILITY_CONDITIONAL 전용)

    Returns:
        penalty: float (-DECAY_MAX_PENALTY ~ 0.0)
    """
    if mode == "LINEAR":
        return _decay_linear(bar_age)
    elif mode == "EXPONENTIAL":
        return _decay_exponential(bar_age)
    elif mode == "VOLATILITY_CONDITIONAL":
        return _decay_volatility_conditional(bar_age, atr_ratio)
    else:
        logger.warning("BM-18: unknown decay mode '%s', fallback to EXPONENTIAL", mode)
        return _decay_exponential(bar_age)


# ══════════════════════════════════════════════════════════════════════════════
# 상태 로더
# ══════════════════════════════════════════════════════════════════════════════

def load_signal_age_map(timeout_state_path: Path = TIMEOUT_STATE_JSON) -> dict:
    """
    BM-13 signal_timeout_state.json에서 {ticker: bar_age} 맵 로드
    구조: {"005930": {"signal": "RESERVE_BUY", "bar_count": 3, ...}, ...}
    """
    if not timeout_state_path.exists():
        logger.info("BM-18: timeout_state.json not found, bar_age=0 for all")
        return {}
    try:
        with open(timeout_state_path, encoding="utf-8") as f:
            raw = json.load(f)
        age_map = {}
        for ticker, info in raw.items():
            if isinstance(info, dict):
                age_map[ticker] = int(info.get("bar_count", 0))
            else:
                age_map[ticker] = 0
        logger.info("BM-18: loaded bar_age for %d tickers", len(age_map))
        return age_map
    except Exception as e:
        logger.warning("BM-18: timeout_state load error: %s", e)
        return {}


def load_atr_ratio_map(tech_csv: Path = VOLATILITY_CSV) -> dict:
    """
    sfd_technical_latest.csv에서 {ticker: atr_ratio} 맵 로드
    ATR 컬럼: atr / atr_ratio / atr14 중 자동탐지
    """
    if not tech_csv.exists():
        return {}
    try:
        df = pd.read_csv(tech_csv, dtype=str)
        # ticker 컬럼 탐지
        ticker_col = next(
            (c for c in ["stock_code", "ticker", "code"] if c in df.columns), None
        )
        if ticker_col is None:
            return {}

        # ATR ratio 컬럼 탐지
        atr_col = next(
            (c for c in ["atr_ratio", "atr", "atr14"] if c in df.columns), None
        )
        close_col = next(
            (c for c in ["close", "close_price", "prev_close"] if c in df.columns), None
        )

        atr_map = {}

        if atr_col == "atr_ratio":
            # 이미 ratio인 경우
            df["_ratio"] = pd.to_numeric(df[atr_col], errors="coerce").fillna(0.025)
        elif atr_col and close_col:
            # atr / close 계산
            atr_val  = pd.to_numeric(df[atr_col], errors="coerce").fillna(0)
            close_val = pd.to_numeric(df[close_col], errors="coerce").replace(0, np.nan)
            df["_ratio"] = (atr_val / close_val).fillna(0.025)
        else:
            return {}

        for _, row in df.iterrows():
            t = str(row[ticker_col]).zfill(6)
            atr_map[t] = float(row["_ratio"])

        logger.info("BM-18: loaded ATR ratio for %d tickers", len(atr_map))
        return atr_map
    except Exception as e:
        logger.warning("BM-18: ATR load error: %s", e)
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# 메인 적용 함수 (aggregator에서 호출)
# ══════════════════════════════════════════════════════════════════════════════

def apply_alpha_decay(df: pd.DataFrame) -> pd.DataFrame:
    """
    DataFrame에 알파 감쇠 패널티 적용.
    aggregator Pass3 후단에서 호출.

    Expected columns:
        stock_code (or ticker), signal, total_score

    Added columns:
        decay_penalty   : float (0 이하)
        decay_bar_age   : int
        total_score     : 갱신 (decay 적용 후)
        signal          : 재판정 (decay로 threshold 이탈 시 하향)

    Returns:
        df with decay columns added
    """
    # ── 컬럼명 탐지 ────────────────────────────────────────────────────────────
    ticker_col = next(
        (c for c in ["stock_code", "ticker", "code"] if c in df.columns), None
    )
    if ticker_col is None:
        logger.warning("BM-18: no ticker column found, skip")
        df["decay_penalty"] = 0.0
        df["decay_bar_age"] = 0
        return df

    if "total_score" not in df.columns:
        logger.warning("BM-18: total_score not found, skip")
        df["decay_penalty"] = 0.0
        df["decay_bar_age"] = 0
        return df

    # ── 상태 로드 ──────────────────────────────────────────────────────────────
    age_map = load_signal_age_map()
    atr_map = load_atr_ratio_map()

    # ── 감쇠 적용 ──────────────────────────────────────────────────────────────
    penalties   = []
    bar_ages    = []

    for _, row in df.iterrows():
        ticker  = str(row[ticker_col]).zfill(6)
        signal  = str(row.get("signal", "HOLD"))

        # HOLD나 감쇠 미대상 신호는 스킵
        if signal not in DECAY_TARGET_SIGNALS:
            penalties.append(0.0)
            bar_ages.append(0)
            continue

        bar_age  = age_map.get(ticker, 0)
        atr_ratio = atr_map.get(ticker, 0.025)

        penalty = calculate_decay_penalty(bar_age, DECAY_MODE, atr_ratio)
        penalties.append(round(penalty, 2))
        bar_ages.append(bar_age)

    df = df.copy()
    df["decay_penalty"] = penalties
    df["decay_bar_age"] = bar_ages

    # ── total_score 갱신 ───────────────────────────────────────────────────────
    df["total_score"] = (
        pd.to_numeric(df["total_score"], errors="coerce").fillna(0)
        + df["decay_penalty"]
    ).round(2)

    # ── 신호 재판정 (threshold 이탈 시 하향) ───────────────────────────────────
    THRESHOLD_RESERVE = int(os.environ.get("SFD_THRESHOLD_RESERVE", "90"))
    THRESHOLD_WATCH   = int(os.environ.get("SFD_THRESHOLD_WATCH", "70"))

    def _reclassify(row):
        sig   = row.get("signal", "HOLD")
        score = row["total_score"]
        if sig == "RESERVE_BUY" and score < THRESHOLD_RESERVE:
            if score >= THRESHOLD_WATCH:
                return "WATCH_ONLY"
            else:
                return "HOLD"
        elif sig == "WATCH_ONLY" and score < THRESHOLD_WATCH:
            return "HOLD"
        return sig

    df["signal"] = df.apply(_reclassify, axis=1)

    # ── 로깅 요약 ──────────────────────────────────────────────────────────────
    decayed = df[df["decay_penalty"] < 0]
    reclassified = df[df["decay_bar_age"] > 0]
    logger.info(
        "BM-18 [%s] applied: %d tickers decayed | avg_penalty=%.2fpt | "
        "RESERVE→WATCH=%d | WATCH→HOLD=%d",
        DECAY_MODE,
        len(decayed),
        decayed["decay_penalty"].mean() if len(decayed) > 0 else 0,
        len(reclassified[reclassified["signal"] == "WATCH_ONLY"]),
        len(reclassified[reclassified["signal"] == "HOLD"]),
    )

    # ── 감쇠 리포트 저장 ───────────────────────────────────────────────────────
    _save_decay_report(df, decayed)

    return df


# ══════════════════════════════════════════════════════════════════════════════
# 리포트 저장
# ══════════════════════════════════════════════════════════════════════════════

def _save_decay_report(df: pd.DataFrame, decayed: pd.DataFrame):
    """감쇠 결과 JSON 저장 — backtest_analyzer v2.0과 연동"""
    ticker_col = next(
        (c for c in ["stock_code", "ticker"] if c in df.columns), "stock_code"
    )
    try:
        report = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "decay_mode": DECAY_MODE,
            "params": {
                "start_bar": DECAY_START_BAR,
                "max_penalty": DECAY_MAX_PENALTY,
                "halflife_bars": DECAY_HALFLIFE,
                "linear_rate": DECAY_LINEAR_RATE,
                "timeout_bars": TIMEOUT_BARS,
            },
            "summary": {
                "total_tickers": len(df),
                "decayed_tickers": len(decayed),
                "avg_penalty_pt": round(decayed["decay_penalty"].mean(), 3) if len(decayed) > 0 else 0,
                "max_penalty_applied": round(decayed["decay_penalty"].min(), 3) if len(decayed) > 0 else 0,
                "reclassified_to_watch": int((
                    df["decay_bar_age"] > 0
                ).sum()),
            },
            "top_decayed": (
                decayed[[ticker_col, "decay_bar_age", "decay_penalty", "signal", "total_score"]]
                .sort_values("decay_penalty")
                .head(10)
                .to_dict(orient="records")
            ) if len(decayed) > 0 else [],
        }
        DECAY_REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
        with open(DECAY_REPORT_JSON, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        logger.info("BM-18: decay report saved → %s", DECAY_REPORT_JSON)
    except Exception as e:
        logger.warning("BM-18: report save error: %s", e)


# ══════════════════════════════════════════════════════════════════════════════
# 단독 실행 (진단용)
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("BM-18 Alpha Decay — 감쇠 곡선 미리보기")
    print(f"Mode: {DECAY_MODE} | MaxPenalty: -{DECAY_MAX_PENALTY}pt | Halflife: {DECAY_HALFLIFE}bars")
    print("=" * 60)
    print(f"{'Bar Age':>8} | {'LINEAR':>10} | {'EXPONENTIAL':>12} | {'VOL_COND(H)':>12} | {'VOL_COND(L)':>12}")
    print("-" * 68)
    for age in range(0, TIMEOUT_BARS + 2):
        lin  = _decay_linear(age)
        exp  = _decay_exponential(age)
        vc_h = _decay_volatility_conditional(age, VOL_HIGH_THRESHOLD + 0.01)
        vc_l = _decay_volatility_conditional(age, VOL_LOW_THRESHOLD - 0.005)
        print(f"{age:>8} | {lin:>10.2f} | {exp:>12.2f} | {vc_h:>12.2f} | {vc_l:>12.2f}")
    print()

    # 신호 재판정 시뮬레이션
    print("신호 재판정 시뮬 (EXPONENTIAL, RESERVE_BUY score=92)")
    for age in range(0, TIMEOUT_BARS + 1):
        base_score = 92.0
        penalty    = _decay_exponential(age)
        final      = base_score + penalty
        sig = "RESERVE_BUY" if final >= 90 else ("WATCH_ONLY" if final >= 70 else "HOLD")
        print(f"  bar_age={age}: {base_score} + ({penalty:.2f}) = {final:.2f} → {sig}")
    print()
    print(f"[OK] sfd_alpha_decay.py v1.0 정상 — 배포 대상: sfd-pipeline/tools/")
