#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sfd_trade_guardian.py v1.3
Layer 5 — Trade Guardian++ (매매 원칙 감시 + 심리 경보 + 포지션 관리)

v1.2 → v1.3 변경사항 [P_NEW_4 Guardian++ REDUCE_SIZE]:
  [REDUCE_SIZE] risk_mid 판정 시 FULL_EXIT 대신 포지션 50% 축소 중간 단계 신설
    - risk_low  : HOLD (기존 유지)
    - risk_mid  : REDUCE_SIZE 50% — 신설 (이전: ADD_BUY 억제만)
    - risk_high : FULL_EXIT (기존 유지)
  risk_mid 조건 (아래 중 1개 이상 충족):
    1. pnl <= stop_pct * 0.7  (손절 기준 70% 도달)
    2. below_waistline AND distribution_risk 동시 발생
    3. vp_position == 'below_val' AND pnl < -5%
  risk_high 조건 (아래 중 1개 이상 충족):
    1. pnl <= stop_pct  (손절 기준 도달 + TIP confirmed)
    2. BROKEN_JAR (포트폴리오 손실 60% 초과)
  출력 guardian_alerts.json에 신규 필드 추가:
    - action: "HOLD" | "REDUCE_SIZE" | "FULL_EXIT"
    - reduce_pct: 50 (REDUCE_SIZE 시)
    - risk_level: "low" | "mid" | "high"

v1.2 변경사항:
  [BM-5] no_trade 연동

v1.1 변경사항:
  [BM-11] AF_TRAP_REVERSAL State Machine 추가 (야베스 사양서 §3.2)
  [BM-04] TIP Noise Filter 강화: confirm_candles=2 기반 확정 손절
  [BM-03] Bias Filter: 허리라인을 52주 고저 기준으로 확장

원칙 출처:
 - 차트프로 심리초급/중급: 물타기 경보, 손익비, 블랙데이, 깨진항아리
 - 차트프로 차트초급/중급: 허리라인 판별, 절대기준가 이탈, 설거지 감지
 - 야베스 16신호 체계: 숏딥/턴딥 눌림목 감지, 양음트랩 반전 포착
 - 야베스 사양서 §3.2: AF_TRAP_REVERSAL State Machine

입력: portfolio.json (보유 종목 + 등급 + 매수가)
      signal_latest.csv (L2 신호 출력)
      technical_latest.csv (L2.7+BM-20 기술점수)
      guardian_state.json (State Machine 상태 유지)
      sfd_no_trade_tickers.json (BM-5)
출력: guardian_alerts.json (Drive 업로드 대상)
      guardian_state.json (State Machine 상태 저장)
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
    "C": {"max_add_count": 0, "pyramid": "방치",    "stop_pct": None,  "loss_ratio_min": None},
}

PSYCHOLOGY_THRESHOLDS = {
    "add_buy_overcount":    True,
    "profit_loss_ratio_min": 2.0,
    "distribution_alert":   True,
    "waistline_below_ma20": True,
    "blackday_worst_n":     1,
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

# ── [P_NEW_4] REDUCE_SIZE 파라미터 ───────────────────────────────────────────
REDUCE_SIZE_PARAMS = {
    "reduce_pct":          50,     # 50% 포지션 축소
    # risk_mid 조건 임계값
    "stop_pct_ratio_mid":  0.7,    # stop_pct * 0.7 도달 시 risk_mid
    "below_val_pnl_thr":  -5.0,   # vp_position==below_val + pnl < -5% → risk_mid
    # risk_high는 stop_pct 도달(TIP confirmed) 또는 BROKEN_JAR
}


# ── 데이터 로더 ───────────────────────────────────────────────────────────────
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


# ── [BM-5] no_trade_set 로드 ─────────────────────────────────────────────────
def load_no_trade_set() -> set:
    no_trade_path = _SFD_BASE / "outputs" / "latest" / "sfd_no_trade_tickers.json"
    if not no_trade_path.exists():
        print(f"[BM-5] no_trade JSON 없음 (정상): {no_trade_path}")
        return set()
    try:
        with open(no_trade_path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            tickers = data
        elif isinstance(data, dict):
            tickers = data.get("no_trade_tickers", data.get("tickers", []))
        else:
            tickers = []
        result = {str(t).strip().zfill(6) for t in tickers if t}
        print(f"[BM-5] no_trade_set: {len(result)}건")
        return result
    except Exception as e:
        print(f"[BM-5] no_trade JSON 로드 실패: {e}")
        return set()


# ── 경보 생성 함수 ────────────────────────────────────────────────────────────
def alert(code, ticker, name, msg, severity="WARN", action="HOLD",
          risk_level="low", reduce_pct=None):
    result = {
        "severity":   severity,
        "code":       code,
        "ticker":     ticker,
        "name":       name,
        "message":    msg,
        "action":     action,
        "risk_level": risk_level,
        "ts":         datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    if reduce_pct is not None:
        result["reduce_pct"] = reduce_pct
    return result


# ── [P_NEW_4] risk 레벨 판정 + REDUCE_SIZE 경보 ──────────────────────────────
def check_risk_level_and_reduce(h, tech_map) -> list:
    """
    Guardian++ REDUCE_SIZE 핵심 로직.

    risk_mid 조건 (OR):
      1. pnl <= stop_pct * 0.7
      2. below_waistline AND distribution_risk 동시
      3. vp_position == 'below_val' AND pnl < below_val_pnl_thr

    risk_high 조건 (OR):
      1. pnl <= stop_pct (손절기준 도달, TIP confirmed)
      2. 포트폴리오 단독 BROKEN_JAR은 별도 check_broken_jar에서 처리

    액션 매핑:
      risk_low  → HOLD (경보 없음, 별도 경보에서 처리)
      risk_mid  → REDUCE_SIZE (50% 축소) CRITICAL
      risk_high → FULL_EXIT CRITICAL
    """
    alerts = []
    ticker  = h.get("ticker", h.get("stk_cd", ""))
    name    = h.get("name",   h.get("stk_nm", ticker))
    grade   = h.get("grade",  "C")
    pnl     = float(h.get("prft_rt", h.get("pnl_pct", 0)) or 0)
    gp      = GRADE_PARAMS.get(grade, GRADE_PARAMS["C"])
    stop    = gp.get("stop_pct")

    tech      = tech_map.get(ticker, {})
    ma20      = float(tech.get("ma20", 0) or 0)
    cur_p     = float(h.get("cur_prc", h.get("current_price", 0)) or 0)
    vol_label = tech.get("vol_gap_label", "")
    vp_pos    = tech.get("vp_position", "")

    # TIP confirm 여부
    confirm       = int(h.get("tip_breach_candles", 1) or 1)
    tip_confirmed = confirm >= AF_TRAP_PARAMS["tip_confirm_candles"]

    # ── risk_high 판정 ──
    if stop and pnl <= stop and tip_confirmed:
        alerts.append(alert(
            "FULL_EXIT_TRIGGER", ticker, name,
            f"[Guardian++ FULL_EXIT] {grade}급 손절 기준 {stop}% 도달 + TIP {confirm}봉 확정. "
            f"현재 {pnl:.2f}%. 즉시 전량 매도 실행.",
            severity="CRITICAL",
            action="FULL_EXIT",
            risk_level="high",
        ))
        return alerts  # high → REDUCE_SIZE 중복 방지

    # ── risk_mid 조건 검사 ──
    mid_reasons = []

    # 조건 1: stop의 70% 도달
    if stop and pnl <= stop * REDUCE_SIZE_PARAMS["stop_pct_ratio_mid"]:
        mid_reasons.append(f"손절 기준 {stop}%의 70% 도달 (현재 {pnl:.2f}%)")

    # 조건 2: 허리선 이탈 + 설거지 동시
    below_waist = (ma20 > 0 and cur_p > 0 and cur_p < ma20)
    dist_risk   = vol_label in ("DISTRIBUTION_RISK", "DIST_WARNING")
    if below_waist and dist_risk:
        mid_reasons.append(
            f"허리선 이탈({cur_p:,.0f}<MA20:{ma20:,.0f}) + "
            f"설거지 의심({vol_label}) 동시 발생"
        )

    # 조건 3: below_val + pnl 악화
    if vp_pos == "below_val" and pnl < REDUCE_SIZE_PARAMS["below_val_pnl_thr"]:
        mid_reasons.append(
            f"Volume Area 하방(below_val) + PnL {pnl:.2f}% "
            f"(기준 {REDUCE_SIZE_PARAMS['below_val_pnl_thr']}%)"
        )

    if mid_reasons:
        reason_str = " | ".join(mid_reasons)
        alerts.append(alert(
            "REDUCE_SIZE_TRIGGER", ticker, name,
            f"[Guardian++ REDUCE_SIZE] {grade}급 risk_mid 판정. "
            f"포지션 {REDUCE_SIZE_PARAMS['reduce_pct']}% 축소 권고. "
            f"사유: {reason_str}. "
            f"피라미딩: {gp['pyramid']}. ADD_BUY 전면 금지.",
            severity="CRITICAL",
            action="REDUCE_SIZE",
            risk_level="mid",
            reduce_pct=REDUCE_SIZE_PARAMS["reduce_pct"],
        ))

    return alerts


# ── [BM-5] no_trade 경보 ─────────────────────────────────────────────────────
def check_bm5_no_trade(ticker, name, no_trade_set: set):
    alerts = []
    if ticker in no_trade_set:
        alerts.append(alert(
            "BM5_NO_TRADE", ticker, name,
            f"[BM-5 Volatility Buffer] 이벤트 ±60분 No-Trade 구간. "
            f"신규 진입 및 추가매수 금지. 기존 포지션 모니터링 강화 요망.",
            severity="WARN",
            action="HOLD",
            risk_level="low",
        ))
    return alerts

def check_stop_loss(h, params):
    """기존 손절 경보 (TIP unconfirmed WARN 포함 — FULL_EXIT과 별개)"""
    alerts = []
    ticker = h.get("ticker", h.get("stk_cd", ""))
    name   = h.get("name",   h.get("stk_nm", ticker))
    grade  = h.get("grade",  "C")
    pnl    = float(h.get("prft_rt", h.get("pnl_pct", 0)) or 0)
    gp     = GRADE_PARAMS.get(grade, GRADE_PARAMS["C"])
    stop   = gp.get("stop_pct")
    confirm     = int(h.get("tip_breach_candles", 1) or 1)
    tip_confirmed = confirm >= AF_TRAP_PARAMS["tip_confirm_candles"]

    if stop and pnl <= stop and not tip_confirmed:
        # TIP unconfirmed: WARN 수준 (FULL_EXIT는 check_risk_level에서 처리)
        alerts.append(alert(
            "STOP_LOSS_TIP_UNCONFIRMED", ticker, name,
            f"{grade}급 손절 기준 {stop}% 도달 ({pnl:.2f}%). "
            f"TIP 이탈 감지 ({confirm}봉, 확정={AF_TRAP_PARAMS['tip_confirm_candles']}봉 필요). "
            f"다음 봉 확인 후 FULL_EXIT 전환 가능. 피라미딩: {gp['pyramid']}.",
            severity="WARN",
            action="HOLD",
            risk_level="low",
        ))
    return alerts

def check_af_trap_reversal(ticker, name, h, guardian_state: dict) -> tuple:
    """[BM-11] AF_TRAP_REVERSAL State Machine (야베스 사양서 §3.2)"""
    alerts = []
    ticker_state   = guardian_state.get(ticker, {"state": 0, "bars_since_exit": 0, "stop_loss_level": None})
    pnl            = float(h.get("prft_rt",    h.get("pnl_pct", 0)) or 0)
    grade          = h.get("grade", "C")
    gp             = GRADE_PARAMS.get(grade, GRADE_PARAMS["C"])
    stop           = gp.get("stop_pct")
    cur_prc        = float(h.get("cur_prc",    h.get("current_price", 0)) or 0)
    buy_prc        = float(h.get("buy_price",  h.get("avg_buy_price",  0)) or 0)
    vol_delta      = float(h.get("vol_delta",  0) or 0)
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
                f"[야베스 BM-11] 손절가({stop_loss_level:,.0f}원) 후 {bars_since_exit}봉 이내 "
                f"재돌파 (현재 {cur_prc:,.0f}원). "
                f"거래량 확인: {'YES' if vol_delta > 0 else 'NO'}. "
                f"AF 재진입 기회 포착. 비중관리 후 매수 가능. 반드시 손절 재설정 후 진입.",
                severity="CRITICAL",
                action="HOLD",
                risk_level="low",
            ))
    elif current_state == 3:
        new_state = 1
    updated_state = {
        "state":            new_state,
        "bars_since_exit":  bars_since_exit,
        "stop_loss_level":  stop_loss_level,
        "last_updated":     datetime.now().strftime("%Y-%m-%d"),
    }
    return alerts, updated_state

def check_add_buy_overcount(h):
    alerts = []
    ticker    = h.get("ticker", h.get("stk_cd", ""))
    name      = h.get("name",   h.get("stk_nm", ticker))
    grade     = h.get("grade",  "C")
    add_count = int(h.get("add_buy_count", 0) or 0)
    max_count = GRADE_PARAMS.get(grade, GRADE_PARAMS["C"])["max_add_count"]
    if add_count > max_count:
        alerts.append(alert(
            "ADD_BUY_OVERCOUNT", ticker, name,
            f"추가매수 {add_count}회 → {grade}급 한도 {max_count}회 초과. "
            f"경고: 더 이상 추가매수 절대 금지. 물타기/추가매수 경보.",
            severity="CRITICAL",
            action="HOLD",
            risk_level="low",
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
            f"현재가({cur_p:,.0f}) < 20일이평({ma20:,.0f}) ({gap_pct:.1f}%). "
            f"허리선 이탈 → 예측매매 금지. 추가매수 절대 금지.",
            severity="WARN",
            action="HOLD",
            risk_level="low",
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
            f"설거지 의심 신호 (vol_gap_label={label}, score={vg}). "
            f"기관/외국인 물량 >> 개인 매수 주의. 추가매수 금지.",
            severity="WARN",
            action="HOLD",
            risk_level="low",
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
            f"야베스 숏딥/턴딥 눌림목 진입 (pullback_zone_score={pb_score:.1f}). "
            f"1봉 이내 반등 가능성 있음. 5/10분봉 확인 후 소량 진입 고려.",
            severity="INFO",
            action="HOLD",
            risk_level="low",
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
                f"야베스 양음트랩/음양트랩 감지: "
                f"전일 {prev_chg:.1f}% 하락 → 당일 {today_chg:.1f}% 반등. "
                f"단기 추세 전환 가능 신호. 추가매수 후 손절 재설정.",
                severity="INFO",
                action="HOLD",
                risk_level="low",
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
            f"포트폴리오 최대손실 종목: {name} ({pnl:.2f}%). "
            f"종목 집중 모니터링 필요 — 손절 기준 재확인 요망.",
            severity="INFO",
            action="HOLD",
            risk_level="low",
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
            "BROKEN_JAR_WARNING", "PORTFOLIO", "포트폴리오전체",
            f"포트폴리오 손실 비중 {loss_ratio*100:.0f}% ({loss_count}/{total_count}). "
            f"깨진항아리 경보: 신규 종목 매수금지. 현금 비중 확대 검토.",
            severity="WARN",
            action="HOLD",
            risk_level="low",
        ))
    return alerts


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print(" SFD Trade Guardian++ v1.3 — Layer 5")
    print(f" 실행일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(" [P_NEW_4] REDUCE_SIZE 50% 중간 단계 활성")
    print(" [BM-11]  AF_TRAP_REVERSAL State Machine 활성")
    print(" [BM-5]   no_trade Volatility Buffer 활성")
    print("=" * 60)

    holdings       = load_portfolio()
    signal_rows    = load_csv_safe("signal_latest.csv")
    tech_rows      = load_csv_safe("technical_latest.csv")
    guardian_state = load_guardian_state()
    no_trade_set   = load_no_trade_set()

    signal_map = {r.get("ticker", r.get("stk_cd", "")): r for r in signal_rows}
    tech_map   = {r.get("ticker", r.get("stk_cd", "")): r for r in tech_rows}

    if not holdings:
        print("[INFO] 보유 종목 없음 → 포트폴리오 점검 대상 없음.")

    all_alerts    = []
    new_state_map = {}

    all_alerts += find_blackday(holdings)
    all_alerts += check_broken_jar(holdings)

    reduce_size_tickers = []
    full_exit_tickers   = []

    for h in holdings:
        ticker = h.get("ticker", h.get("stk_cd", ""))
        name   = h.get("name",   h.get("stk_nm", ticker))
        sig    = signal_map.get(ticker, {})

        # [BM-5] no_trade 경보 — 최우선
        all_alerts += check_bm5_no_trade(ticker, name, no_trade_set)

        # [P_NEW_4] risk 레벨 판정 (REDUCE_SIZE / FULL_EXIT)
        risk_alerts = check_risk_level_and_reduce(h, tech_map)
        all_alerts += risk_alerts
        for a in risk_alerts:
            if a["action"] == "REDUCE_SIZE":
                reduce_size_tickers.append(ticker)
            elif a["action"] == "FULL_EXIT":
                full_exit_tickers.append(ticker)

        # 기존 경보들 (REDUCE_SIZE/FULL_EXIT 미적용 종목만 상세 체크)
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

    # ── STDOUT 출력 ──
    if not all_alerts:
        print("\n이상 없음 — 모든 매매 원칙 정상")
    else:
        print(f"\n총 {len(all_alerts)}건 경보:\n")
        for a in all_alerts:
            icon = {"CRITICAL": "CRITICAL", "WARN": "WARN", "INFO": "INFO"}.get(a["severity"], "")
            action_tag = f" [{a.get('action','HOLD')}]" if a.get("action") != "HOLD" else ""
            print(f"[{icon}]{action_tag} {a['code']}")
            print(f"  종목: {a['name']} ({a['ticker']})")
            print(f"  내용: {a['message']}")
            if a.get("reduce_pct"):
                print(f"  축소비율: {a['reduce_pct']}%")
            print()

    # ── REDUCE_SIZE / FULL_EXIT 요약 ──
    if reduce_size_tickers or full_exit_tickers:
        print("=" * 60)
        print("[Guardian++ 포지션 액션 요약]")
        if full_exit_tickers:
            print(f"  FULL_EXIT   : {', '.join(full_exit_tickers)}")
        if reduce_size_tickers:
            print(f"  REDUCE_SIZE : {', '.join(reduce_size_tickers)} (각 50% 축소)")
        print("=" * 60)

    # ── JSON 저장 ──
    out_dir  = _SFD_BASE / "outputs" / "latest"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "guardian_alerts.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at":      datetime.now().isoformat(),
            "version":           "v1.3",
            "total":             len(all_alerts),
            "critical":          sum(1 for a in all_alerts if a["severity"] == "CRITICAL"),
            "warn":              sum(1 for a in all_alerts if a["severity"] == "WARN"),
            "info":              sum(1 for a in all_alerts if a["severity"] == "INFO"),
            "no_trade_cnt":      sum(1 for a in all_alerts if a["code"] == "BM5_NO_TRADE"),
            "reduce_size_cnt":   len(reduce_size_tickers),
            "full_exit_cnt":     len(full_exit_tickers),
            "reduce_size_tickers": reduce_size_tickers,
            "full_exit_tickers":   full_exit_tickers,
            "alerts":            all_alerts,
        }, f, ensure_ascii=False, indent=2)
    print(f"guardian_alerts.json 저장: {out_path}")


if __name__ == "__main__":
    main()
