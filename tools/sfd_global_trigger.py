"""
sfd_global_trigger.py  v1.0
Layer 0.5 — 글로벌 트리거 선행 감지
======================================
목적: 미국 전일 주가 움직임 → 한국 연관 종목 사전 부스트 점수 산출
      "뒷북" → "한 발 앞서" 전환의 핵심 선행 레이어

출력: outputs/latest/sfd_global_trigger_latest.csv
      columns: ticker, kr_name, trigger_source, us_pct_chg, boost_score, signal_reason

실행 시점: 매일 08:20 KST (메인 파이프라인 08:35 이전)
작성: Claude (Anthropic) | 2026.06.01
"""

import os
import json
import logging
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from pathlib import Path

# ── 경로 설정 ──────────────────────────────────────────────────────────────
BASE_DIR = os.environ.get("SFD_BASE_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs", "latest")
os.makedirs(OUTPUT_DIR, exist_ok=True)

LOG_PATH = os.path.join(OUTPUT_DIR, "sfd_global_trigger.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# ── 임계값 설정 ────────────────────────────────────────────────────────────
STRONG_THRESH   = 4.0   # 강한 트리거: ±4% 이상 → boost ±15pt
MEDIUM_THRESH   = 2.0   # 중간 트리거: ±2% 이상 → boost ±8pt
WEAK_THRESH     = 1.0   # 약한 트리거: ±1% 이상 → boost ±3pt
ETF_MULTIPLIER  = 0.7   # ETF 기반 트리거는 70% 가중 (직접 종목보다 약함)

# ── 글로벌 트리거 맵 ────────────────────────────────────────────────────────
# 구조: US_ticker → [(KR_ticker, KR_name, 상관강도[1.0=최대]), ...]
TRIGGER_MAP = {

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 피지컬 AI / 로보틱스
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    "NVDA": [
        ("454910", "두산로보틱스",    1.0),
        ("277810", "레인보우로보틱스", 1.0),
        ("108490", "로보티즈",        0.9),
        ("000660", "SK하이닉스",      0.8),
        ("005930", "삼성전자",        0.7),
        ("066570", "LG전자",          0.7),
        ("011070", "LG이노텍",        0.6),
    ],
    "AMD": [
        ("000660", "SK하이닉스",      0.8),
        ("005930", "삼성전자",        0.7),
        ("042700", "한미반도체",      0.7),
    ],

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 반도체 / 소부장
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    "TSM": [   # TSMC
        ("000660", "SK하이닉스",      0.9),
        ("005930", "삼성전자",        0.8),
        ("042700", "한미반도체",      0.8),
        ("009150", "삼성전기",        0.7),
        ("003990", "한솔케미칼",      0.6),
    ],
    "ASML": [
        ("042700", "한미반도체",      0.9),
        ("000660", "SK하이닉스",      0.7),
        ("240810", "원익IPS",         0.7),
    ],
    "AMAT": [  # Applied Materials
        ("042700", "한미반도체",      0.8),
        ("240810", "원익IPS",         0.7),
        ("131970", "테크윙",          0.6),
    ],
    "SOXX": [  # 반도체 ETF
        ("000660", "SK하이닉스",      0.8),
        ("005930", "삼성전자",        0.8),
        ("042700", "한미반도체",      0.7),
    ],

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 2차전지 / EV
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    "TSLA": [
        ("086520", "에코프로",        0.9),
        ("247540", "에코프로비엠",    0.9),
        ("373220", "LG에너지솔루션",  0.8),
        ("003670", "포스코퓨처엠",    0.8),
        ("277810", "레인보우로보틱스", 0.7),  # Optimus 연동
        ("066570", "LG전자",          0.6),
    ],
    "LIT": [   # 리튬/배터리 ETF
        ("086520", "에코프로",        0.8),
        ("247540", "에코프로비엠",    0.8),
        ("373220", "LG에너지솔루션",  0.7),
        ("003670", "포스코퓨처엠",    0.7),
        ("006400", "삼성SDI",         0.7),
    ],
    "F": [     # Ford (전기차)
        ("373220", "LG에너지솔루션",  0.7),
        ("006400", "삼성SDI",         0.7),
    ],

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 방산 / 우주
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    "LMT": [   # Lockheed Martin
        ("012450", "한화에어로스페이스", 0.9),
        ("079550", "LIG넥스원",         0.8),
        ("064350", "현대로템",           0.7),
        ("006260", "LS",                 0.5),
    ],
    "RTX": [   # Raytheon
        ("012450", "한화에어로스페이스", 0.8),
        ("079550", "LIG넥스원",         0.8),
    ],
    "ITA": [   # 방산 ETF
        ("012450", "한화에어로스페이스", 0.8),
        ("079550", "LIG넥스원",         0.7),
        ("064350", "현대로템",           0.6),
    ],

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 바이오 / 헬스케어
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    "XBI": [   # 바이오 ETF
        ("207940", "삼성바이오로직스", 0.8),
        ("068270", "셀트리온",         0.8),
        ("326030", "SK바이오팜",       0.7),
    ],
    "PFE": [
        ("207940", "삼성바이오로직스", 0.7),
        ("068270", "셀트리온",         0.7),
    ],

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 전력 / 에너지 인프라
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    "NEE": [   # NextEra Energy
        ("052690", "한전기술",    0.8),
        ("010120", "LS일렉트릭",  0.7),
        ("001440", "대한전선",    0.7),
    ],
    "XLU": [   # 유틸리티 ETF
        ("052690", "한전기술",    0.7),
        ("010120", "LS일렉트릭",  0.7),
    ],

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 해운 / 물류
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    "FDX": [
        ("011200", "HMM",      0.7),
        ("028670", "팬오션",   0.7),
        ("003490", "대한항공",  0.6),
    ],

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 구리 / 소재
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    "COPX": [  # 구리 광산 ETF
        ("010120", "LS일렉트릭",  0.8),
        ("001440", "대한전선",    0.8),
        ("006260", "LS",          0.7),
    ],

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 클라우드 / AI 소프트웨어
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    "MSFT": [
        ("035420", "NAVER",       0.7),
        ("035720", "카카오",      0.6),
        ("383220", "LG CNS",      0.6),
    ],
    "GOOG": [
        ("035420", "NAVER",       0.8),
        ("066570", "LG전자",      0.7),  # AAOS 협력
        ("035720", "카카오",      0.5),
    ],
}

# ── ETF 여부 판별 ────────────────────────────────────────────────────────
ETF_TICKERS = {"SOXX", "LIT", "ITA", "XBI", "XLU", "COPX"}


def fetch_us_changes() -> dict:
    """미국 전일 등락률 조회. 반환: {ticker: pct_change}"""
    result = {}
    us_tickers = list(TRIGGER_MAP.keys())
    log.info(f"미국 티커 {len(us_tickers)}개 조회 중...")

    try:
        raw = yf.download(
            us_tickers,
            period="3d",
            auto_adjust=True,
            progress=False,
            threads=True
        )
        closes = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw

        for ticker in us_tickers:
            try:
                if ticker in closes.columns:
                    vals = closes[ticker].dropna()
                    if len(vals) >= 2:
                        pct = (vals.iloc[-1] / vals.iloc[-2] - 1) * 100
                        result[ticker] = round(float(pct), 2)
                        log.info(f"  {ticker:6s}: {pct:+.2f}%")
                    else:
                        log.warning(f"  {ticker}: 데이터 부족")
                else:
                    log.warning(f"  {ticker}: 조회 실패")
            except Exception as e:
                log.warning(f"  {ticker} 처리 오류: {e}")
    except Exception as e:
        log.error(f"yfinance 일괄 조회 오류: {e}")

    return result


def calc_boost(pct_chg: float, corr: float, is_etf: bool) -> int:
    """등락률 + 상관강도 → 부스트 점수 계산"""
    multiplier = ETF_MULTIPLIER if is_etf else 1.0
    abs_pct = abs(pct_chg)

    if abs_pct >= STRONG_THRESH:
        raw = 15
    elif abs_pct >= MEDIUM_THRESH:
        raw = 8
    elif abs_pct >= WEAK_THRESH:
        raw = 3
    else:
        return 0

    direction = 1 if pct_chg > 0 else -1
    return round(direction * raw * corr * multiplier)


def build_trigger_signals(us_changes: dict) -> pd.DataFrame:
    """트리거 신호 DataFrame 생성"""
    rows = []
    triggered = {}  # KR ticker별 boost 누적

    for us_ticker, pct in us_changes.items():
        if abs(pct) < WEAK_THRESH:
            continue

        is_etf = us_ticker in ETF_TICKERS
        kr_list = TRIGGER_MAP.get(us_ticker, [])

        for kr_ticker, kr_name, corr in kr_list:
            boost = calc_boost(pct, corr, is_etf)
            if boost == 0:
                continue

            key = kr_ticker
            if key not in triggered:
                triggered[key] = {
                    "ticker": kr_ticker,
                    "kr_name": kr_name,
                    "trigger_sources": [],
                    "boost_total": 0,
                    "max_us_pct": 0.0,
                }

            triggered[key]["trigger_sources"].append(
                f"{us_ticker}({pct:+.1f}%)"
            )
            triggered[key]["boost_total"] += boost
            if abs(pct) > abs(triggered[key]["max_us_pct"]):
                triggered[key]["max_us_pct"] = pct

    for key, d in triggered.items():
        boost = d["boost_total"]
        sources = ", ".join(d["trigger_sources"])

        if boost >= 10:
            signal = "GLOBAL_STRONG_BUY"
        elif boost >= 5:
            signal = "GLOBAL_BUY"
        elif boost >= 1:
            signal = "GLOBAL_WATCH"
        elif boost <= -10:
            signal = "GLOBAL_STRONG_SELL"
        elif boost <= -5:
            signal = "GLOBAL_SELL"
        else:
            signal = "GLOBAL_CAUTION"

        rows.append({
            "ticker":         d["ticker"],
            "kr_name":        d["kr_name"],
            "trigger_source": sources,
            "us_pct_chg":     d["max_us_pct"],
            "boost_score":    min(max(boost, -20), 20),  # ±20pt 캡
            "signal":         signal,
            "updated_at":     datetime.now().strftime("%Y-%m-%d %H:%M"),
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("boost_score", ascending=False).reset_index(drop=True)
    return df


def save_outputs(df: pd.DataFrame):
    """CSV + JSON 저장"""
    csv_path  = os.path.join(OUTPUT_DIR, "sfd_global_trigger_latest.csv")
    json_path = os.path.join(OUTPUT_DIR, "sfd_global_trigger_latest.json")

    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    summary = {
        "updated_at": datetime.now().isoformat(),
        "total_triggered": len(df),
        "strong_buy":  int((df["signal"] == "GLOBAL_STRONG_BUY").sum()),
        "buy":         int((df["signal"] == "GLOBAL_BUY").sum()),
        "watch":       int((df["signal"] == "GLOBAL_WATCH").sum()),
        "sell_risk":   int(df["signal"].str.contains("SELL|CAUTION").sum()),
        "top5": df.head(5)[["ticker","kr_name","boost_score","signal","trigger_source"]].to_dict("records"),
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    log.info(f"저장 완료: {csv_path}")
    log.info(f"저장 완료: {json_path}")
    return csv_path, json_path


def print_summary(df: pd.DataFrame, us_changes: dict):
    """콘솔 요약 출력"""
    log.info("=" * 60)
    log.info("  GLOBAL TRIGGER 선행 신호 요약")
    log.info("=" * 60)
    log.info(f"  미국 조회: {len(us_changes)}개 티커")
    log.info(f"  KR 트리거: {len(df)}개 종목")

    if df.empty:
        log.info("  유효 트리거 없음 (전일 미국 시장 변동 미미)")
        return

    buy_df  = df[df["boost_score"] > 0].head(10)
    sell_df = df[df["boost_score"] < 0].head(5)

    if not buy_df.empty:
        log.info("\n  매수 선행 신호 (상위 10):")
        for _, r in buy_df.iterrows():
            log.info(f"    {r['ticker']} {r['kr_name']:15s} boost={r['boost_score']:+3d}pt  [{r['trigger_source']}]")

    if not sell_df.empty:
        log.info("\n  리스크 신호 (상위 5):")
        for _, r in sell_df.iterrows():
            log.info(f"    {r['ticker']} {r['kr_name']:15s} boost={r['boost_score']:+3d}pt  [{r['trigger_source']}]")

    log.info("=" * 60)


def main():
    log.info("sfd_global_trigger v1.0 시작")

    us_changes = fetch_us_changes()

    if not us_changes:
        log.error("미국 데이터 조회 실패 -- 빈 파일 저장 후 종료")
        empty = pd.DataFrame(columns=[
            "ticker","kr_name","trigger_source",
            "us_pct_chg","boost_score","signal","updated_at"
        ])
        save_outputs(empty)
        return

    df = build_trigger_signals(us_changes)
    print_summary(df, us_changes)
    save_outputs(df)
    log.info("sfd_global_trigger 완료")


if __name__ == "__main__":
    main()
