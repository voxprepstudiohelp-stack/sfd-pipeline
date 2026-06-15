# ============================================================
# 파일명: sfd_add_buy_v2.py
# 버전: v1.0
# 작성: Claude (Anthropic) — 2026.06.15
# 위치: tools/sfd_add_buy_v2.py
#
# [기능] 조정 매집 신호 (ADD_BUY v2)
# 수익이 난 종목이 조정 구간 진입 시 → 저가 매집 기회 감지
#
# [전략 원칙]
# - 수익 실현 후 재조정 시 보유량 확대 (거미줄 역방향 매집)
# - 목표가 여정 중간 (달성률 < 50%) + 조정 폭 −20% 이상
# - 섹터/매크로 유효성 재확인 후 1주 매집
# - 물타기와 구분: 목표가 근거 유효 + 현금 여력 확보 전제
#
# [트리거 조건 AND]
# ① 고점 대비 −20% 이상 하락 (조정 구간)
# ② 목표가 달성률 < 50% (아직 여정 중간)
# ③ decay_flag != STALE (시그널 유효)
# ④ macro_score >= 0 (시장 우호적)
# ⑤ pnl_rate > -5% (과도한 손실 종목 제외 — 물타기 방지)
# ⑥ risk_level != WATCH_NO_ADD (명시적 매집 금지 제외)
#
# [출력]
# sfd_add_buy_v2_signal_latest.csv
# 이메일/노션 알림 연동 가능 (sfd_notifier 호출)
# ============================================================

from __future__ import annotations

import os
import logging
from pathlib import Path
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv

# ── 경로 설정 ─────────────────────────────────────────────────────────
IS_GITHUB = os.getenv("GITHUB_ACTIONS") == "true"

if IS_GITHUB:
    OUTPUT_DIR = Path("outputs/latest")
    INPUT_DIR  = Path("inputs")
    ROOT       = Path(".")
else:
    ROOT       = Path(r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline")
    OUTPUT_DIR = ROOT / r"outputs\latest"
    INPUT_DIR  = ROOT / r"inputs"
    _ENV = ROOT / ".env"
    if _ENV.exists():
        load_dotenv(_ENV, override=True)

# ── 입력 파일 ──────────────────────────────────────────────────────────
EXECUTION_CSV = OUTPUT_DIR / "sfd_account_execution_latest.csv"
SIGNAL_CSV    = OUTPUT_DIR / "sfd_master_signal_latest.csv"

# ── 출력 파일 ──────────────────────────────────────────────────────────
OUT_CSV  = OUTPUT_DIR / "sfd_add_buy_v2_signal_latest.csv"
LOG_PATH = ROOT / "logs" / "sfd_add_buy_v2.log"

# ── 파라미터 ──────────────────────────────────────────────────────────
DROP_THRESHOLD   = -0.20   # 고점 대비 −20% = 조정 매집 진입
TARGET_PROG_MAX  = 0.50    # 목표가 달성률 50% 미만만 매집 대상
MIN_PNL_RATE     = -0.05   # pnl −5% 이상 (과손실 물타기 방지)
MACRO_MIN        = 0.0     # macro_score 최소값
CASH_RESERVE_MIN = 0.30    # 전체 자산 대비 현금 30% 이상 유지 기준

LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    encoding="utf-8",
)


def _parse_krw(val) -> float:
    """'209,116원' 또는 숫자 → float"""
    try:
        return float(str(val).replace(",", "").replace("원", "").replace("%", "").strip())
    except Exception:
        return 0.0


def _parse_pct(val) -> float:
    """'4.73%' 또는 숫자 → float (−1~+1 범위)"""
    try:
        s = str(val).replace("%", "").strip()
        return float(s) / 100.0
    except Exception:
        return 0.0


def load_execution() -> pd.DataFrame:
    """보유 종목 execution 테이블 로드"""
    if not EXECUTION_CSV.exists():
        print(f"[WARN] execution CSV 없음: {EXECUTION_CSV}")
        return pd.DataFrame()
    df = pd.read_csv(EXECUTION_CSV, dtype=str, encoding="utf-8-sig")
    return df


def load_signal() -> pd.DataFrame:
    """마스터 시그널 로드 (decay_flag, macro_score 참조)"""
    if not SIGNAL_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(SIGNAL_CSV, dtype=str)
    if "ticker" in df.columns and "stock_code" not in df.columns:
        df = df.rename(columns={"ticker": "stock_code"})
    return df


def evaluate_add_buy(exec_df: pd.DataFrame, signal_df: pd.DataFrame) -> pd.DataFrame:
    """
    ADD_BUY v2 조정 매집 신호 평가

    핵심 로직:
    1. 고점 = first_sell_price (1차 익절 목표가를 고점 프록시로 사용)
       → 더 정확한 고점은 별도 price_history 구축 필요 (v2.0 예정)
    2. 현재가가 고점 대비 DROP_THRESHOLD 이하 → 매집 진입
    3. 목표가 달성률 = current_price / target_price
       → target_price = second_sell_price (2차 익절가 = 중간 목표)
    """
    results = []

    for _, row in exec_df.iterrows():
        code      = str(row.get("stock_code", "")).strip()
        name      = str(row.get("corp_name", "")).strip()
        risk      = str(row.get("risk_level", "")).strip()
        ex_signal = str(row.get("execution_signal", "")).strip()

        # ── 조건 ⑥: 명시적 매집 금지 제외
        if "NO_ADD" in ex_signal or "NO_ADD" in risk:
            continue

        current_price  = _parse_krw(row.get("current_price", 0))
        avg_price      = _parse_krw(row.get("avg_price", 0))
        pnl_rate       = _parse_pct(row.get("pnl_rate", 0))

        # first_sell_price = 1차 익절가 → 단기 고점 프록시
        high_proxy     = _parse_krw(row.get("first_sell_price", 0))
        # second_sell_price = 2차 익절가 → 목표가 프록시
        target_proxy   = _parse_krw(row.get("second_sell_price", 0))

        if current_price <= 0 or high_proxy <= 0 or target_proxy <= 0:
            continue

        # ── 조건 ①: 고점 대비 하락률
        drop_from_high = (current_price - high_proxy) / high_proxy
        if drop_from_high > DROP_THRESHOLD:
            # 아직 충분히 안 빠짐
            continue

        # ── 조건 ②: 목표가 달성률
        target_progress = (current_price - avg_price) / (target_proxy - avg_price) if (target_proxy - avg_price) > 0 else 1.0
        if target_progress >= TARGET_PROG_MAX:
            # 목표가 절반 이상 달성 → 매집보다 익절 관리 구간
            continue

        # ── 조건 ⑤: 과손실 물타기 방지
        if pnl_rate < MIN_PNL_RATE:
            continue

        # ── 시그널 CSV에서 decay_flag, macro_score 조회
        decay_flag  = "UNKNOWN"
        macro_score = 0.0
        if not signal_df.empty and "stock_code" in signal_df.columns:
            match = signal_df[signal_df["stock_code"] == code]
            if not match.empty:
                decay_flag  = str(match.iloc[0].get("decay_flag", "FRESH"))
                try:
                    macro_score = float(match.iloc[0].get("macro_score", 0) or 0)
                except Exception:
                    macro_score = 0.0

        # ── 조건 ③: decay 유효
        if decay_flag == "STALE":
            continue

        # ── 조건 ④: 매크로 우호
        if macro_score < MACRO_MIN:
            continue

        # ── 매집 권고가 = 현재가 기준 (시장가 매집)
        add_buy_price = current_price
        reason_parts  = []

        if drop_from_high <= -0.30:
            urgency = "HIGH"
            reason_parts.append(f"고점 대비 {drop_from_high*100:.1f}% 급조정")
        else:
            urgency = "NORMAL"
            reason_parts.append(f"고점 대비 {drop_from_high*100:.1f}% 조정")

        reason_parts.append(f"목표가 진행률 {target_progress*100:.0f}%")
        reason_parts.append(f"평단 {avg_price:,.0f}원 → 매집 시 평단 희석")

        results.append({
            "stock_code":       code,
            "corp_name":        name,
            "current_price":    int(current_price),
            "avg_price":        int(avg_price),
            "pnl_rate":         f"{pnl_rate*100:+.2f}%",
            "high_proxy":       int(high_proxy),
            "drop_from_high":   f"{drop_from_high*100:.1f}%",
            "target_proxy":     int(target_proxy),
            "target_progress":  f"{target_progress*100:.0f}%",
            "add_buy_price":    int(add_buy_price),
            "add_buy_qty":      1,  # 자본여력 보수 전략: 1주 고정
            "urgency":          urgency,
            "decay_flag":       decay_flag,
            "macro_score":      macro_score,
            "signal":           "ADD_BUY_v2",
            "reason":           " | ".join(reason_parts),
            "evaluated_at":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

    return pd.DataFrame(results)


def main() -> None:
    print(f"[INFO] sfd_add_buy_v2 v1.0 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[INFO] 조정 매집 신호 평가 시작")

    exec_df   = load_execution()
    signal_df = load_signal()

    if exec_df.empty:
        print("[WARN] execution 데이터 없음 — 종료")
        return

    print(f"[INFO] 보유 종목: {len(exec_df)}개 평가 중...")

    result_df = evaluate_add_buy(exec_df, signal_df)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    result_df.to_csv(str(OUT_CSV), index=False, encoding="utf-8-sig")

    if result_df.empty:
        print("[DONE] 조정 매집 대상 없음 (모든 종목 조건 미충족)")
    else:
        print(f"\n[DONE] ADD_BUY v2 신호: {len(result_df)}종목")
        print("-" * 60)
        for _, r in result_df.iterrows():
            print(f"  [{r['urgency']}] {r['stock_code']} {r['corp_name']}")
            print(f"         현재가={r['current_price']:,}원 | 고점대비={r['drop_from_high']} | "
                  f"목표진행={r['target_progress']}")
            print(f"         매집권고: {r['add_buy_price']:,}원 × 1주")
            print(f"         사유: {r['reason']}")
            print()
        print(f"[OUT] {OUT_CSV}")

    logging.info(f"v1.0 완료: {len(result_df)}종목 ADD_BUY_v2 신호")


if __name__ == "__main__":
    main()
