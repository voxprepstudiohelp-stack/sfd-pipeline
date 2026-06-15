# naver_fundamental_test2.py — 네이버 금융 재무지표 엔드포인트 탐색
import requests, json, time

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://m.stock.naver.com/"
}
TICKER = "005930"

endpoints = [
    f"https://m.stock.naver.com/api/stock/{TICKER}/investment",
    f"https://m.stock.naver.com/api/stock/{TICKER}/summary",
    f"https://m.stock.naver.com/api/stock/{TICKER}/finance",
]

for url in endpoints:
    print(f"\n{'='*50}")
    print(f"URL: {url}")
    print('='*50)
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        print(f"STATUS: {r.status_code}")
        if r.status_code == 200:
            print(json.dumps(r.json(), ensure_ascii=False, indent=2))
        else:
            print(r.text[:300])
    except Exception as e:
        print(f"ERROR: {e}")
    time.sleep(0.5)
