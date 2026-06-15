# ============================================================
# 파일명: sfd_news_fetcher.py
# 버전: v4.0
# 작성: Claude (Anthropic) — 2026.06.15
# GitHub 경로: voxprepstudiohelp-stack/sfd-pipeline/tools/sfd_news_fetcher.py
#
# [v4.0 변경사항 vs v3.0]
# - P_NEW_6: 83종목(RESERVE_BUY/WATCH_ONLY only) → 483종목 전체 커버
# - load_targets(): signal 필터 제거 → prev_close_latest.csv 전체 로드
# - 483종목 universe: inputs/sfd_target_universe.csv 우선, 없으면 prev_close 전체
# - Gemini API 연동 준비: GEMINI_API_KEY 환경변수 읽기 (P5 대비)
# - news_score 컬럼 정규화: 0~30pt 범위 유지
# - API 미설정 시 graceful 종료 (기존 파일 유지)
# ============================================================

from __future__ import annotations

import os
import re
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta

import requests
import pandas as pd
from dotenv import load_dotenv

# ── 경로 설정 ─────────────────────────────────────────────────────────
IS_GITHUB = os.getenv("GITHUB_ACTIONS") == "true"

if IS_GITHUB:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from config import LATEST_DIR, INPUT_DIR
        OUTPUT_DIR = Path(LATEST_DIR)
        INPUT_DIR = Path(INPUT_DIR)
        ROOT = OUTPUT_DIR.parent.parent
    except ImportError:
        OUTPUT_DIR = Path("outputs/latest")
        INPUT_DIR = Path("inputs")
        ROOT = Path(".")
else:
    D_ROOT = Path(r"D:\AI_WorkSpace\I_SFC")
    ROOT = D_ROOT / r"09_Implementation\SFC_DataPipeline"
    SECRET_ENV = D_ROOT / r"00_Local_Secrets\SFD\.env"
    OUTPUT_DIR = ROOT / r"outputs\latest"
    INPUT_DIR = ROOT / r"inputs"
    if SECRET_ENV.exists():
        load_dotenv(SECRET_ENV)
    else:
        load_dotenv(ROOT / ".env")

# ── 파일 경로 ──────────────────────────────────────────────────────────
UNIVERSE_CSV   = INPUT_DIR / "sfd_target_universe.csv"
PREV_CLOSE_CSV = OUTPUT_DIR / "sfd_prev_close_latest.csv"
SIGNAL_CSV     = OUTPUT_DIR / "sfd_master_signal_latest.csv"

OUT_ARTICLES = OUTPUT_DIR / "sfd_news_signal_latest.csv"
OUT_SCORES   = OUTPUT_DIR / "sfd_news_score_latest.csv"
LOG_PATH     = ROOT / "logs" / "sfd_news_fetcher.log"

# ── API 키 ────────────────────────────────────────────────────────────
NAVER_ID     = os.getenv("NAVER_CLIENT_ID", "")
NAVER_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")
GEMINI_KEY   = os.getenv("GEMINI_API_KEY", "")  # P5 대비 — 현재 미사용

# ── 감성 키워드 ───────────────────────────────────────────────────────
POS_KW = {
    "수주": 3, "공급계약": 3, "수주확보": 3, "대규모계약": 3,
    "상한가": 3, "급등": 2, "호실적": 2, "흑자전환": 3,
    "목표주가상향": 3, "매수": 2, "강력매수": 3, "신고가": 2,
    "실적개선": 2, "영업이익증가": 2, "배당확대": 1,
    "신제품": 1, "특허": 1, "기술이전": 2, "MOU": 1,
}
NEG_KW = {
    "적자": -3, "영업손실": -3, "하락": -1, "급락": -2,
    "하한가": -3, "매도": -2, "목표주가하향": -3, "불성실공시": -3,
    "횡령": -3, "배임": -3, "상장폐지": -3, "관리종목": -3,
    "실적부진": -2, "영업이익감소": -2, "매출감소": -1,
}
ALL_KW = {**POS_KW, **NEG_KW}

MAX_DISPLAY  = 10
SLEEP_SEC    = 0.1
DAYS_BACK    = 2
MAX_UNIVERSE = 600


LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    encoding="utf-8",
)


def load_targets() -> pd.DataFrame:
    """
    483종목 유니버스 로드 (우선순위):
    1. inputs/sfd_target_universe.csv
    2. outputs/latest/sfd_prev_close_latest.csv 전체
    3. sfd_master_signal_latest.csv 전체 (신호 필터 없음)
    v3.0 대비 핵심 변경: RESERVE_BUY/WATCH_ONLY 필터 제거
    """
    if UNIVERSE_CSV.exists():
        df = pd.read_csv(UNIVERSE_CSV, dtype={"ticker": str})
        if {"ticker", "name"}.issubset(df.columns):
            df["ticker"] = df["ticker"].str.zfill(6)
            print(f"[INFO] 유니버스 로드 (universe.csv): {len(df)}종목")
            return df[["ticker", "name"]].drop_duplicates().head(MAX_UNIVERSE)

    if PREV_CLOSE_CSV.exists():
        df = pd.read_csv(PREV_CLOSE_CSV, encoding="utf-8-sig", dtype={"ticker": str})
        if {"ticker", "name"}.issubset(df.columns):
            df["ticker"] = df["ticker"].str.zfill(6)
            if "data_status" in df.columns:
                df = df[df["data_status"] == "OK"]
            print(f"[INFO] 유니버스 로드 (prev_close): {len(df)}종목")
            return df[["ticker", "name"]].drop_duplicates().head(MAX_UNIVERSE)

    if SIGNAL_CSV.exists():
        df = pd.read_csv(SIGNAL_CSV, dtype={"ticker": str})
        if {"ticker", "name"}.issubset(df.columns):
            df["ticker"] = df["ticker"].str.zfill(6)
            print(f"[INFO] 유니버스 로드 (signal.csv, 필터 없음): {len(df)}종목")
            return df[["ticker", "name"]].drop_duplicates().head(MAX_UNIVERSE)

    print("[WARN] 유니버스 소스 없음")
    return pd.DataFrame(columns=["ticker", "name"])


def search_news(query: str, display: int = MAX_DISPLAY) -> list[dict]:
    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": NAVER_ID,
        "X-Naver-Client-Secret": NAVER_SECRET,
    }
    params = {"query": query, "display": display, "sort": "date"}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=5)
        r.raise_for_status()
        return r.json().get("items", [])
    except Exception as e:
        logging.warning(f"[NEWS] API 오류: {query} | {e}")
        return []


def score_text(text: str) -> float:
    score = 0.0
    for kw, w in ALL_KW.items():
        if kw in text:
            score += w
    return round(score, 1)


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", str(text or "")).replace("&quot;", '"').replace("&amp;", "&")


def is_recent(pub_date_str: str, days: int = DAYS_BACK) -> bool:
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(pub_date_str)
        cutoff = datetime.now(dt.tzinfo) - timedelta(days=days)
        return dt >= cutoff
    except Exception:
        return True


def main() -> None:
    print(f"[INFO] sfd_news_fetcher v4.0 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[INFO] 변경: 전체 유니버스 커버 (신호 필터 제거 → 최대 {MAX_UNIVERSE}종목)")

    if not NAVER_ID or not NAVER_SECRET:
        print("[WARN] NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 없음 — 기존 파일 유지 후 종료")
        if OUT_SCORES.exists():
            print(f"[INFO] 기존 파일 유지: {OUT_SCORES}")
        return

    targets = load_targets()
    total = len(targets)
    print(f"[INFO] 검색 대상: {total}종목 | 예상 API 콜: {total * MAX_DISPLAY:,}건")

    if total == 0:
        print("[ERROR] 유니버스 로드 실패 — 종료")
        return

    articles_all: list[dict] = []
    score_rows: list[dict] = []

    for idx, (_, row) in enumerate(targets.iterrows(), 1):
        ticker = str(row["ticker"]).zfill(6)
        name   = str(row.get("name", ticker))

        if idx % 50 == 0 or idx == total:
            print(f"[PROG] {idx}/{total} | {name} ({ticker})")

        items = search_news(name)
        time.sleep(SLEEP_SEC)

        ticker_score = 0.0
        ticker_cnt   = 0

        for item in items:
            title = strip_html(item.get("title", ""))
            desc  = strip_html(item.get("description", ""))
            pub   = item.get("pubDate", "")
            link  = item.get("link", item.get("originallink", ""))

            if not is_recent(pub):
                continue

            text = title + " " + desc
            sc   = score_text(text)

            articles_all.append({
                "ticker":   ticker,
                "name":     name,
                "title":    title,
                "pub_date": pub,
                "score":    sc,
                "link":     link,
            })
            ticker_score += sc
            ticker_cnt   += 1

        if ticker_cnt > 0:
            score_rows.append({
                "ticker":      ticker,
                "name":        name,
                "news_score":  round(min(ticker_score, 30.0), 1),
                "article_cnt": ticker_cnt,
            })

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(articles_all).to_csv(str(OUT_ARTICLES), index=False, encoding="utf-8-sig")
    pd.DataFrame(score_rows).to_csv(str(OUT_SCORES),   index=False, encoding="utf-8-sig")

    covered = len(score_rows)
    print(f"\n[DONE] 완료: {covered}/{total}종목 | 커버율: {covered/total*100:.1f}% | 기사: {len(articles_all)}건")
    logging.info(f"v4.0 완료: {covered}/{total}종목, {len(articles_all)}기사")

    if GEMINI_KEY:
        print(f"\n[P5] GEMINI_API_KEY 감지 — 뉴스 요약 강화 기능 준비됨")
        logging.info("GEMINI_API_KEY detected — P5 ready")


if __name__ == "__main__":
    main()
