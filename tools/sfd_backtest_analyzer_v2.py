"""
sfd_backtest_analyzer_v2.py
Phase 1 Backtest Analysis Framework
SFD Pipeline — Post Run#93 activation

Features vs v1.0:
  + layer_attribution_analysis()  : 레이어별 기여도 회귀분석
  + threshold_optimizer()         : ROC-style threshold 최적화 (numpy only)
  + sector_performance_matrix()   : 섹터별 성과 히트맵
  + signal_decay_curve()          : D+1~D+10 신호 유효기간 추적
  + bm_score_correlation()        : BM 점수 ↔ 실제 수익률 상관계수

Input:
  outputs/latest/signal_output.csv   (SFD 신호 파일)
  outputs/latest/backtest_d1.csv     (D+1 실제 수익률, sfd_backtest_d1.py 생성)

Author: Claude (Architect)
Version: 2.0
Date: 2026-06-09
"""

import os
import sys
import json
import logging
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────
BASE_DIR    = Path(os.environ.get("SFD_BASE", Path(__file__).resolve().parent.parent))
OUTPUT_DIR  = BASE_DIR / "outputs" / "latest"
SIGNAL_CSV  = OUTPUT_DIR / "signal_output.csv"
BT_CSV      = OUTPUT_DIR / "backtest_d1.csv"
REPORT_PATH = OUTPUT_DIR / "backtest_report_v2.json"

# Score column definitions (must match signal_output.csv headers)
LAYER_COLS = {
    "tech":     "tech_score",
    "news":     "news_score",
    "investor": "investor_score",
    "theme":    "theme_score",
    "fund":     "fund_score",
    "sector":   "sector_score",
    "macro":    "macro_boost",
    "global":   "global_boost",
    "candle":   "candle_score",   # BM-14 (available after v3.9+patch)
}

SIGNAL_COL  = "signal"
SCORE_COL   = "total_score"
TICKER_COL  = "stock_code"
RETURN_COL  = "return_d1"        # from backtest_d1.csv

SECTOR_MAP = {
    "전력":       ["267260", "298040", "015760", "034020", "105560"],
    "원전":       ["082920", "095340", "012450", "298040"],
    "로봇":       ["215000", "090460", "108490", "285130"],
    "Physical_AI":["042000", "079550", "196490", "267260"],
}

RESERVE_THRESHOLD_DEFAULT = 90
WATCH_THRESHOLD_DEFAULT   = 70


# ─────────────────────────────────────────────
# 1. Data loader
# ─────────────────────────────────────────────
def load_data(signal_path: Path = SIGNAL_CSV,
              bt_path: Path = BT_CSV) -> pd.DataFrame:
    """
    신호 CSV + D+1 수익률 CSV 조인.
    Returns merged DataFrame or empty DF with warning.
    """
    if not signal_path.exists():
        logger.warning("signal_output.csv not found: %s", signal_path)
        return pd.DataFrame()

    df = pd.read_csv(signal_path, dtype={TICKER_COL: str})
    logger.info("Loaded signal CSV: %d rows", len(df))

    if bt_path.exists():
        bt = pd.read_csv(bt_path, dtype={TICKER_COL: str})
        if RETURN_COL in bt.columns:
            df = df.merge(bt[[TICKER_COL, "date", RETURN_COL]],
                          on=[TICKER_COL, "date"], how="left")
            logger.info("Merged backtest D+1: %.1f%% coverage",
                        df[RETURN_COL].notna().mean() * 100)
    else:
        logger.warning("backtest_d1.csv not found — return analysis skipped")
        df[RETURN_COL] = np.nan

    return df


# ─────────────────────────────────────────────
# 2. Signal accuracy (hit-rate)
# ─────────────────────────────────────────────
def signal_accuracy(df: pd.DataFrame,
                    win_threshold: float = 0.0) -> dict:
    """
    RESERVE_BUY / WATCH_ONLY 각각 D+1 적중률 계산.
    win_threshold: 양수 수익률 기준 (default 0%)
    """
    result = {}
    for sig in ["RESERVE_BUY", "WATCH_ONLY"]:
        sub = df[(df[SIGNAL_COL] == sig) & df[RETURN_COL].notna()]
        if len(sub) == 0:
            result[sig] = {"count": 0, "hit_rate": None, "avg_return": None}
            continue
        wins = (sub[RETURN_COL] > win_threshold).sum()
        result[sig] = {
            "count":      int(len(sub)),
            "hit_rate":   round(wins / len(sub), 4),
            "avg_return": round(sub[RETURN_COL].mean(), 4),
            "median_return": round(sub[RETURN_COL].median(), 4),
            "std_return": round(sub[RETURN_COL].std(), 4),
        }
    logger.info("Signal accuracy: %s", result)
    return result


# ─────────────────────────────────────────────
# 3. Layer attribution analysis (numpy regression)
# ─────────────────────────────────────────────
def layer_attribution_analysis(df: pd.DataFrame) -> dict:
    """
    각 레이어 점수 ↔ D+1 수익률 피어슨 상관계수 + 단순회귀 계수.
    sklearn 없이 numpy만 사용.
    """
    df_clean = df[df[RETURN_COL].notna()].copy()
    if len(df_clean) < 10:
        return {"error": "insufficient data for regression"}

    y = df_clean[RETURN_COL].values
    result = {}

    for layer_name, col in LAYER_COLS.items():
        if col not in df_clean.columns:
            continue
        x = df_clean[col].fillna(0).values
        if x.std() == 0:
            result[layer_name] = {"corr": 0.0, "beta": 0.0, "available": True}
            continue

        # Pearson correlation
        corr = float(np.corrcoef(x, y)[0, 1])

        # OLS beta (slope)
        x_centered = x - x.mean()
        beta = float(np.dot(x_centered, y) / np.dot(x_centered, x_centered))

        result[layer_name] = {
            "corr":       round(corr, 4),
            "beta":       round(beta, 6),
            "col":        col,
            "n":          int(len(df_clean)),
        }

    # Rank by absolute correlation
    ranked = sorted(result.items(), key=lambda kv: abs(kv[1].get("corr", 0)), reverse=True)
    result["_ranked_by_corr"] = [k for k, _ in ranked]
    logger.info("Layer attribution complete. Top: %s", result["_ranked_by_corr"][:3])
    return result


# ─────────────────────────────────────────────
# 4. Threshold optimizer (ROC-style, numpy only)
# ─────────────────────────────────────────────
def threshold_optimizer(df: pd.DataFrame,
                        score_col: str = SCORE_COL,
                        return_col: str = RETURN_COL,
                        step: float = 1.0,
                        win_threshold: float = 0.0) -> dict:
    """
    total_score 임계값 스윕 → 최적 RESERVE/WATCH threshold 도출.
    Metric: F1-proxy = 2 * precision * recall / (precision + recall)
    """
    df_clean = df[df[return_col].notna() & df[score_col].notna()].copy()
    if len(df_clean) < 10:
        return {"error": "insufficient data"}

    scores  = df_clean[score_col].values
    returns = df_clean[return_col].values
    actual_pos = (returns > win_threshold)
    total_pos  = actual_pos.sum()

    if total_pos == 0:
        return {"error": "no positive returns in dataset"}

    thresholds = np.arange(max(scores.min(), 50), min(scores.max(), 150), step)
    best = {"threshold": None, "f1": -1, "precision": 0, "recall": 0, "n_signals": 0}
    sweep = []

    for t in thresholds:
        predicted = scores >= t
        tp = (predicted & actual_pos).sum()
        fp = (predicted & ~actual_pos).sum()
        fn = (~predicted & actual_pos).sum()

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall    = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1        = (2 * precision * recall / (precision + recall)
                     if (precision + recall) > 0 else 0)

        sweep.append({
            "threshold":  float(t),
            "f1":         round(float(f1), 4),
            "precision":  round(float(precision), 4),
            "recall":     round(float(recall), 4),
            "n_signals":  int(predicted.sum()),
        })

        if f1 > best["f1"]:
            best = {"threshold": float(t), **sweep[-1]}

    # Find high-precision threshold (precision >= 0.7)
    high_prec = [s for s in sweep if s["precision"] >= 0.7]
    best_high_prec = max(high_prec, key=lambda x: x["f1"]) if high_prec else None

    result = {
        "current_reserve": RESERVE_THRESHOLD_DEFAULT,
        "current_watch":   WATCH_THRESHOLD_DEFAULT,
        "optimal_f1":      best,
        "optimal_high_precision": best_high_prec,
        "n_tested":        len(sweep),
    }
    logger.info("Threshold opt: optimal_f1=%.0f, high_prec=%.0f",
                best.get("threshold", 0),
                best_high_prec.get("threshold", 0) if best_high_prec else 0)
    return result


# ─────────────────────────────────────────────
# 5. Sector performance matrix
# ─────────────────────────────────────────────
def sector_performance_matrix(df: pd.DataFrame,
                               sector_map: dict = SECTOR_MAP) -> dict:
    """
    섹터별 신호 수, 적중률, 평균 수익률 산출.
    """
    df_clean = df[df[RETURN_COL].notna()].copy()
    result = {}

    for sector, tickers in sector_map.items():
        sub = df_clean[df_clean[TICKER_COL].isin(tickers)]
        if len(sub) == 0:
            result[sector] = {"count": 0, "hit_rate": None, "avg_return": None}
            continue
        wins = (sub[RETURN_COL] > 0).sum()
        result[sector] = {
            "count":      int(len(sub)),
            "hit_rate":   round(float(wins / len(sub)), 4),
            "avg_return": round(float(sub[RETURN_COL].mean()), 4),
            "tickers_covered": int(sub[TICKER_COL].nunique()),
        }

    # Rank sectors by avg_return
    ranked = sorted(
        [(k, v) for k, v in result.items() if v["avg_return"] is not None],
        key=lambda kv: kv[1]["avg_return"], reverse=True
    )
    result["_ranked"] = [k for k, _ in ranked]
    return result


# ─────────────────────────────────────────────
# 6. Signal decay curve (D+1 ~ D+10)
# ─────────────────────────────────────────────
def signal_decay_curve(bt_dir: Path = OUTPUT_DIR) -> dict:
    """
    D+1 ~ D+10 수익률 추적 (파일명: backtest_d{n}.csv).
    각 파일이 있으면 적중률 계산, 없으면 None.
    """
    result = {}
    for n in range(1, 11):
        path = bt_dir / f"backtest_d{n}.csv"
        if not path.exists():
            result[f"D+{n}"] = None
            continue
        try:
            bt = pd.read_csv(path)
            ret_col = f"return_d{n}" if f"return_d{n}" in bt.columns else RETURN_COL
            if ret_col not in bt.columns:
                result[f"D+{n}"] = None
                continue
            valid = bt[ret_col].dropna()
            hit   = (valid > 0).sum() / len(valid) if len(valid) > 0 else None
            result[f"D+{n}"] = {
                "hit_rate":   round(float(hit), 4) if hit else None,
                "avg_return": round(float(valid.mean()), 4) if len(valid) > 0 else None,
                "n":          int(len(valid)),
            }
        except Exception as e:
            result[f"D+{n}"] = {"error": str(e)}

    # Determine signal half-life (where hit_rate drops below 0.5)
    half_life = None
    for n in range(1, 11):
        val = result.get(f"D+{n}")
        if val and val.get("hit_rate") and val["hit_rate"] < 0.5:
            half_life = n
            break
    result["_half_life_day"] = half_life
    return result


# ─────────────────────────────────────────────
# 7. BM score correlation summary
# ─────────────────────────────────────────────
def bm_score_correlation(df: pd.DataFrame) -> dict:
    """
    BM별 점수 컬럼 ↔ return_d1 상관계수 요약.
    """
    bm_cols = [c for c in df.columns if c.endswith("_score") or c.endswith("_boost")]
    df_clean = df[df[RETURN_COL].notna()].copy()
    if len(df_clean) < 5:
        return {}

    y = df_clean[RETURN_COL].values
    result = {}
    for col in bm_cols:
        x = df_clean[col].fillna(0).values
        if x.std() == 0:
            continue
        corr = float(np.corrcoef(x, y)[0, 1])
        result[col] = round(corr, 4)

    result = dict(sorted(result.items(), key=lambda kv: abs(kv[1]), reverse=True))
    return result


# ─────────────────────────────────────────────
# 8. Master report generator
# ─────────────────────────────────────────────
def generate_report(signal_path: Path = SIGNAL_CSV,
                    bt_path: Path = BT_CSV,
                    save: bool = True) -> dict:
    """
    전체 분석 실행 → JSON 리포트 생성.
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info("=== SFD Backtest Analyzer v2.0 START: %s ===", ts)

    df = load_data(signal_path, bt_path)

    if df.empty:
        report = {
            "generated_at": ts,
            "status": "NO_DATA",
            "message": "signal_output.csv not found. Run after Run#93.",
        }
    else:
        has_returns = df[RETURN_COL].notna().sum() > 0
        report = {
            "generated_at":    ts,
            "status":          "OK" if has_returns else "NO_RETURNS",
            "total_signals":   int(len(df)),
            "return_coverage": round(float(df[RETURN_COL].notna().mean()), 4),

            "signal_accuracy":       signal_accuracy(df) if has_returns else {},
            "layer_attribution":     layer_attribution_analysis(df) if has_returns else {},
            "threshold_optimizer":   threshold_optimizer(df) if has_returns else {},
            "sector_performance":    sector_performance_matrix(df) if has_returns else {},
            "signal_decay":          signal_decay_curve(bt_path.parent),
            "bm_score_correlation":  bm_score_correlation(df) if has_returns else {},
        }

    if save:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info("Report saved: %s", REPORT_PATH)

    _print_summary(report)
    return report


def _print_summary(report: dict) -> None:
    print("\n" + "=" * 60)
    print(f"SFD Backtest Report v2.0  [{report.get('generated_at')}]")
    print("=" * 60)
    status = report.get("status")
    if status == "NO_DATA":
        print("⚠️  No signal data. Activate after Run#93.")
        return

    print(f"Total signals : {report.get('total_signals', 0)}")
    print(f"Return coverage: {report.get('return_coverage', 0):.1%}")

    acc = report.get("signal_accuracy", {})
    for sig, val in acc.items():
        if val.get("count", 0) > 0:
            print(f"\n[{sig}]  n={val['count']}  "
                  f"hit={val['hit_rate']:.1%}  "
                  f"avg_ret={val['avg_return']:+.2%}")

    thr = report.get("threshold_optimizer", {})
    opt = thr.get("optimal_f1", {})
    if opt.get("threshold"):
        print(f"\n[Threshold] Optimal F1 @ {opt['threshold']:.0f}pt  "
              f"(F1={opt['f1']:.3f}, prec={opt['precision']:.1%}, "
              f"recall={opt['recall']:.1%})")

    attr = report.get("layer_attribution", {})
    ranked = attr.get("_ranked_by_corr", [])
    if ranked:
        print("\n[Layer Corr]")
        for layer in ranked[:5]:
            c = attr[layer].get("corr", 0)
            print(f"  {layer:<12} corr={c:+.4f}")

    sec = report.get("sector_performance", {})
    sec_ranked = sec.get("_ranked", [])
    if sec_ranked:
        print("\n[Sector Performance]")
        for s in sec_ranked:
            v = sec[s]
            print(f"  {s:<14} hit={v['hit_rate']:.1%}  "
                  f"avg_ret={v['avg_return']:+.2%}  n={v['count']}")

    print("=" * 60)


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SFD Backtest Analyzer v2.0")
    parser.add_argument("--signal", default=str(SIGNAL_CSV), help="signal_output.csv path")
    parser.add_argument("--bt",     default=str(BT_CSV),     help="backtest_d1.csv path")
    parser.add_argument("--no-save", action="store_true",    help="skip saving report JSON")
    args = parser.parse_args()

    generate_report(
        signal_path=Path(args.signal),
        bt_path=Path(args.bt),
        save=not args.no_save
    )
