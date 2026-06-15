"""
sfd_account_report.py v1.0
===========================
목적: 계좌 분석 & 손실탈출/수익실현 전략 레포트 생성 (Page 2)
출력: outputs/latest/sfd_account_latest.html
      outputs/reports/sfd_account_YYYYMMDD.html

섹션 구성:
  A0 — 계좌 요약 (총평가금액 / 수익률 / 예수금)
  A1 — 보유종목 현황 (매수가/현재가/수익률/등급)
  A2 — 손실 탈출 전략 (단계별 트리거)
  A3 — 추가매수 신호 (트리거 도달 종목)
  A4 — 수익 실현 전략 (+15%/+30% 분할매도)
  A5 — DART 이벤트 (보유종목 공시 알림)

트리거 기준:
  Grade A: -15% (1차 추가매수), -30% (손절 검토)
  Grade B: -25% (경고), -40% (손절 검토)
  Grade C: -20% (방치→매도 검토)
  수익실현: +15% (1차), +30% (2차)
"""

import os, csv, json, time, requests, logging
from datetime import datetime, date
from pathlib import Path

# ── 경로 ──────────────────────────────────────────────────────
_DIR = Path(__file__).resolve().parent
def _find_root():
    for c in [_DIR, _DIR.parent]:
        if (c / ".env").exists(): return c
    return _DIR

BASE_DIR    = _find_root()
OUTPUT_DIR  = BASE_DIR / "outputs" / "latest"
REPORT_DIR  = BASE_DIR / "outputs" / "reports"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [ACCOUNT_RPT] %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

# ── .env ──────────────────────────────────────────────────────
def load_env():
    ep = BASE_DIR / ".env"
    if ep.exists():
        for line in ep.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()
load_env()

KIS_KEY    = os.environ.get("KIS_APP_KEY", "")
KIS_SECRET = os.environ.get("KIS_APP_SECRET", "").replace("\n","")
KIS_ACCT   = os.environ.get("KIS_ACCOUNT_NO", "44626570")
KIS_BASE   = "https://openapi.koreainvestment.com:9443"

# ══════════════════════════════════════════════════════════════
# KIS API
# ══════════════════════════════════════════════════════════════
def get_token() -> str:
    r = requests.post(f"{KIS_BASE}/oauth2/tokenP",
        json={"grant_type":"client_credentials","appkey":KIS_KEY,"appsecret":KIS_SECRET}, timeout=10)
    return r.json().get("access_token","")

def kis_get(path, params, tr_id, token) -> dict:
    h = {"content-type":"application/json","authorization":f"Bearer {token}",
         "appkey":KIS_KEY,"appsecret":KIS_SECRET,"tr_id":tr_id,"custtype":"P"}
    r = requests.get(f"{KIS_BASE}{path}", headers=h, params=params, timeout=15)
    r.raise_for_status()
    return r.json()

def fetch_balance(token: str) -> tuple[list, dict]:
    """KIS 잔고 조회 → (보유종목 리스트, 계좌요약)"""
    params = {
        "CANO": KIS_ACCT[:8], "ACNT_PRDT_CD": "01",
        "AFHR_FLPR_YN":"N","OFL_YN":"","INQR_DVSN":"02",
        "UNPR_DVSN":"01","FUND_STTL_ICLD_YN":"N","FNCG_AMT_AUTO_RDPT_YN":"N",
        "PRCS_DVSN":"00","CTX_AREA_FK100":"","CTX_AREA_NK100":"",
    }
    try:
        raw = kis_get("/uapi/domestic-stock/v1/trading/inquire-balance",
                      params, "TTTC8434R", token)
        holdings = raw.get("output1", []) or []
        summary  = (raw.get("output2") or [{}])
        summary  = summary[0] if isinstance(summary, list) else summary
        return holdings, summary
    except Exception as e:
        log.error(f"KIS 잔고 조회 실패: {e}")
        return [], {}

# ══════════════════════════════════════════════════════════════
# 로컬 데이터 로드
# ══════════════════════════════════════════════════════════════
def load_portfolio_json() -> dict:
    for p in [BASE_DIR/"portfolio.json", OUTPUT_DIR/"portfolio.json"]:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return {}

def load_dart_events() -> dict:
    """ticker → {event_type, impact_score, report_nm, url}"""
    result = {}
    fp = OUTPUT_DIR / "sfd_dart_event_latest.csv"
    if not fp.exists(): return result
    with open(fp, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            t = row.get("ticker","").zfill(6)
            if row.get("in_sfd") == "Y":
                result.setdefault(t, []).append(row)
    return result

def load_sfd_signals() -> dict:
    """ticker → {total_score, signal}"""
    result = {}
    for fname in ["sfd_master_signal_latest.csv","sfd_master_signal.csv"]:
        fp = OUTPUT_DIR / fname
        if fp.exists():
            with open(fp, encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    code = row.get("stock_code", row.get("ticker",""))
                    if code: result[code] = row
            break
    return result

# ══════════════════════════════════════════════════════════════
# 분석 엔진
# ══════════════════════════════════════════════════════════════
GRADE_TRIGGER = {"A": -15, "B": -25, "C": -20}
GRADE_CUTLOSS = {"A": -30, "B": -40, "C": -30}
PROFIT_T1, PROFIT_T2 = +15, +30

def analyze_holding(h: dict, kis_price_map: dict, dart_map: dict, sig_map: dict) -> dict:
    """종목 1개 분석 → 전략 판단"""
    ticker    = str(h.get("ticker","")).zfill(6)
    name      = h.get("name", ticker)
    qty       = int(h.get("qty", 0) or 0)
    avg_price = float(h.get("avg_price", 0) or 0)
    grade     = h.get("grade", "C")
    step      = int(h.get("current_step", 1) or 1)
    max_steps = int(h.get("max_steps", 1) or 1)
    active          = h.get("active", True)
    catastrophic_only = h.get("catastrophic_only", False)

    # 현재가: KIS 실시간 > portfolio.json
    cur = kis_price_map.get(ticker, float(h.get("current_price", avg_price) or avg_price))
    if cur == 0: cur = avg_price

    ret_pct    = ((cur - avg_price) / avg_price * 100) if avg_price > 0 else 0
    eval_amt   = cur * qty
    profit_amt = (cur - avg_price) * qty

    trig_pct   = GRADE_TRIGGER.get(grade, -20)
    cut_pct    = GRADE_CUTLOSS.get(grade, -30)
    trig_price = avg_price * (1 + trig_pct/100)
    cut_price  = avg_price * (1 + cut_pct/100)
    p1_price   = avg_price * (1 + PROFIT_T1/100)
    p2_price   = avg_price * (1 + PROFIT_T2/100)

    # SFD 신호 / DART (전략 판단 전에 조회)
    sig        = sig_map.get(ticker, {})
    sfd_score  = sig.get("total_score", sig.get("score",""))
    sfd_signal = sig.get("signal", h.get("sfd_signal",""))
    dart_hits  = dart_map.get(ticker, [])

    # [수정 1] active=False → INACTIVE 즉시 반환 (트리거 계산 스킵)
    if not active:
        return {
            "ticker": ticker, "name": name, "qty": qty,
            "avg_price": avg_price, "cur_price": cur,
            "ret_pct": ret_pct, "eval_amt": eval_amt, "profit_amt": profit_amt,
            "grade": grade, "step": step, "max_steps": max_steps,
            "trig_pct": trig_pct, "trig_price": trig_price,
            "cut_pct": cut_pct, "cut_price": cut_price,
            "p1_price": p1_price, "p2_price": p2_price,
            "strategy": "INACTIVE", "strategy_detail": "거미줄 비활성 — 전략 스킵",
            "sfd_score": sfd_score, "sfd_signal": sfd_signal,
            "dart_hits": dart_hits,
        }

    # 전략 판단 (우선순위: CUTLOSS > STEP_FULL > MONITOR > ADD_BUY > PROFIT_T2 > PROFIT_T1 > HOLD)
    strategy = "HOLD"
    strategy_detail = ""
    if ret_pct <= cut_pct:
        strategy = "CUTLOSS"
        strategy_detail = f"손절 기준 {cut_pct}% 도달 → 매도 강력 검토"
    elif ret_pct <= trig_pct:
        # [수정 3] step >= max_steps → STEP_FULL (ADD_BUY 억제)
        if step >= max_steps:
            strategy = "STEP_FULL"
            strategy_detail = f"추가매수 트리거 도달 — Step {step}/{max_steps} 소진 → 추가매수 불가"
        # [수정 2] catastrophic_only=True → MONITOR (ADD_BUY 억제)
        elif catastrophic_only:
            strategy = "MONITOR"
            strategy_detail = f"추가매수 트리거 {trig_pct}% 도달 — catastrophic_only 대기 중 (Step {step}/{max_steps})"
        else:
            strategy = "ADD_BUY"
            strategy_detail = f"추가매수 트리거 {trig_pct}% 도달 (Step {step}/{max_steps})"
    elif ret_pct >= PROFIT_T2:
        strategy = "PROFIT_T2"
        strategy_detail = f"+{PROFIT_T2}% 달성 → 2차 분할매도 검토"
    elif ret_pct >= PROFIT_T1:
        strategy = "PROFIT_T1"
        strategy_detail = f"+{PROFIT_T1}% 달성 → 1차 분할매도 검토"

    return {
        "ticker": ticker, "name": name, "qty": qty,
        "avg_price": avg_price, "cur_price": cur,
        "ret_pct": ret_pct, "eval_amt": eval_amt, "profit_amt": profit_amt,
        "grade": grade, "step": step, "max_steps": max_steps,
        "trig_pct": trig_pct, "trig_price": trig_price,
        "cut_pct": cut_pct, "cut_price": cut_price,
        "p1_price": p1_price, "p2_price": p2_price,
        "strategy": strategy, "strategy_detail": strategy_detail,
        "sfd_score": sfd_score, "sfd_signal": sfd_signal,
        "dart_hits": dart_hits,
    }

# ══════════════════════════════════════════════════════════════
# HTML 렌더링
# ══════════════════════════════════════════════════════════════
STRATEGY_STYLE = {
    "CUTLOSS":   {"color": "#ff1744", "label": "🚨 손절 검토",      "desc": "손절 기준 도달"},
    "ADD_BUY":   {"color": "#ff9800", "label": "📥 추가매수 트리거", "desc": "추가매수 트리거 도달"},
    "PROFIT_T2": {"color": "#00e676", "label": "💰 2차 수익실현",   "desc": "+30% 달성"},
    "PROFIT_T1": {"color": "#69f0ae", "label": "✅ 1차 수익실현",   "desc": "+15% 달성"},
    "HOLD":      {"color": "#888",    "label": "⏳ 보유 유지",      "desc": "관망"},
    "MONITOR":   {"color": "#f59e0b", "label": "🟡 MONITOR",        "desc": "트리거 도달 — 추가매수 보류(catastrophic 대기)"},
    "STEP_FULL": {"color": "#6366f1", "label": "🔵 STEP_FULL",      "desc": "트리거 도달 — 최대 스텝 소진"},
    "INACTIVE":  {"color": "#6b7280", "label": "⚫ INACTIVE",       "desc": "비활성 종목 — 전략 스킵"},
}
GRADE_COLOR = {"A":"#f44336","B":"#ff9800","C":"#888"}

def color_pct(v: float) -> str:
    c = "#e53935" if v > 0 else ("#1565c0" if v < 0 else "#888")
    s = "+" if v > 0 else ""
    return f'<span style="color:{c};font-weight:600">{s}{v:.2f}%</span>'

def fmt_won(v: float) -> str:
    return f"{int(v):,}원"

def render_html(analyzed: list, summary: dict, kis_ok: bool, ts: str) -> str:
    today_str = date.today().strftime("%Y.%m.%d")

    # ── 계좌 요약 계산 ─────────────────────────────────────────
    total_eval   = sum(a["eval_amt"] for a in analyzed)
    total_profit = sum(a["profit_amt"] for a in analyzed)
    total_cost   = sum(a["avg_price"]*a["qty"] for a in analyzed)
    total_ret    = (total_profit/total_cost*100) if total_cost>0 else 0
    cash         = int(float(summary.get("dnca_tot_amt",0) or 0))
    total_asset  = total_eval + cash

    add_buy_list  = [a for a in analyzed if a["strategy"]=="ADD_BUY"]
    cutloss_list  = [a for a in analyzed if a["strategy"]=="CUTLOSS"]
    profit_list   = [a for a in analyzed if a["strategy"] in ("PROFIT_T1","PROFIT_T2")]
    dart_list     = [a for a in analyzed if a["dart_hits"]]

    # ── A0 계좌 요약 ───────────────────────────────────────────
    ret_color = "#e53935" if total_ret>0 else "#1565c0"
    alert_bar = ""
    if cutloss_list:
        alert_bar = f'<div style="background:#b71c1c;padding:8px 16px;border-radius:6px;margin-bottom:12px;font-size:13px">🚨 손절 검토 종목 {len(cutloss_list)}개 — 즉시 확인 필요</div>'
    elif add_buy_list:
        alert_bar = f'<div style="background:#e65100;padding:8px 16px;border-radius:6px;margin-bottom:12px;font-size:13px">📥 추가매수 트리거 {len(add_buy_list)}개 종목</div>'

    s_a0 = f"""
<section class="section" id="a0">
  <h2 class="sec-title">💼 A0 — 계좌 요약</h2>
  {alert_bar}
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:16px">
    <div class="card"><div class="card-label">총 평가금액</div><div class="card-val">{fmt_won(total_eval)}</div></div>
    <div class="card"><div class="card-label">총 손익</div>
      <div class="card-val" style="color:{ret_color}">{'+' if total_profit>=0 else ''}{fmt_won(total_profit)}</div></div>
    <div class="card"><div class="card-label">수익률</div>
      <div class="card-val" style="color:{ret_color}">{'+' if total_ret>=0 else ''}{total_ret:.2f}%</div></div>
    <div class="card"><div class="card-label">예수금</div><div class="card-val">{fmt_won(cash)}</div></div>
    <div class="card"><div class="card-label">총 자산</div><div class="card-val">{fmt_won(total_asset)}</div></div>
    <div class="card"><div class="card-label">보유 종목수</div><div class="card-val">{len(analyzed)}개</div></div>
  </div>
  <div style="font-size:11px;color:#666">{'✅ KIS API 실시간' if kis_ok else '⚠️ portfolio.json 기준 (실시간 아님)'} | {ts}</div>
</section>"""

    # ── A1 보유종목 현황 ───────────────────────────────────────
    rows_html = ""
    for a in sorted(analyzed, key=lambda x: x["ret_pct"]):
        _ss = STRATEGY_STYLE.get(a["strategy"], {"color": "#888", "label": ""})
        strat_color, strat_label = _ss["color"], _ss["label"]
        gc = GRADE_COLOR.get(a["grade"],"#888")
        dart_badge = f' <span style="background:#1565c0;color:#fff;font-size:10px;padding:1px 5px;border-radius:8px">DART</span>' if a["dart_hits"] else ""
        rows_html += f"""
        <tr style="border-bottom:1px solid #2a2a2a">
          <td><span style="color:{gc};font-weight:700">{a['grade']}</span></td>
          <td style="font-weight:500">{a['name']}{dart_badge}<br><span style="color:#666;font-size:10px">{a['ticker']}</span></td>
          <td style="text-align:right">{fmt_won(a['avg_price'])}</td>
          <td style="text-align:right">{fmt_won(a['cur_price'])}</td>
          <td style="text-align:right">{color_pct(a['ret_pct'])}</td>
          <td style="text-align:right;font-size:11px">{fmt_won(a['eval_amt'])}</td>
          <td style="text-align:center"><span style="color:{strat_color};font-size:11px">{strat_label}</span></td>
          <td style="text-align:center;font-size:11px;color:#aaa">{a['sfd_score']}</td>
        </tr>"""

    s_a1 = f"""
<section class="section" id="a1">
  <h2 class="sec-title">📋 A1 — 보유종목 현황</h2>
  <div style="overflow-x:auto">
  <table style="width:100%;border-collapse:collapse;font-size:12px">
    <thead><tr style="color:#aaa;border-bottom:1px solid #444">
      <th>등급</th><th style="text-align:left">종목</th>
      <th>매수가</th><th>현재가</th><th>수익률</th>
      <th>평가금액</th><th>전략</th><th>SFD점수</th>
    </tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
  </div>
</section>"""

    # ── A2 손실 탈출 전략 ──────────────────────────────────────
    tbl_rows = ""
    for a in analyzed:
        gc = GRADE_COLOR.get(a["grade"],"#888")
        bar_w = min(abs(a["ret_pct"])/40*100, 100)
        bar_c = "#e53935" if a["ret_pct"]<0 else "#43a047"
        progress = f'<div style="background:#333;border-radius:3px;height:6px;width:120px;display:inline-block"><div style="background:{bar_c};width:{bar_w:.0f}%;height:6px;border-radius:3px"></div></div>'
        tbl_rows += f"""
        <tr style="border-bottom:1px solid #222">
          <td><span style="color:{gc}">{a['grade']}</span> {a['name']}</td>
          <td style="text-align:right">{color_pct(a['ret_pct'])} {progress}</td>
          <td style="text-align:right;color:#ff9800">{a['trig_pct']}% / {fmt_won(a['trig_price'])}</td>
          <td style="text-align:right;color:#f44336">{a['cut_pct']}% / {fmt_won(a['cut_price'])}</td>
          <td style="text-align:right;color:#69f0ae">+{PROFIT_T1}% / {fmt_won(a['p1_price'])}</td>
        </tr>"""

    s_a2 = f"""
<section class="section" id="a2">
  <h2 class="sec-title">🛡️ A2 — 손실 탈출 & 수익 실현 기준</h2>
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:16px;font-size:12px">
    <div style="background:#1a1a1a;padding:10px;border-radius:8px;border-left:3px solid #ff9800">
      <div style="color:#ff9800;font-weight:700">📥 추가매수</div>
      <div>A등급: -15% (피라미딩 1:2:3:4)</div>
      <div>B등급: -25% (균등 소액 1:1)</div>
      <div>C등급: -20% (매도 검토)</div>
    </div>
    <div style="background:#1a1a1a;padding:10px;border-radius:8px;border-left:3px solid #f44336">
      <div style="color:#f44336;font-weight:700">🚨 손절 기준</div>
      <div>A등급: -30%</div>
      <div>B등급: -40%</div>
      <div>C등급: -30%</div>
    </div>
    <div style="background:#1a1a1a;padding:10px;border-radius:8px;border-left:3px solid #69f0ae">
      <div style="color:#69f0ae;font-weight:700">💰 수익 실현</div>
      <div>1차: +15% 분할매도</div>
      <div>2차: +30% 분할매도</div>
      <div>전량: 신호 EXPIRED 시</div>
    </div>
  </div>
  <div style="overflow-x:auto">
  <table style="width:100%;border-collapse:collapse;font-size:12px">
    <thead><tr style="color:#aaa;border-bottom:1px solid #444">
      <th style="text-align:left">종목</th><th>현재수익률</th>
      <th>추가매수 트리거</th><th>손절 기준</th><th>1차 수익실현</th>
    </tr></thead>
    <tbody>{tbl_rows}</tbody>
  </table>
  </div>
</section>"""

    # ── A3 추가매수 신호 ───────────────────────────────────────
    if add_buy_list:
        add_cards = ""
        for a in add_buy_list:
            add_cards += f"""
        <div style="background:#1a1a1a;border:1px solid #ff9800;border-radius:8px;padding:12px;margin-bottom:8px">
          <div style="display:flex;justify-content:space-between">
            <span style="font-weight:700">{a['name']} <span style="color:#666;font-size:11px">{a['ticker']}</span></span>
            <span style="color:#ff9800;font-weight:700">Step {a['step']}/{a['max_steps']}</span>
          </div>
          <div style="margin-top:6px;font-size:12px;display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px">
            <div>매수가: {fmt_won(a['avg_price'])}</div>
            <div>현재가: {fmt_won(a['cur_price'])}</div>
            <div>{color_pct(a['ret_pct'])}</div>
          </div>
          <div style="margin-top:6px;font-size:12px;color:#ff9800">{a['strategy_detail']}</div>
        </div>"""
        add_content = add_cards
    else:
        add_content = '<p style="color:#888;font-size:13px">현재 추가매수 트리거 도달 종목 없음</p>'

    s_a3 = f"""
<section class="section" id="a3">
  <h2 class="sec-title">📥 A3 — 추가매수 신호 ({len(add_buy_list)}건)</h2>
  {add_content}
</section>"""

    # ── A4 수익 실현 전략 ──────────────────────────────────────
    if profit_list:
        profit_cards = ""
        for a in profit_list:
            sc = STRATEGY_STYLE[a["strategy"]]["color"]
            sl = STRATEGY_STYLE[a["strategy"]]["label"]
            profit_cards += f"""
        <div style="background:#1a1a1a;border:1px solid {sc};border-radius:8px;padding:12px;margin-bottom:8px">
          <div style="display:flex;justify-content:space-between">
            <span style="font-weight:700">{a['name']}</span>
            <span style="color:{sc};font-weight:700">{sl}</span>
          </div>
          <div style="margin-top:6px;font-size:12px;display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px">
            <div>매수가: {fmt_won(a['avg_price'])}</div>
            <div>현재가: {fmt_won(a['cur_price'])}</div>
            <div>{color_pct(a['ret_pct'])}</div>
          </div>
          <div style="margin-top:4px;font-size:11px;color:#aaa">평가손익: {'+' if a['profit_amt']>=0 else ''}{fmt_won(a['profit_amt'])}</div>
        </div>"""
        profit_content = profit_cards
    else:
        profit_content = '<p style="color:#888;font-size:13px">현재 수익실현 기준 도달 종목 없음</p>'

    s_a4 = f"""
<section class="section" id="a4">
  <h2 class="sec-title">💰 A4 — 수익 실현 전략 ({len(profit_list)}건)</h2>
  {profit_content}
</section>"""

    # ── A5 DART 이벤트 ─────────────────────────────────────────
    if dart_list:
        dart_rows = ""
        for a in dart_list:
            for d in a["dart_hits"]:
                sc = int(float(d.get("impact_score",0) or 0))
                sc_color = "#e53935" if sc>0 else "#1565c0"
                sc_sign  = "+" if sc>0 else ""
                dart_rows += f"""
            <tr style="border-bottom:1px solid #222">
              <td>{a['name']}</td>
              <td style="font-size:11px">{d.get('event_type','')}</td>
              <td style="font-size:11px;max-width:200px">{d.get('report_nm','')[:35]}</td>
              <td style="color:{sc_color};font-weight:600">{sc_sign}{sc}pt</td>
              <td style="font-size:11px"><a href="{d.get('url','')}" target="_blank" style="color:#4a7abf">DART ↗</a></td>
            </tr>"""
        dart_content = f"""<table style="width:100%;border-collapse:collapse;font-size:12px">
          <thead><tr style="color:#aaa;border-bottom:1px solid #444">
            <th style="text-align:left">종목</th><th>유형</th><th>공시명</th><th>영향</th><th>링크</th>
          </tr></thead><tbody>{dart_rows}</tbody></table>"""
    else:
        dart_content = '<p style="color:#888;font-size:13px">보유종목 관련 최근 공시 없음</p>'

    s_a5 = f"""
<section class="section" id="a5">
  <h2 class="sec-title">📢 A5 — 보유종목 DART 공시</h2>
  {dart_content}
</section>"""

    # ── 네비게이션 ─────────────────────────────────────────────
    nav_items = [("a0","💼요약"),("a1","📋보유"),("a2","🛡️전략"),
                 ("a3","📥추가매수"),("a4","💰수익"),("a5","📢공시")]
    nav_html  = "".join(f'<a href="#{k}" class="nav-item">{v}</a>' for k,v in nav_items)

    # ── 전체 HTML ──────────────────────────────────────────────
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SFD 계좌분석 {today_str}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0d0d0d;color:#e0e0e0;font-family:'Segoe UI',sans-serif;font-size:13px}}
  .header{{background:#111;border-bottom:1px solid #222;padding:12px 20px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100}}
  .header-title{{font-size:18px;font-weight:700;color:#fff}}
  .header-sub{{font-size:11px;color:#888;margin-top:2px}}
  .nav-bar{{display:flex;gap:8px;flex-wrap:wrap}}
  .nav-item{{color:#aaa;text-decoration:none;font-size:12px;padding:4px 10px;border-radius:12px;border:1px solid #333;transition:all .2s}}
  .nav-item:hover{{background:#2a4a7f;color:#fff;border-color:#4a7abf}}
  .page-link{{background:#1e1e1e;border:1px solid #444;color:#ccc;padding:5px 14px;border-radius:12px;text-decoration:none;font-size:12px}}
  .page-link:hover{{background:#2a4a7f;color:#fff}}
  .content{{max-width:1100px;margin:0 auto;padding:20px}}
  .section{{background:#161616;border-radius:10px;padding:20px;margin-bottom:20px;border:1px solid #222}}
  .sec-title{{font-size:15px;font-weight:700;margin-bottom:14px;color:#fff}}
  .card{{background:#1e1e1e;border-radius:8px;padding:12px;border:1px solid #2a2a2a}}
  .card-label{{font-size:11px;color:#888;margin-bottom:4px}}
  .card-val{{font-size:16px;font-weight:700}}
  table th{{padding:8px 6px;font-weight:600;white-space:nowrap}}
  table td{{padding:7px 6px}}
</style>
</head>
<body>
<div class="header">
  <div>
    <div class="header-title">📊 SFD — 계좌 분석 리포트</div>
    <div class="header-sub">{today_str} | v1.0 | {'KIS 실시간' if kis_ok else 'portfolio.json 기준'}</div>
  </div>
  <div style="display:flex;align-items:center;gap:12px">
    <nav class="nav-bar">{nav_html}</nav>
    <a href="sfd_report_latest.html" class="page-link">← 급등주 예측 (P1)</a>
  </div>
</div>
<div class="content">
  {s_a0}{s_a1}{s_a2}{s_a3}{s_a4}{s_a5}
</div>
</body>
</html>"""

# ══════════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════════
def run():
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log.info(f"=== sfd_account_report.py v1.0 시작 ({ts}) ===")

    portfolio = load_portfolio_json()
    holdings  = portfolio.get("holdings", [])
    dart_map  = load_dart_events()
    sig_map   = load_sfd_signals()

    # KIS 실시간 잔고 시도
    kis_ok = False
    kis_price_map = {}
    summary = {}
    if KIS_KEY and KIS_SECRET:
        try:
            token = get_token()
            raw_holdings, summary = fetch_balance(token)
            if raw_holdings:
                for row in raw_holdings:
                    code = row.get("pdno","").zfill(6)
                    price = float(row.get("prpr", row.get("stck_prpr",0)) or 0)
                    if code and price:
                        kis_price_map[code] = price
                kis_ok = True
                log.info(f"KIS 실시간 잔고: {len(raw_holdings)}종목")
        except Exception as e:
            log.warning(f"KIS 잔고 실패 → portfolio.json fallback: {e}")

    if not holdings:
        log.warning("portfolio.json 보유종목 없음")

    analyzed = [analyze_holding(h, kis_price_map, dart_map, sig_map) for h in holdings]

    html = render_html(analyzed, summary, kis_ok, ts)

    today_str = date.today().strftime("%Y%m%d")
    out1 = OUTPUT_DIR / "sfd_account_latest.html"
    out2 = REPORT_DIR / f"sfd_account_{today_str}.html"
    for p in [out1, out2]:
        p.write_text(html, encoding="utf-8")

    log.info(f"[완료] {out1}")
    log.info(f"  보유종목: {len(analyzed)}개 | 추가매수 트리거: {len([a for a in analyzed if a['strategy']=='ADD_BUY'])}개")
    log.info(f"  손절 검토: {len([a for a in analyzed if a['strategy']=='CUTLOSS'])}개 | 수익실현: {len([a for a in analyzed if 'PROFIT' in a['strategy']])}개")

if __name__ == "__main__":
    run()
