#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sfd_daily_report.py v1.0
SFD 일일 HTML 레포트 생성기 (7섹션 완전판)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
S0: 글로벌 온도계 (지수/환율/원자재/VIX)
S1: 오늘의 한국 영향 요인 (뉴스 트리거→섹터)
S2: 캘린더 경보 (D-30/7/1 자동 팝업)
S3: 급등예상 TOP10
S4: 종목 상세 카드
S5: 미래산업 모멘텀 게이지
S6: 벤치마킹 + 자가진단
출력: sfd_report_YYYYMMDD.html
실행: python -X utf8 tools/sfd_daily_report.py
스케줄: 08:10 장전 / 16:10 장마감
"""

import os, sys, json, csv, logging
from datetime import datetime
from pathlib import Path

import json as _json

def _load_market_rank() -> dict:
    _p = Path(__file__).parent / "outputs" / "latest" / "sfd_market_rank.json"
    if _p.exists():
        try:
            return _json.loads(_p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def _build_s7_section(rank_data: dict = None) -> str:
    if rank_data is None:
        rank_data = _load_market_rank()
    updated = rank_data.get("generated_at", "")
    def _tbl(rows, show_vol=False, show_net=False, empty_msg="데이터 없음"):
        if not rows:
            return f'<p style="color:#888;font-size:12px;padding:8px">{empty_msg}</p>'
        extra_th = "<th>거래량</th><th>증감%</th>" if show_vol else ("<th>순매수</th>" if show_net else "<th>거래량</th>")
        body = ""
        for r in rows:
            rate = r.get("change_rate", 0)
            color = "#e53935" if rate > 0 else ("#1565c0" if rate < 0 else "#888")
            sign = "+" if rate > 0 else ""
            code = r.get("code","")
            link = f'<a href="https://finance.naver.com/item/main.nhn?code={code}" target="_blank" style="color:inherit;text-decoration:none">{r.get("name", code)}</a>'
            if show_vol:
                extra_td = f'<td>{int(r.get("volume",0)):,}</td><td>{r.get("vol_ratio","")}</td>'
            elif show_net:
                nb = r.get("net_buy",0); snb = "+" if nb>0 else ""
                extra_td = f'<td style="color:{color}">{snb}{nb:,}</td>'
            else:
                extra_td = f'<td>{int(r.get("volume",0)):,}</td>'
            body += f'<tr><td style="color:#888">{r["rank"]}</td><td>{link}</td><td>{int(r.get("price",0)):,}</td><td style="color:{color};font-weight:600">{sign}{rate:.2f}%</td>{extra_td}</tr>'
        return f'<table style="width:100%;border-collapse:collapse;font-size:12px"><thead><tr style="border-bottom:1px solid #333;color:#aaa"><th>#</th><th style="text-align:left">종목</th><th>현재가</th><th>등락률</th>{extra_th}</tr></thead><tbody>{body}</tbody></table>'
    tabs = [
        ("rise","🔴 상승",_tbl(rank_data.get("rise_top15",[]))),
        ("fall","🔵 하락",_tbl(rank_data.get("fall_top15",[]))),
        ("vol","📈 거래량",_tbl(rank_data.get("volume_top15",[]),show_vol=True)),
        ("foreign","🌍 외국인",_tbl(rank_data.get("foreign_top15",[]),show_net=True,empty_msg="파이프라인 실행 후 표시")),
        ("inst","🏦 기관",_tbl(rank_data.get("institution_top15",[]),show_net=True,empty_msg="파이프라인 실행 후 표시")),
    ]
    btn_html = "".join(f'<button onclick="showRankTab(\'{k}\')" class="rtab{" active" if i==0 else ""}" id="rtab-{k}">{lbl}</button>' for i,(k,lbl,_) in enumerate(tabs))
    panel_html = "".join(f'<div id="rank-{k}" class="rank-panel{" active" if i==0 else ""}">{tbl}</div>' for i,(k,_,tbl) in enumerate(tabs))
    return f"""<section id="s7" class="section">
  <h2 class="sec-title">📊 시장 순위 <span style="font-size:11px;color:#888;font-weight:normal">TOP 15</span><span style="font-size:10px;color:#666;float:right">{updated}</span></h2>
  <div style="display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap">{btn_html}</div>
  <style>.rtab{{padding:4px 10px;border-radius:12px;border:1px solid #444;background:#1e1e1e;color:#ccc;cursor:pointer;font-size:12px}}.rtab.active{{background:#2a4a7f;border-color:#4a7abf;color:#fff}}.rank-panel{{display:none}}.rank-panel.active{{display:block}}</style>
  {panel_html}
  <script>function showRankTab(n){{document.querySelectorAll('.rank-panel').forEach(p=>p.classList.remove('active'));document.querySelectorAll('.rtab').forEach(b=>b.classList.remove('active'));document.getElementById('rank-'+n).classList.add('active');document.getElementById('rtab-'+n).classList.add('active');}}</script>
</section>"""

BASE_DIR = os.environ.get("SFD_BASE_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUTPUT_DIR   = os.path.join(BASE_DIR, "outputs", "latest")
REPORT_DIR   = os.path.join(BASE_DIR, "outputs", "reports")
os.makedirs(REPORT_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(asctime)s - %(message)s")
logger = logging.getLogger(__name__)

# ── 데이터 로드 헬퍼 ─────────────────────────────────────────────

def load_json(filename):
    path = os.path.join(OUTPUT_DIR, filename)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def load_csv(filename):
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def load_calendar():
    path = os.path.join(BASE_DIR, "data", "sfd_calendar_3yr.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

# ── 데이터 준비 ───────────────────────────────────────────────────

def prepare_data():
    radar  = load_json("sfd_global_radar_latest.json")
    master = load_csv("sfd_master_signal_latest.csv")
    signal = load_csv("sfd_signal.csv")
    backtest = load_json("sfd_backtest_report.json")
    grid   = load_csv("sfd_grid_signal_latest.csv")
    news   = load_csv("sfd_news_signal_latest.csv")
    timeout = load_json("signal_timeout_state.json")
    calendar = load_calendar()

    # TOP20: master_signal에서 WATCH_ONLY/RESERVE_BUY 상위
    candidates = [r for r in master if r.get("signal") in ("WATCH_ONLY", "RESERVE_BUY")]
    try:
        candidates.sort(key=lambda x: float(x.get("total_score", 0)), reverse=True)
    except Exception:
        pass
    top10 = candidates[:20]  # TOP20으로 확장

    # prev_close 보강: sfd_prev_close_latest.csv LEFT JOIN by ticker
    _pc_path = os.path.join(OUTPUT_DIR, "sfd_prev_close_latest.csv")
    _pc_map: dict = {}
    if os.path.exists(_pc_path):
        try:
            with open(_pc_path, "r", encoding="utf-8-sig") as _f:
                for _row in csv.DictReader(_f):
                    _t = _row.get("ticker", "").strip()
                    if _t:
                        _pc_map[_t] = _row
        except Exception:
            pass
    if _pc_map:
        for r in top10:
            _src = _pc_map.get(r.get("ticker", ""), {})
            if not r.get("prev_close") and _src.get("prev_close"):
                r["prev_close"] = _src["prev_close"]
            if not r.get("close") and _src.get("close"):
                r["close"] = _src["close"]

    # SIGNAL_EXPIRED 경고
    expired = [r for r in master if r.get("signal") == "SIGNAL_EXPIRED"]

    # recent_trades: RESERVE_BUY 실적 (return_d1 내림차순 TOP10)
    recent_trades = []
    _bt_csv = os.path.join(OUTPUT_DIR, "sfd_backtest_report.csv")
    if os.path.exists(_bt_csv):
        try:
            with open(_bt_csv, "r", encoding="utf-8-sig") as _f:
                _rows = [r for r in csv.DictReader(_f)
                         if r.get("signal_label") == "RESERVE_BUY"
                         and r.get("return_d1", "") != ""]
            _rows.sort(key=lambda x: float(x["return_d1"]), reverse=True)
            recent_trades = _rows[:10]
        except Exception:
            pass

    return {
        "radar": radar,
        "top10": top10,
        "expired": expired,
        "backtest": backtest,
        "grid": grid,
        "news_map": {r["ticker"]: r for r in news if "ticker" in r},
        "timeout": timeout,
        "calendar": calendar,
        "master": master,
        "recent_trades": recent_trades,
    }

# ── 색상/아이콘 헬퍼 ─────────────────────────────────────────────

def chg_color(v):
    if v is None: return "#888"
    return "#e24b4a" if float(v) >= 0 else "#378add"

def chg_arrow(v):
    if v is None: return "−"
    return f"▲ {abs(float(v)):.2f}%" if float(v) >= 0 else f"▼ {abs(float(v)):.2f}%"

def signal_badge(sig):
    colors = {
        "RESERVE_BUY":    ("#e24b4a", "⭐ 매수후보"),
        "WATCH_ONLY":     ("#EF9F27", "👁 관심"),
        "HOLD":           ("#888",    "⏸ 보유"),
        "SIGNAL_EXPIRED": ("#A32D2D", "⚠ 신호만료"),
    }
    c, t = colors.get(sig, ("#888", sig))
    return f'<span style="background:{c};color:#fff;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:500">{t}</span>'

def urgency_style(u):
    return {
        "HIGH": "background:#FCEBEB;border-left:4px solid #E24B4A;",
        "MID":  "background:#FAEEDA;border-left:4px solid #EF9F27;",
        "LOW":  "background:#E6F1FB;border-left:4px solid #378ADD;",
    }.get(u, "")

# ── S0: 글로벌 온도계 ─────────────────────────────────────────────

def render_s0(radar):
    market = radar.get("market", {})
    indices    = market.get("indices", {})
    fx_rates   = market.get("fx_rates", {})
    commodities= market.get("commodities", {})
    vix_note   = radar.get("vix_note", "")

    # 지수별 한국 영향 설명
    INDEX_CONTEXT = {
        "KOSPI":    ("코스피", "한국 대형주 종합지수", "직접 지표"),
        "KOSDAQ":   ("코스닥", "한국 중소형/기술주 지수", "직접 지표"),
        "SP500":    ("S&P500", "미국 500대 기업 지수 — 전일 등락이 다음날 코스피 방향에 60~70% 연동", "글로벌 선행"),
        "NASDAQ":   ("나스닥", "미국 기술주 지수 — 반도체/AI주 직접 연동. NASDAQ↑ → 삼성전자/SK하이닉스 강세", "반도체 선행"),
        "DOW":      ("다우존스", "미국 우량주 30개 — 경기 방향성 지표", "경기 선행"),
        "NIKKEI":   ("닛케이", "일본 지수 — 엔화/원화 동조화. 닛케이↓ = 아시아 리스크 확대", "아시아 동조"),
        "SHANGHAI": ("상하이", "중국 지수 — 화장품/면세/소재주 연동. 상하이↑ → 중국 소비 관련주 강세", "중국 소비 선행"),
        "HANGSENG": ("항셍", "홍콩 지수 — 중국 자본 흐름 바로미터", "중국 자본"),
    }
    FX_CONTEXT = {
        "USD_KRW": ("달러/원", "원화 약세(↑) → 수출주 유리, 수입 원자재주 불리. 1,400원 돌파 시 외국인 이탈 경고"),
        "USD_JPY": ("달러/엔", "엔화 약세(↑) → 일본 수출주 경쟁력↑, 한국 자동차/전자와 경쟁"),
        "USD_CNY": ("달러/위안", "위안화 약세(↑) → 중국 수출 유리, 한국 대중국 수출 불리"),
        "EUR_USD": ("유로/달러", "유로 강세(↑) → 글로벌 달러 약세 신호, 신흥국 외국인 자금 유입"),
    }
    COM_CONTEXT = {
        "GOLD":    ("금", "안전자산 선호 지표. 금↑ = 리스크 오프 → 방어주/금 관련주 강세"),
        "OIL_WTI": ("WTI유가", "유가↑ → 정유/조선(LNG선) 강세, 항공/운송 약세. 중동 긴장 시 급등"),
        "COPPER":  ("구리", "'닥터 코퍼' — 경기 선행 지표. 구리↑ = 글로벌 경기 회복 신호 → 소재/건설 강세"),
        "NATGAS":  ("천연가스", "천연가스↑ → LNG 운반선/가스 관련주 강세. 겨울 시즌 계절성"),
        "BTC":     ("비트코인", "Risk-on 지표. BTC↑ = 위험자산 선호 → 성장주/기술주 동반 강세 경향"),
        "VIX":     ("VIX 공포지수", "20 미만: 안정 | 20~30: 경계 | 30+: 공포(저점 매수 기회). 오늘: " + str(vix_note)),
        "US10Y":   ("미국10년국채", "금리↑ = 성장주 불리, 배당주/리츠 불리. 4.5% 돌파 시 외국인 이탈 경고"),
    }

    def row(d, key=""):
        if not d or d.get("price") is None:
            return ""
        color = chg_color(d.get("chg_pct"))
        arrow = chg_arrow(d.get("chg_pct"))
        # 팝업 데이터
        ctx = INDEX_CONTEXT.get(key) or FX_CONTEXT.get(key) or COM_CONTEXT.get(key)
        popup_title = ctx[0] if ctx else d.get('label','')
        popup_desc  = ctx[1] if ctx else ""
        popup_tag   = ctx[2] if ctx and len(ctx) > 2 else ""
        chg = d.get('chg_pct', 0) or 0
        impact = "상승 — 관련 섹터 긍정적" if float(chg) > 0 else "하락 — 관련 섹터 주의" if float(chg) < 0 else "보합"
        price_str = str(d.get('price', '-'))
        onclick = f"showInfoPopup('{popup_title}', '{popup_desc}', '{popup_tag}', '{price_str}', '{arrow}', '{impact}')"
        return f"""
        <div class="mcard" onclick="{onclick}" style="cursor:pointer" title="클릭하면 상세 설명">
          <div class="mlabel">{d.get('label','')}</div>
          <div class="mprice">{d.get('price', '-'):,.2f}</div>
          <div class="mchg" style="color:{color}">{arrow}</div>
        </div>"""

    idx_html = "".join(row(v, k) for k, v in indices.items())
    fx_html  = "".join(row(v, k) for k, v in fx_rates.items())
    com_html = "".join(row(v, k) for k, v in commodities.items())

    # RSS 헤드라인 상위 10건 (모바일도 충분히)
    def _news_summary(title):
        t = title.lower()
        if any(k in t for k in ("cuts", "downgrade", "upgrade")): return "등급변경"
        if "ipo" in t: return "IPO"
        if any(k in t for k in ("earnings", "profit")): return "실적"
        if any(k in t for k in ("rate", "fed", "fomc")): return "금리"
        if any(k in t for k in ("crash", "disaster", "accident")): return "사고"
        return title[:20]

    headlines = radar.get("rss_headlines", [])[:10]
    hl_html = ""
    for h in headlines:
        _t = h.get("title", "")
        _summary = _news_summary(_t)
        hl_html += f'<div class="hl-item"><span class="hl-src">{h.get("source","")}</span> <a href="{h.get("link","#")}" target="_blank" style="color:var(--text-primary)">{_t}</a> <span style="color:#888;font-size:11px;margin-left:6px">| {_summary}</span></div>'

    vix_val = (commodities.get("VIX") or {}).get("price")
    vix_color = "#e24b4a" if vix_val and vix_val > 25 else "#3B6D11"

    return f"""
<section id="s0" class="section">
  <h2 class="sec-title">📡 S0 — 글로벌 온도계 <span style="font-size:11px;color:#888;font-weight:400">카드 클릭 → 한국 영향 설명</span></h2>
  <div class="subsec-label">주요 지수</div>
  <div class="market-grid">{idx_html}</div>
  <div class="subsec-label" style="margin-top:12px">환율</div>
  <div class="market-grid">{fx_html}</div>
  <div class="subsec-label" style="margin-top:12px">원자재 & 자산</div>
  <div class="market-grid">{com_html}</div>
  <div class="vix-bar" style="color:{vix_color}">
    VIX {vix_val or '—'} → {vix_note}
  </div>
  <div class="subsec-label" style="margin-top:16px">글로벌 뉴스 헤드라인 (클릭 → 원문)</div>
  <div class="hl-box">{hl_html if hl_html else '<div class="empty">뉴스 없음</div>'}</div>
</section>"""

# ── S1: 오늘의 한국 영향 요인 ────────────────────────────────────

def render_s1(radar):
    triggers = radar.get("sector_triggers", [])
    if not triggers:
        return '<section id="s1" class="section"><h2 class="sec-title">🇰🇷 S1 — 오늘의 한국 영향 요인</h2><div class="empty">뉴스 트리거 없음</div></section>'

    pos = [t for t in triggers if t.get("boost", 0) > 0]
    neg = [t for t in triggers if t.get("boost", 0) < 0]

    def trig_card(t):
        color = "#e24b4a" if t.get("boost", 0) > 0 else "#378add"
        sign  = "+" if t.get("boost", 0) > 0 else ""
        tickers_str = ", ".join(t.get("tickers", [])[:4])
        direction = "상승" if t.get("boost",0) > 0 else "하락"
        onclick = f"showInfoPopup('{t.get('sector','')}', '{t.get('headline','').replace(chr(39),'')}', '{t.get('source','')} · 키워드: {t.get('keyword','')}', '{sign}{t.get('boost',0)}pt boost', '관련 종목코드: {tickers_str}', '{direction} 트리거')"
        return f"""
        <div class="trig-card" onclick="{onclick}" style="cursor:pointer">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span class="trig-sector">{t.get('sector','')}</span>
            <span style="color:{color};font-weight:500;font-size:12px">{sign}{t.get('boost',0)}pt</span>
          </div>
          <div class="trig-headline">"{t.get('headline','')}"</div>
          <div class="trig-src">{t.get('source','')} · 키워드: {t.get('keyword','')}</div>
        </div>"""

    pos_html = "".join(trig_card(t) for t in pos[:5])
    neg_html = "".join(trig_card(t) for t in neg[:3])

    return f"""
<section id="s1" class="section">
  <h2 class="sec-title">🇰🇷 S1 — 오늘의 한국 영향 요인</h2>
  <div class="two-col">
    <div>
      <div class="subsec-label" style="color:#e24b4a">▲ 상승 트리거 ({len(pos)})</div>
      {pos_html if pos_html else '<div class="empty">없음</div>'}
    </div>
    <div>
      <div class="subsec-label" style="color:#378add">▼ 하락 요인 ({len(neg)})</div>
      {neg_html if neg_html else '<div class="empty">없음</div>'}
    </div>
  </div>
</section>"""

# ── S2: 캘린더 경보 ───────────────────────────────────────────────

def render_s2(radar):
    alerts = radar.get("calendar_alerts", [])
    if not alerts:
        return '<section id="s2" class="section"><h2 class="sec-title">📅 S2 — 캘린더 경보</h2><div class="empty">D-30 이내 이벤트 없음</div></section>'

    DAY_KO = ["월","화","수","목","금","토","일"]

    def _fmt_date(date_str):
        try:
            from datetime import datetime as _dt
            d = _dt.strptime(date_str, "%Y-%m-%d")
            return f"{d.month:02d}.{d.day:02d}", DAY_KO[d.weekday()]
        except Exception:
            return (date_str[:5] if date_str else "—"), ""

    BADGE_COLOR = {"HIGH": "#e53935", "MID": "#ef9f27", "LOW": "#378add"}

    html = ""
    for a in alerts[:8]:
        u         = a.get("urgency", "LOW")
        sectors   = ", ".join(a.get("sectors", []))
        days      = a.get("days_left", 0)
        note_esc  = a.get("note", "").replace("'", "")
        boost_str = a.get("boost", "")
        ev_name   = a.get("name", "").replace("'", "")
        ev_date   = a.get("date", "")
        badge_col = BADGE_COLOR.get(u, "#378add")
        md, dow   = _fmt_date(ev_date)
        onclick   = f"showInfoPopup('{ev_name}', '{note_esc}', 'D-{days} | {ev_date}', '수혜 섹터: {sectors}', '{boost_str}', '{u} 긴급도')"
        sector_note = f"수혜: {sectors}" + (f" | {a.get('note','')}" if a.get("note") else "")
        html += f"""
        <div class="cal-row" onclick="{onclick}" style="cursor:pointer">
          <div class="cal-date">{md}<br><span style="font-size:11px;font-weight:400;color:#aaa">{dow}</span></div>
          <div class="cal-body">
            <div>{a.get('name','')} <span class="cal-badge" style="background:{badge_col}22;color:{badge_col};border:1px solid {badge_col}55">D-{days}</span></div>
            <div class="cal-sector">{sector_note}</div>
          </div>
        </div>"""

    return f"""
<section id="s2" class="section">
  <style>
    .cal-row{{display:flex;gap:12px;padding:10px 0;border-bottom:1px solid #222;align-items:flex-start}}
    .cal-row:last-child{{border-bottom:none}}
    .cal-row:hover{{background:rgba(255,255,255,0.03)}}
    .cal-date{{min-width:70px;font-size:13px;font-weight:700;color:#90caf9}}
    .cal-body{{flex:1}}
    .cal-badge{{display:inline-block;font-size:10px;padding:2px 8px;border-radius:10px;margin-left:8px}}
    .cal-sector{{font-size:11px;color:#aaa;margin-top:4px}}
  </style>
  <h2 class="sec-title">📅 S2 — 캘린더 경보 ({len(alerts)}건) <span style="font-size:11px;color:#888;font-weight:400">클릭 → 상세</span></h2>
  {html}
</section>"""

# ── S3/S4: 급등예상 TOP10 + 클릭 팝업 상세 ──────────────────────

def score_winrate(score):
    """점수대별 D+1 승률 (백테스트 기반)"""
    try:
        s = float(score)
        if s >= 95: return 0,  "극소수 데이터 — 신뢰 낮음"
        if s >= 90: return 9,  "9% (평균수익 -2.2%)"
        if s >= 85: return 29, "29% ✅ 최고 승률 구간"
        if s >= 80: return 14, "14% (평균수익 -2.9%)"
        if s >= 70: return 17, "17% (평균수익 -1.4%)"
        if s >= 60: return 18, "18% (평균수익 -2.3%)"
        return 10, "10% 미만 — 참고용"
    except Exception:
        return 0, "데이터 없음"

def score_holding(score, ma, rsi):
    """예상 보유 기간 추정"""
    try:
        s = float(score)
        r = float(rsi) if rsi else 50
        if s >= 85 and ma == "3ma_bull" and r < 65:
            return "D+1~3 스윙", "#1D9E75"
        if s >= 70 and ma == "3ma_bull":
            return "D+1 단타", "#EF9F27"
        return "당일 관찰 후 판단", "#888"
    except Exception:
        return "판단 불가", "#888"

def render_score_bar(label, val, max_val, color="#378ADD"):
    try:
        pct = min(100, float(val) / float(max_val) * 100)
    except Exception:
        pct = 0
    return f"""
    <div style="margin-bottom:6px">
      <div style="display:flex;justify-content:space-between;font-size:10px;color:#666;margin-bottom:2px">
        <span>{label}</span><span>{val}pt / {max_val}pt</span>
      </div>
      <div style="height:6px;background:#eee;border-radius:3px">
        <div style="width:{pct:.0f}%;height:100%;background:{color};border-radius:3px"></div>
      </div>
    </div>"""

def build_popup_data(top10, news_map, backtest):
    """종목별 팝업 데이터 JSON 생성"""
    popups = {}
    bands  = backtest.get("score_bands", {})

    for r in top10:
        ticker = r.get("ticker", "")
        score  = r.get("total_score", 0)
        rsi    = r.get("rsi", "")
        ma     = r.get("ma_align", "")

        wr, wr_note  = score_winrate(score)
        holding, h_color = score_holding(score, ma, rsi)

        # 점수 구성 (각 컴포넌트)
        tech_s = r.get("tech_score", 0)
        news_s = r.get("news_score", 0)
        inv_s  = r.get("investor_score", 0)
        theme_s= r.get("theme_score", 0)
        fund_s = r.get("fund_score", 0)
        decay_s= r.get("decay_score", 0)

        # 뉴스
        news_row = news_map.get(ticker, {})
        news_title = news_row.get("title", "") if news_row else ""
        news_link  = news_row.get("link", "#") if news_row else "#"

        # 리스크 판단
        risks = []
        try:
            if float(rsi) > 70: risks.append("RSI 과매수 — 단기 조정 가능")
        except Exception: pass
        if ma == "bearish": risks.append("MA 역배열 — 하락 추세 중")
        if str(r.get("decay_flag","")) not in ("FRESH",""):
            risks.append(f"신호 노후화({r.get('decay_flag','')}) — 진입 타이밍 주의")
        if str(r.get("signal_timeout","")).lower() == "true":
            risks.append("신호 타임아웃 임박")
        if not risks: risks.append("특이 리스크 없음")

        # MA 해석
        ma_map = {
            "3ma_bull":  "✅ 3MA 정배열 — 단기/중기/장기 모두 우상향",
            "2ma_bull":  "⚡ 2MA 부분 정배열 — 추세 전환 초입",
            "bearish":   "⚠️ 역배열 — 하락 추세, 반등 시 진입 고려",
        }
        ma_desc = ma_map.get(ma, ma)

        # vol 해석
        vol_map = {
            "healthy_strong":              "거래량 건강 — 강한 매수세",
            "healthy_strong_accumulation": "거래량 건강 — 매집 패턴",
            "healthy_mid":                 "거래량 보통 — 정상 수준",
            "neutral_high":                "거래량 중립 — 관망 구간",
            "sellout_warn":                "⚠️ 매도 경고 — 거래량 급증",
            "sellout_strong":              "🚨 강한 매도 — 주의 필요",
        }
        vol_desc = vol_map.get(r.get("vol_gap_label",""), r.get("vol_gap_label",""))

        popups[ticker] = {
            "name":      r.get("name", ticker),
            "ticker":    ticker,
            "signal":    r.get("signal",""),
            "score":     score,
            "sector":    r.get("sector_major",""),
            "winrate":   wr,
            "wr_note":   wr_note,
            "holding":   holding,
            "h_color":   h_color,
            "tech_s":    tech_s,
            "news_s":    news_s,
            "inv_s":     inv_s,
            "theme_s":   theme_s,
            "fund_s":    fund_s,
            "decay_s":   decay_s,
            "rsi":       rsi,
            "ma_desc":   ma_desc,
            "vol_desc":  vol_desc,
            "news_title":news_title,
            "news_link": news_link,
            "risks":     risks,
            "poc_score": r.get("poc_score",""),
            "sr_score":  r.get("sr_score",""),
        }
    return popups

def render_s3_s4(top10, news_map, backtest):
    if not top10:
        return '<section id="s3" class="section"><h2 class="sec-title">🚀 S3 — 급등예상 TOP10</h2><div class="empty">신호 없음</div></section>'

    popups = build_popup_data(top10, news_map, backtest)
    popup_json = json.dumps(popups, ensure_ascii=False)

    # 용어 정의 데이터
    GLOSSARY = {
        "점수(pt)": "SFD 종합 점수 (최대 225pt). 기술(93)+뉴스(30)+수급(20)+테마(10)+펀더멘탈(15)+부스트 합산. 높을수록 매수 조건 충족",
        "신호": "RESERVE_BUY(매수후보): 점수 70pt 이상 / WATCH_ONLY(관심): 50pt 이상 / SIGNAL_EXPIRED: 5봉 이상 경과로 신호 만료",
        "D+1 승률": "이 점수대 종목이 다음날(D+1) 플러스 마감한 역사적 비율. 85~90pt 구간이 29%로 최고. 100%는 없으므로 참고용",
        "트리거": "📰뉴스: 뉴스 감성점수 5pt 이상 / 💰수급: 외국인·기관 순매수 10pt 이상 / 📈기술: 3MA 정배열",
        "보유기간": "D+1 단타: 내일 하루 / D+3~5 스윙: 3~5일 보유 전략 / 당일 관찰: 추가 확인 후 판단",
        "RSI": "상대강도지수(0~100). 70 이상: 과매수(단기 조정 주의) / 30 이하: 과매도(반등 기대) / 50 근처: 중립",
        "MA배열": "이동평균선 배열. 정배열(3MA_BULL): 단기>중기>장기로 우상향 → 매수 유리. 역배열: 하락 추세",
        "Decay": "신호 노후화 지표. FRESH: 오늘 발생 / 숫자 클수록 오래된 신호 → 진입 타이밍 주의",
        "전일종가": "전 거래일 마감 기준 주가. 당일 등락률 판단의 기준점",
    }

    rows = ""
    for i, r in enumerate(top10, 1):
        ticker  = r.get("ticker","")
        name    = r.get("name", ticker)
        score   = r.get("total_score","")
        sig     = r.get("signal","")
        sector  = r.get("sector_major","")
        rsi     = r.get("rsi","")
        ma      = r.get("ma_align","")
        news_s  = r.get("news_score", 0)
        inv_s   = r.get("investor_score", 0)
        # 전일종가: prev_close 또는 sfd_technical에서 올 수 있음
        prev_close = r.get("prev_close","") or r.get("close","") or ""
        try:
            prev_close_str = f"{float(prev_close):,.0f}원"
        except Exception:
            prev_close_str = "-"

        wr, _ = score_winrate(score)
        holding, h_color = score_holding(score, ma, rsi)

        trigger = []
        try:
            if float(news_s) >= 5:  trigger.append("📰뉴스")
            if float(inv_s) >= 10:  trigger.append("💰수급")
            if ma == "3ma_bull":    trigger.append("📈기술")
        except Exception: pass
        trigger_str = " ".join(trigger) if trigger else "📈기술"

        news_row   = news_map.get(ticker)
        news_title = (news_row.get("title","")[:30] + "...") if news_row else ""

        wr_color  = "#1D9E75" if wr >= 25 else "#EF9F27" if wr >= 15 else "#888"
        # 순위별 배경 강조
        rank_style = "background:#fff8f0" if i <= 3 else ""

        rows += f"""
        <tr class="stock-row" onclick="showPopup('{ticker}')" style="cursor:pointer;{rank_style}">
          <td style="text-align:center;font-weight:500;color:{'#e24b4a' if i<=3 else '#aaa'};font-size:{'16px' if i<=3 else '13px'}">{i}</td>
          <td>
            <strong style="font-size:{'15px' if i<=3 else '13px'}">{name}</strong><br>
            <span style="font-size:10px;color:#aaa">{ticker}</span>
          </td>
          <td>{signal_badge(sig)}</td>
          <td>
            <span style="font-size:{'20px' if i<=3 else '16px'};font-weight:500;color:#e24b4a">{score}</span>
            <span style="font-size:10px;color:#aaa">pt</span>
          </td>
          <td style="font-size:12px;color:#555;font-weight:500">
            {prev_close_str}
          </td>
          <td style="font-size:11px;color:#666">{sector}</td>
          <td>
            <span style="font-size:11px">{trigger_str}</span><br>
            <span style="font-size:10px;color:{h_color}">{holding}</span>
          </td>
          <td style="font-size:11px;color:#555">{news_title}</td>
          <td>
            <span style="font-size:13px;font-weight:500;color:{wr_color}">{wr}%</span><br>
            <span style="font-size:9px;color:#aaa">D+1 승률</span>
          </td>
          <td>
            <button onclick="event.stopPropagation();showPopup('{ticker}')"
              style="font-size:11px;padding:3px 10px;border-radius:20px;border:0.5px solid #ddd;
                     background:#f8f8f6;cursor:pointer;color:#333">
              상세▶
            </button>
          </td>
        </tr>"""

    # 용어 정의 패널 (접기/펼치기)
    glossary_items = "".join(
        f'<div style="padding:8px 0;border-bottom:0.5px solid #f0f0ee">'
        f'<span style="font-weight:500;font-size:12px;color:#333">{k}</span>'
        f'<div style="font-size:11px;color:#666;margin-top:2px">{v}</div></div>'
        for k, v in GLOSSARY.items()
    )
    glossary_html = f"""
    <div style="margin-top:14px">
      <button onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none'"
        style="font-size:12px;padding:6px 14px;border-radius:20px;border:0.5px solid #ddd;
               background:#f8f8f6;cursor:pointer;color:#555;margin-bottom:8px">
        📖 용어 정의 (펼치기/접기)
      </button>
      <div style="display:none;background:#f8f8f6;border-radius:10px;padding:12px 16px">
        {glossary_items}
      </div>
    </div>"""

    # 팝업 HTML
    popup_html = """
<div id="popup-overlay" onclick="closePopup()"
  style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;
         background:rgba(0,0,0,0.5);z-index:1000;overflow-y:auto;-webkit-overflow-scrolling:touch">
  <div id="popup-box" onclick="event.stopPropagation()"
    style="background:#fff;border-radius:16px;max-width:680px;margin:40px auto 20px;
           padding:28px;position:relative">
    <button onclick="closePopup()"
      style="position:absolute;top:16px;right:16px;background:none;border:none;
             font-size:20px;cursor:pointer;color:#888">✕</button>
    <div id="popup-content"></div>
  </div>
</div>"""

    script = f"""
<script>
const POPUP_DATA = {popup_json};

function showPopup(ticker) {{
  const d = POPUP_DATA[ticker];
  if (!d) return;

  const sigColor = d.signal === 'RESERVE_BUY' ? '#e24b4a' : '#EF9F27';
  const sigLabel = d.signal === 'RESERVE_BUY' ? '⭐ 매수후보' : '👁 관심';

  // 점수 구성 바
  const totalScore = parseFloat(d.score) || 0;
  const bars = [
    ['기술점수 (MA/RSI/볼륨)', d.tech_s, 93, '#378ADD'],
    ['뉴스점수', d.news_s, 30, '#7F77DD'],
    ['수급점수 (외국인/기관)', d.inv_s, 20, '#1D9E75'],
    ['테마점수', d.theme_s, 10, '#EF9F27'],
    ['펀더멘탈점수', d.fund_s, 15, '#639922'],
    ['Decay 패널티', d.decay_s, 0, '#E24B4A'],
  ].map(([label, val, max, color]) => {{
    const pct = max > 0 ? Math.min(100, parseFloat(val||0) / max * 100) : 0;
    const isNeg = parseFloat(val||0) < 0;
    return `<div style="margin-bottom:8px">
      <div style="display:flex;justify-content:space-between;font-size:11px;color:#666;margin-bottom:2px">
        <span>${{label}}</span>
        <span style="font-weight:500;color:${{isNeg?'#e24b4a':'#333'}}">${{val}}pt</span>
      </div>
      <div style="height:7px;background:#eee;border-radius:4px">
        <div style="width:${{pct.toFixed(0)}}%;height:100%;background:${{isNeg?'#e24b4a':color}};border-radius:4px"></div>
      </div>
    </div>`;
  }}).join('');

  // 승률 게이지
  const wrPct = d.winrate;
  const wrColor = wrPct >= 25 ? '#1D9E75' : wrPct >= 15 ? '#EF9F27' : '#888';

  // 리스크 항목
  const riskHtml = d.risks.map(r =>
    `<div style="font-size:12px;padding:4px 0;border-bottom:0.5px solid #f0f0ee;color:#555">⚠️ ${{r}}</div>`
  ).join('');

  // 뉴스
  const newsHtml = d.news_title
    ? `<a href="${{d.news_link}}" target="_blank"
         style="display:block;background:#f0f4ff;padding:8px 12px;border-radius:8px;
                font-size:12px;color:#333;text-decoration:none;margin-top:8px">
         📰 ${{d.news_title}}
       </a>`
    : '<div style="font-size:12px;color:#aaa;margin-top:8px">관련 뉴스 없음</div>';

  document.getElementById('popup-content').innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:16px">
      <div>
        <div style="font-size:22px;font-weight:500">${{d.name}}</div>
        <div style="font-size:12px;color:#888;margin-top:2px">${{d.ticker}} · ${{d.sector}}</div>
        <span style="background:${{sigColor}};color:#fff;padding:2px 10px;border-radius:20px;
                     font-size:11px;font-weight:500;margin-top:6px;display:inline-block">${{sigLabel}}</span>
      </div>
      <div style="text-align:right">
        <div style="font-size:36px;font-weight:500;color:#e24b4a">${{d.score}}<span style="font-size:14px">pt</span></div>
        <div style="font-size:11px;color:#888">최대 225pt 기준</div>
      </div>
    </div>

    <div style="background:#f8f8f6;border-radius:10px;padding:14px;margin-bottom:14px">
      <div style="font-size:11px;font-weight:500;color:#888;margin-bottom:10px;text-transform:uppercase;letter-spacing:.06em">점수 구성 — 왜 이 점수인가</div>
      ${{bars}}
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px">
      <div style="background:#f8f8f6;border-radius:10px;padding:12px">
        <div style="font-size:11px;color:#888;margin-bottom:6px">D+1 승률 (백테스트)</div>
        <div style="font-size:28px;font-weight:500;color:${{wrColor}}">${{wrPct}}%</div>
        <div style="font-size:10px;color:#888;margin-top:2px">${{d.wr_note}}</div>
        <div style="height:6px;background:#eee;border-radius:3px;margin-top:6px">
          <div style="width:${{wrPct}}%;height:100%;background:${{wrColor}};border-radius:3px"></div>
        </div>
      </div>
      <div style="background:#f8f8f6;border-radius:10px;padding:12px">
        <div style="font-size:11px;color:#888;margin-bottom:6px">예상 보유 기간</div>
        <div style="font-size:16px;font-weight:500;color:${{d.h_color}};margin-top:4px">${{d.holding}}</div>
        <div style="margin-top:10px;font-size:11px;color:#666">RSI: ${{d.rsi}} | ${{d.ma_desc.split('—')[0].trim()}}</div>
      </div>
    </div>

    <div style="background:#f8f8f6;border-radius:10px;padding:12px;margin-bottom:14px">
      <div style="font-size:11px;color:#888;margin-bottom:6px">기술적 분석</div>
      <div style="font-size:12px;color:#333;margin-bottom:4px">${{d.ma_desc}}</div>
      <div style="font-size:12px;color:#555">${{d.vol_desc}}</div>
    </div>

    ${{newsHtml}}

    <div style="margin-top:14px">
      <div style="font-size:11px;color:#888;margin-bottom:6px">리스크 요인</div>
      ${{riskHtml}}
    </div>

    <div style="margin-top:16px;background:#EEEDFE;padding:10px 14px;border-radius:8px;font-size:11px;color:#534AB7">
      ℹ️ 본 점수는 기술/뉴스/수급/테마/펀더멘탈 복합 지표입니다.
      D+1 승률은 과거 백테스트 기준이며 미래 수익을 보장하지 않습니다.
    </div>
  `;

  document.getElementById('popup-overlay').style.display = 'block';
  document.body.style.overflow = 'hidden';
}}

function closePopup() {{
  document.getElementById('popup-overlay').style.display = 'none';
  document.body.style.overflow = '';
}}

document.addEventListener('keydown', function(e) {{
  if (e.key === 'Escape') closePopup();
}});
</script>"""

    return f"""
{popup_html}
<section id="s3" class="section">
  <h2 class="sec-title">🚀 S3 — 급등예상 TOP20 <span style="font-size:11px;color:#888;font-weight:400">종목 클릭 → 상세 | 헤더 ❓ 클릭 → 용어 설명</span></h2>
  <div style="overflow-x:auto">
  <table class="data-table" style="min-width:780px">
    <thead>
      <tr>
        <th style="width:32px">#</th>
        <th>종목</th>
        <th onclick="showInfoPopup('신호 등급 설명','RESERVE_BUY ⭐매수후보: 종합점수 70pt 이상, 즉시 관심 필요\\nWATCH_ONLY 👁관심: 50pt 이상, 모니터링 대상\\nSIGNAL_EXPIRED ⚠: 신호 발생 후 5봉 이상 경과로 타이밍 만료 — 신규 진입 비권고','','','📌 신호 용어')" style="cursor:pointer;color:#378ADD">신호 ❓</th>
        <th onclick="showInfoPopup('점수(pt) 구성 설명','SFD 종합 점수 최대 225pt\\n\\n기술점수 최대 93pt: MA배열/RSI/거래량 패턴\\n뉴스점수 최대 30pt: 관련 뉴스 감성 분석\\n수급점수 최대 20pt: 외국인·기관 순매수\\n테마점수 10pt: 섹터 테마 해당 여부\\n펀더멘탈 15pt: 재무 건전성\\n글로벌부스트 ±20pt: 미국 연동 종목\\n\\n70pt 이상이 매수후보, 85~90pt 구간이 역사적 최고 승률(29%)','','','📌 점수 용어')" style="cursor:pointer;color:#378ADD">점수 ❓</th>
        <th onclick="showInfoPopup('전일 종가 의미','전 거래일 장 마감 기준 주가(원)\\n오늘 시장 시작 시 이 가격 대비 등락률로 판단\\n거래 전 호가 확인 권장','','','📌 전일종가')" style="cursor:pointer;color:#378ADD">전일종가 ❓</th>
        <th>섹터</th>
        <th onclick="showInfoPopup('트리거 & 보유기간 설명','트리거 유형:\\n📰뉴스: 관련 뉴스 감성점수 5pt 이상\\n💰수급: 외국인·기관 순매수 10pt 이상\\n📈기술: 3MA 정배열(단기>중기>장기 우상향)\\n\\n예상 보유기간:\\nD+1 단타: 내일 하루 목표\\nD+3~5 스윙: 3~5일 보유 전략\\n당일 관찰: 추가 확인 후 판단','','','📌 트리거/기간 용어')" style="cursor:pointer;color:#378ADD">트리거/기간 ❓</th>
        <th>뉴스</th>
        <th onclick="showInfoPopup('D+1 승률 해설','백테스트 기간: 2026.05~06 (7거래일, 1,409건)\\n\\n점수별 D+1 익일 양봉 확률:\\n85-90pt: 29% ✅ 최고 구간\\n70-80pt: 17%\\n60-70pt: 18%\\n90-95pt: 9% (역설적으로 낮음)\\n\\n⚠️ 승률 50% 미만이 정상입니다\\n주식시장 특성상 100% 예측은 불가능\\n이 지표는 선택의 참고 기준입니다','','','📌 D+1승률 용어')" style="cursor:pointer;color:#378ADD">D+1승률 ❓</th>
        <th></th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
  </div>
  {glossary_html}
</section>
<section id="s4" class="section" style="display:none"></section>
{script}"""

# ── S5: 미래산업 모멘텀 게이지 ───────────────────────────────────

def render_s5(calendar):
    sectors  = calendar.get("future_industry_monitor", {}).get("sectors", [])
    last_upd = calendar.get("future_industry_monitor", {}).get("last_updated", "")

    phase_color = {
        "초초기":    "#B5D4F4",
        "초기":      "#378ADD",
        "초기→성장": "#1D9E75",
        "성장":      "#639922",
        "피크":      "#EF9F27",
        "식는 중":   "#E24B4A",
    }
    phase_pct = {
        "초초기": 10, "초기": 25, "초기→성장": 40,
        "성장": 60, "피크": 80, "식는 중": 90,
    }
    PHASE_DESC = {
        "초초기":    "아직 주류 투자자 관심 없음 — 선점 기회. 단 변동성 극심, 소액 분산 필수",
        "초기":      "글로벌 리서치 언급 시작 — 얼리 어답터 진입 구간. 효성중공업 1만원대 시절",
        "초기→성장": "기관 자금 유입 시작 — 주도주 윤곽 형성 중. 지금이 황금 구간",
        "성장":      "본격 상승 추세 — 주도 종목 선별 중요. 고점 매수 리스크 증가",
        "피크":      "과열 경고 — 선점자 차익 실현 구간. 신규 진입 리스크 높음",
        "식는 중":   "모멘텀 소진 — 다음 사이클 준비 시작. 익절 후 관망 권고",
    }

    # horizon 기준으로 정렬 (짧은 기간 → 긴 기간)
    def horizon_sort_key(s):
        h = s.get("horizon", "99년")
        try:
            return int(h.split("~")[0].replace("년","").strip())
        except Exception:
            return 99

    sorted_sectors = sorted(sectors, key=horizon_sort_key)

    rows = ""
    for s in sorted_sectors:
        phase    = s.get("phase", "초기")
        color    = phase_color.get(phase, "#888")
        pct      = phase_pct.get(phase, 30)
        horizon  = s.get('horizon','')
        name     = s.get('name','')
        tickers_str = " / ".join(s.get("key_tickers", [])[:3])
        phase_desc  = PHASE_DESC.get(phase, "")
        signal      = s.get('global_signal','').replace("'","")
        name_esc    = name.replace("'","")
        onclick = f"showInfoPopup('{horizon} : {name_esc}', '{phase_desc}', '{phase} 단계', '핵심 종목: {tickers_str}', '글로벌 신호: {signal}', '미래산업 모멘텀')"

        rows += f"""
        <div class="momentum-row" onclick="{onclick}" style="cursor:pointer;padding:8px;border-radius:8px;transition:background 0.15s" onmouseover="this.style.background='#f8f8f6'" onmouseout="this.style.background=''">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px">
            <div>
              <span style="font-size:12px;font-weight:500;color:{color};background:{color}18;padding:2px 8px;border-radius:20px;margin-right:8px">{horizon}</span>
              <span style="font-weight:500;font-size:13px">{name}</span>
            </div>
            <span style="font-size:11px;color:{color};font-weight:500;white-space:nowrap">{phase} ▶</span>
          </div>
          <div class="progress-bar">
            <div class="progress-fill" style="width:{pct}%;background:{color}"></div>
          </div>
          <div style="font-size:10px;color:#888;margin-top:3px">
            핵심 종목: {tickers_str} | {signal}
          </div>
        </div>"""

    return f"""
<section id="s5" class="section">
  <h2 class="sec-title">🔭 S5 — 미래산업 모멘텀 <span style="font-size:11px;color:#888;font-weight:400">기간 → 산업 순 | 클릭 → 단계 해설</span></h2>
  <div style="font-size:11px;color:#888;margin-bottom:12px">업데이트: {last_upd} | 다음: 분기 1회</div>
  {rows if rows else '<div class="empty">데이터 없음</div>'}
  <div class="phase-legend" style="flex-wrap:wrap">
    <span style="color:#378ADD">■ 초기(얼리)</span>
    <span style="color:#1D9E75">■ 초기→성장(황금)</span>
    <span style="color:#639922">■ 성장(주류)</span>
    <span style="color:#EF9F27">■ 피크(과열)</span>
    <span style="color:#E24B4A">■ 식는 중(익절)</span>
  </div>
</section>"""

# ── S6: 벤치마킹 + 자가진단 + 적중률 모니터링 ────────────────────

def render_s6(backtest, expired, recent_trades=None):
    tiers   = backtest.get("tiers", {})
    reserve = tiers.get("RESERVE_BUY", {})
    watch   = tiers.get("WATCH_ONLY", {})
    bands   = backtest.get("score_bands", {})
    meta    = backtest.get("meta", {})

    # 최고 승률 구간
    best_band = max(bands.items(), key=lambda x: x[1].get("win_rate", 0)) if bands else ("--", {})

    expired_html = ""
    for e in expired[:5]:
        name_e   = e.get("name","")
        ticker_e = e.get("ticker","")
        bars_e   = e.get("signal_bars_elapsed", "?")
        score_e  = e.get("total_score","")
        onclick_e = f"showInfoPopup('⚠️ {name_e}({ticker_e}) 신호 만료', 'SIGNAL_EXPIRED는 신호 발생 후 5봉(거래일) 이상 경과한 종목입니다. 주가가 충분히 반응하지 않은 것으로 보유 중이라면 포지션 정리를 검토하세요.', '{bars_e}봉 경과 | 점수: {score_e}pt', '권고: 신규 진입 금지', '보유 중이면 손절 기준 재확인', '신호 만료 경고')"
        expired_html += f'<div class="expired-row" onclick="{onclick_e}" style="cursor:pointer">⚠️ <strong>{name_e}({ticker_e})</strong> — {bars_e}봉 경과 | 클릭 → 처리 방법</div>'

    # 점수 구간별 승률 테이블
    band_rows = ""
    for band, bdata in sorted(bands.items(), key=lambda x: x[0], reverse=True):
        wr  = bdata.get("win_rate", 0)
        cnt = bdata.get("count", 0)
        avg = bdata.get("avg_return_d1", 0)
        bar_w = min(100, wr * 2)
        color = "#1D9E75" if wr >= 25 else "#EF9F27" if wr >= 15 else "#888"
        band_rows += f"""
        <tr>
          <td style="font-weight:500;font-size:12px">{band}pt</td>
          <td style="font-size:12px;text-align:center">{cnt}건</td>
          <td>
            <div style="display:flex;align-items:center;gap:6px">
              <div style="flex:1;height:6px;background:#eee;border-radius:3px">
                <div style="width:{bar_w}%;height:100%;background:{color};border-radius:3px"></div>
              </div>
              <span style="font-size:12px;font-weight:500;color:{color};min-width:32px">{wr}%</span>
            </div>
          </td>
          <td style="font-size:12px;text-align:right;color:{'#e24b4a' if float(avg or 0)>=0 else '#378add'}">{avg}%</td>
        </tr>"""

    # 최근 RESERVE_BUY 거래 근거 테이블 HTML 생성
    recent_table_html = ""
    if recent_trades:
        _rows_html = ""
        for r in recent_trades:
            _date    = r.get("date", "")
            _ticker  = r.get("ticker", "")
            _ret_raw = r.get("return_d1", "")
            _win_raw = r.get("win_flag", "")
            try:
                _ret_f   = float(_ret_raw)
                _ret_str = f"{_ret_f:+.2f}%"
                _ret_col = "#1D9E75" if _ret_f >= 0 else "#e24b4a"
            except Exception:
                _ret_str, _ret_col = "-", "#888"
            try:
                _entry_str = f"{float(r.get('close_entry', '')):,.0f}"
            except Exception:
                _entry_str = "-"
            try:
                _exit_str = f"{float(r.get('close_exit', '')):,.0f}"
            except Exception:
                _exit_str = "-"
            try:
                _score_str = f"{float(r.get('total_score', '')):,.1f}pt"
            except Exception:
                _score_str = r.get("total_score", "-") or "-"
            _win_badge = "✅ 승" if str(_win_raw) in ("1", "True", "true") else "❌ 패"
            _rows_html += f"""
        <tr style="border-bottom:1px solid #f0f0f0">
          <td style="padding:5px 8px;font-size:11px;color:#666">{_date}</td>
          <td style="padding:5px 8px;font-size:12px;font-weight:500">{_ticker}</td>
          <td style="padding:5px 8px;font-size:12px;text-align:right">{_score_str}</td>
          <td style="padding:5px 8px;font-size:12px;text-align:right">{_entry_str}</td>
          <td style="padding:5px 8px;font-size:12px;text-align:right">{_exit_str}</td>
          <td style="padding:5px 8px;font-size:12px;text-align:right;font-weight:600;color:{_ret_col}">{_ret_str}</td>
          <td style="padding:5px 8px;font-size:12px;text-align:center">{_win_badge}</td>
        </tr>"""
        recent_table_html = f"""
  <div style="margin-top:18px">
    <div class="subsec-label">📋 최근 RESERVE_BUY 거래 근거 (D+1 실적) — 수익률 상위 10건</div>
    <div style="overflow-x:auto;margin-top:6px">
    <table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead>
        <tr style="background:#f8f8f6;border-bottom:2px solid #ddd">
          <th style="padding:6px 8px;text-align:left;font-weight:500">날짜</th>
          <th style="padding:6px 8px;text-align:left;font-weight:500">종목코드</th>
          <th style="padding:6px 8px;text-align:right;font-weight:500">점수</th>
          <th style="padding:6px 8px;text-align:right;font-weight:500">진입가</th>
          <th style="padding:6px 8px;text-align:right;font-weight:500">익일종가</th>
          <th style="padding:6px 8px;text-align:right;font-weight:500">D+1수익률</th>
          <th style="padding:6px 8px;text-align:center;font-weight:500">결과</th>
        </tr>
      </thead>
      <tbody>{_rows_html}
      </tbody>
    </table>
    </div>
  </div>"""

    # 적중률 모니터링 설명
    date_range = f"{meta.get('date_range_start','')} ~ {meta.get('date_range_end','')}"
    total_dates = meta.get('total_dates', '--')
    total_records = meta.get('total_records', '--')

    return f"""
<section id="s6" class="section">
  <h2 class="sec-title">📊 S6 — 적중률 모니터링 & 자가진단</h2>

  <!-- 핵심 지표 -->
  <div class="two-col" style="margin-bottom:14px">
    <div class="stat-box">
      <div class="stat-label">⭐ RESERVE_BUY D+1 승률</div>
      <div class="stat-val" style="color:#e24b4a">{reserve.get('win_rate','--')}%</div>
      <div class="stat-sub">평균수익 {reserve.get('avg_return_d1','--')}% | {reserve.get('count','--')}건 분석</div>
      <div style="height:6px;background:#eee;border-radius:3px;margin-top:8px">
        <div style="width:{min(100, float(reserve.get('win_rate') or 0)*2):.0f}%;height:100%;background:#e24b4a;border-radius:3px"></div>
      </div>
    </div>
    <div class="stat-box">
      <div class="stat-label">👁 WATCH_ONLY D+1 승률</div>
      <div class="stat-val" style="color:#EF9F27">{watch.get('win_rate','--')}%</div>
      <div class="stat-sub">평균수익 {watch.get('avg_return_d1','--')}% | {watch.get('count','--')}건 분석</div>
      <div style="height:6px;background:#eee;border-radius:3px;margin-top:8px">
        <div style="width:{min(100, float(watch.get('win_rate') or 0)*2):.0f}%;height:100%;background:#EF9F27;border-radius:3px"></div>
      </div>
    </div>
  </div>

  <div class="best-band">
    ✅ 최고 승률 구간: <strong>{best_band[0]}pt</strong> —
    승률 {best_band[1].get('win_rate','--')}% |
    {best_band[1].get('count','--')}건 |
    평균 D+1 수익 {best_band[1].get('avg_return_d1','--')}%
  </div>

  <!-- 점수 구간별 상세 승률 -->
  <div style="margin-top:16px">
    <div class="subsec-label">점수 구간별 D+1 적중률 상세 (백테스트 {date_range} | {total_dates}거래일 | {total_records}건)</div>
    <div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
      <thead>
        <tr style="background:#f8f8f6">
          <th style="padding:6px 10px;text-align:left;font-weight:500">점수 구간</th>
          <th style="padding:6px 10px;text-align:center;font-weight:500">샘플수</th>
          <th style="padding:6px 10px;font-weight:500">D+1 승률</th>
          <th style="padding:6px 10px;text-align:right;font-weight:500">평균 수익</th>
        </tr>
      </thead>
      <tbody>{band_rows}</tbody>
    </table>
    </div>
    <div style="font-size:10px;color:#888;margin-top:6px">
      ℹ️ 승률 = D+1 종가 > 진입 종가인 비율 | 평균수익 마이너스는 손절 포함 전체 평균
    </div>
  </div>

  <!-- SIGNAL_EXPIRED -->
  {f'<div class="subsec-label" style="margin-top:14px;color:#A32D2D">⚠️ SIGNAL_EXPIRED 경고 ({len(expired)}건) — 포지션 정리 검토</div>' if expired else ''}
  {expired_html}

  <!-- 누적 적중률 추적 안내 -->
  <div style="margin-top:16px;background:#E1F5EE;border-radius:10px;padding:14px;cursor:pointer"
       onclick="showInfoPopup('📈 누적 적중률 트래킹 시스템', '매일 15:35 레포트에서 전일 TOP20 종목의 D+1 실제 수익률을 자동 집계합니다. 이 데이터가 쌓이면 BM(벤치마크 모듈) 가중치를 자동 조정하여 점수 예측 정확도가 점진적으로 향상됩니다.', '운영 목표: RESERVE_BUY 승률 30%↑ / 평균 D+1 수익 +1%↑', '현재: 백테스트 {total_records}건 분석 완료', '실전 데이터 누적 진행 중 → 6/29 Run #93 이후 본격 집계', '적중률 트래킹 설명')">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <div style="font-size:12px;font-weight:500;color:#0F6E56">📈 누적 적중률 트래킹 — 운영 방침</div>
      <span style="font-size:11px;color:#0F6E56">클릭 → 상세 ▶</span>
    </div>
    <div style="font-size:11px;color:#0F6E56;line-height:1.8;margin-top:6px">
      • 매일 15:35 레포트에서 전일 TOP20의 D+1 실제 수익률 자동 집계<br>
      • 주간 단위 승률 추이 → 점수 임계값 자동 조정 (BM 가중치 피드백)<br>
      • 목표: RESERVE_BUY 승률 30% 이상 / 평균 D+1 수익 +1% 이상<br>
      • 현재: <strong>백테스트 데이터 {total_records}건 분석 완료</strong> | 실전 누적 집계 진행 중
    </div>
  </div>

  <!-- AI 자가진단 -->
  <div class="self-diag" style="margin-top:12px;cursor:pointer"
       onclick="showInfoPopup('🤖 SFD AI 자가진단 메모', 'SFD(Smart Finance Dynamic)는 매 세션마다 미구현 항목과 개선 방향을 스스로 기록합니다. 이 메모는 다음 AI(Claude)가 세션을 이어받을 때 가장 먼저 읽는 인수인계 자료입니다.', '미구현 1순위: Reuters/AP RSS 직접 수집', '미구현 2순위: DART 공시 유형→영향 강도 매핑', '미구현 3순위: 차트프로 패턴 S3/S4 반영', 'AI 자가진단 시스템')">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <div class="subsec-label" style="margin-bottom:0">🤖 AI 자가진단 메모 (클릭 → 상세)</div>
      <span style="font-size:11px;color:#534AB7">▶</span>
    </div>
    <div class="diag-item" style="margin-top:8px">• 완료: 글로벌 레이더(S0) + 7섹션 레포트 + 클릭 팝업 + TOP20 + 적중률 모니터링</div>
    <div class="diag-item">• 미구현 1순위: Reuters/AP RSS 직접 수집</div>
    <div class="diag-item">• 미구현 2순위: DART 공시 유형→영향 강도 매핑</div>
    <div class="diag-item">• 미구현 3순위: 차트프로 패턴 S3 반영 / 전일종가 연동</div>
    <div class="diag-item">• 스케줄: 08:10 / 09:05 / 15:35 하루 3회 | 6/29 Run #93 후 TOP20 정상화</div>
  </div>
  {recent_table_html}
</section>"""

# ── HTML 조합 ────────────────────────────────────────────────────

def build_html(data, trade_date):
    d   = data
    radar = d["radar"]

    s0 = render_s0(radar)
    s1 = render_s1(radar)
    s2 = render_s2(radar)
    s3_s4 = render_s3_s4(d["top10"], d["news_map"], d["backtest"])
    s5 = render_s5(d["calendar"])
    s6 = render_s6(d["backtest"], d["expired"], d.get("recent_trades", []))

    now_str    = datetime.now().strftime("%Y-%m-%d %H:%M")
    import json as _json

    # 배너/대시보드용 JSON
    radar_slim = {
        "market": {
            "indices":    radar.get("market",{}).get("indices",{}),
            "fx_rates":   radar.get("market",{}).get("fx_rates",{}),
            "commodities":radar.get("market",{}).get("commodities",{}),
        }
    }
    radar_json = _json.dumps(radar_slim, ensure_ascii=False)

    # 업종상위: 뉴스 트리거에서 상위 3개
    triggers = radar.get("sector_triggers", [])
    sector_top_html = ""
    for i, t in enumerate(triggers[:5], 1):
        boost = t.get("boost", 0)
        color = "#e24b4a" if boost > 0 else "#378ADD"
        sign  = "+" if boost > 0 else ""
        sector_top_html += f"""
        <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:0.5px solid #f0f0ee;cursor:pointer"
             onclick="showInfoPopup('{t.get('sector','')}','{t.get('headline','').replace("'","")}','{t.get('source','')}','{sign}{boost}pt boost','키워드: {t.get('keyword','')}','업종 트리거')">
          <span style="font-size:12px;font-weight:500">{t.get('sector','')}</span>
          <span style="font-size:12px;color:{color};font-weight:500">{sign}{boost}pt</span>
        </div>"""
    if not sector_top_html:
        sector_top_html = '<div style="font-size:12px;color:#888;padding:8px 0">트리거 없음</div>'

    # TOP5 미리보기
    top5_preview_html = ""
    for i, r in enumerate(d["top10"][:5], 1):
        score = r.get("total_score","")
        name  = r.get("name", r.get("ticker",""))
        sig   = r.get("signal","")
        color = "#e24b4a" if sig == "RESERVE_BUY" else "#EF9F27"
        top5_preview_html += f"""
        <div style="display:flex;justify-content:space-between;align-items:center;padding:4px 0;border-bottom:0.5px solid #f0f0ee">
          <span style="font-size:11px;color:#888;margin-right:4px">{i}</span>
          <span style="font-size:12px;font-weight:500;flex:1">{name}</span>
          <span style="font-size:12px;font-weight:500;color:{color}">{score}pt</span>
        </div>"""
    if not top5_preview_html:
        top5_preview_html = '<div style="font-size:12px;color:#888;padding:8px 0">6/29 이후 정상화</div>'

    # 캘린더 미리보기
    cal_alerts = radar.get("calendar_alerts", [])
    calendar_preview_html = ""
    for a in cal_alerts[:4]:
        u = a.get("urgency","LOW")
        color = "#e24b4a" if u=="HIGH" else "#EF9F27" if u=="MID" else "#378ADD"
        days  = a.get("days_left",0)
        calendar_preview_html += f"""
        <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:0.5px solid #f0f0ee">
          <span style="font-size:11px;color:{color};font-weight:500">D-{days}</span>
          <span style="font-size:11px;flex:1;margin-left:6px">{a.get('name','')}</span>
        </div>"""
    if not calendar_preview_html:
        calendar_preview_html = '<div style="font-size:12px;color:#888;padding:8px 0">이벤트 없음</div>'

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SFD 일일 레포트 {trade_date}</title>
<style>
  :root {{
    --bg: #f8f8f6;
    --card: #ffffff;
    --border: rgba(0,0,0,0.08);
    --text-primary: #1a1a1a;
    --text-secondary: #666;
    --accent: #e24b4a;
    --blue: #378ADD;
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{
    font-family: 'Noto Sans KR', -apple-system, sans-serif;
    background: var(--bg); color: var(--text-primary);
    font-size: 14px; line-height: 1.6;
  }}
  .header {{
    background: #1a1a2e; color: #fff;
    padding: 16px 24px;
    display: flex; justify-content: space-between; align-items: center;
    position: sticky; top: 0; z-index: 100;
  }}
  .header-title {{ font-size: 18px; font-weight: 500; }}
  .header-sub {{ font-size: 11px; color: #aaa; margin-top: 2px; }}
  .nav {{ display:flex; gap:8px; }}
  .nav a {{
    color: #ccc; text-decoration:none; font-size:11px;
    padding: 4px 10px; border-radius:20px;
    border: 0.5px solid rgba(255,255,255,0.2);
  }}
  .nav a:hover {{ background:rgba(255,255,255,0.1); color:#fff; }}
  .container {{ max-width: 1100px; margin: 0 auto; padding: 20px 16px; }}
  .section {{
    background: var(--card);
    border: 0.5px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
  }}
  .sec-title {{
    font-size: 16px; font-weight: 500;
    margin-bottom: 14px;
    padding-bottom: 10px;
    border-bottom: 0.5px solid var(--border);
  }}
  .subsec-label {{
    font-size: 10px; font-weight: 500; letter-spacing:.08em;
    text-transform: uppercase; color: var(--text-secondary);
    margin-bottom: 6px;
  }}
  .market-grid {{
    display: flex; flex-wrap: wrap; gap: 8px;
  }}
  .mcard {{
    background: #f8f8f6; border-radius: 8px;
    padding: 10px 14px; min-width: 120px; flex: 1;
  }}
  .mlabel {{ font-size: 10px; color: var(--text-secondary); }}
  .mprice {{ font-size: 15px; font-weight: 500; margin: 2px 0; }}
  .mchg {{ font-size: 12px; font-weight: 500; }}
  .vix-bar {{
    margin-top: 10px; padding: 8px 12px;
    background: #f0f0ee; border-radius: 8px;
    font-size: 12px; font-weight: 500;
  }}
  .hl-box {{
    background: #f8f8f6; border-radius: 8px;
    padding: 10px 14px;
  }}
  .hl-item {{
    font-size: 12px; padding: 5px 0;
    border-bottom: 0.5px solid var(--border);
  }}
  .hl-item:last-child {{ border-bottom: none; }}
  .hl-src {{
    font-size: 10px; color: #888;
    background: #e8e8e6; padding: 1px 6px;
    border-radius: 20px; margin-right: 6px;
  }}
  .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
  .trig-card {{
    background: #f8f8f6; border-radius: 8px;
    padding: 10px 12px; margin-bottom: 6px;
  }}
  .trig-sector {{ font-size: 13px; font-weight: 500; }}
  .trig-headline {{ font-size: 11px; color: #555; margin: 4px 0 2px; }}
  .trig-src {{ font-size: 10px; color: #888; }}
  .data-table {{
    width: 100%; border-collapse: collapse; font-size: 13px;
  }}
  .data-table th {{
    background: #f0f0ee; padding: 8px 10px;
    text-align: left; font-weight: 500; font-size: 11px;
    border-bottom: 0.5px solid var(--border);
  }}
  .data-table td {{
    padding: 8px 10px;
    border-bottom: 0.5px solid var(--border);
  }}
  .data-table tr:hover td {{ background: #f8f8f6; }}
  .detail-card {{
    border: 0.5px solid var(--border); border-radius: 10px;
    padding: 14px; margin-bottom: 10px;
  }}
  .detail-header {{
    display: flex; justify-content: space-between; align-items: flex-start;
    margin-bottom: 10px; padding-bottom: 10px;
    border-bottom: 0.5px solid var(--border);
  }}
  .detail-news {{
    font-size: 12px; color: #555; background: #f0f4ff;
    padding: 6px 10px; border-radius: 6px; margin-bottom: 10px;
  }}
  .score-grid {{
    display: grid; grid-template-columns: repeat(6, 1fr); gap: 6px;
    margin-bottom: 10px;
  }}
  .sc-item {{
    background: #f8f8f6; border-radius: 6px;
    padding: 6px 8px; text-align: center;
  }}
  .sc-label {{ font-size: 9px; color: #888; }}
  .sc-val {{ font-size: 13px; font-weight: 500; }}
  .detail-risk {{
    font-size: 11px; color: #A32D2D;
    background: #FCEBEB; padding: 5px 10px; border-radius: 6px;
  }}
  .momentum-row {{ margin-bottom: 14px; }}
  .progress-bar {{
    height: 8px; background: #e8e8e6;
    border-radius: 4px; overflow: hidden;
  }}
  .progress-fill {{ height: 100%; border-radius: 4px; transition: width 0.3s; }}
  .phase-legend {{
    display: flex; gap: 12px; font-size: 11px;
    margin-top: 12px; color: var(--text-secondary);
  }}
  .stat-box {{
    background: #f8f8f6; border-radius: 8px; padding: 12px 16px;
  }}
  .stat-label {{ font-size: 11px; color: var(--text-secondary); }}
  .stat-val {{ font-size: 24px; font-weight: 500; margin: 4px 0; }}
  .stat-sub {{ font-size: 11px; color: #888; }}
  .best-band {{
    margin-top: 10px; background: #EAF3DE;
    padding: 8px 12px; border-radius: 8px; font-size: 12px;
    color: #3B6D11;
  }}
  .expired-row {{
    font-size: 12px; background: #FCEBEB; color: #A32D2D;
    padding: 6px 10px; border-radius: 6px; margin-bottom: 4px;
  }}
  .self-diag {{
    margin-top: 14px; background: #EEEDFE;
    padding: 12px 14px; border-radius: 8px;
  }}
  .diag-item {{ font-size: 12px; color: #534AB7; margin-top: 4px; }}
  .empty {{ font-size: 12px; color: #888; padding: 10px 0; }}
  .footer {{
    text-align: center; font-size: 11px; color: #888;
    padding: 20px; margin-top: 10px;
  }}
  @media (max-width: 700px) {{
    .two-col {{ grid-template-columns: 1fr; }}
    .score-grid {{ grid-template-columns: repeat(3, 1fr); }}
    .nav {{ display: none; }}
    .market-grid {{ grid-template-columns: repeat(2, 1fr); }}
    .mcard {{ min-width: unset; }}
    .data-table {{ font-size: 12px; }}
    .data-table th, .data-table td {{ padding: 6px 6px; }}
    .header {{ padding: 12px 14px; }}
    .header-title {{ font-size: 15px; }}
    .container {{ padding: 12px 10px; }}
    .section {{ padding: 14px 12px; }}
    .sec-title {{ font-size: 14px; }}
    #popup-box {{ margin: 10px; border-radius: 12px; padding: 18px; }}
    #dashboard-grid {{ grid-template-columns: 1fr !important; }}
    #dashboard-grid + div {{ grid-template-columns: 1fr !important; }}
    .mobile-nav {{
      display: flex !important;
      position: fixed; bottom: 0; left: 0; right: 0;
      background: #1a1a2e; padding: 8px 0;
      justify-content: space-around; z-index: 200;
    }}
    .mobile-nav a {{
      color: #aaa; font-size: 10px; text-decoration: none;
      display: flex; flex-direction: column; align-items: center; gap: 2px;
    }}
    .mobile-nav a span {{ font-size: 18px; }}
    body {{ padding-bottom: 60px; }}
  }}
  @media (min-width: 701px) {{
    .mobile-nav {{ display: none !important; }}
  }}
</style>
</head>
<body>

<!-- 공용 정보 팝업 (S0/S1/S2/S5용) -->
<div id="info-popup-overlay" onclick="closeInfoPopup()"
  style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;
         background:rgba(0,0,0,0.5);z-index:999;overflow-y:auto;-webkit-overflow-scrolling:touch">
  <div id="info-popup-box" onclick="event.stopPropagation()"
    style="background:#fff;border-radius:16px;max-width:520px;margin:60px auto 20px;
           padding:24px;position:relative">
    <button onclick="closeInfoPopup()"
      style="position:absolute;top:14px;right:14px;background:none;border:none;
             font-size:22px;cursor:pointer;color:#888;line-height:1">✕</button>
    <div id="info-popup-content"></div>
  </div>
</div>

<script>
function showInfoPopup(title, desc, tag, val1, val2, category) {{
  const tagColor = category === '미래산업 모멘텀' ? '#534AB7' :
                   category === '글로벌 선행' ? '#185FA5' :
                   category.includes('트리거') ? '#e24b4a' :
                   category.includes('긴급') ? '#A32D2D' : '#3B6D11';
  document.getElementById('info-popup-content').innerHTML = `
    <div style="margin-bottom:16px">
      <div style="font-size:11px;color:#888;background:#f0f0ee;padding:2px 8px;
                  border-radius:20px;display:inline-block;margin-bottom:8px">${{category}}</div>
      <div style="font-size:20px;font-weight:500;margin-bottom:6px">${{title}}</div>
      ${{tag ? `<div style="font-size:12px;color:${{tagColor}};font-weight:500;margin-bottom:8px">${{tag}}</div>` : ''}}
    </div>
    ${{desc ? `<div style="background:#f8f8f6;border-radius:10px;padding:14px;margin-bottom:14px;font-size:13px;color:#333;line-height:1.7">${{desc}}</div>` : ''}}
    <div style="display:flex;flex-direction:column;gap:6px">
      ${{val1 ? `<div style="display:flex;justify-content:space-between;padding:8px 12px;background:#f0f0ee;border-radius:8px;font-size:12px"><span style="color:#666">${{val1.split(':')[0]}}</span><span style="font-weight:500">${{val1.split(':').slice(1).join(':') || val1}}</span></div>` : ''}}
      ${{val2 ? `<div style="display:flex;justify-content:space-between;padding:8px 12px;background:#f0f0ee;border-radius:8px;font-size:12px"><span style="color:#666">${{val2.split(':')[0]}}</span><span style="font-weight:500">${{val2.split(':').slice(1).join(':') || val2}}</span></div>` : ''}}
    </div>
  `;
  document.getElementById('info-popup-overlay').style.display = 'block';
  document.body.style.overflow = 'hidden';
}}
function closeInfoPopup() {{
  document.getElementById('info-popup-overlay').style.display = 'none';
  document.body.style.overflow = '';
}}
document.addEventListener('keydown', function(e) {{
  if (e.key === 'Escape') {{ closePopup(); closeInfoPopup(); }}
}});

// 상단 배너 데이터 채우기
(function() {{
  const rd = {radar_json};
  const m  = rd.market || {{}};
  const idx = m.indices || {{}};
  const fx  = m.fx_rates || {{}};
  const com = m.commodities || {{}};
  function fmt(d) {{
    if (!d || d.price == null) return '--';
    const c = d.chg_pct >= 0 ? '#ff6b6b' : '#74b9ff';
    const a = d.chg_pct >= 0 ? '▲' : '▼';
    return `<span style="color:#fff;font-weight:500">${{d.label}}</span> <span style="color:#ccc">${{d.price.toLocaleString()}}</span> <span style="color:${{c}}">${{a}}${{Math.abs(d.chg_pct).toFixed(2)}}%</span>`;
  }}
  const el = (id, html) => {{ const e = document.getElementById(id); if(e) e.innerHTML = html; }};
  el('banner-kospi',  fmt(idx.KOSPI));
  el('banner-nasdaq', fmt(idx.NASDAQ));
  el('banner-sp500',  fmt(idx.SP500));
  el('banner-vix',    fmt(com.VIX));
  el('banner-usdkrw', fmt(fx.USD_KRW));
}})();
</script>

<div class="header">
  <div>
    <div class="header-title">📊 SFD — Smart Finance Dynamic</div>
    <div class="header-sub">
      {trade_date[:4]}.{trade_date[4:6]}.{trade_date[6:]} | 생성: {now_str} KST
      | v3.9 BM-18 | 일일 시황 레포트
    </div>
  </div>
  <nav class="nav">
    <a href="#s0">📡온도계</a>
    <a href="#s1">🇰🇷영향</a>
    <a href="#s2">📅캘린더</a>
    <a href="#s3">🚀TOP20</a>
    <a href="#s5">🔭미래</a>
    <a href="#s6">📊진단</a><a href="#s7">📊순위</a>
    <a href="sfd_account_latest.html" style="margin-left:8px;background:#1e3a5f;border:1px solid #4a7abf;color:#90caf9;padding:5px 14px;border-radius:12px;text-decoration:none;font-size:12px;white-space:nowrap">💼 계좌분석 →</a>
  </nav>
</div>

<!-- 상단 요약 배너 -->
<div id="summary-banner" style="background:#1a1a2e;color:#fff;padding:8px 24px;font-size:12px;
     display:flex;gap:24px;overflow-x:auto;white-space:nowrap;border-bottom:1px solid #333">
  <span id="banner-kospi">KOSPI --</span>
  <span id="banner-nasdaq">NASDAQ --</span>
  <span id="banner-sp500">S&P500 --</span>
  <span id="banner-vix">VIX --</span>
  <span id="banner-usdkrw">USD/KRW --</span>
  <span id="banner-time" style="margin-left:auto;color:#888">{now_str}</span>
</div>

<div class="container">

<!-- ── 네이버 증권 스타일 대시보드 ─────────────────────────────── -->
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:14px" id="dashboard-grid">

  <!-- 오늘의 증시 -->
  <div class="section" style="padding:14px">
    <div class="subsec-label" style="margin-bottom:8px">오늘의 증시</div>
    <div id="db-market-rows">
      <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:0.5px solid #f0f0ee">
        <span style="font-size:12px;font-weight:500">코스피</span>
        <span id="db-kospi" style="font-size:12px">--</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:0.5px solid #f0f0ee">
        <span style="font-size:12px;font-weight:500">코스닥</span>
        <span id="db-kosdaq" style="font-size:12px">--</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:0.5px solid #f0f0ee">
        <span style="font-size:12px;color:#888">나스닥</span>
        <span id="db-nasdaq" style="font-size:12px">--</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:0.5px solid #f0f0ee">
        <span style="font-size:12px;color:#888">S&P500</span>
        <span id="db-sp500" style="font-size:12px">--</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:0.5px solid #f0f0ee">
        <span style="font-size:12px;color:#888">닛케이</span>
        <span id="db-nikkei" style="font-size:12px">--</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:5px 0">
        <span style="font-size:12px;color:#888">상하이</span>
        <span id="db-shanghai" style="font-size:12px">--</span>
      </div>
    </div>
  </div>

  <!-- 외국인/기관/개인 수급 -->
  <div class="section" style="padding:14px">
    <div class="subsec-label" style="margin-bottom:8px">수급 동향 (코스피 당일)</div>
    <div id="db-supply-rows">
      <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:0.5px solid #f0f0ee">
        <span style="font-size:12px;font-weight:500">🌍 외국인</span>
        <div style="text-align:right">
          <span id="db-foreign" style="font-size:13px;font-weight:500">집계중</span><br>
          <span style="font-size:10px;color:#888">순매수(억원)</span>
        </div>
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:0.5px solid #f0f0ee">
        <span style="font-size:12px;font-weight:500">🏦 기관</span>
        <div style="text-align:right">
          <span id="db-institution" style="font-size:13px;font-weight:500">집계중</span><br>
          <span style="font-size:10px;color:#888">순매수(억원)</span>
        </div>
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0">
        <span style="font-size:12px;font-weight:500">👤 개인</span>
        <div style="text-align:right">
          <span id="db-individual" style="font-size:13px;font-weight:500">집계중</span><br>
          <span style="font-size:10px;color:#888">순매수(억원)</span>
        </div>
      </div>
    </div>
    <div style="font-size:10px;color:#888;margin-top:6px;background:#f8f8f6;padding:5px 8px;border-radius:6px">
      💡 외국인 100조 순매도 추세 지속 중 (2026.01~) → 수급 악화 주의
    </div>
  </div>

  <!-- 환율 + 원자재 요약 -->
  <div class="section" style="padding:14px">
    <div class="subsec-label" style="margin-bottom:8px">환율 & 원자재</div>
    <div>
      <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:0.5px solid #f0f0ee">
        <span style="font-size:12px;font-weight:500">달러/원</span>
        <span id="db-usdkrw" style="font-size:12px">--</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:0.5px solid #f0f0ee">
        <span style="font-size:12px;color:#888">달러/엔</span>
        <span id="db-usdjpy" style="font-size:12px">--</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:0.5px solid #f0f0ee">
        <span style="font-size:12px;color:#888">금($/oz)</span>
        <span id="db-gold" style="font-size:12px">--</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:0.5px solid #f0f0ee">
        <span style="font-size:12px;color:#888">WTI유가</span>
        <span id="db-oil" style="font-size:12px">--</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:0.5px solid #f0f0ee">
        <span style="font-size:12px;color:#888">BTC</span>
        <span id="db-btc" style="font-size:12px">--</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:5px 0">
        <span style="font-size:12px;color:#888">VIX</span>
        <span id="db-vix2" style="font-size:12px">--</span>
      </div>
    </div>
  </div>
</div>

<!-- 업종상위 + 테마상위 + 인기검색 -->
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:14px">

  <!-- 업종상위 (SFD 트리거 기반) -->
  <div class="section" style="padding:14px">
    <div class="subsec-label" style="margin-bottom:8px">📈 업종상위 (뉴스 트리거)</div>
    <div id="db-sector-top">
      {sector_top_html}
    </div>
  </div>

  <!-- SFD 급등 후보 미리보기 -->
  <div class="section" style="padding:14px">
    <div class="subsec-label" style="margin-bottom:8px">🚀 SFD TOP5 미리보기</div>
    <div id="db-top5">
      {top5_preview_html}
    </div>
  </div>

  <!-- 캘린더 경보 미리보기 -->
  <div class="section" style="padding:14px">
    <div class="subsec-label" style="margin-bottom:8px">📅 임박 이벤트</div>
    <div id="db-calendar-preview">
      {calendar_preview_html}
    </div>
  </div>

</div>

<script>
// 대시보드 시장 데이터 채우기
(function() {{
  const rd  = {radar_json};
  const idx = (rd.market||{{}}).indices    || {{}};
  const fx  = (rd.market||{{}}).fx_rates   || {{}};
  const com = (rd.market||{{}}).commodities|| {{}};

  function priceFmt(d) {{
    if (!d || d.price == null) return '<span style="color:#888">--</span>';
    const c = (d.chg_pct||0) >= 0 ? '#e24b4a' : '#378ADD';
    const a = (d.chg_pct||0) >= 0 ? '▲' : '▼';
    return `<span style="color:#333;font-weight:500">${{Number(d.price).toLocaleString()}}</span> <span style="color:${{c}};font-size:11px">${{a}}${{Math.abs(d.chg_pct||0).toFixed(2)}}%</span>`;
  }}

  const set = (id, html) => {{ const e=document.getElementById(id); if(e) e.innerHTML=html; }};
  set('db-kospi',    priceFmt(idx.KOSPI));
  set('db-kosdaq',   priceFmt(idx.KOSDAQ));
  set('db-nasdaq',   priceFmt(idx.NASDAQ));
  set('db-sp500',    priceFmt(idx.SP500));
  set('db-nikkei',   priceFmt(idx.NIKKEI));
  set('db-shanghai', priceFmt(idx.SHANGHAI));
  set('db-usdkrw',   priceFmt(fx.USD_KRW));
  set('db-usdjpy',   priceFmt(fx.USD_JPY));
  set('db-gold',     priceFmt(com.GOLD));
  set('db-oil',      priceFmt(com.OIL_WTI));
  set('db-btc',      priceFmt(com.BTC));
  set('db-vix2',     priceFmt(com.VIX));

  // 배너도 채우기
  function bannerFmt(d) {{
    if (!d || d.price==null) return '--';
    const c=(d.chg_pct||0)>=0?'#ff6b6b':'#74b9ff';
    const a=(d.chg_pct||0)>=0?'▲':'▼';
    return `<span style="color:#fff;font-weight:500">${{d.label}}</span> <span style="color:#ccc">${{Number(d.price).toLocaleString()}}</span> <span style="color:${{c}}">${{a}}${{Math.abs(d.chg_pct||0).toFixed(2)}}%</span>`;
  }}
  const bset=(id,h)=>{{const e=document.getElementById(id);if(e)e.innerHTML=h;}};
  bset('banner-kospi',  bannerFmt(idx.KOSPI));
  bset('banner-nasdaq', bannerFmt(idx.NASDAQ));
  bset('banner-sp500',  bannerFmt(idx.SP500));
  bset('banner-vix',    bannerFmt(com.VIX));
  bset('banner-usdkrw', bannerFmt(fx.USD_KRW));
}})();
</script>

<!-- 본문 섹션 -->
  {s0}
  {s1}
  {s2}
  {s3_s4}
  {s5}
  {s6}
</div>

<div class="footer">
  SFD v3.9 | BM-18 적용 | Claude Sonnet 4.6 | 본 레포트는 투자 참고용이며 최종 판단은 본인 책임입니다.
</div>

<!-- 모바일 하단 네비게이션 -->
<nav class="mobile-nav">
  <a href="#s0"><span>📡</span>온도계</a>
  <a href="#s1"><span>🇰🇷</span>영향</a>
  <a href="#s2"><span>📅</span>캘린더</a>
  <a href="#s3"><span>🚀</span>TOP10</a>
  <a href="#s5"><span>🔭</span>미래</a>
  <a href="#s6"><span>📊</span>진단</a>
            <a href="#s7"><span>📊</span>순위</a>
</nav>
{_build_s7_section()}
</body>
</html>"""

# ── 메인 ─────────────────────────────────────────────────────────

def main():
    today = datetime.now()
    trade_date = today.strftime("%Y%m%d")
    logger.info(f"=== sfd_daily_report v1.0 START | {trade_date} ===")

    data = prepare_data()
    html = build_html(data, trade_date)

    # 저장
    out_path = os.path.join(REPORT_DIR, f"sfd_report_{trade_date}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    # latest 복사
    latest_path = os.path.join(OUTPUT_DIR, "sfd_report_latest.html")
    with open(latest_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info(f"✓ 레포트 저장: {out_path}")
    logger.info(f"✓ latest 복사: {latest_path}")
    logger.info(f"=== sfd_daily_report DONE ===")

if __name__ == "__main__":
    main()
