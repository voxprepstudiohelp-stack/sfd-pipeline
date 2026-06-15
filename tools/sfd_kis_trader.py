"""
sfd_kis_trader.py — KIS 자동매매 모듈 v0.5
=============================================================
계좌: 실전투자계좌 44626570 | 만료: 2027.05.25
인터페이스: KIS OpenAPI REST

레이어 구조:
  [Layer 7] sfd_kis_trader.py
  [Layer 6] sfd_trade_guardian.py ← 9개 알림코드
  [Layer 5] sfd_master_signal_latest.csv ← RESERVE_BUY 후보 (decay 내장)
  [Layer 4] sfd_signal_aggregator

거미줄 분할매수 (Spider-Web):
  Grade A (고신뢰): 캐시의 12% / 3분할 매수
  Grade B (중신뢰): 캐시의 6% / 2분할 매수
  Grade C (보통): 캐시의 2.5% / 1분할 매수

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
  - [C1] 기존 보유 종목 (portfolio.json / KIS 잔고)
  - [C2] 동일종목 당일 2회 이상 주문 (order_log.csv)
  - [M1] 계좌 당일손실 −3% 이하

v0.4 → v0.5 변경사항:
  - [거미줄 보수전략] _calc_qty(): SFD_QTY_FIXED_ONE 환경변수 추가
    → true(기본값): 1주 고정 (자본여력 보수 전략)
    → false: 기존 Grade 비중 방식 (A=12%/B=6%/C=2.5%)
    → .env 또는 GitHub Secrets에서 제어 가능
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

APP_KEY    = os.environ.get("KIS_APP_KEY", "")
APP_SECRET = os.environ.get("KIS_APP_SECRET", "")
ACCOUNT_NO = os.environ.get("KIS_ACCOUNT_NO", "44626570")
ACCOUNT_SFX = os.environ.get("KIS_ACCOUNT_SFX", "01")
BASE_URL   = "https://openapi.koreainvestment.com:9443"

PIPELINE_ROOT = Path(os.environ.get(
    "PIPELINE_ROOT",
    r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline"
))
SIGNAL_OUTPUT  = PIPELINE_ROOT / "outputs" / "latest" / "sfd_master_signal_latest.csv"
DECAY_OUTPUT   = None  # decay embedded in SIGNAL_OUTPUT
ORDER_LOG      = PIPELINE_ROOT / "outputs" / "order_log.csv"
PORTFOLIO_JSON = PIPELINE_ROOT / "outputs" / "latest" / "sfd_portfolio_latest.json"

# ── Grade 기준
GRADE_THRESHOLDS = {"A": 110, "B": 90, "C": 70}

# ── 당일손실 HALT 기준 (M1)
DAILY_LOSS_HALT = -0.03  # −3%


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
        self._token: Optional[str] = None
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
            "Content-Type": "application/json",
            "authorization": f"Bearer {self.get_token()}",
            "appkey": APP_KEY,
            "appsecret": APP_SECRET,
            "tr_id": tr_id,
            "custtype": "P",
        }


class KISPortfolio:
    def __init__(self, auth: KISAuth):
        self.auth = auth
        self._balance_cache: Optional[dict] = None  # 1콜 캐시

    def get_balance(self) -> dict:
        """KIS TTTC8434R 잔고조회 — 캐시 적용 (동일 세션 내 재호출 방지)"""
        if self._balance_cache:
            return self._balance_cache
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
        self._balance_cache = resp.json()
        return self._balance_cache

    def get_balance_summary(self) -> dict:
        """
        [P6] 잔고 요약 반환 — cash + daily_pnl_rate 통합 (1콜)

        KIS output2[0] 주요 필드:
          dnca_tot_amt       : 예수금 총액 (가용 현금)
          tot_evlu_amt       : 총평가금액 (보유주식 현재가 합계 + 예수금)
          pchs_amt_smtl_inqr : 매입금액 합계 (보유주식 매입가 합계)
          evlu_pfls_smtl_amt : 평가손익 합계

        daily_pnl_rate 계산:
          = evlu_pfls_smtl_amt / pchs_amt_smtl_inqr
          → 주식 평가금액 기준 수익률 (예수금 제외)
          → pchs_amt = 0 이면 0.0 반환
        """
        result = {"cash": 0, "daily_pnl_rate": None, "source": "KIS_API"}
        try:
            data = self.get_balance()
            o2 = data.get("output2", [{}])[0]

            cash     = int(o2.get("dnca_tot_amt", 0) or 0)
            pchs_amt = float(o2.get("pchs_amt_smtl_inqr", 0) or 0)
            evlu_pfls = float(o2.get("evlu_pfls_smtl_amt", 0) or 0)

            result["cash"] = cash

            # ★ P6 핵심: 실시간 daily_pnl_rate
            if pchs_amt > 0:
                result["daily_pnl_rate"] = evlu_pfls / pchs_amt
            else:
                result["daily_pnl_rate"] = 0.0  # 주식 미보유

            print(f"[KIS] 잔고조회 완료 | 현금={cash:,}원 | "
                  f"매입={pchs_amt:,.0f}원 | 평가손익={evlu_pfls:+,.0f}원 | "
                  f"수익률={result['daily_pnl_rate']*100:+.2f}%")

        except Exception as e:
            print(f"[WARN] KIS 잔고조회 실패: {e} → portfolio.json fallback")
            result["source"] = "FALLBACK"
            result.update(self._fallback_from_portfolio())

        return result

    def _fallback_from_portfolio(self) -> dict:
        """KIS API 실패 시 portfolio.json 정적 계산 (graceful degradation)"""
        fallback = {"cash": 0, "daily_pnl_rate": None}
        if not PORTFOLIO_JSON.exists():
            return fallback
        try:
            with open(PORTFOLIO_JSON, encoding="utf-8") as f:
                data = json.load(f)
            if "daily_pnl_rate" in data:
                fallback["daily_pnl_rate"] = float(data["daily_pnl_rate"])
            else:
                total_eval = float(data.get("total_eval", 0))
                total_buy  = float(data.get("total_buy", 0))
                if total_buy > 0:
                    fallback["daily_pnl_rate"] = (total_eval - total_buy) / total_buy
            fallback["cash"] = int(data.get("cash", 0))
        except Exception as e:
            print(f"[WARN] portfolio.json fallback 실패: {e}")
        return fallback

    def get_cash(self) -> int:
        """예수금 반환 (get_balance_summary 캐시 활용)"""
        return self.get_balance_summary()["cash"]

    def get_daily_pnl_rate(self) -> Optional[float]:
        """[P6] 실시간 당일 수익률 반환"""
        return self.get_balance_summary()["daily_pnl_rate"]


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
        return holdings

    def _load_today_orders(self) -> set:
        today_str  = date.today().strftime("%Y-%m-%d")
        today_codes = set()
        if ORDER_LOG.exists():
            try:
                log_df = pd.read_csv(ORDER_LOG, dtype=str)
                if "timestamp" in log_df.columns and "stock_code" in log_df.columns:
                    today_df    = log_df[log_df["timestamp"].str.startswith(today_str)]
                    today_codes = set(today_df["stock_code"].dropna().unique())
            except Exception as e:
                print(f"  [WARN] order_log.csv 파싱 실패: {e}")
        return today_codes

    def _get_account_daily_pnl(self) -> Optional[float]:
        """
        [P6] KIS API 실시간 당일 수익률 반환
        KISPortfolio.get_daily_pnl_rate() 위임 (API 실패 시 자동 fallback)
        """
        return self.portfolio.get_daily_pnl_rate()

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
        """
        매수 수량 계산
        [v0.5] SFD_QTY_FIXED_ONE 환경변수로 전략 전환:
          - true (기본값): 1주 고정 — 거미줄 매매 자본여력 보수 전략
          - false         : Grade 비중 방식 (A=12%/B=6%/C=2.5%)
        .env 또는 GitHub Secrets에서 SFD_QTY_FIXED_ONE=false 로 전환 가능
        """
        fixed_one = os.environ.get("SFD_QTY_FIXED_ONE", "true").lower() == "true"
        if fixed_one:
            return 1

        ratio  = {"A": 0.12, "B": 0.06, "C": 0.025}.get(grade, 0.03)
        budget = int(cash * ratio / split)
        qty    = budget // price if price > 0 else 0
        return max(1, qty)

    def run(self, dry_run: bool = True):
        mode_label = "DRY-RUN" if dry_run else "LIVE"
        print(f"\n[SFDTrader v0.5] {mode_label} | {datetime.now():%Y-%m-%d %H:%M:%S}")
        print(f"  SIGNAL_OUTPUT : {SIGNAL_OUTPUT}")
        print(f"  PORTFOLIO_JSON: {PORTFOLIO_JSON}")
        qty_mode = "1주고정" if os.environ.get("SFD_QTY_FIXED_ONE", "true").lower() == "true" else "Grade비중"
        print(f"  QTY_MODE      : {qty_mode} (SFD_QTY_FIXED_ONE={os.environ.get('SFD_QTY_FIXED_ONE','true')})")
        print("-" * 65)

        # ── [P6] KIS API 실시간 잔고 + PnL (1콜)
        balance_summary = self.portfolio.get_balance_summary()
        pnl    = balance_summary["daily_pnl_rate"]
        source = balance_summary["source"]

        if pnl is not None:
            print(f"  Daily PnL: {pnl*100:+.2f}% [{source}]", end="")
            if pnl <= DAILY_LOSS_HALT:
                print(f" HALT (<={DAILY_LOSS_HALT*100:.0f}%)")
                if not dry_run:
                    print("[SFDTrader] HALT: 당일 손실 한도 초과 — 주문 중단")
                    return
                else:
                    print(" [DRY-RUN] HALT 조건 해당 — 실거래 시 주문 중단됨 (시뮬레이션 계속)")
            else:
                print(" OK")
        else:
            print("  Daily PnL: N/A")

        holdings     = self._load_holdings()
        today_orders = self._load_today_orders()
        print(f"  Held stocks : {len(holdings)}종목")
        print(f"  Today orders: {len(today_orders)}건")
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

        # ── [P6] dry_run도 실잔고 우선 사용 (시뮬레이션 정확도 향상)
        if dry_run:
            kis_cash = balance_summary.get("cash", 0)
            cash       = kis_cash if kis_cash > 0 else 50_000_000
            cash_label = "(KIS실잔고)" if kis_cash > 0 else "(simulated)"
        else:
            cash       = balance_summary["cash"]
            cash_label = "(actual)"

        print(f"  Total signals : {len(df)}")
        print(f"  RESERVE_BUY   : {len(reserve)}")
        print(f"  Available cash: {cash:,}원 {cash_label}")
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
                print(f"  BLOCKED {code:6s} {name[:10]:10s} score={score:5.1f} | {reason}")
                continue

            if price <= 0:
                print(f"  SKIP    {code:6s} {name[:10]:10s} score={score:5.1f} | PRICE_ZERO")
                continue

            qty     = self._calc_qty(price, grade, cash)
            buy_prc = int(price * 1.003)
            budget  = int(cash * {"A": 0.12, "B": 0.06, "C": 0.025}.get(grade, 0.03))
            order_count += 1

            print(f"  ORDER   {code:6s} {name[:10]:10s} | grade={grade} score={score:5.1f} "
                  f"qty={qty} @{buy_prc:,}원 budget={budget:,}원")

            if not dry_run:
                self.order.buy_limit(code, qty, buy_prc)
                today_orders.add(code)
                time.sleep(0.3)

        print("-" * 65)
        print(f"[SFDTrader v0.5] Done | orders={'SIMULATED' if dry_run else 'EXECUTED'} x{order_count}")


if __name__ == "__main__":
    dry = "--live" not in sys.argv
    trader = SFDTrader()
    trader.run(dry_run=dry)
