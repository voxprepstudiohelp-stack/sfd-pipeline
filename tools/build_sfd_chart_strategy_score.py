from __future__ import annotations

from datetime import datetime
from pathlib import Path
import pandas as pd

D_ROOT = Path(r"D:\AI_WorkSpace\I_SFC")
ROOT = D_ROOT / r"09_Implementation\SFC_DataPipeline"
WATCH = ROOT / r"inputs\sfd_market_watchlist_template.csv"
OUTPUT = ROOT / r"outputs\latest\sfd_chart_strategy_score_latest.csv"


def action_from_score(score: int, change: float) -> str:
    if change >= 25:
        return "NO_CHASE"
    if score >= 80:
        return "BUY_CANDIDATE"
    if score >= 65:
        return "WATCH_BUY"
    if score >= 50:
        return "WATCH"
    if score >= 35:
        return "HOLD_OFF"
    return "EXCLUDE"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if not WATCH.exists():
        pd.DataFrame().to_csv(OUTPUT, index=False, encoding="utf-8-sig")
        print("NO WATCH", WATCH)
        return

    df = pd.read_csv(WATCH, encoding="utf-8-sig", dtype={"stock_code": str})
    rows = []
    for _, r in df.iterrows():
        current = float(r.get("current_price", 0) or 0)
        prev = float(r.get("prev_close", 0) or 0)
        change = float(r.get("change_rate_pct", 0) or 0)
        high = max(current, prev) if current and prev else current
        low = min(current, prev) if current and prev else prev
        rng = max(high - low, 1)

        # 현재는 실시간 OHLCV가 없으므로 템플릿 기반의 placeholder 점수.
        # v0.3에서 pykrx/키움 데이터로 RSI/MACD/VWAP/Fib를 실제 계산한다.
        score = 40
        if "거래대금" in str(r.get("ranking_type", "")):
            score += 15
        if change > 0:
            score += 10
        if 3 <= change <= 15:
            score += 15
        if change >= 25:
            score -= 30
        if "전선" in str(r.get("note", "")) or "전력" in str(r.get("note", "")):
            score += 10
        if "AI" in str(r.get("note", "")) or "HBM" in str(r.get("note", "")):
            score += 10
        score = max(0, min(int(score), 100))

        # fib placeholder: prev/current only. v0.3에서 swing low/high 자동화.
        swing_low = int(low) if low else 0
        swing_high = int(high) if high else 0
        fib_382 = int(swing_high - (swing_high - swing_low) * 0.382) if swing_high else 0
        fib_500 = int(swing_high - (swing_high - swing_low) * 0.500) if swing_high else 0
        fib_618 = int(swing_high - (swing_high - swing_low) * 0.618) if swing_high else 0
        fib_786 = int(swing_high - (swing_high - swing_low) * 0.786) if swing_high else 0
        fib_1236 = int(swing_high + (swing_high - swing_low) * 0.236) if swing_high else 0
        fib_1618 = int(swing_high + (swing_high - swing_low) * 0.618) if swing_high else 0

        rows.append({
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "stock_name": r.get("stock_name", ""),
            "stock_code": str(r.get("stock_code", "")).zfill(6),
            "current_price": int(current),
            "change_rate_pct": change,
            "chart_score": score,
            "chart_action": action_from_score(score, change),
            "ninja_signal": "TODO",
            "pitbull_volume": "TODO",
            "vwap_status": "TODO",
            "rsi_status": "TODO",
            "macd_status": "TODO",
            "supertrend_status": "TODO",
            "fib_swing_low": swing_low,
            "fib_swing_high": swing_high,
            "fib_382_price": fib_382,
            "fib_500_price": fib_500,
            "fib_618_price": fib_618,
            "fib_786_price": fib_786,
            "fib_1236_target": fib_1236,
            "fib_1618_target": fib_1618,
            "notes": "v0.2 placeholder; v0.3에서 과거데이터 기반 실제 지표 계산",
        })

    out = pd.DataFrame(rows)
    out.to_csv(OUTPUT, index=False, encoding="utf-8-sig")
    print("OK chart strategy score", len(out))
    print(OUTPUT)


if __name__ == "__main__":
    main()
