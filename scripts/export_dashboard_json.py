# export_dashboard_json.py v1.0
# SFD GitHub Pages 대시보드용 JSON 생성기
# 위치: sfd-pipeline/scripts/export_dashboard_json.py
# 실행: GitHub Actions 파이프라인 마지막 step
#
# 입력:
#   outputs/latest/sfd_master_signal_latest.csv  → TOP10 시그널
#   outputs/latest/sfd_prev_close_latest.csv      → 현재가(종가)
#   outputs/latest/sfd_portfolio_status.csv        → 포트폴리오 상태
#   outputs/latest/sfd_alerts.json                 → 거미줄 알람
#   portfolio.json                                  → 보유종목 메타
# 출력:
#   dashboard/data/sfd_dashboard_data.json

import os
import json
import csv
import sys
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── 경로 설정 ──────────────────────────────────────────────
_HERE   = Path(__file__).resolve().parent          # scripts/
_ROOT   = _HERE.parent                             # sfd-pipeline/
_LATEST = _ROOT / "outputs" / "latest"
_DASH   = _ROOT / "dashboard" / "data"
_DASH.mkdir(parents=True, exist_ok=True)

OUT_FILE      = _DASH / "sfd_dashboard_data.json"
MASTER_CSV    = _LATEST / "sfd_master_signal_latest.csv"
CLOSE_CSV     = _LATEST / "sfd_prev_close_latest.csv"
STATUS_CSV    = _LATEST / "sfd_portfolio_status.csv"
ALERTS_JSON   = _LATEST / "sfd_alerts.json"
PORTFOLIO_JSON = _ROOT  / "portfolio.json"
ACCURACY_JSON = _LATEST / "sfd_accuracy_tracker.json"

KST = timezone(timedelta(hours=9))
TOP_N = 10

# 거미줄 트리거 확정값 (V15.6 기준 — portfolio.json과 동기)
SPIDER_TRIGGER = {
    "001440": {"name": "대한전선",    "trigger_price": 26075,  "avg_price": 46575},
    "006260": {"name": "LS",          "trigger_price": 260225, "avg_price": 496938},
    "034020": {"name": "두산에너빌리티","trigger_price": 56000,  "avg_price": 101960},
    "052690": {"name": "한전기술",    "trigger_price": 68600,  "avg_price": 142467},
}


# ── 1. KIS API 현재가 조회 ──────────────────────────────────
def fetch_kis_price(ticker: str, token: str) -> float | None:
    """KIS REST API — 주식현재가시세 (fhkst01010100)"""
    url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-price"
    headers = {
        "content-type":  "application/json",
        "authorization": f"Bearer {token}",
        "appkey":        os.environ.get("KIS_APP_KEY", ""),
        "appsecret":     os.environ.get("KIS_APP_SECRET", ""),
        "tr_id":         "FHKST01010100",
        "custtype":      "P",
    }
    params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": ticker}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=8)
        data = resp.json()
        price = data.get("output", {}).get("stck_prpr", "0")
        return float(price) if price else None
    except Exception as e:
        print(f"[KIS] {ticker} 가격조회 실패: {e}")
        return None


def get_kis_token() -> str | None:
    """KIS 접근토큰 발급"""
    url = "https://openapi.koreainvestment.com:9443/oauth2/tokenP"
    body = {
        "grant_type": "client_credentials",
        "appkey":     os.environ.get("KIS_APP_KEY", ""),
        "appsecret":  os.environ.get("KIS_APP_SECRET", ""),
    }
    try:
        resp = requests.post(url, json=body, timeout=10)
        token = resp.json().get("access_token")
        if token:
            print("[KIS] 토큰 발급 성공")
        else:
            print(f"[KIS] 토큰 발급 실패: {resp.text[:100]}")
        return token
    except Exception as e:
        print(f"[KIS] 토큰 요청 실패: {e}")
        return None


def fetch_all_prices(tickers: list[str]) -> dict:
    """KIS 토큰 1회 발급 → 전체 종목 가격 일괄 조회"""
    token = get_kis_token()
    prices = {}
    if not token:
        print("[KIS] 토큰 없음 → 현재가 N/A")
        return prices
    for t in tickers:
        p = fetch_kis_price(t, token)
        if p:
            prices[t] = p
            print(f"[KIS] {t}: {p:,.0f}원")
    return prices


# ── 2. CSV 파서 ─────────────────────────────────────────────
def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        print(f"[WARN] 파일 없음: {path.name}")
        return []
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def safe_float(val, default=0.0) -> float:
    try:
        return float(str(val).replace(",", "").replace("+", ""))
    except:
        return default


# ── 3. TOP10 시그널 추출 ────────────────────────────────────
def build_top10(rows: list[dict]) -> list[dict]:
    """
    sfd_master_signal_latest.csv → BUY_STRONG / BUY 종목 상위 10개
    score 컬럼 우선순위: sfd_score > adjusted_fund_score > total_score
    """
    def score_of(r):
        for col in ("sfd_score", "adjusted_fund_score", "total_score"):
            v = r.get(col)
            if v not in (None, "", "nan"):
                return safe_float(v)
        return 0.0

    # BUY_STRONG → BUY → WATCH_ONLY 순서로 필터
    buy_rows = [r for r in rows if r.get("signal", "").upper() in ("BUY_STRONG", "BUY", "RESERVE_BUY")]
    if not buy_rows:
        buy_rows = rows  # fallback: 전체 기준

    buy_rows.sort(key=score_of, reverse=True)

    result = []
    for i, r in enumerate(buy_rows[:TOP_N], 1):
        ticker = str(r.get("ticker", "")).zfill(6)
        bm_scores = {}
        for col in r:
            if col.startswith("bm") and "_score" in col:
                bm_scores[col] = safe_float(r[col])

        result.append({
            "rank":          i,
            "ticker":        ticker,
            "name":          r.get("name", r.get("stock_name", ticker)),
            "sfd_score":     round(score_of(r), 2),
            "signal":        r.get("signal", "N/A").upper(),
            "bm_scores":     bm_scores,
            "trigger_chain": r.get("vc_chain", r.get("industry_chain", "")),
            "sector":        r.get("sector_major", r.get("sector", "")),
        })
    return result


# ── 4. 포트폴리오 섹션 ──────────────────────────────────────
def build_portfolio(prices: dict) -> dict:
    """
    SPIDER_TRIGGER 기준 4종목 상태 계산
    portfolio.json이 있으면 avg_price, qty 업데이트
    """
    # portfolio.json 로드 (있으면)
    port_meta = {}
    if PORTFOLIO_JSON.exists():
        with open(PORTFOLIO_JSON, encoding="utf-8") as f:
            pj = json.load(f)
        for h in pj.get("holdings", []):
            tk = str(h.get("ticker", "")).zfill(6)
            port_meta[tk] = h

    portfolio = {}
    for ticker, meta in SPIDER_TRIGGER.items():
        cur = prices.get(ticker)
        avg = safe_float(port_meta.get(ticker, {}).get("avg_price", meta["avg_price"]))
        qty = int(port_meta.get(ticker, {}).get("qty", 0))
        trigger = meta["trigger_price"]

        pnl_pct = round((cur - avg) / avg * 100, 2) if cur and avg else None

        # 거미줄 상태
        if cur is None:
            spider_status = "조회불가"
        elif cur <= trigger:
            spider_status = "🔴 발동"
        elif cur <= trigger * 1.05:
            spider_status = "🟡 근접(5%이내)"
        else:
            spider_status = "🟢 미발동"

        # 총평가금액
        eval_amt = round(cur * qty) if cur and qty else None

        portfolio[meta["name"]] = {
            "ticker":        ticker,
            "avg_price":     avg,
            "qty":           qty,
            "trigger_price": trigger,
            "current_price": cur,
            "pnl_pct":       pnl_pct,
            "eval_amt":      eval_amt,
            "spider_status": spider_status,
            "phase":         "A안 (회복·현금확보)",
        }
    return portfolio


# ── 5. 정확도 트래커 ────────────────────────────────────────
def build_accuracy() -> dict:
    if ACCURACY_JSON.exists():
        with open(ACCURACY_JSON, encoding="utf-8") as f:
            return json.load(f)
    # fallback: status.csv에서 추정
    rows = read_csv(STATUS_CSV)
    return {
        "d1":               None,
        "d3":               None,
        "d5":               None,
        "total_predictions": len(rows),
        "note":             "accuracy_tracker.json 없음 — 수동 업데이트 필요",
    }


# ── 6. 알람 섹션 ────────────────────────────────────────────
def build_alerts() -> list[dict]:
    if not ALERTS_JSON.exists():
        return []
    with open(ALERTS_JSON, encoding="utf-8") as f:
        data = json.load(f)
    # alerts.json 구조: {"alerts": [...]} 또는 [...]
    if isinstance(data, list):
        return data[:10]
    return data.get("alerts", data.get("grid_alerts", []))[:10]


# ── 7. 거시환경 (macro) — prev_close CSV 또는 Actions 환경변수 ──
def build_macro() -> dict:
    """
    우선순위:
    1. Actions 환경변수 (MACRO_KOSPI, MACRO_USD_KRW 등)
    2. prev_close_latest.csv 인덱스 행
    3. N/A fallback
    """
    def env_float(key):
        v = os.environ.get(key)
        return float(v) if v else None

    macro = {
        "kospi":    env_float("MACRO_KOSPI"),
        "kosdaq":   env_float("MACRO_KOSDAQ"),
        "usd_krw":  env_float("MACRO_USD_KRW"),
        "us_rate":  env_float("MACRO_US_RATE")  or 3.625,
        "kr_rate":  env_float("MACRO_KR_RATE")  or 2.75,
        "vix":      env_float("MACRO_VIX"),
        "sp500":    env_float("MACRO_SP500"),
        "nasdaq":   env_float("MACRO_NASDAQ"),
    }

    # prev_close에서 인덱스 행 탐색 (ticker가 ^KOSPI / 코스피 등)
    rows = read_csv(CLOSE_CSV)
    idx_map = {
        "^KS11": "kospi", "코스피": "kospi", "KOSPI": "kospi",
        "^KQ11": "kosdaq", "코스닥": "kosdaq",
        "^GSPC": "sp500", "^IXIC": "nasdaq",
        "^VIX":  "vix",
    }
    for r in rows:
        tk = r.get("ticker", "").strip()
        if tk in idx_map:
            key = idx_map[tk]
            if macro[key] is None:
                for col in ("close", "prev_close", "close_price", "종가"):
                    if col in r:
                        macro[key] = safe_float(r[col]) or None
                        break

    return macro


# ── 8. 메인 ────────────────────────────────────────────────
def main():
    now_kst = datetime.now(KST)
    print(f"[export_dashboard_json] 시작: {now_kst.strftime('%Y-%m-%d %H:%M:%S KST')}")

    # GitHub Actions Run ID
    run_id = os.environ.get("GITHUB_RUN_NUMBER", "local")

    # ① 현재가 일괄 조회 (KIS API)
    all_tickers = list(SPIDER_TRIGGER.keys())
    master_rows = read_csv(MASTER_CSV)
    # TOP10 후보 ticker도 함께 조회
    top10_tickers = [str(r.get("ticker","")).zfill(6) for r in master_rows[:20]]
    all_query = list(set(all_tickers + top10_tickers))
    prices = fetch_all_prices(all_query)

    # ② 섹션별 빌드
    top10    = build_top10(master_rows)
    # top10에 현재가 주입
    for item in top10:
        item["current_price"] = prices.get(item["ticker"])

    portfolio = build_portfolio(prices)
    accuracy  = build_accuracy()
    alerts    = build_alerts()
    macro     = build_macro()

    # ③ 최종 JSON 조립
    dashboard = {
        "meta": {
            "generated_at":      now_kst.isoformat(),
            "generated_at_kst":  now_kst.strftime("%Y-%m-%d %H:%M KST"),
            "run_id":            run_id,
            "pipeline_version":  "yml_v10.6_agg_v4.1.2_waist_v1.0",
            "data_date":         now_kst.strftime("%Y-%m-%d"),
        },
        "macro":       macro,
        "top10_signals": top10,
        "portfolio":   portfolio,
        "accuracy":    accuracy,
        "alerts":      alerts,
    }

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, ensure_ascii=False, indent=2)

    size_kb = OUT_FILE.stat().st_size / 1024
    print(f"[OK] 저장 완료: {OUT_FILE} ({size_kb:.1f} KB)")
    print(f"[OK] TOP10: {len(top10)}개 | 포트폴리오: {len(portfolio)}종목 | 알람: {len(alerts)}건")


if __name__ == "__main__":
    main()
