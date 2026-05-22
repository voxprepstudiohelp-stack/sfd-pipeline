"""
sfd_event_calendar_builder.py  v1.0
SFD Pipeline — Layer 1.6 (Event Calendar)
Schedule : 매주 일요일 22:00 KST  (GitHub Actions: sfd-event-calendar.yml)
Author   : Claude (Anthropic) — SFD Main Architect
Date     : 2026-05-22
"""

import os
import requests
import pandas as pd
from datetime import date, timedelta
import calendar as cal_mod

# ──────────────────────────────────────────
# 경로 설정
# ──────────────────────────────────────────
OUTPUT_PATH   = "outputs/latest/sfd_event_calendar_latest.csv"
BASE_CSV_PATH = "data/sfd_event_calendar_base.csv"

# ──────────────────────────────────────────
# 환경변수
# ──────────────────────────────────────────
FMP_API_KEY = os.environ.get("FMP_API_KEY", "")
FETCH_WEEKS = 10  # 오늘 기준 10주치 수집

# ──────────────────────────────────────────
# 매핑 테이블
# ──────────────────────────────────────────
IMPACT_SCORE_MAP = {
    "High":   -7,
    "Medium": -4,
    "Low":    -2,
    "None":    0,
}

D_MINUS_MAP = {
    "High":   2,
    "Medium": 1,
    "Low":    0,
}

DIRECTION_KEYWORDS = {
    "RISK_OFF": [
        "fomc", "rate decision", "cpi", "pce", "ppi",
        "unemployment", "기준금리", "금리결정", "물가",
    ],
    "RISK_ON": [
        "nfp", "nonfarm", "gdp", "retail sales", "ism manufacturing",
        "무역수지", "수출",
    ],
}

def get_direction(event_name: str) -> str:
    name_lower = event_name.lower()
    for direction, keywords in DIRECTION_KEYWORDS.items():
        if any(kw in name_lower for kw in keywords):
            return direction
    return "NEUTRAL"

# ──────────────────────────────────────────
# [1] FMP API — 미국·한국 매크로 이벤트
# ──────────────────────────────────────────
def fetch_fmp_events() -> list[dict]:
    if not FMP_API_KEY:
        print("[WARN] FMP_API_KEY 미설정 → FMP 수집 스킵")
        return []

    today    = date.today()
    end_date = today + timedelta(weeks=FETCH_WEEKS)
    url = (
        f"https://financialmodelingprep.com/api/v3/economic_calendar"
        f"?from={today.isoformat()}&to={end_date.isoformat()}"
        f"&apikey={FMP_API_KEY}"
    )

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        raw = resp.json()
    except Exception as e:
        print(f"[ERROR] FMP API 호출 실패: {e}")
        return []

    events = []
    for item in raw:
        country = (item.get("country") or "").upper()
        if country not in ("US", "KR"):
            continue

        impact = item.get("impact", "None") or "None"
        if impact == "None":
            continue  # 임팩트 없는 이벤트 필터링

        ev_name = (item.get("event") or "").strip()
        ev_date = (item.get("date") or "")[:10]  # YYYY-MM-DD

        if not ev_name or not ev_date:
            continue

        events.append({
            "event_date":      ev_date,
            "event_type":      "MACRO_US" if country == "US" else "MACRO_KR",
            "event_name":      ev_name,
            "market":          country,
            "impact_dir":      get_direction(ev_name),
            "impact_score":    IMPACT_SCORE_MAP.get(impact, -2),
            "d_minus_signal":  D_MINUS_MAP.get(impact, 1),
            "source":          "FMP_API",
            "notes":           f"FMP_impact={impact}",
        })

    print(f"[OK] FMP 이벤트 수집: {len(events)}건")
    return events


# ──────────────────────────────────────────
# [2] KRX 자동계산 — 월간 옵션만기
#     매월 2번째 목요일 (단, 쿼드러플 월 제외)
# ──────────────────────────────────────────
def get_monthly_option_expiry(year: int) -> list[dict]:
    events = []
    quad_months = {3, 6, 9, 12}

    for month in range(1, 13):
        if month in quad_months:
            continue  # 쿼드러플 위칭에서 처리

        month_cal = cal_mod.monthcalendar(year, month)
        thursdays = [week[3] for week in month_cal if week[3] != 0]
        if len(thursdays) < 2:
            continue

        expiry_day = thursdays[1]
        events.append({
            "event_date":      date(year, month, expiry_day).isoformat(),
            "event_type":      "DERIVATIVE",
            "event_name":      "KOSPI200 옵션만기",
            "market":          "KR",
            "impact_dir":      "NEUTRAL",
            "impact_score":    -3,
            "d_minus_signal":  1,
            "source":          "AUTO_KRX",
            "notes":           "수급 변동성 주의",
        })
    return events


# ──────────────────────────────────────────
# [3] KRX 자동계산 — 쿼드러플 위칭
#     3/6/9/12월 2번째 목요일
# ──────────────────────────────────────────
def get_quadruple_witching(year: int) -> list[dict]:
    events = []
    for month in [3, 6, 9, 12]:
        month_cal = cal_mod.monthcalendar(year, month)
        thursdays = [week[3] for week in month_cal if week[3] != 0]
        if len(thursdays) < 2:
            continue

        expiry_day = thursdays[1]
        events.append({
            "event_date":      date(year, month, expiry_day).isoformat(),
            "event_type":      "DERIVATIVE",
            "event_name":      "네 마녀의 날 (쿼드러플 위칭)",
            "market":          "KR",
            "impact_dir":      "NEUTRAL",
            "impact_score":    -5,
            "d_minus_signal":  2,
            "source":          "AUTO_KRX",
            "notes":           "선물+옵션+ETF+주식선물 동시만기 / 변동성 최대",
        })
    return events


# ──────────────────────────────────────────
# [4] base CSV 로드 — 수동 등록 이벤트
#     (BOK 금통위, 지정학, 실적시즌 등)
# ──────────────────────────────────────────
def load_base_events() -> list[dict]:
    try:
        df = pd.read_csv(BASE_CSV_PATH, encoding="utf-8-sig")
        # event_date를 문자열로 통일
        df["event_date"] = pd.to_datetime(df["event_date"]).dt.strftime("%Y-%m-%d")
        print(f"[OK] base CSV 로드: {len(df)}건")
        return df.to_dict("records")
    except FileNotFoundError:
        print(f"[WARN] base CSV 없음 ({BASE_CSV_PATH}) → 스킵")
        return []
    except Exception as e:
        print(f"[ERROR] base CSV 로드 실패: {e}")
        return []


# ──────────────────────────────────────────
# 메인 빌더
# ──────────────────────────────────────────
def build_calendar():
    today = date.today()
    year  = today.year

    print(f"\n{'='*50}")
    print(f"SFD Event Calendar Builder v1.0")
    print(f"실행일: {today.isoformat()}  |  수집범위: {FETCH_WEEKS}주")
    print(f"{'='*50}\n")

    events = []

    # Step 1. FMP API (US + KR 매크로)
    events += fetch_fmp_events()

    # Step 2. KRX 파생상품 만기 (올해 + 내년)
    for y in [year, year + 1]:
        events += get_monthly_option_expiry(y)
        events += get_quadruple_witching(y)
    print(f"[OK] KRX 파생만기 계산 완료")

    # Step 3. 수동 base CSV
    events += load_base_events()

    if not events:
        print("[FATAL] 수집된 이벤트 없음 — 종료")
        return

    # Step 4. 정제 및 저장
    df = (
        pd.DataFrame(events)
          .drop_duplicates(subset=["event_date", "event_name"])
          .sort_values("event_date")
          .reset_index(drop=True)
    )

    # 과거 이벤트 제외 (오늘 이전 30일 이후만 유지)
    cutoff = (today - timedelta(days=30)).isoformat()
    df = df[df["event_date"] >= cutoff].reset_index(drop=True)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

    # ── 요약 리포트
    print(f"\n{'─'*50}")
    print(f"[DONE] 저장 완료: {len(df)}건 → {OUTPUT_PATH}")
    print(f"\n[ 유형별 집계 ]")
    print(df["event_type"].value_counts().to_string())
    print(f"\n[ HIGH 임팩트 이벤트 (score ≤ -5) — 향후 30일 ]")
    upcoming = df[
        (df["impact_score"] <= -5) &
        (df["event_date"] <= (today + timedelta(days=30)).isoformat())
    ][["event_date", "event_name", "impact_score", "impact_dir"]]
    if upcoming.empty:
        print("  없음")
    else:
        print(upcoming.to_string(index=False))
    print(f"{'─'*50}\n")


if __name__ == "__main__":
    build_calendar()
