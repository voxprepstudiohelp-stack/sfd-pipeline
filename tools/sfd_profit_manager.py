# ============================================================
# 파일명: sfd_profit_manager.py
# 버전: v1.1
# 작성: Claude (Anthropic) — 2026.06.15
# 위치: tools/sfd_profit_manager.py
#
# [기능] 보유종목 분할 익절 + 트레일링 스탑 알림
#
# [익절 구간]
# 30% 도달 → 보유량 1/3 익절 권고 (원금 회수)
# 50% 도달 → 추가 25% 익절 권고
# 70% 도달 → 추가 25% 익절 권고
# 목표가 95% → 잔량 전량 익절 권고
#
# [트레일링 스탑]
# 고점(first_sell_price) 대비 -15% 이탈 → 긴급 경보
#
# [입력]
# sfd_account_execution_latest.csv
#
# [출력]
# sfd_profit_manager_latest.csv
# 이메일 알림 (sfd_notifier 연동)
# ============================================================

from __future__ import annotations

import os
import json
import logging
from pathlib import Path
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv

# ── 경로 설정 ─────────────────────────────────────────────
IS_GITHUB = os.getenv("GITHUB_ACTIONS") == "true"

if IS_GITHUB:
    OUTPUT_DIR = Path("/tmp/sfd/outputs/latest")
    ROOT       = Path(".")
else:
    ROOT       = Path(r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline")
    OUTPUT_DIR = ROOT / "outputs" / "latest"
    _ENV = ROOT / ".env"
    if _ENV.exists():
        load_dotenv(_ENV, override=True)

# ── 입력/출력 ──────────────────────────────────────────────
EXECUTION_CSV       = OUTPUT_DIR / "sfd_account_execution_latest.csv"
OUT_CSV             = OUTPUT_DIR / "sfd_profit_manager_latest.csv"
NOTIFIED_STATE_JSON = OUTPUT_DIR / "profit_manager_notified.json"
LOG_PATH            = ROOT / "logs" / "sfd_profit_manager.log"

# ── 익절 구간 파라미터 ────────────────────────────────────
PROFIT_STAGES = [
    {"pnl_pct": 0.30, "action": "1/3 익절 권고",    "urgency": "NORMAL", "qty_ratio": 1/3},
    {"pnl_pct": 0.50, "action": "추가 25% 익절 권고", "urgency": "NORMAL", "qty_ratio": 0.25},
    {"pnl_pct": 0.70, "action": "추가 25% 익절 권고", "urgency": "NORMAL", "qty_ratio": 0.25},
    {"pnl_pct": 0.95, "action": "목표가 근접 — 잔량 전량 익절 권고", "urgency": "HIGH", "qty_ratio": 1.0},
]

TRAILING_STOP_PCT = -0.15  # 고점 대비 -15% → 긴급 경보

LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    encoding="utf-8",
)


# ── Notifier 연동 ─────────────────────────────────────────
def _try_import_notifier():
    try:
        import sfd_notifier
        return sfd_notifier
    except ImportError:
        logging.info("[notifier] sfd_notifier not available — 알림 생략")
        return None


def load_notified_state() -> dict:
    if not NOTIFIED_STATE_JSON.exists():
        return {}
    try:
        with open(NOTIFIED_STATE_JSON, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_notified_state(state: dict) -> None:
    try:
        with open(NOTIFIED_STATE_JSON, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.warning(f"[notifier] notified_state 저장 실패: {e}")


def send_profit_alert(notifier, code: str, name: str, action: str,
                      pnl_rate: str, current_price: int) -> bool:
    subject = f"[SFD 익절 알림] {code} {name} — {action}"
    body    = (f"종목: {code} {name}\n수익률: {pnl_rate}\n"
               f"현재가: {current_price:,}원\n권고: {action}")
    try:
        if hasattr(notifier, "send_alert"):
            notifier.send_alert(subject=subject, body=body)
            return True
        if hasattr(notifier, "send_email"):
            notifier.send_email(subject=subject, body=body)
            return True
    except Exception as e:
        logging.warning(f"[notifier] send_profit_alert 실패: {e}")
    return False


def send_trailing_stop_alert(notifier, code: str, name: str,
                              drop_pct: str, current_price: int) -> bool:
    subject = f"[SFD 긴급경보] {code} {name} — 트레일링 스탑 발동"
    body    = (f"종목: {code} {name}\n고점 대비 하락: {drop_pct}\n"
               f"현재가: {current_price:,}원\n→ 긴급 매도 검토 요망")
    try:
        if hasattr(notifier, "send_alert"):
            notifier.send_alert(subject=subject, body=body, priority="CRITICAL")
            return True
        if hasattr(notifier, "send_email"):
            notifier.send_email(subject=subject, body=body)
            return True
    except Exception as e:
        logging.warning(f"[notifier] send_trailing_stop_alert 실패: {e}")
    return False


def _f(val, default=0.0) -> float:
    try:
        return float(str(val).replace(",", "").replace("원", "").replace("%", "").strip())
    except Exception:
        return default


def _pct(val) -> float:
    try:
        s = str(val).replace("%", "").strip()
        v = float(s)
        return v / 100.0 if abs(v) > 1.5 else v
    except Exception:
        return 0.0


def load_execution() -> pd.DataFrame:
    if not EXECUTION_CSV.exists():
        print(f"[WARN] execution CSV 없음: {EXECUTION_CSV}")
        return pd.DataFrame()
    return pd.read_csv(EXECUTION_CSV, dtype=str, encoding="utf-8-sig")


def evaluate_profit(exec_df: pd.DataFrame) -> pd.DataFrame:
    results = []

    for _, row in exec_df.iterrows():
        code  = str(row.get("stock_code", "")).strip()
        name  = str(row.get("corp_name",  "")).strip()

        current_price  = _f(row.get("current_price", 0))
        avg_price      = _f(row.get("avg_price",     0))
        hold_qty       = int(_f(row.get("hold_qty", row.get("quantity", 1))))
        high_proxy     = _f(row.get("first_sell_price",  0))  # 1차 익절가 = 단기 고점 프록시
        target_proxy   = _f(row.get("second_sell_price", 0))  # 2차 익절가 = 목표가 프록시

        if current_price <= 0 or avg_price <= 0:
            continue

        # 현재 수익률
        pnl_rate = (current_price - avg_price) / avg_price

        # ── 트레일링 스탑 체크 (최우선)
        trailing_alert = None
        if high_proxy > 0:
            drop_from_high = (current_price - high_proxy) / high_proxy
            if drop_from_high <= TRAILING_STOP_PCT:
                trailing_alert = {
                    "stock_code":    code,
                    "corp_name":     name,
                    "signal_type":   "TRAILING_STOP",
                    "urgency":       "CRITICAL",
                    "action":        f"고점 대비 {drop_from_high*100:.1f}% 이탈 — 긴급 매도 검토",
                    "current_price": int(current_price),
                    "avg_price":     int(avg_price),
                    "pnl_rate":      f"{pnl_rate*100:+.2f}%",
                    "high_proxy":    int(high_proxy),
                    "drop_from_high": f"{drop_from_high*100:.1f}%",
                    "target_proxy":  int(target_proxy) if target_proxy > 0 else None,
                    "hold_qty":      hold_qty,
                    "suggest_qty":   hold_qty,  # 전량 매도 검토
                    "evaluated_at":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                results.append(trailing_alert)
                continue  # 트레일링 스탑 발동 시 익절 체크 스킵

        # ── 목표가 기준 수익률 계산 (target_proxy 있을 때)
        target_pnl = (target_proxy - avg_price) / avg_price if target_proxy > avg_price > 0 else None

        # ── 분할 익절 구간 체크
        triggered_stage = None
        for stage in reversed(PROFIT_STAGES):  # 높은 구간부터 체크
            # 목표가 기준 달성률로 판단 (target_proxy 있을 때)
            if target_pnl and target_pnl > 0:
                progress = pnl_rate / target_pnl
                if progress >= stage["pnl_pct"]:
                    triggered_stage = stage
                    break
            else:
                # 단순 수익률 기준
                if pnl_rate >= stage["pnl_pct"]:
                    triggered_stage = stage
                    break

        if triggered_stage:
            suggest_qty = max(1, int(hold_qty * triggered_stage["qty_ratio"]))
            suggest_price = int(current_price * 0.997)  # 시장가 근사 (지정가 -0.3%)

            results.append({
                "stock_code":    code,
                "corp_name":     name,
                "signal_type":   "TAKE_PROFIT",
                "urgency":       triggered_stage["urgency"],
                "action":        triggered_stage["action"],
                "current_price": int(current_price),
                "avg_price":     int(avg_price),
                "pnl_rate":      f"{pnl_rate*100:+.2f}%",
                "high_proxy":    int(high_proxy) if high_proxy > 0 else None,
                "drop_from_high": None,
                "target_proxy":  int(target_proxy) if target_proxy > 0 else None,
                "hold_qty":      hold_qty,
                "suggest_qty":   suggest_qty,
                "suggest_price": suggest_price,
                "evaluated_at":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })

    return pd.DataFrame(results)


def main() -> None:
    print(f"[INFO] sfd_profit_manager v1.1 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[INFO] 분할 익절 + 트레일링 스탑 평가 시작")

    notifier       = _try_import_notifier()
    notified_state = load_notified_state()

    exec_df = load_execution()
    if exec_df.empty:
        print("[WARN] execution 데이터 없음 — 종료")
        return

    print(f"[INFO] 보유 종목: {len(exec_df)}개 평가 중...")
    result_df = evaluate_profit(exec_df)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    result_df.to_csv(str(OUT_CSV), index=False, encoding="utf-8-sig")

    if result_df.empty:
        print("[DONE] 익절/트레일링 스탑 대상 없음")
    else:
        critical = result_df[result_df["urgency"] == "CRITICAL"]
        high     = result_df[result_df["urgency"] == "HIGH"]
        normal   = result_df[result_df["urgency"] == "NORMAL"]

        print(f"\n[DONE] 익절/경보 신호: {len(result_df)}종목")
        print("-" * 60)

        today = datetime.now().strftime("%Y-%m-%d")

        for _, r in result_df.iterrows():
            icon = "🚨" if r["urgency"] == "CRITICAL" else ("⚠️" if r["urgency"] == "HIGH" else "💰")
            print(f"  {icon} [{r['urgency']}] {r['stock_code']} {r['corp_name']}")
            print(f"     현재가={r['current_price']:,}원 | 수익률={r['pnl_rate']} | {r['action']}")
            if r.get("suggest_qty"):
                print(f"     권고: {r['suggest_qty']}주 매도")
            print()

            # 중복 방지: (종목+action+날짜) 키로 오늘 이미 발송한 건 skip
            notif_key = f"{today}|{r['stock_code']}|{r['signal_type']}|{r['action']}"
            if notifier and not notified_state.get(notif_key):
                if r["signal_type"] == "TRAILING_STOP":
                    ok = send_trailing_stop_alert(
                        notifier,
                        code=str(r["stock_code"]),
                        name=str(r["corp_name"]),
                        drop_pct=str(r.get("drop_from_high", "")),
                        current_price=int(r["current_price"]),
                    )
                else:
                    ok = send_profit_alert(
                        notifier,
                        code=str(r["stock_code"]),
                        name=str(r["corp_name"]),
                        action=str(r["action"]),
                        pnl_rate=str(r["pnl_rate"]),
                        current_price=int(r["current_price"]),
                    )
                if ok:
                    notified_state[notif_key] = True
                    logging.info(f"[notifier] 알림 발송: {notif_key}")

        if not critical.empty:
            logging.warning(f"TRAILING_STOP {len(critical)}건: {list(critical['stock_code'])}")
        logging.info(f"v1.1 완료: CRITICAL={len(critical)}, HIGH={len(high)}, NORMAL={len(normal)}")

    save_notified_state(notified_state)
    print(f"[OUT] {OUT_CSV}")


if __name__ == "__main__":
    main()
