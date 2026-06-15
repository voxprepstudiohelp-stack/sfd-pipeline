# fmp_test.py — FMP 한국주식 커버리지 사전 테스트
# Layer 2.6 착수 전 실행 필수

import requests

# .env에서 FMP_API_KEY 읽기
env_path = r"D:\AI_WorkSpace\I_SFC\00_Local_Secrets\SFD\.env"
key = ""
with open(env_path, "r") as f:
    for line in f:
        if "FMP_API_KEY" in line:
            key = line.split("=", 1)[1].strip()
            break

if not key:
    print("[ERROR] FMP_API_KEY not found in .env.")
    exit(1)

print(f"FMP KEY check: {key[:8]}***\n")

samples = [
    ("005930", "005930.KS", "삼성전자"),
    ("000660", "000660.KS", "SK하이닉스"),
    ("035720", "035720.KQ", "카카오(KQ)"),
    ("051910", "051910.KS", "LG화학"),
    ("068270", "068270.KS", "셀트리온"),
]

ok_count = 0
for ticker, symbol, name in samples:
    r = requests.get(
        f"https://financialmodelingprep.com/api/v3/ratios-ttm/{symbol}",
        params={"apikey": key},
        timeout=10
    ).json()
    if r and isinstance(r, list) and len(r) > 0:
        per = r[0].get("priceEarningsRatioTTM")
        roe = r[0].get("returnOnEquityTTM")
        pbr = r[0].get("priceToBookRatioTTM")
        print(f"  ✅ {symbol} {name} | PER={per} ROE={roe} PBR={pbr}")
        ok_count += 1
    else:
        print(f"  ❌ {symbol} {name} | no data")

print(f"\nCoverage: {ok_count}/{len(samples)} ({ok_count/len(samples)*100:.0f}%)")
