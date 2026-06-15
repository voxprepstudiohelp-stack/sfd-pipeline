from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Iterable

import feedparser
import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "inputs" / "sfd_news_sources.csv"
OUTPUT = ROOT / "outputs" / "latest" / "sfd_news_signal_latest.csv"
LOG = ROOT / "logs" / "collect_sfd_news_sources.log"

KEYWORDS = {
    "AI_CAPEX": ["capex", "ai investment", "artificial intelligence", "ai data center", "ai infrastructure", "AI", "인공지능", "AI 투자"],
    "DATA_CENTER_POWER": ["data center", "power shortage", "electricity", "grid", "데이터센터", "전력", "전력망", "전력 부족"],
    "SEMICONDUCTOR": ["semiconductor", "chip", "HBM", "DRAM", "NAND", "반도체", "메모리"],
    "NUCLEAR": ["nuclear", "원전", "SMR"],
    "CABLE_COPPER": ["copper", "cable", "wire", "구리", "전선", "케이블"],
    "SHIPBUILDING": ["shipbuilding", "LNG", "조선", "선박", "해양플랜트"],
    "DEFENSE": ["defense", "war", "missile", "방산", "전쟁", "미사일"],
    "BATTERY": ["battery", "EV", "전기차", "2차전지", "배터리"],
}


def detect_tags(text: str) -> str:
    lowered = text.lower()
    hits: list[str] = []
    for tag, words in KEYWORDS.items():
        for w in words:
            if w.lower() in lowered:
                hits.append(tag)
                break
    return ";".join(sorted(set(hits)))


def collect_rss(row: dict[str, str]) -> Iterable[dict[str, str]]:
    url = row.get("url_or_rss", "")
    if not url or url.startswith("TODO"):
        return []
    feed = feedparser.parse(url)
    out = []
    for entry in feed.entries[:20]:
        title = getattr(entry, "title", "")
        summary = getattr(entry, "summary", "")
        link = getattr(entry, "link", "")
        published = getattr(entry, "published", "")
        text = f"{title} {summary}"
        out.append({
            "collected_at": datetime.now().isoformat(timespec="seconds"),
            "source_group": row.get("source_group", ""),
            "source_name": row.get("source_name", ""),
            "language": row.get("language", ""),
            "region": row.get("region", ""),
            "title": title,
            "summary": summary[:500].replace("\n", " "),
            "link": link,
            "published": published,
            "detected_tags": detect_tags(text),
            "priority": row.get("priority", ""),
        })
    return out


def main() -> None:
    load_dotenv(ROOT / ".env")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)

    if not INPUT.exists():
        raise FileNotFoundError(f"missing input file: {INPUT}")

    rows: list[dict[str, str]] = []
    with INPUT.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("enabled", "N").upper() != "Y":
                continue
            collector = row.get("collector_type", "").upper()
            if collector == "RSS":
                rows.extend(collect_rss(row))

    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=[
            "collected_at", "source_group", "source_name", "language", "region",
            "title", "summary", "link", "published", "detected_tags", "priority"
        ])
    df.to_csv(OUTPUT, index=False, encoding="utf-8-sig")
    LOG.write_text(f"{datetime.now().isoformat(timespec='seconds')} rows={len(df)} output={OUTPUT}\n", encoding="utf-8")
    print(f"OK news rows={len(df)}")
    print(OUTPUT)


if __name__ == "__main__":
    main()
