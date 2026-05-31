# sfd_oscillation_analyzer.py | v1.2 | Layer 2.8 | Claude (Anthropic) 2026-06-01
# Deploy to: sfd-pipeline/tools/sfd_oscillation_analyzer.py
#
# [v1.1 → v1.2 변경사항]
# - [BM-12] ZONE_PULLBACK ATR 기반 눌림목 감지 추가
#   calc_zone_pullback(df, atr) → zone_pullback_score (0~15pt), zone_pullback_label
#
#   로직:
#     1) 직전 스윙 고점 탐색 (lookback 30봉 내)
#     2) 현재가가 직전 고점 대비 1~2 ATR 이내 되돌림 → PULLBACK_1ATR / PULLBACK_2ATR
#     3) phase가 LOWER_MID 또는 BOTTOM_ZONE → 점수 상향
#     4) 거래량 확인 (vol < vol_avg × 0.8) → 저거래량 눌림목 가산점
#
#   score 체계:
#     PULLBACK_1ATR + LOWER_MID/BOTTOM_ZONE + 저거래량 → 15pt (최고)
#     PULLBACK_1ATR + LOWER_MID/BOTTOM_ZONE              → 12pt
#     PULLBACK_2ATR + LOWER_MID/BOTTOM_ZONE              → 8pt
#     PULLBACK_1ATR + MID_ZONE                           → 5pt
#     그 외 눌림목 없음                                   → 0pt
#
#   출력 컬럼: zone_pullback_score, zone_pullback_label
#   출력 파일: sfd_oscillation_latest.csv에 컬럼 추가
#              sfd_zone_pullback_latest.csv (점수 > 0 종목만 별도 저장)
#
# [v1.1 변경사항] (유지)
#   MIN_GRID_PCT: 10.0, MAX_GRID_PCT: 30.0, ATR_MULT: 2.0, SWING_DISTANCE: 7

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

PORTFOLIO_JSON      = os.path.join(DATA_DIR,    "portfolio.json")
OUTPUT_CSV          = os.path.join(LATEST_DIR,  "sfd_oscillation_latest.csv")
GRID_SIGNAL_CSV     = os.path.join(LATEST_DIR,  "sfd_grid_signal_latest.csv")
ZONE_PULLBACK_CSV   = os.path.join(LATEST_DIR,  "sfd_zone_pullback_latest.csv")  # ★ BM-12
LOG_PATH            = os.path.join(LATEST_DIR,  "sfd_oscillation_analyzer.log")

logging.basicConfig(
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

# ── 파라미터 (★ v1.1 튜닝 유지, v1.2 BM-12 추가) ──────────────────────────
LOOKBACK_DAYS    = 120
ATR_PERIOD       = 14
SWING_DISTANCE   = 7        # ★ v1.1: 5→7
MIN_SWINGS       = 3
MAX_GRID_STEPS   = 4
QTY_RATIOS       = [1, 2, 3, 4]

MIN_GRID_PCT     = 10.0     # ★ v1.1: 3.0→10.0
MAX_GRID_PCT     = 30.0     # ★ v1.1: 25.0→30.0
ATR_MULT         = 2.0      # ★ v1.1: 1.5→2.0

# [BM-12] ZONE_PULLBACK 파라미터
ZP_LOOKBACK_BARS = 30       # 직전 고점 탐색 구간 (봉)
ZP_ATR_NEAR_1    = 1.0      # 1 ATR 이내 = 근접 눌림목
ZP_ATR_NEAR_2    = 2.0      # 2 ATR 이내 = 중간 눌림목
ZP_VOL_QUIET     = 0.8      # 저거래량 임계 (vol_avg의 80% 이하 = 조용한 눌림목)

START_TIME = time.time()


# ── OHLCV 로드 ────────────────────────────────────────────────────────────────
def fetch_ohlcv(ticker, end_date):
    try:
        start = (end_date - timedelta(days=LOOKBACK_DAYS * 2)).strftime("%Y-%m-%d")
        df    = fdr.DataReader(ticker, start, end_date.strftime("%Y-%m-%d"))
        if df is None or len(df) < 30: return None
        return df.sort_index().tail(LOOKBACK_DAYS)
    except:
        return None


# ── 스윙 분석 ─────────────────────────────────────────────────────────────────
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
            return {"amplitude_pct": 15.0, "cycle_days": 20, "swing_count": 0,
                    "reliability": "LOW", "low_peaks": np.array([]), "high_peaks": high_peaks if len(high_peaks) > 0 else np.array([])}

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
            "high_peaks":    high_peaks,
        }
    except Exception as e:
        logging.debug(f"swing_analysis error: {e}")
        return {"amplitude_pct": 15.0, "cycle_days": 20, "swing_count": 0,
                "reliability": "LOW", "low_peaks": np.array([]), "high_peaks": np.array([])}


# ── ATR 계산 ──────────────────────────────────────────────────────────────────
def calc_atr(df, period=14):
    try:
        h, l, c = df["High"], df["Low"], df["Close"]
        tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
        return float(tr.rolling(period).mean().iloc[-1])
    except:
        return float(df["Close"].std())


# ── Phase 계산 ────────────────────────────────────────────────────────────────
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


# ── [BM-12] ZONE_PULLBACK 계산 ────────────────────────────────────────────────
def calc_zone_pullback(df, atr_val, phase_data, swing_data) -> dict:
    """
    ATR 기반 눌림목 감지 (BM-12 ZONE_PULLBACK)

    알고리즘:
      1) 최근 ZP_LOOKBACK_BARS 봉에서 직전 스윙 고점 탐색
      2) 현재가가 직전 고점 대비 1~2 ATR 이내 되돌림 여부 판정
      3) phase + 저거래량 여부로 점수 결정

    Returns:
      {
        "zone_pullback_score": 0~15,
        "zone_pullback_label": str,
        "zp_swing_high": float,        # 직전 스윙 고점 가격
        "zp_distance_atr": float,      # 고점 대비 현재가 거리 (ATR 배수)
        "zp_vol_quiet": bool,          # 저거래량 여부
      }
    """
    try:
        close  = df["Close"].values
        volume = df["Volume"].values if "Volume" in df.columns else None
        n      = len(close)
        current = close[-1]
        phase   = phase_data.get("phase", "UNKNOWN")

        if atr_val <= 0 or current <= 0:
            return {"zone_pullback_score": 0, "zone_pullback_label": "NO_DATA",
                    "zp_swing_high": 0.0, "zp_distance_atr": 0.0, "zp_vol_quiet": False}

        # 직전 스윙 고점 탐색 (최근 ZP_LOOKBACK_BARS 봉)
        lookback_start = max(0, n - ZP_LOOKBACK_BARS - 1)
        recent_close   = close[lookback_start:-1]  # 현재봉 제외

        swing_high = float(np.max(recent_close)) if len(recent_close) > 0 else 0.0

        if swing_high <= 0 or swing_high <= current:
            # 현재가가 고점 이상 → 눌림목 없음
            return {"zone_pullback_score": 0, "zone_pullback_label": "ABOVE_SWING_HIGH",
                    "zp_swing_high": round(swing_high, 0), "zp_distance_atr": 0.0, "zp_vol_quiet": False}

        # 고점 대비 현재가 거리 (ATR 배수)
        distance      = swing_high - current
        distance_atr  = round(distance / atr_val, 2)

        # 저거래량 판정
        vol_quiet = False
        if volume is not None and len(volume) >= 20:
            vol_avg   = float(np.mean(volume[-20:]))
            vol_cur   = float(volume[-1])
            vol_quiet = (vol_cur < vol_avg * ZP_VOL_QUIET) if vol_avg > 0 else False

        # phase 분류
        phase_is_low = phase in ("BOTTOM_ZONE", "LOWER_MID")
        phase_is_mid = phase == "MID_ZONE"

        # score 결정
        if distance_atr <= ZP_ATR_NEAR_1:
            # 1 ATR 이내 = 근접 눌림목
            if phase_is_low and vol_quiet:
                score = 15
                label = "PULLBACK_1ATR_LOW_QUIET"
            elif phase_is_low:
                score = 12
                label = "PULLBACK_1ATR_LOW"
            elif phase_is_mid:
                score = 5
                label = "PULLBACK_1ATR_MID"
            else:
                score = 3
                label = "PULLBACK_1ATR_HIGH"
        elif distance_atr <= ZP_ATR_NEAR_2:
            # 1~2 ATR 이내 = 중간 눌림목
            if phase_is_low and vol_quiet:
                score = 10
                label = "PULLBACK_2ATR_LOW_QUIET"
            elif phase_is_low:
                score = 8
                label = "PULLBACK_2ATR_LOW"
            elif phase_is_mid:
                score = 4
                label = "PULLBACK_2ATR_MID"
            else:
                score = 2
                label = "PULLBACK_2ATR_HIGH"
        else:
            # 2 ATR 초과 = 눌림목 아님 (단순 하락)
            score = 0
            label = "NO_PULLBACK"

        return {
            "zone_pullback_score": score,
            "zone_pullback_label": label,
            "zp_swing_high":       round(swing_high, 0),
            "zp_distance_atr":     distance_atr,
            "zp_vol_quiet":        vol_quiet,
        }

    except Exception as e:
        logging.debug(f"calc_zone_pullback error: {e}")
        return {"zone_pullback_score": 0, "zone_pullback_label": "ERROR",
                "zp_swing_high": 0.0, "zp_distance_atr": 0.0, "zp_vol_quiet": False}


# ── 격자 계산 ─────────────────────────────────────────────────────────────────
def calc_grid(current_price, amplitude_pct, atr, phase_data, base_price=None):
    atr_pct  = atr / current_price * 100
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

    if   phase == "BOTTOM_ZONE" and near:                          action = f"BUY_NOW_STEP{near[0]['step']}"
    elif phase in ["BOTTOM_ZONE", "LOWER_MID"] and est_days <= 3: action = "BUY_SOON"
    elif phase == "LOWER_MID"   and near:                          action = f"BUY_READY_STEP{near[0]['step']}"
    elif phase in ["TOP_ZONE", "UPPER_MID"]:                       action = "SELL_ZONE"
    else:                                                           action = "HOLD_WATCH"

    return {"grid_pct": grid_pct, "buy_levels": buy_levels, "sell_levels": sell_levels, "action": action}


# ── 종목 분석 (메인 함수) ──────────────────────────────────────────────────────
def analyze_ticker_oscillation(ticker, end_date, base_price=None):
    df = fetch_ohlcv(ticker, end_date)
    if df is None: return None

    try:
        current   = float(df["Close"].iloc[-1])
        swing     = calc_swing_analysis(df)
        atr_val   = calc_atr(df)
        phase     = calc_phase(df, swing)
        grid      = calc_grid(current, swing["amplitude_pct"], atr_val, phase, base_price)
        # ★ [BM-12] ZONE_PULLBACK
        zp        = calc_zone_pullback(df, atr_val, phase, swing)

        bl = grid["buy_levels"]
        sl = grid["sell_levels"]
        return {
            "ticker":              ticker.zfill(6),
            "current_price":       round(current, 0),
            "base_price":          round(base_price, 0) if base_price else round(current, 0),
            "amplitude_pct":       swing["amplitude_pct"],
            "cycle_days":          swing["cycle_days"],
            "swing_count":         swing["swing_count"],
            "reliability":         swing["reliability"],
            "atr_pct":             round(atr_val / current * 100, 2),
            "phase":               phase["phase"],
            "phase_pct":           phase["phase_pct"],
            "days_since_low":      phase["days_since_low"],
            "est_days_to_bottom":  phase["est_days_to_bottom"],
            "recent_high":         phase.get("recent_high", 0),
            "recent_low":          phase.get("recent_low", 0),
            "grid_pct":            grid["grid_pct"],
            "action":              grid["action"],
            "buy_step1_price":     bl[0]["trigger_price"], "buy_step1_status": bl[0]["status"],
            "buy_step2_price":     bl[1]["trigger_price"], "buy_step2_status": bl[1]["status"],
            "buy_step3_price":     bl[2]["trigger_price"], "buy_step3_status": bl[2]["status"],
            "buy_step4_price":     bl[3]["trigger_price"], "buy_step4_status": bl[3]["status"],
            "sell_step1_price":    sl[0]["target_price"],
            "sell_step2_price":    sl[1]["target_price"],
            # ★ [BM-12] ZONE_PULLBACK 컬럼
            "zone_pullback_score": zp["zone_pullback_score"],
            "zone_pullback_label": zp["zone_pullback_label"],
            "zp_swing_high":       zp["zp_swing_high"],
            "zp_distance_atr":     zp["zp_distance_atr"],
            "zp_vol_quiet":        zp["zp_vol_quiet"],
        }
    except Exception as e:
        logging.debug(f"analyze {ticker} error: {e}")
        return None


# ── 포트폴리오 로드 ───────────────────────────────────────────────────────────
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


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    logging.info("=== sfd_oscillation_analyzer v1.2 START ===")
    logging.info(f"SCIPY: {SCIPY_AVAILABLE}")
    logging.info(f"GRID PARAMS: MIN={MIN_GRID_PCT}% MAX={MAX_GRID_PCT}% ATR_MULT={ATR_MULT} SWING_DIST={SWING_DISTANCE}")
    logging.info(f"[BM-12] ZONE_PULLBACK: lookback={ZP_LOOKBACK_BARS}봉 ATR_1={ZP_ATR_NEAR_1} ATR_2={ZP_ATR_NEAR_2} VOL_QUIET={ZP_VOL_QUIET}")

    end_date = find_recent_trade_date()
    holdings = load_portfolio_tickers()

    if not holdings:
        logging.error("No tickers. Abort.")
        sys.exit(1)

    logging.info(f"Tickers: {len(holdings)} | date: {end_date.strftime('%Y%m%d')}")

    results       = []
    grid_alerts   = []
    zp_alerts     = []  # ★ BM-12

    for h in holdings:
        row = analyze_ticker_oscillation(h["ticker"], end_date, h.get("base_price"))
        if not row:
            logging.warning(f"  SKIP: {h['ticker']}")
            continue
        row["name"] = h.get("name", "")
        results.append(row)

        if row["action"] not in ["HOLD_WATCH", "SELL_ZONE"]:
            grid_alerts.append(row)

        # ★ [BM-12] ZONE_PULLBACK 알림 대상
        if row["zone_pullback_score"] >= 5:
            zp_alerts.append(row)

        logging.info(
            f"  {h['ticker']} | {row['phase']:12s} | amp={row['amplitude_pct']}% "
            f"| cycle={row['cycle_days']}d | grid={row['grid_pct']}% | {row['action']}"
            f" | ZP={row['zone_pullback_score']}pt({row['zone_pullback_label']})"
        )

    if results:
        cols_drop = ["low_peaks", "high_peaks", "_grid_detail"]
        df_out = pd.DataFrame(results).drop(columns=cols_drop, errors="ignore")
        df_out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
        df_out.to_csv(
            os.path.join(HISTORY_DIR, f"sfd_oscillation_{end_date.strftime('%Y%m%d')}.csv"),
            index=False, encoding="utf-8-sig"
        )

    if grid_alerts:
        pd.DataFrame(grid_alerts).drop(columns=["low_peaks", "high_peaks", "_grid_detail"], errors="ignore")\
          .to_csv(GRID_SIGNAL_CSV, index=False, encoding="utf-8-sig")

    # ★ [BM-12] ZONE_PULLBACK 결과 별도 저장
    if zp_alerts:
        zp_df = pd.DataFrame(zp_alerts)[
            ["ticker", "name", "current_price", "phase", "phase_pct",
             "zone_pullback_score", "zone_pullback_label",
             "zp_swing_high", "zp_distance_atr", "zp_vol_quiet",
             "atr_pct", "reliability"]
        ].sort_values("zone_pullback_score", ascending=False)
        zp_df.to_csv(ZONE_PULLBACK_CSV, index=False, encoding="utf-8-sig")

    elapsed = int(time.time() - START_TIME)
    logging.info(
        f"DONE | analyzed={len(results)} grid_alerts={len(grid_alerts)} "
        f"zp_alerts={len(zp_alerts)} elapsed={elapsed}s"
    )
    print(
        f"[OK] oscillation v1.2 | analyzed={len(results)} | "
        f"grid_alerts={len(grid_alerts)} | [BM-12]zp={len(zp_alerts)} | elapsed={elapsed}s"
    )

    if zp_alerts:
        print(f"\n{'='*70}")
        print(f"[BM-12 ZONE_PULLBACK] {len(zp_alerts)}건 눌림목 감지")
        for a in sorted(zp_alerts, key=lambda x: -x["zone_pullback_score"]):
            print(
                f"  [{a['zone_pullback_label']:30s}] {a['ticker']} {a.get('name',''):12s} | "
                f"현재가={a['current_price']:>8,} | 직전고점={a['zp_swing_high']:>8,.0f} | "
                f"거리={a['zp_distance_atr']:.1f}ATR | ZP={a['zone_pullback_score']}pt | "
                f"저거래량={'Y' if a['zp_vol_quiet'] else 'N'}"
            )
        print(f"{'='*70}")

    if grid_alerts:
        print(f"\n{'='*70}")
        print(f"[격자매매 신호] {len(grid_alerts)}건")
        for a in grid_alerts:
            print(
                f"  [{a['action']:25s}] {a['ticker']} {a.get('name',''):12s} | "
                f"현재가={a['current_price']:>8,} | 매수가={a['base_price']:>8,} | "
                f"격자={a['grid_pct']}% | 진폭={a['amplitude_pct']}% | "
                f"저점예측≈{a['est_days_to_bottom']}일\n"
            )
        print(f"{'='*70}")

    print(f"  -> {OUTPUT_CSV}")
    if zp_alerts:
        print(f"  -> {ZONE_PULLBACK_CSV}")


if __name__ == "__main__":
    main()
