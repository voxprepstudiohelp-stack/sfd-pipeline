# debug_samsung.py — 삼성전자(005930) th 태그 전수 조사
import requests
from bs4 import BeautifulSoup

ticker = "005930"
url = f"https://finance.naver.com/item/main.naver?code={ticker}"
headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com/"}

r = requests.get(url, headers=headers, timeout=10)
r.encoding = "euc-kr"
soup = BeautifulSoup(r.text, "html.parser")

print(f"Samsung({ticker}) all th tags:")
print("=" * 80)

th_list = soup.find_all("th")
print(f"Total th tag count: {len(th_list)}\n")

for i, th in enumerate(th_list):
    th_text = th.get_text(strip=True)
    td = th.find_next_sibling("td")
    td_text = td.get_text(strip=True) if td else "N/A"
    
    print(f"[{i:2d}] th='{th_text[:50]:50s}' | td='{td_text[:30]:30s}'")
    
    if "PER" in th_text or "PBR" in th_text or "EPS" in th_text:
        print(f"      ↑ Financial indicator found!")

print("\n" + "=" * 80)
print("Conclusion: Is there a th tag containing PER?")
per_found = any("PER" in th.get_text() for th in th_list)
pbr_found = any("PBR" in th.get_text() for th in th_list)
print(f"PER: {per_found}, PBR: {pbr_found}")
