# kiwoom_diagnose2.py - 키움 REST API 정확한 엔드포인트/TR ID 진단
# URL: /api/dostk/acnt, Method: POST, 헤더에 api-id 필요
import requests, os, json
from dotenv import load_dotenv

load_dotenv(".env")
APP_KEY    = os.getenv("KIWOOM_APP_KEY")
SECRET_KEY = os.getenv("KIWOOM_SECRET_KEY")
ACCOUNT_NO = os.getenv("KIWOOM_ACCOUNT_NO", "").replace("-", "")

BASE_URL = "https://api.kiwoom.com"

# 토큰 발급
r = requests.post(
    f"{BASE_URL}/oauth2/token",
    headers={"Content-Type": "application/json;charset=UTF-8"},
    json={"grant_type": "client_credentials", "appkey": APP_KEY, "secretkey": SECRET_KEY}
)
token = r.json().get("token")
print(f"TOKEN: {token[:20] if token else 'FAIL'}")
if not token:
    exit()

def call(api_id, url_path, body):
    hdrs = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "secretkey": SECRET_KEY,
        "api-id": api_id,
    }
    resp = requests.post(f"{BASE_URL}{url_path}", headers=hdrs, json=body, timeout=10)
    tag = "[OK]" if resp.status_code == 200 else "[NG]"
    try:
        body_preview = json.dumps(resp.json(), ensure_ascii=False)[:200]
    except Exception:
        body_preview = resp.text[:200]
    print(f"{tag} api-id={api_id} => {resp.status_code}: {body_preview}")
    return resp

print("\n--- /api/dostk/acnt account-related TR ID diagnosis ---")

# 주식잔고 관련 TR ID 후보
tests = [
    # (api_id, url_path, body)
    ("ka01690", "/api/dostk/acnt", {"qry_dt": "20260529"}),                         # 일별잔고수익률
    ("ka10072", "/api/dostk/acnt", {"acnt_no": ACCOUNT_NO, "qry_tp": "1"}),         # 주식잔고2
    ("ka10073", "/api/dostk/acnt", {"acnt_no": ACCOUNT_NO}),                        # 주식잔고3
    ("ka10074", "/api/dostk/acnt", {"acnt_no": ACCOUNT_NO, "qry_tp": "1"}),         # 주식잔고
    ("ka10085", "/api/dostk/acnt", {"acnt_no": ACCOUNT_NO}),                        # 계좌수익률현황
    ("ka10170", "/api/dostk/acnt", {"acnt_no": ACCOUNT_NO}),                        # 계좌평가잔고
    ("ka10172", "/api/dostk/acnt", {"acnt_no": ACCOUNT_NO, "qry_tp": "1"}),
    ("ka10200", "/api/dostk/acnt", {"acnt_no": ACCOUNT_NO}),
    # 다른 엔드포인트
    ("ka10072", "/api/dostk/acnt", {"acnt_no": ACCOUNT_NO, "qry_tp": "2"}),
    ("ka10074", "/api/dostk/acnt", {"acnt_no": ACCOUNT_NO, "qry_tp": "2", "stex_tp": "3"}),
]

ok_list = []
for api_id, url_path, body in tests:
    resp = call(api_id, url_path, body)
    if resp.status_code == 200:
        ok_list.append((api_id, url_path, body, resp.json()))

print(f"\n--- OK {len(ok_list)} results detail ---")
for api_id, url_path, body, result in ok_list:
    print(f"\n[api-id={api_id}]")
    print(json.dumps(result, ensure_ascii=False, indent=2)[:500])
