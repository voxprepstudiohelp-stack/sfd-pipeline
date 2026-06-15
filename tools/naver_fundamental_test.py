# naver_fundamental_test.py — 네이버 금융 모바일 API 재무지표 테스트
# Layer 2.6 데이터소스 최종 검증

import requests
import time

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://m.stock.naver.com/"
}

samples = [
    ("005930", "삼성전자"),
    ("000660", "SK하이닉스"),
    ("035720", "카카오"),
    ("051910", "LG화학"),
    ("068270", "셀트리온"),
]

ok_count = 0

for ticker, name in samples:
    url = f"https://m.stock.naver.com/api/stock/{ticker}/basic"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        d = r.json()

        per = d.get("per")
        pbr = d.get("pbr")
        eps = d.get("eps")
        roe = d.get("roe")
        market_cap = d.get("marketValue")

        print(f"  OK {ticker} {name}")
        print(f"     PER={per} | PBR={pbr} | EPS={eps} | ROE={roe} | market_cap={market_cap}")
        ok_count += 1
    except Exception as e:
        print(f"  ERROR {ticker} {name}: {e}")
    time.sleep(0.3)

print(f"\nCoverage: {ok_count}/{len(samples)} ({ok_count/len(samples)*100:.0f}%)")
print("\n[Raw response sample - Samsung Electronics]")
try:
    r = requests.get("https://m.stock.naver.com/api/stock/005930/basic", headers=HEADERS, timeout=10)
    import json
    print(json.dumps(r.json(), ensure_ascii=False, indent=2))
except Exception as e:
    print(f"ERROR: {e}")
