# sfd_technical_analyzer.py | v1.2 | Layer 2.7 | Claude (Anthropic) 2026-05-30
# Deploy to: sfd-pipeline/tools/sfd_technical_analyzer.py
#
# [Layer 2.7] 기술적 분석 / 스코어링 / 기준봉 자동 탐지
# 입력: inputs/sfd_master_signal_input.csv  (ticker 목록)
# 출력: outputs/latest/sfd_technical_latest.csv
#
# [스코어 아키텍처] tech_total_score (max 75pt ★ v1.2)
#   [A] Volume Profile / POC 점수        : 0~15pt  (v1.0 유지)
#   [B] Support/Resistance 점수          : 0~10pt  (v1.0 유지)
#   [C] RSI 포지션 (과매도)               : 0~5pt   (v1.0 유지)
#   [D] MA5>20>60>120 정배열 점수         : 0~10pt  (v1.0 유지)
#   [E] Volume Gap Score (설거지 탐지)    : 0~15pt  ★ v1.1 추가
#   [F] Standard Bar Score (기준봉 탐지)  : 0~10pt  ★ v1.1 추가
#   [G] Pullback Zone Score (눌림목 탐지) : 0~10pt  ★ v1.2 신규
#      합계 max = 75pt (기존 65pt → +10pt)
#
# [v1.2 변경사항]
#   - [G] pullback_zone_score 추가 (야베스 숏딥/턴딥 + 차트프로 AF F구간)
#     * 1차 상승 후 5/10일선 사이 수렴 + 거래량 감소 구간 탐지
#     * MA 정배열 유지 중 눌림목(-3%~-15%) 구간 집중 탐지
#     * L5.5 trade_guardian JABEZ_PULLBACK 경보와 연동 (score >= 7)
#   - tech_total_score max: 65pt → 75pt

import os
import sys
import time
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

# ── 경로 설정 (SFD_BASE_DIR 환경변수 우선, 없으면 __file__ 기반)
_env_base = os.environ.get("SFD_BASE_DIR", "")
if _env_base and os.path.isdir(_env_base):
    BASE_DIR = _env_base
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LATEST_DIR  = os.path.join(BASE_DIR, "outputs", "latest")
HISTORY_DIR = os.path.join(BASE_DIR, "outputs", "history")
INPUT_DIR   = os.path.join(BASE_DIR, "inputs")

os.makedirs(LATEST_DIR,  exist_ok=True)
os.makedirs(HISTORY_DIR, exist_ok=True)

INPUT_CSV  = os.path.join(INPUT_DIR,   "sfd_master_signal_input.csv")
OUTPUT_CSV = os.path.join(LATEST_DIR,  "sfd_technical_latest.csv")
LOG_PATH   = os.path.join(LATEST_DIR,  "sfd_technical_analyzer.log")

logging.basicConfig(
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

# ── 파라미터
LOOKBACK_DAYS    = 60
MA_PERIODS       = [5, 10, 20, 60, 120]   # ★ v1.2: MA10 추가 (눌림목 탐지용)
RSI_PERIOD       = 14
VOL_BINS         = 20
SWING_DISTANCE   = 5

# [E] Volume Gap 파라미터
VOL_GAP_BOTTOM_PCT = 0.20
VOL_GAP_TOP_PCT    = 0.20

# [F] Standard Bar 파라미터
STD_BAR_BODY_PCT     = 0.03
STD_BAR_VOL_MULT     = 1.5
STD_BAR_BREAKOUT_WIN = 20
STD_BAR_LOOKBACK     = 5

# ★ [G] Pullback Zone 파라미터 (v1.2 신규)
PB_LOOKBACK_HIGH    = 20   # 최근 N일 고점 탐색 구간
PB_DROP_MIN_PCT     = 3.0  # 눌림목 최소 하락률 (고점 대비 -3%)
PB_DROP_MAX_PCT     = 15.0 # 눌림목 최대 하락률 (고점 대비 -15%)
PB_VOL_SHRINK_RATIO = 0.7  # 거래량 수축 기준 (5일 평균 < 20일 평균 * 0.7)
PB_MA_ALIGN_REQ     = True # MA5 > MA20 정배열 필수 여부

START_TIME = time.time()


# ── [A] Volume Profile / POC 점수 (0~15) ─────────────────────────────────────
def calc_poc_score(df: pd.DataFrame) -> tuple:
    try:
        close   = df["Close"].values
        volume  = df["Volume"].values
        current = close[-1]

        price_min, price_max = close.min(), close.max()
        if price_max == price_min:
            return 0, current, 0.0

        bins      = np.linspace(price_min, price_max, VOL_BINS + 1)
        bin_idx   = np.digitize(close, bins) - 1
        bin_idx   = np.clip(bin_idx, 0, VOL_BINS - 1)
        vol_by_bin = np.zeros(VOL_BINS)
        for i, v in zip(bin_idx, volume):
            vol_by_bin[i] += v

        poc_bin   = np.argmax(vol_by_bin)
        poc_price = (bins[poc_bin] + bins[poc_bin + 1]) / 2
        pct_diff  = (current - poc_price) / poc_price * 100

        if pct_diff >= 3.0:   score = 15
        elif pct_diff >= 1.0: score = 12
        elif pct_diff >= -1.0: score = 8
        elif pct_diff >= -5.0: score = 3
        else:                  score = 0

        return score, round(poc_price, 0), round(pct_diff, 2)
    except Exception as e:
        logging.debug(f"poc_score error: {e}")
        return 0, 0.0, 0.0


# ── [B] Support/Resistance 점수 (0~10) ───────────────────────────────────────
def calc_sr_score(df: pd.DataFrame) -> tuple:
    try:
        close   = df["Close"].values
        current = close[-1]

        if SCIPY_AVAILABLE:
            peaks, _ = find_peaks(-close, distance=SWING_DISTANCE, prominence=current * 0.01)
            support_levels = close[peaks] if len(peaks) > 0 else np.array([])
        else:
            window = 5
            local_min_idx = []
            for i in range(window, len(close) - window):
                if close[i] == min(close[i - window: i + window + 1]):
                    local_min_idx.append(i)
            support_levels = close[local_min_idx] if local_min_idx else np.array([])

        supports_below = support_levels[support_levels < current]
        if len(supports_below) == 0:
            return 0, 0.0, 0.0

        nearest_support = supports_below.max()
        gap_pct = (current - nearest_support) / nearest_support * 100

        if gap_pct <= 2.0:   score = 10
        elif gap_pct <= 5.0: score = 7
        elif gap_pct <= 10.0: score = 4
        else:                 score = 1

        return score, round(nearest_support, 0), round(gap_pct, 2)
    except Exception as e:
        logging.debug(f"sr_score error: {e}")
        return 0, 0.0, 0.0


# ── [C] RSI 점수 (0~5) ───────────────────────────────────────────────────────
def calc_rsi(series: pd.Series, period: int = 14) -> float:
    delta    = series.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    rsi      = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 2) if not pd.isna(rsi.iloc[-1]) else 50.0

def calc_rsi_score(rsi: float) -> int:
    if rsi < 30: return 5
    if rsi < 40: return 4
    if rsi < 50: return 3
    if rsi < 65: return 1
    return 0


# ── [D] MA 정배열 점수 (0~10) ────────────────────────────────────────────────
def calc_ma_score(df: pd.DataFrame) -> tuple:
    try:
        close = df["Close"]
        ma5   = close.rolling(5).mean().iloc[-1]
        ma20  = close.rolling(20).mean().iloc[-1]
        ma60  = close.rolling(60).mean().iloc[-1]
        ma120 = close.rolling(120).mean().iloc[-1] if len(close) >= 120 else None

        if any(pd.isna(v) for v in [ma5, ma20, ma60]):
            return 0, "insufficient"

        if ma120 is not None and not pd.isna(ma120):
            if ma5 > ma20 > ma60 > ma120: return 10, "full_bull"
            if ma5 > ma20 > ma60:         return 7, "3ma_bull"
            if ma5 > ma20:                return 3, "2ma_bull"
        else:
            if ma5 > ma20 > ma60: return 7, "3ma_bull"
            if ma5 > ma20:        return 3, "2ma_bull"

        return 0, "bearish"
    except Exception as e:
        logging.debug(f"ma_score error: {e}")
        return 0, "error"


# ── [E] Volume Gap Score (0~15) ★ v1.1 ──────────────────────────────────────
def calc_volume_gap_score(df: pd.DataFrame) -> tuple:
    try:
        close  = df["Close"].values
        volume = df["Volume"].values
        n      = len(close)

        if n < 20:
            return 0, 0.0, "insufficient"

        price_20pct = np.percentile(close, VOL_GAP_BOTTOM_PCT * 100)
        price_80pct = np.percentile(close, (1 - VOL_GAP_TOP_PCT) * 100)

        bottom_mask = close <= price_20pct
        top_mask    = close >= price_80pct

        bottom_vol = volume[bottom_mask].mean() if bottom_mask.sum() > 0 else 0
        top_vol    = volume[top_mask].mean()    if top_mask.sum() > 0    else 0

        if bottom_vol == 0:
            return 5, 0.0, "no_bottom_vol"

        vol_gap_ratio = round(top_vol / bottom_vol, 2)

        if vol_gap_ratio >= 4.0:   score, label = 0,  "sellout_strong"
        elif vol_gap_ratio >= 3.0: score, label = 3,  "sellout_warn"
        elif vol_gap_ratio >= 2.0: score, label = 7,  "neutral_high"
        elif vol_gap_ratio >= 1.5: score, label = 10, "healthy_mid"
        else:                      score, label = 15, "healthy_strong"

        # 추가 보정: 바닥 30% 구간에서 축적 시 가점
        current  = close[-1]
        base_pct = (current - price_20pct) / (price_80pct - price_20pct + 1e-9) * 100
        if 0 <= base_pct <= 30 and score >= 10:
            score = min(score + 2, 15)
            label += "_accumulation"

        return score, vol_gap_ratio, label
    except Exception as e:
        logging.debug(f"volume_gap_score error: {e}")
        return 0, 0.0, "error"


# ── [F] Standard Bar Score (0~10) ★ v1.1 ────────────────────────────────────
def calc_standard_bar_score(df: pd.DataFrame) -> tuple:
    try:
        if len(df) < STD_BAR_BREAKOUT_WIN + STD_BAR_LOOKBACK + 5:
            return 0, 0, -1

        close  = df["Close"].values
        open_  = df["Open"].values
        volume = df["Volume"].values
        high   = df["High"].values
        n      = len(close)

        vol_ma20 = pd.Series(volume).rolling(20).mean().values

        best_score   = 0
        best_cond    = 0
        best_bar_idx = -1

        for offset in range(STD_BAR_LOOKBACK):
            i = n - 1 - offset
            if i < STD_BAR_BREAKOUT_WIN + 5:
                break

            body_pct = (close[i] - open_[i]) / open_[i] if open_[i] > 0 else 0
            cond1    = body_pct >= STD_BAR_BODY_PCT and close[i] > open_[i]

            cond2_vol = vol_ma20[i] if not np.isnan(vol_ma20[i]) else 0
            cond2     = volume[i] >= cond2_vol * STD_BAR_VOL_MULT if cond2_vol > 0 else False

            ma5_val  = np.mean(close[i-4:i+1]) if i >= 4 else None
            ma20_val = np.mean(close[i-19:i+1]) if i >= 19 else None
            cond3    = (ma5_val is not None and ma20_val is not None
                        and ma5_val > ma20_val)

            prev_high = high[i - STD_BAR_BREAKOUT_WIN: i].max() if i >= STD_BAR_BREAKOUT_WIN else 0
            cond4     = close[i] > prev_high if prev_high > 0 else False

            conds_met = sum([cond1, cond2, cond3, cond4])

            if conds_met > best_cond:
                best_cond    = conds_met
                best_bar_idx = offset
                is_2nd_bar = (
                    offset >= 1
                    and close[n - offset] < close[n - offset - 1]
                    and conds_met >= 3
                )
                if conds_met == 4:   best_score = 10 if is_2nd_bar else 8
                elif conds_met == 3: best_score = 7  if is_2nd_bar else 6
                elif conds_met == 2: best_score = 4
                elif conds_met == 1: best_score = 2
                else:                best_score = 0

        return best_score, best_cond, best_bar_idx
    except Exception as e:
        logging.debug(f"standard_bar_score error: {e}")
        return 0, 0, -1


# ── [G] Pullback Zone Score (0~10) ★ v1.2 신규 ──────────────────────────────
def calc_pullback_zone_score(df: pd.DataFrame) -> tuple:
    """
    [야베스 숏딥/턴딥 눌림목 탐지]

    눌림목 정의 (5가지 조건 복합 평가):
      조건1. 최근 N일 고점 대비 현재가 -3% ~ -15% 구간 (눌림 깊이)
      조건2. MA5 > MA20 정배열 유지 (상승추세 중 눌림)
      조건3. MA5와 MA10 사이에 현재가 위치 (단기 이평 수렴 구간)
      조건4. 최근 5일 거래량 평균 < 20일 평균 * 0.7 (거래량 수축)
      조건5. MA5 기울기 완화 (수렴 중) = |MA5 - MA5_3일전| / MA5 < 2%

    Returns: (score 0~10, pb_drop_pct, conditions_met, pb_label)
    """
    try:
        if len(df) < 25:
            return 0, 0.0, 0, "insufficient"

        close  = df["Close"].values
        volume = df["Volume"].values
        n      = len(close)

        current = close[-1]

        # MA 계산
        ma5  = pd.Series(close).rolling(5).mean().values
        ma10 = pd.Series(close).rolling(10).mean().values
        ma20 = pd.Series(close).rolling(20).mean().values

        ma5_cur  = ma5[-1]
        ma10_cur = ma10[-1]
        ma20_cur = ma20[-1]

        if pd.isna(ma5_cur) or pd.isna(ma10_cur) or pd.isna(ma20_cur):
            return 0, 0.0, 0, "ma_insufficient"

        # 최근 N일 고점
        lookback_window = min(PB_LOOKBACK_HIGH, n - 1)
        recent_high = close[-lookback_window - 1: -1].max()  # 현재가 제외 고점

        if recent_high <= 0:
            return 0, 0.0, 0, "no_high"

        pb_drop_pct = (recent_high - current) / recent_high * 100

        # 조건1: 눌림 깊이 체크
        cond1 = PB_DROP_MIN_PCT <= pb_drop_pct <= PB_DROP_MAX_PCT

        # 조건2: MA 정배열 (MA5 > MA20)
        cond2 = bool(ma5_cur > ma20_cur)

        # 조건3: 현재가가 MA5 ~ MA10 사이 (단기 이평 수렴 구간)
        # 또는 MA10 ~ MA20 사이 (좀 더 깊은 눌림)
        in_ma5_ma10  = min(ma5_cur, ma10_cur) <= current <= max(ma5_cur, ma10_cur)
        in_ma10_ma20 = min(ma10_cur, ma20_cur) <= current <= max(ma10_cur, ma20_cur)
        cond3 = in_ma5_ma10 or in_ma10_ma20

        # 조건4: 거래량 수축 (최근 5일 평균 < 20일 평균 * 0.7)
        vol_5d  = np.mean(volume[-5:])  if n >= 5  else np.mean(volume)
        vol_20d = np.mean(volume[-20:]) if n >= 20 else np.mean(volume)
        cond4 = bool(vol_5d < vol_20d * PB_VOL_SHRINK_RATIO) if vol_20d > 0 else False

        # 조건5: MA5 기울기 완화 (수렴 징후)
        ma5_3d_ago = ma5[-4] if n >= 4 and not pd.isna(ma5[-4]) else ma5_cur
        ma5_slope_pct = abs(ma5_cur - ma5_3d_ago) / (ma5_cur + 1e-9) * 100
        cond5 = ma5_slope_pct < 2.0  # MA5 기울기 2% 미만 → 수렴 중

        conds_met = sum([cond1, cond2, cond3, cond4, cond5])

        # 점수 산정
        if not cond1:
            # 눌림 범위 벗어남 → 기본 0점 (단, 가까우면 소점수)
            if pb_drop_pct < PB_DROP_MIN_PCT:
                label = "too_shallow"   # 고점 근처
            else:
                label = "too_deep"      # 하락 과다
            return 0, round(pb_drop_pct, 2), conds_met, label

        # 눌림 구간 내 → 조건 수에 따라 점수
        if conds_met >= 5:   score, label = 10, "perfect_pullback"
        elif conds_met == 4: score, label = 8,  "strong_pullback"
        elif conds_met == 3: score, label = 6,  "mild_pullback"
        elif conds_met == 2: score, label = 3,  "weak_pullback"
        else:                score, label = 1,  "possible_pullback"

        # 추가 보정: MA5~MA10 사이 수렴 + 거래량 수축 동시 만족 시 +1
        if in_ma5_ma10 and cond4 and score < 10:
            score = min(score + 1, 10)
            label += "_confirmed"

        return score, round(pb_drop_pct, 2), conds_met, label

    except Exception as e:
        logging.debug(f"pullback_zone_score error: {e}")
        return 0, 0.0, 0, "error"


# ── OHLCV 수집 ────────────────────────────────────────────────────────────────
def fetch_ohlcv(ticker: str, end_date: datetime) -> pd.DataFrame | None:
    try:
        start = (end_date - timedelta(days=LOOKBACK_DAYS * 2)).strftime("%Y-%m-%d")
        end   = end_date.strftime("%Y-%m-%d")
        df    = fdr.DataReader(ticker, start, end)
        if df is None or len(df) < 20:
            return None
        df = df.sort_index()
        return df.tail(LOOKBACK_DAYS)
    except Exception:
        return None


# ── 최근 거래일 탐색 ──────────────────────────────────────────────────────────
def find_recent_trade_date() -> datetime:
    now = datetime.now()
    for i in range(7):
        d = now - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        try:
            ds = d.strftime("%Y-%m-%d")
            df = fdr.DataReader("005930", ds, ds)
            if df is not None and len(df) > 0:
                return d
        except Exception:
            pass
    return now


# ── 종목별 분석 ───────────────────────────────────────────────────────────────
def analyze_ticker(ticker: str, end_date: datetime) -> dict | None:
    df = fetch_ohlcv(ticker, end_date)
    if df is None:
        return None

    try:
        poc_score,   poc_price,    poc_pct      = calc_poc_score(df)
        sr_score,    sr_support,   sr_gap        = calc_sr_score(df)
        rsi_val                                   = calc_rsi(df["Close"])
        rsi_score                                 = calc_rsi_score(rsi_val)
        ma_score,    ma_label                     = calc_ma_score(df)
        vg_score,    vol_gap_ratio, vg_label      = calc_volume_gap_score(df)
        sb_score,    sb_conds,      sb_bar_idx    = calc_standard_bar_score(df)
        # ★ v1.2 신규
        pb_score,    pb_drop_pct,   pb_conds, pb_label = calc_pullback_zone_score(df)

        tech_detail_score = poc_score + sr_score + rsi_score + ma_score   # max 40 (v1.0 호환)
        tech_total_score  = tech_detail_score + vg_score + sb_score + pb_score  # ★ max 75

        return {
            "ticker":             ticker.zfill(6),
            # ── v1.0 컬럼 (signal_aggregator 호환) ──────────────────────────
            "poc_score":          poc_score,
            "poc_price":          poc_price,
            "poc_pct":            poc_pct,
            "sr_score":           sr_score,
            "sr_support":         sr_support,
            "sr_gap_pct":         sr_gap,
            "rsi_score":          rsi_score,
            "rsi":                rsi_val,
            "ma_score":           ma_score,
            "ma_label":           ma_label,
            "tech_detail_score":  tech_detail_score,   # max=40 (aggregator 호환)
            # ── v1.1 컬럼 ───────────────────────────────────────────────────
            "vol_gap_score":      vg_score,
            "vol_gap_ratio":      vol_gap_ratio,
            "vol_gap_label":      vg_label,
            "std_bar_score":      sb_score,
            "std_bar_conds":      sb_conds,
            "std_bar_recency":    sb_bar_idx,
            # ── v1.2 컬럼 (신규) ────────────────────────────────────────────
            "pullback_zone_score": pb_score,           # ★ 0~10 (guardian 연동)
            "pullback_drop_pct":   pb_drop_pct,        # ★ 고점 대비 하락률
            "pullback_conds":      pb_conds,            # ★ 만족 조건 수
            "pullback_label":      pb_label,            # ★ 눌림목 유형
            # ── 합산 ────────────────────────────────────────────────────────
            "tech_total_score":   tech_total_score,    # ★ max=75
        }
    except Exception as e:
        logging.debug(f"analyze_ticker {ticker} error: {e}")
        return None


# ── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    logging.info("=== sfd_technical_analyzer v1.2 START ===")
    logging.info(f"BASE_DIR:  {BASE_DIR}")
    logging.info(f"SCIPY:     {SCIPY_AVAILABLE}")
    logging.info("SCORE MAX: v1.0=40pt / v1.1=65pt / v1.2 total=75pt (+pullback_zone)")

    if not os.path.exists(INPUT_CSV):
        logging.error(f"INPUT_CSV not found: {INPUT_CSV}")
        sys.exit(1)

    input_df = pd.read_csv(INPUT_CSV, encoding="utf-8-sig", dtype={"ticker": str})
    tickers  = (
        input_df["ticker"].dropna().astype(str)
        .str.strip().str.zfill(6).unique().tolist()
    )
    logging.info(f"tickers: {len(tickers)}")

    end_date = find_recent_trade_date()
    logging.info(f"trade_date: {end_date.strftime('%Y%m%d')}")

    results  = []
    ok_cnt   = 0
    fail_cnt = 0

    for i, ticker in enumerate(tickers):
        row = analyze_ticker(ticker, end_date)
        if row:
            results.append(row)
            ok_cnt += 1
        else:
            fail_cnt += 1

        if (i + 1) % 50 == 0:
            elapsed = int(time.time() - START_TIME)
            logging.info(f"  progress: {i+1}/{len(tickers)} | ok={ok_cnt} fail={fail_cnt} | {elapsed}s")

    if not results:
        logging.error("No results. Abort.")
        sys.exit(1)

    df_out = (
        pd.DataFrame(results)
        .sort_values("tech_total_score", ascending=False)
        .reset_index(drop=True)
    )
    df_out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    hist_path = os.path.join(
        HISTORY_DIR,
        f"sfd_technical_{end_date.strftime('%Y%m%d')}.csv"
    )
    df_out.to_csv(hist_path, index=False, encoding="utf-8-sig")

    elapsed = int(time.time() - START_TIME)

    # 눌림목 탐지 현황 로그
    pb_active = df_out[df_out["pullback_zone_score"] >= 7]
    pb_list   = pb_active[["ticker", "pullback_zone_score", "pullback_label", "pullback_drop_pct"]].head(10).to_string(index=False)

    top5 = df_out.head(5)[[
        "ticker", "tech_total_score", "tech_detail_score",
        "vol_gap_score", "std_bar_score", "pullback_zone_score",
        "ma_label", "pullback_label"
    ]].to_string(index=False)

    logging.info(f"DONE | ok={ok_cnt} fail={fail_cnt} elapsed={elapsed}s")
    logging.info(f"TOP5:\n{top5}")
    logging.info(f"PULLBACK(score>=7, {len(pb_active)}건):\n{pb_list}")
    print(f"[OK] tech_analyzer v1.2 | ok={ok_cnt} | fail={fail_cnt} | elapsed={elapsed}s")
    print(f"  -> {OUTPUT_CSV}")
    print(f"  -> pullback_zone score>=7: {len(pb_active)}건")


if __name__ == "__main__":
    main()
