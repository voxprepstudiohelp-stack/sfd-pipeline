#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sfd_signal_quality.py — Signal Quality Monitor v1.0

기능:
  1. D+1 백테스트 아카이브(outputs/archive/) 전체 읽기
     → history/ 폴백 지원 (아카이브 미존재 시)
  2. 스코어 구간별 정밀도 집계:
       90+  (RESERVE_BUY)  / 80-90 / 70-80 (WATCH_ONLY) / <70
       각 구간: 총 신호 수, win_rate, avg_return, best/worst 종목
  3. 섹터별 win_rate 누적 테이블
  4. 이상 감지 (ANOMALY):
       - 스코어 구성요소(tech/news/investor/fund/theme) 전일 대비 50%↓ → WARN
       - RESERVE_BUY 0건 → WARN
  5. 출력:
       - --report  터미널 리포트
       - outputs/latest/sfd_signal_quality_latest.json  저장
  6. --days N  최근 N일만 분석

Usage:
  py tools/sfd_signal_quality.py
  py tools/sfd_signal_quality.py --report
  py tools/sfd_signal_quality.py --days 30 --report

Version: v1.0
Author:  Claude Sonnet 4.6 (2026-06-07)
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

# ── 경로 설정 ─────────────────────────────────────────────────────────────
import os
_HERE    = Path(__file__).resolve().parent
_ROOT    = _HERE.parent
_BASE    = Path(os.environ.get("SFD_BASE_DIR", str(_ROOT)))
_ARCHIVE = _BASE  / "outputs" / "archive"
_HISTORY = _ROOT  / "outputs" / "history"    # history는 항상 repo 기준
_LATEST  = _BASE  / "outputs" / "latest"
_DATA    = _BASE  / "data"

COMPANY_MASTER = _DATA  / "sfd_company_master_v1.4_sector_filled.csv"
OUTPUT_JSON    = _LATEST / "sfd_signal_quality_latest.json"

# ── 상수 ─────────────────────────────────────────────────────────────────
SCORE_BANDS = [
    ("90+",   90, 9999),
    ("80-90", 80, 90),
    ("70-80", 70, 80),
    ("<70",    0, 70),
]
COMPONENT_COLS  = ["tech_score", "news_score", "investor_score",
                   "fund_score", "theme_score"]
ANOMALY_DROP    = 50.0   # % 임계값
MIN_DATES_FULL  = 2      # return_d1 계산에 필요한 최소 날짜 수


# ═══════════════════════════════════════════════════════════════════════════
# 1. 데이터 로드
# ═══════════════════════════════════════════════════════════════════════════

def scan_dates(days: int | None = None) -> list[str]:
    """
    YYYYMMDD 날짜 목록을 반환.
    archive/ 우선, 없으면 history/ 에서 sfd_master_signal_{date}.csv 스캔.
    """
    dates = set()

    if _ARCHIVE.exists():
        for d in _ARCHIVE.iterdir():
            if d.is_dir() and len(d.name) == 8 and d.name.isdigit():
                sig = d / "sfd_signal.csv"
                if sig.exists():
                    dates.add(d.name)

    if not dates and _HISTORY.exists():
        for f in _HISTORY.glob("sfd_master_signal_????????.csv"):
            stem = f.stem                           # sfd_master_signal_20260529
            date_part = stem.split("_")[-1]
            if len(date_part) == 8 and date_part.isdigit():
                dates.add(date_part)

    sorted_dates = sorted(dates)
    if days:
        sorted_dates = sorted_dates[-days:]
    return sorted_dates


def _load_signal_csv(date_str: str) -> pd.DataFrame | None:
    """archive/{date}/sfd_signal.csv 또는 history/sfd_master_signal_{date}.csv 읽기."""
    candidates = [
        _ARCHIVE / date_str / "sfd_signal.csv",
        _HISTORY / f"sfd_master_signal_{date_str}.csv",
    ]
    for path in candidates:
        if path.exists():
            try:
                df = pd.read_csv(path, encoding="utf-8-sig",
                                 dtype={"ticker": str}, low_memory=False)
                # ticker 정규화
                if "ticker" in df.columns:
                    df["ticker"] = df["ticker"].astype(str).str.zfill(6)
                elif "stock_code" in df.columns:
                    df = df.rename(columns={"stock_code": "ticker"})
                    df["ticker"] = df["ticker"].astype(str).str.zfill(6)
                # signal 컬럼 통일
                if "signal_label" not in df.columns and "signal" in df.columns:
                    df = df.rename(columns={"signal": "signal_label"})
                df["_date"] = date_str
                return df
            except Exception as e:
                print(f"[SQ] WARN: {path} 읽기 실패: {e}")
    return None


def _load_close_csv(date_str: str) -> pd.DataFrame | None:
    """archive/{date}/sfd_prev_close.csv 읽기."""
    path = _ARCHIVE / date_str / "sfd_prev_close.csv"
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, encoding="utf-8-sig",
                         dtype={"ticker": str}, low_memory=False)
        if "ticker" in df.columns:
            df["ticker"] = df["ticker"].astype(str).str.zfill(6)
        # 종가 컬럼 탐지
        close_col = next(
            (c for c in ["close", "Close", "prev_close", "close_price"]
             if c in df.columns), None
        )
        if close_col is None:
            return None
        return df[["ticker", close_col]].rename(columns={close_col: "close"})
    except Exception:
        return None


def load_all_frames(dates: list[str]) -> dict[str, pd.DataFrame]:
    """날짜 → 신호 DataFrame 딕셔너리."""
    frames = {}
    for d in dates:
        df = _load_signal_csv(d)
        if df is not None and len(df) > 0:
            frames[d] = df
    return frames


def attach_return_d1(dates: list[str]) -> pd.DataFrame | None:
    """
    연속 날짜의 close 파일을 페어링해 return_d1 / win_flag 계산.
    사용 가능한 페어가 없으면 None 반환.
    """
    rows = []
    close_cache: dict[str, pd.DataFrame | None] = {}

    def _get_close(d: str):
        if d not in close_cache:
            close_cache[d] = _load_close_csv(d)
        return close_cache[d]

    for i, date_str in enumerate(dates):
        sig_df = _load_signal_csv(date_str)
        if sig_df is None:
            continue

        # entry close: 신호 당일
        entry_close = _get_close(date_str)

        # exit close: 다음 존재하는 날짜의 close
        exit_close = None
        for j in range(i + 1, min(i + 6, len(dates))):
            exit_close = _get_close(dates[j])
            if exit_close is not None:
                break

        if entry_close is None or exit_close is None:
            continue

        entry = entry_close.rename(columns={"close": "close_entry"})
        exit_ = exit_close.rename(columns={"close": "close_exit"})
        merged = sig_df.merge(entry, on="ticker", how="left") \
                       .merge(exit_,  on="ticker", how="left")
        valid = merged["close_entry"].notna() & merged["close_exit"].notna() \
                & (merged["close_entry"] > 0)
        merged["return_d1"] = None
        merged.loc[valid, "return_d1"] = (
            (merged.loc[valid, "close_exit"] - merged.loc[valid, "close_entry"])
            / merged.loc[valid, "close_entry"] * 100
        ).round(4)
        merged["win_flag"] = merged["return_d1"].apply(
            lambda x: bool(x > 0) if pd.notna(x) else None
        )
        rows.append(merged)

    if not rows:
        return None
    return pd.concat(rows, ignore_index=True)


def load_sector_map() -> dict[str, str]:
    """Returns {ticker: sector_major}."""
    if not COMPANY_MASTER.exists():
        return {}
    try:
        df = pd.read_csv(COMPANY_MASTER, encoding="utf-8-sig",
                         dtype={"stock_code": str}, low_memory=False)
        df["stock_code"] = df["stock_code"].str.strip().str.zfill(6)
        return dict(zip(df["stock_code"], df["sector_major"].fillna("기타")))
    except Exception:
        return {}


# ═══════════════════════════════════════════════════════════════════════════
# 2. 스코어 구간 분석
# ═══════════════════════════════════════════════════════════════════════════

def analyze_score_bands(combined: pd.DataFrame,
                        all_frames: dict[str, pd.DataFrame]) -> dict:
    """
    combined: return_d1 있는 데이터 (없으면 None)
    all_frames: 전체 날짜 신호 (카운트 기준)
    """
    # 전체 신호 집계 (return 없어도 카운트 가능)
    full_df = pd.concat(all_frames.values(), ignore_index=True) if all_frames else pd.DataFrame()

    result = {}
    for label, lo, hi in SCORE_BANDS:
        band = {}

        # 총 신호 수 (all_frames 기준)
        if not full_df.empty and "total_score" in full_df.columns:
            mask = (pd.to_numeric(full_df["total_score"], errors="coerce") >= lo) & \
                   (pd.to_numeric(full_df["total_score"], errors="coerce") < hi)
            band["count"] = int(mask.sum())
        else:
            band["count"] = 0

        # win_rate / avg_return / best / worst (combined 기준)
        if combined is not None and "return_d1" in combined.columns and \
                "total_score" in combined.columns:
            sub = combined[
                (pd.to_numeric(combined["total_score"], errors="coerce") >= lo) &
                (pd.to_numeric(combined["total_score"], errors="coerce") < hi)
            ]
            valid = sub[sub["return_d1"].notna()]
            if len(valid) > 0:
                wr = sub["win_flag"].dropna()
                band["win_rate"]   = round(float(wr.mean()) * 100, 1) if len(wr) > 0 else None
                band["avg_return"] = round(float(valid["return_d1"].mean()), 3)
                # best / worst ticker
                best_row  = valid.loc[valid["return_d1"].idxmax()]
                worst_row = valid.loc[valid["return_d1"].idxmin()]
                name_col  = "name" if "name" in valid.columns else "ticker"
                band["best"]  = {"ticker": best_row["ticker"],
                                  "name": str(best_row.get(name_col, "")),
                                  "return_d1": round(float(best_row["return_d1"]), 2)}
                band["worst"] = {"ticker": worst_row["ticker"],
                                  "name": str(worst_row.get(name_col, "")),
                                  "return_d1": round(float(worst_row["return_d1"]), 2)}
                band["sample_n"] = int(len(valid))
            else:
                band["win_rate"] = band["avg_return"] = None
                band["best"] = band["worst"] = None
                band["sample_n"] = 0
        else:
            band["win_rate"] = band["avg_return"] = None
            band["best"] = band["worst"] = None
            band["sample_n"] = 0

        result[label] = band
    return result


# ═══════════════════════════════════════════════════════════════════════════
# 3. 섹터별 win_rate 집계
# ═══════════════════════════════════════════════════════════════════════════

def analyze_sectors(combined: pd.DataFrame | None,
                    sector_map: dict) -> dict:
    if combined is None or combined.empty or "return_d1" not in combined.columns:
        return {}

    # RESERVE_BUY + WATCH_ONLY 만 대상
    active_signals = {"RESERVE_BUY", "WATCH_ONLY"}
    sig_col = "signal_label" if "signal_label" in combined.columns else None
    if sig_col:
        sub = combined[combined[sig_col].isin(active_signals)].copy()
    else:
        sub = combined.copy()

    sub["sector_major"] = sub["ticker"].map(sector_map).fillna("기타")
    valid = sub[sub["return_d1"].notna()]
    if valid.empty:
        return {}

    result = {}
    for sector, grp in valid.groupby("sector_major"):
        wf = grp["win_flag"].dropna()
        result[str(sector)] = {
            "count":       int(len(grp)),
            "win_rate":    round(float(wf.mean()) * 100, 1) if len(wf) > 0 else None,
            "avg_return":  round(float(grp["return_d1"].mean()), 3),
            "sample_n":    int(len(grp)),
        }

    # win_rate 내림차순 정렬
    result = dict(sorted(result.items(),
                          key=lambda x: x[1]["win_rate"] or -1, reverse=True))
    return result


# ═══════════════════════════════════════════════════════════════════════════
# 4. 이상 감지
# ═══════════════════════════════════════════════════════════════════════════

def detect_anomalies(all_frames: dict[str, pd.DataFrame]) -> list[dict]:
    anomalies = []
    dates = sorted(all_frames.keys())

    if len(dates) < 2:
        return anomalies

    # 각 날짜별 구성요소 평균 계산
    comp_means: dict[str, dict[str, float]] = {}
    for d, df in all_frames.items():
        means = {}
        for col in COMPONENT_COLS:
            if col in df.columns:
                val = pd.to_numeric(df[col], errors="coerce").mean()
                means[col] = float(val) if pd.notna(val) else 0.0
        comp_means[d] = means

    # 전일 대비 50%↓ 감지 (최근 연속 2일)
    for i in range(1, len(dates)):
        today_d = dates[i]
        prev_d  = dates[i - 1]
        today_m = comp_means.get(today_d, {})
        prev_m  = comp_means.get(prev_d, {})

        for col in COMPONENT_COLS:
            t_val = today_m.get(col, 0.0)
            p_val = prev_m.get(col, 0.0)
            if p_val <= 0:
                continue
            drop_pct = (t_val - p_val) / p_val * 100
            if drop_pct <= -ANOMALY_DROP:
                anomalies.append({
                    "type":      "COMPONENT_DROP",
                    "component": col,
                    "date":      today_d,
                    "prev_date": prev_d,
                    "prev_avg":  round(p_val, 3),
                    "today_avg": round(t_val, 3),
                    "drop_pct":  round(drop_pct, 1),
                    "message":   (f"{col} 전일 대비 {drop_pct:.1f}% 하락 "
                                  f"({prev_d} {p_val:.2f} -> {today_d} {t_val:.2f})"),
                })

    # RESERVE_BUY 0건 감지 (가장 최근 날짜)
    latest_date = dates[-1]
    latest_df   = all_frames[latest_date]
    sig_col = "signal_label" if "signal_label" in latest_df.columns else None
    if sig_col:
        reserve_count = int((latest_df[sig_col] == "RESERVE_BUY").sum())
        if reserve_count == 0:
            anomalies.append({
                "type":    "RESERVE_ZERO",
                "date":    latest_date,
                "message": f"RESERVE_BUY 0건 ({latest_date}) -- 임계값 또는 데이터 확인 필요",
            })

    return anomalies


# ═══════════════════════════════════════════════════════════════════════════
# 5. 터미널 리포트
# ═══════════════════════════════════════════════════════════════════════════

def print_report(result: dict) -> None:
    has_return = result.get("has_return_data", False)
    dates      = result.get("dates_analyzed", [])
    bands      = result.get("score_bands", {})
    sectors    = result.get("sector_win_rates", {})
    anomalies  = result.get("anomalies", [])

    print()
    print("=" * 68)
    print("  SFD SIGNAL QUALITY REPORT v1.0")
    print(f"  분석 기간: {dates[0] if dates else 'N/A'} ~ {dates[-1] if dates else 'N/A'}"
          f"  ({len(dates)}일)")
    print(f"  return_d1 {'계산됨' if has_return else '데이터 없음 (카운트만)'}")
    print("=" * 68)

    # 스코어 구간
    print("\n[스코어 구간별 정밀도]")
    hdr = f"  {'구간':<10} {'신호수':>6} {'샘플':>6} {'win_rate':>9} {'avg_return':>11}  best / worst"
    print(hdr)
    print("  " + "-" * 65)
    for band_label, lo, hi in SCORE_BANDS:
        b = bands.get(band_label, {})
        cnt  = b.get("count", 0)
        sn   = b.get("sample_n", 0)
        wr   = f"{b['win_rate']:.1f}%" if b.get("win_rate") is not None else "  N/A"
        ar   = f"{b['avg_return']:+.2f}%" if b.get("avg_return") is not None else "    N/A"
        best_str  = ""
        worst_str = ""
        if b.get("best"):
            best_str  = f"{b['best']['ticker']}({b['best']['return_d1']:+.1f}%)"
        if b.get("worst"):
            worst_str = f"{b['worst']['ticker']}({b['worst']['return_d1']:+.1f}%)"
        bw = f"{best_str} / {worst_str}" if best_str or worst_str else ""
        print(f"  {band_label:<10} {cnt:>6} {sn:>6} {wr:>9} {ar:>11}  {bw}")

    # 섹터 win_rate
    if sectors:
        print("\n[섹터별 win_rate (RESERVE+WATCH 대상)]")
        print(f"  {'섹터':<34} {'건수':>5} {'win_rate':>9} {'avg_return':>11}")
        print("  " + "-" * 62)
        for sector, s in list(sectors.items())[:15]:
            wr  = f"{s['win_rate']:.1f}%" if s.get("win_rate") is not None else "  N/A"
            ar  = f"{s['avg_return']:+.2f}%" if s.get("avg_return") is not None else "    N/A"
            print(f"  {sector[:34]:<34} {s['count']:>5} {wr:>9} {ar:>11}")
    else:
        print("\n[섹터별 win_rate]  return_d1 데이터 필요")

    # 이상 감지
    print("\n[이상 감지 (ANOMALY)]")
    if anomalies:
        for a in anomalies:
            print(f"  [WARN] {a['message']}")
    else:
        print("  이상 없음")

    print()
    print("=" * 68)
    print(f"  저장: {OUTPUT_JSON}")
    print("=" * 68)
    print()


# ═══════════════════════════════════════════════════════════════════════════
# 메인
# ═══════════════════════════════════════════════════════════════════════════

def run(days: int | None = None, report: bool = False) -> None:
    print(f"[SQ] Signal Quality Monitor v1.0 | days={days or 'all'} | "
          f"report={report}")
    _LATEST.mkdir(parents=True, exist_ok=True)

    # 날짜 목록 수집
    dates = scan_dates(days)
    if not dates:
        print("[SQ] insufficient data: 분석 가능한 날짜 없음 (archive/ 및 history/ 비어있음)")
        sys.exit(0)

    print(f"[SQ] {len(dates)}일 데이터 감지: {dates[0]} ~ {dates[-1]}")

    # 신호 데이터 로드
    all_frames = load_all_frames(dates)
    if not all_frames:
        print("[SQ] insufficient data: 신호 CSV 읽기 실패")
        sys.exit(0)

    # return_d1 계산 (archive close 페어링)
    combined     = None
    has_return   = False
    if len(dates) >= MIN_DATES_FULL and _ARCHIVE.exists():
        combined = attach_return_d1(dates)
        has_return = combined is not None and \
                     "return_d1" in combined.columns and \
                     combined["return_d1"].notna().any()
    print(f"[SQ] return_d1 계산: {'완료' if has_return else '불가 (close 파일 없음)'}")

    # 섹터 맵
    sector_map = load_sector_map()
    print(f"[SQ] sector_map: {len(sector_map)}종목")

    # 분석
    score_bands   = analyze_score_bands(combined if has_return else None, all_frames)
    sector_wr     = analyze_sectors(combined if has_return else None, sector_map)
    anomalies     = detect_anomalies(all_frames)

    # 데이터 품질 요약
    total_recs = sum(len(df) for df in all_frames.values())
    return_cov = 0.0
    if combined is not None and "return_d1" in combined.columns and len(combined) > 0:
        return_cov = round(combined["return_d1"].notna().mean(), 3)

    result = {
        "generated_at":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "analysis_days":   len(dates),
        "days_requested":  days,
        "date_range":      {"start": dates[0], "end": dates[-1]},
        "has_return_data": has_return,
        "score_bands":     score_bands,
        "sector_win_rates": sector_wr,
        "anomalies":       anomalies,
        "data_quality": {
            "total_records":  total_recs,
            "return_coverage": return_cov,
            "dates_with_data": len(all_frames),
        },
        "dates_analyzed": dates,
    }

    # JSON 저장
    OUTPUT_JSON.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"[SQ] 저장 완료: {OUTPUT_JSON}")

    # 이상 감지 요약
    if anomalies:
        print(f"[SQ] ANOMALY {len(anomalies)}건 감지:")
        for a in anomalies:
            print(f"     [WARN] {a['message']}")
    else:
        print("[SQ] 이상 없음")

    # 리포트 출력
    if report:
        result["dates_analyzed"] = dates   # for print_report
        print_report(result)
    else:
        # 간단 요약
        for label, _, _ in SCORE_BANDS:
            b = score_bands.get(label, {})
            wr_str = f"win={b['win_rate']:.1f}%" if b.get("win_rate") is not None else "win=N/A"
            print(f"[SQ] {label:<8} count={b.get('count',0):>4}  {wr_str}")
        print(f"[SQ] DONE | anomalies={len(anomalies)} | -> {OUTPUT_JSON}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SFD Signal Quality Monitor v1.0")
    parser.add_argument("--days",   type=int, default=None,
                        help="최근 N일만 분석 (기본: 전체)")
    parser.add_argument("--report", action="store_true",
                        help="터미널 리포트 출력")
    args = parser.parse_args()
    run(days=args.days, report=args.report)
