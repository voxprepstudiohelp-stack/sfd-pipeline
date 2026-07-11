"""
sfd_investor_flow_fetch.py v2.3
investor_flow 수집 -- KIS Developers API (Primary) / Fail-Safe (0)
[v2.3] signal_file: sfd_master_signal_latest.csv → sfd_master_signal_input.csv (항상 존재)

[v2.1 → v2.2 → v2.3 변경사항]
- APP_KEY/APP_SECRET: os.environ 우선 읽기 + .env fallback
  (GitHub Actions Secret 주입 대응 — .env 파일 없는 환경에서도 작동)
"""
import os, time, datetime, requests, csv
from pathlib import Path

BASE_DIR   = Path(__file__).resolve().parent.parent
ENV_FILE   = BASE_DIR / ".env"
OUTPUT_DIR = BASE_DIR / "outputs" / "latest"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def load_env(path):
    env = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

ENV = load_env(ENV_FILE)

# [v2.2] os.environ 우선, .env fallback — GitHub Actions Secret 대응
APP_KEY    = os.environ.get("KIS_APP_KEY")    or ENV.get("KIS_APP_KEY", "")
APP_SECRET = os.environ.get("KIS_APP_SECRET") or ENV.get("KIS_APP_SECRET", "")
BASE_URL   = "https://openapi.koreainvestment.com:9443"

def get_access_token():
    if not APP_KEY or not APP_SECRET:
        print("[WARN] KIS key not set -> Fail-Safe mode")
        return ""
    url  = BASE_URL + "/oauth2/tokenP"
    body = {"grant_type": "client_credentials",
            "appkey": APP_KEY, "appsecret": APP_SECRET}
    try:
        r = requests.post(url, json=body, timeout=30)
        r.raise_for_status()
        token = r.json().get("access_token", "")
        print("[OK] KIS token issued OK (first 20 chars: " + token[:20] + "...)")
        return token
    except Exception as e:
        print("[FAIL] Token issue FAIL: " + str(e))
        return ""

def fetch_investor(token, ticker):
    if not token:
        return {"foreign_net_buy": 0, "institution_net_buy": 0,
                "individual_net_buy": 0, "pension_net_buy": 0,
                "data_status": "FAIL"}
    url = BASE_URL + "/uapi/domestic-stock/v1/quotations/inquire-investor"
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": "Bearer " + token,
        "appkey":    APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id":     "FHKST01010900",
        "custtype":  "P",
    }
    params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": ticker}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        r.raise_for_status()
        out = r.json().get("output", [{}])
        if not out:
            return {"foreign_net_buy": 0, "institution_net_buy": 0,
                    "individual_net_buy": 0, "pension_net_buy": 0,
                    "data_status": "EMPTY"}
        row = out[0] if isinstance(out, list) else out
        f       = int(row.get("frgn_ntby_qty",  0) or 0)
        i       = int(row.get("orgn_ntby_qty",  0) or 0)
        p       = int(row.get("indv_ntby_qty",  0) or 0)
        pension = int(row.get("pnsn_ntby_qty",  0) or 0)
        status = "OK" if any([f, i, p, pension]) else "ZERO"
        return {"foreign_net_buy": f, "institution_net_buy": i,
                "individual_net_buy": p, "pension_net_buy": pension,
                "data_status": status}
    except Exception as e:
        return {"foreign_net_buy": 0, "institution_net_buy": 0,
                "individual_net_buy": 0, "pension_net_buy": 0,
                "data_status": "FAIL"}

def load_tickers():
    # [v2.4] 경로 우선순위: inputs/ → outputs/latest/ (input) → outputs/latest/ (latest)
    candidates = [
        BASE_DIR / "inputs"          / "sfd_master_signal_input.csv",
        BASE_DIR / "outputs" / "latest" / "sfd_master_signal_input.csv",
        BASE_DIR / "outputs" / "latest" / "sfd_master_signal_latest.csv",
    ]
    signal_file = next((p for p in candidates if p.exists()), None)
    if signal_file is None:
        print("[WARN] signal input file not found (tried: inputs/, outputs/latest/)")
        return []
    print(f"[INFO] ticker source: {signal_file}")
    tickers, seen = [], set()
    with open(signal_file, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            t = row.get("ticker", "").strip()
            if t and t not in seen:
                tickers.append(t)
                seen.add(t)
    return tickers

def main():
    today    = datetime.date.today().strftime("%Y-%m-%d")
    out_file = OUTPUT_DIR / "sfd_investor_flow_latest.csv"
    print("=" * 55)
    print("[investor_flow v2.3] " + today)
    print("=" * 55)

    token   = get_access_token()
    tickers = load_tickers()

    if not tickers:
        print("[WARN] No tickers found. Creating empty file.")
        with open(out_file, "w", newline="", encoding="utf-8-sig") as f:
            f.write("ticker,foreign_net_buy,institution_net_buy,individual_net_buy,pension_net_buy,fetch_date,data_status\n")
        return

    print("[INFO] Target tickers: " + str(len(tickers)) + " total")
    rows, ok_cnt = [], 0
    for i, ticker in enumerate(tickers):
        res = fetch_investor(token, ticker)
        rows.append({"ticker":              ticker,
                     "foreign_net_buy":     res["foreign_net_buy"],
                     "institution_net_buy": res["institution_net_buy"],
                     "individual_net_buy":  res["individual_net_buy"],
                     "pension_net_buy":     res["pension_net_buy"],
                     "fetch_date":          today,
                     "data_status":         res["data_status"]})
        if res["data_status"] == "OK":
            ok_cnt += 1
        if (i + 1) % 50 == 0:
            print(" ... " + str(i+1) + "/" + str(len(tickers)) + " processing (OK: " + str(ok_cnt) + ")")
        time.sleep(0.05)

    with open(out_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "ticker","foreign_net_buy","institution_net_buy",
            "individual_net_buy","pension_net_buy","fetch_date","data_status"])
        writer.writeheader()
        writer.writerows(rows)

    fail = sum(1 for r in rows if r["data_status"] == "FAIL")
    zero = sum(1 for r in rows if r["data_status"] == "ZERO")
    print("\n[RESULT] " + str(out_file))
    print(" OK   : " + str(ok_cnt) + " records")
    print(" ZERO : " + str(zero) + " records (API OK, no trades today)")
    print(" FAIL : " + str(fail) + " records")
    print(" TOTAL: " + str(len(rows)) + " records")

if __name__ == "__main__":
    main()
