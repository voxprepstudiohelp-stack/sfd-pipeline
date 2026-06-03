#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SFD Signal Aggregator v3.4
==========================
v3.3 → v3.4 패치:
  - tech_total_score 컬럼명 자동탐지 추가 (tech_total_score / tech_score / score 순)
v3.2 → v3.3 패치:
  - tech_score rename 버그 수정: score 컬럼 별도 초기화 후 tech_score 누적
  - global_trigger 컬럼명 자동 탐지 (ticker / stock_code 모두 허용)
  - tech_score 컬럼 출력에 보존

스코어 아키텍처 (max 225pt):
  기술(93) + 뉴스(30) + 투자자(20) + 테마(10) + 펀더멘탈(15)
  + 바이어스(±5)[BM-3] + 볼륨급증(10)[BM-10] + 존풀백(15)[BM-12]
  + 글로벌(±20)[L0.5] + 매크로(±15)[L-2]
"""


import os
import sys
import logging
import pandas as pd
import numpy as np


# ===== CONFIG =====
_env_base = os.environ.get("SFD_BASE_DIR", "")
BASE_DIR = _env_base if _env_base else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs", "latest")
os.makedirs(OUTPUTS_DIR, exist_ok=True)


TECH_CSV       = os.path.join(OUTPUTS_DIR, "sfd_technical_latest.csv")
NEWS_CSV       = os.path.join(OUTPUTS_DIR, "sfd_news_sentiment_latest.csv")
INVESTOR_CSV   = os.path.join(OUTPUTS_DIR, "sfd_investor_flow_latest.csv")
THEME_CSV      = os.path.join(OUTPUTS_DIR, "sfd_theme_score_latest.csv")
FUND_CSV       = os.path.join(OUTPUTS_DIR, "sfd_fundamental_watch_latest.csv")
RERATING_CSV   = os.path.join(OUTPUTS_DIR, "sfd_rerating_watch_latest.csv")
SECTOR_CSV     = os.path.join(OUTPUTS_DIR, "sfd_sector_injector_latest.csv")
GLOBAL_TRIGGER_CSV = os.path.join(OUTPUTS_DIR, "sfd_global_trigger_latest.csv")
MACRO_RADAR_CSV    = os.path.join(OUTPUTS_DIR, "sfd_macro_radar_latest.csv")
OUTPUT_CSV     = os.path.join(OUTPUTS_DIR, "sfd_master_signal_latest.csv")


logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(asctime)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(OUTPUTS_DIR, "aggregator.log")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


THRESHOLD_RESERVE = 55
THRESHOLD_WATCH   = 40


# ===== HELPERS =====
def detect_code_col(df):
    """stock_code / ticker 자동 탐지"""
    for c in ["stock_code", "ticker"]:
        if c in df.columns:
            return c
    return df.columns[0]


# ===== LOAD INPUTS =====
def load_all_inputs():
    logger.info("Loading input signals from Layer 1~2.6...")
    inputs = {}

    if os.path.exists(TECH_CSV):
        tech_df = pd.read_csv(TECH_CSV)
        # [FIX v3.4] 컬럼명 자동탐지: tech_total_score / tech_score / score 순으로 → tech_score로 표준화
        _tscore_col = next(
            (c for c in ["tech_total_score", "tech_score", "score"] if c in tech_df.columns),
            None
        )
        if _tscore_col and _tscore_col != "tech_score":
            tech_df.rename(columns={_tscore_col: "tech_score"}, inplace=True)
            logger.info(f"tech score 컬럼 표준화: '{_tscore_col}' → 'tech_score'")
        code_col = detect_code_col(tech_df)
        if code_col != "stock_code":
            tech_df.rename(columns={code_col: "stock_code"}, inplace=True)
        inputs["tech"] = tech_df
        logger.info(f"✓ Technical: {len(tech_df)} rows")
    
    if os.path.exists(NEWS_CSV):
        news_df = pd.read_csv(NEWS_CSV)
        code_col = detect_code_col(news_df)
        if code_col != "stock_code":
            news_df.rename(columns={code_col: "stock_code"}, inplace=True)
        if "sentiment_score" in news_df.columns:
            news_df.rename(columns={"sentiment_score": "news_score"}, inplace=True)
        inputs["news"] = news_df
        logger.info(f"✓ News: {len(news_df)} rows")

    if os.path.exists(INVESTOR_CSV):
        investor_df = pd.read_csv(INVESTOR_CSV)
        code_col = detect_code_col(investor_df)
        if code_col != "stock_code":
            investor_df.rename(columns={code_col: "stock_code"}, inplace=True)
        inputs["investor"] = investor_df
        logger.info(f"✓ Investor: {len(investor_df)} rows")

    if os.path.exists(THEME_CSV):
        theme_df = pd.read_csv(THEME_CSV)
        code_col = detect_code_col(theme_df)
        if code_col != "stock_code":
            theme_df.rename(columns={code_col: "stock_code"}, inplace=True)
        inputs["theme"] = theme_df
        logger.info(f"✓ Theme: {len(theme_df)} rows")

    if os.path.exists(FUND_CSV):
        fund_df = pd.read_csv(FUND_CSV)
        code_col = detect_code_col(fund_df)
        if code_col != "stock_code":
            fund_df.rename(columns={code_col: "stock_code"}, inplace=True)
        if "fund_score" not in fund_df.columns:
            # 숫자 컬럼 중 첫번째를 fund_score로
            num_cols = fund_df.select_dtypes(include="number").columns.tolist()
            if num_cols:
                fund_df.rename(columns={num_cols[0]: "fund_score"}, inplace=True)
        inputs["fund"] = fund_df
        logger.info(f"✓ Fundamental: {len(fund_df)} rows")

    if os.path.exists(RERATING_CSV):
        rerating_df = pd.read_csv(RERATING_CSV)
        code_col = detect_code_col(rerating_df)
        if code_col != "stock_code":
            rerating_df.rename(columns={code_col: "stock_code"}, inplace=True)
        inputs["rerating"] = rerating_df
        logger.info(f"✓ Rerating: {len(rerating_df)} rows")

    if os.path.exists(SECTOR_CSV):
        sector_df = pd.read_csv(SECTOR_CSV)
        code_col = detect_code_col(sector_df)
        if code_col != "stock_code":
            sector_df.rename(columns={code_col: "stock_code"}, inplace=True)
        inputs["sector"] = sector_df
        logger.info(f"✓ Sector: {len(sector_df)} rows")

    return inputs


# ===== LOAD LAYER 0.5 =====
def load_global_trigger_map():
    if not os.path.exists(GLOBAL_TRIGGER_CSV):
        logger.warning(f"Global trigger CSV not found: {GLOBAL_TRIGGER_CSV}")
        return {}
    try:
        gt_df = pd.read_csv(GLOBAL_TRIGGER_CSV)
        # [FIX v3.3] stock_code / ticker 자동 탐지
        code_col = detect_code_col(gt_df)
        boost_col = next((c for c in ["boost_score", "global_boost", "boost"] if c in gt_df.columns), None)
        if boost_col is None:
            logger.error(f"Failed to load global trigger: boost 컬럼 없음. columns={list(gt_df.columns)}")
            return {}
        gt_map = dict(zip(gt_df[code_col], gt_df[boost_col]))
        logger.info(f"✓ Global Trigger Map: {len(gt_map)} tickers")
        return gt_map
    except Exception as e:
        logger.error(f"Failed to load global trigger: {e}")
        return {}


# ===== LOAD LAYER -2 =====
def load_macro_boost_map():
    if not os.path.exists(MACRO_RADAR_CSV):
        logger.warning(f"Macro radar CSV not found: {MACRO_RADAR_CSV}")
        return {}
    try:
        macro_df = pd.read_csv(MACRO_RADAR_CSV)
        sector_col = next((c for c in ["sector", "sector_name"] if c in macro_df.columns), None)
        boost_col  = next((c for c in ["macro_boost", "boost_score", "boost"] if c in macro_df.columns), None)
        if not sector_col or not boost_col:
            logger.error(f"Macro radar 컬럼 불명: columns={list(macro_df.columns)}")
            return {}
        macro_map = dict(zip(macro_df[sector_col], macro_df[boost_col]))
        logger.info(f"✓ Macro Boost Map: {len(macro_map)} sectors")
        return macro_map
    except Exception as e:
        logger.error(f"Failed to load macro radar: {e}")
        return {}


# ===== AGGREGATION =====
def aggregate_signals(inputs, global_trigger_map, macro_boost_map):
    logger.info("Aggregating all signals...")

    if "tech" not in inputs:
        logger.error("Technical analysis data required!")
        return pd.DataFrame()

    master = inputs["tech"].copy()

    # [FIX v3.3] tech_score를 score에 복사 (rename 아님 — 컬럼 보존)
    if "tech_score" in master.columns:
        master["score"] = master["tech_score"].fillna(0).astype(float)
    else:
        master["score"] = 0.0
        logger.warning("tech_score 컬럼 없음 — score=0 초기화")

    # 뉴스 (30pt)
    if "news" in inputs and "news_score" in inputs["news"].columns:
        news_agg = inputs["news"].groupby("stock_code")["news_score"].mean().reset_index()
        master = master.merge(news_agg, on="stock_code", how="left")
        master["news_score"] = master["news_score"].fillna(0)
        master["score"] += master["news_score"]
    else:
        master["news_score"] = 0.0

    # 투자자 (20pt)
    if "investor" in inputs and "investor_score" in inputs["investor"].columns:
        inv_agg = inputs["investor"].groupby("stock_code")["investor_score"].mean().reset_index()
        master = master.merge(inv_agg, on="stock_code", how="left")
        master["investor_score"] = master["investor_score"].fillna(0)
        master["score"] += master["investor_score"]
    else:
        master["investor_score"] = 0.0

    # 테마 (10pt)
    if "theme" in inputs and "theme_score" in inputs["theme"].columns:
        theme_agg = inputs["theme"].groupby("stock_code")["theme_score"].mean().reset_index()
        master = master.merge(theme_agg, on="stock_code", how="left")
        master["theme_score"] = master["theme_score"].fillna(0)
        master["score"] += master["theme_score"]
    else:
        master["theme_score"] = 0.0

    # 펀더멘탈 (15pt)
    if "fund" in inputs and "fund_score" in inputs["fund"].columns:
        fund_agg = inputs["fund"].groupby("stock_code")["fund_score"].mean().reset_index()
        master = master.merge(fund_agg, on="stock_code", how="left")
        master["fund_score"] = master["fund_score"].fillna(0)
        master["score"] += master["fund_score"]
    else:
        master["fund_score"] = 0.0

    # BM-3 바이어스 (±5pt)
    if "rerating" in inputs and "bias_score" in inputs["rerating"].columns:
        bias_agg = inputs["rerating"].groupby("stock_code")["bias_score"].mean().reset_index()
        bias_agg.rename(columns={"bias_score": "bias"}, inplace=True)
        master = master.merge(bias_agg, on="stock_code", how="left")
        master["bias"] = master["bias"].fillna(0)
        master["score"] += master["bias"]
    else:
        master["bias"] = 0.0

    master["vol_surge"]    = 0.0
    master["zone_pullback"] = 0.0

    # Layer 0.5 글로벌 부스트 (±20pt)
    master["global_boost"] = master["stock_code"].map(global_trigger_map).fillna(0)
    master["score"] += master["global_boost"]

    # Layer -2 매크로 부스트 (±15pt)
    if "sector" in inputs and macro_boost_map:
        sector_map = dict(zip(inputs["sector"]["stock_code"], inputs["sector"].get("sector", inputs["sector"].iloc[:, 1])))
        master["sector"] = master["stock_code"].map(sector_map)
        master["macro_boost"] = master["sector"].map(macro_boost_map).fillna(0)
        master["score"] += master["macro_boost"]
    else:
        master["macro_boost"] = 0.0

    # 신호 판정
    def determine_signal(score):
        if score >= THRESHOLD_RESERVE:
            return "RESERVE_BUY"
        elif score >= THRESHOLD_WATCH:
            return "WATCH_ONLY"
        return "HOLD"

    master["signal"] = master["score"].apply(determine_signal)

    # 컬럼 정렬
    col_order = [
        "stock_code", "name", "signal", "score",
        "tech_score", "news_score", "investor_score", "theme_score", "fund_score",
        "bias", "vol_surge", "zone_pullback", "global_boost", "macro_boost",
    ]
    col_order = [c for c in col_order if c in master.columns]
    master = master[col_order].sort_values("score", ascending=False)

    logger.info(f"✓ Aggregated {len(master)} signals")
    logger.info(f"  RESERVE_BUY: {len(master[master['signal']=='RESERVE_BUY'])}")
    logger.info(f"  WATCH_ONLY:  {len(master[master['signal']=='WATCH_ONLY'])}")

    return master


# ===== MAIN =====
def main():
    logger.info("=" * 70)
    logger.info("SFD Signal Aggregator v3.4 - 실행 시작")
    logger.info("=" * 70)

    inputs = load_all_inputs()
    if not inputs:
        logger.error("No input signals loaded. Exiting.")
        return False

    global_trigger_map = load_global_trigger_map()
    macro_boost_map    = load_macro_boost_map()

    master = aggregate_signals(inputs, global_trigger_map, macro_boost_map)
    if master.empty:
        logger.error("Aggregation failed. Exiting.")
        return False

    master.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    logger.info(f"✓ Output saved: {OUTPUT_CSV}")

    logger.info("\n" + "=" * 70)
    logger.info("📊 신호 통계")
    logger.info("=" * 70)
    for sig, cnt in master["signal"].value_counts().items():
        logger.info(f"{sig:15s}: {cnt:4d}종목")

    name_col = "name" if "name" in master.columns else None
    best_name = master.loc[master["score"].idxmax(), name_col] if name_col else "N/A"
    logger.info(f"\n평균 스코어: {master['score'].mean():.1f}pt")
    logger.info(f"최고 스코어: {master['score'].max():.1f}pt ({best_name})")
    logger.info(f"최저 스코어: {master['score'].min():.1f}pt")

    logger.info("\n" + "=" * 70)
    logger.info("✅ Signal Aggregator v3.4 완료")
    logger.info("=" * 70)

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
