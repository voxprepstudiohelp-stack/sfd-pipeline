"""SFD RSS news sentinel.

최근 24시간 내 RSS 기사를 키워드로 분류하고 카카오톡으로 알린다.
외부 의존성: feedparser, requests
"""

from __future__ import annotations

import calendar
import hashlib
import html
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import feedparser
import requests


SCRIPT_DIR = Path(__file__).resolve().parent
STATE_FILE = SCRIPT_DIR / "sent_news_ids.json"
WATCH_PENDING_FILE = SCRIPT_DIR / "watch_news_pending.json"
WATCH_SUMMARY_DATE_FILE = SCRIPT_DIR / "watch_summary_last_date.txt"
LOG_DIR = SCRIPT_DIR / "logs"

RSS_FEEDS = (
    ("Bloomberg Tech", "https://feeds.bloomberg.com/technology/news.rss"),
    ("Ars Technica Tech", "https://feeds.arstechnica.com/arstechnica/technology-lab"),
    ("CNBC Tech", "https://www.cnbc.com/id/19854910/device/rss/rss.html"),
    ("Google News - China chip", "https://news.google.com/rss/search?q=China+semiconductor+CXMT&hl=en&gl=US&ceid=US:en"),
    ("Google News - 삼성전자", "https://news.google.com/rss/search?q=%EC%82%BC%EC%84%B1%EC%A0%84%EC%9E%90&hl=ko&gl=KR&ceid=KR:ko"),
)

TRIGGER_KEYWORDS = (
    "삼성전자", "SK하이닉스", "한미반도체", "HBM", "D램", "낸드",
    "파운드리", "AI 반도체", "반도체",
    "CXMT", "YMTC", "SMIC", "Samsung", "SK Hynix", "Micron",
    "DRAM", "NAND", "China semiconductor", "China chip",
    "China AI", "DeepSeek", "Huawei", "Korea chip", "KOSPI",
)

IMPACT_KEYWORDS = (
    "급등", "급락", "폭등", "폭락", "신고가", "실적", "어닝", "영업이익",
    "수주", "계약", "인수", "합병", "투자", "증설", "감산", "공급 중단",
    "리콜", "사고", "파산", "규제", "제재",
    "IPO", "threat", "rival", "surges", "plunges", "crashes",
    "warning", "sanctions", "export control",
)

ARTICLE_MAX_AGE = timedelta(hours=24)
SEEN_RETENTION = timedelta(days=7)
HTTP_TIMEOUT_SECONDS = 10
KAKAO_API_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_TOKEN_INFO_URL = "https://kapi.kakao.com/v1/user/access_token_info"
KAKAO_REFRESH_MARGIN_SECONDS = 3600


def configure_logging(now: datetime) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"news_sentinel_{now.astimezone().strftime('%Y%m%d')}.log"
    logger = logging.getLogger("sfd_news_sentinel")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.addHandler(stream_handler)
    return logger


def load_seen_ids(now: datetime, logger: logging.Logger) -> dict[str, str]:
    if not STATE_FILE.exists():
        return {}
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("최상위 JSON 값이 객체가 아님")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        logger.error("중복 방지 파일 읽기 실패, 빈 상태로 시작: %s", exc)
        return {}
    cutoff = now - SEEN_RETENTION
    cleaned: dict[str, str] = {}
    for article_id, timestamp in raw.items():
        try:
            seen_at = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            if seen_at.tzinfo is None:
                seen_at = seen_at.replace(tzinfo=timezone.utc)
            if seen_at.astimezone(timezone.utc) >= cutoff:
                cleaned[str(article_id)] = seen_at.astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError):
            logger.warning("잘못된 알림 이력 삭제: %s", article_id)
    removed = len(raw) - len(cleaned)
    if removed:
        logger.info("7일 경과/잘못된 알림 이력 %d건 삭제", removed)
    return cleaned


def save_seen_ids(seen_ids: dict[str, str], logger: logging.Logger) -> None:
    try:
        STATE_FILE.write_text(
            json.dumps(seen_ids, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        logger.error("중복 방지 파일 저장 실패: %s", exc)


def load_watch_pending(logger: logging.Logger) -> dict[str, dict[str, Any]]:
    """아직 일일 요약하지 않은 WATCH 기사를 읽는다."""
    if not WATCH_PENDING_FILE.exists():
        return {}
    try:
        raw = json.loads(WATCH_PENDING_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("최상위 JSON 값이 객체가 아님")
        return {
            str(article_id): article
            for article_id, article in raw.items()
            if isinstance(article, dict)
        }
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        logger.error("WATCH 대기 파일 읽기 실패, 빈 상태로 시작: %s", exc)
        return {}


def save_watch_pending(
    pending: dict[str, dict[str, Any]], logger: logging.Logger
) -> None:
    """WATCH 대기 기사를 BOM 없는 UTF-8 JSON으로 저장한다."""
    try:
        WATCH_PENDING_FILE.write_text(
            json.dumps(pending, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        logger.error("WATCH 대기 파일 저장 실패: %s", exc)


def last_watch_summary_date(logger: logging.Logger) -> str:
    if not WATCH_SUMMARY_DATE_FILE.exists():
        return ""
    try:
        return WATCH_SUMMARY_DATE_FILE.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        logger.error("WATCH 요약 날짜 읽기 실패: %s", exc)
        return ""


def save_watch_summary_date(date_text: str, logger: logging.Logger) -> None:
    try:
        WATCH_SUMMARY_DATE_FILE.write_text(date_text + "\n", encoding="utf-8")
    except OSError as exc:
        logger.error("WATCH 요약 날짜 저장 실패: %s", exc)


def _persist_user_environment(name: str, value: str, logger: logging.Logger) -> None:
    """현재 프로세스와 Windows 사용자 환경변수에 값을 저장한다."""
    os.environ[name] = value
    if os.name != "nt":
        return
    try:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    except OSError as exc:
        logger.error("사용자 환경변수 저장 실패 [%s]: %s", name, exc)


def refresh_kakao_token(logger: logging.Logger) -> str | None:
    """리프레시 토큰으로 액세스 토큰을 갱신하고 안전하게 보존한다."""
    refresh_token = os.environ.get("NOTIFY_KAKAO_REFRESH_TOKEN", "")
    rest_api_key = os.environ.get("KAKAO_REST_API_KEY", "")
    client_secret = os.environ.get("KAKAO_CLIENT_SECRET", "")
    if not refresh_token or not rest_api_key:
        logger.error(
            "카카오 자동 갱신 설정 부족: NOTIFY_KAKAO_REFRESH_TOKEN/KAKAO_REST_API_KEY 확인 필요"
        )
        return None

    payload = {
        "grant_type": "refresh_token",
        "client_id": rest_api_key,
        "refresh_token": refresh_token,
    }
    if client_secret:
        payload["client_secret"] = client_secret

    try:
        response = requests.post(
            KAKAO_TOKEN_URL,
            data=payload,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        try:
            body = response.json()
        except ValueError:
            body = {}

        new_access_token = body.get("access_token")
        if not response.ok or not new_access_token:
            error_code = body.get("error", "unknown")
            error_description = body.get("error_description", response.text[:200])
            logger.error(
                "카카오 토큰 갱신 실패 [%s] %s: %s",
                response.status_code,
                error_code,
                error_description,
            )
            return None

        _persist_user_environment("NOTIFY_KAKAO_TOKEN", new_access_token, logger)
        new_refresh_token = body.get("refresh_token")
        if new_refresh_token:
            _persist_user_environment(
                "NOTIFY_KAKAO_REFRESH_TOKEN", new_refresh_token, logger
            )
        logger.info(
            "카카오 토큰 자동 갱신 완료 (access %s초, refresh 갱신=%s)",
            body.get("expires_in", "unknown"),
            bool(new_refresh_token),
        )
        return new_access_token
    except requests.RequestException as exc:
        logger.error("카카오 토큰 갱신 요청 실패: %s", exc)
        return None


def ensure_kakao_token(logger: logging.Logger) -> str | None:
    """토큰이 없거나 1시간 이내 만료 예정이면 자동으로 갱신한다."""
    token = os.environ.get("NOTIFY_KAKAO_TOKEN", "")
    if not token:
        logger.warning("카카오 액세스 토큰 없음 — 자동 갱신 시도")
        return refresh_kakao_token(logger)

    try:
        response = requests.get(
            KAKAO_TOKEN_INFO_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        if response.status_code == 401:
            logger.warning("카카오 액세스 토큰 만료 — 자동 갱신 시도")
            return refresh_kakao_token(logger)
        if not response.ok:
            logger.warning(
                "카카오 토큰 상태 확인 실패 [%s] — 기존 토큰으로 계속",
                response.status_code,
            )
            return token

        expires_in = int(response.json().get("expires_in", 0))
        if expires_in <= KAKAO_REFRESH_MARGIN_SECONDS:
            logger.info("카카오 토큰 만료 임박 (%s초) — 자동 갱신", expires_in)
            return refresh_kakao_token(logger)
        logger.info("카카오 토큰 정상 (잔여 %s초)", expires_in)
        return token
    except (requests.RequestException, TypeError, ValueError) as exc:
        logger.warning("카카오 토큰 상태 확인 오류 — 기존 토큰으로 계속: %s", exc)
        return token


def _kakao_send_request(token: str, text: str):
    import urllib.error
    import urllib.parse
    import urllib.request
    template = {
        "object_type": "text",
        "text": text[:1000],
        "link": {"web_url": "", "mobile_web_url": ""},
        "button_title": "SFD 뉴스",
    }
    body = urllib.parse.urlencode(
        {"template_object": json.dumps(template, ensure_ascii=False)}
    ).encode("utf-8")
    req = urllib.request.Request(
        KAKAO_API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            status = resp.status
            body_text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status = exc.code
        body_text = exc.read().decode("utf-8", errors="replace")

    class _Response:
        status_code = status
        text = body_text
        ok = 200 <= status < 300
        def json(self):
            return json.loads(body_text)
    return _Response()


def send_kakao(text: str, logger: logging.Logger) -> bool:
    token = os.environ.get("NOTIFY_KAKAO_TOKEN", "")
    if not token:
        token = refresh_kakao_token(logger) or ""
        if not token:
            logger.warning("카카오 토큰 없음 (환경변수 NOTIFY_KAKAO_TOKEN)")
            return False
    try:
        response = _kakao_send_request(token, text)
        logger.info("카카오 응답 [%s]: %s", response.status_code, response.text[:300])
        if response.status_code == 401:
            logger.warning("카카오 401 — 토큰 자동 갱신 후 1회 재전송")
            token = refresh_kakao_token(logger) or ""
            if not token:
                logger.error("KAKAO_TOKEN_EXPIRED: 자동 갱신 실패")
                return False
            response = _kakao_send_request(token, text)
            logger.info(
                "카카오 재전송 응답 [%s]: %s",
                response.status_code,
                response.text[:300],
            )
        try:
            result_code = response.json().get("result_code")
        except (ValueError, AttributeError):
            result_code = None
        if response.ok and result_code == 0:
            logger.info("카카오 발송 완료")
            return True
        logger.error("카카오 발송 실패 [%s]: %s", response.status_code, response.text)
    except Exception as exc:
        logger.exception("카카오 발송 오류: %s", exc)
    return False


def clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def matched_keywords(text: str, keywords: tuple[str, ...]) -> list[str]:
    folded = text.casefold()
    return [kw for kw in keywords if kw.casefold() in folded]


def published_at_utc(entry: Any) -> datetime | None:
    parsed = entry.get("published_parsed")
    if not parsed:
        return None
    try:
        return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
    except (OverflowError, TypeError, ValueError):
        return None


def article_id(entry: Any) -> str:
    source_id = clean_text(entry.get("id") or entry.get("guid"))
    if source_id:
        return source_id
    basis = f"{entry.get('link', '')}|{entry.get('title', '')}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def collect_feed(feed_name: str, feed_url: str, now: datetime, logger: logging.Logger) -> list[dict[str, Any]]:
    try:
        response = requests.get(feed_url, headers={"User-Agent": "SFD-News-Sentinel/1.0"}, timeout=HTTP_TIMEOUT_SECONDS)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        if getattr(feed, "bozo", False) and not feed.entries:
            raise RuntimeError(str(getattr(feed, "bozo_exception", "RSS 파싱 실패")))
    except Exception as exc:
        logger.error("RSS 수집 실패 [%s], 건너뜀: %s", feed_name, exc)
        return []
    cutoff = now - ARTICLE_MAX_AGE
    matched: list[dict[str, Any]] = []
    for entry in feed.entries:
        published_at = published_at_utc(entry)
        if published_at is None or not cutoff <= published_at <= now:
            continue
        title = clean_text(entry.get("title"))
        summary = clean_text(entry.get("summary") or entry.get("description"))
        trigger_hits = matched_keywords(f"{title} {summary}", TRIGGER_KEYWORDS)
        if not trigger_hits:
            continue
        impact_hits = matched_keywords(f"{title} {summary}", IMPACT_KEYWORDS)
        matched.append({
            "id": article_id(entry),
            "feed": feed_name,
            "title": title or "(제목 없음)",
            "summary": summary,
            "link": clean_text(entry.get("link")),
            "published_at": published_at,
            "trigger_hits": trigger_hits,
            "impact_hits": impact_hits,
            "level": "CRITICAL" if impact_hits else "WATCH",
        })
    logger.info("RSS 수집 완료 [%s]: 전체 %d건, 조건 매칭 %d건", feed_name, len(feed.entries), len(matched))
    return matched


def format_critical(article: dict[str, Any]) -> str:
    return (
        "[SFD NEWS CRITICAL]\n"
        f"{article['title']}\n"
        f"트리거: {', '.join(article['trigger_hits'])}\n"
        f"영향: {', '.join(article['impact_hits'])}\n"
        f"출처: {article['feed']}\n"
        f"{article['link']}"
    )


def format_watch_summary(articles: list[dict[str, Any]], now: datetime) -> str:
    header = f"[SFD NEWS WATCH] {now.astimezone().strftime('%Y-%m-%d')} 요약 ({len(articles)}건)"
    lines = [header]
    for index, article in enumerate(articles, 1):
        candidate = "\n".join(lines + [f"{index}. {article['title']}\n{article['link']}"])
        if len(candidate) > 930:
            lines.append(f"외 {len(articles) - index + 1}건")
            break
        lines.append(f"{index}. {article['title']}\n{article['link']}")
    return "\n".join(lines)


def main() -> int:
    now = datetime.now(timezone.utc)
    logger = configure_logging(now)
    logger.info("SFD 뉴스 감시 시작")
    ensure_kakao_token(logger)
    seen_ids = load_seen_ids(now, logger)
    watch_pending = load_watch_pending(logger)
    processed_ids = set(seen_ids) | set(watch_pending)
    critical_count = 0
    new_watch_count = 0
    for feed_name, feed_url in RSS_FEEDS:
        for article in collect_feed(feed_name, feed_url, now, logger):
            if article["id"] in processed_ids:
                logger.info("중복 기사 건너뜀: %s", article["title"])
                continue
            processed_ids.add(article["id"])
            if article["level"] == "CRITICAL":
                critical_count += 1
                sent = send_kakao(format_critical(article), logger)
                logger.info("CRITICAL 처리 (%s): %s", "발송" if sent else "발송 실패", article["title"])
                if sent:
                    seen_ids[article["id"]] = now.isoformat()
                    save_seen_ids(seen_ids, logger)
            else:
                new_watch_count += 1
                watch_pending[article["id"]] = {
                    "id": article["id"],
                    "feed": article["feed"],
                    "title": article["title"],
                    "link": article["link"],
                    "trigger_hits": article["trigger_hits"],
                    "queued_at": now.isoformat(),
                }
                # WATCH는 발송 성공 여부와 무관하게 중복 수집하지 않는다.
                seen_ids[article["id"]] = now.isoformat()

    local_date = now.astimezone().date().isoformat()
    summary_sent_today = last_watch_summary_date(logger) == local_date
    if watch_pending and not summary_sent_today:
        pending_articles = list(watch_pending.values())
        sent = send_kakao(format_watch_summary(pending_articles, now), logger)
        logger.info(
            "WATCH 일일 요약 처리: %d건 (%s)",
            len(pending_articles),
            "발송" if sent else "발송 실패",
        )
        if sent:
            watch_pending.clear()
            save_watch_summary_date(local_date, logger)
    elif watch_pending:
        logger.info("WATCH %d건 대기 중 — 오늘 요약은 이미 발송됨", len(watch_pending))

    save_seen_ids(seen_ids, logger)
    save_watch_pending(watch_pending, logger)
    logger.info(
        "SFD 뉴스 감시 종료: CRITICAL %d건, 신규 WATCH %d건, 대기 WATCH %d건",
        critical_count,
        new_watch_count,
        len(watch_pending),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
