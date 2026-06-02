# -*- coding: utf-8 -*-
"""
sfd_sector_injector.py  v1.4
역할: sfd_fundamental_watch.py 출력에 sector_major + adjusted_fund_score 주입
수정: Claude (Anthropic) 2026-05-30
  v1.3 → v1.4
  ① MASTER CSV: 로컬 하드코딩 제거 → SFD_BASE_DIR 환경변수 우선, data/ 폴더 fallback
  ② FUND_CSV: 동일하게 환경변수 기반 경로로 통일
  ③ 클라우드(GitHub Actions) 완전 호환
"""

import os
import pandas as pd

# ──────────────────────────────────────────────────────────────
# 경로 설정 (v1.4 핵심 수정: 환경변수 → data/ fallback)
# ──────────────────────────────────────────────────────────────
_BASE = os.environ.get(
    "SFD_BASE_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)

# MASTER CSV: data/ 폴더에 위치 (GitHub repo에 포함)
MASTER = os.path.join(_BASE, "data", "sfd_company_master_v1.4_sector_filled.csv")

# FUND CSV: outputs/latest/ (파이프라인 런타임 생성)
FUND_CSV = os.path.join(_BASE, "outputs", "latest", "sfd_fundamental_watch_latest.csv")

# ──────────────────────────────────────────────────────────────
# sector 우선순위 정의
# ──────────────────────────────────────────────────────────────
SECTOR_PRIORITY = {
    "원전/방산":                ("HIGH",    1.2),
    "2차전지/배터리소재/이차전지": ("HIGH",    1.2),
    "반도체/반도체장비":          ("HIGH",    1.2),
    "조선/해양":                 ("HIGH",    1.2),
    "소프트웨어/IT서비스/IT솔루션": ("HIGH",    1.15),
    "신재생에너지/태양광풍력":    ("HIGH",    1.15),
    "바이오/헬스케어":           ("MEDIUM",  1.1),
    "자동차/자동차부품":          ("MEDIUM",  1.05),
    "철강/금속/비철금속":         ("MEDIUM",  1.05),
    "건설/건자재":               ("MEDIUM",  1.0),
    "화학/정밀화학":             ("MEDIUM",  1.0),
    "LG계열":                   ("MEDIUM",  1.0),
    "음식료/유통":               ("NEUTRAL", 1.0),
    "섬유/의류/잡화":            ("NEUTRAL", 1.0),
    "금융투자/은행/증권":        ("NEUTRAL", 1.0),
    "통신/인터넷/미디어":        ("NEUTRAL", 1.0),
    "운송/물류/항공":            ("NEUTRAL", 1.0),
    "서비스/레저/엔터":          ("MEDIUM",  1.05),
    "지주회사/복합기업":         ("NEUTRAL", 1.0),
    "에너지/가스/정유":          ("NEUTRAL", 0.95),
    "부동산":                    ("NEUTRAL", 1.0),
    "기타":                      ("NEUTRAL", 1.0),
    "전력/전선/변압기":          ("MEDIUM",  1.05),
}

MANUAL_SECTOR_MAP = {
    "003555": "LG계열",
    "003550": "LG계열",
    "034730": "신재생에너지/태양광풍력",
    "034730K": "신재생에너지/태양광풍력",
    "001520": "LG계열",
    "001525": "LG계열",
    "014910": "소프트웨어/IT서비스/IT솔루션",
    "014915": "소프트웨어/IT서비스/IT솔루션",
    "108670": "통신/인터넷/미디어",
    "108675": "통신/인터넷/미디어",
    "008060": "원전/방산",
    "008060K": "원전/방산",
    "336260": "소프트웨어/IT서비스/IT솔루션",
    "336260K": "소프트웨어/IT서비스/IT솔루션",
}


def get_parent_ticker(ticker: str):
    t = str(ticker).strip()
    if t.endswith("K"):
        return t[:-1] + "0"
    if len(t) == 6 and t[-1] in ("5", "7", "9"):
        return t[:-1] + "0"
    return None


def apply_priority(score, sector):
    if not sector or str(sector).strip() in ("", "nan", "None"):
        return "NEUTRAL", 1.0, float(score)
    grade, mult = SECTOR_PRIORITY.get(str(sector).strip(), ("NEUTRAL", 1.0))
    return grade, mult, round(float(score) * mult, 2)


def main():
    print("=" * 60)
    print("SFD Sector Injector — post-processor  v1.4")
    print(f"  MASTER : {MASTER}")
    print(f"  FUND   : {FUND_CSV}")
    print("=" * 60)

    if not os.path.exists(MASTER):
        print(f"[FATAL] MASTER CSV 없음: {MASTER}")
        print("  → data/ 폴더에 sfd_company_master_v1.4_sector_filled.csv 배치 필요")
        raise SystemExit(1)

    if not os.path.exists(FUND_CSV):
        print(f"[FATAL] FUND CSV 없음: {FUND_CSV}")
        raise SystemExit(1)

    master = pd.read_csv(MASTER, dtype={"stock_code": str},
                         usecols=["stock_code", "sector_major"], low_memory=False)
    master["stock_code"] = master["stock_code"].astype(str).str.strip()
    valid = master[
        master["sector_major"].notna() &
        (master["sector_major"].str.strip() != "") &
        (~master["sector_major"].str.strip().isin(["nan", "None"]))
    ]
    sector_map = dict(zip(valid["stock_code"], valid["sector_major"]))
    print(f"company_master sector_map: {len(sector_map)}건")

    fund = pd.read_csv(FUND_CSV, dtype={"ticker": str})
    fund["ticker"] = fund["ticker"].astype(str).str.strip()
    print(f"fund 로드: {len(fund)}건")

    fund["sector_major"]           = fund["sector_major"].astype(object) \
                                     if "sector_major" in fund.columns else ""
    fund["sector_priority_grade"]  = fund.get("sector_priority_grade",
                                     pd.Series([""] * len(fund))).astype(object)
    fund["sector_multiplier"]      = fund.get("sector_multiplier",
                                     pd.Series([1.0] * len(fund))).astype(float)
    fund["adjusted_fund_score"]    = fund.get("adjusted_fund_score",
                                     pd.Series([0.0] * len(fund))).astype(float)

    stats = {"master": 0, "manual": 0, "preferred": 0, "neutral": 0}

    for idx, row in fund.iterrows():
        ticker = row["ticker"]
        sector = sector_map.get(ticker)
        if sector:
            source = "master"
        else:
            sector = MANUAL_SECTOR_MAP.get(ticker)
            if sector:
                source = "manual"
            else:
                parent = get_parent_ticker(ticker)
                if parent:
                    sector = sector_map.get(parent) or MANUAL_SECTOR_MAP.get(parent)
                    source = "preferred" if sector else "neutral"
                else:
                    source = "neutral"

        if sector:
            grade, mult, adj = apply_priority(row["fundamental_score"], sector)
            fund.at[idx, "sector_major"]           = sector
            fund.at[idx, "sector_priority_grade"]  = grade
            fund.at[idx, "sector_multiplier"]      = mult
            fund.at[idx, "adjusted_fund_score"]    = adj
        else:
            fund.at[idx, "sector_priority_grade"]  = "NEUTRAL"
            fund.at[idx, "sector_multiplier"]      = 1.0
            fund.at[idx, "adjusted_fund_score"]    = float(row["fundamental_score"])

        stats[source] += 1

    fund.to_csv(FUND_CSV, index=False, encoding="utf-8-sig")

    nan_remain = fund["sector_major"].isna().sum()
    print(f"\n주입 결과 ({len(fund)}건):")
    print(f"  company_master : {stats['master']}건")
    print(f"  수동 매핑     : {stats['manual']}건")
    print(f"  우선주 연결   : {stats['preferred']}건")
    print(f"  NEUTRAL       : {stats['neutral']}건")
    print(f"  NaN 잔여      : {nan_remain}건  → 목표: 0")

    top = fund.nlargest(10, "adjusted_fund_score")[
        ["ticker", "name", "fundamental_score", "sector_major",
         "sector_multiplier", "adjusted_fund_score"]
    ]
    print(f"\n[adjusted_fund_score TOP10]\n{top.to_string(index=False)}")
    print(f"\n✅ 저장: {FUND_CSV}")


if __name__ == "__main__":
    main()
