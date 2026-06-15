from __future__ import annotations

from datetime import datetime
from pathlib import Path
import pandas as pd

D_ROOT = Path(r"D:\AI_WorkSpace\I_SFC")
ROOT = D_ROOT / r"09_Implementation\SFC_DataPipeline"
IN = ROOT / "inputs"
OUT = ROOT / r"outputs\latest"
REPORT = ROOT / r"reports\latest\sfd_0835_report_latest.md"


def read_csv(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path, encoding="utf-8-sig", dtype={"stock_code": str})
    return pd.DataFrame()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    account = read_csv(IN / "sfd_account_snapshot_template.csv")
    market = read_csv(IN / "sfd_market_watchlist_template.csv")
    news = read_csv(OUT / "sfd_news_signal_latest.csv")
    chart = read_csv(OUT / "sfd_chart_strategy_score_latest.csv")

    if not account.empty:
        account.to_csv(OUT / "sfd_account_snapshot_latest.csv", index=False, encoding="utf-8-sig")

    if not market.empty:
        market.to_csv(OUT / "sfd_market_ranking_latest.csv", index=False, encoding="utf-8-sig")

    rows = []
    for _, r in market.iterrows() if not market.empty else []:
        code = str(r.get("stock_code", "")).zfill(6)
        current = float(r.get("current_price", 0) or 0)
        prev = float(r.get("prev_close", 0) or 0)
        change = float(r.get("change_rate_pct", 0) or 0)
        cscore = 0
        caction = "WATCH"
        if not chart.empty and "stock_code" in chart.columns:
            hit = chart[chart["stock_code"].astype(str).str.zfill(6) == code]
            if not hit.empty:
                cscore = int(hit.iloc[0].get("chart_score", 0) or 0)
                caction = hit.iloc[0].get("chart_action", "WATCH")

        if change >= 25:
            target_entry = "추격금지"
            target_sell = "확인필요"
            qty = 0
            decision = "NO_CHASE"
        elif cscore >= 65 or 3 <= change <= 15:
            target_entry = f"{int(current * 0.93):,}~{int(current * 0.96):,}원"
            target_sell = f"{int(current * 1.05):,}~{int(current * 1.10):,}원"
            qty = max(1, int(300000 // current)) if current > 0 else 0
            decision = "WATCH_BUY"
        elif -3 <= change <= 1:
            target_entry = f"{int(current * 0.98):,}~{int(current):,}원"
            target_sell = f"{int(current * 1.05):,}~{int(current * 1.09):,}원"
            qty = max(1, int(300000 // current)) if current > 0 and current <= 900000 else 0
            decision = "REENTRY_WATCH" if qty > 0 else "DIRECTION_LEADER"
        else:
            target_entry = "확인필요"
            target_sell = "확인필요"
            qty = 0
            decision = caction

        rows.append({
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "구분": "신규대기",
            "종목명": r.get("stock_name", ""),
            "종목코드": code,
            "어제 종가": f"{int(prev):,}원" if prev else "확인필요",
            "현재가": f"{int(current):,}원" if current else "확인필요",
            "목표 진입가": target_entry,
            "목표 매도가": target_sell,
            "수량": qty,
            "차트점수": cscore,
            "실행 판단": decision,
            "특장점": r.get("note", ""),
            "리스크": "급등 후 변동성" if change >= 8 else "추가 확인",
            "상승/하락 원인": r.get("ranking_type", ""),
        })

    order = pd.DataFrame(rows)
    order.to_csv(OUT / "sfd_0835_order_plan_latest.csv", index=False, encoding="utf-8-sig")

    md = f"""# SFD 08:35 Report v0.2

- 생성시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} KST
- 구조: H 기준본 / D 실행본
- 주의: v0.2는 Power BI CSV와 네이버 뉴스 API 복구 뼈대입니다. 실매매 아님.

## 1. 08:35 실행표

{order.to_markdown(index=False) if not order.empty else '데이터 없음'}

## 2. 뉴스 신호

{news.head(10).to_markdown(index=False) if not news.empty else '데이터 없음 또는 NAVER API 키 미입력'}

## 3. 차트조합 점수

{chart.head(10).to_markdown(index=False) if not chart.empty else '데이터 없음'}
"""
    REPORT.write_text(md, encoding="utf-8")
    print("OK powerbi latest csv")
    print(OUT)
    print(REPORT)


if __name__ == "__main__":
    main()
