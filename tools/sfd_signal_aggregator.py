#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SFD Signal Aggregator v3.1
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
TECH_CSV = os.path.join(OUTPUTS_DIR, "sfd_technical_analysis_latest.csv")
NEWS_CSV = os.path.join(OUTPUTS_DIR, "sfd_news_sentiment_latest.csv")
INVESTOR_CSV = os.path.join(OUTPUTS_DIR, "sfd_investor_flow_latest.csv")
THEME_CSV = os.path.join(OUTPUTS_DIR, "sfd_theme_score_latest.csv")
FUND_CSV = os.path.join(OUTPUTS_DIR, "sfd_fundamental_watch_latest.csv")
RERATING_CSV = os.path.join(OUTPUTS_DIR, "sfd_rerating_watch_latest.csv")
SECTOR_CSV = os.path.join(OUTPUTS_DIR, "sfd_sector_injector_latest.csv")
GLOBAL_TRIGGER_CSV = os.path.join(OUTPUTS_DIR, "sfd_global_trigger_latest.csv")
MACRO_RADAR_CSV = os.path.join(OUTPUTS_DIR, "sfd_macro_radar_latest.csv")
OUTPUT_CSV = os.path.join(OUTPUTS_DIR, "sfd_master_signal_latest.csv")


logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(asctime)s - %(message)s=[]",
    handlers=[logging.FileHandler(os.path.join(OUTPUTS_DIR, "aggregator.log")),logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

THRESHOLD_RESERVE = 70
THRESHOLD_WATCH = 50

def load_all_inputs():
    logger.info("Loading input signals from Layer 1~2.6...")
    inputs = {}
    if os.path.exists(TECH_CSV):
        tech_df = pd.read_csv(TECH_CSV)
        tech_df.rename(columns={"score": "tech_score"}, inplace=True)
        inputs["tech"] = tech_df
        logger.info(f"✓ Technical: {len(tech_df)} rows")
    if os.path.exists(NEWS_CSV):
        news_df = pd.read_csv(NEWS_CSV)
        news_df.rename(columns={"sentiment_score": "news_score"}, inplace=True)
        inputs["news"] = news_df
        logger.info(f"✓ News: {len(news_df)} rows")
    if os.path.exists(INVESTOR_CSV):
        investor_df = pd.read_csv(INVESTOR_CSV)  
        inputs["investor"] = investor_df
        logger.info(f"✓ Investor: {len(investor_df)} rows")
    if os.path.exists(THEME_CSV):
        theme_df = pd.read_csv(THEME_CSV)
        theme_df.rename(columns={"theme_score": "theme_score"}, inplace=True)
        inputs["theme"] = theme_df
        logger.info(f"✓ Theme: {len(theme_df)} rows")
    if os.path.exists(FUND_CSV):
        fund_df = pd.read_csv(AUMDE_CSV)
        fund_df.rename(columns={"fund_score": "fund_score"}, inplace=True)
        inputs["fund"] = fund_df
        logger.info(f"✓ Fundamental: {len(fund_df)} rows")
    if os.path.exists(RERATING_CSV):
        rerating_df = pd.read_csv(RERATING_CSV)
        inputs["rerating"] = rerating_df
    if os.path.exists(SECTOR_CSV):
        sector_df = pd.read_csv(SECTOR_CSV)
        inputs["sector"] = sector_df
    return inputs

def load_global_trigger_map():
    if not os.path.exists(GLOBAL_TRIGGER_CSV):
        logger.warning(f"Global trigger CSV not found: {GLOBAL_TRIGGER_CSV}")
        return {}
    try:
        gt_df = pd.read_csv(GLOBAL_TRIGGER_CSV)
        gt_map = dict(zip(gt_df["stock_code"], gt_df["boost_score"]))
        logger.info(f"✓ Global Trigger Map: {len(gt_map)} tickers")
        return gt_map
    except Exception as e:
        logger.error(f"Failed to load global trigger: {e}")
        return {}

def load_macro_boost_map():
    if not os.path.exists(MACRO_RADAR_CSV):
        logger.warning(f"Macro radar CSV not found: {MACRO_RADAR_CSV}")
        return {}
    try:
        macro_df = pd.read_csv(MACRO_RADAR_CSV)  
        macro_map = dict(zip(macro_df["sector"], macro_df["macro_boost"]))
        logger.info(f"✓ Macro Boost Map: {len(macro_map)} sectors")
        return macro_map
    except Exception as e:
        logger.error(f"Failed to load macro radar: {e}")
        return {}

def aggregate_signals(inputs, global_trigger_map, macro_boost_map):
    logger.info("Aggregating all signals...")
    if "tech" not in inputs:
        logger.error("Technical analysis data required!")
        return pd.DataFrame()
    master = inputs["tech"].copy()
    code_col = next((c for c in master.columns if c in ["stock_code", "ticker"]), master.columns[0])
    master.rename(columns={code_col: "stock_code"}, inplace=True)
    if "tech_score" in master.columns:
        master.rename(columns={"tech_score": "score"}, inplace=True)
    if "score" not in master.columns:
        master["score"] = 0.0
    # 뉴스
    if "news" in inputs:
        news_agg = inputs["news"].groupby("stock_code")["news_score"].mean()
        master = master.merge(news_agg.to_frame().reset_index(),on="stock_code",how="left")
        master["news_score"] = master["news_score"].fillna(0)
        master["score"] += master["news_score"]
    else:
        master["news_score"] = 0.0
    # 투자자
    if "investor" in inputs:
        inv_df = inputs["investor"]
        inv_col = next((c for c in inv_df.columns if "investor" in c.lower() and "score" in c.lower()), None)
        if inv_col:
            inv_agg = inv_df.groupby("stock_code")[inv_col].mean()
            master = master.merge(inv_agg.to_frame().reset_index().rename(columns={inv_col: "investor_score"}),on="stock_code",how="left")
            master["investor_score"] = master["investor_score"].fillna(0)
            master["score"] += master["investor_score"]
        else:
            master["investor_score"] = 0.0
    else:
        master["investor_score"] = 0.0
    # 테마
    if "theme" in inputs:
        theme_agg = inputs["theme"].groupby("stock_code")["theme_score"].mean()
        master = master.merge(theme_agg.to_frame().reset_index(),on="stock_code",how="left")
        master["theme_score"] = master["theme_score"].fillna(0)
        master["score"] += master["theme_score"]
    else:
        master["theme_score"] = 0.0
    # 펀더멘탈
    if "fund" in inputs:
        fund_df = inputs["fund"]
        fund_col = next((c for c in fund_df.columns if "fund" in c.lower() and "score" in c.lower()), None)
        if fund_col:
            fund_agg = fund_df.groupby("stock_code")[fund_col].mean()
            master = master.merge(fund_agg.to_frame().reset_index().rename(columns={fund_col: "fund_score"}),on="stock_code",how="left")
            master["fund_score"] = master["fund_score"].fillna(0)
            master["score"] += master["fund_score"]
        else:
            master["fund_score"] = 0.0
    else:
        master["fund_score"] = 0.0
    # BM-3 이어스
    if "rerating" in inputs:
        rer_df = inputs["rerating"]
        if "bias_score" in rer_df.columns:
            bias_agg = rer_df.groupby("stock_code")["bias_score"].mean()
            master = master.merge(bias_agg.to_frame().reset_index().rename(columns={"bias_score": "bias"}),on="stock_code",how="left")
            master["bias"] = master["bias"].fillna(0)
            master["score"] += master["bias"]
        else:
            master["bias"] = 0.0
    else:
        master["bias"] = 0.0
    master["vol_surge"] = 0.0
    master["zone_pullback"] = 0.0
    # Layer 0.5
    master["global_boost"] = master["stock_code"].map(global_trigger_map).fillna(0)
    master["score"] += master["global_boost"]
    # Layer -2
    if "sector" in inputs:
        sector_map = dict(zip(inputs["sector"]["stock_code"], inputs["sector"]["sector"]))
        master["sector"] = master["stock_code"].map(sector_map)
        master["macro_boost"] = master["sector"].map(macro_boost_map).fillna(0)
        master["score"] += master["macro_boost"]
    else:
        master["macro_boost"] = 0.0
    def determine_signal(row):
        s = row["score"]
        if s >= THRESHOLD_RESERVE: return "RESERVE_BUY"
        elif s >= THRESHOLD_WATCH: return "WATCH_ONLY"
        else: return "HOLD"
    master["signal"] = master.apply(determine_signal, axis=1)
    col_order = ["stock_code","name","signal","score","tech_score","news_score","investor_score","theme_score","fund_score","bias","vol_surge","zone_pullback","global_boost","macro_boost"]
    col_order = [c for c in col_order if c in master.columns]
    master = master[col_order]
    master.sort_values("score", ascending=False, inplace=True)
    logger.info(f"✓ Aggregated {len(master)} signals")
    logger.info(f"  RESERVE_BUY: {len(master[moster['signal']=='RESERVE_BUY'])}")
    logger.info(f"  WATCH_ONLY: {len(master[master['signal']=='WATCH_ONLY'])}")
    return master

def main():
    logger.info("=" * 70)
    logger.info("SFD Signal Aggregator v3.1 실행 시작")
    logger.info("=" * 70)
    inputs = load_all_inputs()
    if not inputs:
        logger.error("No input signals. Exiting.")
        return False
    global_trigger_map = load_global_trigger_map()
    macro_boost_map = load_macro_boost_map()
    master = aggregate_signals(inputs, global_trigger_map, macro_boost_map)
    if master.empty:
        logger.error("Aggregation failed. Exiting.")
        return False
    master.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    logger.info(f"✓ Output: {OUTPUT_CSV}")
    signal_counts = master["signal"].value_counts()
    for sig, cnt in signal_counts.items():
        logger.info(f"{sig:15s}: {cnt:4d}종목")
    logger.info(f"\n✅ Signal Aggregator v3.1 완료")
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)