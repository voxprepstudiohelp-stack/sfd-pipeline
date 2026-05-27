#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sfd_portfolio_monitor.py — Layer 5  v1.0
SFD 포트폴리오 모니터 + 거미줄 매매 단계 추적

역할:
  - portfolio.json (보유 종목 + 거미줄 전략) 로드
  - sfd_prev_close_latest.csv (현재가) 로드
  - sfd_signal.csv (Layer 4 SFD 신호) 로드
  - 종목별 수익률 계산 + 거미줄 단계 점검
  - 알림 생성 (WEB_TRIGGER / WEB_NEAR / SFD_UPGRADE / CATASTROPHIC)
  - portfolio.json status 자동 업데이트

알림 등급:
  🔴 WEB_TRIGGER   : 거미줄 추가매수 트리거 도달
  🟡 WEB_NEAR      : 트리거 5% 이내 접근
  🟢 SFD_UPGRADE   : SFD 신호 상승 (HOLD → WATCH_ONLY → RESERVE_BUY)
  🔵 SFD_NEW_ENTRY : 미보유 종목 SFD 신규 진입
  ⚫ CATASTROPHIC   : catastrophic_flag 수동 활성화 시

흐름도:
  IN  : portfolio.json
  IN  : outputs/latest/sfd_prev_close_latest.csv  (현재가)
  IN  : outputs/latest/sfd_signal.csv             (SFD 신호)
  OUT : outputs/latest/sfd_portfolio_status.csv
  OUT : outputs/latest/sfd_alerts.json
  MOD : portfolio.json  (status 필드 자동 업데이트)

버전: v1.0
작성: Claude Sonnet 4.6 (2026-05-27)
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

# ============================
# 경로 설정
# ============================
_HERE          = Path(__file__).resolve().parent
_PIPELINE_ROOT = _HERE.parent
_LATEST        = _PIPELINE_ROOT / "outputs" / "latest"

PORTFOLIO_FILE   = _PIPELINE_ROOT / "portfolio.json"
CLOSE_FILE       = _LATEST / "sfd_prev_close_latest.csv"
SIGNAL_FILE      = _LATEST / "sfd_signal.csv"
STATUS_OUT       = _LATEST / "sfd_portfolio_status.csv"
ALERTS_OUT       = _LATEST / "sfd_alerts.json"

# 거미줄 NEAR 경고 임계 (트리거가 대비 %)
NEAR_THRESHOLD = 5.0


# ============================
# 유틸
# ============================
def load_portfolio() -> dict:
    if not PORTFOLIO_FILE.exists():
        print(f"[Layer5] ERROR: {PORTFOLIO_FILE} 없음")
        sys.exit(1)
    with open(PORTFOLIO_FILE, encoding="utf-8") as f:
        return json.load(f)


def load_close() -> dict:
    """ticker → 현재가 딕셔너리"""
    if not CLOSE_FILE.exists():
        print(f"[Layer5] WARN: {CLOSE_FILE} 없음 — 현재가 N/A")
        return {}
    df = pd.read_csv(CLOSE_FILE, dtype={"ticker": str})
    df["ticker"] = df["ticker"].str.zfill(6)
    close_candidates = ["close", "prev_close", "close_price", "종가"]
    close_col = next((c for c in close_candidates if c in df.columns), None)
    if close_col is None:
        print(f"[Layer5] WARN: 종가 컬럼 미발견 — {list(df.columns)}")
        return {}
    return dict(zip(df["ticker"], pd.to_numeric(df[close_col], errors="coerce")))


def load_sfd_signals() -> dict:
    """ticker → signal 딕셔너리"""
    if not SIGNAL_FILE.exists():
        print(f"[Layer5] WARN: {SIGNAL_FILE} 없음 — SFD 신호 N/A")
        return {}
    df = pd.read_csv(SIGNAL_FILE, dtype={"ticker": str})
    df["ticker"] = df["ticker"].str.zfill(6)
    return dict(zip(df["ticker"], df["signal"]))


def calc_avg_price(positions: list) -> float:
    """보유 포지션 평균 매입가 계산"""
    total_qty = sum(p["qty"] for p in positions)
    total_amt = sum(p["qty"] * p["price"] for p in positions)
    return round(total_amt / total_qty, 2) if total_qty > 0 else 0


def calc_return_pct(avg_price: float, current_price: float) -> float:
    if avg_price <= 0:
        return 0.0
    return round((current_price - avg_price) / avg_price * 100, 2)


def signal_rank(signal: str) -> int:
    """신호 등급 숫자화 (높을수록 강함)"""
    return {"RESERVE_BUY": 3, "WATCH_ONLY": 2, "HOLD": 1}.get(signal, 0)


# ============================
# 거미줄 단계 점검
# ============================
def check_web_strategy(holding: dict, current_price: float) -> list:
    alerts = []
    ws = holding.get("web_strategy", {})
    if not ws.get("enabled", False):
        return alerts

    ticker = holding["ticker"]
    name   = holding["name"]
    steps  = ws.get("steps_plan", [])

    for step in steps:
        if step["status"] in ("DONE", "SKIPPED"):
            continue

        trigger = step["trigger_price"]
        step_n  = step["step"]

        # 트리거 도달
        if current_price <= trigger:
            alerts.append({
                "level":   "🔴 WEB_TRIGGER",
                "ticker":  ticker,
                "name":    name,
                "step":    step_n,
                "message": f"{name} {step_n}차 추가매수 트리거 도달 "
                           f"(현재가 {current_price:,.0f} ≤ 트리거 {trigger:,.0f})",
                "action":  f"추가매수 {ws.get('step_qty', 1)}주 @ {current_price:,.0f}원"
            })
            step["status"] = "TRIGGERED"
            break  # 한 번에 1단계씩

        # NEAR 경고 (트리거 5% 이내)
        near_line = trigger * (1 + NEAR_THRESHOLD / 100)
        if current_price <= near_line:
            gap_pct = round((current_price - trigger) / trigger * 100, 1)
            alerts.append({
                "level":   "🟡 WEB_NEAR",
                "ticker":  ticker,
                "name":    name,
                "step":    step_n,
                "message": f"{name} {step_n}차 트리거 접근 중 "
                           f"(현재가 {current_price:,.0f} / 트리거 {trigger:,.0f} / 괴리 {gap_pct:+.1f}%)",
                "action":  "매수 준비"
            })
            step["status"] = "NEAR"
            break

        # 그 외 PENDING 유지
        step["status"] = "PENDING"
        break  # 첫 번째 미완료 단계만 확인

    # next_trigger_price 갱신
    next_pending = next(
        (s for s in steps if s["status"] not in ("DONE", "TRIGGERED", "SKIPPED")),
        None
    )
    if next_pending:
        ws["next_trigger_price"] = next_pending["trigger_price"]
        ws["current_step"] = next_pending["step"] - 1

    return alerts


# ============================
# SFD 신호 변화 점검
# ============================
def check_sfd_change(holding: dict, new_signal: str) -> list:
    alerts = []
    ticker      = holding["ticker"]
    name        = holding["name"]
    prev_signal = holding.get("sfd_signal", "HOLD")

    if new_signal and signal_rank(new_signal) > signal_rank(prev_signal):
        alerts.append({
            "level":   "🟢 SFD_UPGRADE",
            "ticker":  ticker,
            "name":    name,
            "step":    None,
            "message": f"{name} SFD 신호 상승: {prev_signal} → {new_signal}",
            "action":  "관심 강화 / 비중 확대 검토"
        })

    return alerts


# ============================
# catastrophic 점검
# ============================
def check_catastrophic(holding: dict) -> list:
    alerts = []
    if holding.get("stop_loss", {}).get("catastrophic_flag", False):
        alerts.append({
            "level":   "⚫ CATASTROPHIC",
            "ticker":  holding["ticker"],
            "name":    holding["name"],
            "step":    None,
            "message": f"{holding['name']} catastrophic_flag 활성화 — 즉시 손절 검토",
            "action":  "전량 매도 검토"
        })
    return alerts


# ============================
# 메인
# ============================
def main():
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"[Layer5] sfd_portfolio_monitor v1.0 시작 | {today}")

    portfolio   = load_portfolio()
    close_map   = load_close()
    signal_map  = load_sfd_signals()

    holdings    = portfolio.get("holdings", [])
    all_alerts  = []
    status_rows = []

    for h in holdings:
        ticker      = h["ticker"]
        name        = h["name"]
        positions   = h.get("positions", [])
        avg_price   = calc_avg_price(positions)
        current_px  = close_map.get(ticker)
        sfd_signal  = signal_map.get(ticker, h.get("sfd_signal", "HOLD"))

        # SFD 신호 업데이트
        h["sfd_signal"] = sfd_signal

        ret_pct = calc_return_pct(avg_price, current_px) if current_px else None

        # 알림 점검
        if current_px:
            all_alerts += check_web_strategy(h, current_px)
        all_alerts += check_sfd_change(h, sfd_signal)
        all_alerts += check_catastrophic(h)

        ws = h.get("web_strategy", {})
        status_rows.append({
            "as_of_date":        today,
            "ticker":            ticker,
            "name":              name,
            "sector":            h.get("sector", ""),
            "avg_price":         avg_price,
            "current_price":     current_px if current_px else "N/A",
            "return_pct":        f"{ret_pct:+.2f}%" if ret_pct is not None else "N/A",
            "sfd_signal":        sfd_signal,
            "web_step":          ws.get("current_step", 1),
            "next_trigger":      ws.get("next_trigger_price", "N/A"),
            "web_status":        ws.get("steps_plan", [{}])[0].get("status", "N/A")
                                 if ws.get("steps_plan") else "N/A",
        })

    # 신규 SFD 진입 (미보유 종목)
    held_tickers = {h["ticker"] for h in holdings}
    for ticker, signal in signal_map.items():
        if ticker not in held_tickers and signal in ("RESERVE_BUY", "WATCH_ONLY"):
            all_alerts.append({
                "level":   "🔵 SFD_NEW_ENTRY",
                "ticker":  ticker,
                "name":    ticker,
                "step":    None,
                "message": f"미보유 종목 SFD 진입: {ticker} → {signal}",
                "action":  "신규 매수 검토"
            })

    # 결과 저장
    df_status = pd.DataFrame(status_rows)
    df_status.to_csv(STATUS_OUT, index=False, encoding="utf-8-sig")

    alert_output = {
        "as_of_date": today,
        "total_alerts": len(all_alerts),
        "alerts": all_alerts
    }
    with open(ALERTS_OUT, "w", encoding="utf-8") as f:
        json.dump(alert_output, f, ensure_ascii=False, indent=2)

    # portfolio.json 업데이트 (status 반영)
    portfolio["_last_updated"] = today
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(portfolio, f, ensure_ascii=False, indent=2)

    # 콘솔 출력
    print(f"\n{'='*55}")
    print(f"[Layer5] 포트폴리오 현황 ({today})")
    print(f"{'='*55}")
    for row in status_rows:
        print(f"  {row['ticker']} {row['name']:10s} | "
              f"평단 {row['avg_price']:>10,.0f} | "
              f"수익률 {row['return_pct']:>8s} | "
              f"SFD: {row['sfd_signal']:12s} | "
              f"웹: {row['web_step']}단계/{row['next_trigger']}원")

    print(f"\n[Layer5] 알림 {len(all_alerts)}건")
    for a in all_alerts:
        print(f"  {a['level']} | {a['message']}")
        print(f"    → {a['action']}")

    print(f"\n  → {STATUS_OUT}")
    print(f"  → {ALERTS_OUT}")
    print(f"[Layer5] 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
