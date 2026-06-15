# fmp_coverage_test.py
import requests
env_path = r"D:\AI_WorkSpace\I_SFC\00_Local_Secrets\SFD\.env"
key = ""
with open(env_path, "r", encoding="utf-8") as f:
    for line in f:
        if "FMP_API_KEY" in line:
            key = line.split("=", 1)[1].strip()
            break
if not key:
    print("ERROR: FMP_API_KEY not found")
    exit(1)
print("KEY: " + key[:8] + "***")
samples = [("005930.KS","Samsung"),("000660.KS","SKHynix"),("035720.KQ","Kakao"),("051910.KS","LGChem"),("068270.KS","Celltrion")]
ok = 0
for sym, nm in samples:
    r = requests.get("https://financialmodelingprep.com/api/v3/ratios-ttm/"+sym, params={"apikey":key}, timeout=10).json()
    if r and isinstance(r,list) and len(r)>0:
        print("OK "+sym+" "+nm+" PER="+str(r[0].get("priceEarningsRatioTTM"))+" ROE="+str(r[0].get("returnOnEquityTTM")))
        ok+=1
    else:
        print("EMPTY "+sym+" "+nm)
print("Coverage: "+str(ok)+"/"+str(len(samples)))
