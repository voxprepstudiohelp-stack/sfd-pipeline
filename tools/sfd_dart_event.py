"""
sfd_dart_event.py v1.0
=======================
목적: DART 공시 유형 분류 → 영향 강도(pt) 매핑 → SFD 점수 반영
레이어: Layer 1.7 (Layer 1.6 event_calendar 다음)

입력: DART Open API (공시검색)
출력: outputs/latest/sfd_dart_event_latest.csv
      컬럼: ticker, corp_name, report_nm, event_type, impact_score,
             rcept_dt, url

영향 강도 매핑 테이블:
  해외수주/계약   +15pt   글로벌 수요 확인
  자사주취득      +10pt   수급 호재
  임상성공/허가   +20pt   바이오 트리거
  실적서프라이즈  +12pt   (BM-16과 별개, 공시 기반)
  유상증자        -10pt   희석 리스크
  전환사채(CB)    -8pt    잠재 희석
  임원 대량매도   -7pt    내부자 경보
  합병/인수(M&A)  +8pt    성장 기대
  분할/물적분할   -5pt    가치 훼손 우려
  관리종목지정    -20pt   퇴출 리스크

sfd_signal_aggregator.py 연동 방법:
  dart_event_latest.csv → ticker 매핑 → total_score += impact_score
"""

import os
import csv
import time
import logging
import requests
from datetime import datetime, date, timedelta
from pathlib import Path

# ── 경로 설정 ──────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
def _find_root() -> Path:
    for c in [_SCRIPT_DIR, _SCRIPT_DIR.parent]:
        if (c / ".env").exists():
            return c
    return _SCRIPT_DIR

BASE_DIR   = _find_root()
OUTPUT_DIR = BASE_DIR / "outputs" / "latest"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── 로깅 ───────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [DART_EVENT] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── .env 로드 ──────────────────────────────────────────────────
def load_env():
    ep = BASE_DIR / ".env"
    if ep.exists():
        for line in ep.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

load_env()
DART_API_KEY = os.environ.get("DART_API_KEY", "")
DART_BASE    = "https://opendart.fss.or.kr/api"

# ══════════════════════════════════════════════════════════════
# 공시 유형 → 영향 강도 매핑 테이블
# ══════════════════════════════════════════════════════════════
# (키워드, event_type, impact_score, 설명)
DART_EVENT_MAP = [
    # ── 강한 악재 (우선 매칭) ───────────────────────────────────
    (["관리종목", "상장폐지", "거래정지"],                "관리종목",      -20),
    (["횡령", "배임", "금융감독", "검찰"],                "법적리스크",    -15),
    (["유상증자", "주주배정", "제3자배정"],               "유상증자",      -10),
    (["전환사채", "CB발행", "BW발행", "신주인수권부사채"],"CB/BW발행",     -8),
    # ── 자사주 (계약 키워드보다 반드시 먼저) ────────────────────
    (["자사주", "자기주식취득", "자기주식신탁"],          "자사주취득",    +10),
    # ── 강한 호재 ──────────────────────────────────────────────
    (["임상", "FDA", "허가", "승인", "식약처"],          "임상/허가",     +20),
    (["수주", "수출계약", "공급계약", "납품계약", "MOU"], "해외수주/계약", +15),
    (["영업이익", "매출액", "흑자전환", "실적발표"],      "실적호조",      +12),
    (["합병", "인수합병", "M&A", "지분취득"],             "M&A",           +8),
    (["특허", "기술이전", "라이선스아웃"],                "특허/기술이전", +7),
    (["배당", "중간배당", "특별배당"],                    "배당",          +5),
    (["상장", "IPO", "코스피이전상장"],                   "상장",          +5),
    # ── 약한/중간 악재 ─────────────────────────────────────────
    (["임원", "대량매도", "장내매도"],                    "임원매도",      -7),
    (["물적분할", "인적분할"],                            "분할",          -5),
    (["사임", "해임", "대표이사변경"],                    "임원변동",      -3),
]

def classify_report(report_nm: str) -> tuple[str, int]:
    """공시명 → (event_type, impact_score). 미분류 시 ("기타", 0)"""
    for keywords, etype, score in DART_EVENT_MAP:
        if any(kw in report_nm for kw in keywords):
            return etype, score
    return "기타", 0


# ══════════════════════════════════════════════════════════════
# DART API 호출
# ══════════════════════════════════════════════════════════════
def fetch_dart_disclosures(bgn_de: str, end_de: str, pblntf_ty: str = "A") -> list[dict]:
    """
    DART 공시 검색 API
    bgn_de / end_de: YYYYMMDD
    pblntf_ty: A=정기공시, B=주요사항보고, C=발행공시, D=지분공시, F=거래소공시
    """
    if not DART_API_KEY:
        log.error("DART_API_KEY 없음")
        return []

    all_items = []
    for ptype in ["B", "C", "D", "F"]:  # 주요사항+발행+지분+거래소
        params = {
            "crtfc_key": DART_API_KEY,
            "bgn_de":    bgn_de,
            "end_de":    end_de,
            "pblntf_ty": ptype,
            "page_no":   "1",
            "page_count":"100",
        }
        try:
            r = requests.get(f"{DART_BASE}/list.json", params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
            if data.get("status") == "000":
                items = data.get("list", [])
                all_items.extend(items)
                log.info(f"  DART pblntf_ty={ptype}: {len(items)}건")
            else:
                log.warning(f"  DART pblntf_ty={ptype}: status={data.get('status')} {data.get('message','')}")
            time.sleep(0.3)
        except Exception as e:
            log.error(f"  DART fetch 실패(type={ptype}): {e}")

    return all_items


def load_master_tickers() -> dict:
    """master_signal에서 ticker→corp_name 매핑 로드"""
    mapping = {}
    for fname in ["sfd_master_signal_latest.csv", "sfd_master_signal.csv"]:
        fp = OUTPUT_DIR / fname
        if fp.exists():
            try:
                with open(fp, encoding="utf-8-sig", newline="") as f:
                    for row in csv.DictReader(f):
                        code = row.get("stock_code", row.get("ticker",""))
                        name = row.get("name", row.get("hts_kor_isnm",""))
                        if code:
                            mapping[code] = name
            except Exception:
                pass
            log.info(f"master_signal 로드: {len(mapping)}종목")
            break
    return mapping


# ══════════════════════════════════════════════════════════════
# 메인 실행
# ══════════════════════════════════════════════════════════════
def run(lookback_days: int = 3):
    today     = date.today()
    bgn_de    = (today - timedelta(days=lookback_days)).strftime("%Y%m%d")
    end_de    = today.strftime("%Y%m%d")
    ts        = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    log.info(f"=== sfd_dart_event.py v1.0 시작 ({ts}) ===")
    log.info(f"조회 기간: {bgn_de} ~ {end_de}")

    if not DART_API_KEY:
        log.error("DART_API_KEY 없음 — .env 확인")
        return []

    # DART 공시 수집
    items = fetch_dart_disclosures(bgn_de, end_de)
    log.info(f"전체 공시: {len(items)}건")

    # master ticker 로드 (SFD 추적 종목만 필터링)
    ticker_map = load_master_tickers()

    # 분류 + 필터링
    results = []
    skipped_other = 0
    for item in items:
        stock_code = item.get("stock_code", "").zfill(6)
        corp_name  = item.get("corp_name", "")
        report_nm  = item.get("report_nm", "")
        rcept_dt   = item.get("rcept_dt", "")
        rcept_no   = item.get("rcept_no", "")

        etype, score = classify_report(report_nm)

        if etype == "기타":
            skipped_other += 1
            continue

        # SFD 추적 종목 여부 (없으면 전체 포함)
        in_sfd = stock_code in ticker_map

        results.append({
            "ticker":       stock_code,
            "corp_name":    corp_name,
            "report_nm":    report_nm,
            "event_type":   etype,
            "impact_score": score,
            "rcept_dt":     rcept_dt,
            "in_sfd":       "Y" if in_sfd else "N",
            "url":          f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
        })

    # impact_score 절댓값 기준 정렬
    results.sort(key=lambda x: abs(x["impact_score"]), reverse=True)

    # 저장
    out_path    = OUTPUT_DIR / "sfd_dart_event_latest.csv"
    backup_path = OUTPUT_DIR / f"sfd_dart_event_{today.strftime('%Y%m%d')}.csv"
    fieldnames  = ["ticker","corp_name","report_nm","event_type",
                   "impact_score","rcept_dt","in_sfd","url"]

    for p in [out_path, backup_path]:
        with open(p, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

    # SFD 추적 종목만 별도 요약
    sfd_hits = [r for r in results if r["in_sfd"] == "Y"]

    log.info("=" * 55)
    log.info(f"[완료] 전체 분류: {len(results)}건 / 기타 스킵: {skipped_other}건")
    log.info(f"  SFD 추적 종목 히트: {len(sfd_hits)}건")
    log.info(f"  저장: {out_path}")
    if sfd_hits:
        log.info("  ── SFD 히트 TOP5 ──")
        for r in sfd_hits[:5]:
            sign = "+" if r["impact_score"] > 0 else ""
            log.info(f"  {r['corp_name']:12s} [{r['event_type']}] {sign}{r['impact_score']}pt  {r['report_nm'][:30]}")
    log.info("=" * 55)

    return results


if __name__ == "__main__":
    run()
