# ============================================================
# 파일명: sfd_trend_filter.py
# 버전: v1.0
# 작성: Claude (Anthropic) — 2026.06.15
# 위치: tools/sfd_trend_filter.py
#
# [기능] 중단기 우상향 종목 필터
# PRISM 입력 전 추세 정배열 종목만 선별
#
# [필터 조건 AND]
# ① 정배열: ma20 > ma60 > ma120
# ② 52주 위치: 현재가 >= 52주 최저 × 1.3 AND <= 52주 최고 × 0.85
# ③ 목표가 괴리: analyst_target > 현재가 × 1.20 (데이터 있을 때만)
#
# [입력]
# sfd_technical_latest.csv (ma20/ma60/ma120/high_52w/low_52w)
# sfd_master_signal_latest.csv (prev_close/current_price)
# sfd_fundamental_latest.csv (analyst_target, 옵션)
#
# [출력]
# sfd_trend_filter_latest.csv
#   columns: stock_code, corp_name, trend_pass, fail_reason,
#            ma_aligned, price_position, target_gap
# ============================================================

from __future__ import annotations

import os
import logging
from pathlib import Path
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv

# ── 경로 설정 ─────────────────────────────────────────────
IS_GITHUB = os.getenv("GITHUB_ACTIONS") == "true"

if IS_GITHUB:
    OUTPUT_DIR = Path("/tmp/sfd/outputs/latest")
    ROOT       = Path(".")
else:
    ROOT       = Path(r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline")
    OUTPUT_DIR = ROOT / "outputs" / "latest"
    _ENV = ROOT / ".env"
    if _ENV.exists():
        load_dotenv(_ENV, override=True)

# ── 입력 파일 ──────────────────────────────────────────────
TECHNICAL_CSV    = OUTPUT_DIR / "sfd_technical_latest.csv"
SIGNAL_CSV       = OUTPUT_DIR / "sfd_master_signal_latest.csv"
FUNDAMENTAL_CSV  = OUTPUT_DIR / "sfd_fundamental_latest.csv"

# ── 출력 파일 ──────────────────────────────────────────────
OUT_CSV  = OUTPUT_DIR / "sfd_trend_filter_latest.csv"
LOG_PATH = ROOT / "logs" / "sfd_trend_filter.log"

# ── 파라미터 ──────────────────────────────────────────────
MA_ALIGNED_REQUIRED  = True    # ① 정배열 필수
PRICE_POS_MIN        = 1.30    # ② 52주 최저 대비 최소 +30%
PRICE_POS_MAX        = 0.85    # ② 52주 최고 대비 최대 85% 이내
TARGET_GAP_MIN       = 1.20    # ③ 목표가 괴리 최소 +20%
TARGET_GAP_REQUIRED  = False   # ③ 목표가 없으면 PASS (데이터 부재 허용)

LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    encoding="utf-8",
)


def _f(val, default=0.0) -> float:
    try:
        return float(str(val).replace(",", "").replace("원", "").replace("%", "").strip())
    except Exception:
        return default


def load_technical() -> pd.DataFrame:
    if not TECHNICAL_CSV.exists():
        print(f"[WARN] technical CSV 없음: {TECHNICAL_CSV}")
        return pd.DataFrame()
    return pd.read_csv(TECHNICAL_CSV, dtype=str)


def load_signal() -> pd.DataFrame:
    if not SIGNAL_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(SIGNAL_CSV, dtype=str)
    if "ticker" in df.columns and "stock_code" not in df.columns:
        df = df.rename(columns={"ticker": "stock_code"})
    return df


def load_fundamental() -> pd.DataFrame:
    if not FUNDAMENTAL_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(FUNDAMENTAL_CSV, dtype=str)
    if "ticker" in df.columns and "stock_code" not in df.columns:
        df = df.rename(columns={"ticker": "stock_code"})
    return df


def evaluate(tech_df: pd.DataFrame, signal_df: pd.DataFrame, fund_df: pd.DataFrame) -> pd.DataFrame:
    # signal을 기준으로 merge
    base = signal_df.copy() if not signal_df.empty else tech_df.copy()

    # technical merge
    if not tech_df.empty and "stock_code" in tech_df.columns:
        base = base.merge(tech_df, on="stock_code", how="left", suffixes=("", "_tech"))

    # fundamental merge (옵션)
    if not fund_df.empty and "stock_code" in fund_df.columns:
        base = base.merge(fund_df[["stock_code", "analyst_target"]], on="stock_code", how="left")
    else:
        base["analyst_target"] = None

    results = []
    pass_count = 0
    fail_count = 0

    for _, row in base.iterrows():
        code = str(row.get("stock_code", "")).strip()
        name = str(row.get("corp_name", row.get("name", ""))).strip()

        fail_reasons = []
        ma_aligned     = False
        price_position = None
        target_gap     = None

        # ── 현재가
        current_price = _f(row.get("current_price") or row.get("prev_close") or row.get("close", 0))

        # ── 조건 ①: 정배열 (ma20 > ma60 > ma120)
        ma20  = _f(row.get("ma20",  0))
        ma60  = _f(row.get("ma60",  0))
        ma120 = _f(row.get("ma120", 0))

        if ma20 > 0 and ma60 > 0 and ma120 > 0:
            ma_aligned = (ma20 > ma60 > ma120)
            if MA_ALIGNED_REQUIRED and not ma_aligned:
                fail_reasons.append(f"역배열(ma20={ma20:.0f}<ma60={ma60:.0f})")
        else:
            # MA 데이터 없으면 조건 스킵 (데이터 부재 허용)
            ma_aligned = None

        # ── 조건 ②: 52주 위치
        high_52w = _f(row.get("high_52w", 0))
        low_52w  = _f(row.get("low_52w",  0))

        if current_price > 0 and high_52w > 0 and low_52w > 0:
            above_low  = current_price >= low_52w  * PRICE_POS_MIN
            below_high = current_price <= high_52w * PRICE_POS_MAX
            price_position = current_price / high_52w if high_52w > 0 else None

            if not above_low:
                fail_reasons.append(f"52주최저근접({current_price:.0f}<{low_52w*PRICE_POS_MIN:.0f})")
            if not below_high:
                fail_reasons.append(f"52주고점초과({current_price:.0f}>{high_52w*PRICE_POS_MAX:.0f})")

        # ── 조건 ③: 목표가 괴리
        analyst_target = _f(row.get("analyst_target", 0))
        if analyst_target > 0 and current_price > 0:
            target_gap = analyst_target / current_price
            if target_gap < TARGET_GAP_MIN:
                fail_reasons.append(f"목표가괴리부족({target_gap*100:.0f}%<{TARGET_GAP_MIN*100:.0f}%)")
        elif TARGET_GAP_REQUIRED:
            fail_reasons.append("목표가데이터없음")

        trend_pass = len(fail_reasons) == 0
        if trend_pass:
            pass_count += 1
        else:
            fail_count += 1

        results.append({
            "stock_code":     code,
            "corp_name":      name,
            "trend_pass":     trend_pass,
            "fail_reason":    " | ".join(fail_reasons) if fail_reasons else "OK",
            "ma_aligned":     ma_aligned,
            "ma20":           ma20 if ma20 > 0 else None,
            "ma60":           ma60 if ma60 > 0 else None,
            "ma120":          ma120 if ma120 > 0 else None,
            "price_position": f"{price_position*100:.1f}%" if price_position else None,
            "target_gap":     f"{target_gap*100:.1f}%" if target_gap else None,
            "current_price":  int(current_price) if current_price > 0 else None,
            "evaluated_at":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

    print(f"[TREND_FILTER] PASS: {pass_count}종목 / FAIL: {fail_count}종목 / 전체: {len(results)}종목")
    return pd.DataFrame(results)


def main() -> None:
    print(f"[INFO] sfd_trend_filter v1.0 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[INFO] 중단기 우상향 필터 시작")

    tech_df   = load_technical()
    signal_df = load_signal()
    fund_df   = load_fundamental()

    if tech_df.empty and signal_df.empty:
        print("[WARN] technical/signal 데이터 모두 없음 — 종료")
        return

    result_df = evaluate(tech_df, signal_df, fund_df)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    result_df.to_csv(str(OUT_CSV), index=False, encoding="utf-8-sig")

    pass_df = result_df[result_df["trend_pass"] == True]
    print(f"\n[DONE] 중단기 우상향 PASS 종목: {len(pass_df)}개")
    if not pass_df.empty:
        print("-" * 50)
        for _, r in pass_df.head(10).iterrows():
            print(f"  ✅ {r['stock_code']} {r['corp_name']} | {r['fail_reason']}")
    print(f"[OUT] {OUT_CSV}")
    logging.info(f"v1.0 완료: PASS={len(pass_df)}, FAIL={len(result_df)-len(pass_df)}")


if __name__ == "__main__":
    main()
