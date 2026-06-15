"""
sfd_kis_trader.py — KIS 자동매매 모듈 v0.3
=============================================================
계좌: 실전투자계좌 44626570  |  만료: 2027.05.25
인터페이스: KIS OpenAPI REST

레이어 구조:
  [Layer 7]  sfd_kis_trader.py
  [Layer 6]  sfd_trade_guardian.py   ← 9개 알림코드
  [Layer 5]  sfd_master_signal_latest.csv  ← RESERVE_BUY 후보 (decay 내장)
  [Layer 4]  sfd_signal_aggregator

거미줄 분할매수 (Spider-Web):
  Grade A (고신뢰): 캐시의 12% / 3분할 매수
  Grade B (중신뢰): 캐시의  6% / 2분할 매수
  Grade C (보통): 캐시의  2.5% / 1분할 매수

  1차 매수: 현재가 × 1.003
  2차 매수: −3%
  3차 매수: −6%
  손절: −8%
  익절: +15%

BLOCK 조건:
  - signal != RESERVE_BUY
  - total_score < 90
  - decay_flag == "STALE"
  - macro_score < −10pt
  - [C1] 기존 보유 종목 (portfolio.json / KIS 잔고)     ← v0.3 신규
  - [C2] 동일종목 당일 2회 이상 주문 (order_log.csv)    ← v0.3 신규
  - [M1] 계좌 당일손실 −3% 이하                         ← v0.3 신규

v0.2.1 → v0.3 변경사항:
  - [C1] _load_holdings(): portfolio.json fallback → 보유종목 set 구성
         _is_blocked()에 ALREADY_HELD 체크 추가
  - [C2] _load_today_orders(): order_log.csv 당일 주문 종목 집계
         _is_blocked()에 DUPLICATE_TODAY 체크 추가
  - [M1] _get_account_daily_pnl(): portfolio.json 기준 당일 손익률 계산
         run() 시작 시 계좌 손실 −3% 이하 → 전체 HALT
  - dry_run 시 HALT 메시지 출력 (실주문 없으므로 계속 진행은 가능, warning만)
"""

import os
import sys
import time
import json
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime, date
from typing import Optional

# .env 자동 로드
try:
    from dotenv import load_dotenv
    _ENV = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(_ENV, override=True)
except ImportError:
    pass

APP_KEY     = os.environ.get("KIS_APP_KEY",     "")
APP_SECRET  = os.environ.get("KIS_APP_SECRET",  "")
ACCOUNT_NO  = os.environ.get("KIS_ACCOUNT_NO",  "44626570")
ACCOUNT_SFX = os.environ.get("KIS_ACCOUNT_SFX", "01")
BASE_URL    = "https://openapi.koreainvestment.com:9443"

PIPELINE_ROOT = Path(os.environ.get(
    "PIPELINE_ROOT",
    r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline"
))
SIGNAL_OUTPUT  = PIPELINE_ROOT / "outputs" / "latest" / "sfd_master_signal_latest.csv"
DECAY_OUTPUT   = None  # v0.2.1+: decay embedded in SIGNAL_OUTPUT
ORDER_LOG      = PIPELINE_ROOT / "outputs" / "order_log.csv"
PORTFOLIO_JSON = PIPELINE_ROOT / "portfolio.json"  # 루트 portfolio.json (account_report와 동일 소스)

# ── Grade 기준
GRADE_THRESHOLDS = {"A": 110, "B": 90, "C": 70}

# ── 당일손실 HALT 기준 (M1)
DAILY_LOSS_HALT = -0.03   # −3%


def score_to_grade(score: float) -> str:
    if score >= GRADE_THRESHOLDS["A"]: return "A"
    if score >= GRADE_THRESHOLDS["B"]: return "B"
    return "C"


def _safe(row: pd.Series, *keys, default=0):
    for k in keys:
        if k in row.index and pd.notna(row[k]):
            try: return row[k]
            except: pass
    return default


class KISAuth:
    def __init__(self):
        self._token:   Optional[str]      = None
        self._expires: Optional[datetime] = None

    def get_token(self) -> str:
        if self._token and self._expires and datetime.now() < self._expires:
            return self._token
        resp = requests.post(
            f"{BASE_URL}/oauth2/tokenP",
            json={"grant_type": "client_credentials", "appkey": APP_KEY, "appsecret": APP_SECRET},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        exp_str = data.get("access_token_token_expired", "")
        try:
            self._expires = datetime.strptime(exp_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            self._expires = None
        print(f"[KIS] Token issued (expires: {self._expires})")
        return self._token

    def headers(self, tr_id: str) -> dict:
        return {
            "Content-Type":  "application/json",
            "authorization": f"Bearer {self.get_token()}",
            "appkey":        APP_KEY,
            "appsecret":     APP_SECRET,
            "tr_id":         tr_id,
            "custtype":      "P",
        }


class KISPortfolio:
    def __init__(self, auth: KISAuth):
        self.auth = auth

    def get_balance(self) -> dict:
        resp = requests.get(
            f"{BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance",
            headers=self.auth.headers("TTTC8434R"),
            params={
                "CANO": ACCOUNT_NO, "ACNT_PRDT_CD": ACCOUNT_SFX,
                "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02",
                "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "00",
                "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def get_cash(self) -> int:
        data = self.get_balance()
        try:
            return int(data["output2"][0]["dnca_tot_amt"])
        except (KeyError, IndexError, ValueError):
            return 0


class KISOrder:
    def __init__(self, auth: KISAuth):
        self.auth = auth

    def buy_limit(self, stock_code: str, qty: int, price: int) -> dict:
        body = {
            "CANO": ACCOUNT_NO, "ACNT_PRDT_CD": ACCOUNT_SFX,
            "PDNO": stock_code, "ORD_DVSN": "00",
            "ORD_QTY": str(qty), "ORD_UNPR": str(price),
        }
        resp = requests.post(
            f"{BASE_URL}/uapi/domestic-stock/v1/trading/order-cash",
            headers=self.auth.headers("TTTC0802U"),
            json=body, timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()
        self._log_order(stock_code, "BUY_LIMIT", qty, price, result)
        return result

    def sell_limit(self, stock_code: str, qty: int, price: int) -> dict:
        body = {
            "CANO": ACCOUNT_NO, "ACNT_PRDT_CD": ACCOUNT_SFX,
            "PDNO": stock_code, "ORD_DVSN": "00",
            "ORD_QTY": str(qty), "ORD_UNPR": str(price),
        }
        resp = requests.post(
            f"{BASE_URL}/uapi/domestic-stock/v1/trading/order-cash",
            headers=self.auth.headers("TTTC0801U"),
            json=body, timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()
        self._log_order(stock_code, "SELL_LIMIT", qty, price, result)
        return result

    def _log_order(self, code, order_type, qty, price, result):
        log = {
            "timestamp":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "stock_code": code, "order_type": order_type,
            "qty": qty, "price": price,
            "rt_cd": result.get("rt_cd", "?"),
            "msg":   result.get("msg1", ""),
        }
        df = pd.DataFrame([log])
        if ORDER_LOG.exists():
            df.to_csv(ORDER_LOG, mode="a", header=False, index=False, encoding="utf-8-sig")
        else:
            ORDER_LOG.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(ORDER_LOG, index=False, encoding="utf-8-sig")
        print(f"  [ORDER] {code} {order_type} {qty}주 @{price:,}원 → {log['rt_cd']} {log['msg']}")


class SFDTrader:
    def __init__(self):
        self.auth      = KISAuth()
        self.portfolio = KISPortfolio(self.auth)
        self.order     = KISOrder(self.auth)

    def _load_holdings(self) -> set:
        holdings = set()
        if PORTFOLIO_JSON.exists():
            try:
                with open(PORTFOLIO_JSON, encoding="utf-8") as f:
                    data = json.load(f)
                for item in data.get("holdings", []):
                    code = item.get("stock_code") or item.get("ticker")
                    if code:
                        holdings.add(str(code).strip())
            except Exception as e:
                print(f"  [WARN] portfolio.json 파싱 실패: {e} → 보유종목 체크 스킵")
        else:
            print(f"  [WARN] portfolio.json 없음: {PORTFOLIO_JSON}")
            print(f"         → 기존 보유종목 중복매수 방지 비활성")
        return holdings

    def _load_today_orders(self) -> set:
        today_str = date.today().strftime("%Y-%m-%d")
        today_codes = set()
        if ORDER_LOG.exists():
            try:
                log_df = pd.read_csv(ORDER_LOG, dtype=str)
                if "timestamp" in log_df.columns and "stock_code" in log_df.columns:
                    today_df = log_df[log_df["timestamp"].str.startswith(today_str)]
                    today_codes = set(today_df["stock_code"].dropna().unique())
            except Exception as e:
                print(f"  [WARN] order_log.csv 파싱 실패: {e}")
        return today_codes

    def _get_account_daily_pnl(self) -> Optional[float]:
        if not PORTFOLIO_JSON.exists():
            return None
        try:
            with open(PORTFOLIO_JSON, encoding="utf-8") as f:
                data = json.load(f)
            if "daily_pnl_rate" in data:
                return float(data["daily_pnl_rate"])
            total_eval = float(data.get("total_eval", 0))
            total_buy  = float(data.get("total_buy", 0))
            if total_buy > 0:
                return (total_eval - total_buy) / total_buy
        except Exception as e:
            print(f"  [WARN] 당일 손익률 계산 실패: {e}")
        return None

    def _is_blocked(self, row: pd.Series, holdings: set, today_orders: set) -> tuple:
        sig = _safe(row, "signal", default="")
        if sig != "RESERVE_BUY":
            return True, f"NOT_RESERVE_BUY({sig})"

        score = float(_safe(row, "total_score", default=0))
        if score < 90:
            return True, f"SCORE_LOW({score})"

        if row.get("decay_flag") == "STALE":
            return True, "DECAY_STALE"

        macro = float(_safe(row, "macro_boost", "macro_score", default=0))
        if macro < -10:
            return True, f"MACRO_SHOCK({macro})"

        code = str(row.get("stock_code", "?"))
        if code in holdings:
            return True, "ALREADY_HELD"

        if code in today_orders:
            return True, "DUPLICATE_TODAY"

        return False, "OK"

    def _calc_qty(self, price: int, grade: str, cash: int, split: int = 1) -> int:
        ratio  = {"A": 0.12, "B": 0.06, "C": 0.025}.get(grade, 0.03)
        budget = int(cash * ratio / split)
        qty    = budget // price if price > 0 else 0
        return max(1, qty)

    def run(self, dry_run: bool = True):
        mode_label = "DRY-RUN" if dry_run else "LIVE"
        print(f"\n[SFDTrader v0.3] {mode_label} | {datetime.now():%Y-%m-%d %H:%M:%S}")
        print(f"  SIGNAL_OUTPUT : {SIGNAL_OUTPUT}")
        print(f"  PORTFOLIO_JSON: {PORTFOLIO_JSON}")
        print("-" * 65)

        pnl = self._get_account_daily_pnl()
        if pnl is not None:
            print(f"  Daily PnL: {pnl*100:+.2f}%", end="")
            if pnl <= DAILY_LOSS_HALT:
                print(f"  HALT (<={DAILY_LOSS_HALT*100:.0f}%)")
                if not dry_run:
                    print("[SFDTrader] HALT: 당일 손실 한도 초과 — 주문 중단")
                    return
                else:
                    print("  [DRY-RUN] HALT 조건 해당 — 실거래 시 주문 중단됨 (시뮬레이션 계속)")
            else:
                print("  OK")
        else:
            print("  Daily PnL: N/A (portfolio.json 없음)")

        holdings     = self._load_holdings()
        today_orders = self._load_today_orders()
        print(f"  Held stocks   : {len(holdings)}종목")
        print(f"  Today orders  : {len(today_orders)}건")
        print("-" * 65)

        if not SIGNAL_OUTPUT.exists():
            raise FileNotFoundError(f"SIGNAL_OUTPUT 없음: {SIGNAL_OUTPUT}")

        df = pd.read_csv(SIGNAL_OUTPUT, dtype=str)
        if "ticker" in df.columns and "stock_code" not in df.columns:
            df = df.rename(columns={"ticker": "stock_code"})
        if "decay_flag"  not in df.columns: df["decay_flag"]  = "FRESH"
        if "decay_score" not in df.columns: df["decay_score"] = "0"

        for col in ["total_score", "tech_score", "news_score", "investor_score",
                    "decay_score", "prev_close", "macro_score", "macro_boost"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        reserve = df[df["signal"] == "RESERVE_BUY"].copy()
        cash    = 50_000_000 if dry_run else self.portfolio.get_cash()
        print(f"  Total signals  : {len(df)}")
        print(f"  RESERVE_BUY    : {len(reserve)}")
        print(f"  Available cash : {cash:,}원 {'(simulated)' if dry_run else '(actual)'}")
        print("-" * 65)

        order_count = 0
        for _, row in reserve.iterrows():
            blocked, reason = self._is_blocked(row, holdings, today_orders)
            code  = str(row.get("stock_code", "?"))
            name  = str(_safe(row, "name", default=""))
            score = float(_safe(row, "total_score", default=0))
            price = int(_safe(row, "current_price", "prev_close", "close", default=0))
            grade = row.get("grade") if "grade" in row.index and pd.notna(row.get("grade")) \
                    else score_to_grade(score)

            if blocked:
                print(f"  BLOCKED  {code:6s} {name[:10]:10s} score={score:5.1f} | {reason}")
                continue

            if price <= 0:
                print(f"  SKIP     {code:6s} {name[:10]:10s} score={score:5.1f} | PRICE_ZERO")
                continue

            qty     = self._calc_qty(price, grade, cash)
            buy_prc = int(price * 1.003)
            budget  = int(cash * {"A": 0.12, "B": 0.06, "C": 0.025}.get(grade, 0.03))
            order_count += 1

            print(f"  ORDER    {code:6s} {name[:10]:10s} | grade={grade} score={score:5.1f} "
                  f"qty={qty} @{buy_prc:,}원 budget={budget:,}원")

            if not dry_run:
                self.order.buy_limit(code, qty, buy_prc)
                today_orders.add(code)
                time.sleep(0.3)

        print("-" * 65)
        print(f"[SFDTrader v0.3] Done | orders={'SIMULATED' if dry_run else 'EXECUTED'} x{order_count}")


if __name__ == "__main__":
    dry = "--live" not in sys.argv
    trader = SFDTrader()
    trader.run(dry_run=dry)
