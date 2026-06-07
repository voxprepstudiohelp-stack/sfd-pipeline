#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sfd_bm9_us_sector_boost.py — BM-9 US Sector Dynamic Boost v1.0

기능:
  · sfd_macro_radar_latest.json 에서 OIL/VIX/KRW 읽기 (없으면 yfinance fallback)
  · yfinance 로 NASDAQ(^IXIC), SOX(^SOX) 직접 수집 (macro_radar 미포함 지표)
  · 아래 규칙으로 섹터-ticker 별 부스트 계산:
      [R1] NASDAQ +1% AND SOX +1%  → 반도체/Physical AI 섹터 +5pt
      [R2] NASDAQ +1% (SOX 무관)   → IT/소프트웨어 섹터 +3pt
      [R3] OIL +2%                 → 화학/에너지 섹터 +3pt
      [R4] VIX >= 20               → 전체 -3pt (리스크오프)
      [R5] KRW +1% 약세(USDKRW↑)  → 반도체/자동차/조선 섹터 +2pt
  · company_master sector_major 로 ticker 매핑
  · 데이터 없거나 활성 조건 없으면 빈 CSV 출력 후 exit 0 (continue-on-error 친화)

Inputs:
  outputs/latest/sfd_macro_radar_latest.json   (OIL/VIX/KRW)
  outputs/latest/sfd_master_signal_latest.csv  (ticker 목록)
  data/sfd_company_master_v1.4_sector_filled.csv

Outputs:
  outputs/latest/sfd_bm9_us_boost_latest.csv
    columns: ticker, us_boost_score, boost_reason, sector_major, as_of_date

Usage:
  py tools/sfd_bm9_us_sector_boost.py
  py tools/sfd_bm9_us_sector_boost.py --mock

Version: v1.0
Author:  Claude Sonnet 4.6 (2026-06-07)
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# ── 경로 설정 ─────────────────────────────────────────────────────────────
_HERE  = Path(__file__).resolve().parent
_BASE  = Path(os.environ.get("SFD_BASE_DIR", str(_HERE.parent)))
_LATEST = _BASE / "outputs" / "latest"
_DATA   = _BASE / "data"

MACRO_JSON     = _LATEST / "sfd_macro_radar_latest.json"
SIGNAL_CSV     = _LATEST / "sfd_master_signal_latest.csv"
COMPANY_MASTER = _DATA   / "sfd_company_master_v1.4_sector_filled.csv"
OUTPUT_CSV     = _LATEST / "sfd_bm9_us_boost_latest.csv"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

# ── 섹터 키워드 (sector_major 부분 일치) ─────────────────────────────────
# R1: NASDAQ+SOX 동시 상승 → 강한 반도체/AI 신호
R1_KEYWORDS = ["반도체", "Physical AI", "로봇", "자율주행"]
# R2: NASDAQ 단독 상승 → IT/소프트웨어 신호 (R1과 다른 섹터 대상)
R2_KEYWORDS = ["소프트웨어", "IT서비스", "IT솔루션", "게임", "엔터"]
# R3: OIL 급등 → 에너지/화학 섹터
R3_KEYWORDS = ["화학", "정밀화학", "에너지", "원유", "정유"]
# R5: KRW 약세 → 수출 대형주
R5_KEYWORDS = ["반도체", "자동차", "조선", "해양"]

# ── Mock 데이터 (--mock 오프라인 테스트) ─────────────────────────────────
MOCK_IND = {
    "NASDAQ": {"price": 19_800.0, "change_%": +1.5},
    "SOX":    {"price":  5_200.0, "change_%": +2.1},
    "OIL":    {"price":     78.5, "change_%": +2.3},
    "VIX":    {"price":     18.2, "change_%": -3.0},
    "KRW":    {"price":  1_380.0, "change_%": +1.2},
}


# ── 지표 수집 ─────────────────────────────────────────────────────────────
def _fetch_yf(key: str, symbol: str) -> dict:
    """yfinance로 전일 대비 변동률 수집. 실패 시 {}."""
    try:
        import yfinance as yf
        end   = datetime.today()
        start = end - timedelta(days=7)
        df = yf.download(symbol,
                         start=start.strftime("%Y-%m-%d"),
                         end=end.strftime("%Y-%m-%d"),
                         progress=False, auto_adjust=True)
        if df is None or len(df) < 2:
            log.warning(f"[BM-9] {key}({symbol}): 데이터 부족")
            return {}
        close = df["Close"] if not isinstance(df.columns, pd.MultiIndex) \
                else df["Close"][symbol] if symbol in df["Close"].columns \
                else df["Close"].iloc[:, 0]
        close = close.dropna()
        if len(close) < 2:
            return {}
        prev = float(close.iloc[-2])
        curr = float(close.iloc[-1])
        chg  = round((curr - prev) / prev * 100, 2) if prev != 0 else 0.0
        return {"price": round(curr, 4), "change_%": chg}
    except Exception as e:
        log.warning(f"[BM-9] {key}({symbol}) yfinance 실패: {e}")
        return {}


def load_indicators(mock: bool) -> dict:
    """
    OIL/VIX/KRW: macro_radar JSON 우선 → yfinance fallback
    NASDAQ/SOX:   항상 yfinance 직접 수집 (macro_radar 미포함)
    """
    if mock:
        log.info("[BM-9] --mock 모드")
        return MOCK_IND.copy()

    ind = {}

    # OIL / VIX / KRW: macro_radar JSON에서 읽기
    if MACRO_JSON.exists():
        try:
            with open(MACRO_JSON, encoding="utf-8") as f:
                meta = json.load(f)
            for key in ("OIL", "VIX", "KRW"):
                val = meta.get("macros", {}).get(key)
                if val and val.get("price"):
                    ind[key] = val
                    log.info(f"[BM-9] {key}: macro_radar JSON -> {val}")
        except Exception as e:
            log.warning(f"[BM-9] macro_radar JSON 읽기 실패: {e}")

    # OIL / VIX / KRW fallback
    FALLBACK_SYM = {"OIL": "CL=F", "VIX": "^VIX", "KRW": "USDKRW=X"}
    for key, sym in FALLBACK_SYM.items():
        if key not in ind:
            data = _fetch_yf(key, sym)
            if data:
                ind[key] = data
                log.info(f"[BM-9] {key}: yfinance fallback -> {data}")

    # NASDAQ / SOX: 항상 직접 수집
    for key, sym in [("NASDAQ", "^IXIC"), ("SOX", "^SOX")]:
        data = _fetch_yf(key, sym)
        if data:
            ind[key] = data
            log.info(f"[BM-9] {key}: yfinance -> {data}")
        else:
            log.warning(f"[BM-9] {key}: 데이터 수집 실패")

    return ind


# ── 조건 평가 ─────────────────────────────────────────────────────────────
def evaluate(ind: dict) -> dict:
    nasdaq_chg = ind.get("NASDAQ", {}).get("change_%", 0.0)
    sox_chg    = ind.get("SOX",    {}).get("change_%", 0.0)
    oil_chg    = ind.get("OIL",    {}).get("change_%", 0.0)
    vix_level  = ind.get("VIX",    {}).get("price",    0.0)
    krw_chg    = ind.get("KRW",    {}).get("change_%", 0.0)  # USDKRW +: 원화 약세

    conds = {
        "r1_nasdaq_sox": nasdaq_chg >= 1.0 and sox_chg >= 1.0,
        "r2_nasdaq":     nasdaq_chg >= 1.0,
        "r3_oil":        oil_chg    >= 2.0,
        "r4_vix":        vix_level  >= 20.0,
        "r5_krw_weak":   krw_chg    >= 1.0,
        # raw values for boost_reason 문자열 생성
        "_nasdaq": nasdaq_chg,
        "_sox":    sox_chg,
        "_oil":    oil_chg,
        "_vix":    vix_level,
        "_krw":    krw_chg,
    }

    parts = []
    if conds["r1_nasdaq_sox"]: parts.append(f"NASDAQ+SOX↑({nasdaq_chg:+.1f}%/{sox_chg:+.1f}%)")
    elif conds["r2_nasdaq"]:   parts.append(f"NASDAQ↑({nasdaq_chg:+.1f}%)")
    if conds["r3_oil"]:        parts.append(f"OIL↑({oil_chg:+.1f}%)")
    if conds["r4_vix"]:        parts.append(f"VIX≥20({vix_level:.1f})")
    if conds["r5_krw_weak"]:   parts.append(f"KRW↓({krw_chg:+.1f}%)")
    log.info(f"[BM-9] 활성 조건: {', '.join(parts) if parts else '없음'}")
    conds["_summary"] = ", ".join(parts) if parts else "neutral"
    return conds


# ── 섹터 키워드 매칭 ──────────────────────────────────────────────────────
def _match(sector_major: str, keywords: list) -> bool:
    s = str(sector_major)
    return any(kw in s for kw in keywords)


# ── ticker별 부스트 계산 ──────────────────────────────────────────────────
def compute_boost(sector_major: str, conds: dict) -> tuple:
    """Returns (score: int, reason: str)"""
    score   = 0
    reasons = []

    # [R1] NASDAQ AND SOX 동시 +1% → 반도체/AI +5pt
    if conds["r1_nasdaq_sox"] and _match(sector_major, R1_KEYWORDS):
        score += 5
        reasons.append(f"R1:NASDAQ+SOX+5")

    # [R2] NASDAQ +1% → IT/소프트웨어 +3pt (R1 대상 섹터와 별도 집합)
    if conds["r2_nasdaq"] and _match(sector_major, R2_KEYWORDS):
        score += 3
        reasons.append(f"R2:NASDAQ+3")

    # [R3] OIL +2% → 화학/에너지 +3pt
    if conds["r3_oil"] and _match(sector_major, R3_KEYWORDS):
        score += 3
        reasons.append(f"R3:OIL+3")

    # [R4] VIX >= 20 → 전체 -3pt
    if conds["r4_vix"]:
        score -= 3
        reasons.append(f"R4:VIX-3")

    # [R5] KRW +1% 약세 → 반도체/자동차/조선 +2pt
    if conds["r5_krw_weak"] and _match(sector_major, R5_KEYWORDS):
        score += 2
        reasons.append(f"R5:KRW+2")

    return score, (", ".join(reasons) if reasons else "")


# ── ticker-sector 매핑 로드 ───────────────────────────────────────────────
def load_sector_map() -> dict:
    """Returns {ticker(6자리): sector_major}"""
    sector_map = {}

    if COMPANY_MASTER.exists():
        try:
            df = pd.read_csv(COMPANY_MASTER, encoding="utf-8-sig",
                             dtype={"stock_code": str})
            df["stock_code"] = df["stock_code"].str.strip().str.zfill(6)
            sector_map = dict(zip(df["stock_code"],
                                  df["sector_major"].fillna("")))
            log.info(f"[BM-9] company_master: {len(sector_map)}종목 로드")
        except Exception as e:
            log.warning(f"[BM-9] company_master 읽기 실패: {e}")
    else:
        log.warning(f"[BM-9] company_master 없음: {COMPANY_MASTER}")

    # signal CSV로 누락 ticker 보강 (sector_major='')
    if SIGNAL_CSV.exists():
        try:
            sig = pd.read_csv(SIGNAL_CSV, dtype={"ticker": str})
            for t in sig["ticker"].astype(str).str.zfill(6).tolist():
                if t not in sector_map:
                    sector_map[t] = ""
            log.info(f"[BM-9] signal CSV 보강 후: {len(sector_map)}종목")
        except Exception as e:
            log.warning(f"[BM-9] signal CSV 읽기 실패: {e}")

    return sector_map


# ── 빈 CSV 저장 헬퍼 ──────────────────────────────────────────────────────
def save_empty(reason: str):
    _LATEST.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=["ticker", "us_boost_score", "boost_reason",
                           "sector_major", "as_of_date"]
                 ).to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    log.info(f"[BM-9] 빈 CSV 저장 ({reason}): {OUTPUT_CSV}")


# ── 메인 ─────────────────────────────────────────────────────────────────
def run(mock: bool = False):
    log.info("=== BM-9 US Sector Dynamic Boost v1.0 START ===")
    _LATEST.mkdir(parents=True, exist_ok=True)

    # 1. 지표 수집
    indicators = load_indicators(mock)
    if not indicators:
        save_empty("지표 없음")
        return

    # 2. 조건 평가
    conds = evaluate(indicators)
    any_active = any(conds[k] for k in
                     ("r1_nasdaq_sox", "r2_nasdaq", "r3_oil", "r4_vix", "r5_krw_weak"))
    if not any_active:
        save_empty("활성 조건 없음")
        return

    # 3. ticker-sector 로드
    sector_map = load_sector_map()
    if not sector_map:
        save_empty("ticker 없음")
        return

    # 4. 부스트 계산
    today = datetime.today().strftime("%Y-%m-%d")
    rows  = []
    for ticker, sector_major in sector_map.items():
        score, reason = compute_boost(sector_major, conds)
        if score != 0:
            rows.append({
                "ticker":         ticker,
                "us_boost_score": score,
                "boost_reason":   reason,
                "sector_major":   sector_major,
                "as_of_date":     today,
            })

    if not rows:
        save_empty("부스트 해당 종목 없음")
        return

    df = (pd.DataFrame(rows)
          .sort_values("us_boost_score", ascending=False)
          .reset_index(drop=True))
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    pos = len(df[df["us_boost_score"] > 0])
    neg = len(df[df["us_boost_score"] < 0])
    log.info(f"[BM-9] 저장: {OUTPUT_CSV} ({len(df)}rows | +{pos} / -{neg})")
    print(f"[BM-9] DONE | {conds['_summary']} | +{pos} / -{neg} tickers -> {OUTPUT_CSV}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BM-9 US Sector Dynamic Boost v1.0")
    parser.add_argument("--mock", action="store_true", help="Mock 데이터로 오프라인 테스트")
    args = parser.parse_args()
    run(mock=args.mock)
