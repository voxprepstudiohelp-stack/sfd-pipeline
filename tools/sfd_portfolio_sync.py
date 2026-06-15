# sfd_portfolio_sync.py v1.3
# 변경: 종목 등급제 (A/B/C) + 등급별 trigger_pct / max_steps / step_qty_ratio 차등 적용
# 키움 REST API ka01690 → 실잔고 → portfolio.json 자동 생성

import os
import json
import requests
from datetime import datetime
from dotenv import load_dotenv

# ── 환경변수 로드 ──────────────────────────────────────────
BASE_DIR = os.environ.get(
    "SFD_BASE_DIR",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
load_dotenv(os.path.join(BASE_DIR, ".env"))

APP_KEY    = os.getenv("KIWOOM_APP_KEY", "")
SECRET_KEY = os.getenv("KIWOOM_SECRET_KEY", "")
ACCOUNT_NO = os.getenv("KIWOOM_ACCOUNT_NO", "").replace("-", "")
ENV        = os.getenv("KIWOOM_ENV", "real")
BASE_URL   = "https://api.kiwoom.com"
OUTPUT_PATH = os.path.join(BASE_DIR, "portfolio.json")

# ══════════════════════════════════════════════════════════
# 종목 등급 마스터 (수동 관리)
#
# A급: 중장기 상승 모멘텀 확실 → -15% 트리거, 피라미딩 1:2:3:4
# B급: 모멘텀 불확실/소액     → -25% 트리거, 균등 소액 1:1
# C급: 거미줄 비활성화        → 트리거 없음, 방치
# ══════════════════════════════════════════════════════════
GRADE_MASTER = {
    "006260": {  # LS
        "grade": "A",
        "reason": "전선/전력 중장기 테마, DB증권 목표가 60만원",
        "trigger_pct": -15.0,
        "max_steps": 4,
        "step_qty_ratio": [1, 2, 3, 4],
        "alert_price": 380000,
        "alert_memo": "LS 38만원 추가매수 대기",
    },
    "034020": {  # 두산에너빌리티
        "grade": "A",
        "reason": "원전 중장기 모멘텀",
        "trigger_pct": -15.0,
        "max_steps": 4,
        "step_qty_ratio": [1, 2, 3, 4],
    },
    "052690": {  # 한전기술
        "grade": "A",
        "reason": "원전 설계 독점",
        "trigger_pct": -15.0,
        "max_steps": 4,
        "step_qty_ratio": [1, 2, 3, 4],
    },
    "001440": {  # 대한전선
        "grade": "B",
        "reason": "전선 테마이나 모멘텀 확인 필요",
        "trigger_pct": -25.0,
        "max_steps": 2,
        "step_qty_ratio": [1, 1],
    },
    "171120": {  # 라이온켐텍
        "grade": "B",
        "reason": "소액 보유, 모멘텀 불확실 → 방치 우선, -25% 시 소액 평단 낮추기",
        "trigger_pct": -25.0,
        "max_steps": 2,
        "step_qty_ratio": [1, 1],
    },
    "005930": {  # 삼성전자
        "grade": "C",
        "reason": "지수 추종, 거미줄 불필요",
        "trigger_pct": None,
        "max_steps": 0,
        "step_qty_ratio": [],
    },
}

GRADE_DEFAULTS = {
    "A": {"trigger_pct": -15.0, "max_steps": 4, "step_qty_ratio": [1, 2, 3, 4]},
    "B": {"trigger_pct": -25.0, "max_steps": 2, "step_qty_ratio": [1, 1]},
    "C": {"trigger_pct": None,  "max_steps": 0, "step_qty_ratio": []},
}
DEFAULT_GRADE = "B"

# ── 토큰 발급 ──────────────────────────────────────────────
def get_access_token():
    resp = requests.post(
        f"{BASE_URL}/oauth2/token",
        headers={"Content-Type": "application/json;charset=UTF-8"},
        json={"grant_type": "client_credentials", "appkey": APP_KEY, "secretkey": SECRET_KEY},
        timeout=10
    )
    token = resp.json().get("token")
    print(f"[OK] Token issued OK" if token else f"[ERROR] Token issue FAIL")
    return token

# ── ka01690 잔고 조회 ──────────────────────────────────────
def get_balance_ka01690(token):
    today = datetime.now().strftime("%Y%m%d")
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "secretkey": SECRET_KEY,
        "api-id": "ka01690",
    }
    resp = requests.post(f"{BASE_URL}/api/dostk/acnt",
                         headers=headers, json={"qry_dt": today}, timeout=10)
    result = resp.json()
    if "day_bal_rt" in result:
        print(f"[OK] Balance query OK")
        return result
    print(f"[ERROR] Balance query FAIL: {str(result)[:100]}")
    return None

# ── 파싱 ──────────────────────────────────────────────────
def parse_holdings(raw):
    holdings = []
    for item in raw.get("day_bal_rt", []):
        ticker = item.get("stk_cd", "").strip().zfill(6)
        qty    = int(item.get("rmnd_qty", 0) or 0)
        if qty <= 0:
            continue
        holdings.append({
            "ticker":        ticker,
            "name":          item.get("stk_nm", "N/A").strip(),
            "qty":           qty,
            "avg_price":     float(item.get("buy_uv", 0) or 0),
            "current_price": float(str(item.get("cur_prc", "0")).replace("+","").replace("-","") or 0),
            "prft_rt":       float(item.get("prft_rt", 0) or 0),
        })
    print(f"[OK] Holdings parsed: {len(holdings)} tickers")
    return holdings

# ── portfolio.json 생성 (등급 적용) ───────────────────────
def build_portfolio_json(holdings):
    portfolio = {
        "_meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "kiwoom_rest_api_ka01690",
            "account_no": ACCOUNT_NO,
            "env": ENV,
            "version": "1.3",
            "grade_legend": {
                "A": "핵심 중장기 | -15% 트리거 | 피라미딩 1:2:3:4",
                "B": "소액/불확실 | -25% 트리거 | 균등 소액 1:1",
                "C": "거미줄 비활성 | 방치",
            }
        },
        "holdings": []
    }

    for h in holdings:
        ticker    = h["ticker"]
        avg_price = h["avg_price"]
        gm        = GRADE_MASTER.get(ticker, {})
        grade     = gm.get("grade", DEFAULT_GRADE)
        gd        = GRADE_DEFAULTS[grade]

        trigger_pct    = gm.get("trigger_pct",     gd["trigger_pct"])
        max_steps      = gm.get("max_steps",        gd["max_steps"])
        step_qty_ratio = gm.get("step_qty_ratio",   gd["step_qty_ratio"])

        trigger_price = round(avg_price * (1 + trigger_pct / 100)) \
                        if trigger_pct is not None and avg_price > 0 else None

        entry = {
            "ticker":          ticker,
            "name":            h["name"],
            "qty":             h["qty"],
            "avg_price":       avg_price,
            "current_price":   h["current_price"],
            "prft_rt":         h["prft_rt"],
            "grade":           grade,
            "reason":          gm.get("reason", "신규 종목 - 등급 미분류"),
            "trigger_pct":     trigger_pct,
            "trigger_price":   trigger_price,
            "current_step":    1,
            "max_steps":       max_steps,
            "step_qty_ratio":  step_qty_ratio,
            "catastrophic_only": True,
            "active":          grade != "C",
        }

        if "alert_price" in gm:
            entry["alert_price"] = gm["alert_price"]
            entry["alert_memo"]  = gm.get("alert_memo", "")

        portfolio["holdings"].append(entry)

    return portfolio

# ── fallback ───────────────────────────────────────────────
def manual_fallback():
    print("[FALLBACK] Using manual balance")
    return [
        {"ticker": "006260", "name": "LS",           "qty": 3,  "avg_price": 538667, "current_price": 0, "prft_rt": 0},
        {"ticker": "034020", "name": "두산에너빌리티", "qty": 3, "avg_price": 114300, "current_price": 0, "prft_rt": 0},
        {"ticker": "052690", "name": "한전기술",       "qty": 2, "avg_price": 164700, "current_price": 0, "prft_rt": 0},
        {"ticker": "005930", "name": "삼성전자",       "qty": 1, "avg_price": 299500, "current_price": 0, "prft_rt": 0},
        {"ticker": "001440", "name": "대한전선",       "qty": 1, "avg_price": 55900,  "current_price": 0, "prft_rt": 0},
        {"ticker": "171120", "name": "라이온켐텍",     "qty": 16,"avg_price": 2703,   "current_price": 0, "prft_rt": 0},
    ]

# ── MAIN ───────────────────────────────────────────────────
def main():
    print("=" * 55)
    print("sfd_portfolio_sync.py v1.3  [Grade system applied]")
    print(f"Account: {ACCOUNT_NO} / Env: {ENV}")
    print("=" * 55)

    token    = get_access_token() if APP_KEY else None
    holdings = []
    if token:
        raw      = get_balance_ka01690(token)
        holdings = parse_holdings(raw) if raw else []
    if not holdings:
        holdings = manual_fallback()

    portfolio = build_portfolio_json(holdings)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(portfolio, f, ensure_ascii=False, indent=2)

    print(f"\n[DONE] portfolio.json saved")
    print(f"{'Ticker':^8} {'Name':^12} {'Grade':^5} {'Qty':>4} {'AvgPrice':>10} {'Trigger':>10} {'Trig%':>7} {'PnL%':>8}")
    print("-" * 75)
    for h in portfolio["holdings"]:
        tp   = f"{h['trigger_price']:>10,.0f}" if h["trigger_price"] else "       N/A"
        tpct = f"{h['trigger_pct']:>+6.0f}%" if h["trigger_pct"] else "    N/A"
        alert  = " ★" if "alert_price" in h else ""
        active = "" if h["active"] else " [방치]"
        print(f"  {h['ticker']}  {h['name']:10s}  [{h['grade']}]  "
              f"{h['qty']:>3}주  {h['avg_price']:>9,.0f}원  {tp}원  {tpct}  "
              f"{h['prft_rt']:>+7.2f}%{alert}{active}")

if __name__ == "__main__":
    main()
