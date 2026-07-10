# generate_briefing.py v1.0
# 목적: Gemini 2.5 Pro로 글로벌/국내 정세 브리핑 생성
# 위치: sfd-pipeline/scripts/generate_briefing.py
# 출력: dashboard/data/sfd_briefing.json

import os
import json
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
NOW = datetime.now(KST)

_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = _ROOT / "dashboard" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_FILE = OUT_DIR / "sfd_briefing.json"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-pro:generateContent"
)

PROMPT = f"""당신은 한국 주식시장 전문 애널리스트입니다.
현재 시각: {NOW.strftime('%Y-%m-%d %H:%M KST')}

다음 형식으로 한국 주식시장 투자자를 위한 글로벌/국내 정세 브리핑을 작성하세요.
각 섹션은 2~3문장으로 간결하게 작성하고, 반드시 아래 JSON 형식으로만 응답하세요.

{{
  "generated_at": "{NOW.isoformat()}",
  "generated_at_kst": "{NOW.strftime('%Y-%m-%d %H:%M KST')}",
  "sections": [
    {{
      "id": "global_macro",
      "title": "글로벌 거시경제",
      "content": "미국 연준 통화정책, 달러 강약, 국제 금리 동향 등 핵심 내용 2~3문장",
      "impact": "positive|negative|neutral",
      "impact_reason": "코스피/한국 주식에 미치는 영향 1문장"
    }},
    {{
      "id": "us_market",
      "title": "미국 증시 동향",
      "content": "나스닥/S&P500 주요 흐름, 빅테크/반도체 동향 2~3문장",
      "impact": "positive|negative|neutral",
      "impact_reason": "영향 1문장"
    }},
    {{
      "id": "geopolitics",
      "title": "지정학적 리스크",
      "content": "중동, 러-우, 미중 관계, 한반도 등 주요 지정학 이슈 2~3문장",
      "impact": "positive|negative|neutral",
      "impact_reason": "영향 1문장"
    }},
    {{
      "id": "korea_domestic",
      "title": "국내 경제/정치",
      "content": "한국 경제지표, 정책, 환율, 내수 동향 2~3문장",
      "impact": "positive|negative|neutral",
      "impact_reason": "영향 1문장"
    }},
    {{
      "id": "sector_watch",
      "title": "주목 섹터",
      "content": "오늘 주목할 한국 주식 섹터 및 테마 (전력/원전/반도체 등) 2~3문장",
      "impact": "positive|negative|neutral",
      "impact_reason": "영향 1문장"
    }}
  ],
  "one_line_summary": "오늘 한국 증시를 한 문장으로 요약",
  "model": "gemini-2.5-pro"
}}

반드시 유효한 JSON만 출력하고 다른 텍스트는 포함하지 마세요."""

def call_gemini():
    if not GEMINI_API_KEY:
        print("[ERROR] GEMINI_API_KEY 없음")
        return None
    headers = {"Content-Type": "application/json"}
    body = {
        "contents": [{"parts": [{"text": PROMPT}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2048}
    }
    try:
        resp = requests.post(f"{GEMINI_URL}?key={GEMINI_API_KEY}", headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())
    except Exception as e:
        print(f"[ERROR] Gemini 호출 실패: {e}")
        return None

def fallback_briefing():
    return {
        "generated_at": NOW.isoformat(),
        "generated_at_kst": NOW.strftime("%Y-%m-%d %H:%M KST"),
        "sections": [],
        "one_line_summary": "브리핑 생성 실패 — Gemini API 연결을 확인하세요",
        "model": "fallback",
        "error": True
    }

def main():
    print(f"[generate_briefing] 시작: {NOW.strftime('%Y-%m-%d %H:%M KST')}")
    result = call_gemini()
    if not result:
        result = fallback_briefing()
    else:
        print(f"[OK] 완료: {result.get('one_line_summary', '')[:50]}")
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[OK] 저장: {OUT_FILE}")

if __name__ == "__main__":
    main()
