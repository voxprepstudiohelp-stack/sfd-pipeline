# ============================================================
# 파일명: sfd_news_fetcher.py
# 버전: v2.0
# 작성: Claude (Anthropic) — 2026-05-21
# GitHub 경로: voxprepstudiohelp-stack/sfd-pipeline/tools/sfd_news_fetcher.py
#
# [v2.0 변경사항]
# - STOCK_MAP 하드코딩 제거
#   → outputs/latest/sfd_prev_close_latest.csv 에서 동적 로드 (2770종목)
# - 출력 파일 추가: outputs/latest/sfd_news_score_latest.csv (ticker별 집계)
# - importance_score 정규화: 0~10 범위 (기존 50~100 → 수정)
# - 쿼리 소스 단일화: inputs/sfd_naver_news_queries.csv 만 사용
# - 코드 내 KEYWORDS 딕셔너리 제거
# - GitHub Actions 환경 자동 감지
# ============================================================

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

# ── 경로 설정 ──────────────────────────────────────────────
IS_GITHUB = os.getenv("GITHUB_ACTIONS") == "true"

if IS_GITHUB:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from config import LATEST_DIR, INPUT_DIR
        OUTPUT_DIR = Path(LATEST_DIR)
        INPUT_DIR  = Path(INPUT_DIR)
        ROOT       = OUTPUT_DIR.parent.parent
    except ImportError:
        OUTPUT_DIR = Path("outputs/latest")
        INPUT_DIR  = Path("inputs")
        ROOT       = Path(".")
else:
    D_ROOT     = Path(r"D:\AI_WorkSpace\I_SFC")
    ROOT       = D_ROOT / r"09_Implementation\SFC_DataPipeline"
    SECRET_ENV = D_ROOT / r"00_Local_Secrets\SFD\.env"
    OUTPUT_DIR = ROOT / r"outputs\latest"
    INPUT_DIR  = ROOT / r"inputs"
    if Path(r"D:\AI_WorkSpace\I_SFC\00_Local_Secrets\SFD\.env").exists():
        load_dotenv(Path(r"D:\AI_WorkSpace\I_SFC\00_Local_Secrets\SFD\.env"))

# ── 파일 경로 ──────────────────────────────────────────────
QUERY_CSV      = INPUT_DIR / "sfd_naver_news_queries.csv"
PREV_CLOSE_CSV = OUTPUT_DIR / "sfd_prev_close_latest.csv"
OUT_ARTICLES   = OUTPUT_DIR / "sfd_news_signal_latest.csv"
OUT_SCORES     = OUTPUT_DIR / "sfd_news_score_latest.csv"
LOG_PATH       = ROOT / "logs" / "sfd_news_fetcher.log"

IMPORTANCE_BASE   = 5
IMPORTANCE_TAG    = 7
IMPORTANCE_STOCK  = 9
IMPORTANCE_URGENT = 10


def load_stock_map(prev_close_csv: Path) -> dict[str, str]:
    if not prev_close_csv.exists():
        print(f"[WARN] prev_close_csv 없음: {prev_close_csv}")
        return {}
    df = pd.read_csv(prev_close_csv, encoding="utf-8-sig", dtype=str)
    if "name" not in df.columns or "ticker" not in df.columns:
        print(f"[WARN] 컬럼 오류: {df.columns.tolist()}")
        return {}
    stock_map = dict(zip(df["name"].str.strip(), df["ticker"].str.strip()))
    print(f"[INFO] STOCK_MAP 로드 완료: {len(stock_map)}종목")
    return stock_map


def build_keywords_from_queries(qdf: pd.DataFrame) -> dict[str, list[str]]:
    kw: dict[str, list[str]] = {}
    for _, row in qdf.iterrows():
        group = str(row.get("group", "UNKNOWN")).strip()
        query = str(row.get("query", "")).strip()
        if query:
            kw.setdefault(group, []).append(query)
    return kw


def strip_html(text: str) -> str:
    return re.sub(r"<.*?>", "", str(text or "")).replace("&quot;", '"').replace("&amp;", "&")


def detect_tags(text: str, keywords: dict[str, list[str]]) -> str:
    out = []
    for tag, words in keywords.items():
        if any(w.lower() in text.lower() for w in words):
            out.append(tag)
    return ";".join(sorted(set(out)))


def detect_stocks(text: str, stock_map: dict[str, str]) -> list[tuple[str, str]]:
    hits = []
    for name, code in stock_map.items():
        if len(name) >= 2 and name.lower() in text.lower():
            hits.append((name, code))
    return hits


def calc_importance(tags: str, stocks: list, title: str) -> float:
    urgent = re.compile(r"긴급|속보|단독|breaking|exclusive", re.I)
    if urgent.search(title):
        return IMPORTANCE_URGENT
    if stocks and tags:
        return IMPORTANCE_STOCK
    if tags:
        return IMPORTANCE_TAG
    return IMPORTANCE_BASE


def fetch_naver_news(query: str, display: int, client_id: str, client_secret: str) -> list[dict]:
    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    params  = {"query": query, "display": display, "sort": "date"}
    r = requests.get(url, headers=headers, params=params, timeout=15)
    r.raise_for_status()
    return r.json().get("items", [])


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    client_id     = os.getenv("NAVER_CLIENT_ID", "").strip()
    client_secret = os.getenv("NAVER_CLIENT_SECRET", "").strip()
    display       = int(os.getenv("NAVER_NEWS_DISPLAY", "20") or "20")

    article_cols = [
        "collected_at", "source", "query_group", "query",
        "ticker", "stock_name",
        "title", "description", "originallink", "link", "pubDate",
        "detected_tags", "detected_stocks", "importance_score",
    ]
    score_cols = ["ticker", "stock_name", "news_score", "article_count", "top_tags"]

    if not client_id or not client_secret:
        pd.DataFrame(columns=article_cols).to_csv(OUT_ARTICLES, index=False, encoding="utf-8-sig")
        pd.DataFrame(columns=score_cols).to_csv(OUT_SCORES, index=False, encoding="utf-8-sig")
        LOG_PATH.write_text(f"{datetime.now().isoformat()} NAVER API keys missing.\n", encoding="utf-8")
        print("NAVER API keys missing. Empty CSVs created.")
        return

    if not QUERY_CSV.exists():
        print(f"[ERROR] Query CSV 없음: {QUERY_CSV}")
        return

    qdf = pd.read_csv(QUERY_CSV, encoding="utf-8-sig")
    enabled_mask = qdf.get("enabled", pd.Series(["Y"] * len(qdf)))
    qdf = qdf[enabled_mask.astype(str).str.upper() == "Y"]

    keywords  = build_keywords_from_queries(qdf)
    stock_map = load_stock_map(PREV_CLOSE_CSV)

    rows: list[dict] = []

    for _, q in qdf.iterrows():
        query = str(q.get("query", "")).strip()
        group = str(q.get("group", "")).strip()
        if not query:
            continue
        try:
            items = fetch_naver_news(query, display, client_id, client_secret)
        except Exception as e:
            LOG_PATH.write_text(f"{datetime.now().isoformat()} query={query} error={e}\n", encoding="utf-8")
            continue

        for item in items:
            title = strip_html(item.get("title", ""))
            desc  = strip_html(item.get("description", ""))
            text  = f"{title} {desc}"

            tags       = detect_tags(text, keywords)
            stock_hits = detect_stocks(text, stock_map)
            importance = calc_importance(tags, stock_hits, title)
            stocks_str = ";".join(f"{n}({c})" for n, c in stock_hits)

            base_row = {
                "collected_at": datetime.now().isoformat(timespec="seconds"),
                "source": "NAVER_NEWS_API", "query_group": group, "query": query,
                "title": title, "description": desc[:300],
                "originallink": item.get("originallink", ""), "link": item.get("link", ""),
                "pubDate": item.get("pubDate", ""), "detected_tags": tags,
                "detected_stocks": stocks_str, "importance_score": importance,
            }

            if stock_hits:
                for name, code in stock_hits:
                    rows.append({**base_row, "ticker": code, "stock_name": name})
            else:
                rows.append({**base_row, "ticker": "", "stock_name": ""})

    df_articles = pd.DataFrame(rows, columns=article_cols)
    df_articles.to_csv(OUT_ARTICLES, index=False, encoding="utf-8-sig")

    df_ticker = df_articles[df_articles["ticker"] != ""].copy()
    if not df_ticker.empty:
        agg = (
            df_ticker.groupby(["ticker", "stock_name"])
            .agg(
                article_count=("title", "count"),
                avg_importance=("importance_score", "mean"),
                top_tags=("detected_tags", lambda x: ";".join(
                    sorted(set(t for s in x for t in str(s).split(";") if t)))[:200]),
            ).reset_index()
        )
        agg["news_score"] = (agg["article_count"] * agg["avg_importance"] * 0.3).clip(upper=30).round(2)
        df_scores = agg[score_cols]
    else:
        df_scores = pd.DataFrame(columns=score_cols)

    df_scores.to_csv(OUT_SCORES, index=False, encoding="utf-8-sig")

    mapped_count = df_ticker["ticker"].nunique() if not df_ticker.empty else 0
    log_msg = (
        f"{datetime.now().isoformat()} articles={len(df_articles)} "
        f"tickers_mapped={mapped_count}\n"
    )
    LOG_PATH.write_text(log_msg, encoding="utf-8")
    print(f"[OK] articles={len(df_articles)} | tickers={mapped_count}")
    print(f"     -> {OUT_ARTICLES}")
    print(f"     -> {OUT_SCORES}")


if __name__ == "__main__":
    main()
