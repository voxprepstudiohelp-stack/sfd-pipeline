"""
모듈명: sfd_finalize.py
역할:
- sfd_master_signal_latest.csv + sfd_fundamental_latest.csv를 ticker 기준 left join
- 조건 필터링 및 정렬 후 최종 unified signal 파일 생성

요구사항:
- Python 3.14
- pandas

변경이력:
- v1.0: 최초 생성 (RESERVE_BUY, WATCH 필터)
- v1.1: WATCH → WATCH_ONLY 필터 수정 (문자열 불일치 버그 수정)
- encoding: utf-8-sig
"""

import os
import sys
import pandas as pd
from datetime import datetime

# ============================
# 경로 설정 상수
# ============================
BASE_DIR = os.environ.get("SFD_BASE_DIR", r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline")
LATEST_DIR = os.path.join(BASE_DIR, "outputs", "latest")
ARCHIVE_DIR = os.path.join(BASE_DIR, "outputs", "archive")

MASTER_FILE = os.path.join(LATEST_DIR, "sfd_master_signal_latest.csv")
FUND_FILE = os.path.join(LATEST_DIR, "sfd_fundamental_latest.csv")

OUTPUT_LATEST = os.path.join(LATEST_DIR, "sfd_signal.csv")


# ============================
# 파일 존재 확인
# ============================
def check_file_exists(path):
    if not os.path.exists(path):
        print(f"[ERROR] File not found: {path}")
        sys.exit(1)


# ============================
# 메인 실행 함수
# ============================
def main():
    # 1. 파일 검증
    check_file_exists(MASTER_FILE)
    check_file_exists(FUND_FILE)

    # 2. 데이터 로드
    try:
        df_master = pd.read_csv(MASTER_FILE, encoding="utf-8-sig")
        df_fund = pd.read_csv(FUND_FILE, encoding="utf-8-sig")
    except Exception as e:
        print(f"[ERROR] CSV load failed: {e}")
        sys.exit(1)

    # 3. LEFT JOIN (ticker 기준)
    df = pd.merge(
        df_master,
        df_fund,
        on="ticker",
        how="left",
        suffixes=("", "_fund")
    )

    # name 중복 컬럼 제거 (master 우선)
    if "name_fund" in df.columns:
        df.drop(columns=["name_fund"], inplace=True)

    # 4. 필터링 (RESERVE_BUY, WATCH_ONLY)  <- v1.1 수정: WATCH -> WATCH_ONLY
    df = df[df["signal"].isin(["RESERVE_BUY", "WATCH_ONLY"])]

    # 5. 정렬 (adjusted_fund_score 내림차순)
    if "adjusted_fund_score" not in df.columns:
        print("[ERROR] adjusted_fund_score column not found.")
        sys.exit(1)

    df = df.sort_values(by="adjusted_fund_score", ascending=False)

    # 6. fetch_date 기준 archive 경로 결정
    if "fetch_date" in df.columns and not df["fetch_date"].isna().all():
        latest_date = str(df["fetch_date"].dropna().max())
        archive_date = latest_date.replace("-", "").replace("/", "")
    else:
        archive_date = datetime.now().strftime("%Y%m%d")

    archive_path = os.path.join(ARCHIVE_DIR, archive_date)
    os.makedirs(archive_path, exist_ok=True)

    output_archive = os.path.join(archive_path, "sfd_signal.csv")

    # 7. 출력 컬럼 정렬
    final_columns = [
        "fetch_date", "ticker", "name", "signal", "total_score", "adjusted_fund_score",
        "sector_major", "sector_priority_grade", "sector_multiplier",
        "tech_score", "news_score", "investor_score", "theme_score", "fund_score",
        "rsi", "ma_align", "vol_ratio", "mode"
    ]

    # 존재하는 컬럼만 선택 (유연성)
    final_columns = [col for col in final_columns if col in df.columns]
    df = df[final_columns]

    # ticker 6자리 zfill
    if "ticker" in df.columns:
        df["ticker"] = df["ticker"].astype(str).str.zfill(6)

    # 8. 파일 저장
    try:
        df.to_csv(OUTPUT_LATEST, index=False, encoding="utf-8-sig")
        df.to_csv(output_archive, index=False, encoding="utf-8-sig")
    except Exception as e:
        print(f"[ERROR] File save failed: {e}")
        sys.exit(1)

    # 9. 결과 요약
    reserve_count = (df["signal"] == "RESERVE_BUY").sum()
    watch_count = (df["signal"] == "WATCH_ONLY").sum()  # <- v1.1 수정

    print("[SUCCESS] sfd_finalize DONE")
    print(f"RESERVE_BUY count: {reserve_count}")
    print(f"WATCH_ONLY count: {watch_count}")
    print(f"Archive saved: {output_archive}")


# ============================
# 실행
# ============================
if __name__ == "__main__":
    main()
