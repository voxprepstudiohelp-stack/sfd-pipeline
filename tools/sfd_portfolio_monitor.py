# sfd_portfolio_monitor.py v1.3.1
# 버그수정: trigger_pct=None(C급) 포맷 오류 수정

import json
import sys
from datetime import datetime
from pathlib import Path
import pandas as pd

_HERE          = Path(__file__).resolve().parent
_ROOT          = _HERE.parent
_LATEST        = _ROOT / "outputs" / "latest"

PORTFOLIO_FILE = _ROOT / "portfolio.json"
CLOSE_FILE     = _LATEST / "sfd_prev_close_latest.csv"
SIGNAL_FILE    = _LATEST / "sfd_signal.csv"
MASTER_FILE    = _LATEST / "sfd_master_signal_latest.csv"
STATUS_OUT     = _LATEST / "sfd_portfolio_status.csv"
ALERTS_OUT     = _LATEST / "sfd_alerts.json"

NEAR_THRESHOLD = 5.0
WATCH_TOP_N    = 5

def load_portfolio():
    if not PORTFOLIO_FILE.exists():
        print(f"[Layer5] ERROR: {PORTFOLIO_FILE} not found"); sys.exit(1)
    with open(PORTFOLIO_FILE, encoding="utf-8") as f:
        return json.load(f)

def load_close():
    if not CLOSE_FILE.exists():
        print(f"[Layer5] WARN: close price file not found → N/A"); return {}
    df = pd.read_csv(CLOSE_FILE, dtype={"ticker": str})
    df["ticker"] = df["ticker"].str.zfill(6)
    for col in ["close", "prev_close", "close_price", "종가"]:
        if col in df.columns:
            return dict(zip(df["ticker"], pd.to_numeric(df[col], errors="coerce")))
    return {}

def load_sfd_signals():
    for f in [SIGNAL_FILE, MASTER_FILE]:
        if f.exists():
            df = pd.read_csv(f, dtype={"ticker": str})
            df["ticker"] = df["ticker"].str.zfill(6)
            return df
    return pd.DataFrame()

def get_avg_price(h):
    if h.get("avg_price"):
        return float(h["avg_price"])
    positions = h.get("positions", [])
    if positions:
        tq = sum(p["qty"] for p in positions)
        ta = sum(p["qty"] * p.get("price", p.get("avg_price", 0)) for p in positions)
        return round(ta / tq, 2) if tq > 0 else 0
    return 0.0

def get_qty(h):
    if "qty" in h: return int(h["qty"])
    return sum(p["qty"] for p in h.get("positions", []))

def calc_return_pct(avg, cur):
    if avg <= 0: return 0.0
    return round((cur - avg) / avg * 100, 2)

def signal_rank(s):
    return {"RESERVE_BUY": 3, "WATCH_ONLY": 2, "HOLD": 1}.get(s, 0)

def check_grid_alerts(h, current_price):
    alerts = []
    ticker = h["ticker"]
    name   = h["name"]
    grade  = h.get("grade", "B")

    # C급 비활성
    if not h.get("active", True):
        return alerts

    # 특별 알람가격
    alert_price = h.get("alert_price")
    if alert_price and current_price <= float(alert_price):
        alerts.append({
            "level":   "🔔 ALERT_PRICE",
            "ticker":  ticker, "name": name, "grade": grade,
            "message": f"[{grade}급] {name} 알람가 도달: {current_price:,.0f}원 ≤ {float(alert_price):,.0f}원",
            "action":  h.get("alert_memo", "추가매수 검토"),
        })

    trigger = h.get("trigger_price")
    if not trigger or current_price <= 0:
        return alerts

    trigger  = float(trigger)
    step     = h.get("current_step", 1)
    ratio    = h.get("step_qty_ratio", [1])
    step_qty = ratio[min(step - 1, len(ratio) - 1)] if ratio else 1
    tpct     = h.get("trigger_pct", 0) or 0

    if current_price <= trigger:
        alerts.append({
            "level":   "🔴 WEB_TRIGGER",
            "ticker":  ticker, "name": name, "grade": grade,
            "message": f"[{grade}급] {name} {step}단계 트리거 도달 "
                       f"(현재 {current_price:,.0f} ≤ 트리거 {trigger:,.0f} / {tpct:+.0f}%)",
            "action":  f"추가매수 {step_qty}배수 실행 검토",
        })
        return alerts

    near_line = trigger * (1 + NEAR_THRESHOLD / 100)
    if current_price <= near_line:
        gap = round((current_price - trigger) / trigger * 100, 1)
        alerts.append({
            "level":   "🟡 WEB_NEAR",
            "ticker":  ticker, "name": name, "grade": grade,
            "message": f"[{grade}급] {name} 트리거 근접 "
                       f"(현재 {current_price:,.0f} / 트리거 {trigger:,.0f} / 괴리 {gap:+.1f}%)",
            "action":  "추가매수 대기",
        })
    return alerts

def check_sfd_change(h, new_signal):
    prev = h.get("sfd_signal", "HOLD")
    if new_signal and signal_rank(new_signal) > signal_rank(prev):
        return [{"level": "🟢 SFD_UPGRADE", "ticker": h["ticker"], "name": h["name"],
                 "grade": h.get("grade","B"),
                 "message": f"[{h.get('grade','B')}급] {h['name']} SFD 신호 상승: {prev} → {new_signal}",
                 "action": "포지션 확대 검토"}]
    return []

def check_new_entries(held, df_signal):
    reserve, watch = [], []
    for _, row in df_signal.iterrows():
        t = row["ticker"]
        s = row.get("signal", "")
        if t in held: continue
        score = row.get("adjusted_fund_score", row.get("total_score", 0))
        name  = row.get("name", t)
        if s == "RESERVE_BUY":
            reserve.append({"level": "🔵 SFD_NEW_ENTRY", "ticker": t, "name": name, "grade": "-",
                            "message": f"미보유 종목 SFD 진입: {t} {name} → {s}",
                            "action": "신규 매수 검토"})
        elif s == "WATCH_ONLY":
            watch.append({"ticker": t, "name": name, "score": score,
                          "sector": row.get("sector_major", "")})
    watch.sort(key=lambda x: x["score"] or 0, reverse=True)
    return reserve, {"total": len(watch), "top_n": WATCH_TOP_N, "top_list": watch[:WATCH_TOP_N]}

def main():
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"[Layer5] sfd_portfolio_monitor v1.3.1 START | {today}")

    portfolio = load_portfolio()
    close_map = load_close()
    df_signal = load_sfd_signals()
    signal_map = dict(zip(df_signal["ticker"], df_signal["signal"])) \
                 if not df_signal.empty else {}

    holdings   = portfolio.get("holdings", [])
    all_alerts = []
    rows       = []

    for h in holdings:
        ticker     = h["ticker"]
        name       = h["name"]
        grade      = h.get("grade", "B")
        avg_price  = get_avg_price(h)
        qty        = get_qty(h)
        cur_px     = close_map.get(ticker)
        sfd_signal = signal_map.get(ticker, h.get("sfd_signal", "HOLD"))
        h["sfd_signal"] = sfd_signal
        ret_pct = calc_return_pct(avg_price, cur_px) if cur_px else None

        if cur_px:
            all_alerts += check_grid_alerts(h, cur_px)
        all_alerts += check_sfd_change(h, sfd_signal)

        trigger  = h.get("trigger_price")
        tpct_val = h.get("trigger_pct")  # None 가능 (C급)

        rows.append({
            "as_of_date":    today,
            "ticker":        ticker,
            "name":          name,
            "grade":         grade,
            "qty":           qty,
            "avg_price":     avg_price,
            "current_price": cur_px if cur_px else "N/A",
            "return_pct":    f"{ret_pct:+.2f}%" if ret_pct is not None else "N/A",
            "trigger_price": trigger,
            "trigger_pct":   tpct_val,
            "sfd_signal":    sfd_signal,
            "active":        h.get("active", True),
            "prft_rt":       h.get("prft_rt", ""),
        })

    held = {h["ticker"] for h in holdings}
    reserve_alerts, watch_summary = check_new_entries(held, df_signal)
    all_alerts += reserve_alerts

    # ── 출력 ───────────────────────────────────────────────
    print(f"\n{'='*68}")
    print(f"[Layer5] Portfolio Status ({today})")
    print(f"{'='*68}")
    for r in rows:
        # ✅ 수정: trigger_price/trigger_pct None 안전 처리
        tp   = f"{float(r['trigger_price']):>9,.0f}원" if r["trigger_price"] is not None else "      N/A"
        tpct = f"{r['trigger_pct']:+.0f}%" if r["trigger_pct"] is not None else "  N/A"
        inactive = " [HOLD]" if not r["active"] else ""
        pnl = r.get("prft_rt", "")
        pnl_str = f"({pnl:+.2f}%)" if isinstance(pnl, (int, float)) else f"({r['return_pct']})"
        print(f"  {r['ticker']} [{r['grade']}] {r['name']:10s} | {r['qty']} shs | "
              f"avg {float(r['avg_price']):>9,.0f} | "
              f"trigger {tp} {tpct} {pnl_str:>10}{inactive} | SFD: {r['sfd_signal']}")

    web_alerts  = [a for a in all_alerts if any(k in a["level"] for k in ["WEB_","ALERT_"])]
    sfd_ups     = [a for a in all_alerts if "SFD_UPGRADE" in a["level"]]
    new_reserve = [a for a in all_alerts if "SFD_NEW_ENTRY" in a["level"]]

    print(f"\n[Layer5] Alert Summary")
    print(f"  Grid/Alarm: {len(web_alerts)} | SFD Upgrade: {len(sfd_ups)} | New RESERVE: {len(new_reserve)}")

    for a in web_alerts + sfd_ups:
        print(f"\n  {a['level']} | {a['message']}")
        print(f"    → {a['action']}")

    if new_reserve:
        print(f"\n  SFD_NEW_ENTRY (RESERVE_BUY) {len(new_reserve)} tickers:")
        for a in new_reserve:
            print(f"    {a['ticker']} {a['name']} → {a['action']}")

    ws = watch_summary
    print(f"\n  WATCH_ONLY new entries total {ws['total']} (TOP {ws['top_n']}):")
    for i, item in enumerate(ws["top_list"], 1):
        print(f"    {i}. {item['ticker']} {item['name']:10s} | score={item['score']} | {item['sector']}")

    pd.DataFrame(rows).to_csv(STATUS_OUT, index=False, encoding="utf-8-sig")
    with open(ALERTS_OUT, "w", encoding="utf-8") as f:
        json.dump({"as_of_date": today, "total_alerts": len(all_alerts),
                   "alerts": all_alerts, "watch_only_new_summary": watch_summary},
                  f, ensure_ascii=False, indent=2)
    portfolio["_last_updated"] = today
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(portfolio, f, ensure_ascii=False, indent=2)

    print(f"\n  → {STATUS_OUT}")
    print(f"  → {ALERTS_OUT}")
    print(f"[Layer5] DONE")
    return 0

if __name__ == "__main__":
    sys.exit(main())
