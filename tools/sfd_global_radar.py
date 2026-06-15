#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sfd_global_radar.py v1.0
SFD Layer -1 / Layer -3 통합 모듈
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
① 글로벌 온도계: 지수/환율/원자재/VIX (yfinance)
② 미국 매거진 RSS 헤드라인 수집 (Reuters/AP/Bloomberg)
③ 키워드 → 한국 섹터 자동 매핑
④ 캘린더 D-체크: 오늘 기준 D-30/7/1 이내 이벤트 자동 스캔
출력: sfd_global_radar_latest.json (outputs/latest/)
실행: python -X utf8 tools/sfd_global_radar.py
스케줄: 08:05 (글로벌 온도계는 가장 먼저 실행)
"""

import os, sys, json, logging
from datetime import datetime, timedelta
import feedparser
import yfinance as yf

BASE_DIR = os.environ.get("SFD_BASE_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs", "latest")
CALENDAR_PATH = os.path.join(BASE_DIR, "data", "sfd_calendar_3yr.json")
os.makedirs(OUTPUT_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO,
    format="[%(levelname)s] %(asctime)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(OUTPUT_DIR, "global_radar.log"), encoding="utf-8"),
        logging.StreamHandler()
    ])
logger = logging.getLogger(__name__)

# ── 1. 수집 대상 정의 ──────────────────────────────────────────

INDICES = {
    "KOSPI":      ("^KS11",  "KOSPI"),
    "KOSDAQ":     ("^KQ11",  "KOSDAQ"),
    "SP500":      ("^GSPC",  "S&P500"),
    "NASDAQ":     ("^IXIC",  "NASDAQ"),
    "DOW":        ("^DJI",   "DOW"),
    "NIKKEI":     ("^N225",  "닛케이"),
    "SHANGHAI":   ("000001.SS", "상하이"),
    "HANGSENG":   ("^HSI",   "항셍"),
}

FX_RATES = {
    "USD_KRW":  ("KRW=X",   "달러/원"),
    "USD_JPY":  ("JPY=X",   "달러/엔"),
    "USD_CNY":  ("CNY=X",   "달러/위안"),
    "EUR_USD":  ("EURUSD=X","유로/달러"),
}

COMMODITIES = {
    "GOLD":     ("GC=F",    "금(달러/oz)"),
    "OIL_WTI":  ("CL=F",    "WTI유가"),
    "COPPER":   ("HG=F",    "구리"),
    "NATGAS":   ("NG=F",    "천연가스"),
    "BTC":      ("BTC-USD", "비트코인"),
    "VIX":      ("^VIX",    "VIX(공포지수)"),
    "US10Y":    ("^TNX",    "미국10년국채"),
}

# ── 2. RSS 뉴스 소스 ─────────────────────────────────────────

RSS_SOURCES = [
    # Reuters — 현행 URL (2025 이후)
    {"name": "Reuters World",      "url": "https://feeds.reuters.com/Reuters/worldNews",          "lang": "en"},
    {"name": "Reuters Business",   "url": "https://feeds.reuters.com/reuters/businessNews",       "lang": "en"},
    {"name": "Reuters Technology", "url": "https://feeds.reuters.com/reuters/technologyNews",     "lang": "en"},
    # AP
    {"name": "AP Top News",        "url": "https://rsshub.app/apnews/topics/apf-topnews",        "lang": "en"},
    {"name": "AP Business",        "url": "https://rsshub.app/apnews/topics/apf-business-news",  "lang": "en"},
    # Investing.com (작동 확인됨)
    {"name": "Investing.com",      "url": "https://www.investing.com/rss/news.rss",              "lang": "en"},
    {"name": "Investing Markets",  "url": "https://www.investing.com/rss/market_overview.rss",   "lang": "en"},
    # Yahoo Finance (안정적)
    {"name": "Yahoo Finance",      "url": "https://finance.yahoo.com/rss/topfinstories",         "lang": "en"},
    {"name": "Yahoo Markets",      "url": "https://finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US", "lang": "en"},
    # CNBC
    {"name": "CNBC Top News",      "url": "https://feeds.nbcnews.com/nbcnews/public/news",       "lang": "en"},
    {"name": "CNBC Finance",       "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", "lang": "en"},
    # MarketWatch
    {"name": "MarketWatch",        "url": "https://feeds.marketwatch.com/marketwatch/topstories", "lang": "en"},
]

# ── 3. 키워드 → 한국 섹터 자동 매핑 ──────────────────────────

KEYWORD_SECTOR_MAP = {
    # AI / 반도체
    "semiconductor": {"sector": "반도체/소부장", "boost": 10, "tickers": ["000660", "005930", "042700"]},
    "AI chip":       {"sector": "반도체/AI",     "boost": 12, "tickers": ["000660", "042700", "036830"]},
    "HBM":           {"sector": "반도체/HBM",    "boost": 15, "tickers": ["000660", "042700"]},
    "nvidia":        {"sector": "반도체/AI",     "boost": 12, "tickers": ["000660", "005930"]},
    "data center":   {"sector": "AI인프라",      "boost": 8,  "tickers": ["000660", "034220"]},
    # 방산
    "defense spending": {"sector": "방산",       "boost": 10, "tickers": ["012450", "079550", "047050"]},
    "military":      {"sector": "방산",          "boost": 8,  "tickers": ["012450", "079550"]},
    "NATO":          {"sector": "방산",          "boost": 10, "tickers": ["012450", "079550", "047050"]},
    "weapon":        {"sector": "방산",          "boost": 8,  "tickers": ["012450", "079550"]},
    # 원전
    "nuclear":       {"sector": "원전/SMR",      "boost": 12, "tickers": ["034020", "082740", "071970"]},
    "SMR":           {"sector": "원전/SMR",      "boost": 15, "tickers": ["034020", "082740", "071970"]},
    "reactor":       {"sector": "원전/SMR",      "boost": 8,  "tickers": ["034020", "082740"]},
    # 전력/에너지
    "power grid":    {"sector": "전력설비",      "boost": 10, "tickers": ["004490", "006260", "267260"]},
    "electricity":   {"sector": "전력설비",      "boost": 6,  "tickers": ["004490", "006260"]},
    "transformer":   {"sector": "전력설비",      "boost": 8,  "tickers": ["004490", "006260"]},
    # EV / 배터리
    "EV battery":    {"sector": "2차전지",       "boost": 10, "tickers": ["051910", "006400", "373220"]},
    "cathode":       {"sector": "2차전지 소재",  "boost": 8,  "tickers": ["051910", "006260"]},
    "lithium":       {"sector": "2차전지 소재",  "boost": 6,  "tickers": ["051910"]},
    # 중국 관련
    "China stimulus": {"sector": "화장품/면세/관광", "boost": 10, "tickers": ["090430", "051900", "008770"]},
    "yuan":          {"sector": "화장품/면세",   "boost": 6,  "tickers": ["090430", "051900"]},
    "chinese tourist": {"sector": "관광/면세",   "boost": 8,  "tickers": ["008770", "090430"]},
    # 금리
    "rate cut":      {"sector": "리츠/성장주",   "boost": 10, "tickers": ["016360", "035420", "035720"]},
    "fed cut":       {"sector": "리츠/성장주",   "boost": 10, "tickers": ["016360"]},
    "rate hike":     {"sector": "은행/보험",     "boost": 6,  "tickers": ["105560", "086790"]},
    # 로봇
    "robot":         {"sector": "로봇/물리AI",   "boost": 10, "tickers": ["454910", "277810", "108490"]},
    "humanoid":      {"sector": "로봇/물리AI",   "boost": 12, "tickers": ["454910", "277810"]},
    "automation":    {"sector": "로봇/자동화",   "boost": 6,  "tickers": ["454910", "277810"]},
    # K-콘텐츠
    "K-pop":         {"sector": "엔터",          "boost": 10, "tickers": ["352820", "041510", "035900"]},
    "BTS":           {"sector": "엔터/하이브",   "boost": 15, "tickers": ["352820"]},
    "kpop":          {"sector": "엔터",          "boost": 8,  "tickers": ["352820", "041510", "035900"]},
    "Netflix Korea": {"sector": "드라마/제작사", "boost": 8,  "tickers": ["253450", "036420"]},
    # 지정학
    "North Korea":   {"sector": "방산(리스크)",  "boost": 12, "tickers": ["012450", "079550"]},
    "Taiwan":        {"sector": "반도체(리스크)", "boost": -8, "tickers": ["000660", "005930"]},
    "Middle East":   {"sector": "정유/방산",     "boost": 8,  "tickers": ["010130", "012450"]},
}

# ── 4. 시장 데이터 수집 ────────────────────────────────────────

def fetch_market_data():
    """yfinance로 지수/환율/원자재 수집"""
    result = {}
    all_tickers = {}
    all_tickers.update({k: v for k, v in INDICES.items()})
    all_tickers.update({k: v for k, v in FX_RATES.items()})
    all_tickers.update({k: v for k, v in COMMODITIES.items()})

    for key, (symbol, label) in all_tickers.items():
        try:
            ticker = yf.Ticker(symbol)
            # 5일치: 주말/휴장/장외시간 NaN 대비
            hist = ticker.history(period="5d")
            hist = hist.dropna(subset=["Close"])
            if len(hist) >= 2:
                prev_close = float(hist["Close"].iloc[-2])
                last_close = float(hist["Close"].iloc[-1])
                import math
                if math.isnan(last_close) or math.isnan(prev_close):
                    raise ValueError("NaN in close price")
                chg_pct = (last_close - prev_close) / prev_close * 100
                result[key] = {
                    "label":      label,
                    "symbol":     symbol,
                    "price":      round(last_close, 4),
                    "prev_close": round(prev_close, 4),
                    "chg_pct":    round(chg_pct, 2),
                    "direction":  "▲" if chg_pct >= 0 else "▼",
                }
            elif len(hist) == 1:
                last_close = float(hist["Close"].iloc[-1])
                result[key] = {
                    "label":     label,
                    "symbol":    symbol,
                    "price":     round(last_close, 4),
                    "chg_pct":   0.0,
                    "direction": "-",
                }
            else:
                result[key] = {"label": label, "symbol": symbol, "price": None, "chg_pct": None, "direction": "?"}
                logger.warning(f"✗ {label}: 데이터 없음")
                continue
            logger.info(f"✓ {label}: {result[key].get('price')} ({result[key].get('chg_pct', 0):+.2f}%)")
        except Exception as e:
            logger.warning(f"✗ {label} ({symbol}): {e}")
            result[key] = {"label": label, "symbol": symbol, "price": None, "chg_pct": None, "direction": "?"}
    return result

# ── 5. RSS 뉴스 수집 ────────────────────────────────────────────

def fetch_rss_news(max_per_source=15):
    """RSS 피드에서 최신 뉴스 헤드라인 수집"""
    all_news = []
    for src in RSS_SOURCES:
        try:
            feed = feedparser.parse(src["url"])
            count = 0
            for entry in feed.entries[:max_per_source]:
                title = entry.get("title", "").strip()
                link  = entry.get("link", "")
                pub   = entry.get("published", "")
                if title:
                    all_news.append({
                        "source": src["name"],
                        "title":  title,
                        "link":   link,
                        "published": pub,
                    })
                    count += 1
            logger.info(f"✓ RSS {src['name']}: {count}건 수집")
        except Exception as e:
            logger.warning(f"✗ RSS {src['name']}: {e}")
    return all_news

# ── 6. 뉴스 → 섹터 매핑 ───────────────────────────────────────

def map_news_to_sectors(news_list):
    """뉴스 헤드라인에서 키워드 감지 → 한국 섹터 매핑"""
    triggered = []
    seen_sectors = set()

    for news in news_list:
        title_lower = news["title"].lower()
        for keyword, info in KEYWORD_SECTOR_MAP.items():
            if keyword.lower() in title_lower:
                sector = info["sector"]
                if sector not in seen_sectors:
                    triggered.append({
                        "keyword":  keyword,
                        "sector":   sector,
                        "boost":    info["boost"],
                        "tickers":  info["tickers"],
                        "headline": news["title"],
                        "source":   news["source"],
                        "link":     news["link"],
                    })
                    seen_sectors.add(sector)

    triggered.sort(key=lambda x: abs(x["boost"]), reverse=True)
    logger.info(f"✓ 뉴스→섹터 매핑: {len(triggered)}개 트리거")
    return triggered

# ── 7. 캘린더 D-체크 ────────────────────────────────────────────

def check_calendar_alerts(today: datetime):
    """오늘 날짜 기준 D-30/7/1 이내 이벤트 스캔"""
    alerts = []

    if not os.path.exists(CALENDAR_PATH):
        logger.warning(f"캘린더 파일 없음: {CALENDAR_PATH}")
        return alerts

    with open(CALENDAR_PATH, "r", encoding="utf-8") as f:
        cal = json.load(f)

    def check_fixed(events):
        for ev in events:
            date_str = ev.get("date") or ev.get("date_start")
            if not date_str or "XX" in date_str:
                continue
            try:
                ev_date = datetime.strptime(date_str, "%Y-%m-%d")
                delta = (ev_date - today).days
                thresholds = ev.get("d_minus_alert", [30, 7, 1])
                for th in sorted(thresholds):
                    if 0 <= delta <= th:
                        urgency = "HIGH" if delta <= 1 else "MID" if delta <= 7 else "LOW"
                        alerts.append({
                            "id":       ev["id"],
                            "name":     ev["name"],
                            "date":     date_str,
                            "days_left": delta,
                            "urgency":  urgency,
                            "sectors":  ev.get("sectors_positive") or ev.get("sectors_watch", []),
                            "boost":    ev.get("boost", ""),
                            "note":     ev.get("note", ""),
                        })
                        break
            except Exception:
                continue

    def check_recurring(events):
        for ev in events:
            months = ev.get("months") or ([ev["month"]] if "month" in ev else [])
            for m in months:
                # 올해와 내년 모두 체크
                for year in [today.year, today.year + 1]:
                    week_num = ev.get("week", 2)
                    if isinstance(week_num, str):
                        week_num = 2
                    try:
                        # 해당 월 첫날 기준 week번째 주 월요일 추정
                        first_day = datetime(year, m, 1)
                        day_offset = (week_num - 1) * 7
                        ev_date = first_day + timedelta(days=day_offset)
                        delta = (ev_date - today).days
                        thresholds = ev.get("d_minus_alert", [14, 7, 1])
                        for th in sorted(thresholds):
                            if 0 <= delta <= th:
                                urgency = "HIGH" if delta <= 1 else "MID" if delta <= 7 else "LOW"
                                alerts.append({
                                    "id":       ev["id"],
                                    "name":     ev["name"],
                                    "date":     ev_date.strftime("%Y-%m-%d"),
                                    "days_left": delta,
                                    "urgency":  urgency,
                                    "sectors":  ev.get("sectors_positive") or ev.get("sectors", []),
                                    "boost":    ev.get("boost", ""),
                                    "note":     ev.get("note", ""),
                                })
                                break
                    except Exception:
                        continue

    check_fixed(cal.get("fixed_events_2026_2028", []))
    check_fixed(cal.get("us_annual_schedule", []))
    check_recurring(cal.get("recurring_annual", []))
    check_recurring(cal.get("us_annual_schedule", []))

    # 긴급도순 정렬
    urgency_order = {"HIGH": 0, "MID": 1, "LOW": 2}
    alerts.sort(key=lambda x: (urgency_order.get(x["urgency"], 3), x["days_left"]))
    logger.info(f"✓ 캘린더 경보: {len(alerts)}건 (오늘={today.strftime('%Y-%m-%d')})")
    return alerts

# ── 8. VIX 해석 ──────────────────────────────────────────────────

def interpret_vix(vix_val):
    if vix_val is None:
        return "데이터 없음"
    if vix_val < 15:
        return "극도의 안정 — 과열 주의"
    elif vix_val < 20:
        return "안정적 — 일반 매수 환경"
    elif vix_val < 30:
        return "경계 — 변동성 확대 중"
    elif vix_val < 40:
        return "공포 — 저점 매수 기회 탐색"
    else:
        return "극도의 공포 — 시장 붕괴 경고"

# ── 9. 메인 ──────────────────────────────────────────────────────

def main():
    today = datetime.now()
    logger.info(f"=== sfd_global_radar v1.0 START | {today.strftime('%Y-%m-%d %H:%M')} ===")

    # 시장 데이터
    logger.info("--- 시장 데이터 수집 ---")
    market = fetch_market_data()

    # VIX 해석
    vix_val  = market.get("VIX", {}).get("price")
    vix_note = interpret_vix(vix_val)

    # RSS 뉴스
    logger.info("--- RSS 뉴스 수집 ---")
    raw_news = fetch_rss_news(max_per_source=20)

    # 섹터 매핑
    sector_triggers = map_news_to_sectors(raw_news)

    # 캘린더 체크
    logger.info("--- 캘린더 D-체크 ---")
    calendar_alerts = check_calendar_alerts(today)

    # 전체 결과 조합
    output = {
        "generated_at":    today.strftime("%Y-%m-%d %H:%M:%S"),
        "trade_date":      today.strftime("%Y%m%d"),
        "market": {
            "indices":    {k: market[k] for k in INDICES    if k in market},
            "fx_rates":   {k: market[k] for k in FX_RATES   if k in market},
            "commodities":{k: market[k] for k in COMMODITIES if k in market},
        },
        "vix_note":        vix_note,
        "rss_news_count":  len(raw_news),
        "rss_headlines":   raw_news[:30],   # 최신 30건
        "sector_triggers": sector_triggers, # 뉴스→섹터 매핑
        "calendar_alerts": calendar_alerts, # D-체크 결과
        "summary": {
            "kospi_chg":       market.get("KOSPI",   {}).get("chg_pct"),
            "nasdaq_chg":      market.get("NASDAQ",  {}).get("chg_pct"),
            "sp500_chg":       market.get("SP500",   {}).get("chg_pct"),
            "usd_krw":         market.get("USD_KRW", {}).get("price"),
            "vix":             vix_val,
            "vix_note":        vix_note,
            "top_triggers":    [t["sector"] for t in sector_triggers[:5]],
            "urgent_calendar": [a["name"] for a in calendar_alerts if a["urgency"] == "HIGH"],
        }
    }

    out_path = os.path.join(OUTPUT_DIR, "sfd_global_radar_latest.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    logger.info(f"✓ 저장: {out_path}")
    logger.info(f"  지수: KOSPI {market.get('KOSPI',{}).get('chg_pct',0):+.2f}% / NASDAQ {market.get('NASDAQ',{}).get('chg_pct',0):+.2f}%")
    logger.info(f"  VIX: {vix_val} → {vix_note}")
    logger.info(f"  뉴스 트리거: {len(sector_triggers)}개 / 캘린더 경보: {len(calendar_alerts)}건")
    logger.info(f"=== sfd_global_radar DONE ===")
    return output

if __name__ == "__main__":
    main()
