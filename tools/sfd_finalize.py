# -*- coding: utf-8 -*-
"""
sfd_finalize.py v1.2
역할:
- sfd_master_signal_latest.csv + sfd_fundamental_latest.csv → ticker 기준 LEFT JOIN
- 최종 unified signal 파일 sfd_signal.csv 생성

수정: Claude (Anthropic) 2026-05-30
  v1.1 → v1.2
  ① adjusted_fund_score 컬럼 없을 시 FATAL exit → graceful fallback
     (total_score를 adjusted_fund_score로 대체하여 계속 진행)
  ② SFD_BASE_DIR 환경변수 기반 경로
  ③ tech_total_score / vol_gap_score / std_bar_score 컬럼 추가 지원 (L2.7 v1.1)
"""

import os
import sys
import pandas as pd
from datetime import datetime

_BASE = os.environ.get(
    "SFD_BASE_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)
LATEST_DIR   = os.path.join(_BASE, "outputs", "latest")
ARCHIVE_DIR  = os.path.join(_BASE, "outputs", "archive")

MASTER_FILE   = os.path.join(LATEST_DIR, "sfd_master_signal_latest.csv")
FUND_FILE     = os.path.join(LATEST_DIR, "sfd_fundamental_latest.csv")
OUTPUT_LATEST = os.path.join(LATEST_DIR, "sfd_signal.csv")


def check_file_exists(path):
    if not os.path.exists(path):
        print(f"[ERROR] 파일이 존재하지 않습니다: {path}")
        sys.exit(1)


def main():
    check_file_exists(MASTER_FILE)
    check_file_exists(FUND_FILE)

    try:
        df_master = pd.read_csv(MASTER_FILE, encoding="utf-8-sig", dtype={"ticker": str})
        df_fund   = pd.read_csv(FUND_FILE,   encoding="utf-8-sig", dtype={"ticker": str})
    except Exception as e:
        print(f"[ERROR] CSV 로드 실패: {e}")
        sys.exit(1)

    df_master["ticker"] = df_master["ticker"].astype(str).str.strip().str.zfill(6)
    df_fund["ticker"]   = df_fund["ticker"].astype(str).str.strip().str.zfill(6)

    df = pd.merge(df_master, df_fund, on="ticker", how="left", suffixes=("", "_fund"))

    if "name_fund" in df.columns:
        df.drop(columns=["name_fund"], inplace=True)

    df = df[df["signal"].isin(["RESERVE_BUY", "WATCH_ONLY"])]

    # ★ v1.2 핵심: adjusted_fund_score 없으면 total_score로 graceful fallback
    if "adjusted_fund_score" not in df.columns or df["adjusted_fund_score"].isna().all():
        print("[WARN] adjusted_fund_score 컬럼 없음 → total_score로 대체 (fallback)")
        df["adjusted_fund_score"] = df.get("total_score", pd.Series([0.0] * len(df)))
    else:
        mask = df["adjusted_fund_score"].isna()
        if mask.any():
            df.loc[mask, "adjusted_fund_score"] = df.loc[mask, "total_score"].fillna(0.0)

    df = df.sort_values(by="adjusted_fund_score", ascending=False)

    if "fetch_date" in df.columns and not df["fetch_date"].isna().all():
        latest_date  = str(df["fetch_date"].dropna().max())
        archive_date = latest_date.replace("-", "").replace("/", "")
    else:
        archive_date = datetime.now().strftime("%Y%m%d")

    archive_path = os.path.join(ARCHIVE_DIR, archive_date)
    os.makedirs(archive_path, exist_ok=True)
    output_archive = os.path.join(archive_path, "sfd_signal.csv")

    desired_columns = [
        "fetch_date", "ticker", "name", "signal", "total_score",
        "adjusted_fund_score",
        "sector_major", "sector_priority_grade", "sector_multiplier",
        "tech_total_score", "tech_detail_score",
        "vol_gap_score", "std_bar_score",
        "tech_score", "news_score", "investor_score", "theme_score", "fund_score",
        "rsi", "ma_align", "vol_ratio", "mode"
    ]
    final_columns = [col for col in desired_columns if col in df.columns]
    df = df[final_columns]

    if "ticker" in df.columns:
        df["ticker"] = df["ticker"].astype(str).str.zfill(6)

    try:
        df.to_csv(OUTPUT_LATEST,  index=False, encoding="utf-8-sig")
        df.to_csv(output_archive, index=False, encoding="utf-8-sig")
    except Exception as e:
        print(f"[ERROR] 파일 저장 실패: {e}")
        sys.exit(1)

    reserve_count = (df["signal"] == "RESERVE_BUY").sum()
    watch_count   = (df["signal"] == "WATCH_ONLY").sum()

    print("[SUCCESS] sfd_finalize 완료")
    print(f"RESERVE_BUY 건수: {reserve_count}")
    print(f"WATCH_ONLY  건수: {watch_count}")
    print(f"Archive 저장: {output_archive}")


if __name__ == "__main__":
    main()
