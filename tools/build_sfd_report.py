from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
REPORT_LATEST = ROOT / "reports" / "latest" / "sfd_report_latest.md"
REPORT_HISTORY = ROOT / "reports" / "history"
NEWS = ROOT / "outputs" / "latest" / "sfd_news_signal_latest.csv"
ACCOUNT = ROOT / "inputs" / "sfd_account_snapshot_template.csv"
WATCH = ROOT / "inputs" / "sfd_market_watchlist_template.csv"
THEME = ROOT / "inputs" / "sfd_theme_stock_map.csv"


def read_csv(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path, encoding="utf-8-sig", dtype={"stock_code": str})
    return pd.DataFrame()


def calc_signal(row: pd.Series) -> str:
    change = float(row.get("change_rate_pct", 0) or 0)
    if change >= 25:
        return "NO_CHASE"
    if change >= 8:
        return "WATCH_BUY_ON_PULLBACK"
    if -3 <= change <= 1 and str(row.get("stock_name", "")) in ["삼성전자", "SK하이닉스"]:
        return "REENTRY_WATCH"
    return "WATCH"


def build_execution_table(watch: pd.DataFrame) -> pd.DataFrame:
    if watch.empty:
        return pd.DataFrame()
    rows = []
    for _, r in watch.iterrows():
        current = float(r.get("current_price", 0) or 0)
        prev_close = float(r.get("prev_close", 0) or 0)
        signal = calc_signal(r)
        target_entry = "추격금지"
        target_sell = "확인필요"
        qty = 0
        if signal == "WATCH_BUY_ON_PULLBACK":
            target_entry = f"{int(current * 0.93):,}~{int(current * 0.96):,}원"
            target_sell = f"{int(current * 1.05):,}~{int(current * 1.10):,}원"
            qty = max(1, int(300000 // current)) if current > 0 else 0
        elif signal == "REENTRY_WATCH":
            target_entry = f"{int(current * 0.98):,}~{int(current):,}원"
            target_sell = f"{int(current * 1.05):,}~{int(current * 1.09):,}원"
            qty = max(1, int(300000 // current)) if current > 0 else 0
        rows.append({
            "구분": "신규대기",
            "종목명": r.get("stock_name", ""),
            "종목코드": str(r.get("stock_code", "")).zfill(6) if str(r.get("stock_code", "")).isdigit() else r.get("stock_code", ""),
            "어제 종가": f"{int(prev_close):,}원" if prev_close else "확인필요",
            "현재가": f"{int(current):,}원" if current else "확인필요",
            "목표 진입가": target_entry,
            "목표 매도가": target_sell,
            "수량": qty,
            "실행 판단": signal,
            "특장점": r.get("note", ""),
            "리스크": "급등 후 변동성" if float(r.get("change_rate_pct", 0) or 0) >= 8 else "추가 확인",
            "상승/하락 원인": r.get("ranking_type", "")
        })
    return pd.DataFrame(rows)


def md_table(df: pd.DataFrame, max_rows: int = 20) -> str:
    if df.empty:
        return "데이터 없음\n"
    return df.head(max_rows).to_markdown(index=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", default="0835")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    REPORT_LATEST.parent.mkdir(parents=True, exist_ok=True)
    REPORT_HISTORY.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    news = read_csv(NEWS)
    account = read_csv(ACCOUNT)
    watch = read_csv(WATCH)
    exec_table = build_execution_table(watch)

    report = f"""# SFD {args.slot} 매도·매수 전략 리포트

- 생성시각: {now.strftime('%Y-%m-%d %H:%M:%S')} KST
- 목적: 08:35 이전 정보 취합, 보유종목 판단, 신규 후보, 기술검증 전 실행 후보 정리
- 주의: 이 파일은 자동화 뼈대입니다. 실제 주문 전 최신 시세와 차트 지표를 추가 확인해야 합니다.

## 1. 보유종목 현황

{md_table(account)}

## 2. 뉴스 신호 요약

{md_table(news[[c for c in ['source_name','title','detected_tags','published'] if c in news.columns]] if not news.empty else news)}

## 3. 네이버 증권 벤치마킹형 시장 후보

{md_table(watch)}

## 4. 1차 실행 후보표

{md_table(exec_table)}

## 5. 기술적 차트 2차 검증 TODO

| 종목명 | 종목코드 | RSI | MACD | 거래량 변화 | 가격 위치 | 과열 여부 | 기술 판단 | 최종 판단 |
|---|---:|---:|---|---|---|---|---|---|
| TODO | 000000 | 확인 | 확인 | 확인 | 지지/저항 | 확인 | WATCH | 최종확인 |

## 6. 고정 원칙

- 상한가 당일 추격 금지
- 급등주는 왜 올랐는가를 태그화하고 D+1/D+3/D+5 검증
- 채택 후보는 RSI/MACD/거래량/가격위치로 2차 검증
- 종목명과 종목코드는 항상 함께 표기
- 어제 종가, 현재가, 목표 진입가, 목표 매도가, 수량, 특장점, 리스크를 표에 포함
"""
    REPORT_LATEST.write_text(report, encoding="utf-8")
    hist = REPORT_HISTORY / f"sfd_{args.slot}_report_{now.strftime('%Y%m%d_%H%M%S')}.md"
    hist.write_text(report, encoding="utf-8")
    print("OK report")
    print(REPORT_LATEST)
    print(hist)


if __name__ == "__main__":
    main()
