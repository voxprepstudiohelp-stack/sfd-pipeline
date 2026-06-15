# -*- coding: utf-8 -*-
"""
diag_naver_investor.py
용도: investor.naver 수급 파싱 실패 원인 진단
      - HTTP 상태 / 인코딩 확인
      - pd.read_html() 테이블 목록 출력
      - 외국인/기관/개인 컬럼 매칭 여부 확인
실행: python diag_naver_investor.py
작성: Claude (Anthropic) 2026-05-25
"""
import requests
import pandas as pd
from bs4 import BeautifulSoup

TICKER  = "005930"
URL     = f"https://finance.naver.com/item/investor.naver?code={TICKER}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
    "Referer":    "https://finance.naver.com/"
}

print(f"[DIAGNOSE] URL: {URL}")
print("=" * 60)

try:
    r = requests.get(URL, headers=HEADERS, timeout=10)
    print(f"[HTTP] status={r.status_code} | encoding={r.encoding} | size={len(r.text)}byte")

    # ── 1) pd.read_html 테이블 목록 ───────────────────────────
    print("\n[pd.read_html result]")
    try:
        tables = pd.read_html(r.text)
        print(f"  table count: {len(tables)}")
        for i, t in enumerate(tables):
            cols = list(t.columns)
            print(f"  [{i}] columns={cols[:6]} | rows={len(t)}")
            print(f"       head=\n{t.head(2)}\n")
    except Exception as e:
        print(f"  read_html ERROR: {e}")

    # ── 2) 키워드 매칭 확인 ───────────────────────────────────
    print("=" * 60)
    print("[foreign/institution/individual keyword matching]")
    r.encoding = "euc-kr"
    soup = BeautifulSoup(r.text, "html.parser")
    keywords = ["외국인", "기관", "개인", "순매수", "investor"]
    for kw in keywords:
        found = [tag.get_text(strip=True) for tag in soup.find_all(string=lambda t: t and kw in t)]
        if found:
            print(f"  '{kw}' found: {found[:3]}")
        else:
            print(f"  '{kw}' not found <- parsing failure candidate")

    # ── 3) 응답 HTML 앞부분 확인 ─────────────────────────────
    print("\n" + "=" * 60)
    print("[response HTML first 500 chars]")
    print(r.text[:500])

except Exception as e:
    print(f"[ERROR] fetch FAIL: {e}")