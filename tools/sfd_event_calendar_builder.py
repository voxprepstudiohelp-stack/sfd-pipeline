#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sfd_event_calendar_builder.py — Layer 1.6  v2.0
DART 공시 기반 이벤트 캘린더 빌더

역할:
  - DART OpenAPI로 전일/당일 공시 수집
  - 급등 트리거 공시 필터링 (주식병합, 거래재개, 대규모계약, 유상증자 등)
  - sfd_event_calendar.csv 생성 → Layer 2 signal_aggregator에 theme_score 반영

포착 대상 공시 유형:
  🔴 HIGH  : 주식병합/분할 재개, 관리종목 해제, 대규모 계약 (매출 10%↑)
  🟡 MID   : 유상증자, 전환사채 발행, 자사주 취득, 신규사업 진출
  🟢 LOW   : 임원 변경, 배당 결정, 분기보고서 제출

DART API:
  - 등록: https://opendart.fss.or.kr/
  - .env: DART_API_KEY=your_key

흐름도:
  IN  : DART OpenAPI (공시 목록)
  OUT : outputs/latest/sfd_event_calendar.csv
  OUT : outputs/latest/sfd_event_summary.json

버전: v2.0
작성: Claude Sonnet 4.6 (2026-05-27)
"""

import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

# ============================
# 경로 설정
# ============================
_HERE          = Path(__file__).resolve().parent
_PIPELINE_ROOT = _HERE.parent
_LATEST        = _PIPELINE_ROOT / "outputs" / "latest"

EVENT_OUT   = _LATEST / "sfd_event_calendar.csv"
SUMMARY_OUT = _LATEST / "sfd_event_summary.json"

load_dotenv(_PIPELINE_ROOT / ".env")
DART_API_KEY = os.getenv("DART_API_KEY", "")

DART_BASE = "https://opendart.fss.or.kr/api"

# ============================
# 공시 유형 분류표
# ============================
EVENT_RULES = [
    # (키워드, 등급, 이벤트명, 예상영향)
    ("주식병합",     "HIGH",  "주식병합",      "+30% 상한가 가능"),
    ("액면병합",     "HIGH",  "액면병합",      "+30% 상한가 가능"),
    ("매매거래재개",  "HIGH",  "거래재개",      "급등 가능"),
    ("관리종목해제",  "HIGH",  "관리종목해제",   "급등 가능"),
    ("상장폐지취소",  "HIGH",  "상폐취소",      "급등 가능"),
    ("단일판매공급계약", "HIGH", "대규모계약",  "매출 10%↑ 급등"),
    ("공급계약",     "HIGH",  "공급계약",      "매출 기여 기대"),
    ("수주",         "HIGH",  "수주공시",      "실적 기여 기대"),
    ("자기주식취득",  "MID",   "자사주매입",    "주가 방어 신호"),
    ("유상증자",     "MID",   "유상증자",      "희석 or 성장 투자"),
    ("전환사채",     "MID",   "CB발행",        "오버행 주의"),
    ("신규사업",     "MID",   "신규사업",      "테마 편입 가능"),
    ("합병",         "MID",   "합병공시",      "변동성 확대"),
    ("분할",         "MID",   "분할공시",      "변동성 확대"),
    ("주식분할",     "MID",   "주식분할",      "유동성 증가"),
    ("배당",         "LOW",   "배당결정",      "안정 신호"),
    ("임원",         "LOW",   "임원변경",      "경영진 변화"),
]

GRADE_SCORE = {"HIGH": 30, "MID": 15, "LOW": 5}


# ============================
# DART API 호출
# ============================
def fetch_dart_list(bgn_de: str, end_de: str) -> list:
    """공시 목록 조회 (최대 100건/페이지)"""
    if not DART_API_KEY:
        print("[Layer1.6] ERROR: DART_API_KEY not configured — check .env")
        return []

    all_items = []
    page = 1

    while True:
        params = {
            "crtfc_key": DART_API_KEY,
            "bgn_de":    bgn_de,
            "end_de":    end_de,
            "page_no":   page,
            "page_count": 100,
        }
        try:
            resp = requests.get(f"{DART_BASE}/list.json", params=params, timeout=10)
            data = resp.json()
        except Exception as e:
            print(f"[Layer1.6] DART API ERROR: {e}")
            break

        if data.get("status") != "000":
            print(f"[Layer1.6] DART response ERROR: {data.get('message', '')}")
            break

        items = data.get("list", [])
        all_items.extend(items)

        total = int(data.get("total_count", 0))
        if page * 100 >= total:
            break
        page += 1
        time.sleep(0.3)

    print(f"[Layer1.6] DART disclosures fetched: {len(all_items)} items ({bgn_de}~{end_de})")
    return all_items


# ============================
# 공시 분류
# ============================
def classify_disclosure(report_nm: str) -> tuple:
    """공시명 → (등급, 이벤트명, 예상영향) or None"""
    for keyword, grade, event_name, impact in EVENT_RULES:
        if keyword in report_nm:
            return grade, event_name, impact
    return None, None, None


# ============================
# 메인
# ============================
def main():
    today     = date.today()
    yesterday = today - timedelta(days=1)

    # 주말 처리: 월요일이면 금요일부터
    if today.weekday() == 0:
        yesterday = today - timedelta(days=3)

    bgn_de = yesterday.strftime("%Y%m%d")
    end_de = today.strftime("%Y%m%d")

    print(f"[Layer1.6] sfd_event_calendar_builder v2.0 START | {bgn_de}~{end_de}")

    if not DART_API_KEY:
        print("[Layer1.6] WARN: DART_API_KEY not found — creating empty event file and exiting")
        df_empty = pd.DataFrame(columns=[
            "rcept_dt", "corp_name", "ticker", "report_nm",
            "event_grade", "event_name", "event_impact", "event_score"
        ])
        df_empty.to_csv(EVENT_OUT, index=False, encoding="utf-8-sig")
        summary = {"as_of_date": str(today), "total": 0, "HIGH": 0, "MID": 0, "LOW": 0, "events": []}
        SUMMARY_OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[Layer1.6] Add DART_API_KEY to .env: DART_API_KEY=your_key")
        print("           발급: https://opendart.fss.or.kr/")
        return 0

    # 공시 수집
    items = fetch_dart_list(bgn_de, end_de)

    # 분류 및 필터링
    rows = []
    for item in items:
        report_nm = item.get("report_nm", "")
        grade, event_name, impact = classify_disclosure(report_nm)
        if grade is None:
            continue

        rows.append({
            "rcept_dt":     item.get("rcept_dt", ""),
            "corp_name":    item.get("corp_name", ""),
            "stock_code":   item.get("stock_code", "").zfill(6),
            "report_nm":    report_nm,
            "event_grade":  grade,
            "event_name":   event_name,
            "event_impact": impact,
            "event_score":  GRADE_SCORE[grade],
            "rcept_no":     item.get("rcept_no", ""),
            "dart_url":     f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.get('rcept_no', '')}",
        })

    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=[
        "rcept_dt", "corp_name", "stock_code", "report_nm",
        "event_grade", "event_name", "event_impact", "event_score", "rcept_no", "dart_url"
    ])

    # 등급 정렬
    grade_order = {"HIGH": 0, "MID": 1, "LOW": 2}
    if not df.empty:
        df["_order"] = df["event_grade"].map(grade_order)
        df = df.sort_values(["_order", "rcept_dt"], ascending=[True, False])
        df = df.drop(columns=["_order"])

    _LATEST.mkdir(parents=True, exist_ok=True)
    df.to_csv(EVENT_OUT, index=False, encoding="utf-8-sig")

    # 요약
    high_n = len(df[df["event_grade"] == "HIGH"]) if not df.empty else 0
    mid_n  = len(df[df["event_grade"] == "MID"]) if not df.empty else 0
    low_n  = len(df[df["event_grade"] == "LOW"]) if not df.empty else 0

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

    # 콘솔 출력
    print(f"\n[Layer1.6] Events detected: total {len(df)} (HIGH={high_n} / MID={mid_n} / LOW={low_n})")
    if not df.empty:
        for _, row in df[df["event_grade"] == "HIGH"].iterrows():
            print(f"  🔴 HIGH | {row['corp_name']}({row['stock_code']}) "
                  f"| {row['event_name']} | {row['event_impact']}")
            print(f"         | {row['dart_url']}")
        if mid_n > 0:
            print(f"  🟡 MID  | {mid_n}건 (sfd_event_calendar.csv 참조)")
    print(f"\n  → {EVENT_OUT}")
    print(f"  → {SUMMARY_OUT}")
    print("[Layer1.6] DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
