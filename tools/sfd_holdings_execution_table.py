# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import csv
import html
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd


DEFAULT_MASTER = r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline\data\sfd_company_master_v1.4_with_financials.csv"
DEFAULT_HOLDINGS = r"D:\AI_WorkSpace\I_SFC\download\holdings_current_from_kiwoom.csv"
DEFAULT_OUTPUT_ROOT = r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline\reports\execution_tables"


def kst_now_stamp() -> str:
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%d_%H%M_KST")


def read_csv_safely(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"CSV file not found: {p}")
    last_error = None
    for enc in ("utf-8-sig", "cp949", "utf-8"):
        try:
            return pd.read_csv(p, dtype=str, encoding=enc).fillna("")
        except Exception as e:
            last_error = e
    raise RuntimeError(f"Failed to read CSV: {p} / last_error={last_error}")


def normalize_stock_code(code: str) -> str:
    code = str(code).strip()
    return code.zfill(6) if code.isdigit() else code


def get_value(row: Optional[pd.Series], candidates: List[str], default: str = "") -> str:
    if row is None:
        return default
    for c in candidates:
        if c in row.index:
            v = str(row.get(c, "")).strip()
            if v and v.lower() != "nan":
                return v
    return default


def to_float(value: Any) -> Optional[float]:
    try:
        s = str(value).replace(",", "").replace("%", "").replace("원", "").strip()
        if not s or s.lower() == "nan":
            return None
        return float(s)
    except Exception:
        return None


def won(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"{round(value):,.0f}원"


def pct(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}%"


def pick_master_row(master_df: pd.DataFrame, stock_code: str) -> Optional[pd.Series]:
    code = normalize_stock_code(stock_code)
    if "stock_code" not in master_df.columns:
        raise ValueError("stock_code column not found in SFD master.")
    hit = master_df[master_df["stock_code"].astype(str).str.zfill(6) == code]
    if len(hit) == 0:
        return None
    return hit.iloc[0]


def calc_metrics(holding: pd.Series) -> Dict[str, Optional[float]]:
    qty = to_float(get_value(holding, ["quantity", "qty", "보유수량"]))
    avg = to_float(get_value(holding, ["avg_price", "average_price", "평균단가", "평단"]))
    cur = to_float(get_value(holding, ["current_price", "현재가"]))
    target_sell = to_float(get_value(holding, ["target_sell_price", "목표매도가"]))
    target_buy = to_float(get_value(holding, ["target_buy_price", "추가매수가"]))

    invested = qty * avg if qty is not None and avg is not None else None
    value = qty * cur if qty is not None and cur is not None else None
    pnl = value - invested if invested is not None and value is not None else None
    pnl_rate = pnl / invested * 100 if invested not in (None, 0) and pnl is not None else None

    return {
        "qty": qty,
        "avg": avg,
        "cur": cur,
        "target_sell": target_sell,
        "target_buy": target_buy,
        "invested": invested,
        "value": value,
        "pnl": pnl,
        "pnl_rate": pnl_rate,
    }


def round_price_kr(price: Optional[float]) -> Optional[int]:
    if price is None:
        return None
    p = float(price)
    if p < 1000:
        unit = 1
    elif p < 5000:
        unit = 5
    elif p < 10000:
        unit = 10
    elif p < 50000:
        unit = 50
    elif p < 100000:
        unit = 100
    elif p < 500000:
        unit = 500
    else:
        unit = 1000
    return int(round(p / unit) * unit)


def build_execution_plan(holding: pd.Series, master_row: Optional[pd.Series]) -> Dict[str, str]:
    m = calc_metrics(holding)
    qty = m["qty"]
    avg = m["avg"]
    cur = m["cur"]
    pnl_rate = m["pnl_rate"]

    risk_level = get_value(master_row, ["risk_level"], "-")
    bucket = get_value(master_row, ["bucket_default"], "-")
    leader = get_value(master_row, ["leader_class"], "-")
    rare = get_value(master_row, ["rare_capability_flag"], "-")

    if qty is None or qty <= 0 or avg is None or cur is None:
        return {
            "first_sell_price": "-",
            "first_sell_qty": "-",
            "second_sell_price": "-",
            "second_sell_qty": "-",
            "add_buy_price": "-",
            "add_buy_qty": "-",
            "watch_price": "-",
            "hard_stop_price": "-",
            "execution_signal": "DATA_CHECK",
            "execution_reason": "수량/평단/현재가 데이터 확인 필요",
        }

    if pnl_rate is None:
        pnl_rate = 0.0

    if risk_level in ("RISK", "HIGH", "DANGER"):
        risk_mode = "HIGH_RISK"
    elif risk_level == "WATCH":
        risk_mode = "WATCH"
    else:
        risk_mode = "NORMAL"

    first_qty = max(1, int(qty // 2)) if qty >= 2 else int(qty)
    second_qty = max(0, int(qty - first_qty))

    if pnl_rate >= 15:
        first_sell = cur * 1.02
        second_sell = cur * 1.07
        add_buy = None
        signal = "PARTIAL_SELL_READY"
        reason = "강한 수익권. 1차 일부익절 우선, 2차는 추세 연장 대응."
    elif pnl_rate >= 7:
        first_sell = cur * 1.03
        second_sell = cur * 1.08
        add_buy = avg if risk_mode == "NORMAL" else None
        signal = "HOLD_OR_PARTIAL_SELL"
        reason = "수익권. 일부익절 또는 추세 보유 병행."
    elif pnl_rate >= 0:
        first_sell = avg * 1.08
        second_sell = avg * 1.15
        add_buy = avg * 0.96 if risk_mode == "NORMAL" else None
        signal = "HOLD"
        reason = "소폭 수익권. 코어/회전 성격에 따라 보유 중심."
    elif pnl_rate >= -4:
        first_sell = avg * 1.03
        second_sell = avg * 1.08
        add_buy = cur * 0.97 if risk_mode == "NORMAL" else None
        signal = "WATCH"
        reason = "소폭 손실권. 성급한 추가매수보다 관찰 우선."
    elif pnl_rate >= -8:
        first_sell = avg
        second_sell = avg * 1.05
        add_buy = cur * 0.95 if risk_mode == "NORMAL" and leader == "LEADER" else None
        signal = "STOP_CHECK"
        reason = "손실 확대 구간. 구조 확인 후 제한적 대응."
    else:
        first_sell = avg * 0.98
        second_sell = avg * 1.03
        add_buy = None
        signal = "HARD_STOP_REVIEW"
        reason = "하드스탑 기준 접근 또는 이탈. 추가매수 금지."

    if risk_mode == "WATCH" and pnl_rate >= 10:
        signal = "PARTIAL_SELL_PRIORITY"
        reason = "WATCH 위험등급이므로 수익권에서는 일부익절 우선."
    elif risk_mode == "WATCH" and pnl_rate < 0:
        signal = "WATCH_NO_ADD"
        reason = "WATCH 위험등급 손실권. 추가매수 금지, 관찰 우선."

    if bucket == "LONG" and leader == "LEADER" and pnl_rate >= 0 and risk_mode == "NORMAL":
        reason += " 대장/코어 성격이므로 전량매도보다 분할 접근."

    if rare in ("Y", "y", "1", "TRUE", "True", "true") and pnl_rate >= 0:
        reason += " 희소역량 후보로 중기 추적 가치가 있음."

    if m["target_sell"] is not None:
        first_sell = m["target_sell"]
        reason += " 입력된 목표매도가를 1차 매도가로 우선 반영."
    if m["target_buy"] is not None:
        add_buy = m["target_buy"]
        reason += " 입력된 추가매수가를 우선 반영."

    watch_price = avg * 0.95
    hard_stop = avg * 0.92

    return {
        "first_sell_price": won(round_price_kr(first_sell)),
        "first_sell_qty": str(first_qty),
        "second_sell_price": won(round_price_kr(second_sell)) if second_qty > 0 else "-",
        "second_sell_qty": str(second_qty) if second_qty > 0 else "-",
        "add_buy_price": won(round_price_kr(add_buy)) if add_buy is not None else "-",
        "add_buy_qty": "1" if add_buy is not None else "-",
        "watch_price": won(round_price_kr(watch_price)),
        "hard_stop_price": won(round_price_kr(hard_stop)),
        "execution_signal": signal,
        "execution_reason": reason,
    }


def make_summary_row(holding: pd.Series, master_row: Optional[pd.Series]) -> Dict[str, str]:
    code = normalize_stock_code(get_value(holding, ["stock_code"], "-"))
    name = get_value(master_row, ["corp_name", "company_name", "stock_name"], "") if master_row is not None else ""
    if not name:
        name = get_value(holding, ["corp_name", "company_name", "stock_name"], "-")
    m = calc_metrics(holding)
    plan = build_execution_plan(holding, master_row)
    return {
        "stock_code": code,
        "corp_name": name,
        "quantity": str(int(m["qty"])) if m["qty"] is not None else "-",
        "avg_price": won(m["avg"]),
        "current_price": won(m["cur"]),
        "invested_amount": won(m["invested"]),
        "valuation_amount": won(m["value"]),
        "pnl_amount": won(m["pnl"]),
        "pnl_rate": pct(m["pnl_rate"]),
        "risk_level": get_value(master_row, ["risk_level"], "-") if master_row is not None else "MASTER_MISSING",
        **plan,
    }


def summarize_portfolio(rows: List[Dict[str, str]]) -> Dict[str, str]:
    def parse_won(s: str) -> float:
        s = str(s).replace(",", "").replace("원", "").strip()
        if not s or s == "-":
            return 0.0
        return float(s)

    total_invested = sum(parse_won(r.get("invested_amount", "0")) for r in rows)
    total_valuation = sum(parse_won(r.get("valuation_amount", "0")) for r in rows)
    total_pnl = total_valuation - total_invested
    total_rate = (total_pnl / total_invested * 100) if total_invested else 0.0

    safe_count = sum(1 for r in rows if r.get("risk_level") == "SAFE")
    watch_count = sum(1 for r in rows if r.get("risk_level") == "WATCH")
    no_add_count = sum(1 for r in rows if r.get("execution_signal") in ("WATCH_NO_ADD", "HARD_STOP_REVIEW", "STOP_CHECK"))

    return {
        "total_invested_amount": won(total_invested),
        "total_valuation_amount": won(total_valuation),
        "total_pnl_amount": won(total_pnl),
        "total_pnl_rate": pct(total_rate),
        "holding_count": str(len(rows)),
        "safe_count": str(safe_count),
        "watch_count": str(watch_count),
        "no_add_or_stop_count": str(no_add_count),
    }


def save_portfolio_summary_csv(summary: Dict[str, str], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["metric", "value"])
        writer.writeheader()
        for k, v in summary.items():
            writer.writerow({"metric": k, "value": v})


def save_html(rows: List[Dict[str, str]], html_path: Path) -> None:
    headers = [
        "종목코드", "기업명", "수량", "평단", "현재가", "매입금액", "평가금액", "평가손익", "수익률",
        "위험등급", "1차 매도가", "1차 수량", "2차 매도가", "2차 수량",
        "추가매수가", "추가수량", "경계가", "하드스탑", "실행판단", "이유"
    ]
    keys = [
        "stock_code", "corp_name", "quantity", "avg_price", "current_price", "invested_amount", "valuation_amount", "pnl_amount", "pnl_rate",
        "risk_level", "first_sell_price", "first_sell_qty", "second_sell_price", "second_sell_qty",
        "add_buy_price", "add_buy_qty", "watch_price", "hard_stop_price", "execution_signal", "execution_reason"
    ]
    summary = summarize_portfolio(rows)
    summary_cards = [
        ("총매입금액", summary["total_invested_amount"]),
        ("총평가금액", summary["total_valuation_amount"]),
        ("총평가손익", summary["total_pnl_amount"]),
        ("총수익률", summary["total_pnl_rate"]),
        ("보유종목 수", summary["holding_count"]),
        ("SAFE 수", summary["safe_count"]),
        ("WATCH 수", summary["watch_count"]),
        ("추가금지/손절점검 수", summary["no_add_or_stop_count"]),
    ]

    trade_cols = {"first_sell_price", "first_sell_qty", "second_sell_price", "second_sell_qty", "add_buy_price", "add_buy_qty"}
    caution_cols = {"watch_price"}
    stop_cols = {"hard_stop_price"}

    html_lines = [
        "<!doctype html><html><head><meta charset='utf-8'><title>SFD Holdings Execution Table</title>",
        "<style>"
        "body{font-family:Arial,'Malgun Gothic',sans-serif;background:#f5f6f8;margin:24px;color:#1f2937}"
        ".wrap{max-width:1800px;margin:0 auto;background:#fff;border-radius:16px;padding:28px;box-shadow:0 4px 18px rgba(0,0,0,.08)}"
        "h1{font-size:28px;margin:0 0 8px 0}"
        ".summary{display:grid;grid-template-columns:repeat(4,minmax(180px,1fr));gap:12px;margin:18px 0 24px}"
        ".card{background:#fafafa;border:1px solid #e5e7eb;border-radius:14px;padding:14px}"
        ".label{font-size:13px;color:#6b7280}"
        ".value{font-size:22px;font-weight:800;margin-top:6px}"
        ".table-wrap{overflow-x:auto}"
        "table{border-collapse:collapse;width:100%;font-size:13px;table-layout:auto}"
        "th,td{border-bottom:1px solid #e5e7eb;padding:9px 8px;text-align:left;vertical-align:top;line-height:1.45}"
        "th{background:#f8fafc;font-size:11px;font-weight:700;color:#475569;white-space:nowrap;letter-spacing:-0.2px;word-break:keep-all}"
        "td{word-break:keep-all}"
        ".plus{color:#c1121f;font-weight:700}.minus{color:#1d4ed8;font-weight:700}.sig{font-weight:800}"
        ".trade-col{background:#eef8ef}"
        ".trade-head{background:#dff1e2 !important}"
        ".caution-col{background:#fff8e8}"
        ".caution-head{background:#ffefc2 !important}"
        ".stop-col{background:#fff1f2;color:#b42318;font-weight:800}"
        ".stop-head{background:#ffd9dd !important;color:#b42318 !important}"
        ".reason{min-width:260px}"
        ".name-col{min-width:86px}"
        "</style>",
        "</head><body><div class='wrap'><h1>SFD Holdings Execution Table</h1>",
        "<div class='summary'>",
    ]

    for label, value in summary_cards:
        cls = "value"
        if label in ("총평가손익", "총수익률"):
            cls += " minus" if str(value).startswith("-") else " plus"
        html_lines.append(f"<div class='card'><div class='label'>{html.escape(label)}</div><div class='{cls}'>{html.escape(value)}</div></div>")
    html_lines.append("</div>")

    html_lines.append("<div class='table-wrap'><table>")
    head_cells = []
    for h, k in zip(headers, keys):
        cls = []
        if k in trade_cols:
            cls.append("trade-head")
        elif k in caution_cols:
            cls.append("caution-head")
        elif k in stop_cols:
            cls.append("stop-head")
        head_cells.append(f"<th class='{' '.join(cls)}'>{html.escape(h)}</th>")
    html_lines.append("<tr>" + "".join(head_cells) + "</tr>")

    for r in rows:
        html_lines.append("<tr>")
        for k in keys:
            v = r.get(k, "-")
            cls = []
            if k in ("pnl_amount", "pnl_rate"):
                cls.append("minus" if str(v).startswith("-") else "plus")
            if k == "execution_signal":
                cls.append("sig")
            if k in trade_cols:
                cls.append("trade-col")
            elif k in caution_cols:
                cls.append("caution-col")
            elif k in stop_cols:
                cls.append("stop-col")
            if k == "execution_reason":
                cls.append("reason")
            if k == "corp_name":
                cls.append("name-col")
            html_lines.append(f"<td class='{' '.join(cls)}'>{html.escape(str(v))}</td>")
        html_lines.append("</tr>")
    html_lines.append("</table></div></div></body></html>")
    html_path.write_text("\n".join(html_lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="SFD Holdings Execution Table v1.2 STYLE")
    parser.add_argument("--holdings-csv", default=DEFAULT_HOLDINGS)
    parser.add_argument("--master", default=DEFAULT_MASTER)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--batch-name", default=None)
    args = parser.parse_args()

    master_df = read_csv_safely(args.master)
    if "stock_code" in master_df.columns:
        master_df["stock_code"] = master_df["stock_code"].astype(str).str.zfill(6)

    holdings_df = read_csv_safely(args.holdings_csv)
    if "stock_code" not in holdings_df.columns:
        raise ValueError("holdings CSV must include stock_code column.")
    holdings_df["stock_code"] = holdings_df["stock_code"].astype(str).str.zfill(6)

    batch_name = args.batch_name or f"execution_table_{kst_now_stamp()}"
    out_dir = Path(args.output_root) / batch_name
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, str]] = []
    for _, hrow in holdings_df.iterrows():
        code = normalize_stock_code(get_value(hrow, ["stock_code"], "-"))
        mrow = pick_master_row(master_df, code)
        row = make_summary_row(hrow, mrow)
        rows.append(row)
        print(f"[SFD] {row['stock_code']} {row['corp_name']} -> {row['execution_signal']} / {row['execution_reason']}")

    csv_path = out_dir / "sfd_holdings_execution_table.csv"
    html_path = out_dir / "sfd_holdings_execution_table.html"
    summary_csv_path = out_dir / "sfd_holdings_portfolio_summary.csv"

    fieldnames = [
        "stock_code", "corp_name", "quantity", "avg_price", "current_price", "invested_amount", "valuation_amount", "pnl_amount", "pnl_rate",
        "risk_level", "first_sell_price", "first_sell_qty", "second_sell_price", "second_sell_qty",
        "add_buy_price", "add_buy_qty", "watch_price", "hard_stop_price", "execution_signal", "execution_reason"
    ]

    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    summary = summarize_portfolio(rows)
    save_portfolio_summary_csv(summary, summary_csv_path)
    save_html(rows, html_path)

    print()
    print("[DONE] Execution table created.")
    print(f"- CSV    : {csv_path}")
    print(f"- HTML   : {html_path}")
    print(f"- SUMMARY: {summary_csv_path}")
    print(f"- total_invested_amount : {summary['total_invested_amount']}")
    print(f"- total_valuation_amount: {summary['total_valuation_amount']}")
    print(f"- total_pnl_amount      : {summary['total_pnl_amount']}")
    print(f"- total_pnl_rate        : {summary['total_pnl_rate']}")


if __name__ == "__main__":
    main()
