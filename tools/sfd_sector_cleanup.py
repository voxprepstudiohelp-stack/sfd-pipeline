# -*- coding: utf-8 -*-
# sfd_sector_cleanup.py
# 목적: 잔여 38건 처리
#   1) company_master 패치 (비표준 코드 포함)
#   2) sfd_fundamental_latest.csv 직접 패치 (즉시 반영)
#   3) adjusted_fund_score 재계산
# 작성: Claude (Anthropic) 2026-05-24

import pandas as pd
import os

MASTER = r"D:\AI_WorkSpace\I_SFC\01_DB\sfd_company_master_v1.4_with_financials.csv"
FUND_CSV = r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline\outputs\latest\sfd_fundamental_latest.csv"
LAYER26_PY = r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline\tools\sfd_fundamental_watch.py"

# 잔여 38건 수동 매핑 (ticker 기준 — fundamental_latest.csv 직접 패치용)
FINAL_MAP = {
    "003555": "인터넷/플랫폼",   # LG우 (LG 우선주)
    "307180": "인터넷/플랫폼",   # 아이엘
    "051390": "기계/장비",       # YW
    "065770": "건설/인프라",     # CS
    "115530": "통신/네트워크",   # 씨엔플러스
    "001525": "건설/인프라",     # 동양우
    "33626K": "에너지/정유",     # 두산퓨얼셀1우
    "458650": "자동차/부품",     # 성우
    "357880": "방산/우주항공",   # SKAI (드론)
    "104040": "기계/장비",       # 디에스엠
    "006345": "전력/전선/변압기", # 대원전선우
    "005257": "바이오/제약",     # 녹십자홀딩스2우
    "019010": "게임/엔터",       # 베뉴지
    "142210": "통신/네트워크",   # 유니트론텍
    "014915": "전력/전선/변압기", # 성문전자우
    "005385": "자동차/부품",     # 현대차우
    "00806K": "반도체",          # 대덕1우
    "060540": "기계/장비",       # 에스에이티
    "005387": "자동차/부품",     # 현대차2우B
    "041930": "자동차/부품",     # SY동아
    "005389": "자동차/부품",     # 현대차3우B
    "064800": "인터넷/플랫폼",   # 포니링크
    "35320K": "반도체",          # 대덕전자1우
    "108675": "건설/인프라",     # LX하우시스우
    "432980": "금융",            # 엠에프씨
    "009460": "식품/소비재",     # 한창제지
    "437730": "기계/장비",       # 삼현
    "015590": "기계/장비",       # DKME
    "424760": "바이오/제약",     # 벨로크
    "263020": "기계/장비",       # 디케이앤디
    "012205": "전력/전선/변압기", # 계양전기우
    "076610": "의료기기",        # 해성옵틱스
    "066575": "인터넷/플랫폼",   # LG전자우
    "039830": "게임/엔터",       # 오로라
    "078890": "전력/전선/변압기", # 가온그룹 (가온전선 계열)
    "323350": "에너지/정유",     # 다원넥스뷰 (전력변환)
    "013000": "화학/소재",       # 세우글로벌
    "02826K": "유통/물류",       # 삼성물산우B
}

# =============================================
# STEP 1: company_master 패치 (비표준 코드)
# =============================================
print("=" * 60)
print("STEP 1: company_master patch")

master = pd.read_csv(MASTER, dtype={"stock_code": str}, low_memory=False)
# 비표준 코드는 zfill 없이 그대로 비교
m_patched = 0
for ticker, sector in FINAL_MAP.items():
    mask = (master["stock_code"].str.strip() == ticker) & \
           (master["sector_major"].fillna("").str.strip() == "")
    if mask.any():
        master.loc[mask, "sector_major"] = sector
        m_patched += 1
master.to_csv(MASTER, index=False, encoding="utf-8-sig")
print(f"  company_master patched: {m_patched} records")

# =============================================
# STEP 2: sfd_fundamental_latest.csv 직접 패치
# =============================================
print("\nSTEP 2: sfd_fundamental_latest.csv direct patch")

fund = pd.read_csv(FUND_CSV, dtype={"ticker": str})
# ticker 정규화 (비표준 코드 보존)
fund["ticker"] = fund["ticker"].astype(str).str.strip()

f_patched = 0
for ticker, sector in FINAL_MAP.items():
    mask = (fund["ticker"] == ticker) & \
           (fund["sector_major"].fillna("").str.strip().isin(["", "nan", "None"]))
    if mask.any():
        fund.loc[mask, "sector_major"] = sector
        name = fund.loc[mask, "name"].values[0]
        print(f"  {ticker} {name:18s} → {sector}")
        f_patched += 1

print(f"  fundamental_latest patched: {f_patched} records")

# =============================================
# STEP 3: adjusted_fund_score 재계산
# =============================================
print("\nSTEP 3: adjusted_fund_score recalculate")

SECTOR_PRIORITY = {
    "반도체":           ("HIGH",    1.2),
    "2차전지/소재":     ("HIGH",    1.2),
    "방산/우주항공":    ("HIGH",    1.2),
    "전력/원전":        ("HIGH",    1.2),
    "전력/전선/변압기": ("HIGH",    1.15),
    "조선/중공업":      ("HIGH",    1.15),
    "바이오/제약":      ("MEDIUM",  1.1),
    "인터넷/플랫폼":    ("MEDIUM",  1.05),
    "자동차/부품":      ("MEDIUM",  1.05),
    "화학/소재":        ("MEDIUM",  1.0),
    "기계/장비":        ("MEDIUM",  1.0),
}

def apply_priority(score, sector):
    if not sector or str(sector).strip() in ("", "nan", "None"):
        return "NEUTRAL", 1.0, score
    grade, mult = SECTOR_PRIORITY.get(str(sector).strip(), ("NEUTRAL", 1.0))
    return grade, mult, round(score * mult, 2)

recalc = 0
for idx, row in fund.iterrows():
    sector = row.get("sector_major", "")
    if sector and str(sector).strip() not in ("", "nan", "None"):
        grade, mult, adj = apply_priority(row["fundamental_score"], sector)
        if fund.at[idx, "sector_priority_grade"] == "NEUTRAL" and grade != "NEUTRAL":
            fund.at[idx, "sector_priority_grade"] = grade
            fund.at[idx, "sector_multiplier"]      = mult
            fund.at[idx, "adjusted_fund_score"]    = adj
            recalc += 1

fund.to_csv(FUND_CSV, index=False, encoding="utf-8-sig")
print(f"  adjusted_fund_score recalculated: {recalc} records")

# =============================================
# 최종 결과
# =============================================
filled = fund[fund["sector_major"].notna() & (fund["sector_major"].str.strip() != "")]
empty  = fund[fund["sector_major"].isna()  | (fund["sector_major"].str.strip() == "")]

print("\n" + "=" * 60)
print(f"Final 200-ticker sector mapping")
print(f"  OK: {len(filled)} / unclassified: {len(empty)}")
print(f"\n[sector distribution]")
print(fund["sector_major"].value_counts().to_string())
print(f"\n[adjusted_fund_score top 10]")
print(fund.nlargest(10, "adjusted_fund_score")[
    ["ticker","name","fundamental_score","sector_major","sector_multiplier","adjusted_fund_score"]
].to_string(index=False))
print(f"\n✅ Saved")

if len(empty):
    print(f"\n[Final unclassified: {len(empty)}]")
    print(empty[["ticker","name"]].to_string(index=False))
