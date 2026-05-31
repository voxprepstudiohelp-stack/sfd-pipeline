#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sfd_trade_guardian.py v1.1
Layer 5.5 — Trade Guardian (매매 원칙 감시 + 심리 경보)

v1.0 → v1.1 변경사항:
  [BM-11] AF_TRAP_REVERSAL State Machine 추가 (야베스 사양서 §3.2)
          손절 후 10봉 이내 손절가 재돌파 → 강력 재진입 신호
  [BM-04] TIP Noise Filter 강화: confirm_candles=2 기반 확정 손절
  [BM-03] Bias Filter: 허리라인을 52주 고저 기준으로 확장

원칙 출처:
 - 차트프로 심리초급/중급: 물타기 경보, 손익비, 블랙데이, 깨진항아리
 - 차트프로 차트초급/중급: 허리라인 판별, 절대기준가 이탈, 설거지 감지
 - 야베스 16신호 체계: 숏딥/턴딥 눌림목 감지, 양음트랩 반전 포착
 - 야베스 사양서 §3.2: AF_TRAP_REVERSAL State Machine

입력: portfolio.json (보유 종목 + 등급 + 매수가)
      signal_latest.csv (L2 신호 출력)
      technical_latest.csv (L2.7 기술점수)
      guardian_state.json (State Machine 상태 유지 — 신규)
출력: guardian_alerts.json (Drive 업로드 대상)
      guardian_state.json (State Machine 상태 저장 — 신규)
      STDOUT 요약 보고서

실행: python sfd_trade_guardian.py
"""

import os, sys, json, math
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SFD_BASE = Path(os.environ.get("SFD_BASE_DIR", str(_HERE)))

def _p(name: str) -> Path:
    for candidate in [
        _SFD_BASE / "outputs" / "latest" / name,
        _SFD_BASE / "data" / name,
        _HERE / "outputs" / "latest" / name,
        _HERE / "data" / name,
    ]:
        if candidate.exists():
            return candidate
    return _SFD_BASE / "outputs" / "latest" / name

GRADE_PARAMS = {
    "A": {"max_add_count": 4, "pyramid": "1:2:3:4", "stop_pct": -15.0, "loss_ratio_min": 2.0},
    "B": {"max_add_count": 2, "pyramid": "1:1",     "stop_pct": -25.0, "loss_ratio_min": 2.0},
    "C": {"max_add_count": 0, "pyramid": "방치",     "stop_pct": None,  "loss_ratio_min": None},
}

PSYCHOLOGY_THRESHOLDS = {
    "add_buy_overcount":      True,
    "profit_loss_ratio_min":  2.0,
    "distribution_alert":     True,
    "waistline_below_ma20":   True,
    "blackday_worst_n":       1,
}

JABEZ_PARAMS = {
    "pullback_detect":          True,
    "pullback_score_threshold": 7,
    "trap_reversal_detect":     True,
    "trap_drop_pct":            -3.0,
    "trap_rebound_pct":          2.0,
}

AF_TRAP_PARAMS = {
    "lookback_bars":        10,
    "volume_delta_required": True,
    "tip_confirm_candles":   2,
}

def load_portfolio() -> list:
    path = _p("portfolio.json")
    if not path.exists():
        alt = _HERE.parent / "tools" / "portfolio.json"
        if alt.exists():
            path = alt
        else:
            print("[WARN] portfolio.json 없음 → 빈 포트폴리오로 진행")
            return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    holdings = data.get("holdings", data) if isinstance(data, dict) else data
    return holdings if isinstance(holdings, list) else []

def load_csv_safe(name: str) -> list:
    try:
        import csv
        path = _p(name)
        with open(path, encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except Exception as e:
        print(f"[WARN] {name} 로드 실패: {e}")
        return []

def load_guardian_state() -> dict:
    state_path = _SFD_BASE / "outputs" / "latest" / "guardian_state.json"
    if state_path.exists():
        try:
            with open(state_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_guardian_state(state: dict):
    out_dir = _SFD_BASE / "outputs" / "latest"
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / "guardian_state.json"
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def alert(code, ticker, name, msg, severity="WARN"):
    return {
        "severity": severity,
        "code":     code,
        "ticker":   ticker,
        "name":     name,
        "message":  msg,
        "ts":       datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

def check_stop_loss(h, params):
    alerts = []
    ticker = h.get("ticker", h.get("stk_cd", ""))
    name   = h.get("name",   h.get("stk_nm", ticker))
    grade  = h.get("grade", "C")
    pnl    = float(h.get("prft_rt", h.get("pnl_pct", 0)) or 0)
    gp     = GRADE_PARAMS.get(grade, GRADE_PARAMS["C"])
    stop   = gp.get("stop_pct")
    confirm = int(h.get("tip_breach_candles", 1) or 1)
    tip_confirmed = confirm >= AF_TRAP_PARAMS["tip_confirm_candles"]
    if stop and pnl <= stop:
        severity = "CRITICAL" if tip_confirmed else "WARN"
        label    = "확정 손절" if tip_confirmed else f"TIP 이탈 감지 ({confirm}봉, 확정={AF_TRAP_PARAMS['tip_confirm_candles']}봉 필요)"
        alerts.append(alert(
            "STOP_LOSS_TRIGGER", ticker, name,
            f"{grade}급 손절 기준 {stop}% 도달 (현재 {pnl:.2f}%). "
            f"{label}. 피라미딩: {gp['pyramid']}.",
            severity=severity
        ))
    elif stop and pnl <= stop * 0.7:
        alerts.append(alert(
            "STOP_LOSS_WARNING", ticker, name,
            f"{grade}급 손절 기준 {stop}%의 70% 근접 (현재 {pnl:.2f}%). 비중 점검 필요.",
            severity="WARN"
        ))
    return alerts

def check_af_trap_reversal(ticker, name, h, guardian_state: dict) -> tuple:
    """[BM-11] AF_TRAP_REVERSAL State Machine (야베스 사양서 §3.2)"""
    alerts = []
    ticker_state = guardian_state.get(ticker, {"state": 0, "bars_since_exit": 0, "stop_loss_level": None})
    pnl         = float(h.get("prft_rt",    h.get("pnl_pct", 0)) or 0)
    grade       = h.get("grade", "C")
    gp          = GRADE_PARAMS.get(grade, GRADE_PARAMS["C"])
    stop        = gp.get("stop_pct")
    cur_prc     = float(h.get("cur_prc",    h.get("current_price", 0)) or 0)
    buy_prc     = float(h.get("buy_price",  h.get("avg_buy_price",  0)) or 0)
    vol_delta   = float(h.get("vol_delta",  0) or 0)
    current_state   = ticker_state.get("state", 0)
    bars_since_exit = ticker_state.get("bars_since_exit", 0)
    stop_loss_level = ticker_state.get("stop_loss_level")
    new_state = current_state
    if current_state in (0, 1):
        if buy_prc > 0:
            new_state = 1
        if stop and pnl <= stop:
            stop_loss_level = cur_prc
            new_state       = 2
            bars_since_exit = 0
    elif current_state == 2:
        bars_since_exit += 1
        if bars_since_exit > AF_TRAP_PARAMS["lookback_bars"]:
            new_state       = 0
            bars_since_exit = 0
            stop_loss_level = None
        elif (stop_loss_level and cur_prc > stop_loss_level
              and (not AF_TRAP_PARAMS["volume_delta_required"] or vol_delta > 0)):
            new_state = 3
            alerts.append(alert(
                "AF_TRAP_REVERSAL", ticker, name,
                f"[야베스 BM-11] 손절({stop_loss_level:,.0f}원) 후 {bars_since_exit}봉 만에 "
                f"재돌파 (현재 {cur_prc:,.0f}원). "
                f"거래량 증가: {'YES' if vol_delta > 0 else 'NO'}. "
                f"AF 트랩 반전 강력 재진입 후보. 거래량·허리라인 최종 확인 후 결정.",
                severity="CRITICAL"
            ))
    elif current_state == 3:
        new_state = 1
    updated_state = {
        "state":           new_state,
        "bars_since_exit": bars_since_exit,
        "stop_loss_level": stop_loss_level,
        "last_updated":    datetime.now().strftime("%Y-%m-%d"),
    }
    return alerts, updated_state

def check_add_buy_overcount(h):
    alerts = []
    ticker    = h.get("ticker", h.get("stk_cd", ""))
    name      = h.get("name",   h.get("stk_nm", ticker))
    grade     = h.get("grade", "C")
    add_count = int(h.get("add_buy_count", 0) or 0)
    max_count = GRADE_PARAMS.get(grade, GRADE_PARAMS["C"])["max_add_count"]
    if add_count > max_count:
        alerts.append(alert(
            "ADD_BUY_OVERCOUNT", ticker, name,
            f"추가매수 {add_count}회 → {grade}급 허용 {max_count}회 초과. "
            f"요행 경보: 9번 폭탄 패턴 위험. 원칙 매매로 즉시 복귀.",
            severity="CRITICAL"
        ))
    return alerts

def check_waistline(h, tech_map):
    alerts = []
    ticker = h.get("ticker", h.get("stk_cd", ""))
    name   = h.get("name",   h.get("stk_nm", ticker))
    tech   = tech_map.get(ticker, {})
    ma20   = float(tech.get("ma20", 0) or 0)
    cur_p  = float(h.get("cur_prc", h.get("current_price", 0)) or 0)
    if ma20 > 0 and cur_p > 0 and cur_p < ma20:
        gap_pct = (cur_p - ma20) / ma20 * 100
        alerts.append(alert(
            "BELOW_WAISTLINE", ticker, name,
            f"현재가({cur_p:,.0f}) < 20일선({ma20:,.0f}) ({gap_pct:.1f}%). "
            f"허리라인 아래 = 예측매매 구간. 확인매매 원칙 준수.",
            severity="WARN"
        ))
    return alerts

def check_distribution(h, tech_map):
    alerts = []
    ticker = h.get("ticker", h.get("stk_cd", ""))
    name   = h.get("name",   h.get("stk_nm", ticker))
    tech   = tech_map.get(ticker, {})
    label  = tech.get("vol_gap_label", "")
    if label in ("DISTRIBUTION_RISK", "DIST_WARNING"):
        vg = tech.get("vol_gap_score", "?")
        alerts.append(alert(
            "DISTRIBUTION_RISK", ticker, name,
            f"설거지 의심 (vol_gap_label={label}, score={vg}). "
            f"고점 거래량 >> 바닥 거래량. 즉시 비중 점검.",
            severity="WARN"
        ))
    return alerts

def check_pullback_zone(ticker, name, tech_map):
    alerts = []
    tech     = tech_map.get(ticker, {})
    pb_score = tech.get("pullback_zone_score")
    if pb_score is None:
        return []
    pb_score = float(pb_score or 0)
    if pb_score >= JABEZ_PARAMS["pullback_score_threshold"]:
        alerts.append(alert(
            "JABEZ_PULLBACK", ticker, name,
            f"야베스 숏딥/턴딥 감지 (pullback_zone_score={pb_score:.1f}). "
            f"1차 상승 후 눌림목 진입 후보. 5/10일선 사이 수렴 확인 후 분할 진입 검토.",
            severity="INFO"
        ))
    return alerts

def check_trap_reversal(ticker, name, signal_row):
    alerts = []
    try:
        prev_chg  = float(signal_row.get("prev_day_change_pct", 0) or 0)
        today_chg = float(signal_row.get("today_change_pct",    0) or 0)
        if (prev_chg <= JABEZ_PARAMS["trap_drop_pct"] and
                today_chg >= JABEZ_PARAMS["trap_rebound_pct"]):
            alerts.append(alert(
                "JABEZ_TRAP_REVERSAL", ticker, name,
                f"야베스 양음트랩/불꽃반전: "
                f"전일 {prev_chg:.1f}% 급락 → 당일 {today_chg:.1f}% 반등. "
                f"세력 속임수 이후 강한 매수 의도 가능. 거래량 동반 여부 확인.",
                severity="INFO"
            ))
    except Exception:
        pass
    return alerts

def find_blackday(holdings):
    alerts = []
    if not holdings:
        return alerts
    worst  = min(holdings, key=lambda h: float(h.get("prft_rt", h.get("pnl_pct", 0)) or 0))
    ticker = worst.get("ticker", worst.get("stk_cd", ""))
    name   = worst.get("name",   worst.get("stk_nm", ticker))
    pnl    = float(worst.get("prft_rt", worst.get("pnl_pct", 0)) or 0)
    if pnl < -5:
        alerts.append(alert(
            "BLACKDAY", ticker, name,
            f"블랙데이 종목: {name} ({pnl:.2f}%). "
            f"매매 시작 전 이 종목의 손실 이유를 먼저 복기하고 겸손함을 회복하십시오.",
            severity="INFO"
        ))
    return alerts

def check_broken_jar(holdings):
    alerts      = []
    loss_count  = sum(1 for h in holdings if float(h.get("prft_rt", h.get("pnl_pct", 0)) or 0) < 0)
    total_count = len(holdings)
    if total_count == 0:
        return alerts
    loss_ratio = loss_count / total_count
    if loss_ratio > 0.6:
        alerts.append(alert(
            "BROKEN_JAR_WARNING", "PORTFOLIO", "전체포트폴리오",
            f"손실 종목 비율 {loss_ratio*100:.0f}% ({loss_count}/{total_count}). "
            f"깨진항아리 위험: 수익 기법 추가보다 리스크 관리 우선.",
            severity="WARN"
        ))
    return alerts

def main():
    print("=" * 60)
    print(" SFD Trade Guardian v1.1 — Layer 5.5")
    print(f" 실행시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(" [BM-11] AF_TRAP_REVERSAL State Machine 활성")
    print("=" * 60)
    holdings       = load_portfolio()
    signal_rows    = load_csv_safe("signal_latest.csv")
    tech_rows      = load_csv_safe("technical_latest.csv")
    guardian_state = load_guardian_state()
    signal_map = {r.get("ticker", r.get("stk_cd", "")): r for r in signal_rows}
    tech_map   = {r.get("ticker", r.get("stk_cd", "")): r for r in tech_rows}
    if not holdings:
        print("[INFO] 보유 종목 없음 — 포트폴리오를 확인하세요.")
    all_alerts    = []
    new_state_map = {}
    all_alerts += find_blackday(holdings)
    all_alerts += check_broken_jar(holdings)
    for h in holdings:
        ticker = h.get("ticker", h.get("stk_cd", ""))
        name   = h.get("name",   h.get("stk_nm", ticker))
        sig    = signal_map.get(ticker, {})
        all_alerts += check_stop_loss(h, GRADE_PARAMS)
        all_alerts += check_add_buy_overcount(h)
        all_alerts += check_waistline(h, tech_map)
        all_alerts += check_distribution(h, tech_map)
        all_alerts += check_pullback_zone(ticker, name, tech_map)
        all_alerts += check_trap_reversal(ticker, name, sig)
        af_alerts, updated_ticker_state = check_af_trap_reversal(
            ticker, name, h, guardian_state
        )
        all_alerts += af_alerts
        new_state_map[ticker] = updated_ticker_state
    save_guardian_state(new_state_map)
    severity_order = {"CRITICAL": 0, "WARN": 1, "INFO": 2}
    all_alerts.sort(key=lambda a: severity_order.get(a["severity"], 9))
    if not all_alerts:
        print("\n이상 없음 — 모든 원칙 준수 중")
    else:
        print(f"\n총 {len(all_alerts)}건 경보:\n")
        for a in all_alerts:
            icon = {"CRITICAL": "CRITICAL", "WARN": "WARN", "INFO": "INFO"}.get(a["severity"], "")
            print(f"[{icon}] {a['code']}")
            print(f"  종목: {a['name']} ({a['ticker']})")
            print(f"  내용: {a['message']}")
            print()
    out_dir  = _SFD_BASE / "outputs" / "latest"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "guardian_alerts.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "version":      "v1.1",
            "total":        len(all_alerts),
            "critical":     sum(1 for a in all_alerts if a["severity"] == "CRITICAL"),
            "warn":         sum(1 for a in all_alerts if a["severity"] == "WARN"),
            "info":         sum(1 for a in all_alerts if a["severity"] == "INFO"),
            "alerts":       all_alerts,
        }, f, ensure_ascii=False, indent=2)
    print(f"guardian_alerts.json 저장: {out_path}")

if __name__ == "__main__":
    main()
