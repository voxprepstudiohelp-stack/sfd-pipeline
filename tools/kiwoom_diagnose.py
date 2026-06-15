# kiwoom_diagnose.py - 키움 REST API 잔고조회 엔드포인트 진단
import requests, os
from dotenv import load_dotenv

load_dotenv(".env")
APP_KEY    = os.getenv("KIWOOM_APP_KEY")
SECRET_KEY = os.getenv("KIWOOM_SECRET_KEY")
ACCOUNT_NO = os.getenv("KIWOOM_ACCOUNT_NO", "").replace("-", "")

# 토큰 발급
r = requests.post(
    "https://api.kiwoom.com/oauth2/token",
    headers={"Content-Type": "application/json;charset=UTF-8"},
    json={"grant_type": "client_credentials", "appkey": APP_KEY, "secretkey": SECRET_KEY}
)
token = r.json().get("token")
print(f"TOKEN: {token[:20] if token else 'FAIL'}")
if not token:
    exit()

hdrs = {
    "authorization": f"Bearer {token}",
    "appkey": APP_KEY,
    "secretkey": SECRET_KEY,
    "Content-Type": "application/json;charset=UTF-8",
}

# 파라미터 키명 후보 x 엔드포인트 후보 전수 테스트
tests = [
    ("GET",  "https://api.kiwoom.com/v1/account/balance",      {"acnt_no": ACCOUNT_NO}),
    ("GET",  "https://api.kiwoom.com/v1/account/balance",      {"acnt_no": ACCOUNT_NO, "qry_tp": "1"}),
    ("GET",  "https://api.kiwoom.com/v1/account/balance",      {"account_no": ACCOUNT_NO}),
    ("POST", "https://api.kiwoom.com/v1/account/balance",      {"acnt_no": ACCOUNT_NO}),
    ("POST", "https://api.kiwoom.com/v1/account/balance",      {"acnt_no": ACCOUNT_NO, "qry_tp": "1"}),
    ("GET",  "https://api.kiwoom.com/v1/account/stockbalance", {"acnt_no": ACCOUNT_NO}),
    ("GET",  "https://api.kiwoom.com/v1/account/stockbalance", {"acnt_no": ACCOUNT_NO, "qry_tp": "1"}),
    ("POST", "https://api.kiwoom.com/v1/account/stockbalance", {"acnt_no": ACCOUNT_NO}),
    ("GET",  "https://api.kiwoom.com/v1/tradebook/balance",    {"acnt_no": ACCOUNT_NO}),
    ("POST", "https://api.kiwoom.com/v1/tradebook/balance",    {"acnt_no": ACCOUNT_NO}),
]

print("\n--- DIAGNOSE START ---")
for method, url, params in tests:
    try:
        if method == "GET":
            resp = requests.get(url, headers=hdrs, params=params, timeout=5)
        else:
            resp = requests.post(url, headers=hdrs, json=params, timeout=5)
        tag = "OK" if resp.status_code == 200 else "NG"
        print(f"[{tag}] {method} {url.split('kiwoom.com')[1]} {list(params.keys())} => {resp.status_code}: {resp.text[:120]}")
    except Exception as e:
        print(f"[ERR] {method} {url} => {e}")
