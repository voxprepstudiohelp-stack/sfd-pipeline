# -*- coding: utf-8 -*-
# sfd_sector_manual_patch.py
# 목적: 200 모니터링 종목 수동 sector_major 매핑 + company_master 업데이트
# 작성: Claude (Anthropic) 2026-05-24

import pandas as pd
import os

MASTER = r"D:\AI_WorkSpace\I_SFC\01_DB\sfd_company_master_v1.4_with_financials.csv"
FUND   = r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline\outputs\latest\sfd_fundamental_latest.csv"

# =====================================================
# 수동 매핑 테이블 (ticker → sector_major)
# 기준: SFD 공식 taxonomy
# =====================================================
MANUAL_MAP = {
    # 지주사/그룹사
    "006260": "전력/전선/변압기",  # LS (전선·케이블 주력)
    "003550": "인터넷/플랫폼",     # LG (지주사)
    "034730": "에너지/정유",        # SK (지주사)
    "060980": "자동차/부품",        # HL홀딩스
    "001800": "식품/소비재",        # 오리온홀딩스
    "003555": "자동차/부품",        # LG우

    # 금속/소재
    "024840": "철강/금속",          # KBI메탈
    "275630": "반도체",             # 에스에스알 (반도체 부품)

    # 자동차/부품
    "005850": "자동차/부품",        # 에스엘 (차량 조명)
    "010770": "자동차/부품",        # 평화홀딩스

    # 식품/소비재
    "001130": "식품/소비재",        # 대한제분
    "033780": "식품/소비재",        # KT&G
    "215480": "식품/소비재",        # 토박스코리아

    # IT/인터넷
    "043360": "인터넷/플랫폼",      # 디지아이
    "079940": "인터넷/플랫폼",      # 가비아
    "054800": "인터넷/플랫폼",      # 아이디스홀딩스
    "018260": "인터넷/플랫폼",      # 삼성에스디에스
    "056200": "인터넷/플랫폼",      # 에프앤가이드 → 미디어
    "066980": "화학/소재",          # 한성크린텍

    # 전력/전선
    "037460": "전력/전선/변압기",   # 삼지전자

    # 유통
    "004170": "유통/물류",          # 신세계

    # 바이오/제약/의료
    "008490": "바이오/제약",        # 서흥 (캡슐)
    "031510": "의료기기",           # 오스템임플란트

    # 섬유
    "088790": "섬유/의류",          # 진도 (모피)

    # 기계/장비
    "065130": "기계/장비",          # 탑엔지니어링

    # 금융
    "088350": "금융",               # 한화생명
    "473050": "금융",               # 유안타제15호스팩
    "477340": "금융",               # 에이치엠씨제7호스팩

    # 전자/기타
    "187870": "반도체",             # 디바이스이엔지 (반도체 장비)
    "043910": "환경",               # 자연과환경
    "356680": "통신/네트워크",      # 엑스게이트 (네트워크 보안)
}

def main():
    print("=" * 60)
    print("SFD 200-ticker sector manual mapping patch")
    print("=" * 60)

    fund = pd.read_csv(FUND, dtype={"ticker": str})
    fund["ticker"] = fund["ticker"].str.zfill(6)
    tickers_200 = set(fund["ticker"].tolist())
    print(f"Monitoring tickers: {len(tickers_200)}")

    master = pd.read_csv(MASTER, dtype={"stock_code": str}, low_memory=False)
    master["stock_code"] = master["stock_code"].str.zfill(6)
    before = master["sector_major"].fillna("").eq("").sum()
    print(f"sector blank before patch: {before}")

    # 수동 매핑 적용 (200 종목 중 매핑 대상만, 공백인 경우만)
    patched = 0
    for ticker, sector in MANUAL_MAP.items():
        mask = (master["stock_code"] == ticker) & \
               (master["sector_major"].fillna("").str.strip() == "")
        if mask.any():
            master.loc[mask, "sector_major"] = sector
            name = fund[fund["ticker"] == ticker]["name"].values
            print(f"  patch: {ticker} {name[0] if len(name) else '?':15s} → {sector}")
            patched += 1

    after = master["sector_major"].fillna("").eq("").sum()
    print(f"\nPatched: {patched} records")
    print(f"sector blank after patch: {after} (reduced by: {before - after})")

    master.to_csv(MASTER, index=False, encoding="utf-8-sig")
    print(f"\n✅ Saved: {MASTER}")

    # 최종 200종목 매핑 현황
    merged = fund[["ticker", "name"]].merge(
        master[["stock_code", "sector_major"]],
        left_on="ticker", right_on="stock_code", how="left"
    )
    filled = merged[merged["sector_major"].notna() & (merged["sector_major"].str.strip() != "")]
    empty  = merged[merged["sector_major"].isna() | (merged["sector_major"].str.strip() == "")]
    print(f"\n=== Final 200-ticker mapping status ===")
    print(f"OK: {len(filled)} / FAIL(NEUTRAL): {len(empty)}")
    print("\n[All unmapped tickers]")
    print(empty[["ticker", "name"]].to_string(index=False))


if __name__ == "__main__":
    main()
