"""
SFD Signal Tracker v1.0
- 시그널 발생 시점부터 D+1/D+3/D+5 결과를 자동 추적
- SQLite DB 사용 (data/sfd_tracker.db)
- 매일 파이프라인 실행 시 자동 업데이트
"""

import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import json
import logging

log = logging.getLogger("SFD_TRACKER")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")

PIPELINE_ROOT = Path(__file__).parent.parent
DB_PATH = PIPELINE_ROOT / "data" / "sfd_tracker.db"


def init_db():
    """DB 초기화 — 테이블 생성"""
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 시그널 발생 테이블
    c.execute("""
    CREATE TABLE IF NOT EXISTS signal_log (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_date  TEXT NOT NULL,        -- 시그널 발생일 YYYYMMDD
        ticker       TEXT NOT NULL,
        name         TEXT,
        signal       TEXT,                 -- RESERVE_BUY / WATCH_ONLY
        total_score  REAL,
        tech_score   REAL,
        news_score   REAL,
        investor_score REAL,
        theme_score  REAL,
        fund_score   REAL,
        entry_price  REAL,                 -- 발생일 종가
        -- D+1/D+3/D+5 결과
        price_d1     REAL,
        price_d3     REAL,
        price_d5     REAL,
        return_d1    REAL,
        return_d3    REAL,
        return_d5    REAL,
        win_d1       INTEGER,              -- 1=승 0=패
        win_d3       INTEGER,
        win_d5       INTEGER,
        -- 컨텍스트
        foreign_net_buy   REAL,
        institution_net_buy REAL,
        pension_net_buy   REAL,
        vol_ratio    REAL,
        rsi          REAL,
        sector       TEXT,
        -- 상태
        status       TEXT DEFAULT 'PENDING',  -- PENDING/D1_DONE/D3_DONE/COMPLETE
        created_at   TEXT,
        updated_at   TEXT,
        UNIQUE(signal_date, ticker)
    )""")

    # 일별 성과 요약 테이블
    c.execute("""
    CREATE TABLE IF NOT EXISTS daily_performance (
        perf_date     TEXT PRIMARY KEY,
        total_signals INTEGER,
        reserve_buy   INTEGER,
        watch_only    INTEGER,
        win_d1        INTEGER,
        win_rate_d1   REAL,
        avg_return_d1 REAL,
        best_ticker   TEXT,
        best_return   REAL,
        worst_ticker  TEXT,
        worst_return  REAL,
        created_at    TEXT
    )""")

    conn.commit()
    conn.close()
    log.info(f"✅ DB 초기화 완료: {DB_PATH}")


def register_signals(signal_date: str = None):
    """
    오늘 시그널을 DB에 등록
    signal_date: YYYYMMDD (None이면 오늘)
    """
    if signal_date is None:
        signal_date = datetime.now().strftime("%Y%m%d")

    # master_signal CSV 로드
    csv_path = PIPELINE_ROOT / "outputs" / "latest" / "sfd_master_signal_latest.csv"
    if not csv_path.exists():
        log.warning(f"master_signal CSV 없음: {csv_path}")
        return 0

    df = pd.read_csv(csv_path, encoding="utf-8-sig")

    # RESERVE_BUY / WATCH_ONLY 필터
    targets = df[df["signal"].isin(["RESERVE_BUY", "WATCH_ONLY"])].copy()
    if targets.empty:
        log.info("등록할 시그널 없음")
        return 0

    # prev_close에서 진입가 조회
    prev_close_path = PIPELINE_ROOT / "outputs" / "latest" / "sfd_prev_close_latest.csv"
    price_map = {}
    if prev_close_path.exists():
        pc = pd.read_csv(prev_close_path, encoding="utf-8-sig")
        if "ticker" in pc.columns and "close" in pc.columns:
            price_map = dict(zip(pc["ticker"].astype(str), pc["close"]))

    # investor_flow 로드
    flow_path = PIPELINE_ROOT / "outputs" / "latest" / "sfd_investor_flow_latest.csv"
    flow_map = {}
    if flow_path.exists():
        fl = pd.read_csv(flow_path, encoding="utf-8-sig")
        for _, row in fl.iterrows():
            flow_map[str(row.get("ticker", ""))] = {
                "foreign": row.get("foreign_net_buy", 0),
                "institution": row.get("institution_net_buy", 0),
                "pension": row.get("pension_net_buy", 0),
            }

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()
    registered = 0

    for _, row in targets.iterrows():
        ticker = str(row.get("ticker", ""))
        flow = flow_map.get(ticker, {})

        try:
            c.execute("""
            INSERT OR IGNORE INTO signal_log
            (signal_date, ticker, name, signal, total_score,
             tech_score, news_score, investor_score, theme_score, fund_score,
             entry_price, foreign_net_buy, institution_net_buy, pension_net_buy,
             vol_ratio, rsi, sector, status, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                signal_date,
                ticker,
                str(row.get("name", "")),
                str(row.get("signal", "")),
                float(row.get("total_score", 0) or 0),
                float(row.get("tech_score", 0) or 0),
                float(row.get("news_score", 0) or 0),
                float(row.get("investor_score", 0) or 0),
                float(row.get("theme_score", 0) or 0),
                float(row.get("fund_score", 0) or 0),
                float(price_map.get(ticker, 0) or 0),
                float(flow.get("foreign", 0) or 0),
                float(flow.get("institution", 0) or 0),
                float(flow.get("pension", 0) or 0),
                float(row.get("vol_ratio", 0) or 0),
                float(row.get("rsi", 0) or 0),
                str(row.get("sector", "UNKNOWN")),
                "PENDING",
                now, now
            ))
            if c.rowcount > 0:
                registered += 1
        except Exception as e:
            log.error(f"등록 실패 {ticker}: {e}")

    conn.commit()
    conn.close()
    log.info(f"✅ 시그널 등록: {registered}건 ({signal_date})")
    return registered


def update_results():
    """
    PENDING 시그널의 D+1/D+3/D+5 결과 자동 업데이트
    prev_close_latest.csv 현재가 기준
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 미완료 시그널 조회
    pending = c.execute("""
        SELECT id, signal_date, ticker, entry_price, status
        FROM signal_log
        WHERE status != 'COMPLETE' AND entry_price > 0
    """).fetchall()

    if not pending:
        log.info("업데이트할 PENDING 시그널 없음")
        conn.close()
        return

    # 현재가 로드
    prev_close_path = PIPELINE_ROOT / "outputs" / "latest" / "sfd_prev_close_latest.csv"
    price_map = {}
    if prev_close_path.exists():
        pc = pd.read_csv(prev_close_path, encoding="utf-8-sig")
        if "ticker" in pc.columns and "close" in pc.columns:
            price_map = dict(zip(pc["ticker"].astype(str), pc["close"]))

    today = datetime.now()
    updated = 0

    for row_id, signal_date, ticker, entry_price, status in pending:
        sig_dt = datetime.strptime(signal_date, "%Y%m%d")
        days_elapsed = (today - sig_dt).days
        current_price = float(price_map.get(ticker, 0) or 0)

        if current_price <= 0 or entry_price <= 0:
            continue

        ret = (current_price - entry_price) / entry_price * 100
        win = 1 if ret > 0 else 0

        update_fields = {"updated_at": today.isoformat()}

        if days_elapsed >= 1 and status == "PENDING":
            update_fields.update({
                "price_d1": current_price,
                "return_d1": round(ret, 2),
                "win_d1": win,
                "status": "D1_DONE"
            })
        elif days_elapsed >= 3 and status == "D1_DONE":
            update_fields.update({
                "price_d3": current_price,
                "return_d3": round(ret, 2),
                "win_d3": win,
                "status": "D3_DONE"
            })
        elif days_elapsed >= 5 and status == "D3_DONE":
            update_fields.update({
                "price_d5": current_price,
                "return_d5": round(ret, 2),
                "win_d5": win,
                "status": "COMPLETE"
            })

        if len(update_fields) > 1:
            set_clause = ", ".join([f"{k}=?" for k in update_fields.keys()])
            c.execute(
                f"UPDATE signal_log SET {set_clause} WHERE id=?",
                list(update_fields.values()) + [row_id]
            )
            updated += 1

    conn.commit()
    conn.close()
    log.info(f"✅ 결과 업데이트: {updated}건")


def get_win_rate_summary() -> dict:
    """
    현재까지 누적 승률 요약 반환
    → 주간 리뷰 레포트용
    """
    conn = sqlite3.connect(DB_PATH)

    summary = {}

    # 전체 승률
    df = pd.read_sql("""
        SELECT signal, win_d1, win_d3, win_d5, return_d1, return_d3, return_d5
        FROM signal_log
        WHERE status != 'PENDING'
    """, conn)

    if df.empty:
        conn.close()
        return {"status": "데이터 없음 — 시그널 누적 중"}

    for sig in ["RESERVE_BUY", "WATCH_ONLY"]:
        sub = df[df["signal"] == sig]
        if sub.empty:
            continue
        summary[sig] = {
            "건수": len(sub),
            "D+1승률": f"{sub['win_d1'].mean()*100:.1f}%" if sub['win_d1'].notna().any() else "N/A",
            "D+3승률": f"{sub['win_d3'].mean()*100:.1f}%" if sub['win_d3'].notna().any() else "N/A",
            "D+5승률": f"{sub['win_d5'].mean()*100:.1f}%" if sub['win_d5'].notna().any() else "N/A",
            "D+1평균수익": f"{sub['return_d1'].mean():.2f}%" if sub['return_d1'].notna().any() else "N/A",
        }

    # 점수 구간별 승률
    df_complete = df[df["win_d1"].notna()].copy()
    if not df_complete.empty:
        score_df = pd.read_sql("""
            SELECT total_score, win_d1, return_d1
            FROM signal_log WHERE win_d1 IS NOT NULL
        """, conn)
        bins = [0, 50, 60, 70, 80, 200]
        labels = ["<50", "50-59", "60-69", "70-79", "80+"]
        score_df["구간"] = pd.cut(score_df["total_score"], bins=bins, labels=labels)
        score_summary = score_df.groupby("구간").agg(
            건수=("win_d1", "count"),
            승률=("win_d1", "mean"),
            평균수익=("return_d1", "mean")
        ).round(3)
        summary["score_breakdown"] = score_summary.to_dict()

    conn.close()
    return summary


def run():
    """파이프라인에서 호출 — 등록 + 업데이트 순서로 실행"""
    init_db()
    update_results()   # 기존 PENDING 먼저 업데이트
    registered = register_signals()  # 오늘 신호 등록
    summary = get_win_rate_summary()
    log.info(f"📊 누적 승률 요약: {json.dumps(summary, ensure_ascii=False)}")
    return summary


if __name__ == "__main__":
    run()
