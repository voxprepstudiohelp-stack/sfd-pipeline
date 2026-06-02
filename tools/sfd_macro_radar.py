#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Layer -2: SFD MACRO RADAR v1.1
===============================
글로벌 매크로 지표 → 한국 섹터별 boost_score 산출


입력: 실시간 마켓 데이터 (yfinance)
출력: sfd_macro_radar_latest.csv, JSON 메타데이터


주요 변수:
- 환율: DXY, JPY/KRW, CNY/KRW
- 원자재: Gold, Oil, Copper, Lithium(LIT ETF)
- 금리: Fed Funds Rate, BOK Base Rate
- 위험: BTC (Risk-On/Off), VIX (공포지수)
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
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs", "latest")
os.makedirs(OUTPUTS_DIR, exist_ok=True)


OUTPUT_CSV = os.path.join(OUTPUTS_DIR, "sfd_macro_radar_latest.csv")
OUTPUT_JSON = os.path.join(OUTPUTS_DIR, "sfd_macro_radar_latest.json")


# 로깅 설정
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
    "DXY": "DX-Y.NYB",          # 달러 인덱스
    "GOLD": "GC=F",         # 금 선물
    "OIL": "CL=F",          # WTI 유가
    "COPPER": "HG=F",       # 구리 선물
    "LIT": "LIT",           # 리튬 ETF (현물 대체)
    "BTC": "BTC-USD",       # 비트코인
    "VIX": "^VIX",          # 공포지수
    "JPY": "USDJPY=X",      # USD/JPY
    "CNY": "USDCNY=X",      # USD/CNY
    "KRW": "USDKRW=X",      # USD/KRW
    "FED_RATE": "^IRX",     # Fed Funds Rate (3M Treasury  ph�체)
}


# 섹터별 맀표 로직 감도  �QSECTOR_MACRO_MAP = {
    "SEMICONDUCTOR": {
        "DXY_strong": 10,      # 달러 강세 → 수출 수혜
        "DXY_weak": -8,
        "OIL_spike": -5,       # 유가 상승 → 비용 부담
        "COUPER_spike": 5,     # 구리 수혜 → 동향 지표
        "BTC_rally": 8,        # Risk-on → 성장주 수혜
        "VIX_fear": -15,       # 공포 → 차단
    },
    "CHEMICALS": {
        "DXY_strong": 8,
        "DXY_weak": -6,
        "OIL_spike": 10,       # 유가 수혜 (원료)
        "COPPER_spike": 8,
        "BTC_rally": 5,
        "VIX_fear": -12,
    },
    "STEEL": {
        "DXY_strong": 10,
        "DXY_weak": -8,
        "OIL_spike": 5,
        "COPPER_spike": 12,    # 구리 선행 → 경기 신호
        "BTC_rally": 6,
        "VIX_fear": -10,
    },
    "ENERGY": {
        "DXY_strong": 5,
        "DXY_weak": -4,
        "OIL_spike": 15,       # 유가 직접 수혜
        "COPPER_spike": 3,
        "BTC_rally": 4,
        "VIX_fear": -8,
    },
    "SHIPPING": {
        "DXY_strong": 8,
        "DXY_weak": -7,
        "OIL_spike": -8,       # 유가 비용 부담
        "COPPER_spike": 6,
        "BTC_rally": 7,
        "VIX_fear": -18,       # 글로벌 경기 약화 → 운송 약화
    },
    "ENTERTAINMENT": {
        "DXY_strong": -5,      # 달러 강세 → 해외 매출 후퇴
        "DXY_weak": 8,         # 달러 약세 → 해외 매출 증대
        "OIL_spike": -3,
        "COPPER_spike": 2,
        "BTC_rally": 10,       # 리스크 온 → 엔터 성장주 수혜
        "VIX_fear": -12,
    },
    "MATERIALS": {
        "DXY_strong": 5,
        "DXY_weak": -6,
        "OIL_spike": 8,
        "COPPER_spike": 15,    # 구리 선도 → 채광 수혜
        "BTC_rally": 6,
        "VIX_fear": -10,
    },
}


# ===== FETCH MACROS =====
def fetch_macro_indicators(lookback_days=5):
    """
    매크로 지표 수집 (yfinance)
    
    Returns:
        dict: {"DXY": price, "change_%": %, ...}
    """
    logger.info("Fetching macro indicators from yfinance...")
    macros = {}
    end_date = datetime.now()
    start_date = end_date - timedelta(days=lookback_days)
    
    for key, ticker in INDICATORS.items():
        try:
            data = yf.download(ticker, start=start_date, end=end_date, progress=False)
            if data.empty:
                logger.warning(f"No data for {key} ({ticker})")
                continue
            
            current_price = data["Close"].iloc[-1]
            prev_price = data["Close"].iloc[0]
            change_pct = ((current_price - prev_price) / prev_price) * 100
            
            macros[key] = {
                "price": round(current_price, 4),
                "change_%": round(change_pct, 2),
                "ticker": ticker,
            }
            logger.info(f"{key}: {current_price:.4f} ({change_pct:+.2f}%)")
        except Exception as e:
            logger.error(f"Failed to fetch {key}: {e}")
    
    return macros


# ===== SIGNAL GENERATION =====
def generate_macro_signals(macros):
    """
    매크로 지표 → 신호 생성
    
    Returns:
        dict: {
            "DXY_signal": "STRONG" | "WEAK" | "NEUTRAL",
            "OIL_signal": ...,
            "COPPER_signal": ...,
            "VIX_alert": bool,
            "BTC_rally": bool,
        }
    """
    signals = {}
    
    # DXY 신호
    dxy_change = macros.get("DXY", {}).get("change_%", 0)
    if dxy_change > 1.0:
        signals["DXY_signal"] = "STRONG"
    elif dxy_change < -1.0:
        signals["DXY_signal"] = "WEAK"
    else:
        signals["DXY_signal"] = "NEUTRAL"
    
    # 유가 신호 (3% 이상 = 급등)
    oil_change = macros.get("OIL", {}).get("change_%", 0)
    signals["OIL_spike"] = oil_change > 3.0
    
    # 구리 신호
    copper_change = macros.get("COPPER", {}).get("change_%", 0)
    signals["COUPER_spike"] = copper_change > 3.0
    
    # VIX 경보
    vix_price = macros.get("VIX", {}).get("price", 0)
    signals["VIX_alert"] = vix_price > 25.0  # 공포 구간
    
    # BTC 래리 (최근 3일 +10%)
    btc_change = macros.get("BTC", {}).get("change_%", 0)
    signals["BTC_rally"] = btc_change > 10.0
    
    # 리튬 신호
    lit_change = macros.get("LIT", {}).get("change_%", 0)
    signals["LIT_spike"] = lit_change < -3.0  # 리튬 급락 = 배터리주 수혜
    
    # JPY 급등 신호 (일본 캐리 청산)
    jpy_change = macros.get("JPY", {}).get("change_%", 0)
    signals["JPY_squeeze"] = jpy_change > 2.0  # 엔화 급등 = 위험
    
    return signals


# ===== BOOST CALCULATION =====
def calculate_sector_boosts(signals, macros):
    """
    섹터별 boost_score 산출
    
    Returns:
        dict: {
            "SEMICONDUCTOR": {"boost": 8, "reasons": [...]},
            ...
        }
    """
    boosts = {}
    
    for sector, sensitivities in SECTOR_MACRO_MAP.items():
        boost_score = 0
        reasons = []
        
        # DXY 신호
        if signals["DXY_signal"] == "STRONG":
            boost_score += sensitivities["DXY_strong"]
            reasons.append(f"DXY +{sensitivities['DXY_strong']}pt (강세)")
        elif signals["DXY_signal"] == "WEAK":
            boost_score += sensitivities["DXY_weak"]
            reasons.append(f"DXY {sensitivities['DXY_weak']}pt (약세)")
        
        # 유가
        if signals["OIL_spike"]:
            boost_score += sensitivities["OIL_spike"]
            reasons.append(f"OIL +{sensitivities['OIL_spike']}pt (급등)")
        
        # 구리
        if signals["COUPER_spike"]:
            boost_score += sensitivities["COPPER_spike"]
            reasons.append(f"COPPER +{sensitivities['COPPER_spike']}pt (급등)")
        
        # BTC 래리
        if signals["BTC_rally"]:
            boost_score += sensitivities["BTC_rally"]
            reasons.append(f"BTC +{sensitivities['BTC_rally']}pt (rally)")
        
        # VIX 경보
        if signals["VIX_alert"]:
            boost_score += sensitivities["VIX_fear"]
            reasons.append(f"VIX {sensitivities['VIX_fear']}pt (공포)")
        
        # 리튬 급락 (배터리 수혜)
        if signals["LIT_spike"] and sector in ["MATERIALS", "ENERGY"]:
            boost_score -= 8
            reasons.append("LIT -8pt (급락 = 배터리 수요 둔화)")
        
        # 캡핑 (±15pt)
        boost_score = max(-15, min(15, boost_score))
        
        boosts[sector] = {
            "boost": boost_score,
            "reasons": reasons if reasons else ["(중립)"],
        }
    
    return boosts


# ===== MAIN FLOW =====
def main():
    logger.info("=" * 60)
    logger.info("SFD MACRO RADAR v1.1 - 실행 시작")
    logger.info("=" * 60)
    
    # 1. 매크로 지표 수집
    macros = fetch_macro_indicators(lookback_days=5)
    if not macros:
        logger.error("Failed to fetch any macro indicators. Exiting.")
        return False
    
    # 2. 신호 생성
    signals = generate_macro_signals(macros)
    
    # 3. 섹터별 부스트 계산
    sector_boosts = calculate_sector_boosts(signals, macros)
    
    # 4. 출력 CSV 생성
    output_data = []
    for sector, boost_info in sector_boosts.items():
        output_data.append({
            "sector": sector,
            "macro_boost": boost_info["boost"],
            "reasons": " | ".join(boost_info["reasons"]),
            "vix_alert": signals["VIX_alert"],
            "timestamp": datetime.now().isoformat(),
        })
    
    df_output = pd.DataFrame(output_data)
    df_output.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    logger.info(f"✅ CSV 저장: {OUTPUT_CSV}")
    
    # 5. JSON 메타데이터 저장
    json_output = {
        "timestamp": datetime.now().isoformat(),
        "macro_indicators": macros,
        "signals": signals,
        "sector_boosts": sector_boosts,
        "vix_alert": signals["VIX_alert"],
        "vix_value": macros.get("VIX", {}).get("price", None),
    }
    
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(json_output, f, indent=2, ensure_ascii=False)
    logger.info(f"✅ JSON 저장: {OUTPUT_JSON}")
    
    # 6. 콘솔 요약
    logger.info("\n" + "=" * 60)
    logger.info("📊 매크로 지표 스냅샷")
    logger.info("=" * 60)
    for key, data in macros.items():
        logger.info(f"{key:12s}: {data['price']:10.4f} ({data['change_%']:+7.2f}%)")
    
    logger.info("\n" + "=" * 60)
    logger.info("🚨 신호 요약")
    logger.info("=" * 60)
    for sig, val in signals.items():
        logger.info(f"{sig:20s}: {val}")
    
    logger.info("\n" + "=" * 60)
    logger.info("💰 섹터별 MACRO BOOST")
    logger.info("=" * 60)
    for sector, info in sector_boosts.items():
        boost = info["boost"]
        icon = "🟢" if boost > 0 else ("🔴" if boost < 0 else "⚪")
        logger.info(f"{icon} {sector:20s}: {boost:+3d}pt")
        for reason in info["reasons"]:
            logger.info(f"   └─ {reason}")
    
    logger.info("\n" + "=" * 60)
    logger.info("✅ MACRO RADAR 실행 완료")
    logger.info("=" * 60)
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)