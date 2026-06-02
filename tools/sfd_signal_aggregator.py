#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SFD Signal Aggregator v3.2
==========================
기술 + 뉴스 + 투자자흐름 + 테마 + 펀더멘탈 신호 통합
+ Layer 0.5 (글로벌 트리거) 부스트
+ Layer -2 (매크로 레이더) 부스트


스코어 아키텍처 (max 225pt):
  기술(93) + 뉴스(30) + 투자자(20) + 테마(10) + 펀더멘탈(15)
  + 바이어스(±5)[BM-3] + 볼륨급증(10)[BM-10] + 존풀백(15)[BM-12]
  + 글로벌(±20)[L0.5] + 매크로(±15)[L-2]
"""


import os
import sys
import json
import logging
from datetime import datetime
import pandas as pd
import numpy as np


# ===== CONFIG =====
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs", "latest")
os.makedirs(OUTPUTS_DIR, exist_ok=True)


# 입력 파일 경로 (Layer 1~2.6 아웃풋)
TECH_CSV = os.path.join(OUTPUTS_DIR, "sfd_technical_latest.csv")
NEWS_CSV = os.path.join(OUTPUTS_DIR, "sfd_news_sentiment_latest.csv")
INVESTOR_CSV = os.path.join(OUTPUTS_DIR, "sfd_investor_flow_latest.csv")
THEME_CSV = os.path.join(OUTPUTS_DIR, "sfd_theme_score_latest.csv")
FUND_CSV = os.path.join(OUTPUTS_DIR, "sfd_fundamental_watch_latest.csv")
RERATING_CSV = os.path.join(OUTPUTS_DIR, "sfd_rerating_watch_latest.csv")
SECTOR_CSV = os.path.join(OUTPUTS_DIR, "sfd_sector_injector_latest.csv")


# Layer 0.5 글로벌 트리거
GLOBAL_TRIGGER_CSV = os.path.join(OUTPUTS_DIR, "sfd_global_trigger_latest.csv")


# Layer -2 매크로 레이더
MACRO_RADAR_CSV = os.path.join(OUTPUTS_DIR, "sfd_macro_radar_latest.csv")


# 출력
OUTPUT_CSV = os.path.join(OUTPUTS_DIR, "sfd_master_signal_latest.csv")


# 로깅
logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(asctime)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(OUTPUTS_DIR, "aggregator.log")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ===== THRESHOLD =====
# v3.2: Run #67 전종목 HOLD 분석 → 실효 점수대 재조정
# tech(93)+news(30)+investor(20)+theme(10)+fund(15)=168pt max 기준
# RESERVE_BUY: 70→55 (상위 ~33%), WATCH_ONLY: 50→40 (상위 ~24%)
THRESHOLD_RESERVE = 55
THRESHOLD_WATCH = 40


# ===== LOAD INPUTS =====
def load_all_inputs():
    """모든 입력 CSV 로드"""
    logger.info("Loading input signals from Layer 1~2.6...")
    
    inputs = {}
    
    # 기술 분석
    if os.path.exists(TECH_CSV):
        tech_df = pd.read_csv(TECH_CSV)
        tech_df.rename(columns={"score": "tech_score"}, inplace=True)
        inputs["tech"] = tech_df
        logger.info(f"✓ Technical: {len(tech_df)} rows")
    
    # 뉴스 감정
    if os.path.exists(NEWS_CSV):
        news_df = pd.read_csv(NEWS_CSV)
        news_df.rename(columns={"sentiment_score": "news_score"}, inplace=True)
        inputs["news"] = news_df
        logger.info(f"✓ News: {len(news_df)} rows")
    
    # 투자자 흐름
    if os.path.exists(INVESTOR_CSV):
        investor_df = pd.read_csv(INVESTOR_CSV)
        investor_df.rename(columns={"investor_score": "investor_score"}, inplace=True)
        inputs["investor"] = investor_df
        logger.info(f"✓ Investor: {len(investor_df)} rows")
    
    # 테마
    if os.path.exists(THEME_CSV):
        theme_df = pd.read_csv(THEME_CSV)
        theme_df.rename(columns={"theme_score": "theme_score"}, inplace=True)
        inputs["theme"] = theme_df
        logger.info(f"✓ Theme: {len(theme_df)} rows")
    
    # 펀더멘탈
    if os.path.exists(FUND_CSV):
        fund_df = pd.read_csv(FUND_CSV)
        fund_df.rename(columns={"fund_score": "fund_score"}, inplace=True)
        inputs["fund"] = fund_df
        logger.info(f"✓ Fundamental: {len(fund_df)} rows")
    
    # 리레이팅
    if os.path.exists(RERATING_CSV):
        rerating_df = pd.read_csv(RERATING_CSV)
        inputs["rerating"] = rerating_df
        logger.info(f"✓ Rerating: {len(rerating_df)} rows")
    
    # 섹터
    if os.path.exists(SECTOR_CSV):
        sector_df = pd.read_csv(SECTOR_CSV)
        inputs["sector"] = sector_df
        logger.info(f"✓ Sector: {len(sector_df)} rows")
    
    return inputs


# ===== LOAD LAYER 0.5 GLOBAL TRIGGER =====
def load_global_trigger_map():
    """Layer 0.5 글로벌 트리거 맵 로드"""
    if not os.path.exists(GLOBAL_TRIGGER_CSV):
        logger.warning(f"Global trigger CSV not found: {GLOBAL_TRIGGER_CSV}")
        return {}
    
    try:
        gt_df = pd.read_csv(GLOBAL_TRIGGER_CSV)
        # stock_code → global_boost 맵
        gt_map = dict(zip(gt_df["stock_code"], gt_df["boost_score"]))
        logger.info(f"✓ Global Trigger Map: {len(gt_map)} tickers")
        return gt_map
    except Exception as e:
        logger.error(f"Failed to load global trigger: {e}")
        return {}


# ===== LOAD LAYER -2 MACRO RADAR =====
def load_macro_boost_map():
    """Layer -2 매크로 레이더 부스트 맵 로드"""
    if not os.path.exists(MACRO_RADAR_CSV):
        logger.warning(f"Macro radar CSV not found: {MACRO_RADAR_CSV}")
        return {}
    
    try:
        macro_df = pd.read_csv(MACRO_RADAR_CSV)
        # sector → macro_boost 맵
        macro_map = dict(zip(macro_df["sector"], macro_df["macro_boost"]))
        logger.info(f"✓ Macro Boost Map: {len(macro_map)} sectors")
        return macro_map
    except Exception as e:
        logger.error(f"Failed to load macro radar: {e}")
        return {}


# ===== MASTER SIGNAL AGGREGATION =====
def aggregate_signals(inputs, global_trigger_map, macro_boost_map):
    """
    마스터 신호 통합
    
    Returns:
        DataFrame: stock_code, name, signal, total_score, ...
    """
    logger.info("Aggregating all signals...")
    
    # 기술 분석을 기반으로 시작
    if "tech" not in inputs:
        logger.error("Technical analysis data required!")
        return pd.DataFrame()
    
    master = inputs["tech"].copy()
    
    # stock_code 추출 (ticker 또는 stock_code 컬럼 자동 탐지)
    code_col = next((c for c in master.columns if c in ["stock_code", "ticker"]), master.columns[0])
    master.rename(columns={code_col: "stock_code"}, inplace=True)
    
    # tech_score를 기본 점수로 (93pt)
    master.rename(columns={"tech_score": "score"}, inplace=True)
    if "score" not in master.columns:
        master["score"] = 0.0
    
    # 뉴스 감정 병합 (30pt)
    if "news" in inputs:
        news_agg = inputs["news"].groupby("stock_code")["news_score"].mean()
        master = master.merge(
            news_agg.to_frame().reset_index(),
            on="stock_code",
            how="left"
        )
        master["news_score"].fillna(0, inplace=True)
        master["score"] += master["news_score"]
    else:
        master["news_score"] = 0.0
    
    # 투자자 흐름 병합 (20pt)
    if "investor" in inputs:
        investor_agg = inputs["investor"].groupby("stock_code")["investor_score"].mean()
        master = master.merge(
            investor_agg.to_frame().reset_index(),
            on="stock_code",
            how="left"
        )
        master["investor_score"].fillna(0, inplace=True)
        master["score"] += master["investor_score"]
    else:
        master["investor_score"] = 0.0
    
    # 테마 점수 병합 (10pt)
    if "theme" in inputs:
        theme_agg = inputs["theme"].groupby("stock_code")["theme_score"].mean()
        master = master.merge(
            theme_agg.to_frame().reset_index(),
            on="stock_code",
            how="left"
        )
        master["theme_score"].fillna(0, inplace=True)
        master["score"] += master["theme_score"]
    else:
        master["theme_score"] = 0.0
    
    # 펀더멘탈 점수 병합 (15pt)
    if "fund" in inputs:
        fund_agg = inputs["fund"].groupby("stock_code")["fund_score"].mean()
        master = master.merge(
            fund_agg.to_frame().reset_index(),
            on="stock_code",
            how="left"
        )
        master["fund_score"].fillna(0, inplace=True)
        master["score"] += master["fund_score"]
    else:
        master["fund_score"] = 0.0
    
    # BM-3 바이어스 (±5pt)
    if "rerating" in inputs:
        bias_agg = inputs["rerating"].groupby("stock_code")["bias_score"].mean()
        master = master.merge(
            bias_agg.to_frame().reset_index().rename(columns={"bias_score": "bias"}),
            on="stock_code",
            how="left"
        )
        master["bias"].fillna(0, inplace=True)
        master["score"] += master["bias"]
    else:
        master["bias"] = 0.0
    
    # BM-10 볼륨 급증 (10pt, 이미 tech_score에 포함 가능)
    master["vol_surge"] = 0.0
    
    # BM-12 존 풀백 (15pt, 이미 tech_score에 포함 가능)
    master["zone_pullback"] = 0.0
    
    # Layer 0.5 글로벌 부스트 (±20pt)
    master["global_boost"] = master["stock_code"].map(global_trigger_map).fillna(0)
    master["score"] += master["global_boost"]
    
    # Layer -2 매크로 부스트 (±15pt)
    # sector 정보 필요 - sector_df에서 조회
    if "sector" in inputs:
        sector_map = dict(zip(inputs["sector"]["stock_code"], inputs["sector"]["sector"]))
        master["sector"] = master["stock_code"].map(sector_map)
        master["macro_boost"] = master["sector"].map(macro_boost_map).fillna(0)
        master["score"] += master["macro_boost"]
    else:
        master["macro_boost"] = 0.0
    
    # 신호 판정
    def determine_signal(row):
        score = row["score"]
        if score >= THRESHOLD_RESERVE:
            return "RESERVE_BUY"
        elif score >= THRESHOLD_WATCH:
            return "WATCH_ONLY"
        else:
            return "HOLD"
    
    master["signal"] = master.apply(determine_signal, axis=1)
    
    # 최종 컬럼 정렬
    col_order = [
        "stock_code", "name", "signal", "score",
        "tech_score", "news_score", "investor_score", "theme_score", "fund_score",
        "bias", "vol_surge", "zone_pullback",
        "global_boost", "macro_boost",
    ]
    col_order = [c for c in col_order if c in master.columns]
    master = master[col_order]
    
    # 스코어 내림차순 정렬
    master.sort_values("score", ascending=False, inplace=True)
    
    logger.info(f"✓ Aggregated {len(master)} signals")
    logger.info(f"  RESERVE_BUY: {len(master[master['signal']=='RESERVE_BUY'])}")
    logger.info(f"  WATCH_ONLY: {len(master[master['signal']=='WATCH_ONLY'])}")
    
    return master


# ===== MAIN =====
def main():
    logger.info("=" * 70)
    logger.info("SFD Signal Aggregator v3.2 - 실행 시작")
    logger.info("=" * 70)
    
    # 1. 입력 로드
    inputs = load_all_inputs()
    if not inputs:
        logger.error("No input signals loaded. Exiting.")
        return False
    
    # 2. Layer 0.5 글로벌 트리거 로드
    global_trigger_map = load_global_trigger_map()
    
    # 3. Layer -2 매크로 레이더 로드
    macro_boost_map = load_macro_boost_map()
    
    # 4. 신호 통합
    master = aggregate_signals(inputs, global_trigger_map, macro_boost_map)
    if master.empty:
        logger.error("Aggregation failed. Exiting.")
        return False
    
    # 5. CSV 저장
    master.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    logger.info(f"✓ Output saved: {OUTPUT_CSV}")
    
    # 6. 요약 통계
    logger.info("\n" + "=" * 70)
    logger.info("📊 신호 통계")
    logger.info("=" * 70)
    signal_counts = master["signal"].value_counts()
    for sig, cnt in signal_counts.items():
        logger.info(f"{sig:15s}: {cnt:4d}종목")
    
    logger.info(f"\n평균 스코어: {master['score'].mean():.1f}pt")
    logger.info(f"최고 스코어: {master['score'].max():.1f}pt ({master.loc[master['score'].idxmax(), 'name']})")
    logger.info(f"최저 스코어: {master['score'].min():.1f}pt")
    
    logger.info("\n" + "=" * 70)
    logger.info("✅ Signal Aggregator v3.2 완료")
    logger.info("=" * 70)
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
