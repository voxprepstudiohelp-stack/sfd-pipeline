# -*- coding: utf-8 -*-
# sfd_sector_check.py — 200종목 sector 매핑 진단
import pandas as pd
import os

BASE = r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline"
MASTER = r"D:\AI_WorkSpace\I_SFC\01_DB\sfd_company_master_v1.4_with_financials.csv"
FUND   = os.path.join(BASE, "outputs", "latest", "sfd_fundamental_latest.csv")

df     = pd.read_csv(FUND, dtype={"ticker": str})
master = pd.read_csv(MASTER, dtype={"stock_code": str},
                     usecols=["stock_code", "corp_name", "sector_major"],
                     low_memory=False)
master["stock_code"] = master["stock_code"].str.zfill(6)
df["ticker"]         = df["ticker"].str.zfill(6)

merged = df[["ticker","name"]].merge(master, left_on="ticker",
                                      right_on="stock_code", how="left")
filled = merged[merged["sector_major"].notna() & (merged["sector_major"].str.strip() != "")]
empty  = merged[merged["sector_major"].isna() | (merged["sector_major"].str.strip() == "")]

print(f"=== 200-ticker sector mapping results ===")
print(f"Mapping OK: {len(filled)}")
print(f"Mapping FAIL: {len(empty)}")

if len(filled):
    print("\n[Mapped tickers]")
    print(filled[["ticker","name","sector_major"]].to_string(index=False))

print("\n[Mapping FAIL top 30 - check corp_name]")
sample = empty[["ticker","name"]].merge(
    master[["stock_code","corp_name","sector_major"]],
    left_on="ticker", right_on="stock_code", how="left"
)
print(sample[["ticker","name","corp_name","sector_major"]].head(30).to_string(index=False))
