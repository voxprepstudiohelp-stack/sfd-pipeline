"""
sfd_earnings_surprise.py
BM-16: Earnings Surprise Detector
SFD Pipeline - fundamental score booster

Score range: -3 ~ +5pt
Integrates into sfd_signal_aggregator via fund_score or standalone overlay.

Scoring:
  surprise >  20%  → +5pt  (대형 서프라이즈)
  surprise  10~20% → +3pt  (중형 서프라이즈)
  surprise   5~10% → +1pt  (소형 서프라이즈)
  surprise  -5~ 5% →  0pt  (컨센서스 부합)
  surprise <  -5%  → -3pt  (어닝 쇼크)

Author: Claude (Architect)
Version: 1.0
Date: 2026-06-09
"""

import os
import logging
import urllib.request
import urllib.parse
import json
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DART_API_KEY = os.environ.get("DART_API_KEY", "")
DART_BASE    = "https://opendart.fss.or.kr/api"

# 서프라이즈 강도 → 점수 테이블
_SCORE_TABLE = [
    ( 20.0,  float("inf"),  5.0, "대형 서프라이즈(>20%)"),
    ( 10.0,  20.0,          3.0, "중형 서프라이즈(10~20%)"),
    (  5.0,  10.0,          1.0, "소형 서프라이즈(5~10%)"),
    ( -5.0,   5.0,          0.0, "컨센서스 부합"),
    (float("-inf"), -5.0,  -3.0, "어닝 쇼크(<-5%)"),
]


# ─────────────────────────────────────────────
# DART helpers
# ─────────────────────────────────────────────
def _dart_get(endpoint: str, params: dict) -> dict | None:
    """DART OpenAPI GET 요청. 실패 시 None 반환."""
    if not DART_API_KEY:
        logger.warning("BM-16: DART_API_KEY 미설정")
        return None
    params["crtfc_key"] = DART_API_KEY
    url = f"{DART_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "sfd-pipeline/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") != "000":
            logger.debug("BM-16: DART status=%s msg=%s", data.get("status"), data.get("message"))
            return None
        return data
    except Exception as e:
        logger.warning("BM-16: DART request failed (%s): %s", endpoint, e)
        return None


def _get_corp_code(stock_code: str) -> str | None:
    """종목코드 → DART corp_code 변환."""
    data = _dart_get("company.json", {"stock_code": stock_code.zfill(6)})
    if data:
        return data.get("corp_code")
    return None


def _fetch_recent_financials(corp_code: str) -> list[dict]:
    """
    최근 4분기 재무 데이터 조회.
    fnlttSinglAcntAll: 단일회사 전체 재무제표
    """
    year  = datetime.now().year
    results = []
    for y in [year, year - 1]:
        for reprt in ["11014", "11012", "11013", "11011"]:  # Q4, Q2, Q3, Q1
            data = _dart_get("fnlttSinglAcnt.json", {
                "corp_code":  corp_code,
                "bsns_year":  str(y),
                "reprt_code": reprt,
                "fs_div":     "CFS",  # 연결재무제표 우선
            })
            if data and data.get("list"):
                results.extend(data["list"])
            if len(results) >= 20:
                break
        if len(results) >= 20:
            break
    return results


def _extract_eps_revenue(financials: list[dict]) -> dict:
    """재무 리스트에서 EPS·매출액 추출."""
    eps = revenue = None
    for item in financials:
        acnt = str(item.get("account_nm", "")).strip()
        val  = str(item.get("thstrm_amount", "")).replace(",", "").strip()
        if not val or val in ("-", ""):
            continue
        try:
            v = float(val)
        except ValueError:
            continue
        if "주당순이익" in acnt or "EPS" in acnt.upper():
            if eps is None:
                eps = v
        elif "매출액" in acnt or "수익" in acnt:
            if revenue is None:
                revenue = v
    return {"eps": eps, "revenue": revenue}


# ─────────────────────────────────────────────
# Consensus stub
# ─────────────────────────────────────────────
def _get_consensus(stock_code: str) -> dict:
    """
    컨센서스 조회. 현재는 외부 provider 미연동 → FnGuide/에프앤가이드 stub.
    실제 연동 전까지 None 반환 (surprise_pct 계산 스킵).
    """
    return {"eps_consensus": None, "revenue_consensus": None}


# ─────────────────────────────────────────────
# Score mapping
# ─────────────────────────────────────────────
def _map_score(surprise_pct: float) -> tuple[float, str]:
    for lo, hi, pt, label in _SCORE_TABLE:
        if lo <= surprise_pct < hi:
            return pt, label
    return 0.0, "데이터 없음"


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────
def get_earnings_surprise_score(stock_code: str) -> dict:
    """
    BM-16 메인 함수. DART 실적 vs 컨센서스 비교 후 서프라이즈 점수 반환.

    Args:
        stock_code: 6자리 종목코드 (e.g. "005930")

    Returns:
        {
            "earnings_score":  float,   # -3 ~ +5
            "surprise_pct":    float,   # % (컨센서스 대비)
            "eps_actual":      float | None,
            "eps_consensus":   float | None,
            "detail":          str
        }
    """
    _null = {
        "earnings_score": 0.0,
        "surprise_pct":   0.0,
        "eps_actual":     None,
        "eps_consensus":  None,
        "detail":         "no data",
    }

    if not DART_API_KEY:
        _null["detail"] = "DART_API_KEY not set"
        return _null

    try:
        code = stock_code.zfill(6)

        corp_code = _get_corp_code(code)
        if not corp_code:
            _null["detail"] = f"corp_code not found for {code}"
            return _null

        financials = _fetch_recent_financials(corp_code)
        if not financials:
            _null["detail"] = "DART financials empty"
            return _null

        actual    = _extract_eps_revenue(financials)
        consensus = _get_consensus(code)

        eps_actual    = actual.get("eps")
        eps_consensus = consensus.get("eps_consensus")

        # EPS 기반 서프라이즈 계산
        if eps_actual is not None and eps_consensus is not None and eps_consensus != 0:
            surprise_pct = round((eps_actual - eps_consensus) / abs(eps_consensus) * 100, 2)
            score, label = _map_score(surprise_pct)
            return {
                "earnings_score": score,
                "surprise_pct":   surprise_pct,
                "eps_actual":     eps_actual,
                "eps_consensus":  eps_consensus,
                "detail":         f"{label} EPS={eps_actual:+.0f} vs consensus={eps_consensus:+.0f}",
            }

        # 컨센서스 없음 → 전기 대비 YoY 성장률로 대체 판단
        if eps_actual is not None:
            # financials에서 전기 EPS 탐색
            eps_vals = []
            for item in financials:
                acnt = str(item.get("account_nm", ""))
                if "주당순이익" in acnt or "EPS" in acnt.upper():
                    for field in ["thstrm_amount", "frmtrm_amount"]:
                        v = str(item.get(field, "")).replace(",", "")
                        try:
                            eps_vals.append(float(v))
                        except ValueError:
                            pass
            if len(eps_vals) >= 2 and eps_vals[1] != 0:
                yoy_pct  = round((eps_vals[0] - eps_vals[1]) / abs(eps_vals[1]) * 100, 2)
                score, label = _map_score(yoy_pct)
                return {
                    "earnings_score": score,
                    "surprise_pct":   yoy_pct,
                    "eps_actual":     eps_vals[0],
                    "eps_consensus":  None,
                    "detail":         f"[YoY] {label} {yoy_pct:+.1f}% (컨센서스 미연동)",
                }

        _null["detail"] = "EPS 데이터 부족"
        return _null

    except Exception as e:
        logger.warning("BM-16 error for %s: %s", stock_code, e)
        _null["detail"] = f"error: {e}"
        return _null


# ─────────────────────────────────────────────
# Batch scorer
# ─────────────────────────────────────────────
def score_earnings_batch(stock_codes: list[str]) -> dict:
    """
    복수 종목 일괄 처리.

    Returns:
        {stock_code: get_earnings_surprise_score() result}
    """
    results = {}
    for code in stock_codes:
        try:
            results[code] = get_earnings_surprise_score(code)
        except Exception as e:
            logger.warning("BM-16 batch error %s: %s", code, e)
            results[code] = {
                "earnings_score": 0.0, "surprise_pct": 0.0,
                "eps_actual": None, "eps_consensus": None,
                "detail": f"batch error: {e}",
            }
    return results


# ─────────────────────────────────────────────
# CLI self-test
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("BM-16 sfd_earnings_surprise.py — self-test")
    print("=" * 60)

    key_status = "설정됨" if DART_API_KEY else "미설정 (DART_API_KEY 환경변수 필요)"
    print(f"\nDART_API_KEY: {key_status}")

    # 점수 테이블 검증
    print("\n[Score table verification]")
    test_cases = [25.0, 15.0, 7.0, 0.0, -3.0, -10.0]
    for pct in test_cases:
        score, label = _map_score(pct)
        print(f"  surprise={pct:+6.1f}%  →  score={score:+.0f}pt  ({label})")

    # graceful fallback 검증
    print("\n[Graceful fallback (no API key)]")
    result = get_earnings_surprise_score("005930")
    print(f"  Samsung result: {result}")

    # DART_API_KEY가 있을 때만 실제 호출
    if DART_API_KEY:
        print("\n[Live DART call: 005930 Samsung]")
        r = get_earnings_surprise_score("005930")
        print(f"  {r}")
    else:
        print("\n[Live test skipped — set DART_API_KEY env var to test]")

    print("\n✅ BM-16 self-test complete")
