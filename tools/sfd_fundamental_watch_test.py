"""
sfd_fundamental_watch.py — Layer 2.6 TEST
MAX_TICKERS=10 + timeout 5s + rate_delay 0.2s
빠른 테스트용 (약 10초 완료)
"""

import os, sys, time, requests, pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime, date

PIPELINE_ROOT = r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline"
OUTPUTS_DIR   = os.path.join(PIPELINE_ROOT, "outputs", "latest")
MAX_TICKERS   = 10  # 테스트용 (빠른 확인)
RATE_DELAY    = 0.2  # 0.5 → 0.2 (속도 향상)

HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com/"}

def safe_float(v):
    try:
        if v is None: return None
        return float(str(v).replace(",", "").replace("배", "").replace("원", "").strip())
    except:
        return None

def calc_per_score(per) -> int:
    if per is None or per <= 0: return 0
    if per <= 8:   return 30
    if per <= 15:  return 20
    if per <= 25:  return 10
    return 0

def calc_pbr_score(pbr) -> int:
    if pbr is None or pbr <= 0: return 0
    if pbr <= 0.8: return 40
    if pbr <= 1.5: return 30
    if pbr <= 2.5: return 15
    return 0

def calc_eps_score(eps) -> int:
    if eps is None: return 0
    if eps >= 10000: return 30
    if eps >= 5000:  return 20
    if eps >= 1000:  return 10
    if eps > 0:      return 5
    return 0

def get_per_grade(per) -> str:
    if per is None or per <= 0: return "NEGATIVE"
    if per <= 8:   return "CHEAP"
    if per <= 15:  return "FAIR"
    if per <= 25:  return "PREMIUM"
    return "EXPENSIVE"

def get_pbr_grade(pbr) -> str:
    if pbr is None or pbr <= 0: return "N/A"
    if pbr <= 0.8: return "UNDERVALUE"
    if pbr <= 1.5: return "FAIR"
    if pbr <= 2.5: return "PREMIUM"
    return "EXPENSIVE"

def fetch_naver_fundamental(ticker: str) -> dict:
    url = f"https://finance.naver.com/item/main.naver?code={ticker}"
    result = {"per": None, "pbr": None, "eps": None, "est_per": None}
    try:
        r = requests.get(url, headers=HEADERS, timeout=5)  # 10s → 5s
        r.encoding = "euc-kr"
        soup = BeautifulSoup(r.text, "html.parser")

        per_found, pbr_found, eps_found = False, False, False

        for th in soup.find_all("th"):
            th_text = th.get_text(strip=True)
            td = th.find_next_sibling("td")
            if not td: continue
            td_text = td.get_text(strip=True)

            if "PER(배)" in th_text and not per_found:
                result["per"] = safe_float(td_text)
                per_found = True
            elif "PBR(배)" in th_text and not pbr_found:
                result["pbr"] = safe_float(td_text)
                pbr_found = True

        for th in soup.find_all("th"):
            th_text = th.get_text(strip=True)
            td = th.find_next_sibling("td")
            if not td: continue
            td_text = td.get_text(strip=True)

            if "PERlEPS" in th_text and not eps_found:
                parts = td_text.split("l")
                if len(parts) >= 2:
                    result["per"] = safe_float(parts[0])
                    result["eps"] = safe_float(parts[1])
                    eps_found = True
            elif "추정PERlEPS" in th_text:
                parts = td_text.split("l")
                if len(parts) >= 1:
                    result["est_per"] = safe_float(parts[0])

    except requests.Timeout:
        print(f"  [TIMEOUT] {ticker}")
    except Exception as e:
        print(f"  [ERROR] {ticker}: {type(e).__name__}")

    return result

def load_target_tickers() -> pd.DataFrame:
    master_path = os.path.join(OUTPUTS_DIR, "sfd_master_signal_latest.csv")
    if not os.path.exists(master_path):
        print(f"[ERROR] {master_path}")
        sys.exit(1)
    df = pd.read_csv(master_path, dtype={"ticker": str})
    df["ticker"] = df["ticker"].astype(str).str.zfill(6)
    if "total_score" in df.columns:
        df["total_score"] = pd.to_numeric(df["total_score"], errors="coerce")
        df = df.sort_values("total_score", ascending=False)
    return df[["ticker", "name"]].drop_duplicates().head(MAX_TICKERS).reset_index(drop=True)

def run():
    print(f"\n{'='*60}")
    print(f"[Layer 2.6] TEST (MAX_TICKERS={MAX_TICKERS}) — {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"{'='*60}\n")

    target_df = load_target_tickers()
    total = len(target_df)
    print(f"[INFO] Target: {total} tickers\n")

    records, ok, fail = [], 0, 0

    for idx, (_, row) in enumerate(target_df.iterrows(), 1):
        ticker = row["ticker"]
        name = row.get("name", "")
        print(f"  [{idx:2d}/{total}] {ticker} {name:15s} ... ", end="", flush=True)
        
        data = fetch_naver_fundamental(ticker)
        time.sleep(RATE_DELAY)

        per, pbr, eps, est_per = data["per"], data["pbr"], data["eps"], data["est_per"]
        
        if not any(v is not None for v in [per, pbr, eps]):
            fail += 1
            print("SKIP (no data)")
            continue

        ok += 1
        per_s = calc_per_score(per)
        pbr_s = calc_pbr_score(pbr)
        eps_s = calc_eps_score(eps)
        f_score = per_s + pbr_s + eps_s

        records.append({
            "ticker": ticker, "name": name, "per": per, "pbr": pbr, "eps": eps, "est_per": est_per,
            "per_grade": get_per_grade(per), "pbr_grade": get_pbr_grade(pbr),
            "fundamental_score": f_score, "fetch_date": date.today().isoformat(),
        })
        
        print(f"OK | PER={per:7.2f} PBR={pbr:6.2f} EPS={eps:8.0f} | {f_score:3d}pt")

    print(f"\n{'='*60}")
    print(f"[RESULT] collected:{ok} | failed:{fail} | total:{total}")
    print(f"{'='*60}\n")

    if records:
        out_df = pd.DataFrame(records)
        out_path = os.path.join(OUTPUTS_DIR, "sfd_fundamental_latest.csv")
        out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"✅ {out_path} saved ({len(out_df)} rows)")

        report = os.path.join(OUTPUTS_DIR, "sfd_fundamental_coverage_report.txt")
        with open(report, "w", encoding="utf-8") as f:
            f.write(f"Coverage — {date.today()}\n")
            f.write(f"대상:{total} | 수집:{ok} | 실패:{fail}\n")
            f.write(f"커버리지: {ok/total*100:.1f}%\n")
        print(f"✅ {report} saved\n")

if __name__ == "__main__":
    run()
