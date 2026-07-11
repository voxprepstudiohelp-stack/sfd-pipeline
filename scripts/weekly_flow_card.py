# weekly_flow_card.py v1.0
# 벤치마킹 ⑤ 구현: 주간 수급 랭킹 카드 (KRX 정규화 방식)
# 위치: sfd-pipeline/scripts/weekly_flow_card.py
# 핵심: 거래대금 대비 투자자별 순매수 비중(%) 정규화
#
# 입력: outputs/latest/sfd_investor_flow_latest.csv (P1 산출물)
#   필요 컬럼(유연 매핑): ticker, name, 외국인순매수(frgn_net), 개인순매수(indi_net),
#                         거래대금(trade_amount) — 주간 누적 또는 일별
# 출력: dashboard/data/weekly_flow_card.json + dashboard/weekly_card.html
# 절대규칙: 실데이터 없으면 카드 생성 안 함 (임의 종목+수치 조합 금지)

import json
import csv
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
NOW = datetime.now(KST)

_ROOT = Path(__file__).resolve().parent.parent
_LATEST = _ROOT / "outputs" / "latest"
_DASH = _ROOT / "dashboard"
(_DASH / "data").mkdir(parents=True, exist_ok=True)

# 입력 후보 (P1 산출물 파일명 유연 탐색)
INPUT_CANDIDATES = [
    _LATEST / "sfd_investor_flow_latest.csv",
    _LATEST / "sfd_investor_weekly.csv",
    _LATEST / "investor_flow.csv",
]
OUT_JSON = _DASH / "data" / "weekly_flow_card.json"
OUT_HTML = _DASH / "weekly_card.html"

TOP_N = 20  # 거래대금 Top 20 기준 (벤치마킹 동일)

# 컬럼명 유연 매핑
COL_MAP = {
    "ticker":       ["ticker", "stock_code", "종목코드"],
    "name":         ["name", "stock_name", "종목명"],
    "frgn_net":     ["frgn_net", "foreign_net", "외국인순매수", "frgn_ntby_qty"],
    "indi_net":     ["indi_net", "individual_net", "개인순매수", "prsn_ntby_qty"],
    "trade_amount": ["trade_amount", "acml_tr_pbmn", "거래대금", "trading_value"],
}


def find_col(header: list, keys: list) -> str | None:
    for k in keys:
        if k in header:
            return k
    return None


def load_flow() -> list[dict] | None:
    src = next((p for p in INPUT_CANDIDATES if p.exists()), None)
    if not src:
        print("[SKIP] 수급 입력 파일 없음 — 카드 생성 안 함 (절대규칙: 임의 데이터 금지)")
        return None
    with open(src, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None
    header = list(rows[0].keys())
    cols = {k: find_col(header, v) for k, v in COL_MAP.items()}
    missing = [k for k, v in cols.items() if v is None]
    if missing:
        print(f"[SKIP] 필수 컬럼 없음: {missing} — 카드 생성 안 함")
        return None

    def num(v):
        try:
            return float(str(v).replace(",", ""))
        except:
            return 0.0

    out = []
    for r in rows:
        amt = num(r[cols["trade_amount"]])
        if amt <= 0:
            continue
        out.append({
            "ticker": str(r[cols["ticker"]]).zfill(6),
            "name":   r[cols["name"]],
            "frgn_pct": round(num(r[cols["frgn_net"]]) / amt * 100, 2),  # ★정규화
            "indi_pct": round(num(r[cols["indi_net"]]) / amt * 100, 2),
            "trade_amount": amt,
        })
    # 거래대금 Top N 필터 (벤치마킹 동일 기준)
    out.sort(key=lambda x: x["trade_amount"], reverse=True)
    return out[:TOP_N]


def render_html(data: list[dict], key: str, title: str, color: str) -> str:
    rows = sorted(data, key=lambda x: x[key], reverse=True)
    max_abs = max(abs(r[key]) for r in rows) or 1
    bars = ""
    for r in rows:
        v = r[key]
        w = abs(v) / max_abs * 45  # 최대 45% 폭
        side = "margin-left:50%" if v >= 0 else f"margin-left:{50-w}%"
        label = f'{v:+.2f}' if abs(v) == max_abs else ""
        bars += (
            f'<div class="row"><span class="nm">{r["name"]}</span>'
            f'<div class="track"><div class="bar" style="width:{w}%;{side};background:{color}"></div></div>'
            f'<span class="lb">{label}</span></div>\n'
        )
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<title>{title}</title><style>
body{{font-family:-apple-system,'Apple SD Gothic Neo',sans-serif;background:#0d0d0d;color:#eee;max-width:640px;margin:0 auto;padding:24px}}
h1{{font-size:20px}} .sub{{color:#999;font-size:12px;margin-bottom:16px}}
.row{{display:flex;align-items:center;gap:8px;margin:3px 0}}
.nm{{width:120px;font-size:12px;text-align:right;color:#ccc}}
.track{{flex:1;height:14px;position:relative;background:#1a1a1a;border-radius:2px}}
.bar{{height:100%;border-radius:2px}}
.lb{{width:52px;font-size:11px;color:#aaa}}
.src{{margin-top:14px;font-size:10px;color:#666}}
</style></head><body>
<h1>{title}</h1>
<div class="sub">주간 증시 요약 · 거래대금 Top {TOP_N} 기준 · {NOW.strftime('%m.%d')} 기준 · SFD pipeline</div>
{bars}
<div class="src">Source: KIS API (P1 investor flow) · 거래대금 대비 순매수 비중(%) 정규화 · 생성 {NOW.strftime('%Y-%m-%d %H:%M KST')}</div>
</body></html>"""


def main():
    data = load_flow()
    payload = {
        "meta": {"generated_at": NOW.isoformat(), "generated_at_kst": NOW.strftime("%Y-%m-%d %H:%M KST"), "top_n": TOP_N},
        "available": bool(data),
        "rows": data or [],
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[OK] JSON 저장: {OUT_JSON} (rows={len(data or [])})")

    if data:
        html = render_html(data, "frgn_pct", "외국인 매수세가 가장 강했던 종목", "#4a90d9")
        with open(OUT_HTML, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[OK] HTML 카드 저장: {OUT_HTML}")
    else:
        print("[INFO] 실데이터 없음 — HTML 카드 미생성 (빈 상태 유지)")


if __name__ == "__main__":
    main()
