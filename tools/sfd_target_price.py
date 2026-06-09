"""
sfd_target_price.py
BM-15: AI 목표주가 자동 산출
SFD Pipeline - independent reference indicator

Score range: -3 ~ +8pt
Runs as a standalone reference column (tp_score, upside_pct).
Does NOT contribute to total_score in v3.8 — weight to be decided.

Data source priority:
  1. DART API (fnlttStkIssuStat → 증권신고서 공시 목표주가 탐색)
  2. Naver Finance mobile API consensus (m.stock.naver.com)
  3. fallback → tp_score=0

Author: Claude (Architect)
Version: 1.0
Date: 2026-06-09
"""

import os
import re
import logging
import urllib.request
import urllib.parse
import json
from datetime import datetime, timedelta

import FinanceDataReader as fdr

logger = logging.getLogger(__name__)

DART_API_KEY = os.environ.get("DART_API_KEY", "")
DART_BASE    = "https://opendart.fss.or.kr/api"
NAVER_API    = "https://m.stock.naver.com/api/stock/{code}/investmentOpinion"

# 괴리율 → 점수 테이블
_SCORE_TABLE = [
    ( 30.0,  float("inf"),  8.0, "대형 업사이드(>30%)"),
    ( 20.0,  30.0,          6.0, "중형 업사이드(20~30%)"),
    ( 10.0,  20.0,          4.0, "소형 업사이드(10~20%)"),
    (  5.0,  10.0,          2.0, "미소 업사이드(5~10%)"),
    (  0.0,   5.0,          0.0, "컨센서스 부합(0~5%)"),
    (float("-inf"), 0.0,   -3.0, "다운사이드"),
]


# ─────────────────────────────────────────────
# 공통 유틸
# ─────────────────────────────────────────────
def _map_score(upside_pct: float) -> tuple[float, str]:
    for lo, hi, pt, label in _SCORE_TABLE:
        if lo <= upside_pct < hi:
            return pt, label
    return 0.0, "데이터 없음"


def _get_current_price(stock_code: str) -> float | None:
    """FDR로 최근 종가 조회."""
    try:
        today = datetime.now()
        start = (today - timedelta(days=7)).strftime("%Y-%m-%d")
        end   = today.strftime("%Y-%m-%d")
        df = fdr.DataReader(stock_code, start, end)
        if df is not None and len(df) > 0:
            return float(df["Close"].iloc[-1])
    except Exception as e:
        logger.debug("BM-15: FDR current price error %s: %s", stock_code, e)
    return None


def _dart_get(endpoint: str, params: dict) -> dict | None:
    if not DART_API_KEY:
        return None
    params["crtfc_key"] = DART_API_KEY
    url = f"{DART_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "sfd-pipeline/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data if data.get("status") == "000" else None
    except Exception as e:
        logger.debug("BM-15: DART request failed (%s): %s", endpoint, e)
        return None


# ─────────────────────────────────────────────
# Priority 1: DART 공시 검색 → 목표주가 추출
# ─────────────────────────────────────────────
def _get_dart_target_price(stock_code: str) -> float | None:
    """
    DART fnlttStkIssuStat: 주식발행현황 조회 후 corp_code 확보.
    실적 리포트(사업보고서) 내 목표주가 텍스트 패턴 탐색.
    DART 공시 원문에서 목표주가를 파싱하는 방식이라 정확도 제한적.
    """
    if not DART_API_KEY:
        return None

    # corp_code 조회
    company = _dart_get("company.json", {"stock_code": stock_code.zfill(6)})
    if not company:
        return None
    corp_code = company.get("corp_code")
    if not corp_code:
        return None

    # 최근 분기 공시에서 목표주가 텍스트 탐색 (fnlttStkIssuStat)
    year = datetime.now().year
    data = _dart_get("fnlttStkIssuStat.json", {
        "corp_code": corp_code,
        "bsns_year": str(year),
        "reprt_code": "11011",  # 1분기보고서
    })
    if not data or not data.get("list"):
        return None

    # 목표주가 패턴 검색 (공시 내 자유기재 항목)
    for item in data["list"]:
        for val in item.values():
            txt = str(val)
            m = re.search(r'목표\s*주가[\s:：]*([0-9,]+)', txt)
            if m:
                try:
                    return float(m.group(1).replace(",", ""))
                except ValueError:
                    pass
    return None


# ─────────────────────────────────────────────
# Priority 2: 네이버 금융 모바일 API
# ─────────────────────────────────────────────
def _get_naver_target_price(stock_code: str) -> float | None:
    """
    네이버 금융 모바일 API에서 consensus 목표주가 조회.
    endpoint: m.stock.naver.com/api/stock/{code}/investmentOpinion
    """
    url = NAVER_API.format(code=stock_code.zfill(6))
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent":      "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)",
            "Accept":          "application/json",
            "Referer":         f"https://m.stock.naver.com/domestic/stock/{stock_code}/total",
            "Accept-Language": "ko-KR,ko;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw  = resp.read().decode("utf-8")
            data = json.loads(raw)

        # 응답 구조 탐색 (Naver API 버전에 따라 키 다를 수 있음)
        for key in ("targetPrice", "target_price", "목표주가"):
            if key in data and data[key]:
                return float(str(data[key]).replace(",", ""))

        # 중첩 구조 탐색
        for section in ("opinion", "consensus", "investmentOpinion", "data"):
            sub = data.get(section, {})
            if isinstance(sub, dict):
                for key in ("targetPrice", "target_price", "avgTargetPrice"):
                    if key in sub and sub[key]:
                        return float(str(sub[key]).replace(",", ""))

        logger.debug("BM-15: Naver API response keys=%s", list(data.keys())[:10])
        return None

    except Exception as e:
        logger.debug("BM-15: Naver API error %s: %s", stock_code, e)

    # 네이버 금융 PC 페이지 HTML fallback
    return _scrape_naver_html(stock_code)


def _scrape_naver_html(stock_code: str) -> float | None:
    """네이버 금융 PC 페이지 HTML에서 목표주가 패턴 스크래핑."""
    url = f"https://finance.naver.com/item/coinfo.naver?code={stock_code.zfill(6)}"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent":      "Mozilla/5.0",
            "Accept-Language": "ko-KR,ko;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("euc-kr", errors="replace")

        patterns = [
            r'목표\s*주가[^0-9]{0,30}([0-9]{4,8})',
            r'consensusTargetPrice["\s:]+([0-9]+)',
            r'"targetPrice"\s*:\s*([0-9]+)',
        ]
        for pat in patterns:
            m = re.search(pat, html)
            if m:
                val = float(m.group(1).replace(",", ""))
                if val > 1000:   # 최소 1,000원 이상이어야 유효
                    return val
    except Exception as e:
        logger.debug("BM-15: Naver HTML scrape error %s: %s", stock_code, e)
    return None


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────
def get_target_price_score(stock_code: str) -> dict:
    """
    BM-15 메인 함수. 데이터 소스 우선순위에 따라 목표주가 조회 후 점수 반환.

    Args:
        stock_code: 6자리 종목코드 (e.g. "005930")

    Returns:
        {
            "tp_score":      float,         # -3 ~ +8
            "target_price":  float | None,  # 원화 목표주가
            "current_price": float | None,  # 현재가(종가)
            "upside_pct":    float,         # 업사이드 %
            "source":        str,           # 데이터 소스
            "detail":        str
        }
    """
    _null = {
        "tp_score":      0.0,
        "target_price":  None,
        "current_price": None,
        "upside_pct":    0.0,
        "source":        "none",
        "detail":        "no data",
    }

    code = stock_code.zfill(6)

    try:
        current_price = _get_current_price(code)

        # Priority 1: DART
        target_price = _get_dart_target_price(code)
        source       = "DART"

        # Priority 2: Naver
        if target_price is None:
            target_price = _get_naver_target_price(code)
            source       = "Naver"

        if target_price is None or current_price is None or current_price <= 0:
            _null["current_price"] = current_price
            _null["detail"]        = f"target_price={target_price} current={current_price}"
            return _null

        upside_pct   = round((target_price - current_price) / current_price * 100, 2)
        score, label = _map_score(upside_pct)

        return {
            "tp_score":      score,
            "target_price":  target_price,
            "current_price": current_price,
            "upside_pct":    upside_pct,
            "source":        source,
            "detail":        f"{label} TP={target_price:,.0f} / CP={current_price:,.0f} / upside={upside_pct:+.1f}%",
        }

    except Exception as e:
        logger.warning("BM-15 error for %s: %s", stock_code, e)
        _null["detail"] = f"error: {e}"
        return _null


# ─────────────────────────────────────────────
# Batch scorer
# ─────────────────────────────────────────────
def score_target_price_batch(stock_codes: list[str]) -> dict:
    """
    복수 종목 일괄 처리.

    Returns:
        {stock_code: get_target_price_score() result}
    """
    results = {}
    for code in stock_codes:
        try:
            results[code] = get_target_price_score(code)
        except Exception as e:
            logger.warning("BM-15 batch error %s: %s", code, e)
            results[code] = {
                "tp_score": 0.0, "target_price": None,
                "current_price": None, "upside_pct": 0.0,
                "source": "error", "detail": f"batch error: {e}",
            }
    return results


# ─────────────────────────────────────────────
# CLI self-test
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("BM-15 sfd_target_price.py — self-test")
    print("=" * 60)

    key_status = "설정됨" if DART_API_KEY else "미설정"
    print(f"\nDART_API_KEY: {key_status}")

    # 점수 테이블 검증
    print("\n[Score table verification]")
    test_cases = [35.0, 25.0, 15.0, 7.0, 2.0, -5.0]
    for pct in test_cases:
        score, label = _map_score(pct)
        print(f"  upside={pct:+6.1f}%  →  tp_score={score:+.0f}pt  ({label})")

    # 현재가 조회 테스트
    print("\n[Current price test: 005930]")
    cp = _get_current_price("005930")
    print(f"  Samsung current price: {cp:,.0f}원" if cp else "  조회 실패")

    # Naver 목표주가 조회 테스트
    print("\n[Naver target price test: 005930]")
    tp = _get_naver_target_price("005930")
    print(f"  Samsung target price: {tp:,.0f}원" if tp else "  조회 실패 (graceful fallback)")

    # 종합 스코어 테스트
    print("\n[Full score test: 005930]")
    result = get_target_price_score("005930")
    for k, v in result.items():
        print(f"  {k}: {v}")

    print("\n✅ BM-15 self-test complete")
