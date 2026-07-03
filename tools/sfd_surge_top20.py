# sfd_surge_top20.py | v1.0 | 2026.07.03
# SFD S3 급등예상 TOP20 추출 — aggregator 최종 출력에서 매일 자동 생성
#
# - Input  : outputs/latest/sfd_master_signal_latest.csv
# - Filter : signal == "RESERVE_BUY" AND no_trade == False
# - Sort   : total_score DESC
# - Take   : TOP20 (RESERVE_BUY 부족분은 WATCH_ONLY로 채움)
# - Output1: outputs/latest/sfd_surge_top20_latest.csv
# - Output2: outputs/latest/sfd_surge_top20_latest.json
#
# - SFD_BASE_DIR 환경변수로 베이스 디렉토리 오버라이드 가능
# - 누락 컬럼은 graceful fallback (0 / 빈값) — sys.exit 하지 않음

import os
import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

# ─────────────────────────── paths ───────────────────────────
BASE_DIR = Path(os.environ.get("SFD_BASE_DIR", r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline"))
LATEST_DIR = BASE_DIR / "outputs" / "latest"
INPUT_CSV = LATEST_DIR / "sfd_master_signal_latest.csv"
OUT_CSV = LATEST_DIR / "sfd_surge_top20_latest.csv"
OUT_JSON = LATEST_DIR / "sfd_surge_top20_latest.json"

# ─────────────────────────── logging ─────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sfd_surge_top20")

# ─────────────────────────── columns ─────────────────────────
OUT_COLS = [
    "rank", "ticker", "name", "total_score", "signal",
    "tech_score", "news_score", "investor_score", "fund_score",
    "bm_3hit_score", "bm_aftrap_score",
    "rsi", "ma_align", "vol_ratio", "decay_flag", "fetch_date",
]

# Source columns that may or may not exist in input
SRC_COLS = [
    "ticker", "name", "signal", "no_trade", "total_score",
    "tech_score", "news_score", "investor_score", "fund_score",
    "bm_3hit_score", "bm_aftrap_score",
    "rsi", "ma_align", "vol_ratio", "decay_flag", "fetch_date",
]

# ─────────────────────────── helpers ─────────────────────────
def _safe_get(row: pd.Series, col: str, default=0):
    """컬럼이 없거나 NaN이면 default 반환 (graceful fallback)."""
    if col not in row.index:
        return default
    val = row[col]
    if pd.isna(val):
        return default
    return val


def _norm_bool(v) -> bool:
    """no_trade 컬럼 정규화: True/False/'True'/'False'/1/0 모두 처리."""
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    s = str(v).strip().lower()
    return s in ("true", "1", "y", "yes")


def load_master(path: Path) -> pd.DataFrame:
    log.info(f"loading master signal: {path}")
    df = pd.read_csv(path, encoding="utf-8-sig", dtype={"ticker": str})
    log.info(f"loaded {len(df)} rows, columns={list(df.columns)[:6]}...")
    return df


def pick_top20(df: pd.DataFrame) -> pd.DataFrame:
    """RESERVE_BUY 우선 → 부족분 WATCH_ONLY 로 채워 TOP20 반환."""
    # 1) RESERVE_BUY + no_trade == False
    rb_mask = (df["signal"] == "RESERVE_BUY") & (~df["no_trade"].apply(_norm_bool))
    rb = df[rb_mask].copy()

    # 2) WATCH_ONLY fallback pool
    wo_mask = (df["signal"] == "WATCH_ONLY") & (~df["no_trade"].apply(_norm_bool))
    wo = df[wo_mask].copy()

    # total_score 내림차순 정렬
    rb_sorted = rb.sort_values("total_score", ascending=False, kind="mergesort")
    wo_sorted = wo.sort_values("total_score", ascending=False, kind="mergesort")

    # rank 부여
    rb_sorted["rank"] = range(1, len(rb_sorted) + 1)
    wo_sorted["rank"] = range(len(rb_sorted) + 1, len(rb_sorted) + len(wo_sorted) + 1)

    picked = pd.concat([rb_sorted, wo_sorted], ignore_index=True).head(20)
    log.info(f"RESERVE_BUY={len(rb_sorted)}  WATCH_ONLY(fill)={len(picked) - len(rb_sorted)}  total={len(picked)}")
    return picked


def build_output(picked: pd.DataFrame) -> pd.DataFrame:
    """출력 스키마에 맞춰 row dict 생성 (graceful fallback 적용)."""
    rows = []
    for _, r in picked.iterrows():
        rows.append({
            "rank": int(r["rank"]),
            "ticker": str(_safe_get(r, "ticker", "")),
            "name": str(_safe_get(r, "name", "")),
            "total_score": _safe_get(r, "total_score", 0.0),
            "signal": str(_safe_get(r, "signal", "")),
            "tech_score": _safe_get(r, "tech_score", 0.0),
            "news_score": _safe_get(r, "news_score", 0.0),
            "investor_score": _safe_get(r, "investor_score", 0.0),
            "fund_score": _safe_get(r, "fund_score", 0.0),
            "bm_3hit_score": _safe_get(r, "bm_3hit_score", 0.0),
            "bm_aftrap_score": _safe_get(r, "bm_aftrap_score", 0.0),
            "rsi": _safe_get(r, "rsi", 0.0),
            "ma_align": _safe_get(r, "ma_align", ""),
            "vol_ratio": _safe_get(r, "vol_ratio", 0.0),
            "decay_flag": _safe_get(r, "decay_flag", ""),
            "fetch_date": str(_safe_get(r, "fetch_date", "")),
        })
    return pd.DataFrame(rows, columns=OUT_COLS)


def log_top20(out_df: pd.DataFrame) -> None:
    log.info("=" * 60)
    log.info("SFD S3 급등예상 TOP20")
    log.info("=" * 60)
    for _, r in out_df.iterrows():
        log.info(
            f"  #{int(r['rank']):>2}  {str(r['ticker']):<8}  {str(r['name']):<14}  "
            f"score={float(r['total_score']):>6.2f}  signal={r['signal']}"
        )
    log.info("=" * 60)


def main() -> None:
    if not INPUT_CSV.exists():
        log.warning(f"input not found: {INPUT_CSV}  → 빈 TOP20 생성")
        empty = pd.DataFrame(columns=OUT_COLS)
        empty.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
        payload = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "trade_date": "",
            "count": 0,
            "top20": [],
        }
        OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    df = load_master(INPUT_CSV)
    picked = pick_top20(df)
    out_df = build_output(picked)

    # trade_date: 가장 흔한 fetch_date 사용
    trade_date = ""
    if "fetch_date" in df.columns and len(df) > 0:
        trade_date = str(df["fetch_date"].mode().iloc[0]) if not df["fetch_date"].mode().empty else ""

    # CSV 출력
    out_df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    log.info(f"csv  → {OUT_CSV}  ({len(out_df)} rows)")

    # JSON 출력
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "trade_date": trade_date,
        "count": int(len(out_df)),
        "top20": out_df.to_dict(orient="records"),
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"json → {OUT_JSON}")

    log_top20(out_df)


if __name__ == "__main__":
    main()