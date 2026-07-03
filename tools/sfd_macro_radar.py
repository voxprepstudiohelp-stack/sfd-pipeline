#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Layer -2: SFD MACRO RADAR v1.3
===============================
[v1.2 → v1.3 변경사항]
- DXY 티커 수정: "DXY=F" → "DX-Y.NYB"  (ICE 달러인덱스 현물, yfinance 안정 티커)
  근거: DXY=F는 yfinance에서 데이터 공백 빈번 → DX-Y.NYB로 교체
- MultiIndex 처리 시 ticker 키 DX-Y.NYB 반영 (하이픈 포함 티커 안전 처리)
작성: Claude (SFD 메인 아키텍트) | 2026.07.03
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance not installed. Run: pip install yfinance")
    sys.exit(1)

# ===== CONFIG =====
_env_base = os.environ.get("SFD_BASE_DIR", "")
if _env_base and os.path.isdir(_env_base):
    BASE_DIR = _env_base
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs", "latest")
os.makedirs(OUTPUTS_DIR, exist_ok=True)

OUTPUT_CSV  = os.path.join(OUTPUTS_DIR, "sfd_macro_radar_latest.csv")
OUTPUT_JSON = os.path.join(OUTPUTS_DIR, "sfd_macro_radar_latest.json")

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(asctime)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(OUTPUTS_DIR, "macro_radar.log")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ===== MACRO INDICATORS =====
INDICATORS = {
    "DXY":      "DX-Y.NYB",   # 달러 인덱스 [v1.3: DXY=F → DX-Y.NYB]
    "GOLD":     "GC=F",        # 금 선물
    "OIL":      "CL=F",        # WTI 유가
    "COPPER":   "HG=F",        # 구리 선물
    "LIT":      "LIT",         # 리튬 ETF
    "BTC":      "BTC-USD",     # 비트코인
    "VIX":      "^VIX",        # 공포지수
    "JPY":      "USDJPY=X",   # USD/JPY
    "CNY":      "USDCNY=X",   # USD/CNY
    "KRW":      "USDKRW=X",   # USD/KRW
    "FED_RATE": "^IRX",        # Fed Funds Rate (3M Treasury)
}

# ===== 섹터별 매크로 감도 맵 =====
SECTOR_MACRO_MAP = {
    "SEMICONDUCTOR": {
        "DXY_strong": 10, "DXY_weak": -8,
        "OIL_spike": -5, "COPPER_spike": 5,
        "BTC_rally": 8,  "VIX_fear": -15,
    },
    "CHEMICALS": {
        "DXY_strong": 8,  "DXY_weak": -6,
        "OIL_spike": 10,  "COPPER_spike": 8,
        "BTC_rally": 5,   "VIX_fear": -12,
    },
    "STEEL": {
        "DXY_strong": 10, "DXY_weak": -8,
        "OIL_spike": 5,   "COPPER_spike": 12,
        "BTC_rally": 6,   "VIX_fear": -10,
    },
    "ENERGY": {
        "DXY_strong": 5,  "DXY_weak": -4,
        "OIL_spike": 15,  "COPPER_spike": 3,
        "BTC_rally": 4,   "VIX_fear": -8,
    },
    "SHIPPING": {
        "DXY_strong": 8,  "DXY_weak": -7,
        "OIL_spike": -8,  "COPPER_spike": 6,
        "BTC_rally": 7,   "VIX_fear": -18,
    },
    "ENTERTAINMENT": {
        "DXY_strong": -5, "DXY_weak": 8,
        "OIL_spike": -3,  "COPPER_spike": 2,
        "BTC_rally": 10,  "VIX_fear": -12,
    },
    "MATERIALS": {
        "DXY_strong": 5,  "DXY_weak": -6,
        "OIL_spike": 8,   "COPPER_spike": 15,
        "BTC_rally": 6,   "VIX_fear": -10,
    },
    "POWER_INFRA": {  # LS·두산에너빌리티·한전기술 대응
        "DXY_strong": 6,  "DXY_weak": -5,
        "OIL_spike": 8,   "COPPER_spike": 10,
        "BTC_rally": 3,   "VIX_fear": -8,
    },
}

# ===== [v1.2] REGIME 분류 =====
REGIME_MULTIPLIER = {
    "bull":    1.2,   # 포지션 확대 허용
    "neutral": 1.0,   # 기본 운용
    "bear":    0.0,   # RESERVE_BUY 전면 차단
}

def classify_macro(m_score: float) -> str:
    if m_score >= 5:
        return "bull"
    elif m_score <= -5:
        return "bear"
    else:
        return "neutral"

def get_regime_action(regime: str) -> str:
    actions = {
        "bull":    "FULL_OPERATION  | 포지션 확대 허용 (×1.2)",
        "neutral": "NORMAL_OPERATION| 기본 운용",
        "bear":    "SIGNAL_BLOCKED  | RESERVE_BUY 전면 차단 (×0.0)",
    }
    return actions.get(regime, "NORMAL_OPERATION")


# ===== FETCH MACROS =====
def fetch_macro_indicators(lookback_days=5):
    """
    매크로 지표 수집 (yfinance)
    [v1.3] DX-Y.NYB 하이픈 포함 티커 MultiIndex 안전 처리
    """
    logger.info("Fetching macro indicators from yfinance...")
    macros = {}
    end_date   = datetime.now()
    start_date = end_date - timedelta(days=lookback_days)

    for key, ticker in INDICATORS.items():
        try:
            data = yf.download(ticker, start=start_date, end=end_date, progress=False)
            if data is None or data.empty:
                logger.warning(f"No data for {key} ({ticker})")
                continue

            # [v1.3] MultiIndex 처리 — DX-Y.NYB 같은 특수문자 티커 포함
            close_col = None
            if isinstance(data.columns, pd.MultiIndex):
                level0 = data.columns.get_level_values(0)
                level1 = data.columns.get_level_values(1)
                for col_type in ["Close", "Adj Close"]:
                    if col_type in level0:
                        if ticker in level1:
                            close_col = (col_type, ticker)
                        else:
                            matching = [(c0, c1) for c0, c1 in data.columns if c0 == col_type]
                            if matching:
                                close_col = matching[0]
                        break
            else:
                if "Close" in data.columns:
                    close_col = "Close"
                elif "Adj Close" in data.columns:
                    close_col = "Adj Close"

            if close_col is None:
                logger.warning(f"No Close column for {key} ({ticker})")
                continue

            close_series = data[close_col].dropna()
            if len(close_series) < 2:
                logger.warning(f"Insufficient data for {key} ({ticker}): {len(close_series)} rows")
                continue

            current_price = float(close_series.iloc[-1])
            prev_price    = float(close_series.iloc[0])
            change_pct    = ((current_price - prev_price) / prev_price) * 100

            macros[key] = {
                "price":    round(current_price, 4),
                "change_%": round(change_pct, 2),
                "ticker":   ticker,
            }
            logger.info(f"{key} ({ticker}): {current_price:.4f} ({change_pct:+.2f}%)")

        except Exception as e:
            logger.error(f"Failed to fetch {key} ({ticker}): {e}")

    return macros


# ===== SIGNAL GENERATION =====
def generate_macro_signals(macros):
    """매크로 지표 → 신호 생성"""
    signals = {}

    dxy_change    = macros.get("DXY",    {}).get("change_%", 0)
    oil_change    = macros.get("OIL",    {}).get("change_%", 0)
    copper_change = macros.get("COPPER", {}).get("change_%", 0)
    vix_price     = macros.get("VIX",    {}).get("price",    0)
    btc_change    = macros.get("BTC",    {}).get("change_%", 0)
    lit_change    = macros.get("LIT",    {}).get("change_%", 0)

    if dxy_change > 1.0:
        signals["DXY_signal"] = "STRONG"
    elif dxy_change < -1.0:
        signals["DXY_signal"] = "WEAK"
    else:
        signals["DXY_signal"] = "NEUTRAL"

    signals["OIL_spike"]    = oil_change    > 3.0
    signals["COPPER_spike"] = copper_change > 3.0
    signals["VIX_alert"]    = vix_price     > 25.0
    signals["BTC_rally"]    = btc_change    > 10.0
    signals["LIT_spike"]    = lit_change    > 5.0

    logger.info(f"Macro signals: {signals}")
    return signals


# ===== SECTOR BOOST CALCULATION =====
def calc_sector_boost(signals):
    """섹터별 매크로 부스트 산출"""
    sector_boosts = {}

    for sector, sensitivity in SECTOR_MACRO_MAP.items():
        boost = 0

        if signals.get("DXY_signal") == "STRONG":
            boost += sensitivity.get("DXY_strong", 0)
        elif signals.get("DXY_signal") == "WEAK":
            boost += sensitivity.get("DXY_weak", 0)

        if signals.get("OIL_spike"):
            boost += sensitivity.get("OIL_spike", 0)
        if signals.get("COPPER_spike"):
            boost += sensitivity.get("COPPER_spike", 0)
        if signals.get("BTC_rally"):
            boost += sensitivity.get("BTC_rally", 0)
        if signals.get("VIX_alert"):
            boost += sensitivity.get("VIX_fear", 0)

        sector_boosts[sector] = boost
        logger.info(f"Sector {sector}: macro_boost={boost}")

    return sector_boosts


# ===== [v1.2] M_SCORE 산출 & REGIME 판정 =====
def calc_m_score_and_regime(sector_boosts: dict) -> tuple:
    """
    전체 섹터 부스트 합산 → m_score → regime 판정
    Returns: (m_score, regime, multiplier)
    """
    if not sector_boosts:
        return 0.0, "neutral", 1.0

    m_score    = round(sum(sector_boosts.values()) / len(sector_boosts), 2)
    regime     = classify_macro(m_score)
    multiplier = REGIME_MULTIPLIER[regime]

    logger.info(f"[REGIME] m_score={m_score} → regime={regime} (multiplier={multiplier})")
    if regime == "bear":
        logger.warning("[REGIME] ⚠ BEAR DETECTED — RESERVE_BUY 전면 차단")
    elif regime == "bull":
        logger.info("[REGIME] ✅ BULL — 포지션 확대 허용")

    return m_score, regime, multiplier


# ===== MAIN =====
def run():
    logger.info("=== SFD MACRO RADAR v1.3 START ===")
    logger.info(f"OUTPUTS_DIR: {OUTPUTS_DIR}")

    macros        = fetch_macro_indicators(lookback_days=5)
    signals       = generate_macro_signals(macros)
    sector_boosts = calc_sector_boost(signals)
    m_score, regime, multiplier = calc_m_score_and_regime(sector_boosts)

    # 출력 DataFrame
    rows = []
    for sector, boost in sector_boosts.items():
        rows.append({
            "sector":       sector,
            "macro_boost":  boost,
            "vix_alert":    signals.get("VIX_alert",    False),
            "btc_rally":    signals.get("BTC_rally",    False),
            "dxy_signal":   signals.get("DXY_signal",   "NEUTRAL"),
            "oil_spike":    signals.get("OIL_spike",    False),
            "copper_spike": signals.get("COPPER_spike", False),
            "m_score":      m_score,
            "regime":       regime,
            "multiplier":   multiplier,
            "fetch_time":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    logger.info(f"[OK] {OUTPUT_CSV}")

    # JSON 메타데이터
    meta = {
        "fetch_time":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "m_score":       m_score,
        "regime":        regime,
        "multiplier":    multiplier,
        "regime_action": get_regime_action(regime),
        "signals":       {k: (str(v) if isinstance(v, bool) else v) for k, v in signals.items()},
        "macros":        {k: v for k, v in macros.items()},
        "sector_boosts": sector_boosts,
    }
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    logger.info(f"[OK] {OUTPUT_JSON}")

    logger.info("=== SFD MACRO RADAR v1.3 DONE ===")
    return meta


if __name__ == "__main__":
    result = run()
    print(f"\n[최종 결과]")
    print(f"  m_score  : {result['m_score']}")
    print(f"  regime   : {result['regime'].upper()}")
    print(f"  multiplier: ×{result['multiplier']}")
    print(f"  action   : {result['regime_action']}")
