#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sfd_event_calendar_builder.py — Layer 1.6  v2.1
DART 공시 기반 이벤트 캘린더 + BM-5 Volatility Buffer

변경사항 (v2.0 → v2.1):
  [BM-5] Volatility Buffer 추가
    - event_time      : 공시 접수 시각 (HHmm → HH:MM 포맷)
    - no_trade_start  : 이벤트 시각 - 60분
    - no_trade_end    : 이벤트 시각 + 60분
    - is_no_trade_now : 현재 KST 시각이 no_trade 구간 내이면 True
  [출력] sfd_no_trade_tickers.json 추가
    - 현재 시각 기준 No-Trade 대상 ticker 목록
    - trade_guardian / signal_aggregator에서 참조

입출력:
  IN  : DART OpenAPI (공시 목록)
  OUT : outputs/latest/sfd_event_calendar.csv
  OUT : outputs/latest/sfd_event_summary.json
  OUT : outputs/latest/sfd_no_trade_tickers.json  ← BM-5 신규

버전: v2.1
작성: Claude Sonnet 4.6 (2026-05-31)
"""

import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from dotenv import load_dotenv

# ======================================
# 경로 설정
# ======================================
_HERE           = Path(__file__).resolve().parent
_PIPELINE_ROOT  = _HERE.parent
_LATEST         = _PIPELINE_ROOT / "outputs" / "latest"

EVENT_OUT       = _LATEST / "sfd_event_calendar.csv"
SUMMARY_OUT     = _LATEST / "sfd_event_summary.json"
NO_TRADE_OUT    = _LATEST / "sfd_no_trade_tickers.json"   # BM-5 신규

load_dotenv(_PIPELINE_ROOT / ".env")
DART_API_KEY = os.getenv("DART_API_KEY", "")

DART_BASE = "https://opendart.fss.or.kr/api"

# BM-5: No-Trade 버퍼 (분)
NO_TRADE_BUFFER_MIN = 60

KST = ZoneInfo("Asia/Seoul")

# ======================================
# 이벤트 분류 규칙
# ======================================
EVENT_RULES = [
    # (키워드, 등급, 이벤트명, 영향 설명)
    ("유상증자",        "HIGH",  "유상증자",        "+30% 수급영향 리스크"),
    ("무상증자",        "HIGH",  "무상증자",        "+30% 수급영향 리스크"),
    ("주주총회소집공고", "HIGH",  "주주총회",        "의결권 행사"),
    ("자기주식취득결정", "HIGH",  "자사주취득결정",  "의결권 행사"),
    ("영업(잠정)실적",  "HIGH",  "잠정실적",        "의결권 행사"),
    ("주요사항보고서제출기한",  "HIGH",  "주요사항보고서",  "10%↑ 의결권"),
    ("합병결정",        "HIGH",  "합병결정",        "급등락 급등 이상"),
    ("분할",            "HIGH",  "분할공시",        "시장 or 자산 이상"),
    ("상품판매중단",    "MID",   "상품판매중단",    "섹터 이상 업데이트"),
    ("주식교환",        "MID",   "주식교환",        "잠재 or 손실 공시"),
    ("CB발행",          "MID",   "CB발행",          "주가 희석 업데이트"),
    ("신주인수권",      "MID",   "신주인수권",      "확인 이후 대응"),
    ("단기차입",        "MID",   "단기차입공시",    "재무구조 업데이트"),
    ("증자",            "MID",   "증자공시",        "재무구조 업데이트"),
    ("자본감소",        "MID",   "자본감소공시",    "손익 재공시"),
    ("배당",            "LOW",   "배당공시",        "주가 영향 낮음"),
    ("정정",            "LOW",   "정정공시",        "기존 공시 정정"),
]

GRADE_SCORE = {"HIGH": 30, "MID": 15, "LOW": 5}


# ======================================
# DART API 수집
# ======================================
def fetch_dart_list(bgn_de: str, end_de: str) -> list:
    """공시 목록 조회 (최대 100건/페이지)"""
    if not DART_API_KEY:
        print("[Layer1.6] ERROR: DART_API_KEY 환경변수 없음 → .env 확인")
        return []

    all_items = []
    page = 1

    while True:
        params = {
            "crtfc_key":  DART_API_KEY,
            "bgn_de":     bgn_de,
            "end_de":     end_de,
            "page_no":    page,
            "page_count": 100,
        }
        try:
            resp = requests.get(f"{DART_BASE}/list.json", params=params, timeout=10)
            data = resp.json()
        except Exception as e:
            print(f"[Layer1.6] DART API 실패: {e}")
            break

        if data.get("status") != "000":
            print(f"[Layer1.6] DART 응답 오류: {data.get('message', '')}")
            break

        items = data.get("list", [])
        all_items.extend(items)

        total = int(data.get("total_count", 0))
        if page * 100 >= total:
            break
        page += 1
        time.sleep(0.3)

    print(f"[Layer1.6] DART 수집 완료: {len(all_items)}건 ({bgn_de}~{end_de})")
    return all_items


# ======================================
# 이벤트 분류
# ======================================
def classify_disclosure(report_nm: str) -> tuple:
    """공시명 → (등급, 이벤트명, 영향) or None"""
    for keyword, grade, event_name, impact in EVENT_RULES:
        if keyword in report_nm:
            return grade, event_name, impact
    return None, None, None


# ======================================
# BM-5: No-Trade 구간 계산
# ======================================
def calc_no_trade_window(rcept_dt: str, rcept_time: str = "") -> tuple:
    """
    공시 접수일시 → no_trade_start / no_trade_end (KST)
    rcept_dt  : YYYYMMDD
    rcept_time: HHMM (DART API에서 제공하는 경우)
    DART list API는 시분 미제공 → 09:00 기본값 사용
    """
    try:
        hhmm = rcept_time.strip() if rcept_time else "0900"
        if len(hhmm) == 4:
            hh, mm = int(hhmm[:2]), int(hhmm[2:])
        else:
            hh, mm = 9, 0

        event_dt = datetime(
            int(rcept_dt[:4]), int(rcept_dt[4:6]), int(rcept_dt[6:8]),
            hh, mm, tzinfo=KST
        )
        no_trade_start = event_dt - timedelta(minutes=NO_TRADE_BUFFER_MIN)
        no_trade_end   = event_dt + timedelta(minutes=NO_TRADE_BUFFER_MIN)

        return (
            event_dt.strftime("%H:%M"),
            no_trade_start.strftime("%H:%M"),
            no_trade_end.strftime("%H:%M"),
        )
    except Exception:
        return "09:00", "08:00", "10:00"


def is_in_no_trade_window(rcept_dt: str, no_trade_start: str, no_trade_end: str) -> bool:
    """현재 KST 시각이 no_trade 구간 내인지 확인"""
    try:
        now = datetime.now(KST)
        today_str = now.strftime("%Y%m%d")

        # 오늘 공시만 No-Trade 적용
        if rcept_dt != today_str:
            return False

        def to_dt(hhmm_str):
            h, m = map(int, hhmm_str.split(":"))
            return now.replace(hour=h, minute=m, second=0, microsecond=0)

        return to_dt(no_trade_start) <= now <= to_dt(no_trade_end)
    except Exception:
        return False


# ======================================
# 메인
# ======================================
def main():
    today     = date.today()
    yesterday = today - timedelta(days=1)

    # 월요일 보정: 토~일 공시 포함
    if today.weekday() == 0:
        yesterday = today - timedelta(days=3)

    bgn_de = yesterday.strftime("%Y%m%d")
    end_de = today.strftime("%Y%m%d")

    print(f"[Layer1.6] sfd_event_calendar_builder v2.1 시작 | {bgn_de}~{end_de}")

    if not DART_API_KEY:
        print("[Layer1.6] WARN: DART_API_KEY 없음 → 빈 이벤트 캘린더 생성")
        df_empty = pd.DataFrame(columns=[
            "rcept_dt", "corp_name", "ticker", "report_nm",
            "event_grade", "event_name", "event_impact", "event_score",
            "event_time", "no_trade_start", "no_trade_end", "is_no_trade_now"
        ])
        df_empty.to_csv(EVENT_OUT, index=False, encoding="utf-8-sig")
        summary = {"as_of_date": str(today), "total": 0, "HIGH": 0, "MID": 0, "LOW": 0, "events": []}
        SUMMARY_OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        no_trade = {"as_of_datetime": datetime.now(KST).isoformat(), "no_trade_tickers": []}
        NO_TRADE_OUT.write_text(json.dumps(no_trade, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[Layer1.6] DART_API_KEY를 .env에 설정: DART_API_KEY=your_key")
        print("           가입: https://opendart.fss.or.kr/")
        return 0

    # 공시 수집
    items = fetch_dart_list(bgn_de, end_de)

    # 이벤트 분류 + BM-5 no_trade 구간 계산
    rows = []
    for item in items:
        report_nm = item.get("report_nm", "")
        grade, event_name, impact = classify_disclosure(report_nm)
        if grade is None:
            continue

        rcept_dt   = item.get("rcept_dt", "")
        rcept_time = item.get("rcept_tm", "")  # DART list API: rcept_tm 필드 (없을 수도 있음)

        event_time, no_trade_start, no_trade_end = calc_no_trade_window(rcept_dt, rcept_time)
        is_no_trade = is_in_no_trade_window(rcept_dt, no_trade_start, no_trade_end)

        rows.append({
            "rcept_dt":       rcept_dt,
            "corp_name":      item.get("corp_name", ""),
            "stock_code":     item.get("stock_code", "").zfill(6),
            "report_nm":      report_nm,
            "event_grade":    grade,
            "event_name":     event_name,
            "event_impact":   impact,
            "event_score":    GRADE_SCORE[grade],
            # BM-5 컬럼
            "event_time":     event_time,
            "no_trade_start": no_trade_start,
            "no_trade_end":   no_trade_end,
            "is_no_trade_now": is_no_trade,
            # 참조용
            "rcept_no":       item.get("rcept_no", ""),
            "dart_url":       f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.get('rcept_no', '')}",
        })

    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=[
        "rcept_dt", "corp_name", "stock_code", "report_nm",
        "event_grade", "event_name", "event_impact", "event_score",
        "event_time", "no_trade_start", "no_trade_end", "is_no_trade_now",
        "rcept_no", "dart_url"
    ])

    # 등급순 정렬
    grade_order = {"HIGH": 0, "MID": 1, "LOW": 2}
    if not df.empty:
        df["_order"] = df["event_grade"].map(grade_order)
        df = df.sort_values(["_order", "rcept_dt"], ascending=[True, False])
        df = df.drop(columns=["_order"])

    _LATEST.mkdir(parents=True, exist_ok=True)
    df.to_csv(EVENT_OUT, index=False, encoding="utf-8-sig")

    # 요약 JSON
    high_n = len(df[df["event_grade"] == "HIGH"]) if not df.empty else 0
    mid_n  = len(df[df["event_grade"] == "MID"])  if not df.empty else 0
    low_n  = len(df[df["event_grade"] == "LOW"])  if not df.empty else 0

    summary = {
        "as_of_date": str(today),
        "period":     f"{bgn_de}~{end_de}",
        "total":      len(df),
        "HIGH":       high_n,
        "MID":        mid_n,
        "LOW":        low_n,
        "events":     df[df["event_grade"] == "HIGH"].to_dict("records") if not df.empty else []
    }
    SUMMARY_OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # BM-5: No-Trade ticker 목록 JSON
    now_kst = datetime.now(KST)
    if not df.empty and "is_no_trade_now" in df.columns:
        no_trade_df = df[df["is_no_trade_now"] == True]
        no_trade_tickers = no_trade_df["stock_code"].unique().tolist()
        no_trade_details = no_trade_df[["stock_code", "corp_name", "event_name",
                                         "no_trade_start", "no_trade_end"]].to_dict("records")
    else:
        no_trade_tickers = []
        no_trade_details = []

    no_trade_json = {
        "as_of_datetime":   now_kst.isoformat(),
        "buffer_minutes":   NO_TRADE_BUFFER_MIN,
        "no_trade_count":   len(no_trade_tickers),
        "no_trade_tickers": no_trade_tickers,
        "details":          no_trade_details,
    }
    NO_TRADE_OUT.write_text(json.dumps(no_trade_json, ensure_ascii=False, indent=2), encoding="utf-8")

    # 결과 출력
    print(f"\n[Layer1.6] 이벤트 감지: 총 {len(df)}건 (HIGH={high_n} / MID={mid_n} / LOW={low_n})")
    print(f"[Layer1.6] No-Trade 대상: {len(no_trade_tickers)}종목 (±{NO_TRADE_BUFFER_MIN}분 버퍼)")

    if not df.empty:
        for _, row in df[df["event_grade"] == "HIGH"].iterrows():
            no_trade_flag = " ⛔ NO-TRADE" if row.get("is_no_trade_now") else ""
            print(f"  🔴 HIGH | {row['corp_name']}({row['stock_code']}) "
                  f"| {row['event_name']} | {row['event_time']}"
                  f" [{row['no_trade_start']}~{row['no_trade_end']}]{no_trade_flag}")
        if mid_n > 0:
            print(f"  🟡 MID  | {mid_n}건 (sfd_event_calendar.csv 참조)")

    if no_trade_tickers:
        print(f"\n  ⛔ No-Trade 활성 종목: {no_trade_tickers}")

    print(f"\n  → {EVENT_OUT}")
    print(f"  → {SUMMARY_OUT}")
    print(f"  → {NO_TRADE_OUT}")
    print("[Layer1.6] 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
