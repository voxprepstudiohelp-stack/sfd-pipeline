# sfd_oscillation_analyzer.py | v1.1 | Layer 2.8 | Claude (Anthropic) 2026-05-30
# Deploy to: sfd-pipeline/tools/sfd_oscillation_analyzer.py
#
# [Layer 2.8] 진동 패턴 분석 + 격자 매매 신호 + 저점예측
#
# [v1.0 → v1.1 변경사항] 거미줄 파라미터 튜닝
#   - MIN_GRID_PCT: 3.0 → 10.0  ★ 핵심 (너무 촘촘한 격자 방지)
#   - MAX_GRID_PCT: 25.0 → 30.0 ★ 상한 확대 (고변동성 종목 대응)
#   - ATR_MULT:     1.5 → 2.0   ★ ATR 기반 격자 여유 확대
#   - 배경: #45 결과 격자 분포 — 두산에너빌리티 11.3%, 한전기술 10.6%,
#           대한전선 18.3%, LS 18.8% → 10~15% 범위가 실전 적합
#           3~9% 격자는 노이즈 매매 유발 → MIN 10% 로 하한 상향
#   - SWING_DISTANCE: 5 → 7     ★ 스윙 탐지 민감도 완화 (잡음 감소)

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

# ── 경로 설정
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

PORTFOLIO_JSON  = os.path.join(DATA_DIR,   "portfolio.json")
OUTPUT_CSV      = os.path.join(LATEST_DIR, "sfd_oscillation_latest.csv")
GRID_SIGNAL_CSV = os.path.join(LATEST_DIR, "sfd_grid_signal_latest.csv")
LOG_PATH        = os.path.join(LATEST_DIR, "sfd_oscillation_analyzer.log")

logging.basicConfig(
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

# ── 파라미터 (★ v1.1 튜닝)
LOOKBACK_DAYS   = 120
ATR_PERIOD      = 14
SWING_DISTANCE  = 7       # ★ v1.1: 5 → 7 (스윙 탐지 노이즈 감소)
MIN_SWINGS      = 3
MAX_GRID_STEPS  = 4
QTY_RATIOS      = [1, 2, 3, 4]

MIN_GRID_PCT    = 10.0    # ★ v1.1: 3.0 → 10.0 (너무 촘촘한 격자 방지)
MAX_GRID_PCT    = 30.0    # ★ v1.1: 25.0 → 30.0 (고변동성 종목 상한 확대)
ATR_MULT        = 2.0     # ★ v1.1: 1.5 → 2.0 (격자 여유 확대)

START_TIME = time.time()


def fetch_ohlcv(ticker, end_date):
    try:
        start = (end_date - timedelta(days=LOOKBACK_DAYS * 2)).strftime("%Y-%m-%d")
        df    = fdr.DataReader(ticker, start, end_date.strftime("%Y-%m-%d"))
        if df is None or len(df) < 30: return None
        return df.sort_index().tail(LOOKBACK_DAYS)
    except:
        return None


def calc_swing_analysis(df):
    try:
        close = df["Close"].values
        if SCIPY_AVAILABLE:
            low_peaks,  _ = find_peaks(-close, distance=SWING_DISTANCE, prominence=close.mean() * 0.02)
            high_peaks, _ = find_peaks( close, distance=SWING_DISTANCE, prominence=close.mean() * 0.02)
        else:
            w = SWING_DISTANCE
            low_peaks  = np.array([i for i in range(w, len(close)-w) if close[i] == min(close[i-w:i+w+1])])
            high_peaks = np.array([i for i in range(w, len(close)-w) if close[i] == max(close[i-w:i+w+1])])

        if len(low_peaks) < MIN_SWINGS or len(high_peaks) < MIN_SWINGS:
            return {"amplitude_pct": 15.0, "cycle_days": 20, "swing_count": 0, "reliability": "LOW", "low_peaks": np.array([])}

        amplitudes = []
        for lp in low_peaks:
            nearest_hp = high_peaks[np.argmin(np.abs(high_peaks - lp))]
            amp = abs(close[nearest_hp] - close[lp]) / close[lp] * 100
            if 1.0 < amp < 60.0:
                amplitudes.append(amp)

        cycles = [low_peaks[i] - low_peaks[i-1] for i in range(1, len(low_peaks))]

        return {
            "amplitude_pct": round(float(np.median(amplitudes)), 2) if amplitudes else 15.0,
            "cycle_days":    int(np.median(cycles)) if cycles else 20,
            "swing_count":   min(len(amplitudes), len(cycles)),
            "reliability":   "HIGH" if min(len(amplitudes), len(cycles)) >= 5 else
                             "MED"  if min(len(amplitudes), len(cycles)) >= MIN_SWINGS else "LOW",
            "low_peaks":     low_peaks,
        }
    except Exception as e:
        logging.debug(f"swing_analysis error: {e}")
        return {"amplitude_pct": 15.0, "cycle_days": 20, "swing_count": 0, "reliability": "LOW", "low_peaks": np.array([])}


def calc_atr(df, period=14):
    try:
        h, l, c = df["High"], df["Low"], df["Close"]
        tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
        return float(tr.rolling(period).mean().iloc[-1])
    except:
        return float(df["Close"].std())


def calc_phase(df, swing_data):
    try:
        close   = df["Close"].values
        current = close[-1]
        recent  = close[-30:]
        r_high, r_low = recent.max(), recent.min()
        r_range = r_high - r_low

        if r_range == 0:
            return {"phase": "FLAT", "phase_pct": 50.0, "days_since_low": 0,
                    "est_days_to_bottom": 0, "recent_high": r_high, "recent_low": r_low}

        phase_pct = (current - r_low) / r_range * 100
        if   phase_pct <= 20: phase = "BOTTOM_ZONE"
        elif phase_pct <= 40: phase = "LOWER_MID"
        elif phase_pct <= 60: phase = "MID_ZONE"
        elif phase_pct <= 80: phase = "UPPER_MID"
        else:                 phase = "TOP_ZONE"

        low_peaks      = swing_data.get("low_peaks", np.array([]))
        days_since_low = int(len(close) - low_peaks[-1]) if len(low_peaks) > 0 else 0
        cycle          = swing_data.get("cycle_days", 20)
        est_bottom     = max(0, cycle - days_since_low)

        return {
            "phase": phase, "phase_pct": round(phase_pct, 1),
            "days_since_low": days_since_low, "est_days_to_bottom": est_bottom,
            "recent_high": round(float(r_high), 0), "recent_low": round(float(r_low), 0),
        }
    except Exception as e:
        logging.debug(f"calc_phase error: {e}")
        return {"phase": "UNKNOWN", "phase_pct": 50.0, "days_since_low": 0,
                "est_days_to_bottom": 0, "recent_high": 0, "recent_low": 0}


def calc_grid(current_price, amplitude_pct, atr, phase_data, base_price=None):
    atr_pct  = atr / current_price * 100
    # ★ v1.1: ATR_MULT 2.0 적용
    grid_pct = max(amplitude_pct / MAX_GRID_STEPS, atr_pct * ATR_MULT)
    grid_pct = round(max(MIN_GRID_PCT, min(MAX_GRID_PCT, grid_pct)), 1)
    anchor   = base_price if base_price else current_price

    buy_levels  = []
    sell_levels = []

    for step in range(1, MAX_GRID_STEPS + 1):
        tprice = round(anchor * (1 + (-grid_pct * step) / 100))
        status = "ACTIVE"  if abs(current_price - tprice) / tprice < 0.02 else \
                 "NEAR"    if current_price <= tprice * 1.05 else "PENDING"
        buy_levels.append({"step": step, "trigger_pct": -grid_pct * step,
                            "trigger_price": tprice, "qty_ratio": QTY_RATIOS[step-1], "status": status})
        sell_levels.append({"step": step, "target_pct": grid_pct * step,
                             "target_price": round(anchor * (1 + (grid_pct * step) / 100))})

    phase    = phase_data.get("phase", "UNKNOWN")
    est_days = phase_data.get("est_days_to_bottom", 99)
    near     = [l for l in buy_levels if l["status"] in ["ACTIVE", "NEAR"]]

    if   phase == "BOTTOM_ZONE" and near:                             action = f"BUY_NOW_STEP{near[0]['step']}"
    elif phase in ["BOTTOM_ZONE", "LOWER_MID"] and est_days <= 3:    action = "BUY_SOON"
    elif phase == "LOWER_MID"   and near:                             action = f"BUY_READY_STEP{near[0]['step']}"
    elif phase in ["TOP_ZONE", "UPPER_MID"]:                          action = "SELL_ZONE"
    else:                                                              action = "HOLD_WATCH"

    return {"grid_pct": grid_pct, "buy_levels": buy_levels, "sell_levels": sell_levels, "action": action}


def analyze_ticker_oscillation(ticker, end_date, base_price=None):
    df = fetch_ohlcv(ticker, end_date)
    if df is None: return None

    try:
        current   = float(df["Close"].iloc[-1])
        swing     = calc_swing_analysis(df)
        atr_val   = calc_atr(df)
        phase     = calc_phase(df, swing)
        grid      = calc_grid(current, swing["amplitude_pct"], atr_val, phase, base_price)

        bl = grid["buy_levels"]
        sl = grid["sell_levels"]
        return {
            "ticker":             ticker.zfill(6),
            "current_price":      round(current, 0),
            "base_price":         round(base_price, 0) if base_price else round(current, 0),
            "amplitude_pct":      swing["amplitude_pct"],
            "cycle_days":         swing["cycle_days"],
            "swing_count":        swing["swing_count"],
            "reliability":        swing["reliability"],
            "atr_pct":            round(atr_val / current * 100, 2),
            "phase":              phase["phase"],
            "phase_pct":          phase["phase_pct"],
            "days_since_low":     phase["days_since_low"],
            "est_days_to_bottom": phase["est_days_to_bottom"],
            "recent_high":        phase.get("recent_high", 0),
            "recent_low":         phase.get("recent_low", 0),
            "grid_pct":           grid["grid_pct"],
            "action":             grid["action"],
            "buy_step1_price":    bl[0]["trigger_price"], "buy_step1_status": bl[0]["status"],
            "buy_step2_price":    bl[1]["trigger_price"], "buy_step2_status": bl[1]["status"],
            "buy_step3_price":    bl[2]["trigger_price"], "buy_step3_status": bl[2]["status"],
            "buy_step4_price":    bl[3]["trigger_price"], "buy_step4_status": bl[3]["status"],
            "sell_step1_price":   sl[0]["target_price"],
            "sell_step2_price":   sl[1]["target_price"],
        }
    except Exception as e:
        logging.debug(f"analyze {ticker} error: {e}")
        return None


def load_portfolio_tickers():
    if os.path.exists(PORTFOLIO_JSON):
        try:
            with open(PORTFOLIO_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            result = []
            for h in data.get("holdings", []):
                ticker = str(h.get("ticker", "")).zfill(6)
                ws     = h.get("web_strategy", {})
                bp     = ws.get("base_price") or (h.get("positions", [{}])[0].get("price") if h.get("positions") else None)
                if ticker and ticker != "000000":
                    result.append({"ticker": ticker, "name": h.get("name", ""), "base_price": bp})
            logging.info(f"portfolio.json: {len(result)} holdings")
            return result
        except Exception as e:
            logging.warning(f"portfolio.json failed: {e}")

    signal_csv = os.path.join(LATEST_DIR, "sfd_master_signal_latest.csv")
    if os.path.exists(signal_csv):
        df  = pd.read_csv(signal_csv, encoding="utf-8-sig", dtype={"ticker": str})
        top = df.head(20)[["ticker", "name"]].to_dict("records")
        for r in top: r["base_price"] = None
        return top
    return []


def find_recent_trade_date():
    now = datetime.now()
    for i in range(7):
        d = now - timedelta(days=i)
        if d.weekday() >= 5: continue
        try:
            df = fdr.DataReader("005930", d.strftime("%Y-%m-%d"), d.strftime("%Y-%m-%d"))
            if df is not None and len(df) > 0: return d
        except: pass
    return now


def main():
    logging.info("=== sfd_oscillation_analyzer v1.1 START ===")
    logging.info(f"SCIPY: {SCIPY_AVAILABLE}")
    logging.info(f"GRID PARAMS: MIN={MIN_GRID_PCT}% MAX={MAX_GRID_PCT}% ATR_MULT={ATR_MULT} SWING_DIST={SWING_DISTANCE}")

    end_date = find_recent_trade_date()
    holdings = load_portfolio_tickers()

    if not holdings:
        logging.error("No tickers. Abort.")
        sys.exit(1)

    logging.info(f"Tickers: {len(holdings)} | date: {end_date.strftime('%Y%m%d')}")

    results = []
    alerts  = []

    for h in holdings:
        row = analyze_ticker_oscillation(h["ticker"], end_date, h.get("base_price"))
        if not row:
            logging.warning(f"  SKIP: {h['ticker']}")
            continue
        row["name"] = h.get("name", "")
        results.append(row)

        if row["action"] not in ["HOLD_WATCH", "SELL_ZONE"]:
            alerts.append(row)

        logging.info(
            f"  {h['ticker']} | {row['phase']:12s} | amp={row['amplitude_pct']}% "
            f"| cycle={row['cycle_days']}d | grid={row['grid_pct']}% | {row['action']}"
        )

    if results:
        cols_drop = ["low_peaks", "_grid_detail"]
        df_out = pd.DataFrame(results).drop(columns=cols_drop, errors="ignore")
        df_out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
        df_out.to_csv(os.path.join(HISTORY_DIR, f"sfd_oscillation_{end_date.strftime('%Y%m%d')}.csv"),
                      index=False, encoding="utf-8-sig")

    if alerts:
        pd.DataFrame(alerts).drop(columns=["low_peaks", "_grid_detail"], errors="ignore")\
          .to_csv(GRID_SIGNAL_CSV, index=False, encoding="utf-8-sig")

    elapsed = int(time.time() - START_TIME)
    logging.info(f"DONE | analyzed={len(results)} alerts={len(alerts)} elapsed={elapsed}s")
    print(f"[OK] oscillation v1.1 | analyzed={len(results)} | alerts={len(alerts)} | elapsed={elapsed}s")

    if alerts:
        print(f"\n{'='*70}")
        print(f"[거미줄 알림] {len(alerts)}건 신호")
        for a in alerts:
            print(f"  [{a['action']:25s}] {a['ticker']} {a.get('name',''):12s} | "
                  f"현재가={a['current_price']:>8,} | 기준가={a['base_price']:>8,} | "
                  f"격자={a['grid_pct']}% | 진폭={a['amplitude_pct']}% | "
                  f"저점예상≈{a['est_days_to_bottom']}일")
        print(f"{'='*70}")

    print(f"  -> {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
