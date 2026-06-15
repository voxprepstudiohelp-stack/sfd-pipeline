#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sfd_prism_engine.py v1.0
Layer 7.5 — PRISM Engine (Price · Volume · Investor 3-Component Scorer)

[설계 배경]
  aggregator v3.9: TECH_SCORE_CAP=60 적용으로 후행지표 지배 해소
  백테스트 DB contrib 분석 결과:
    p_contrib 54.7% (MA/가격 지배) → 가중치 하향 여지
    r_contrib 36.3% (거래량)       → 실전 유효성 높음
    i_contrib  9.0% (갭/수급)      → 상승 여지
  → 3컴포넌트를 독립 점수로 분리, 동적 가중치로 합산하는 PRISM 구조 도입

[PRISM 점수 구조]
  P_score (Price/Tech):  0~30pt — MA 배열, RSI, VP(BM-20), SR
  R_score (Volume/Risk): 0~30pt — vol_surge, vol_gap, std_bar, pullback
  I_score (Investor):    0~20pt — 외국인/기관 수급, news, DART
  ─────────────────────────────────────────
  PRISM_total = P×W_p + R×W_r + I×W_i  (max 80pt 기준)

[동적 가중치 — contrib 기반 자동 조정]
  기본값: W_p=0.375, W_r=0.375, W_i=0.25
  DB contrib 평균이 기본값과 10% 이상 차이 시 자동 재산출
  → 백테스트 적중률 개선 방향으로 점진적 수렴

[입력]
  sfd_technical_latest.csv   (L2 — tech/VP/SR/vol 컴포넌트)
  sfd_investor_flow_latest.csv (L2 — 수급)
  sfd_news_score_latest.csv  (L2 — 뉴스)
  backtest_historical.db     (contrib 가중치 자동산출용, 선택)

[출력]
  outputs/latest/sfd_prism_latest.csv
    ticker, p_score, r_score, i_score, prism_total,
    w_p, w_r, w_i, prism_grade, prism_label

실행: python sfd_prism_engine.py
"""

import os
import sys
import json
import sqlite3
import logging
from datetime import datetime

import pandas as pd
import numpy as np

# ── 경로 설정 ─────────────────────────────────────────────
_env_base = os.environ.get("SFD_BASE_DIR", "")
if _env_base and os.path.isdir(_env_base):
    BASE_DIR = _env_base
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LATEST_DIR = os.path.join(BASE_DIR, "outputs", "latest")
os.makedirs(LATEST_DIR, exist_ok=True)

TECH_CSV      = os.path.join(LATEST_DIR, "sfd_technical_latest.csv")
INVESTOR_CSV  = os.path.join(LATEST_DIR, "sfd_investor_flow_latest.csv")
NEWS_CSV      = os.path.join(LATEST_DIR, "sfd_news_score_latest.csv")
DB_PATH       = os.path.join(BASE_DIR, "outputs", "backtest_historical.db")
OUTPUT_CSV    = os.path.join(LATEST_DIR, "sfd_prism_latest.csv")
LOG_PATH      = os.path.join(LATEST_DIR, "sfd_prism_engine.log")
WEIGHT_JSON   = os.path.join(LATEST_DIR, "prism_weights.json")

logging.basicConfig(
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

# ── PRISM 파라미터 ────────────────────────────────────────
# 기본 가중치 (p:r:i = 3:3:2 비율 → 합계 1.0)
DEFAULT_W_P = 0.375
DEFAULT_W_R = 0.375
DEFAULT_W_I = 0.250

# P_score 서브 가중치 (합계 30pt)
P_MAX      = 30.0
P_MA_PT    = 10   # MA 배열 (3ma_bull=10, 2ma=6, 1ma=3)
P_RSI_PT   = 5    # RSI 존 (30이하=5, 50이하=3, 70이하=1)
P_VP_PT    = 10   # Volume Profile (BM-20 vp_score 0~20 → 0~10pt 정규화)
P_SR_PT    = 5    # Support/Resistance (sr_score 0~10 → 0~5pt 정규화)

# R_score 서브 가중치 (합계 30pt)
R_MAX      = 30.0
R_VOLSURGE = 10   # vol_surge_score (0~10pt)
R_VOLGAP   = 8    # vol_gap_score (0~15 → 0~8pt 정규화)
R_STDBAR   = 7    # std_bar_score (0~10 → 0~7pt 정규화)
R_PULLBACK = 5    # pullback_zone_score (0~15 → 0~5pt 정규화)

# I_score 서브 가중치 (합계 20pt)
I_MAX      = 20.0
I_FOREIGN  = 7    # 외국인 순매수 방향
I_INST     = 6    # 기관 순매수 방향
I_NEWS     = 5    # news_score (0~30 → 0~5pt 정규화)
I_DART     = 2    # DART 이벤트 보너스 (추후 연동)

# PRISM 등급 기준 (prism_total 0~80pt)
GRADE_A = 48   # 상위 신호
GRADE_B = 43   # 중위 신호
GRADE_C = 35   # 관망


# ── 동적 가중치 로드 / 산출 ───────────────────────────────
def load_dynamic_weights() -> tuple:
    """
    1. prism_weights.json 존재 시 → 캐시 로드
    2. backtest_historical.db contrib 평균으로 재산출
    3. 기본값 fallback
    반환: (w_p, w_r, w_i)
    """
    # 캐시 우선
    if os.path.exists(WEIGHT_JSON):
        try:
            with open(WEIGHT_JSON, encoding="utf-8") as f:
                d = json.load(f)
            w_p = float(d.get("w_p", DEFAULT_W_P))
            w_r = float(d.get("w_r", DEFAULT_W_R))
            w_i = float(d.get("w_i", DEFAULT_W_I))
            logging.info(f"[PRISM] weights loaded from cache: p={w_p:.3f} r={w_r:.3f} i={w_i:.3f}")
            return w_p, w_r, w_i
        except Exception:
            pass

    # DB contrib 기반 산출
    if os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH)
            df = pd.read_sql("""
                SELECT AVG(p_contrib) AS avg_p,
                       AVG(r_contrib) AS avg_r,
                       AVG(i_contrib) AS avg_i
                FROM backtest_signals
                WHERE p_contrib IS NOT NULL
                  AND total_score > 0
            """, conn)
            conn.close()

            avg_p = float(df["avg_p"].iloc[0] or 54.7)
            avg_r = float(df["avg_r"].iloc[0] or 36.3)
            avg_i = float(df["avg_i"].iloc[0] or 9.0)
            total = avg_p + avg_r + avg_i

            # contrib 비율을 [0.2, 0.6] 구간으로 클리핑 (극단값 방지)
            w_p = max(0.2, min(0.6, avg_p / total))
            w_r = max(0.2, min(0.6, avg_r / total))
            w_i = 1.0 - w_p - w_r
            w_i = max(0.1, min(0.4, w_i))

            # 합계 정규화
            s = w_p + w_r + w_i
            w_p, w_r, w_i = w_p/s, w_r/s, w_i/s

            # 캐시 저장
            with open(WEIGHT_JSON, "w", encoding="utf-8") as f:
                json.dump({
                    "w_p": round(w_p, 4),
                    "w_r": round(w_r, 4),
                    "w_i": round(w_i, 4),
                    "source": "backtest_db_contrib",
                    "avg_p_contrib": round(avg_p, 2),
                    "avg_r_contrib": round(avg_r, 2),
                    "avg_i_contrib": round(avg_i, 2),
                    "generated_at": datetime.now().isoformat(),
                }, f, ensure_ascii=False, indent=2)

            logging.info(
                f"[PRISM] weights from DB contrib: "
                f"p={w_p:.3f}({avg_p:.1f}%) r={w_r:.3f}({avg_r:.1f}%) i={w_i:.3f}({avg_i:.1f}%)"
            )
            return w_p, w_r, w_i

        except Exception as e:
            logging.warning(f"[PRISM] DB contrib 로드 실패: {e} → 기본값 사용")

    logging.info(f"[PRISM] 기본 가중치 사용: p={DEFAULT_W_P} r={DEFAULT_W_R} i={DEFAULT_W_I}")
    return DEFAULT_W_P, DEFAULT_W_R, DEFAULT_W_I


# ── 데이터 로더 ───────────────────────────────────────────
def load_tech() -> pd.DataFrame:
    if not os.path.exists(TECH_CSV):
        logging.warning(f"[PRISM] TECH_CSV 없음: {TECH_CSV}")
        return pd.DataFrame()
    df = pd.read_csv(TECH_CSV, encoding="utf-8-sig", dtype={"ticker": str})
    df["ticker"] = df["ticker"].str.strip().str.zfill(6)
    logging.info(f"[PRISM] tech loaded: {len(df)}rows")
    return df

def load_investor() -> pd.DataFrame:
    if not os.path.exists(INVESTOR_CSV):
        logging.warning(f"[PRISM] INVESTOR_CSV 없음")
        return pd.DataFrame()
    df = pd.read_csv(INVESTOR_CSV, encoding="utf-8-sig", dtype=str)
    # ticker/stock_code 컬럼 자동 감지
    tcol = next((c for c in ["ticker", "stock_code"] if c in df.columns), None)
    if tcol and tcol != "ticker":
        df = df.rename(columns={tcol: "ticker"})
    if "ticker" in df.columns:
        df["ticker"] = df["ticker"].str.strip().str.zfill(6)
    logging.info(f"[PRISM] investor loaded: {len(df)}rows")
    return df

def load_news() -> dict:
    if not os.path.exists(NEWS_CSV):
        return {}
    try:
        df = pd.read_csv(NEWS_CSV, encoding="utf-8-sig", dtype={"ticker": str})
        if "ticker" not in df.columns or "news_score" not in df.columns:
            return {}
        return dict(zip(
            df["ticker"].str.strip().str.zfill(6),
            pd.to_numeric(df["news_score"], errors="coerce").fillna(0)
        ))
    except Exception as e:
        logging.warning(f"[PRISM] news 로드 실패: {e}")
        return {}


# ── P_score 계산 ──────────────────────────────────────────
def calc_p_score(row: pd.Series) -> float:
    """
    P_score = MA점수 + RSI점수 + VP점수 + SR점수 (max 30pt)
    """
    score = 0.0

    # MA 배열 (ma_label 또는 개별 컬럼)
    ma_label = str(row.get("ma_label", "") or "")
    if "3ma_bull" in ma_label or "3MA" in ma_label:
        score += P_MA_PT          # 10pt
    elif "2ma_bull" in ma_label or "2MA" in ma_label:
        score += P_MA_PT * 0.6    # 6pt
    elif "1ma_bull" in ma_label or "1MA" in ma_label:
        score += P_MA_PT * 0.3    # 3pt

    # RSI 존
    rsi = float(row.get("rsi", 50) or 50)
    if rsi <= 30:
        score += P_RSI_PT         # 5pt (과매도 반등 기대)
    elif rsi <= 50:
        score += P_RSI_PT * 0.6   # 3pt
    elif rsi <= 70:
        score += P_RSI_PT * 0.2   # 1pt

    # VP (BM-20 vp_score 0~20 → 0~10pt)
    vp_score = float(row.get("vp_score", 0) or 0)
    score += min(vp_score / 20.0 * P_VP_PT, P_VP_PT)

    # SR (sr_score 0~10 → 0~5pt)
    sr_score = float(row.get("sr_score", 0) or 0)
    score += min(sr_score / 10.0 * P_SR_PT, P_SR_PT)

    return round(min(score, P_MAX), 2)


# ── R_score 계산 ──────────────────────────────────────────
def calc_r_score(row: pd.Series) -> float:
    """
    R_score = vol_surge + vol_gap + std_bar + pullback (max 30pt)
    """
    score = 0.0

    # vol_surge (0~10pt 직접 사용)
    vs = float(row.get("vol_surge_score", 0) or 0)
    score += min(vs, R_VOLSURGE)

    # vol_gap (0~15 → 0~8pt)
    vg = float(row.get("vol_gap_score", 0) or 0)
    score += min(vg / 15.0 * R_VOLGAP, R_VOLGAP)

    # std_bar (0~10 → 0~7pt)
    sb = float(row.get("std_bar_score", 0) or 0)
    score += min(sb / 10.0 * R_STDBAR, R_STDBAR)

    # pullback (0~15 → 0~5pt)
    pb = float(row.get("pullback_zone_score", 0) or 0)
    score += min(pb / 15.0 * R_PULLBACK, R_PULLBACK)

    return round(min(score, R_MAX), 2)


# ── I_score 계산 ──────────────────────────────────────────
def calc_i_score(ticker: str, inv_df: pd.DataFrame,
                 news_map: dict) -> float:
    """
    I_score = 외국인 + 기관 + 뉴스 + DART (max 20pt)
    """
    score = 0.0

    # 외국인/기관 수급
    if not inv_df.empty and "ticker" in inv_df.columns:
        row = inv_df[inv_df["ticker"] == ticker]
        if not row.empty:
            try:
                status = str(row.iloc[0].get("data_status", "OK")).upper()
                if status not in ("ZERO", "FAIL"):
                    f_buy = float(row.iloc[0].get("foreign_net_buy", 0) or 0)
                    i_buy = float(row.iloc[0].get("institution_net_buy", 0) or 0)
                    # 방향성 점수 (순매수 규모 비례, 최대 I_FOREIGN/I_INST)
                    score += I_FOREIGN if f_buy > 0 else (I_FOREIGN * 0.3 if f_buy == 0 else 0)
                    score += I_INST    if i_buy > 0 else (I_INST    * 0.3 if i_buy == 0 else 0)
            except Exception:
                pass

    # 뉴스 (0~30 → 0~5pt)
    news = float(news_map.get(ticker, 0))
    score += min(news / 30.0 * I_NEWS, I_NEWS)

    # DART 보너스 (추후 sfd_dart_event.py 연동 예정 — 현재 0pt)
    # dart_score = dart_map.get(ticker, 0)
    # score += min(dart_score, I_DART)

    return round(min(score, I_MAX), 2)


# ── PRISM 등급 분류 ───────────────────────────────────────
def classify_prism(total: float) -> tuple:
    """반환: (grade, label)"""
    if total >= GRADE_A:
        return "A", "PRISM_STRONG"
    elif total >= GRADE_B:
        return "B", "PRISM_WATCH"
    elif total >= GRADE_C:
        return "C", "PRISM_HOLD"
    else:
        return "D", "PRISM_WEAK"


# ── MAIN ──────────────────────────────────────────────────
def main():
    logging.info("=== sfd_prism_engine v1.0 START ===")
    logging.info(f"BASE_DIR: {BASE_DIR}")

    # 가중치 로드
    w_p, w_r, w_i = load_dynamic_weights()
    logging.info(f"[PRISM] 적용 가중치: P={w_p:.3f} R={w_r:.3f} I={w_i:.3f}")

    # 데이터 로드
    tech_df   = load_tech()
    inv_df    = load_investor()
    news_map  = load_news()

    if tech_df.empty:
        logging.error("[PRISM] tech_df 없음 — 종료")
        print("[ERROR] sfd_technical_latest.csv 없음 — 파이프라인 L2 먼저 실행 필요")
        return

    results = []
    for _, row in tech_df.iterrows():
        ticker = str(row.get("ticker", "")).strip().zfill(6)
        if not ticker or ticker == "000000":
            continue

        p = calc_p_score(row)
        r = calc_r_score(row)
        i = calc_i_score(ticker, inv_df, news_map)

        # PRISM 합산 (80pt 기준 정규화)
        prism_raw   = p * w_p + r * w_r + i * w_i
        # 80pt 스케일로 변환 (P_MAX*w_p + R_MAX*w_r + I_MAX*w_i = max)
        prism_max   = P_MAX * w_p + R_MAX * w_r + I_MAX * w_i
        prism_total = round(prism_raw / prism_max * 80, 2) if prism_max > 0 else 0.0

        grade, label = classify_prism(prism_total)

        results.append({
            "ticker":       ticker,
            "name":         str(row.get("name", "") or ""),
            "p_score":      p,
            "r_score":      r,
            "i_score":      i,
            "prism_total":  prism_total,
            "w_p":          round(w_p, 4),
            "w_r":          round(w_r, 4),
            "w_i":          round(w_i, 4),
            "prism_grade":  grade,
            "prism_label":  label,
            "fetch_date":   datetime.now().strftime("%Y%m%d"),
            "fetch_time":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

    df_out = (pd.DataFrame(results)
              .sort_values("prism_total", ascending=False)
              .reset_index(drop=True))

    df_out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    # 등급별 집계
    grade_cnt = df_out["prism_grade"].value_counts().to_dict()
    total_cnt = len(df_out)
    a_cnt     = grade_cnt.get("A", 0)
    b_cnt     = grade_cnt.get("B", 0)
    c_cnt     = grade_cnt.get("C", 0)
    d_cnt     = grade_cnt.get("D", 0)

    # TOP5 출력
    top5 = df_out.head(5)[["ticker", "name", "prism_total", "p_score", "r_score", "i_score", "prism_grade"]]

    logging.info(
        f"DONE | total={total_cnt} A={a_cnt} B={b_cnt} C={c_cnt} D={d_cnt} | "
        f"weights: P={w_p:.3f} R={w_r:.3f} I={w_i:.3f}"
    )
    print("=" * 60)
    print(f" sfd_prism_engine v1.0 완료")
    print(f" 총 {total_cnt}종목 | A={a_cnt} B={b_cnt} C={c_cnt} D={d_cnt}")
    print(f" 가중치: P={w_p:.3f} R={w_r:.3f} I={w_i:.3f}")
    print(f"\n[TOP5 PRISM 신호]")
    print(top5.to_string(index=False))
    print(f"\n출력: {OUTPUT_CSV}")
    print("=" * 60)


if __name__ == "__main__":
    main()
