# diag_naver_investor.py 내용 교체
import requests

TICKER  = "005930"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com/"}

urls = [
    f"https://finance.naver.com/item/sise_investor.naver?code={TICKER}",
    f"https://finance.naver.com/item/frgn.naver?code={TICKER}",
    f"https://m.stock.naver.com/api/stock/{TICKER}/investorTrend",
    f"https://m.stock.naver.com/api/stock/{TICKER}/investorSise",
    f"https://m.stock.naver.com/api/stock/{TICKER}/foreigner",
]

for url in urls:
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        preview = r.text[:150].replace("\n","")
        print(f"[{r.status_code}] {url.split('naver.com')[1]}")
        if r.status_code == 200:
            print(f"  → {preview}\n")
    except Exception as e:
        print(f"[ERR] → {e}")