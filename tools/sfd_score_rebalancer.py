"""
SFD Score Rebalancer v1.0
- 현재 점수 역전 문제(고점수=저승률) 진단 및 수정
- 후행 지표(tech) 비중 축소, 선행 지표(수급 누적/가격위치) 비중 확대
- 수급 3일 누적 감지 로직 추가
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
import logging

log = logging.getLogger("SFD_REBALANCER")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")

PIPELINE_ROOT = Path(__file__).parent.parent


def diagnose_score_issue() -> dict:
    """
    현재 백테스트 데이터로 점수-승률 역전 현상 진단
    """
    bt_path = PIPELINE_ROOT / "outputs" / "latest" / "sfd_backtest_report.csv"
    if not bt_path.exists():
        return {"error": "backtest_report.csv 없음"}

    df = pd.read_csv(bt_path, encoding="utf-8-sig")
    df["win_flag"] = df["win_flag"].astype(str).str.lower() == "true"
    df["total_score"] = pd.to_numeric(df["total_score"], errors="coerce")
    df["return_d1"] = pd.to_numeric(
        df["return_d1"].astype(str).str.replace("%",""), errors="coerce"
    )

    bins   = [0, 50, 60, 70, 80, 300]
    labels = ["<50", "50-59", "60-69", "70-79", "80+"]
    df["score_band"] = pd.cut(df["total_score"], bins=bins, labels=labels)

    result = df.groupby("score_band", observed=True).agg(
        건수     = ("win_flag", "count"),
        승률     = ("win_flag", "mean"),
        평균수익 = ("return_d1", "mean")
    ).round(3)

    # 역전 감지
    rates = result["승률"].values
    inversion = bool(rates[-1] < rates[0]) if len(rates) >= 2 else False

    log.info(f"\n{result.to_string()}")
    log.info(f"점수 역전 현상: {'⚠️ 감지됨' if inversion else '✅ 정상'}")

    return {
        "breakdown": result.to_dict(),
        "inversion_detected": inversion,
        "recommendation": "tech_score 상한 축소 + 선행 수급 가중치 확대 필요" if inversion else "정상"
    }


def score_leading_indicators(ticker: str, flow_history: list) -> dict:
    """
    선행 지표 스코어 계산 (PRISM Engine P/R 레이어)

    flow_history: 최근 3일 수급 데이터
    [{"date": "20260610", "foreign": 100, "institution": 50, "pension": 0}, ...]

    반환: {
        "momentum_score": 0~30,   # P레이어: 가격 모멘텀
        "flow_3d_score":  0~30,   # R레이어: 3일 누적 수급
        "leading_total":  0~60
    }
    """
    scores = {"momentum_score": 0, "flow_3d_score": 0}

    # R레이어 — 3일 연속 수급 누적
    if flow_history:
        consecutive_foreign   = sum(1 for d in flow_history if d.get("foreign", 0) > 0)
        consecutive_institution = sum(1 for d in flow_history if d.get("institution", 0) > 0)
        any_pension           = any(d.get("pension", 0) > 0 for d in flow_history)

        flow_score = 0
        # 3일 연속 외국인 순매수 → +20pt (강력 선행)
        if consecutive_foreign == 3:
            flow_score += 20
        elif consecutive_foreign == 2:
            flow_score += 12
        elif consecutive_foreign == 1:
            flow_score += 5

        # 기관 연속 매수 추가
        if consecutive_institution >= 2:
            flow_score += 8
        elif consecutive_institution == 1:
            flow_score += 3

        # 연기금 가담 보너스
        if any_pension:
            flow_score += 5

        scores["flow_3d_score"] = min(flow_score, 30)

    scores["leading_total"] = scores["momentum_score"] + scores["flow_3d_score"]
    return scores


def get_rebalance_weights() -> dict:
    """
    현행 vs 권장 가중치 비교 반환
    → sfd_signal_aggregator.py 수정 참고용
    """
    return {
        "현행": {
            "tech_score":     "최대 85pt (후행 지표 과다)",
            "investor_score": "최대 35pt (당일 1회만)",
            "news_score":     "최대 30pt",
            "theme_score":    "최대 10pt",
            "fund_score":     "최대 15pt",
        },
        "권장": {
            "tech_score":          "최대 60pt (상한 축소)",
            "flow_3d_score":       "최대 30pt (3일 누적 신규)",
            "investor_score":      "최대 25pt (당일)",
            "news_score":          "최대 25pt",
            "theme_score":         "최대 10pt",
            "fund_score":          "최대 15pt",
            "price_position_score":"최대 15pt (52주 위치 신규)",
        },
        "변경_이유": "고점수=저승률 역전 현상 해소 — 후행→선행 지표 전환"
    }


def run():
    """진단 실행"""
    log.info("=== SFD Score Rebalancer v1.0 ===")
    diag = diagnose_score_issue()
    weights = get_rebalance_weights()

    log.info("\n[현행 vs 권장 가중치]")
    for k, v in weights["현행"].items():
        log.info(f"  현행 {k}: {v}")
    log.info("  →")
    for k, v in weights["권장"].items():
        log.info(f"  권장 {k}: {v}")

    return {"diagnosis": diag, "weights": weights}


if __name__ == "__main__":
    run()
