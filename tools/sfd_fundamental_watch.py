"""
sfd_fundamental_watch.py — Layer 2.6 v1.1_FIX
수정사항:
  1. r.content.decode("euc-kr") 명시적 처리 (r.encoding 설정 방식 제거)
  2. "PER(배)" 정확 매칭 → 길이/조건 기반 매칭으로 변경 (인코딩 안전)
  3. exception 시 에러 출력 추가 (디버깅용)
"""

import os, sys, time, requests, pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime, date

PIPELINE_ROOT = r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline"
OUTPUTS_DIR   = os.path.join(PIPELINE_ROOT, "outputs", "latest")
MAX_TICKERS   = 200
RATE_DELAY    = 0.2

HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com/"}

def safe_float(v):
    if v is None: return None
    try:
        return float(str(v).replace(",", "").replace("배", "").replace("원", "").strip())
    except: return None

def calc_per_score(per) -> int:
    if per is None or per <= 0: return 0
    if per <= 8:  return 30
    if per <= 15: return 20
    if per <= 25: return 10
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
    if per <= 8:  return "CHEAP"
    if per <= 15: return "FAIR"
    if per <= 25: return "PREMIUM"
    return "EXPENSIVE"

def get_pbr_grade(pbr) -> str:
    if pbr is None or pbr <= 0: return "N/A"
    if pbr <= 0.8: return "UNDERVALUE"
    if pbr <= 1.5: return "FAIR"
    if pbr <= 2.5: return "PREMIUM"
    return "EXPENSIVE"

def fetch_naver_fundamental(ticker: str) -> dict:
    """
    [핵심 수정] r.content.decode("euc-kr") 명시적 처리
    "PER(배)" 직접 비교 대신 길이/조건 기반 안전 매칭 사용
    
    debug_samsung.py 검증 결과:
      [47] EPS(원)  → len<=8, "EPS" in, "l" not in
      [48] PER(배)  → len<=8, "PER" in, "%" not in, "l" not in
      [50] PBR(배)  → len<=8, "PBR" in, "l" not in
      [83] PERlEPS(2026.03)... → "PERlEPS" in, "추정" not in
      [84] 추정PERlEPS...       → "추정PER" in, "lEPS" in
    """
    url = f"https://finance.naver.com/item/main.naver?code={ticker}"
    result = {"per": None, "pbr": None, "eps": None, "est_per": None}

    try:
        r = requests.get(url, headers=HEADERS, timeout=5)

        # ── 핵심 수정: 명시적 euc-kr 디코딩 ──
        text = r.content.decode("euc-kr", errors="replace")
        soup = BeautifulSoup(text, "html.parser")

        for th in soup.find_all("th"):
            th_text = th.get_text(strip=True)
            td = th.find_next_sibling("td")
            if not td:
                continue
            td_text = td.get_text(strip=True)

            # PER(배): len<=8, "PER" 포함, "%" 미포함, "l" 미포함
            if (result["per"] is None
                    and "PER" in th_text
                    and len(th_text) <= 8
                    and "%" not in th_text
                    and "l" not in th_text):
                result["per"] = safe_float(td_text)

            # PBR(배): len<=8, "PBR" 포함, "l" 미포함
            if (result["pbr"] is None
                    and "PBR" in th_text
                    and len(th_text) <= 8
                    and "l" not in th_text):
                result["pbr"] = safe_float(td_text)

            # EPS(원): len<=8, "EPS" 포함, "l" 미포함
            if (result["eps"] is None
                    and "EPS" in th_text
                    and len(th_text) <= 8
                    and "l" not in th_text):
                result["eps"] = safe_float(td_text)

            # PERlEPS(연간): "PERlEPS" 포함, "추정" 미포함
            if ("PERlEPS" in th_text
                    and "추정" not in th_text):
                parts = td_text.split("l")
                if len(parts) >= 2:
                    if result["per"] is None:
                        result["per"] = safe_float(parts[0])
                    if result["eps"] is None:
                        result["eps"] = safe_float(parts[1])

            # 추정PERlEPS
            if "추정PER" in th_text and "lEPS" in th_text:
                parts = td_text.split("l")
                if len(parts) >= 1:
                    result["est_per"] = safe_float(parts[0])

    except Exception as e:
        # v1.1: 에러 출력 추가 (디버깅용)
        print(f"  [WARN] {ticker} fetch error: {e}")

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
    print(f"[Layer 2.6] {datetime.now():%Y-%m-%d %H:%M:%S} (MAX={MAX_TICKERS})")
    print(f"{'='*60}\n")

    target_df = load_target_tickers()
    total = len(target_df)
    records, ok, fail = [], 0, 0

    for idx, (_, row) in enumerate(target_df.iterrows(), 1):
        ticker = row["ticker"]
        name   = row.get("name", "")

        data = fetch_naver_fundamental(ticker)
        time.sleep(RATE_DELAY)

        per, pbr, eps, est_per = data["per"], data["pbr"], data["eps"], data["est_per"]

        if not any(v is not None for v in [per, pbr, eps]):
            fail += 1
            if fail <= 10 or idx % 20 == 0:
                print(f"  [{idx:3d}] SKIP {ticker}")
            continue

        ok += 1
        per_s   = calc_per_score(per)
        pbr_s   = calc_pbr_score(pbr)
        eps_s   = calc_eps_score(eps)
        f_score = per_s + pbr_s + eps_s

        records.append({
            "ticker": ticker, "name": name,
            "per": per, "pbr": pbr, "eps": eps, "est_per": est_per,
            "per_grade": get_per_grade(per), "pbr_grade": get_pbr_grade(pbr),
            "fundamental_score": f_score,
            "fetch_date": date.today().isoformat(),
        })

        if ok <= 20 or ok % 10 == 0:
            print(f"  [{idx:3d}] ✅ {ticker} {name:12s} | PER={per} PBR={pbr} | {f_score:3d}pt")

    print(f"\n{'='*60}")
    print(f"[결과] ✅{ok} | ❌{fail} | 커버리지 {ok/total*100:.1f}%")
    print(f"{'='*60}\n")

    if records:
        out_df   = pd.DataFrame(records)
        out_path = os.path.join(OUTPUTS_DIR, "sfd_fundamental_latest.csv")
        out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"✅ {out_path}\n")

if __name__ == "__main__":
    run()
