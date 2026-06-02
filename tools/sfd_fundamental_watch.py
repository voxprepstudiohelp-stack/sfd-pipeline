# -*- coding: utf-8 -*-
"""
sfd_fundamental_watch.py — Layer 2.6
기능: 상위 200종목 PER/PBR/EPS 수집 + 펀더멘털 스코어 산출
출처: finance.naver.com (BeautifulSoup 파싱)
버전: v1.6 | 2026-06-03

[v1.4 → v1.6 변경점]
- load_target_tickers(): stock_code/ticker 컬럼 양립 지원 (KeyError: 'ticker' 완전 해소)
- 출력 파일명: sfd_fundamental_latest.csv → sfd_fundamental_watch_latest.csv (aggregator 기대값 통일)
- fund_score 컬럼 추가 (aggregator v3.x 참조용 = fundamental_score 동일값)
- name 컬럼 탐지 로직 강화 (name/corp_name/회사명 fallback)
"""

import os
import re
import sys
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime, date

# ── 경로 설정 (__file__ 기반, config.py 불필요) ──────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUTS_DIR = os.environ.get("SFD_BASE_DIR",
              os.path.join(BASE_DIR, "outputs", "latest"))
OUTPUTS_DIR = os.path.join(OUTPUTS_DIR, "outputs", "latest") \
              if not OUTPUTS_DIR.endswith("latest") else OUTPUTS_DIR

# Phase 2-B: company_master CSV 경로
SFC_ROOT = os.path.dirname(os.path.dirname(BASE_DIR))
COMPANY_MASTER_CSV = os.path.join(
    SFC_ROOT, "01_DB", "sfd_company_master_v1.4_with_financials.csv")

# sector_priority 모듈 임포트
sys.path.insert(0, os.path.join(BASE_DIR, "layers"))
try:
    from layer2_6_sector_priority import apply_sector_priority
    SECTOR_PRIORITY_AVAILABLE = True
except ImportError:
    SECTOR_PRIORITY_AVAILABLE = False
    print("[WARN] layer2_6_sector_priority 임포트 실패 → adjusted_fund_score = fundamental_score")

# ── 설정 상수 ─────────────────────────────────────────────────────────
MAX_TICKERS = 200
RATE_LIMIT_DELAY = 0.5

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
    "Referer": "https://finance.naver.com/"
}


# ── Phase 2-B: company_master → sector_map 구성 ───────────────────────
def load_sector_map_from_master() -> dict:
    if not os.path.exists(COMPANY_MASTER_CSV):
        print(f"[WARN] company_master 없음: {COMPANY_MASTER_CSV}")
        return {}
    try:
        df = pd.read_csv(
            COMPANY_MASTER_CSV, encoding="utf-8-sig",
            dtype={"stock_code": str},
            usecols=["stock_code", "sector_major"], low_memory=False
        )
        df["stock_code"] = df["stock_code"].astype(str).str.strip().str.zfill(6)
        df = df[df["stock_code"].notna() & (df["stock_code"] != "000000")]
        sector_map = dict(zip(df["stock_code"], df["sector_major"]))
        filled = sum(1 for v in sector_map.values()
                     if pd.notna(v) and str(v).strip() not in ("", "nan"))
        print(f"[Phase2-B] sector_map 로드: {len(sector_map)}건 | sector_major 채움={filled}건")
        return sector_map
    except Exception as e:
        print(f"[ERROR] sector_map 로드 실패: {e}")
        return {}


# ── 유틸 ─────────────────────────────────────────────────────────────
def safe_float(v) -> float | None:
    """v1.4: 정규식 기반 숫자 추출 (한글 단위/쉼표/공백 모두 제거)"""
    try:
        if v is None:
            return None
        cleaned = re.sub(r"[^\d.\-]", "", str(v).replace(",", ""))
        return float(cleaned) if cleaned not in ("", "-", ".") else None
    except Exception:
        return None


# ── 점수 함수 ─────────────────────────────────────────────────────────
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


# ── naver fetch (v1.4 핵심 수정) ──────────────────────────────────────
def fetch_naver_fundamental(ticker: str) -> dict:
    url = f"https://finance.naver.com/item/main.naver?code={ticker}"
    result = {"per": None, "pbr": None, "eps": None, "est_per": None}

    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.encoding = "euc-kr"
        soup = BeautifulSoup(r.text, "html.parser")

        per_found = pbr_found = eps_found = False

        for th in soup.find_all("th"):
            th_text = th.get_text(strip=True)
            td = th.find_next_sibling("td")
            if not td:
                continue
            td_text = td.get_text(strip=True)

            if (not per_found
                    and th_text.startswith("PER(")
                    and len(th_text) < 15
                    and "%" not in th_text):
                result["per"] = safe_float(td_text)
                per_found = True

            elif (not pbr_found
                    and th_text.startswith("PBR(")
                    and len(th_text) < 15):
                result["pbr"] = safe_float(td_text)
                pbr_found = True

            elif (not eps_found
                    and th_text.startswith("EPS(")
                    and len(th_text) < 15):
                result["eps"] = safe_float(td_text)
                eps_found = True

            elif (not eps_found
                    and th_text.startswith("PERl")
                    and "EPS" in th_text[:10]):
                parts = td_text.split("l")
                if len(parts) >= 2:
                    if not per_found:
                        result["per"] = safe_float(parts[0])
                        per_found = True
                    result["eps"] = safe_float(parts[1])
                    eps_found = True

            elif (result["est_per"] is None
                    and "PERl" in th_text[:15]
                    and len(th_text) > 20):
                parts = td_text.split("l")
                if parts:
                    result["est_per"] = safe_float(parts[0])

    except Exception as e:
        print(f"  [WARN] {ticker} 파싱 오류: {e}")

    return result


# ── v1.6 핵심 수정: 대상 종목 로드 (stock_code/ticker 양립) ────────────
def load_target_tickers() -> pd.DataFrame:
    """
    [v1.6] stock_code / ticker 컬럼 자동 탐지
    - signal_aggregator v3.x 출력: stock_code 컬럼
    - 이전 버전: ticker 컬럼
    - name 컬럼: name / corp_name / 회사명 fallback
    """
    master_path = os.path.join(OUTPUTS_DIR, "sfd_master_signal_latest.csv")
    if not os.path.exists(master_path):
        print(f"[ERROR] 입력파일 없음: {master_path}")
        sys.exit(1)

    # 컬럼명 사전 탐지
    df = pd.read_csv(master_path, dtype=str, nrows=1)
    cols = df.columns.tolist()

    # ticker 컬럼 자동 탐지
    tcol = next((c for c in ["ticker", "stock_code"] if c in cols), None)
    if tcol is None:
        print(f"[ERROR] ticker/stock_code 컬럼 없음. 실제 컬럼: {cols}")
        sys.exit(1)

    # name 컬럼 자동 탐지
    ncol = next((c for c in ["name", "corp_name", "회사명"] if c in cols), None)

    # 전체 로드
    read_cols = [tcol] + ([ncol] if ncol else [])
    if "total_score" in cols:
        read_cols.append("total_score")

    df = pd.read_csv(master_path, dtype={tcol: str},
                     usecols=read_cols)
    df[tcol] = df[tcol].astype(str).str.zfill(6)

    # ticker 컬럼으로 통일
    if tcol != "ticker":
        df = df.rename(columns={tcol: "ticker"})
    if ncol and ncol != "name":
        df = df.rename(columns={ncol: "name"})
    if "name" not in df.columns:
        df["name"] = ""

    if "total_score" in df.columns:
        df["total_score"] = pd.to_numeric(df["total_score"], errors="coerce")
        df = df.sort_values("total_score", ascending=False)

    return df[["ticker", "name"]].drop_duplicates().head(MAX_TICKERS).reset_index(drop=True)


# ── 메인 실행 ─────────────────────────────────────────────────────────
def run():
    print("=" * 60)
    print(f"[Layer 2.6] {datetime.now():%Y-%m-%d %H:%M:%S} (MAX={MAX_TICKERS})")
    print(f"OUTPUTS_DIR: {OUTPUTS_DIR}")
    print("=" * 60)

    sector_map = load_sector_map_from_master()
    target_df  = load_target_tickers()
    total_target = len(target_df)
    print(f"[INFO] 대상 종목수: {total_target}건\n")

    records = []
    coverage_ok = coverage_fail = 0

    for idx, row in target_df.iterrows():
        ticker = row["ticker"]
        name   = row.get("name", "")

        data = fetch_naver_fundamental(ticker)
        time.sleep(RATE_LIMIT_DELAY)

        per     = data["per"]
        pbr     = data["pbr"]
        eps     = data["eps"]
        est_per = data["est_per"]

        has_data = any(v is not None for v in [per, pbr, eps])
        if not has_data:
            coverage_fail += 1
            print(f"  [{idx+1:3d}] ❌ {ticker} {name} — 데이터 없음")
            continue

        coverage_ok += 1
        per_s = calc_per_score(per)
        pbr_s = calc_pbr_score(pbr)
        eps_s = calc_eps_score(eps)
        f_score = per_s + pbr_s + eps_s  # MAX 100점

        sector_major = sector_map.get(ticker)
        if not sector_major or str(sector_major).strip() in ("", "nan", "None"):
            sector_major = None

        if SECTOR_PRIORITY_AVAILABLE:
            sp_grade, sp_mult, adj_score = apply_sector_priority(f_score, sector_major)
        else:
            sp_grade, sp_mult, adj_score = "NEUTRAL", 1.0, f_score

        records.append({
            "ticker":                ticker,
            "name":                  name,
            "per":                   per,
            "pbr":                   pbr,
            "eps":                   eps,
            "est_per":               est_per,
            "per_grade":             get_per_grade(per),
            "pbr_grade":             get_pbr_grade(pbr),
            "fundamental_score":     f_score,
            "fund_score":            f_score,   # [v1.6] aggregator v3.x 참조용
            "sector_major":          sector_major,
            "sector_priority_grade": sp_grade,
            "sector_multiplier":     sp_mult,
            "adjusted_fund_score":   adj_score,
            "fetch_date":            date.today().isoformat(),
        })

        print(f"  [{idx+1:3d}] ✅ {ticker} {name:<12} | PER={per} PBR={pbr} | {f_score:3d}pt")

    print("\n" + "=" * 60)
    cov_rate = coverage_ok / total_target * 100 if total_target else 0
    print(f"[결과] ✅{coverage_ok} | ❌{coverage_fail} | 커버리지 {cov_rate:.1f}%")
    print("=" * 60)

    if not records:
        print("[WARN] 저장 데이터 없음")
        return

    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    out_df = pd.DataFrame(records)

    # [v1.6] 출력 파일명 통일: sfd_fundamental_watch_latest.csv
    out_path = os.path.join(OUTPUTS_DIR, "sfd_fundamental_watch_latest.csv")
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n✅ {out_path}")
    print("✅ Layer 2.6 fundamental_watch 완료")


if __name__ == "__main__":
    run()
