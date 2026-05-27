# -*- coding: utf-8 -*-
"""
sfd_sector_injector.py  v1.3
용도: sfd_fundamental_watch.py 실행 후 sector_major + adjusted_fund_score 주입
작성: Claude (Anthropic) 2026-05-25
변경: v1.2 → v1.3
  ① MASTER 파일: sector_filled → with_financials 복구 (company_master 매칭 29→147건)
  ② MANUAL_SECTOR_MAP: 5건 추가 (우선주 parent 미등재 해소)
     003555 LG우 / 03473K SK우 / 001525 동양우 / 014915 성문전자우 / 108675 LX하우시스우
     + parent 본주 5건 추가 (003550/034730/001520/014910/108670)
  목표: NaN 잔존 0건
"""

import pandas as pd

# ─────────────────────────────────────────────────────────────
# 경로
# ─────────────────────────────────────────────────────────────
MASTER   = r"D:\AI_WorkSpace\I_SFC\01_DB\sfd_company_master_v1.4_with_financials.csv"   # v1.3 복구
FUND_CSV = r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline\outputs\latest\sfd_fundamental_latest.csv"

# ─────────────────────────────────────────────────────────────
# sector 우선순위 테이블
# ─────────────────────────────────────────────────────────────
SECTOR_PRIORITY = {
    "반도체":            ("HIGH",    1.2),
    "2차전지/전기차/배터리": ("HIGH",    1.2),
    "방산/우주항공":       ("HIGH",    1.2),
    "바이오/제약":        ("HIGH",    1.2),
    "전력/전선/변압기":    ("HIGH",    1.15),
    "인터넷/플랫폼":      ("HIGH",    1.15),
    "유통/물류":          ("MEDIUM",  1.1),
    "통신/네트워크":       ("MEDIUM",  1.05),
    "식품/소비재":        ("MEDIUM",  1.05),
    "게임/엔터":          ("MEDIUM",  1.0),
    "기계/장비":          ("MEDIUM",  1.0),
    "금융":              ("MEDIUM",  1.0),
    "화학/소재":          ("NEUTRAL", 1.0),
    "섬유/의류":          ("NEUTRAL", 1.0),
    "디스플레이":         ("NEUTRAL", 1.0),
    "건설/인프라":        ("NEUTRAL", 1.0),
    "에너지/정유":        ("NEUTRAL", 1.0),
    "전력/원전":          ("MEDIUM",  1.05),
    "의료기기":           ("NEUTRAL", 1.0),
    "철강/금속":          ("NEUTRAL", 0.95),
    "교육":              ("NEUTRAL", 1.0),
    "환경":              ("NEUTRAL", 1.0),
    "자동차/부품":        ("MEDIUM",  1.05),
}

# ─────────────────────────────────────────────────────────────
# 수동 매핑 (company_master NaN 50건 + 우선주 parent 5건)
# ─────────────────────────────────────────────────────────────
MANUAL_SECTOR_MAP = {
    # ── 보통주 36건 ──────────────────────────────────────────
    "092460": "자동차/부품",       # 한라IMS
    "066620": "건설/인프라",       # 국보디자인
    "011560": "건설/인프라",       # 세보엠이씨
    "228850": "의료기기",          # 레이언스
    "083450": "반도체",            # GST
    "332570": "전력/전선/변압기",  # PS일렉트로닉스
    "402340": "인터넷/플랫폼",     # SK스퀘어
    "243070": "바이오/제약",       # 휴온스
    "357230": "바이오/제약",       # 에이치피오
    "054450": "반도체",            # 텔레칩스
    "115160": "인터넷/플랫폼",     # 휴맥스
    "302430": "기계/장비",         # 이노메트리
    "382800": "환경",              # 지앤비에스 에코
    "012200": "기계/장비",         # 계양전기
    "032800": "게임/엔터",         # 판타지오
    "008060": "반도체",            # 대덕 (PCB)
    "273060": "인터넷/플랫폼",     # 와이즈버즈
    "307950": "인터넷/플랫폼",     # 현대오토에버
    "406820": "식품/소비재",       # 뷰티스킨
    "446540": "기계/장비",         # 메가터치
    "439090": "식품/소비재",       # 마녀공장
    "465480": "인터넷/플랫폼",     # 인스피언
    "336260": "전력/원전",         # 두산퓨얼셀
    "036420": "게임/엔터",         # 콘텐트리중앙
    "452200": "인터넷/플랫폼",     # 민테크
    "065680": "전력/전선/변압기",  # 우주일렉트로
    "145020": "바이오/제약",       # 휴젤
    "092220": "반도체",            # KEC
    "195870": "반도체",            # 해성디에스
    "131290": "반도체",            # 티에스이
    "352480": "식품/소비재",       # 씨앤씨인터내셔널
    "078520": "식품/소비재",       # 에이블씨엔씨
    "007070": "유통/물류",         # GS리테일
    "222800": "반도체",            # 심텍
    "439580": "의료기기",          # 블루엠텍
    "012510": "인터넷/플랫폼",     # 더존비즈온
    # ── 우선주 parent도 NaN (본주 포함) ─────────────────────
    "008060": "반도체",            # 대덕 (본주)
    "00806K": "반도체",            # 대덕1우
    "336260": "전력/원전",         # 두산퓨얼셀 (본주)
    "33626K": "전력/원전",         # 두산퓨얼셀1우
    # ── v1.3 추가: NaN 잔존 5건 해소 ────────────────────────
    "003550": "금융",              # LG (지주) ← parent
    "003555": "금융",              # LG우
    "034730": "인터넷/플랫폼",     # SK (지주, SK하이닉스/SKT 모회사) ← parent
    "03473K": "인터넷/플랫폼",     # SK우
    "001520": "금융",              # 동양 (지주) ← parent
    "001525": "금융",              # 동양우
    "014910": "전력/전선/변압기",  # 성문전자 (본주) ← parent
    "014915": "전력/전선/변압기",  # 성문전자우
    "108670": "건설/인프라",       # LX하우시스 (본주) ← parent
    "108675": "건설/인프라",       # LX하우시스우
}


# ─────────────────────────────────────────────────────────────
# 우선주 parent ticker 파생
# ─────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("SFD Sector Injector — post-processor  v1.3")
    print("=" * 60)

    # 1) company_master → sector_map
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

    # 2) fundamental_latest 로드
    fund = pd.read_csv(FUND_CSV, dtype={"ticker": str})
    fund["ticker"] = fund["ticker"].astype(str).str.strip()
    print(f"fund 종목수: {len(fund)}건")

    # dtype 초기화
    fund["sector_major"]          = fund["sector_major"].astype(object) \
                                    if "sector_major" in fund.columns else ""
    fund["sector_priority_grade"] = fund.get("sector_priority_grade",
                                    pd.Series([""] * len(fund))).astype(object)
    fund["sector_multiplier"]     = fund.get("sector_multiplier",
                                    pd.Series([1.0] * len(fund))).astype(float)
    fund["adjusted_fund_score"]   = fund.get("adjusted_fund_score",
                                    pd.Series([0.0] * len(fund))).astype(float)

    # 3) 주입 (우선순위: company_master → 수동매핑 → 우선주상속 → NEUTRAL)
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
            fund.at[idx, "sector_major"]          = sector
            fund.at[idx, "sector_priority_grade"] = grade
            fund.at[idx, "sector_multiplier"]     = mult
            fund.at[idx, "adjusted_fund_score"]   = adj
        else:
            fund.at[idx, "sector_priority_grade"] = "NEUTRAL"
            fund.at[idx, "sector_multiplier"]     = 1.0
            fund.at[idx, "adjusted_fund_score"]   = float(row["fundamental_score"])

        stats[source] += 1

    fund.to_csv(FUND_CSV, index=False, encoding="utf-8-sig")

    # 4) 결과 출력
    nan_remain = fund["sector_major"].isna().sum()
    print(f"\n주입 결과 (총 {len(fund)}건):")
    print(f"  company_master : {stats['master']}건")
    print(f"  수동 매핑       : {stats['manual']}건")
    print(f"  우선주 상속     : {stats['preferred']}건")
    print(f"  NEUTRAL        : {stats['neutral']}건")
    print(f"  NaN 잔존        : {nan_remain}건  ← 목표: 0")

    print(f"\n[sector 분포]")
    print(fund["sector_major"].value_counts().to_string())

    print(f"\n[adjusted_fund_score 상위 15건]")
    top = fund.nlargest(15, "adjusted_fund_score")[
        ["ticker", "name", "fundamental_score", "sector_major",
         "sector_multiplier", "adjusted_fund_score"]
    ]
    print(top.to_string(index=False))
    print(f"\n✅ 저장: {FUND_CSV}")


if __name__ == "__main__":
    main()
