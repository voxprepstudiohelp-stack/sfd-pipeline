# -*- coding: utf-8 -*-
"""
SFD Sector Major Auto Classifier v1.2
원작: G. Lucy v1.0 / 패치: Claude v1.1 / 경로+Dept 수정: Claude v1.2
수정: 2026-05-24

변경사항 v1.2:
- INPUT/OUTPUT 경로: H 드라이브 기준으로 수정
- KRX sector 컬럼: Dept 우선 사용
- SyntaxWarning 제거 (docstring 경로 제거)
"""

import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime

INPUT_FILE  = r"H:\내 드라이브\AI_WorkSpace\I_SFC\01_DB\sfd_company_master_v1.4_with_financials.csv"
OUTPUT_FILE = r"H:\내 드라이브\AI_WorkSpace\I_SFC\01_DB\sfd_company_master_v1.4_sector_filled.csv"

SECTOR_MAPPING = {
    "반도체":       "반도체",
    "집적회로":     "반도체",
    "웨이퍼":       "반도체",
    "디스플레이":   "디스플레이",
    "LCD":          "디스플레이",
    "OLED":         "디스플레이",
    "패널":         "디스플레이",
    "2차전지":      "2차전지/소재",
    "배터리":       "2차전지/소재",
    "전지":         "2차전지/소재",
    "양극재":       "2차전지/소재",
    "자동차":       "자동차/부품",
    "전기차":       "자동차/부품",
    "자동차부품":   "자동차/부품",
    "바이오":       "바이오/제약",
    "제약":         "바이오/제약",
    "의약":         "바이오/제약",
    "의료기기":     "의료기기",
    "의료":         "바이오/제약",
    "게임":         "게임/엔터",
    "엔터":         "게임/엔터",
    "콘텐츠":       "게임/엔터",
    "소프트웨어":   "인터넷/플랫폼",
    "인터넷":       "인터넷/플랫폼",
    "플랫폼":       "인터넷/플랫폼",
    "IT서비스":     "인터넷/플랫폼",
    "통신":         "통신/네트워크",
    "네트워크":     "통신/네트워크",
    "통신장비":     "통신/네트워크",
    "미디어":       "미디어/광고",
    "방송":         "미디어/광고",
    "광고":         "미디어/광고",
    "철강":         "철강/금속",
    "비철금속":     "철강/금속",
    "금속":         "철강/금속",
    "조선":         "조선/중공업",
    "중공업":       "조선/중공업",
    "기계":         "기계/장비",
    "로봇":         "기계/장비",
    "자동화":       "기계/장비",
    "화학":         "화학/소재",
    "정밀화학":     "화학/소재",
    "소재":         "화학/소재",
    "원전":         "전력/원전",
    "원자력":       "전력/원전",
    "발전":         "전력/원전",
    "전선":         "전력/전선/변압기",
    "변압기":       "전력/전선/변압기",
    "전력기기":     "전력/전선/변압기",
    "전기장비":     "전력/전선/변압기",
    "전력":         "전력/전선/변압기",
    "방산":         "방산/우주항공",
    "항공":         "방산/우주항공",
    "우주":         "방산/우주항공",
    "방위":         "방산/우주항공",
    "건설":         "건설/인프라",
    "건축":         "건설/인프라",
    "부동산":       "건설/인프라",
    "인프라":       "건설/인프라",
    "은행":         "금융",
    "증권":         "금융",
    "보험":         "금융",
    "금융":         "금융",
    "투자":         "금융",
    "정유":         "에너지/정유",
    "에너지":       "에너지/정유",
    "석유":         "에너지/정유",
    "가스":         "에너지/정유",
    "식품":         "식품/소비재",
    "음료":         "식품/소비재",
    "음식료":       "식품/소비재",
    "화장품":       "식품/소비재",
    "생활용품":     "식품/소비재",
    "소비재":       "식품/소비재",
    "유통":         "유통/물류",
    "물류":         "유통/물류",
    "운송":         "유통/물류",
    "해운":         "유통/물류",
    "의류":         "섬유/의류",
    "패션":         "섬유/의류",
    "섬유":         "섬유/의류",
    "호텔":         "여행/레저",
    "여행":         "여행/레저",
    "레저":         "여행/레저",
    "교육":         "교육",
}


def clean_text(text):
    if pd.isna(text):
        return ""
    return str(text).strip()


def map_sector(sector_text):
    sector_text = clean_text(sector_text)
    if not sector_text:
        return "기타"
    for keyword, mapped in SECTOR_MAPPING.items():
        if keyword in sector_text:
            return mapped
    return "기타"


def main():
    print("=" * 60)
    print("SFD Sector Classifier v1.2")
    print(f"Running: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 60)

    # STEP 1: KRX 업종 수집
    print("\n[STEP 1] Collecting KRX sector data...")
    krx = fdr.StockListing("KRX")
    print(f"  Available columns: {list(krx.columns)}")

    # Dept 우선, 없으면 Sector, Industry 순
    for col in ["Dept", "Sector", "Industry"]:
        if col in krx.columns:
            sector_col = col
            break
    else:
        sector_col = None

    krx["stock_code"]  = krx["Code"].astype(str).str.zfill(6)
    krx["krx_sector"]  = krx[sector_col].fillna("") if sector_col else ""
    krx = krx[["stock_code", "Name", "krx_sector"]]
    print(f"  KRX collected: {len(krx)} | sector column: '{sector_col}'")
    print(f"  Dept sample: {krx['krx_sector'].value_counts().head(10).to_dict()}")

    krx["sector_major_new"] = krx["krx_sector"].apply(map_sector)
    print(f"  Mapping distribution:\n{krx['sector_major_new'].value_counts().head(15).to_string()}")

    # STEP 2: company_master 로딩
    print("\n[STEP 2] Loading company_master...")
    print(f"  Path: {INPUT_FILE}")
    df = pd.read_csv(INPUT_FILE, encoding="utf-8-sig", dtype={"stock_code": str}, low_memory=False)
    df["stock_code"] = df["stock_code"].astype(str).str.zfill(6)

    before_empty  = df["sector_major"].fillna("").eq("").sum()
    before_filled = df["sector_major"].fillna("").ne("").sum()
    print(f"  Total: {len(df)} | empty: {before_empty} | existing: {before_filled}")

    # STEP 3: JOIN
    print("\n[STEP 3] sector JOIN...")
    merged = df.merge(krx[["stock_code", "sector_major_new"]], on="stock_code", how="left")
    merged["sector_major"] = merged.apply(
        lambda x: x["sector_major_new"] if clean_text(x["sector_major"]) == "" else x["sector_major"],
        axis=1,
    )
    merged["sector_major"] = merged["sector_major"].fillna("기타")
    merged.drop(columns=["sector_major_new"], inplace=True, errors="ignore")

    after_empty  = merged["sector_major"].fillna("").eq("").sum()
    after_filled = merged["sector_major"].fillna("").ne("").sum()

    # STEP 4: 저장
    print("\n[STEP 4] Saving...")
    merged.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")

    # 결과 통계
    print("\n" + "=" * 60)
    print("Processing DONE")
    print(f"  empty before: {before_empty} → empty after: {after_empty}")
    print(f"  filled before: {before_filled} → filled after: {after_filled}")
    print(f"\n[sector_major distribution top 20]")
    listed = merged[merged["stock_code"].str.strip().ne("000000") & merged["stock_code"].str.strip().ne("")]
    print(listed["sector_major"].value_counts().head(20).to_string())
    print("=" * 60)
    print(f"\nSaved: {OUTPUT_FILE}")
    print("\n★ Next steps:")
    print("  Check distribution, then replace original if OK:")
    print(f'  copy /Y "{OUTPUT_FILE}" "{INPUT_FILE}"')
    print("  → Re-run Pipeline → confirm Layer 2.6 sector applied")


if __name__ == "__main__":
    main()
