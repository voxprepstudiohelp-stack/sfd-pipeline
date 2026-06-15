# 파일명: sfd_news_fetcher.py
# 버전: v3.0 — 네이버 뉴스 API 통합 (NAVER_CLIENT_ID/SECRET)
# 작성: Claude (Anthropic) — 2026.05.27
# 변경점 v2.0 → v3.0:
#   - 네이버 뉴스 검색 API 적용 (무료 25,000건/일)
#   - RESERVE_BUY + WATCH_ONLY 대상 종목만 검색 (효율화)
#   - 감성 점수 산출 로직 고도화 (키워드 가중치)
#   - API 미설정 시 graceful 종료 (기존 파일 유지)

from __future__ import annotations

import os, time, logging
from pathlib import Path
from datetime import datetime, timedelta

import requests
import pandas as pd
from dotenv import load_dotenv

# ── 경로 설정 ────────────────────────────────────────────────────────
ROOT        = Path(__file__).resolve().parents[1]
OUTPUTS     = ROOT / "outputs" / "latest"
INPUTS      = ROOT / "inputs"
OUTPUTS.mkdir(parents=True, exist_ok=True)

load_dotenv(ROOT / ".env")

NAVER_ID     = os.getenv("NAVER_CLIENT_ID", "")
NAVER_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")

# ── 출력 파일 ─────────────────────────────────────────────────────────
NEWS_SIGNAL_PATH = OUTPUTS / "sfd_news_signal_latest.csv"
NEWS_SCORE_PATH  = OUTPUTS / "sfd_news_score_latest.csv"

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

MAX_DISPLAY  = 10    # 종목당 최대 기사 수 (API 1콜)
SLEEP_SEC    = 0.1   # 호출 간격 (100ms)
DAYS_BACK    = 2     # 최근 N일 기사만 채택


def search_news(query: str, display: int = MAX_DISPLAY) -> list[dict]:
    """네이버 뉴스 검색 API 호출 — 실패 시 빈 리스트 반환"""
    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id":     NAVER_ID,
        "X-Naver-Client-Secret": NAVER_SECRET,
    }
    params = {"query": query, "display": display, "sort": "date"}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=5)
        r.raise_for_status()
        return r.json().get("items", [])
    except Exception as e:
        logging.warning(f"[NEWS] API ERROR: {query} | {e}")
        return []


def score_text(text: str) -> float:
    """제목+설명 감성 점수 산출"""
    score = 0.0
    for kw, w in ALL_KW.items():
        if kw in text:
            score += w
    return round(score, 1)


def strip_html(text: str) -> str:
    """네이버 API 반환 HTML 태그 제거"""
    import re
    return re.sub(r"<[^>]+>", "", text)


def load_targets() -> pd.DataFrame:
    """RESERVE_BUY + WATCH_ONLY 종목 로드"""
    for fn in ["sfd_master_signal_latest.csv", "sfd_signal.csv"]:
        p = OUTPUTS / fn
        if p.exists():
            df = pd.read_csv(p, dtype={"ticker": str})
            if "signal" in df.columns:
                target = df[df["signal"].isin(["RESERVE_BUY", "WATCH_ONLY"])]
                if len(target) > 0:
                    return target[["ticker", "name"]].drop_duplicates()
    # fallback: prev_close 전체 (최대 200)
    p = INPUTS / "sfd_prev_close_input.csv"
    if p.exists():
        df = pd.read_csv(p, dtype={"ticker": str})
        return df[["ticker", "name"]].head(200)
    return pd.DataFrame(columns=["ticker", "name"])


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    print(f"[INFO] sfd_news_fetcher v3.0 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if not NAVER_ID or not NAVER_SECRET:
        print("[WARN] NAVER_CLIENT_ID / NAVER_CLIENT_SECRET not found — keeping existing files and exiting")
        if NEWS_SCORE_PATH.exists():
            print(f"[INFO] Keeping existing news file: {NEWS_SCORE_PATH}")
        return

    targets = load_targets()
    print(f"[INFO] STOCK_MAP loading done: {len(targets)} target tickers")

    articles_all: list[dict] = []
    score_rows:   list[dict] = []

    for _, row in targets.iterrows():
        ticker = str(row["ticker"]).zfill(6)
        name   = str(row.get("name", ticker))
        items  = search_news(name)
        time.sleep(SLEEP_SEC)

        ticker_score = 0.0
        ticker_cnt   = 0

        for item in items:
            title = strip_html(item.get("title", ""))
            desc  = strip_html(item.get("description", ""))
            pub   = item.get("pubDate", "")
            link  = item.get("link", item.get("originallink", ""))

            text  = title + " " + desc
            sc    = score_text(text)

            articles_all.append({
                "ticker":    ticker,
                "name":      name,
                "title":     title,
                "pub_date":  pub,
                "score":     sc,
                "link":      link,
            })
            ticker_score += sc
            ticker_cnt   += 1

        if ticker_cnt > 0:
            score_rows.append({
                "ticker":      ticker,
                "name":        name,
                "news_score":  round(ticker_score, 1),
                "article_cnt": ticker_cnt,
            })

    df_signal = pd.DataFrame(articles_all)
    df_score  = pd.DataFrame(score_rows)

    df_signal.to_csv(NEWS_SIGNAL_PATH, index=False, encoding="utf-8-sig")
    df_score.to_csv(NEWS_SCORE_PATH,   index=False, encoding="utf-8-sig")

    tickers_hit = df_score[df_score["news_score"] != 0]["ticker"].nunique() if len(df_score) else 0
    print(f"[OK] articles={len(df_signal)} | tickers={len(df_score)} | sentiment_hit={tickers_hit}")
    print(f"     -> {NEWS_SIGNAL_PATH}")
    print(f"     -> {NEWS_SCORE_PATH}")


if __name__ == "__main__":
    main()
