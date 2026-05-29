# sfd_oscillation_analyzer.py | v1.0 | Layer 2.8 | Claude (Anthropic) 2026-05-29
# Deploy to: D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline\tools\sfd_oscillation_analyzer.py
#
# [Layer 2.8] 가격 진동 패턴 분석 + 거미줄 매매 격자 동적 계산
#
# 기존 portfolio.json web_strategy: 고정 -15% 격자 (모든 종목 동일)
# v1.0 업그레이드: 종목별 실제 진동 폭 측정 → 동적 격자 간격 자동 산출
#
# [분석 지표]
#   [A] 스윙 진폭 (Swing Amplitude): 최근 N개 고저점 간 평균 진폭
#   [B] 진동 주기 (Cycle Period): 연속 저점 간 평균 일수
#   [C] ATR 기반 변동성: Average True Range × 배수 = 적정 격자 간격
#   [D] 현재 페이즈: BOTTOM / LOWER_MID / UPPER_MID / TOP
#
# [거미줄 격자 출력]
#   - grid_pct:        종목별 격자 간격 (%)
#   - grid_levels:     BUY 1~4단계 가격
#   - qty_ratio:       단계별 수량 비율 (1:2:3:4 피라미딩)
#   - phase:           현재 진동 위치
#   - days_to_bottom:  예상 저점 도달 일수
#   - action:          즉시 매수 / 대기 / 홀드

import os
import sys
import time
import json
import logging
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import FinanceDataReader as fdr

try:
    from scipy.signal import find_peaks
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

# ── 경로 설정 ─────────────────────────────────────────────────────────────────
_env_base = os.environ.get("SFD_BASE_DIR", "")
if _env_base and os.path.isdir(_env_base):
    BASE_DIR = _env_base
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LATEST_DIR  = os.path.join(BASE_DIR, "outputs", "latest")
HISTORY_DIR = os.path.join(BASE_DIR, "outputs", "history")
DATA_DIR    = os.path.join(BASE_DIR, "data")

os.makedirs(LATEST_DIR,  exist_ok=True)
os.makedirs(HISTORY_DIR, exist_ok=True)

PORTFOLIO_JSON   = os.path.join(DATA_DIR,    "portfolio.json")
OUTPUT_CSV       = os.path.join(LATEST_DIR,  "sfd_oscillation_latest.csv")
GRID_SIGNAL_CSV  = os.path.join(LATEST_DIR,  "sfd_grid_signal_latest.csv")
LOG_PATH         = os.path.join(LATEST_DIR,  "sfd_oscillation_analyzer.log")

logging.basicConfig(
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

# ── 파라미터 ─────────────────────────────────────────────────────────────────
LOOKBACK_DAYS      = 120    # 진동 패턴 분석 기간
ATR_PERIOD         = 14
SWING_DISTANCE     = 5      # 스윙 고저점 최소 거리(봉)
MIN_SWINGS         = 3      # 유효 패턴 판단 최소 스윙 수
MAX_GRID_STEPS     = 4      # 거미줄 단계 수
QTY_RATIOS         = [1, 2, 3, 4]   # 단계별 수량 비율 (피라미딩)

# 격자 간격 제약 (종목 실제 진폭 기반이지만 상하한 적용)
MIN_GRID_PCT       = 3.0    # 최소 격자 간격: 3%
MAX_GRID_PCT       = 25.0   # 최대 격자 간격: 25%

START_TIME         = time.time()


# ── OHLCV 수집 ────────────────────────────────────────────────────────────────
def fetch_ohlcv(ticker: str, end_date: datetime) -> pd.DataFrame | None:
    try:
        start = (end_date - timedelta(days=LOOKBACK_DAYS * 2)).strftime("%Y-%m-%d")
        end   = end_date.strftime("%Y-%m-%d")
        df    = fdr.DataReader(ticker, start, end)
        if df is None or len(df) < 30: return None
        return df.sort_index().tail(LOOKBACK_DAYS)
    except:
        return None


# ── [A] 스윙 진폭 분석 ────────────────────────────────────────────────────────
def calc_swing_analysis(df: pd.DataFrame) -> dict:
    """
    고점/저점 스윙 탐지 → 진폭 & 주기 계산
    Returns: {amplitude_pct, cycle_days, swing_count, reliability}
    """
    try:
        close = df["Close"].values
        high  = df["High"].values
        low   = df["Low"].values

        if SCIPY_AVAILABLE:
            # 저점 탐지
            low_peaks,  _ = find_peaks(-close, distance=SWING_DISTANCE, prominence=close.mean() * 0.02)
            # 고점 탐지
            high_peaks, _ = find_peaks( close, distance=SWING_DISTANCE, prominence=close.mean() * 0.02)
        else:
            w = SWING_DISTANCE
            low_peaks  = [i for i in range(w, len(close)-w) if close[i] == min(close[i-w:i+w+1])]
            high_peaks = [i for i in range(w, len(close)-w) if close[i] == max(close[i-w:i+w+1])]
            low_peaks  = np.array(low_peaks)
            high_peaks = np.array(high_peaks)

        if len(low_peaks) < MIN_SWINGS or len(high_peaks) < MIN_SWINGS:
            return {"amplitude_pct": 15.0, "cycle_days": 20, "swing_count": 0, "reliability": "LOW"}

        # 진폭: 고점/저점 간 평균 비율 차이
        amplitudes = []
        for lp in low_peaks:
            # 가장 가까운 고점 찾기
            dists = np.abs(high_peaks - lp)
            nearest_hp = high_peaks[np.argmin(dists)]
            amp_pct = abs(close[nearest_hp] - close[lp]) / close[lp] * 100
            if 1.0 < amp_pct < 60.0:  # 이상치 제거
                amplitudes.append(amp_pct)

        # 주기: 연속 저점 간 평균 일수
        cycles = []
        if len(low_peaks) >= 2:
            for i in range(1, len(low_peaks)):
                cycles.append(low_peaks[i] - low_peaks[i-1])

        amplitude_pct = float(np.median(amplitudes)) if amplitudes else 15.0
        cycle_days    = int(np.median(cycles))        if cycles    else 20
        swing_count   = min(len(amplitudes), len(cycles))

        reliability = "HIGH" if swing_count >= 5 else "MED" if swing_count >= MIN_SWINGS else "LOW"

        return {
            "amplitude_pct": round(amplitude_pct, 2),
            "cycle_days":    cycle_days,
            "swing_count":   swing_count,
            "reliability":   reliability,
            "low_peaks":     low_peaks,
        }
    except Exception as e:
        logging.debug(f"swing_analysis error: {e}")
        return {"amplitude_pct": 15.0, "cycle_days": 20, "swing_count": 0, "reliability": "LOW", "low_peaks": np.array([])}


# ── [B] ATR 기반 변동성 ───────────────────────────────────────────────────────
def calc_atr(df: pd.DataFrame, period: int = 14) -> float:
    try:
        high  = df["High"]
        low   = df["Low"]
        close = df["Close"]
        tr    = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(period).mean().iloc[-1]
        return float(atr)
    except:
        return float(df["Close"].std())


# ── [C] 현재 진동 페이즈 판단 ────────────────────────────────────────────────
def calc_phase(df: pd.DataFrame, swing_data: dict) -> dict:
    """
    최근 N일 고/저점 대비 현재가 위치 → 페이즈 판단
    Returns: {phase, phase_pct, days_since_low, est_days_to_bottom}
    """
    try:
        close   = df["Close"].values
        current = close[-1]

        # 최근 진동 범위 계산
        recent = close[-30:]  # 최근 30일
        r_high = recent.max()
        r_low  = recent.min()
        r_range = r_high - r_low

        if r_range == 0:
            return {"phase": "FLAT", "phase_pct": 50.0, "days_since_low": 0, "est_days_to_bottom": 0}

        # 현재가의 범위 내 위치 (0% = 저점, 100% = 고점)
        phase_pct = (current - r_low) / r_range * 100

        if phase_pct <= 20:
            phase = "BOTTOM_ZONE"        # 저점 구간 → 즉시 매수 검토
        elif phase_pct <= 40:
            phase = "LOWER_MID"          # 하락 중간 → 분할 매수 준비
        elif phase_pct <= 60:
            phase = "MID_ZONE"           # 중립
        elif phase_pct <= 80:
            phase = "UPPER_MID"          # 상승 중간 → 매도 준비
        else:
            phase = "TOP_ZONE"           # 고점 구간 → 매도 검토

        # 마지막 저점 이후 경과일
        low_peaks = swing_data.get("low_peaks", np.array([]))
        days_since_low = int(len(close) - low_peaks[-1]) if len(low_peaks) > 0 else 0

        # 다음 저점까지 예상 일수
        cycle = swing_data.get("cycle_days", 20)
        est_days_to_bottom = max(0, cycle - days_since_low)

        return {
            "phase":                phase,
            "phase_pct":            round(phase_pct, 1),
            "days_since_low":       days_since_low,
            "est_days_to_bottom":   est_days_to_bottom,
            "recent_high":          round(float(r_high), 0),
            "recent_low":           round(float(r_low), 0),
        }
    except Exception as e:
        logging.debug(f"calc_phase error: {e}")
        return {"phase": "UNKNOWN", "phase_pct": 50.0, "days_since_low": 0, "est_days_to_bottom": 0}


# ── [D] 거미줄 격자 계산 (핵심) ───────────────────────────────────────────────
def calc_grid(current_price: float, amplitude_pct: float,
              atr: float, phase_data: dict, base_price: float = None) -> dict:
    """
    실제 진동 폭 기반 동적 격자 계산
    - 격자 간격 = 진폭 / 4 (4단계 분할)
    - 최소/최대 제약 적용
    - 피라미딩: 1:2:3:4 수량 비율
    Returns: {grid_pct, grid_levels, qty_plan, action}
    """
    # 격자 간격 결정: amplitude/4 기반, ATR 보정
    atr_pct      = atr / current_price * 100
    grid_pct_raw = amplitude_pct / MAX_GRID_STEPS  # 진폭 4등분
    grid_pct_atr = atr_pct * 1.5                   # ATR 기반 보조 계산
    grid_pct     = max(grid_pct_raw, grid_pct_atr)  # 더 큰 쪽 선택 (안전마진)
    grid_pct     = max(MIN_GRID_PCT, min(MAX_GRID_PCT, grid_pct))  # 제약 적용
    grid_pct     = round(grid_pct, 1)

    # 격자 기준가: base_price(매수가) 또는 현재가
    anchor = base_price if base_price else current_price

    # 매수 격자 레벨 (하락 시)
    buy_levels = []
    for step in range(1, MAX_GRID_STEPS + 1):
        trigger_pct   = -grid_pct * step
        trigger_price = round(anchor * (1 + trigger_pct / 100))
        qty_ratio     = QTY_RATIOS[step - 1]
        status        = "ACTIVE" if current_price <= trigger_price * 1.02 and current_price >= trigger_price * 0.98 else \
                        "NEAR"   if current_price <= trigger_price * 1.05 else \
                        "PENDING"
        buy_levels.append({
            "step":          step,
            "trigger_pct":   trigger_pct,
            "trigger_price": trigger_price,
            "qty_ratio":     qty_ratio,
            "status":        status,
        })

    # 매도 격자 레벨 (상승 시)
    sell_levels = []
    for step in range(1, MAX_GRID_STEPS + 1):
        sell_pct   = grid_pct * step
        sell_price = round(anchor * (1 + sell_pct / 100))
        sell_levels.append({
            "step":       step,
            "target_pct": sell_pct,
            "target_price": sell_price,
        })

    # 액션 판단
    phase = phase_data.get("phase", "UNKNOWN")
    est_days = phase_data.get("est_days_to_bottom", 99)
    near_steps = [l for l in buy_levels if l["status"] in ["ACTIVE", "NEAR"]]

    if phase == "BOTTOM_ZONE" and near_steps:
        action = f"BUY_NOW_STEP{near_steps[0]['step']}"
    elif phase in ["BOTTOM_ZONE", "LOWER_MID"] and est_days <= 3:
        action = "BUY_SOON"
    elif phase in ["LOWER_MID"] and near_steps:
        action = f"BUY_READY_STEP{near_steps[0]['step']}"
    elif phase in ["TOP_ZONE", "UPPER_MID"]:
        action = "SELL_ZONE"
    else:
        action = "HOLD_WATCH"

    return {
        "grid_pct":    grid_pct,
        "buy_levels":  buy_levels,
        "sell_levels": sell_levels,
        "action":      action,
    }


# ── 종목별 통합 분석 ──────────────────────────────────────────────────────────
def analyze_ticker_oscillation(ticker: str, end_date: datetime,
                                base_price: float = None) -> dict | None:
    df = fetch_ohlcv(ticker, end_date)
    if df is None:
        return None

    try:
        current_price  = float(df["Close"].iloc[-1])
        swing_data     = calc_swing_analysis(df)
        atr_val        = calc_atr(df, ATR_PERIOD)
        phase_data     = calc_phase(df, swing_data)
        grid_data      = calc_grid(current_price, swing_data["amplitude_pct"],
                                   atr_val, phase_data, base_price)

        return {
            "ticker":              ticker.zfill(6),
            "current_price":       round(current_price, 0),
            "base_price":          round(base_price, 0) if base_price else round(current_price, 0),
            # 진동 패턴
            "amplitude_pct":       swing_data["amplitude_pct"],
            "cycle_days":          swing_data["cycle_days"],
            "swing_count":         swing_data["swing_count"],
            "reliability":         swing_data["reliability"],
            # ATR
            "atr":                 round(atr_val, 0),
            "atr_pct":             round(atr_val / current_price * 100, 2),
            # 페이즈
            "phase":               phase_data["phase"],
            "phase_pct":           phase_data["phase_pct"],
            "days_since_low":      phase_data["days_since_low"],
            "est_days_to_bottom":  phase_data["est_days_to_bottom"],
            "recent_high":         phase_data.get("recent_high", 0),
            "recent_low":          phase_data.get("recent_low", 0),
            # 격자
            "grid_pct":            grid_data["grid_pct"],
            "action":              grid_data["action"],
            # 격자 레벨 (CSV 직렬화)
            "buy_step1_price":     grid_data["buy_levels"][0]["trigger_price"],
            "buy_step1_status":    grid_data["buy_levels"][0]["status"],
            "buy_step2_price":     grid_data["buy_levels"][1]["trigger_price"],
            "buy_step2_status":    grid_data["buy_levels"][1]["status"],
            "buy_step3_price":     grid_data["buy_levels"][2]["trigger_price"],
            "buy_step3_status":    grid_data["buy_levels"][2]["status"],
            "buy_step4_price":     grid_data["buy_levels"][3]["trigger_price"],
            "buy_step4_status":    grid_data["buy_levels"][3]["status"],
            "sell_step1_price":    grid_data["sell_levels"][0]["target_price"],
            "sell_step2_price":    grid_data["sell_levels"][1]["target_price"],
            # raw grid (JSON 저장용)
            "_grid_detail":        json.dumps(grid_data, ensure_ascii=False),
        }
    except Exception as e:
        logging.debug(f"analyze_ticker_oscillation {ticker} error: {e}")
        return None


# ── portfolio.json에서 보유 종목 + base_price 로드 ────────────────────────────
def load_portfolio_tickers() -> list:
    """
    portfolio.json → [{ticker, name, base_price}]
    없으면 signal_latest.csv에서 상위 종목 로드
    """
    # 1순위: portfolio.json
    if os.path.exists(PORTFOLIO_JSON):
        try:
            with open(PORTFOLIO_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            holdings = data.get("holdings", [])
            result = []
            for h in holdings:
                ticker = str(h.get("ticker", "")).zfill(6)
                name   = h.get("name", "")
                # base_price: 첫 매수가 또는 web_strategy.base_price
                ws         = h.get("web_strategy", {})
                base_price = ws.get("base_price", None)
                if not base_price:
                    positions  = h.get("positions", [])
                    base_price = positions[0]["price"] if positions else None
                if ticker and ticker != "000000":
                    result.append({"ticker": ticker, "name": name, "base_price": base_price})
            logging.info(f"portfolio.json loaded: {len(result)} holdings")
            return result
        except Exception as e:
            logging.warning(f"portfolio.json load failed: {e}")

    # 2순위: sfd_master_signal_latest.csv 상위 20종목
    signal_csv = os.path.join(LATEST_DIR, "sfd_master_signal_latest.csv")
    if os.path.exists(signal_csv):
        try:
            df = pd.read_csv(signal_csv, encoding="utf-8-sig", dtype={"ticker": str})
            top = df.head(20)[["ticker", "name"]].to_dict("records")
            for row in top:
                row["base_price"] = None
            logging.info(f"signal_latest fallback: {len(top)} tickers")
            return top
        except:
            pass

    return []


# ── 최근 거래일 ───────────────────────────────────────────────────────────────
def find_recent_trade_date() -> datetime:
    now = datetime.now()
    for i in range(7):
        d = now - timedelta(days=i)
        if d.weekday() >= 5: continue
        try:
            ds = d.strftime("%Y-%m-%d")
            df = fdr.DataReader("005930", ds, ds)
            if df is not None and len(df) > 0: return d
        except: pass
    return now


# ── 메인 ──────────────────────────────────────────────────────────────────────
def main():
    logging.info("=== sfd_oscillation_analyzer v1.0 START ===")
    logging.info(f"BASE_DIR: {BASE_DIR}")
    logging.info(f"SCIPY:    {SCIPY_AVAILABLE}")

    end_date  = find_recent_trade_date()
    holdings  = load_portfolio_tickers()

    if not holdings:
        logging.error("No tickers to analyze. portfolio.json or signal_latest.csv required.")
        sys.exit(1)

    logging.info(f"Analyzing {len(holdings)} tickers | trade_date: {end_date.strftime('%Y%m%d')}")

    results     = []
    grid_alerts = []   # 즉시 액션 필요 종목

    for h in holdings:
        ticker     = h["ticker"]
        base_price = h.get("base_price")
        name       = h.get("name", "")

        row = analyze_ticker_oscillation(ticker, end_date, base_price)
        if not row:
            logging.warning(f"  SKIP: {ticker}")
            continue

        row["name"] = name
        results.append(row)

        # 즉시 액션 알림
        if row["action"] not in ["HOLD_WATCH", "SELL_ZONE"]:
            grid_alerts.append({
                "ticker":       ticker,
                "name":         name,
                "action":       row["action"],
                "phase":        row["phase"],
                "phase_pct":    row["phase_pct"],
                "grid_pct":     row["grid_pct"],
                "amplitude":    row["amplitude_pct"],
                "cycle_days":   row["cycle_days"],
                "est_bottom":   row["est_days_to_bottom"],
                "buy_step1":    row["buy_step1_price"],
                "buy_step1_st": row["buy_step1_status"],
                "current":      row["current_price"],
                "base_price":   row["base_price"],
            })

        logging.info(
            f"  {ticker} | phase={row['phase']} | amp={row['amplitude_pct']}% "
            f"| cycle={row['cycle_days']}d | grid={row['grid_pct']}% | action={row['action']}"
        )

    # CSV 저장
    if results:
        df_out = pd.DataFrame(results).drop(columns=["_grid_detail", "low_peaks"], errors="ignore")
        df_out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
        hist = os.path.join(HISTORY_DIR, f"sfd_oscillation_{end_date.strftime('%Y%m%d')}.csv")
        df_out.to_csv(hist, index=False, encoding="utf-8-sig")

    if grid_alerts:
        df_alert = pd.DataFrame(grid_alerts)
        df_alert.to_csv(GRID_SIGNAL_CSV, index=False, encoding="utf-8-sig")
        logging.info(f"\n{'='*60}")
        logging.info(f"[거미줄 매매 알림] {len(grid_alerts)}개 종목 액션 필요")
        for a in grid_alerts:
            logging.info(
                f"  [{a['action']}] {a['ticker']} {a['name']} | "
                f"현재={a['current']:,} 기준={a['base_price']:,} | "
                f"격자={a['grid_pct']}% | 진폭={a['amplitude']}% | "
                f"저점예상={a['est_bottom']}일후"
            )
        logging.info(f"{'='*60}")

    elapsed = int(time.time() - START_TIME)
    logging.info(f"DONE | analyzed={len(results)} alerts={len(grid_alerts)} elapsed={elapsed}s")
    print(f"[OK] oscillation | analyzed={len(results)} | alerts={len(grid_alerts)} | elapsed={elapsed}s")
    if grid_alerts:
        print(f"\n[거미줄 매매 알림]")
        for a in grid_alerts:
            print(f"  {a['action']:25s} | {a['ticker']} {a['name']:15s} | "
                  f"현재={a['current']:>8,} | 격자={a['grid_pct']}% | "
                  f"진폭={a['amplitude']}% | 저점까지≈{a['est_bottom']}일")
    print(f"  -> {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
