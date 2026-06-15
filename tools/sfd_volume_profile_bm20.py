# sfd_volume_profile_bm20.py | BM-20 | Layer 2.8 | Claude (Anthropic) 2026-06-15
# Deploy to: SFC_DataPipeline/tools/sfd_volume_profile_bm20.py
#
# [BM-20] Volume Profile Engine — POC / VAH / VAL / Value Area
#
# [기존 calc_poc_score 한계]
#   - POC 위치만 판단 (현재가 > POC 여부)
#   - VAH / VAL 없음 → Value Area 돌파 패턴 미감지
#
# [BM-20 추가 기능]
#   [A] POC  : 가장 거래량 집중된 가격대
#   [B] VAH  : Value Area High — POC 기준 위로 누적 70% 도달 상한
#   [C] VAL  : Value Area Low  — POC 기준 아래로 누적 70% 도달 하한
#   [D] 위치 패턴 점수 (0~20pt):
#       현재가 > VAH 돌파   → +20pt (강한 상승 돌파)
#       현재가 ≈ VAH ±2%   → +15pt (VAH 근접 저항 테스트)
#       VAL < 현재가 < VAH  → +8pt  (Value Area 내 안정)
#       현재가 ≈ VAL ±2%   → +5pt  (VAL 근접 지지 테스트)
#       현재가 < VAL        → 0pt   (매물대 하방 이탈)
#   [E] POC 재확인 보너스 (현재가 POC ±1% 이내 재접근 후 반등) → +3pt
#
# [aggregator 연동]
#   출력: vp_score(0~20), poc_price, vah_price, val_price,
#         vp_label, va_width_pct, poc_position
#
# [백테스트 근거 (28,930건 DB)]
#   VAH 돌파 패턴 D+5 적중률 → backtest_analyzer로 검증 예정
#   현재는 TV Essential 시각 관찰 기반 설계 → 추후 PRISM weight 조정

import numpy as np
import pandas as pd
import logging

# ── Value Area 기본 파라미터
VA_PERCENT   = 0.70   # Value Area = 전체 거래량의 70%
VOL_BINS     = 30     # v1.5의 20 → BM-20은 30으로 정밀도 향상
VAH_NEAR_PCT = 2.0    # VAH 근접 판정 ±%
VAL_NEAR_PCT = 2.0    # VAL 근접 판정 ±%
POC_NEAR_PCT = 1.0    # POC 재접근 판정 ±%


def calc_volume_profile(df: pd.DataFrame) -> dict:
    """
    Volume Profile 전체 계산: POC / VAH / VAL / Value Area

    Returns:
        {
          'poc_price': float,
          'vah_price': float,
          'val_price': float,
          'va_width_pct': float,   # (VAH - VAL) / POC * 100
          'vol_bins': array,       # 가격대별 거래량 (시각화용)
          'bin_centers': array,    # 각 bin 중심 가격
        }
    """
    try:
        close  = df["Close"].values
        volume = df["Volume"].values
        n      = len(close)

        if n < 10:
            return _empty_vp()

        price_min = close.min()
        price_max = close.max()
        if price_max == price_min:
            return _empty_vp()

        # ── 가격대별 거래량 히스토그램
        bins        = np.linspace(price_min, price_max, VOL_BINS + 1)
        bin_centers = (bins[:-1] + bins[1:]) / 2
        bin_idx     = np.clip(np.digitize(close, bins) - 1, 0, VOL_BINS - 1)

        vol_by_bin = np.zeros(VOL_BINS)
        for i, v in zip(bin_idx, volume):
            vol_by_bin[i] += v

        total_vol = vol_by_bin.sum()
        if total_vol == 0:
            return _empty_vp()

        # ── POC: 최대 거래량 bin
        poc_bin   = int(np.argmax(vol_by_bin))
        poc_price = float(bin_centers[poc_bin])

        # ── Value Area: POC에서 위/아래로 확장, 누적 70% 도달
        va_target = total_vol * VA_PERCENT
        va_vol    = vol_by_bin[poc_bin]
        above_idx = poc_bin + 1
        below_idx = poc_bin - 1
        vah_bin   = poc_bin
        val_bin   = poc_bin

        while va_vol < va_target:
            add_above = vol_by_bin[above_idx] if above_idx < VOL_BINS else 0
            add_below = vol_by_bin[below_idx] if below_idx >= 0       else 0

            if add_above == 0 and add_below == 0:
                break

            # 더 많은 거래량 쪽으로 먼저 확장 (TV 표준 방식)
            if add_above >= add_below:
                va_vol   += add_above
                vah_bin   = above_idx
                above_idx += 1
            else:
                va_vol   += add_below
                val_bin   = below_idx
                below_idx -= 1

        vah_price    = float(bin_centers[vah_bin])
        val_price    = float(bin_centers[val_bin])
        va_width_pct = round((vah_price - val_price) / poc_price * 100, 2) if poc_price > 0 else 0.0

        return {
            "poc_price":    round(poc_price, 0),
            "vah_price":    round(vah_price, 0),
            "val_price":    round(val_price, 0),
            "va_width_pct": va_width_pct,
            "vol_bins":     vol_by_bin,
            "bin_centers":  bin_centers,
            "total_vol":    total_vol,
            "poc_bin":      poc_bin,
        }

    except Exception as e:
        logging.debug(f"calc_volume_profile error: {e}")
        return _empty_vp()


def _empty_vp() -> dict:
    return {
        "poc_price": 0.0, "vah_price": 0.0, "val_price": 0.0,
        "va_width_pct": 0.0, "vol_bins": np.array([]),
        "bin_centers": np.array([]), "total_vol": 0, "poc_bin": -1,
    }


def calc_vp_score(df: pd.DataFrame) -> tuple:
    """
    [BM-20] Volume Profile 점수 (0~20pt)

    Returns:
        (score, poc_price, vah_price, val_price, vp_label, va_width_pct, poc_position)

    poc_position: 'above_vah' | 'near_vah' | 'in_va' | 'near_val' | 'below_val' | 'at_poc'
    """
    try:
        vp = calc_volume_profile(df)

        poc_price    = vp["poc_price"]
        vah_price    = vp["vah_price"]
        val_price    = vp["val_price"]
        va_width_pct = vp["va_width_pct"]

        if poc_price == 0:
            return 0, 0.0, 0.0, 0.0, "insufficient", 0.0, "unknown"

        current = float(df["Close"].values[-1])

        # ── 현재가 위치 판정 기준
        vah_near_lower = vah_price * (1 - VAH_NEAR_PCT / 100)
        val_near_upper = val_price * (1 + VAL_NEAR_PCT / 100)
        poc_near_upper = poc_price * (1 + POC_NEAR_PCT / 100)
        poc_near_lower = poc_price * (1 - POC_NEAR_PCT / 100)

        # ── POC 재접근 보너스 (+3pt)
        # 최근 3봉 중 POC 근접했다가 현재 POC 위로 회복
        close_arr = df["Close"].values
        poc_revisit_bonus = 0
        if len(close_arr) >= 4:
            recent_low   = close_arr[-4:-1].min()
            was_near_poc = poc_near_lower <= recent_low <= poc_near_upper
            now_above_poc = current > poc_price
            if was_near_poc and now_above_poc:
                poc_revisit_bonus = 3

        # ── 위치별 점수 판정
        if current > vah_price:
            pct_above_vah = (current - vah_price) / vah_price * 100
            if pct_above_vah <= 3.0:
                score, label, position = 20, "vah_breakout_fresh",    "above_vah"
            elif pct_above_vah <= 8.0:
                score, label, position = 16, "vah_breakout_extended", "above_vah"
            else:
                score, label, position = 12, "vah_breakout_far",      "above_vah"

        elif vah_near_lower <= current <= vah_price:
            score, label, position = 15, "near_vah_testing", "near_vah"

        elif val_price < current < vah_price:
            if poc_near_lower <= current <= poc_near_upper:
                score, label, position = 10, "at_poc", "at_poc"
            else:
                pct_in_va = (current - val_price) / (vah_price - val_price + 1e-9) * 100
                if pct_in_va >= 60:
                    score, label, position = 10, "in_va_upper", "in_va"
                elif pct_in_va >= 40:
                    score, label, position = 8,  "in_va_mid",   "in_va"
                else:
                    score, label, position = 6,  "in_va_lower", "in_va"

        elif val_price <= current <= val_near_upper:
            score, label, position = 5, "near_val_support", "near_val"

        else:
            pct_below_val = (val_price - current) / val_price * 100 if val_price > 0 else 0
            if pct_below_val <= 3.0:
                score, label, position = 2, "below_val_slight", "below_val"
            else:
                score, label, position = 0, "below_val_broken", "below_val"

        final_score = min(score + poc_revisit_bonus, 20)
        if poc_revisit_bonus > 0:
            label += "_poc_revisit"

        return (
            final_score,
            round(poc_price, 0),
            round(vah_price, 0),
            round(val_price, 0),
            label,
            va_width_pct,
            position,
        )

    except Exception as e:
        logging.debug(f"vp_score error: {e}")
        return 0, 0.0, 0.0, 0.0, "error", 0.0, "error"


# ── 단독 실행 검증 ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import FinanceDataReader as fdr
    from datetime import datetime, timedelta

    TEST_TICKERS = [
        ("005930", "삼성전자"),
        ("010120", "LS"),
        ("050610", "한전기술"),
        ("060980", "라이온켐텍"),
        ("000660", "SK하이닉스"),
    ]

    end   = datetime.now()
    start = (end - timedelta(days=120)).strftime("%Y-%m-%d")
    end_s = end.strftime("%Y-%m-%d")

    print("\n[BM-20 Volume Profile 검증]")
    print(f"{'종목':<16} {'POC':>8} {'VAL':>8} {'VAH':>8} {'VA폭%':>6} "
          f"{'현재가':>8} {'위치':<30} {'점수':>4}")
    print("-" * 95)

    for ticker, name in TEST_TICKERS:
        try:
            df = fdr.DataReader(ticker, start, end_s).tail(60)
            if df is None or len(df) < 20:
                print(f"{name}({ticker})  데이터 없음")
                continue

            score, poc, vah, val, label, va_w, pos = calc_vp_score(df)
            current = df["Close"].values[-1]

            print(f"{name}({ticker})  "
                  f"{poc:>8,.0f} {val:>8,.0f} {vah:>8,.0f} {va_w:>6.1f}% "
                  f"{current:>8,.0f} {label:<35} {score:>3}pt")
        except Exception as e:
            print(f"{name}({ticker})  ERROR: {e}")

    print("\n[점수 체계]")
    print("  VAH 돌파 (신선, ≤3%)  : 20pt")
    print("  VAH 돌파 (확장, ≤8%)  : 16pt")
    print("  VAH 돌파 (원거리)     : 12pt")
    print("  VAH 근접 테스트       : 15pt")
    print("  VA 내 상단 (60%↑)    : 10pt")
    print("  POC 위치              : 10pt")
    print("  VA 내 중간 (40~60%)  :  8pt")
    print("  VA 내 하단 (40%↓)    :  6pt")
    print("  VAL 근접 지지         :  5pt")
    print("  VAL 하방 소폭 (≤3%)   :  2pt")
    print("  VAL 하방 이탈         :  0pt")
    print("  POC 재접근 보너스     : +3pt (max 20)")
