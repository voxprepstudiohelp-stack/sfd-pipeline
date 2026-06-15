#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sfd_db_migrate_contrib.py
[P_NEW_5] backtest_signals 테이블 스키마 업데이트

추가 컬럼:
  p_contrib  REAL  — p_score / total_score * 100 (가격/기술 기여도 %)
  r_contrib  REAL  — r_score / total_score * 100 (거래량 기여도 %)
  i_contrib  REAL  — i_score / total_score * 100 (갭/수급 기여도 %)

용도:
  - PRISM Engine v1 (P4) 가중치 최적화 입력 데이터
  - sfd_backtest_analyzer.py LinearRegression 분석 지원
  - 향후 p_weight/r_weight/i_weight 동적 조정 근거

실행: python sfd_db_migrate_contrib.py
"""

import sqlite3
import os
import pandas as pd
from datetime import datetime

DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "outputs", "backtest_historical.db"
)

# 로컬 실제 경로 fallback
LOCAL_DB = r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline\outputs\backtest_historical.db"


def get_db_path():
    if os.path.exists(DB_PATH):
        return DB_PATH
    if os.path.exists(LOCAL_DB):
        return LOCAL_DB
    # tools/ 기준 상대경로 탐색
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "outputs", "backtest_historical.db"),
        os.path.join(here, "..", "outputs", "backtest_historical.db"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def migrate():
    db_path = get_db_path()
    if not db_path:
        print("[ERROR] backtest_historical.db 를 찾을 수 없습니다.")
        print("        경로 확인: outputs/backtest_historical.db")
        return False

    print(f"[DB] 경로: {db_path}")
    conn = sqlite3.connect(db_path)

    # ── 현재 컬럼 확인 ──────────────────────────────────────
    cur = conn.execute("PRAGMA table_info(backtest_signals)")
    existing_cols = {row[1] for row in cur.fetchall()}
    print(f"[DB] 기존 컬럼: {sorted(existing_cols)}")

    # ── 컬럼 추가 (없는 것만) ───────────────────────────────
    new_cols = {
        "p_contrib": "REAL DEFAULT NULL",
        "r_contrib": "REAL DEFAULT NULL",
        "i_contrib": "REAL DEFAULT NULL",
    }

    added = []
    for col, typedef in new_cols.items():
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE backtest_signals ADD COLUMN {col} {typedef}")
            added.append(col)
            print(f"[DB] 컬럼 추가: {col}")
        else:
            print(f"[DB] 이미 존재: {col} (스킵)")

    conn.commit()

    if not added:
        print("[DB] 추가할 컬럼 없음 — 이미 최신 스키마")
        conn.close()
        return True

    # ── 기여도 계산 후 UPDATE ───────────────────────────────
    print("[DB] p_contrib / r_contrib / i_contrib 계산 중...")

    df = pd.read_sql("""
        SELECT id, p_score, r_score, i_score, total_score
        FROM backtest_signals
        WHERE total_score IS NOT NULL AND total_score > 0
    """, conn)

    print(f"[DB] 대상 레코드: {len(df):,}건")

    df["p_contrib"] = (df["p_score"] / df["total_score"] * 100).round(2)
    df["r_contrib"] = (df["r_score"] / df["total_score"] * 100).round(2)
    df["i_contrib"] = (df["i_score"] / df["total_score"] * 100).round(2)

    # 배치 UPDATE
    cur = conn.cursor()
    update_sql = """
        UPDATE backtest_signals
        SET p_contrib = ?, r_contrib = ?, i_contrib = ?
        WHERE id = ?
    """
    batch = [
        (row["p_contrib"], row["r_contrib"], row["i_contrib"], row["id"])
        for _, row in df.iterrows()
    ]
    cur.executemany(update_sql, batch)
    conn.commit()

    print(f"[DB] {len(batch):,}건 업데이트 완료")

    # ── 검증 ────────────────────────────────────────────────
    verify = pd.read_sql("""
        SELECT
            COUNT(*)         AS total,
            AVG(p_contrib)   AS avg_p,
            AVG(r_contrib)   AS avg_r,
            AVG(i_contrib)   AS avg_i,
            SUM(CASE WHEN p_contrib IS NOT NULL THEN 1 ELSE 0 END) AS filled
        FROM backtest_signals
    """, conn)
    conn.close()

    print("\n" + "=" * 52)
    print(" [P_NEW_5] DB 스키마 업데이트 완료")
    print(f"   총 레코드  : {verify['total'].iloc[0]:,}건")
    print(f"   contrib 채워진 건수: {verify['filled'].iloc[0]:,}건")
    print(f"   avg p_contrib : {verify['avg_p'].iloc[0]:.1f}%")
    print(f"   avg r_contrib : {verify['avg_r'].iloc[0]:.1f}%")
    print(f"   avg i_contrib : {verify['avg_i'].iloc[0]:.1f}%")
    print("=" * 52)
    print(f"\n완료 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return True


if __name__ == "__main__":
    migrate()
