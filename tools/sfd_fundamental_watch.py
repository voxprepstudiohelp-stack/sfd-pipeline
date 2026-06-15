# -*- coding: utf-8 -*-
"""
sfd_fundamental_watch.py — Layer 2.6
기능: 상위 200종목 PER/PBR/EPS 수집 + 펀더멘털 스코어 산출
출처: finance.naver.com (BeautifulSoup 파싱)
버전: v1.4 (Phase2B) | 2026-05-25

[v1.3 → v1.4 변경점]
- fetch_naver_fundamental() 파싱 로직 전면 수정:
  * "PER(배)" 한글 매칭 → ASCII startswith 조건으로 교체 (euc-kr 인코딩 깨짐 대응)
  * EPS 단독 태그([47]) 처리 추가
  * safe_float() 정규식 기반으로 강화 (한글 단위 잔재 처리)
  * est_per: 예상PER 태그 조건 개선
- sector_injector post-processor 분리 운영 (sector_major는 injector가 처리)
"""

import os
import re
import sys
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime, date

# ── 경로 설정 (_file_ 기반, config.py 불필요) ──────────────────────────
BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs", "latest")

# Phase 2-B: company_master CSV 경로
SFC_ROOT           = os.path.dirname(os.path.dirname(BASE_DIR))  # = D:\AI_WorkSpace\I_SFC
COMPANY_MASTER_CSV = os.path.join(SFC_ROOT, "01_DB", "sfd_company_master_v1.4_with_financials.csv")

# v1.3: sector_priority 모듈 임포트
sys.path.insert(0, os.path.join(BASE_DIR, "layers"))
try:
    from layer2_6_sector_priority import apply_sector_priority
    SECTOR_PRIORITY_AVAILABLE = False  # v1.4: sector_injector post-processor 담당
except ImportError:
    SECTOR_PRIORITY_AVAILABLE = False
    print("[WARN] layer2_6_sector_priority 임포트 실패 → adjusted_fund_score = fundamental_score")

# ── 설정 상수 ─────────────────────────────────────────────────────────
MAX_TICKERS      = 200
RATE_LIMIT_DELAY = 0.5

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
    "Referer":    "https://finance.naver.com/"
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
    """PER 점수 0-30pt | KOSPI 평균 10-12x 기준"""
    if per is None or per <= 0: return 0
    if per <=  8: return 30
    if per <= 15: return 20
    if per <= 25: return 10
    return 0

def calc_pbr_score(pbr) -> int:
    """PBR 점수 0-40pt | KOSPI 전체 저평가 기준"""
    if pbr is None or pbr <= 0: return 0
    if pbr <= 0.8: return 40
    if pbr <= 1.5: return 30
    if pbr <= 2.5: return 15
    return 0

def calc_eps_score(eps) -> int:
    """EPS 점수 0-30pt | 수익성/성장성"""
    if eps is None: return 0
    if eps >= 10000: return 30
    if eps >=  5000: return 20
    if eps >=  1000: return 10
    if eps >      0: return 5
    return 0

def get_per_grade(per) -> str:
    if per is None or per <= 0: return "NEGATIVE"
    if per <=  8: return "CHEAP"
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
    """
    finance.naver.com 파싱 → PER/PBR/EPS
    v1.4 수정: 한글 없이 ASCII startswith 조건으로 태그 매칭
               (r.encoding=euc-kr 강제 시 한글 깨짐 대응)
    """
    url    = f"https://finance.naver.com/item/main.naver?code={ticker}"
    result = {"per": None, "pbr": None, "eps": None, "est_per": None}

    try:
        r          = requests.get(url, headers=HEADERS, timeout=10)
        r.encoding = "euc-kr"
        soup       = BeautifulSoup(r.text, "html.parser")

        per_found = pbr_found = eps_found = False

        for th in soup.find_all("th"):
            th_text = th.get_text(strip=True)
            td      = th.find_next_sibling("td")
            if not td:
                continue
            td_text = td.get_text(strip=True)

            # ── v1.4: 한글 제거, ASCII startswith 조건 ────────────────
            # PER 단독 태그: th='PER(배)' → euc-kr 깨짐 → 'PER(' + len<15 + '%' 없음
            if (not per_found
                    and th_text.startswith("PER(")
                    and len(th_text) < 15
                    and "%" not in th_text):
                result["per"] = safe_float(td_text)
                per_found = True

            # PBR 단독 태그: th='PBR(배)' → 'PBR(' + len<15
            elif (not pbr_found
                    and th_text.startswith("PBR(")
                    and len(th_text) < 15):
                result["pbr"] = safe_float(td_text)
                pbr_found = True

            # EPS 단독 태그: th='EPS(원)' → 'EPS(' + len<15  ← v1.4 NEW
            elif (not eps_found
                    and th_text.startswith("EPS(")
                    and len(th_text) < 15):
                result["eps"] = safe_float(td_text)
                eps_found = True

            # PERlEPS 복합 태그 (현재 분기 PER + EPS)
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

            # 예상PER 태그 (th 텍스트에 '예상PER' 또는 'PERl' + 복합 long)
            elif (result["est_per"] is None
                    and "PERl" in th_text[:15]
                    and len(th_text) > 20):
                parts = td_text.split("l")
                if parts:
                    result["est_per"] = safe_float(parts[0])

    except Exception as e:
        print(f"  [WARN] {ticker} 파싱 오류: {e}")

    return result


# ── 대상 종목 로드 ────────────────────────────────────────────────────
def load_target_tickers() -> pd.DataFrame:
    master_path = os.path.join(OUTPUTS_DIR, "sfd_master_signal_latest.csv")
    if not os.path.exists(master_path):
        print(f"[ERROR] 입력파일 없음: {master_path}")
        sys.exit(1)
    df = pd.read_csv(master_path, dtype={"ticker": str})
    df["ticker"] = df["ticker"].astype(str).str.zfill(6)
    if "total_score" in df.columns:
        df["total_score"] = pd.to_numeric(df["total_score"], errors="coerce")
        df = df.sort_values("total_score", ascending=False)
    return df[["ticker", "name"]].drop_duplicates().head(MAX_TICKERS).reset_index(drop=True)


# ── 메인 실행 ─────────────────────────────────────────────────────────
def run_fundamental_watch():
    print("=" * 60)
    print(f"[Layer 2.6] {datetime.now():%Y-%m-%d %H:%M:%S} (MAX={MAX_TICKERS})")
    print(f"OUTPUTS_DIR: {OUTPUTS_DIR}")
    print("=" * 60)

    sector_map   = load_sector_map_from_master()
    target_df    = load_target_tickers()
    total_target = len(target_df)
    print(f"[INFO] Target ticker count: {total_target}\n")

    records        = []
    coverage_ok    = 0
    coverage_fail  = 0

    for idx, row in target_df.iterrows():
        ticker = row["ticker"]
        name   = row.get("name", "")

        data    = fetch_naver_fundamental(ticker)
        time.sleep(RATE_LIMIT_DELAY)

        per     = data["per"]
        pbr     = data["pbr"]
        eps     = data["eps"]
        est_per = data["est_per"]

        has_data = any(v is not None for v in [per, pbr, eps])
        if not has_data:
            coverage_fail += 1
            print(f"  [{idx+1:3d}] ❌ {ticker} {name} — no data")
            continue

        coverage_ok += 1
        per_s   = calc_per_score(per)
        pbr_s   = calc_pbr_score(pbr)
        eps_s   = calc_eps_score(eps)
        f_score = per_s + pbr_s + eps_s  # MAX 100점

        # sector_major → adjusted_fund_score (sector_injector v1.1로 분리됨)
        sector_major = sector_map.get(ticker)
        if not sector_major or str(sector_major).strip() in ("", "nan", "None"):
            sector_major = None

        if SECTOR_PRIORITY_AVAILABLE:
            sp_grade, sp_mult, adj_score = apply_sector_priority(f_score, sector_major)
        else:
            sp_grade  = "NEUTRAL"
            sp_mult   = 1.0
            adj_score = f_score

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
            "sector_major":          sector_major,
            "sector_priority_grade": sp_grade,
            "sector_multiplier":     sp_mult,
            "adjusted_fund_score":   adj_score,
            "fetch_date":            date.today().isoformat(),
        })

        print(f"  [{idx+1:3d}] ✅ {ticker} {name:<12} | PER={per} PBR={pbr} | {f_score:3d}pt")

    print("\n" + "=" * 60)
    print(f"[RESULT] ✅{coverage_ok} | ❌{coverage_fail} | coverage {coverage_ok/total_target*100:.1f}%")
    print("=" * 60)

    if not records:
        print("[WARN] No data to save")
        return

    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    out_df   = pd.DataFrame(records)
    out_path = os.path.join(OUTPUTS_DIR, "sfd_fundamental_latest.csv")
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n✅ {out_path}")


if __name__ == "__main__":
    run_fundamental_watch()
