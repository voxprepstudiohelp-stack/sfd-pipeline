# sfd_technical_analyzer.py | v1.6 | Layer 2.7 | Claude (Anthropic) 2026-06-15
# Deploy to: SFC_DataPipeline/tools/sfd_technical_analyzer.py
#
# [스코어 아키텍처] tech_total_score (max 98pt ★ v1.6)
#   [A] Volume Profile POC+VAH+VAL   : 0~20pt  ★ v1.6 BM-20 교체
#   [B] Support/Resistance            : 0~10pt
#   [C] RSI                           : 0~5pt
#   [D] MA 정배열                     : 0~10pt
#   [E] Volume Gap Score              : 0~15pt
#   [F] Standard Bar Score            : 0~10pt
#   [G] Pullback Zone Score           : 0~10pt
#   [H] Volume Surge Score (BM-10)    : 0~10pt
#   [I] MA60 Direction (BM-2)         : 0~8pt
#   [J] cap_trust 보정 (P_NEW_2)      : 승수 보정
#
# [v1.6] calc_poc_score(0~15) → calc_vp_score(0~20) BM-20 교체
#         VAH돌파20pt / VAH근접15pt / VA내8pt / VAL근접5pt / 이탈0pt / POC재접근+3pt
# [v1.5] cap_trust_factor (P_NEW_2) / DXY=F→DX-Y.NYB (P3)
# [v1.4] MA60 Direction BM-2
# [v1.3] Volume Surge BM-10
# [v1.2] Pullback Zone Score

import os, sys, time, logging
from datetime import datetime
import pandas as pd
import numpy as np
from sfd_ohlcv_store import load_ohlcv

try:
    from scipy.signal import find_peaks
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

_env_base = os.environ.get("SFD_BASE_DIR", "")
BASE_DIR  = _env_base if _env_base and os.path.isdir(_env_base) else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LATEST_DIR  = os.path.join(BASE_DIR, "outputs", "latest")
HISTORY_DIR = os.path.join(BASE_DIR, "outputs", "history")
INPUT_DIR   = os.path.join(BASE_DIR, "inputs")
os.makedirs(LATEST_DIR,  exist_ok=True)
os.makedirs(HISTORY_DIR, exist_ok=True)

INPUT_CSV  = os.path.join(INPUT_DIR,  "sfd_master_signal_input.csv")
OUTPUT_CSV = os.path.join(LATEST_DIR, "sfd_technical_latest.csv")
LOG_PATH   = os.path.join(LATEST_DIR, "sfd_technical_analyzer.log")

logging.basicConfig(
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s",
)

# ── 파라미터
LOOKBACK_DAYS = 60
MA_PERIODS    = [5, 10, 20, 60, 120]
RSI_PERIOD    = 14
VOL_BINS      = 20
SWING_DISTANCE = 5

VOL_GAP_BOTTOM_PCT = 0.20
VOL_GAP_TOP_PCT    = 0.20

STD_BAR_BODY_PCT     = 0.03
STD_BAR_VOL_MULT     = 1.5
STD_BAR_BREAKOUT_WIN = 20
STD_BAR_LOOKBACK     = 5

PB_LOOKBACK_HIGH    = 20
PB_DROP_MIN_PCT     = 3.0
PB_DROP_MAX_PCT     = 15.0
PB_VOL_SHRINK_RATIO = 0.7
PB_MA_ALIGN_REQ     = True

MA60_DIR_LOOKBACK    = 5
MA60_DIR_RISING_STR  = 0.5
MA60_DIR_RISING_MILD = 0.1
MA60_DIR_FLAT_LOW    = -0.1

DXY_SYMBOL = "DX-Y.NYB"   # P3: DXY=F → DX-Y.NYB

# ★ BM-20 파라미터
VA_PERCENT_BM20   = 0.70
VOL_BINS_BM20     = 30
VAH_NEAR_PCT_BM20 = 2.0
VAL_NEAR_PCT_BM20 = 2.0
POC_NEAR_PCT_BM20 = 1.0

START_TIME = time.time()
MARKET_CAP_MAP = {}


# ── [A] Volume Profile BM-20 (0~20pt) ★ v1.6 ────────────────────────────────
def _calc_vp_raw(df: pd.DataFrame) -> dict:
    """POC / VAH / VAL 원시 계산 (TV 표준 방식, 70% Value Area)"""
    try:
        close, volume = df["Close"].values, df["Volume"].values
        if len(close) < 10: return {}
        pmin, pmax = close.min(), close.max()
        if pmax == pmin: return {}

        bins        = np.linspace(pmin, pmax, VOL_BINS_BM20 + 1)
        bin_centers = (bins[:-1] + bins[1:]) / 2
        bin_idx     = np.clip(np.digitize(close, bins) - 1, 0, VOL_BINS_BM20 - 1)
        vol_by_bin  = np.zeros(VOL_BINS_BM20)
        for i, v in zip(bin_idx, volume): vol_by_bin[i] += v

        total_vol = vol_by_bin.sum()
        if total_vol == 0: return {}

        poc_bin = int(np.argmax(vol_by_bin))

        # Value Area 확장 (POC 기준 위/아래로 거래량 많은 쪽 우선)
        va_vol, va_target = vol_by_bin[poc_bin], total_vol * VA_PERCENT_BM20
        ai, bi, vh, vl   = poc_bin + 1, poc_bin - 1, poc_bin, poc_bin

        while va_vol < va_target:
            aa = vol_by_bin[ai] if ai < VOL_BINS_BM20 else 0
            ab = vol_by_bin[bi] if bi >= 0             else 0
            if aa == 0 and ab == 0: break
            if aa >= ab: va_vol += aa; vh = ai; ai += 1
            else:        va_vol += ab; vl = bi; bi -= 1

        poc = round(float(bin_centers[poc_bin]), 0)
        return {
            "poc_price":    poc,
            "vah_price":    round(float(bin_centers[vh]), 0),
            "val_price":    round(float(bin_centers[vl]), 0),
            "va_width_pct": round((float(bin_centers[vh]) - float(bin_centers[vl])) / poc * 100, 2),
        }
    except Exception as e:
        logging.debug(f"_calc_vp_raw error: {e}")
        return {}


def calc_vp_score(df: pd.DataFrame) -> tuple:
    """
    [BM-20] Volume Profile 점수 (0~20pt)
    Returns: (score, poc_price, vah_price, val_price, vp_label, va_width_pct, vp_position)
    """
    try:
        vp = _calc_vp_raw(df)
        if not vp:
            return 0, 0.0, 0.0, 0.0, "insufficient", 0.0, "unknown"

        poc, vah, val = vp["poc_price"], vp["vah_price"], vp["val_price"]
        va_w          = vp["va_width_pct"]
        cur           = float(df["Close"].values[-1])

        vah_near_lo = vah * (1 - VAH_NEAR_PCT_BM20 / 100)
        val_near_hi = val * (1 + VAL_NEAR_PCT_BM20 / 100)
        poc_hi      = poc * (1 + POC_NEAR_PCT_BM20 / 100)
        poc_lo      = poc * (1 - POC_NEAR_PCT_BM20 / 100)

        # POC 재접근 보너스
        ca = df["Close"].values
        poc_bonus = 3 if (len(ca) >= 4 and poc_lo <= ca[-4:-1].min() <= poc_hi and cur > poc) else 0

        if cur > vah:
            pct = (cur - vah) / vah * 100
            if pct <= 3.0:   sc, lb, ps = 20, "vah_breakout_fresh",    "above_vah"
            elif pct <= 8.0: sc, lb, ps = 16, "vah_breakout_extended", "above_vah"
            else:            sc, lb, ps = 12, "vah_breakout_far",      "above_vah"
        elif vah_near_lo <= cur <= vah:
            sc, lb, ps = 15, "near_vah_testing", "near_vah"
        elif val < cur < vah:
            if poc_lo <= cur <= poc_hi:
                sc, lb, ps = 10, "at_poc", "at_poc"
            else:
                pct_va = (cur - val) / (vah - val + 1e-9) * 100
                if pct_va >= 60:   sc, lb, ps = 10, "in_va_upper", "in_va"
                elif pct_va >= 40: sc, lb, ps = 8,  "in_va_mid",   "in_va"
                else:              sc, lb, ps = 6,  "in_va_lower", "in_va"
        elif val <= cur <= val_near_hi:
            sc, lb, ps = 5, "near_val_support", "near_val"
        else:
            pct_bv = (val - cur) / val * 100 if val > 0 else 0
            sc, lb, ps = (2, "below_val_slight", "below_val") if pct_bv <= 3.0 else (0, "below_val_broken", "below_val")

        final = min(sc + poc_bonus, 20)
        if poc_bonus: lb += "_poc_revisit"
        return final, round(poc, 0), round(vah, 0), round(val, 0), lb, va_w, ps

    except Exception as e:
        logging.debug(f"calc_vp_score error: {e}")
        return 0, 0.0, 0.0, 0.0, "error", 0.0, "error"


# ── [B] Support/Resistance 점수 (0~10) ───────────────────────────────────────
def calc_sr_score(df: pd.DataFrame) -> tuple:
    try:
        close, current = df["Close"].values, df["Close"].values[-1]
        if SCIPY_AVAILABLE:
            peaks, _ = find_peaks(-close, distance=SWING_DISTANCE, prominence=current * 0.01)
            sl = close[peaks] if len(peaks) > 0 else np.array([])
        else:
            sl = np.array([close[i] for i in range(5, len(close)-5) if close[i] == min(close[i-5:i+6])])

        sb = sl[sl < current]
        if len(sb) == 0: return 0, 0.0, 0.0
        ns  = sb.max()
        gap = (current - ns) / ns * 100
        sc  = 10 if gap <= 2 else 7 if gap <= 5 else 4 if gap <= 10 else 1
        return sc, round(ns, 0), round(gap, 2)
    except Exception as e:
        logging.debug(f"sr_score error: {e}")
        return 0, 0.0, 0.0


# ── [C] RSI 점수 (0~5) ───────────────────────────────────────────────────────
def calc_rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain  = delta.clip(lower=0).ewm(com=period-1, min_periods=period).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=period-1, min_periods=period).mean()
    rs    = gain / loss.replace(0, np.nan)
    rsi   = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 2) if not pd.isna(rsi.iloc[-1]) else 50.0

def calc_rsi_score(rsi: float) -> int:
    return 5 if rsi < 30 else 4 if rsi < 40 else 3 if rsi < 50 else 1 if rsi < 65 else 0


# ── [D] MA 정배열 점수 (0~10) ────────────────────────────────────────────────
def calc_ma_score(df: pd.DataFrame) -> tuple:
    try:
        c = df["Close"]
        m5, m20, m60 = c.rolling(5).mean().iloc[-1], c.rolling(20).mean().iloc[-1], c.rolling(60).mean().iloc[-1]
        m120 = c.rolling(120).mean().iloc[-1] if len(c) >= 120 else None
        if any(pd.isna(v) for v in [m5, m20, m60]): return 0, "insufficient"
        if m120 is not None and not pd.isna(m120):
            if m5 > m20 > m60 > m120: return 10, "full_bull"
            if m5 > m20 > m60:        return 7,  "3ma_bull"
            if m5 > m20:              return 3,  "2ma_bull"
        else:
            if m5 > m20 > m60: return 7, "3ma_bull"
            if m5 > m20:       return 3, "2ma_bull"
        return 0, "bearish"
    except Exception as e:
        logging.debug(f"ma_score error: {e}"); return 0, "error"


# ── [E] Volume Gap Score (0~15) ──────────────────────────────────────────────
def calc_volume_gap_score(df: pd.DataFrame) -> tuple:
    try:
        close, volume, n = df["Close"].values, df["Volume"].values, len(df)
        if n < 20: return 0, 0.0, "insufficient"
        p20  = np.percentile(close, VOL_GAP_BOTTOM_PCT * 100)
        p80  = np.percentile(close, (1 - VOL_GAP_TOP_PCT) * 100)
        bv   = volume[close <= p20].mean() if (close <= p20).sum() > 0 else 0
        tv   = volume[close >= p80].mean() if (close >= p80).sum() > 0 else 0
        if bv == 0: return 5, 0.0, "no_bottom_vol"
        r = round(tv / bv, 2)
        if r >= 4.0:   sc, lb = 0,  "sellout_strong"
        elif r >= 3.0: sc, lb = 3,  "sellout_warn"
        elif r >= 2.0: sc, lb = 7,  "neutral_high"
        elif r >= 1.5: sc, lb = 10, "healthy_mid"
        else:          sc, lb = 15, "healthy_strong"
        bpct = (close[-1] - p20) / (p80 - p20 + 1e-9) * 100
        if 0 <= bpct <= 30 and sc >= 10: sc = min(sc + 2, 15); lb += "_accumulation"
        return sc, r, lb
    except Exception as e:
        logging.debug(f"vg_score error: {e}"); return 0, 0.0, "error"


# ── [F] Standard Bar Score (0~10) ────────────────────────────────────────────
def calc_standard_bar_score(df: pd.DataFrame) -> tuple:
    try:
        if len(df) < STD_BAR_BREAKOUT_WIN + STD_BAR_LOOKBACK + 5: return 0, 0, -1
        close, open_, volume, high = df["Close"].values, df["Open"].values, df["Volume"].values, df["High"].values
        n = len(close)
        vma20 = pd.Series(volume).rolling(20).mean().values
        bs, bc, bi = 0, 0, -1
        for off in range(STD_BAR_LOOKBACK):
            i = n - 1 - off
            if i < STD_BAR_BREAKOUT_WIN + 5: break
            bp   = (close[i] - open_[i]) / open_[i] if open_[i] > 0 else 0
            c1   = bp >= STD_BAR_BODY_PCT and close[i] > open_[i]
            cv   = vma20[i] if not np.isnan(vma20[i]) else 0
            c2   = volume[i] >= cv * STD_BAR_VOL_MULT if cv > 0 else False
            m5v  = np.mean(close[i-4:i+1]) if i >= 4 else None
            m20v = np.mean(close[i-19:i+1]) if i >= 19 else None
            c3   = m5v is not None and m20v is not None and m5v > m20v
            ph   = high[i-STD_BAR_BREAKOUT_WIN:i].max() if i >= STD_BAR_BREAKOUT_WIN else 0
            c4   = close[i] > ph if ph > 0 else False
            cm   = sum([c1, c2, c3, c4])
            if cm > bc:
                bc = cm; bi = off
                is2 = off >= 1 and close[n-off] < close[n-off-1] and cm >= 3
                if cm == 4:   bs = 10 if is2 else 8
                elif cm == 3: bs = 7  if is2 else 6
                elif cm == 2: bs = 4
                elif cm == 1: bs = 2
                else:         bs = 0
        return bs, bc, bi
    except Exception as e:
        logging.debug(f"sb_score error: {e}"); return 0, 0, -1


# ── [G] Pullback Zone Score (0~10) ───────────────────────────────────────────
def calc_pullback_zone_score(df: pd.DataFrame) -> tuple:
    try:
        if len(df) < 25: return 0, 0.0, 0, "insufficient"
        close, volume, n = df["Close"].values, df["Volume"].values, len(df)
        cur  = close[-1]
        m5   = pd.Series(close).rolling(5).mean().values
        m10  = pd.Series(close).rolling(10).mean().values
        m20  = pd.Series(close).rolling(20).mean().values
        if any(pd.isna(x) for x in [m5[-1], m10[-1], m20[-1]]): return 0, 0.0, 0, "ma_insufficient"
        rh   = close[-min(PB_LOOKBACK_HIGH, n-1)-1:-1].max()
        if rh <= 0: return 0, 0.0, 0, "no_high"
        drop = (rh - cur) / rh * 100
        c1   = PB_DROP_MIN_PCT <= drop <= PB_DROP_MAX_PCT
        c2   = bool(m5[-1] > m20[-1])
        im5  = min(m5[-1], m10[-1]) <= cur <= max(m5[-1], m10[-1])
        im10 = min(m10[-1], m20[-1]) <= cur <= max(m10[-1], m20[-1])
        c3   = im5 or im10
        v5   = np.mean(volume[-5:]) if n >= 5 else np.mean(volume)
        v20  = np.mean(volume[-20:]) if n >= 20 else np.mean(volume)
        c4   = bool(v5 < v20 * PB_VOL_SHRINK_RATIO) if v20 > 0 else False
        ma5p = abs(m5[-1] - (m5[-4] if n >= 4 and not pd.isna(m5[-4]) else m5[-1])) / (m5[-1] + 1e-9) * 100
        c5   = ma5p < 2.0
        cm   = sum([c1, c2, c3, c4, c5])
        if not c1:
            return 0, round(drop, 2), cm, "too_shallow" if drop < PB_DROP_MIN_PCT else "too_deep"
        if cm >= 5:   sc, lb = 10, "perfect_pullback"
        elif cm == 4: sc, lb = 8,  "strong_pullback"
        elif cm == 3: sc, lb = 6,  "mild_pullback"
        elif cm == 2: sc, lb = 3,  "weak_pullback"
        else:         sc, lb = 1,  "possible_pullback"
        if im5 and c4 and sc < 10: sc = min(sc+1, 10); lb += "_confirmed"
        return sc, round(drop, 2), cm, lb
    except Exception as e:
        logging.debug(f"pb_score error: {e}"); return 0, 0.0, 0, "error"


# ── [H] Volume Surge Score (BM-10) (0~10) ────────────────────────────────────
def calc_volume_surge_score(df: pd.DataFrame) -> tuple:
    try:
        if len(df) < 22: return 0, 0.0, "insufficient"
        close, open_, volume = df["Close"].values, df["Open"].values, df["Volume"].values
        cv  = volume[-1]
        mv  = volume[-21:-1].max()
        if mv == 0: return 0, 0.0, "no_volume"
        r   = round(cv / mv, 4)
        c1, c2 = r >= 1.5, bool(close[-1] > open_[-1])
        if c1 and c2: return 10, r, "vol_surge_bull"
        elif c1:      return 5,  r, "vol_surge_bear"
        else:         return 0,  r, "normal"
    except Exception as e:
        logging.debug(f"vs_score error: {e}"); return 0, 0.0, "error"


# ── [I] MA60 Direction Score (BM-2) (0~8) ────────────────────────────────────
def calc_ma60_direction_score(df: pd.DataFrame) -> tuple:
    try:
        if len(df) < 60 + MA60_DIR_LOOKBACK + 1: return 0, 0.0, "insufficient"
        ma60 = df["Close"].rolling(60).mean()
        cur, prv = ma60.iloc[-1], ma60.iloc[-(MA60_DIR_LOOKBACK + 1)]
        if pd.isna(cur) or pd.isna(prv) or prv == 0: return 0, 0.0, "ma60_insufficient"
        sl = round((cur - prv) / prv * 100, 4)
        if sl >= MA60_DIR_RISING_STR:   return 8, sl, "MA60_RISING"
        elif sl >= MA60_DIR_RISING_MILD: return 5, sl, "MA60_MILD_RISE"
        elif sl >= MA60_DIR_FLAT_LOW:    return 2, sl, "MA60_FLAT"
        else:                            return 0, sl, "MA60_DECLINING"
    except Exception as e:
        logging.debug(f"ma60_score error: {e}"); return 0, 0.0, "error"


# ── [J] cap_trust_factor (P_NEW_2) ───────────────────────────────────────────
def calc_cap_trust_factor(market_cap: float) -> float:
    if not market_cap or market_cap <= 0: return 0.8
    if market_cap >= 10000: return 1.0
    elif market_cap >= 3000: return 0.9
    elif market_cap >= 1000: return 0.8
    else: return 0.7

def get_market_cap(ticker: str, trade_date: str) -> float:
    """Return market cap in KRW 100M units from prev_close_fetch output."""
    return float(MARKET_CAP_MAP.get(ticker.zfill(6), 0.0) or 0.0)


# ── OHLCV 수집 / 최근 거래일 ─────────────────────────────────────────────────
def fetch_ohlcv(ticker: str, end_date: datetime):
    try:
        df = load_ohlcv(ticker, n=LOOKBACK_DAYS)
        if df is None or len(df) < 20: return None
        df = df.rename(columns={
            "date": "Date", "open": "Open", "high": "High",
            "low": "Low", "close": "Close", "volume": "Volume",
        })
        df["Date"] = pd.to_datetime(df["Date"])
        return df.set_index("Date").sort_index().tail(LOOKBACK_DAYS)
    except FileNotFoundError:
        logging.warning("OHLCV store missing ticker=%s; skip", ticker)
        return None
    except Exception as e:
        logging.warning("OHLCV store load failed ticker=%s: %s; skip", ticker, e)
        return None

def find_recent_trade_date() -> datetime:
    try:
        df = load_ohlcv("005930", n=1)
        if not df.empty:
            return pd.to_datetime(df["date"].iloc[-1]).to_pydatetime()
    except Exception as e:
        logging.warning("Stored trade-date lookup failed: %s", e)
    return datetime.now()


# ── 종목 분석 ─────────────────────────────────────────────────────────────────
def analyze_ticker(ticker: str, end_date: datetime):
    df = fetch_ohlcv(ticker, end_date)
    if df is None: return None
    try:
        vp_score, poc_price, vah_price, val_price, vp_label, va_width_pct, vp_position = calc_vp_score(df)       # ★ BM-20
        sr_score, sr_support, sr_gap        = calc_sr_score(df)
        rsi_val                             = calc_rsi(df["Close"])
        rsi_score                           = calc_rsi_score(rsi_val)
        ma_score, ma_label                  = calc_ma_score(df)
        vg_score, vol_gap_ratio, vg_label   = calc_volume_gap_score(df)
        sb_score, sb_conds, sb_bar_idx      = calc_standard_bar_score(df)
        pb_score, pb_drop_pct, pb_conds, pb_label = calc_pullback_zone_score(df)
        vs_score, vol_surge_ratio, vs_label = calc_volume_surge_score(df)
        ma60_sc, ma60_sl, ma60_lb           = calc_ma60_direction_score(df)

        market_cap  = get_market_cap(ticker, end_date.strftime("%Y%m%d"))
        cap_trust   = calc_cap_trust_factor(market_cap)
        vs_adj      = round(vs_score * cap_trust, 1)

        detail = vp_score + sr_score + rsi_score + ma_score   # max 45
        total  = detail + vg_score + sb_score + pb_score + vs_adj + ma60_sc  # max 98

        return {
            "ticker":              ticker.zfill(6),
            # ★ BM-20 컬럼
            "vp_score":            vp_score,
            "poc_price":           poc_price,
            "vah_price":           vah_price,
            "val_price":           val_price,
            "vp_label":            vp_label,
            "va_width_pct":        va_width_pct,
            "vp_position":         vp_position,
            # 기존 컬럼
            "sr_score":            sr_score,
            "sr_support":          sr_support,
            "sr_gap_pct":          sr_gap,
            "rsi_score":           rsi_score,
            "rsi":                 rsi_val,
            "ma_score":            ma_score,
            "ma_label":            ma_label,
            "tech_detail_score":   detail,
            "vol_gap_score":       vg_score,
            "vol_gap_ratio":       vol_gap_ratio,
            "vol_gap_label":       vg_label,
            "std_bar_score":       sb_score,
            "std_bar_conds":       sb_conds,
            "std_bar_recency":     sb_bar_idx,
            "pullback_zone_score": pb_score,
            "pullback_drop_pct":   pb_drop_pct,
            "pullback_conds":      pb_conds,
            "pullback_label":      pb_label,
            "vol_surge_score":     vs_score,
            "vol_surge_ratio":     vol_surge_ratio,
            "vol_surge_label":     vs_label,
            "ma60_dir_score":      ma60_sc,
            "ma60_slope_pct":      ma60_sl,
            "ma60_dir_label":      ma60_lb,
            "market_cap_억":       market_cap,
            "cap_trust_factor":    cap_trust,
            "vol_surge_adj":       vs_adj,
            "tech_total_score":    total,
        }
    except Exception as e:
        logging.debug(f"analyze_ticker {ticker} error: {e}"); return None


# ── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    global MARKET_CAP_MAP
    logging.info("=== sfd_technical_analyzer v1.6 START ===")
    logging.info(f"BASE_DIR: {BASE_DIR}")
    logging.info(f"SCIPY:    {SCIPY_AVAILABLE}")
    logging.info("SCORE MAX: v1.6=98pt (BM-20 vp_score 0~20pt / cap_trust 보정)")
    logging.info(f"DXY_SYMBOL: {DXY_SYMBOL}")

    if not os.path.exists(INPUT_CSV):
        logging.error(f"INPUT_CSV not found: {INPUT_CSV}"); sys.exit(1)

    input_df = pd.read_csv(INPUT_CSV, encoding="utf-8-sig", dtype={"ticker": str})
    tickers = (
        input_df["ticker"]
        .dropna().astype(str).str.strip().str.zfill(6).unique().tolist()
    )
    if "market_cap_억" in input_df.columns:
        cap_values = pd.to_numeric(input_df["market_cap_억"], errors="coerce").fillna(0.0)
        cap_tickers = input_df["ticker"].astype(str).str.strip().str.zfill(6)
        MARKET_CAP_MAP = dict(zip(cap_tickers, cap_values))
    else:
        logging.warning("market_cap_억 missing from prev_close input; fallback factor applies")
    logging.info(f"tickers: {len(tickers)}")

    end_date = find_recent_trade_date()
    logging.info(f"trade_date: {end_date.strftime('%Y%m%d')}")

    results, ok_cnt, fail_cnt = [], 0, 0
    for i, ticker in enumerate(tickers):
        row = analyze_ticker(ticker, end_date)
        if row: results.append(row); ok_cnt += 1
        else:   fail_cnt += 1
        if (i + 1) % 50 == 0:
            logging.info(f"  progress: {i+1}/{len(tickers)} | ok={ok_cnt} fail={fail_cnt} | {int(time.time()-START_TIME)}s")

    if not results: logging.error("No results. Abort."); sys.exit(1)

    df_out = pd.DataFrame(results).sort_values("tech_total_score", ascending=False).reset_index(drop=True)
    df_out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    df_out.to_csv(os.path.join(HISTORY_DIR, f"sfd_technical_{end_date.strftime('%Y%m%d')}.csv"), index=False, encoding="utf-8-sig")

    elapsed     = int(time.time() - START_TIME)
    pb_active   = df_out[df_out["pullback_zone_score"] >= 7]
    vs_active   = df_out[df_out["vol_surge_label"] == "vol_surge_bull"]
    ma60_rising = df_out[df_out["ma60_dir_label"] == "MA60_RISING"]
    cap_dist    = df_out["cap_trust_factor"].value_counts().to_dict()
    vp_dist     = df_out["vp_position"].value_counts().to_dict()

    top5 = df_out.head(5)[["ticker","tech_total_score","tech_detail_score",
        "vp_score","vp_position","vol_gap_score","std_bar_score",
        "pullback_zone_score","vol_surge_adj","cap_trust_factor",
        "ma60_dir_label","ma_label"]].to_string(index=False)

    logging.info(f"DONE | ok={ok_cnt} fail={fail_cnt} elapsed={elapsed}s")
    logging.info(f"TOP5:\n{top5}")
    logging.info(f"PULLBACK(>=7, {len(pb_active)}종):\n{pb_active[['ticker','pullback_zone_score','pullback_label','pullback_drop_pct']].head(10).to_string(index=False)}")
    logging.info(f"[BM-10] 치량천 ({len(vs_active)}종):\n{vs_active[['ticker','vol_surge_score','vol_surge_adj','vol_surge_ratio','cap_trust_factor']].head(10).to_string(index=False)}")
    logging.info(f"[BM-2] MA60_RISING: {len(ma60_rising)}종")
    logging.info(f"[BM-20] vp_position 분포: {vp_dist}")
    logging.info(f"[P_NEW_2] cap_trust 분포: {cap_dist}")

    print(f"[OK] tech_analyzer v1.6 | ok={ok_cnt} | fail={fail_cnt} | elapsed={elapsed}s")
    print(f"  -> {OUTPUT_CSV}")
    print(f"  -> [BM-20] above_vah:{vp_dist.get('above_vah',0)} near_vah:{vp_dist.get('near_vah',0)} in_va:{vp_dist.get('in_va',0)} at_poc:{vp_dist.get('at_poc',0)}")
    print(f"  -> pullback_zone>=7: {len(pb_active)}종")
    print(f"  -> [BM-10] vol_surge_bull: {len(vs_active)}종")
    print(f"  -> [BM-2] MA60_RISING: {len(ma60_rising)}종")


if __name__ == "__main__":
    main()
