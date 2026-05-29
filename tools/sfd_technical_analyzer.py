# sfd_technical_analyzer.py | v1.0 | Layer 2.7 | Claude (Anthropic) 2026-05-29
# Deploy to: D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline\tools\sfd_technical_analyzer.py
#
# [Layer 2.7] 매물대 / 지지선 / 볼린저밴드 기술적 분석
# 입력: inputs/sfd_master_signal_input.csv  (ticker 목록)
# 출력: outputs/latest/sfd_technical_latest.csv
#
# [점수 구성] tech_detail_score (max 40pt, 기존 tech_score와 동일 범위 → 드롭인 교체)
#   [A] Volume Profile / POC 근접도    : 0~15pt
#   [B] Support/Resistance 지지선       : 0~10pt
#   [C] RSI 포지션 (보조)              : 0~5pt
#   [D] MA5>20>60>120 정배열 강화      : 0~10pt
#   총합 max = 40pt
#
# [자가발전 프로토콜] 벤치마킹 출처:
#   - TradingView Volume Profile (DGT): POC/HVN/LVN 로직 참조
#   - Institutional Insight Indicator (RuneDD): Swing H/L 기반 S/D 존 참조
#   - Supply Demand Zones PRO (IJAlgo): 존 점수화 방식 참조

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

# ── 경로 설정 (SFD_BASE_DIR 환경변수 또는 __file__ 기반 자동 감지) ──────────
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

INPUT_CSV   = os.path.join(INPUT_DIR,   "sfd_master_signal_input.csv")
OUTPUT_CSV  = os.path.join(LATEST_DIR,  "sfd_technical_latest.csv")
LOG_PATH    = os.path.join(LATEST_DIR,  "sfd_technical_analyzer.log")

logging.basicConfig(
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

# ── 파라미터 ─────────────────────────────────────────────────────────────────
LOOKBACK_DAYS   = 60    # 매물대/지지선 분석 기간
MA_PERIODS      = [5, 20, 60, 120]
RSI_PERIOD      = 14
VOL_BINS        = 20    # Volume Profile 구간 수
SWING_DISTANCE  = 5     # 스윙 고저점 최소 거리(봉)
START_TIME      = time.time()


# ── [A] Volume Profile / POC 점수 (0~15) ─────────────────────────────────────
def calc_poc_score(df: pd.DataFrame) -> tuple:
    """
    60일 가격대별 거래량 집계 → POC 산출 → 현재가 위치로 점수화
    Returns: (score 0~15, poc_price, poc_pct_from_current)
    """
    try:
        close  = df["Close"].values
        volume = df["Volume"].values
        current = close[-1]

        price_min, price_max = close.min(), close.max()
        if price_max == price_min:
            return 0, current, 0.0

        # 가격대별 거래량 히스토그램
        bins      = np.linspace(price_min, price_max, VOL_BINS + 1)
        bin_idx   = np.digitize(close, bins) - 1
        bin_idx   = np.clip(bin_idx, 0, VOL_BINS - 1)
        vol_by_bin = np.zeros(VOL_BINS)
        for i, v in zip(bin_idx, volume):
            vol_by_bin[i] += v

        # POC = 가장 거래량 높은 bin 중심가
        poc_bin   = np.argmax(vol_by_bin)
        poc_price = (bins[poc_bin] + bins[poc_bin + 1]) / 2
        pct_diff  = (current - poc_price) / poc_price * 100  # % 차이

        # 점수화: 현재가가 POC 위에 있을수록 지지력 강함
        if pct_diff >= 3.0:
            score = 15   # POC가 충분한 지지선 역할
        elif pct_diff >= 1.0:
            score = 12
        elif pct_diff >= -1.0:
            score = 8    # POC 근접 (혼조)
        elif pct_diff >= -5.0:
            score = 3    # POC 소폭 하회 (매물 압박)
        else:
            score = 0    # POC 대폭 하회 (강한 매물대 하방)

        return score, round(poc_price, 0), round(pct_diff, 2)

    except Exception as e:
        logging.debug(f"poc_score error: {e}")
        return 0, 0.0, 0.0


# ── [B] Support/Resistance 지지선 점수 (0~10) ─────────────────────────────────
def calc_sr_score(df: pd.DataFrame) -> tuple:
    """
    스윙 저점(지지선) 탐지 → 현재가와 가장 가까운 지지선 이격도로 점수화
    Returns: (score 0~10, nearest_support, gap_pct)
    """
    try:
        close   = df["Close"].values
        current = close[-1]

        if SCIPY_AVAILABLE:
            # scipy find_peaks: 저점 = 반전된 시리즈의 고점
            peaks, _ = find_peaks(-close, distance=SWING_DISTANCE, prominence=current * 0.01)
            support_levels = close[peaks] if len(peaks) > 0 else np.array([])
        else:
            # scipy 없을 경우 간단한 롤링 최솟값 근사
            window = 5
            local_min_idx = []
            for i in range(window, len(close) - window):
                if close[i] == min(close[i - window: i + window + 1]):
                    local_min_idx.append(i)
            support_levels = close[local_min_idx] if local_min_idx else np.array([])

        # 현재가 아래의 지지선만 선택 (현재가 > 지지선)
        supports_below = support_levels[support_levels < current]

        if len(supports_below) == 0:
            return 0, 0.0, 0.0

        # 가장 가까운(최근) 지지선
        nearest_support = supports_below.max()
        gap_pct = (current - nearest_support) / nearest_support * 100

        # 지지선 바로 위일수록 고점수 (지지선에 가까울수록 반등 여력 + 리스크 관리)
        if gap_pct <= 2.0:
            score = 10   # 지지선 0~2% 위: 최적 매수 구간
        elif gap_pct <= 5.0:
            score = 7
        elif gap_pct <= 10.0:
            score = 4
        else:
            score = 1    # 지지선에서 멀리 있음

        return score, round(nearest_support, 0), round(gap_pct, 2)

    except Exception as e:
        logging.debug(f"sr_score error: {e}")
        return 0, 0.0, 0.0


# ── [C] RSI 포지션 점수 (0~5) ─────────────────────────────────────────────────
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
    if rsi < 30: return 5    # 과매도: 강한 반등 신호
    if rsi < 40: return 4
    if rsi < 50: return 3
    if rsi < 65: return 1
    return 0                  # 과매수: 추가 상승 제한적


# ── [D] MA 정배열 점수 (0~10) — MA120 추가 강화 ──────────────────────────────
def calc_ma_score(df: pd.DataFrame) -> tuple:
    """
    MA5 > MA20 > MA60 > MA120 정배열 체크
    Returns: (score 0~10, alignment_label)
    """
    try:
        close = df["Close"]
        ma5   = close.rolling(5).mean().iloc[-1]
        ma20  = close.rolling(20).mean().iloc[-1]
        ma60  = close.rolling(60).mean().iloc[-1]
        ma120 = close.rolling(120).mean().iloc[-1] if len(close) >= 120 else None

        if any(pd.isna(v) for v in [ma5, ma20, ma60]):
            return 0, "insufficient"

        if ma120 is not None and not pd.isna(ma120):
            if ma5 > ma20 > ma60 > ma120:
                return 10, "full_bull"      # 완전 정배열
            if ma5 > ma20 > ma60:
                return 7, "3ma_bull"
            if ma5 > ma20:
                return 3, "2ma_bull"
        else:
            if ma5 > ma20 > ma60:
                return 7, "3ma_bull"
            if ma5 > ma20:
                return 3, "2ma_bull"

        return 0, "bearish"

    except Exception as e:
        logging.debug(f"ma_score error: {e}")
        return 0, "error"


# ── OHLCV 수집 ────────────────────────────────────────────────────────────────
def fetch_ohlcv(ticker: str, end_date: datetime) -> pd.DataFrame | None:
    """FinanceDataReader로 LOOKBACK_DAYS 일봉 수집"""
    try:
        start = (end_date - timedelta(days=LOOKBACK_DAYS * 2)).strftime("%Y-%m-%d")
        end   = end_date.strftime("%Y-%m-%d")
        df    = fdr.DataReader(ticker, start, end)
        if df is None or len(df) < 20:
            return None
        df = df.sort_index()
        # 최근 LOOKBACK_DAYS 봉만 사용
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


# ── 종목별 기술적 점수 통합 계산 ─────────────────────────────────────────────
def analyze_ticker(ticker: str, end_date: datetime) -> dict | None:
    df = fetch_ohlcv(ticker, end_date)
    if df is None:
        return None

    try:
        poc_score,   poc_price,   poc_pct  = calc_poc_score(df)
        sr_score,    sr_support,  sr_gap   = calc_sr_score(df)
        rsi_val                            = calc_rsi(df["Close"])
        rsi_score                          = calc_rsi_score(rsi_val)
        ma_score,    ma_label              = calc_ma_score(df)

        tech_detail_score = poc_score + sr_score + rsi_score + ma_score

        return {
            "ticker":            ticker.zfill(6),
            "poc_score":         poc_score,
            "poc_price":         poc_price,
            "poc_pct":           poc_pct,
            "sr_score":          sr_score,
            "sr_support":        sr_support,
            "sr_gap_pct":        sr_gap,
            "rsi_score":         rsi_score,
            "rsi":               rsi_val,
            "ma_score":          ma_score,
            "ma_label":          ma_label,
            "tech_detail_score": tech_detail_score,
        }
    except Exception as e:
        logging.debug(f"analyze_ticker {ticker} error: {e}")
        return None


# ── 메인 ──────────────────────────────────────────────────────────────────────
def main():
    logging.info("=== sfd_technical_analyzer v1.0 START ===")
    logging.info(f"BASE_DIR:   {BASE_DIR}")
    logging.info(f"SCIPY:      {SCIPY_AVAILABLE}")

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

    df_out = pd.DataFrame(results).sort_values("tech_detail_score", ascending=False).reset_index(drop=True)
    df_out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    # 히스토리 저장
    hist_path = os.path.join(
        HISTORY_DIR,
        f"sfd_technical_{end_date.strftime('%Y%m%d')}.csv"
    )
    df_out.to_csv(hist_path, index=False, encoding="utf-8-sig")

    elapsed = int(time.time() - START_TIME)
    top5    = df_out.head(5)[["ticker", "tech_detail_score", "poc_score", "sr_score", "ma_label"]].to_string(index=False)
    logging.info(f"DONE | ok={ok_cnt} fail={fail_cnt} elapsed={elapsed}s")
    logging.info(f"TOP5:\n{top5}")
    print(f"[OK] tech_analyzer | ok={ok_cnt} | fail={fail_cnt} | elapsed={elapsed}s")
    print(f"  -> {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
