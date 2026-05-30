#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sfd_trade_guardian.py  v1.0
Layer 5.5  — Trade Guardian (매매 원칙 감시 + 심리 경보)

원칙 출처:
  - 차트프로 심리초급/중급: 물타기 경보, 손익비, 블랙데이, 깨진항아리
  - 차트프로 차트초급/중급: 허리라인 판별, 절대기준가 이탈, 설거지 감지
  - 야베스 16신호 체계: 숏딥/턴딥 눌림목 감지, 양음트랩 반전 포착

입력:  portfolio.json  (보유 종목 + 등급 + 매수가)
       signal_latest.csv  (L2 신호 출력)
       technical_latest.csv  (L2.7 기술점수)
출력:  guardian_alerts.json  (Drive 업로드 대상)
       STDOUT 요약 보고서

실행:  python sfd_trade_guardian.py
"""

import os, sys, json, math
from datetime import datetime
from pathlib import Path

# ── 경로 설정 (로컬: __file__ 기반, GitHub Actions: /tmp/sfd 기반) ──────────
_HERE = Path(__file__).resolve().parent
_SFD_BASE = Path(os.environ.get("SFD_BASE_DIR", str(_HERE)))

def _p(name: str) -> Path:
    """outputs/latest/ 또는 data/ 에서 파일 탐색"""
    for candidate in [
        _SFD_BASE / "outputs" / "latest" / name,
        _SFD_BASE / "data" / name,
        _HERE / "outputs" / "latest" / name,
        _HERE / "data" / name,
    ]:
        if candidate.exists():
            return candidate
    return _SFD_BASE / "outputs" / "latest" / name  # fallback (없으면 오류 발생)


# ══════════════════════════════════════════════════════════════════════════════
# 1. 등급별 파라미터 (종목등급 마스터와 연동)
# ══════════════════════════════════════════════════════════════════════════════
GRADE_PARAMS = {
    "A": {"max_add_count": 4,  "pyramid": "1:2:3:4", "stop_pct": -15.0, "loss_ratio_min": 2.0},
    "B": {"max_add_count": 2,  "pyramid": "1:1",     "stop_pct": -25.0, "loss_ratio_min": 2.0},
    "C": {"max_add_count": 0,  "pyramid": "방치",    "stop_pct": None,  "loss_ratio_min": None},
}

# ══════════════════════════════════════════════════════════════════════════════
# 2. 심리 경보 임계값 (차트프로 심리초급/중급 기반)
# ══════════════════════════════════════════════════════════════════════════════
PSYCHOLOGY_THRESHOLDS = {
    # 물타기: 등급별 최대 추가매수 횟수 초과 시 경보
    "add_buy_overcount": True,
    # 손익비: 목표가/손절가 비율 1:2 미만 시 경보
    "profit_loss_ratio_min": 2.0,
    # 설거지 의심: vol_gap_label == 'DISTRIBUTION_RISK' 시 경보
    "distribution_alert": True,
    # 허리라인: 현재가 < 20일 이평 → 예측매매 경고
    "waistline_below_ma20": True,
    # 포트폴리오 최대 손실 종목 블랙데이 표시
    "blackday_worst_n": 1,
}

# ══════════════════════════════════════════════════════════════════════════════
# 3. 야베스 패턴 감지 설정
# ══════════════════════════════════════════════════════════════════════════════
JABEZ_PARAMS = {
    # 숏딥/턴딥: pullback_zone (야베스 눌림목 감지)
    # technical_latest에 pullback_zone_score 있으면 활성화 (L2.7 v1.2 이후)
    "pullback_detect": True,
    "pullback_score_threshold": 7,   # pullback_zone_score >= 7 → 눌림목 진입 후보
    # 양음트랩: 전일 급락 후 당일 강반등 → 반전 신호
    "trap_reversal_detect": True,
    "trap_drop_pct": -3.0,           # 전일 -3% 이하 하락 → 트랩 조건
    "trap_rebound_pct":  2.0,        # 당일  +2% 이상 반등 → 반전 확인
}


# ══════════════════════════════════════════════════════════════════════════════
# 4. 데이터 로더
# ══════════════════════════════════════════════════════════════════════════════

def load_portfolio() -> list:
    """portfolio.json 로드"""
    path = _p("portfolio.json")
    if not path.exists():
        # 로컬 tools/ 폴더 탐색
        alt = _HERE.parent / "tools" / "portfolio.json"
        if alt.exists():
            path = alt
        else:
            print(f"[WARN] portfolio.json 없음 → 빈 포트폴리오로 진행")
            return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    holdings = data.get("holdings", data) if isinstance(data, dict) else data
    return holdings if isinstance(holdings, list) else []


def load_csv_safe(name: str) -> list:
    """CSV를 dict 리스트로 로드, 없으면 빈 리스트"""
    try:
        import csv
        path = _p(name)
        with open(path, encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except Exception as e:
        print(f"[WARN] {name} 로드 실패: {e}")
        return []


# ══════════════════════════════════════════════════════════════════════════════
# 5. 경보 생성 함수들
# ══════════════════════════════════════════════════════════════════════════════

def alert(code, ticker, name, msg, severity="WARN"):
    return {
        "severity": severity,     # INFO / WARN / CRITICAL
        "code": code,
        "ticker": ticker,
        "name": name,
        "message": msg,
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def check_stop_loss(h, params):
    """등급별 손절 트리거 초과 여부"""
    alerts = []
    ticker = h.get("ticker", h.get("stk_cd", ""))
    name   = h.get("name",   h.get("stk_nm",  ticker))
    grade  = h.get("grade",  "C")
    pnl    = float(h.get("prft_rt", h.get("pnl_pct", 0)) or 0)
    gp     = GRADE_PARAMS.get(grade, GRADE_PARAMS["C"])

    stop = gp.get("stop_pct")
    if stop and pnl <= stop:
        alerts.append(alert(
            "STOP_LOSS_TRIGGER", ticker, name,
            f"{grade}급 손절 기준 {stop}% 도달 (현재 {pnl:.2f}%). "
            f"피라미딩 방식: {gp['pyramid']}. 즉시 매매 원칙 재확인.",
            severity="CRITICAL"
        ))
    elif stop and pnl <= stop * 0.7:
        alerts.append(alert(
            "STOP_LOSS_WARNING", ticker, name,
            f"{grade}급 손절 기준 {stop}%의 70% 근접 (현재 {pnl:.2f}%). 비중 점검 필요.",
            severity="WARN"
        ))
    return alerts


def check_add_buy_overcount(h):
    """물타기 횟수 초과 — 차트프로 심리초급: 요행 경보"""
    alerts = []
    ticker    = h.get("ticker", h.get("stk_cd", ""))
    name      = h.get("name",   h.get("stk_nm",  ticker))
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
    """허리라인(20일선) 판별 — 차트프로 차트중급"""
    alerts = []
    ticker = h.get("ticker", h.get("stk_cd", ""))
    name   = h.get("name",   h.get("stk_nm",  ticker))
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
    """설거지 탐지 — 차트프로 차트초급 vol_gap_score"""
    alerts = []
    ticker = h.get("ticker", h.get("stk_cd", ""))
    name   = h.get("name",   h.get("stk_nm",  ticker))
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
    """야베스 숏딥/턴딥: pullback_zone_score 탐지 (L2.7 v1.2 이후)"""
    alerts = []
    tech = tech_map.get(ticker, {})
    pb_score = tech.get("pullback_zone_score")
    if pb_score is None:
        return []  # L2.7 v1.2 미배포 시 스킵

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
    """야베스 양음트랩/불꽃반전: 전일 급락 후 당일 급등"""
    alerts = []
    try:
        prev_chg  = float(signal_row.get("prev_day_change_pct", 0) or 0)
        today_chg = float(signal_row.get("today_change_pct", 0) or 0)
        if (prev_chg <= JABEZ_PARAMS["trap_drop_pct"] and
                today_chg >= JABEZ_PARAMS["trap_rebound_pct"]):
            alerts.append(alert(
                "JABEZ_TRAP_REVERSAL", ticker, name,
                f"야베스 양음트랩/불꽃반전 신호: "
                f"전일 {prev_chg:.1f}% 급락 → 당일 {today_chg:.1f}% 반등. "
                f"세력 속임수 이후 강한 매수 의도 가능. 거래량 동반 여부 확인.",
                severity="INFO"
            ))
    except Exception:
        pass
    return alerts


def find_blackday(holdings):
    """블랙데이: 최대 손실 종목 강조 — 차트프로 심리초급"""
    alerts = []
    if not holdings:
        return alerts
    worst = min(
        holdings,
        key=lambda h: float(h.get("prft_rt", h.get("pnl_pct", 0)) or 0)
    )
    ticker = worst.get("ticker", worst.get("stk_cd", ""))
    name   = worst.get("name", worst.get("stk_nm", ticker))
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
    """깨진항아리 이론: 손실 종목 비중 합계 경보"""
    alerts = []
    loss_count  = sum(1 for h in holdings
                      if float(h.get("prft_rt", h.get("pnl_pct", 0)) or 0) < 0)
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


# ══════════════════════════════════════════════════════════════════════════════
# 6. 메인 실행
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  SFD Trade Guardian v1.0  — Layer 5.5")
    print(f"  실행시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # ── 데이터 로드 ──────────────────────────────────────────────
    holdings    = load_portfolio()
    signal_rows = load_csv_safe("signal_latest.csv")
    tech_rows   = load_csv_safe("technical_latest.csv")

    # 인덱스 구성
    signal_map = {r.get("ticker", r.get("stk_cd", "")): r for r in signal_rows}
    tech_map   = {r.get("ticker", r.get("stk_cd", "")): r for r in tech_rows}

    if not holdings:
        print("[INFO] 보유 종목 없음 — 포트폴리오를 확인하세요.")

    all_alerts = []

    # ── 포트폴리오 수준 경보 ──────────────────────────────────────
    all_alerts += find_blackday(holdings)
    all_alerts += check_broken_jar(holdings)

    # ── 종목별 경보 ───────────────────────────────────────────────
    for h in holdings:
        ticker = h.get("ticker", h.get("stk_cd", ""))
        name   = h.get("name",   h.get("stk_nm",  ticker))
        sig    = signal_map.get(ticker, {})

        all_alerts += check_stop_loss(h, GRADE_PARAMS)
        all_alerts += check_add_buy_overcount(h)
        all_alerts += check_waistline(h, tech_map)
        all_alerts += check_distribution(h, tech_map)
        all_alerts += check_pullback_zone(ticker, name, tech_map)
        all_alerts += check_trap_reversal(ticker, name, sig)

    # ── 결과 출력 ─────────────────────────────────────────────────
    severity_order = {"CRITICAL": 0, "WARN": 1, "INFO": 2}
    all_alerts.sort(key=lambda a: severity_order.get(a["severity"], 9))

    if not all_alerts:
        print("\n이상 없음 — 모든 원칙 준수 중")
    else:
        print(f"\n총 {len(all_alerts)}건 경보:\n")
        for a in all_alerts:
            icon = {"CRITICAL": "CRITICAL", "WARN": "WARN", "INFO": "INFO"}.get(a["severity"], "")
            print(f"[{icon}] {a['code']}")
            print(f"   종목: {a['name']} ({a['ticker']})")
            print(f"   내용: {a['message']}")
            print()

    # ── JSON 저장 ─────────────────────────────────────────────────
    out_dir = _SFD_BASE / "outputs" / "latest"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "guardian_alerts.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "total": len(all_alerts),
            "critical": sum(1 for a in all_alerts if a["severity"] == "CRITICAL"),
            "warn":     sum(1 for a in all_alerts if a["severity"] == "WARN"),
            "info":     sum(1 for a in all_alerts if a["severity"] == "INFO"),
            "alerts": all_alerts,
        }, f, ensure_ascii=False, indent=2)
    print(f"guardian_alerts.json 저장: {out_path}")


if __name__ == "__main__":
    main()
