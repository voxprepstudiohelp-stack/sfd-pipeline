# naver_fundamental_test3.py — 네이버 금융 PC 페이지 파싱 + API 추가 탐색
import requests, json, time
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
    "Referer": "https://finance.naver.com/"
}
TICKER = "005930"

# ─── TEST 1: PC 네이버 금융 메인 페이지 BeautifulSoup 파싱
print("=" * 50)
print("[TEST 1] finance.naver.com main page parsing")
print("=" * 50)
try:
    url = f"https://finance.naver.com/item/main.naver?code={TICKER}"
    r = requests.get(url, headers=HEADERS, timeout=10)
    soup = BeautifulSoup(r.text, "html.parser")

    # PER, EPS, PBR 위치: .per_spec 또는 table.tab_con1
    per_area = soup.select(".per_spec")
    if per_area:
        print("per_spec found:")
        for el in per_area:
            print(" ", el.get_text(strip=True))
    else:
        print("per_spec not found - searching other selectors")
        # em 태그 중 숫자값 탐색
        em_tags = soup.select("em.blind")
        for em in em_tags[:20]:
            print(" em.blind:", em.get_text())

    # table 내 PER 탐색
    for th in soup.find_all("th"):
        if "PER" in th.get_text() or "PBR" in th.get_text():
            td = th.find_next_sibling("td")
            print(f"  [{th.get_text(strip=True)}] = {td.get_text(strip=True) if td else 'N/A'}")
except Exception as e:
    print(f"ERROR: {e}")

time.sleep(0.5)

# ─── TEST 2: polling API (실시간 + 기본지표)
print()
print("=" * 50)
print("[TEST 2] polling.finance.naver.com")
print("=" * 50)
try:
    url2 = f"https://polling.finance.naver.com/api/realtime/domestic/stock/{TICKER}"
    r2 = requests.get(url2, headers=HEADERS, timeout=10)
    print(f"STATUS: {r2.status_code}")
    if r2.status_code == 200:
        print(json.dumps(r2.json(), ensure_ascii=False, indent=2)[:2000])
except Exception as e:
    print(f"ERROR: {e}")

time.sleep(0.5)

# ─── TEST 3: 네이버 금융 coinfo (재무 요약)
print()
print("=" * 50)
print("[TEST 3] coinfo finsum_more")
print("=" * 50)
try:
    url3 = f"https://finance.naver.com/item/coinfo.naver?code={TICKER}&target=finsum_more"
    r3 = requests.get(url3, headers=HEADERS, timeout=10)
    print(f"STATUS: {r3.status_code}")
    soup3 = BeautifulSoup(r3.text, "html.parser")
    tables = soup3.find_all("table")
    print(f"table count: {len(tables)}")
    for i, tbl in enumerate(tables[:3]):
        print(f"\n--- table[{i}] ---")
        for row in tbl.find_all("tr")[:5]:
            cols = [td.get_text(strip=True) for td in row.find_all(["th","td"])]
            if any(cols):
                print(" | ".join(cols))
except Exception as e:
    print(f"ERROR: {e}")
