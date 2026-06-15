from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

D_ROOT = Path(r"D:\AI_WorkSpace\I_SFC")
ROOT = D_ROOT / r"09_Implementation\SFC_DataPipeline"
SECRET_ENV = D_ROOT / r"00_Local_Secrets\SFD\.env"
INPUT = ROOT / r"inputs\sfd_naver_news_queries.csv"
OUTPUT = ROOT / r"outputs\latest\sfd_news_signal_latest.csv"
LOG = ROOT / r"logs\collect_sfd_naver_news.log"

KEYWORDS = {
    "AI_MEMORY": ["HBM", "반도체", "삼성전자", "SK하이닉스", "메모리"],
    "AI_CAPEX": ["AI CAPEX", "AI 투자", "데이터센터", "인공지능"],
    "GRID_POWER": ["전력", "전력망", "전선", "변압기", "데이터센터 전력"],
    "NUCLEAR": ["원전", "SMR", "두산에너빌리티", "한전기술"],
    "SHIPBUILDING": ["조선", "LNG선", "삼성중공업", "해양플랜트"],
    "COPPER": ["구리", "KBI메탈", "풍산", "이구산업"],
    "POLICY": ["산업부", "과기부", "금융위", "정부", "정책"],
    "ENERGY_IS_CURRENCY": ["에너지가 화폐", "에너지", "AI 전력"],
}

STOCK_MAP = {
    "삼성전자": "005930", "SK하이닉스": "000660", "한미반도체": "042700",
    "두산에너빌리티": "034020", "대한전선": "001440", "대원전선": "006340",
    "KBI메탈": "024840", "삼성중공업": "010140", "한전기술": "052690",
    "한전산업": "130660", "LS ELECTRIC": "010120", "HD현대일렉트릭": "267260",
    "풍산": "103140", "이구산업": "025820", "가온전선": "000500", "LS": "006260",
}


def strip_html(text: str) -> str:
    return re.sub(r"<.*?>", "", str(text or "")).replace("&quot;", '"').replace("&amp;", "&")


def detect_tags(text: str) -> str:
    out = []
    for tag, words in KEYWORDS.items():
        if any(w.lower() in text.lower() for w in words):
            out.append(tag)
    return ";".join(sorted(set(out)))


def detect_stocks(text: str) -> str:
    hits = []
    for name, code in STOCK_MAP.items():
        if name.lower() in text.lower():
            hits.append(f"{name}({code})")
    return ";".join(hits)


def fetch_naver_news(query: str, display: int, client_id: str, client_secret: str) -> list[dict[str, str]]:
    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }
    params = {"query": query, "display": display, "sort": "date"}
    r = requests.get(url, headers=headers, params=params, timeout=15)
    r.raise_for_status()
    return r.json().get("items", [])


def main() -> None:
    load_dotenv(SECRET_ENV)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)

    client_id = os.getenv("NAVER_CLIENT_ID", "").strip()
    client_secret = os.getenv("NAVER_CLIENT_SECRET", "").strip()
    display = int(os.getenv("NAVER_NEWS_DISPLAY", "20") or "20")

    columns = [
        "collected_at", "source", "query_group", "query", "title", "description",
        "originallink", "link", "pubDate", "detected_tags", "detected_stocks", "importance_score",
    ]

    if not INPUT.exists():
        pd.DataFrame(columns=columns).to_csv(OUTPUT, index=False, encoding="utf-8-sig")
        print("NO INPUT", INPUT)
        return

    qdf = pd.read_csv(INPUT, encoding="utf-8-sig")
    rows = []

    if not client_id or not client_secret:
        pd.DataFrame(columns=columns).to_csv(OUTPUT, index=False, encoding="utf-8-sig")
        LOG.write_text(f"{datetime.now().isoformat()} NAVER API keys missing. output empty.\n", encoding="utf-8")
        print("NAVER API keys missing. Empty news CSV created:", OUTPUT)
        return

    for _, q in qdf.iterrows():
        if str(q.get("enabled", "Y")).upper() != "Y":
            continue
        query = str(q.get("query", "")).strip()
        if not query:
            continue
        try:
            items = fetch_naver_news(query, display, client_id, client_secret)
        except Exception as e:
            LOG.write_text(f"{datetime.now().isoformat()} query={query} error={e}\n", encoding="utf-8")
            continue
        for item in items:
            title = strip_html(item.get("title", ""))
            desc = strip_html(item.get("description", ""))
            text = f"{title} {desc}"
            tags = detect_tags(text)
            stocks = detect_stocks(text)
            score = 50 + 10 * len(tags.split(";")) if tags else 40
            if stocks:
                score += 10
            rows.append({
                "collected_at": datetime.now().isoformat(timespec="seconds"),
                "source": "NAVER_NEWS_API",
                "query_group": q.get("group", ""),
                "query": query,
                "title": title,
                "description": desc[:300],
                "originallink": item.get("originallink", ""),
                "link": item.get("link", ""),
                "pubDate": item.get("pubDate", ""),
                "detected_tags": tags,
                "detected_stocks": stocks,
                "importance_score": min(score, 100),
            })

    df = pd.DataFrame(rows, columns=columns)
    df.to_csv(OUTPUT, index=False, encoding="utf-8-sig")
    LOG.write_text(f"{datetime.now().isoformat()} rows={len(df)} output={OUTPUT}\n", encoding="utf-8")
    print(f"OK naver news rows={len(df)}")
    print(OUTPUT)


if __name__ == "__main__":
    main()
