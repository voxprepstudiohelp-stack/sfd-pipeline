#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sfd_daily_report.py v1.0
SFD ?쇱씪 HTML ?덊룷???앹꽦湲?(7?뱀뀡 ?꾩쟾??
?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺?곣봺??S0: 湲濡쒕쾶 ?⑤룄怨?(吏???섏쑉/?먯옄??VIX)
S1: ?ㅻ뒛???쒓뎅 ?곹뼢 ?붿씤 (?댁뒪 ?몃━嫄겸넂?뱁꽣)
S2: 罹섎┛??寃쎈낫 (D-30/7/1 ?먮룞 ?앹뾽)
S3: 湲됰벑?덉긽 TOP10
S4: 醫낅ぉ ?곸꽭 移대뱶
S5: 誘몃옒?곗뾽 紐⑤찘? 寃뚯씠吏
S6: 踰ㅼ튂留덊궧 + ?먭?吏꾨떒
異쒕젰: sfd_report_YYYYMMDD.html
?ㅽ뻾: python -X utf8 tools/sfd_daily_report.py
?ㅼ?以? 08:10 ?μ쟾 / 16:10 ?λ쭏媛?"""

import os, sys, json, csv, logging
from datetime import datetime
from pathlib import Path

import json as _json

def _load_market_rank() -> dict:
    _p = Path(__file__).parent.parent / "outputs" / "latest" / "sfd_market_rank.json"
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
    def _tbl(rows, show_vol=False, show_net=False, empty_msg="?곗씠???놁쓬"):
        if not rows:
            return f'<p style="color:#888;font-size:12px;padding:8px">{empty_msg}</p>'
        extra_th = "<th>嫄곕옒??/th><th>利앷컧%</th>" if show_vol else ("<th>?쒕ℓ??/th>" if show_net else "<th>嫄곕옒??/th>")
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
        return f'<table style="width:100%;border-collapse:collapse;font-size:12px"><thead><tr style="border-bottom:1px solid #333;color:#aaa"><th>#</th><th style="text-align:left">醫낅ぉ</th><th>?꾩옱媛</th><th>?깅씫瑜?/th>{extra_th}</tr></thead><tbody>{body}</tbody></table>'
    tabs = [
        ("rise","?뵶 ?곸듅",_tbl(rank_data.get("rise_top15",[]))),
        ("fall","?뵷 ?섎씫",_tbl(rank_data.get("fall_top15",[]))),
        ("vol","?뱢 嫄곕옒??,_tbl(rank_data.get("volume_top15",[]),show_vol=True)),
        ("foreign","?뙇 ?멸뎅??,_tbl(rank_data.get("foreign_top15",[]),show_net=True,empty_msg="?뚯씠?꾨씪???ㅽ뻾 ???쒖떆")),
        ("inst","?룱 湲곌?",_tbl(rank_data.get("institution_top15",[]),show_net=True,empty_msg="?뚯씠?꾨씪???ㅽ뻾 ???쒖떆")),
    ]
    btn_html = "".join(f'<button onclick="showRankTab(\'{k}\')" class="rtab{" active" if i==0 else ""}" id="rtab-{k}">{lbl}</button>' for i,(k,lbl,_) in enumerate(tabs))
    panel_html = "".join(f'<div id="rank-{k}" class="rank-panel{" active" if i==0 else ""}">{tbl}</div>' for i,(k,_,tbl) in enumerate(tabs))
    return f"""<section id="s7" class="section">
  <h2 class="sec-title">?뱤 ?쒖옣 ?쒖쐞 <span style="font-size:11px;color:#888;font-weight:normal">TOP 15</span><span style="font-size:10px;color:#666;float:right">{updated}</span></h2>
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

# ?? ?곗씠??濡쒕뱶 ?ы띁 ?????????????????????????????????????????????

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

# ?? ?곗씠??以鍮????????????????????????????????????????????????????

def prepare_data():
    radar  = load_json("sfd_global_radar_latest.json")
    master = load_csv("sfd_master_signal_latest.csv")
    signal = load_csv("sfd_signal.csv")
    backtest = load_json("sfd_backtest_report.json")
    grid   = load_csv("sfd_grid_signal_latest.csv")
    news   = load_csv("sfd_news_signal_latest.csv")
    timeout = load_json("signal_timeout_state.json")
    calendar = load_calendar()

    # TOP20: master_signal?먯꽌 WATCH_ONLY/RESERVE_BUY ?곸쐞
    candidates = [r for r in master if r.get("signal") in ("WATCH_ONLY", "RESERVE_BUY")]
    try:
        candidates.sort(key=lambda x: float(x.get("total_score", 0)), reverse=True)
    except Exception:
        pass
    top10 = candidates[:20]  # TOP20?쇰줈 ?뺤옣

    # prev_close 蹂닿컯: sfd_prev_close_latest.csv LEFT JOIN by ticker
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

    # SIGNAL_EXPIRED 寃쎄퀬
    expired = [r for r in master if r.get("signal") == "SIGNAL_EXPIRED"]

    # recent_trades: RESERVE_BUY ?ㅼ쟻 (return_d1 ?대┝李⑥닚 TOP10)
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

# ?? ?됱긽/?꾩씠肄??ы띁 ?????????????????????????????????????????????

def chg_color(v):
    if v is None: return "#888"
    return "#e24b4a" if float(v) >= 0 else "#378add"

def chg_arrow(v):
    if v is None: return "??
    return f"??{abs(float(v)):.2f}%" if float(v) >= 0 else f"??{abs(float(v)):.2f}%"

def signal_badge(sig):
    colors = {
        "RESERVE_BUY":    ("#e24b4a", "狩?留ㅼ닔?꾨낫"),
        "WATCH_ONLY":     ("#EF9F27", "?몓 愿??),
        "HOLD":           ("#888",    "??蹂댁쑀"),
        "SIGNAL_EXPIRED": ("#A32D2D", "???좏샇留뚮즺"),
    }
    c, t = colors.get(sig, ("#888", sig))
    return f'<span style="background:{c};color:#fff;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:500">{t}</span>'

def urgency_style(u):
    return {
        "HIGH": "background:#FCEBEB;border-left:4px solid #E24B4A;",
        "MID":  "background:#FAEEDA;border-left:4px solid #EF9F27;",
        "LOW":  "background:#E6F1FB;border-left:4px solid #378ADD;",
    }.get(u, "")

# ?? S0: 湲濡쒕쾶 ?⑤룄怨??????????????????????????????????????????????

def render_s0(radar):
    market = radar.get("market", {})
    indices    = market.get("indices", {})
    fx_rates   = market.get("fx_rates", {})
    commodities= market.get("commodities", {})
    vix_note   = radar.get("vix_note", "")

    # 吏?섎퀎 ?쒓뎅 ?곹뼢 ?ㅻ챸
    INDEX_CONTEXT = {
        "KOSPI":    ("肄붿뒪??, "?쒓뎅 ??뺤＜ 醫낇빀吏??, "吏곸젒 吏??),
        "KOSDAQ":   ("肄붿뒪??, "?쒓뎅 以묒냼??湲곗닠二?吏??, "吏곸젒 吏??),
        "SP500":    ("S&P500", "誘멸뎅 500? 湲곗뾽 吏?????꾩씪 ?깅씫???ㅼ쓬??肄붿뒪??諛⑺뼢??60~70% ?곕룞", "湲濡쒕쾶 ?좏뻾"),
        "NASDAQ":   ("?섏뒪??, "誘멸뎅 湲곗닠二?吏????諛섎룄泥?AI二?吏곸젒 ?곕룞. NASDAQ?????쇱꽦?꾩옄/SK?섏씠?됱뒪 媛뺤꽭", "諛섎룄泥??좏뻾"),
        "DOW":      ("?ㅼ슦議댁뒪", "誘멸뎅 ?곕웾二?30媛???寃쎄린 諛⑺뼢??吏??, "寃쎄린 ?좏뻾"),
        "NIKKEI":   ("?쏆???, "?쇰낯 吏?????뷀솕/?먰솕 ?숈“?? ?쏆??닳넃 = ?꾩떆??由ъ뒪???뺣?", "?꾩떆???숈“"),
        "SHANGHAI": ("?곹븯??, "以묎뎅 吏?????붿옣??硫댁꽭/?뚯옱二??곕룞. ?곹븯?닳넁 ??以묎뎅 ?뚮퉬 愿?⑥＜ 媛뺤꽭", "以묎뎅 ?뚮퉬 ?좏뻾"),
        "HANGSENG": ("??뀓", "?띿쉘 吏????以묎뎅 ?먮낯 ?먮쫫 諛붾줈誘명꽣", "以묎뎅 ?먮낯"),
    }
    FX_CONTEXT = {
        "USD_KRW": ("?щ윭/??, "?먰솕 ?쎌꽭(?? ???섏텧二??좊━, ?섏엯 ?먯옄?ъ＜ 遺덈━. 1,400???뚰뙆 ???멸뎅???댄깉 寃쎄퀬"),
        "USD_JPY": ("?щ윭/??, "?뷀솕 ?쎌꽭(?? ???쇰낯 ?섏텧二?寃쎌웳?β넁, ?쒓뎅 ?먮룞李??꾩옄? 寃쎌웳"),
        "USD_CNY": ("?щ윭/?꾩븞", "?꾩븞???쎌꽭(?? ??以묎뎅 ?섏텧 ?좊━, ?쒓뎅 ?以묎뎅 ?섏텧 遺덈━"),
        "EUR_USD": ("?좊줈/?щ윭", "?좊줈 媛뺤꽭(?? ??湲濡쒕쾶 ?щ윭 ?쎌꽭 ?좏샇, ?좏씎援??멸뎅???먭툑 ?좎엯"),
    }
    COM_CONTEXT = {
        "GOLD":    ("湲?, "?덉쟾?먯궛 ?좏샇 吏?? 湲댿넁 = 由ъ뒪???ㅽ봽 ??諛⑹뼱二?湲?愿?⑥＜ 媛뺤꽭"),
        "OIL_WTI": ("WTI?좉?", "?좉??????뺤쑀/議곗꽑(LNG?? 媛뺤꽭, ??났/?댁넚 ?쎌꽭. 以묐룞 湲댁옣 ??湲됰벑"),
        "COPPER":  ("援щ━", "'?ν꽣 肄뷀띁' ??寃쎄린 ?좏뻾 吏?? 援щ━??= 湲濡쒕쾶 寃쎄린 ?뚮났 ?좏샇 ???뚯옱/嫄댁꽕 媛뺤꽭"),
        "NATGAS":  ("泥쒖뿰媛??, "泥쒖뿰媛?ㅲ넁 ??LNG ?대컲??媛??愿?⑥＜ 媛뺤꽭. 寃⑥슱 ?쒖쫵 怨꾩젅??),
        "BTC":     ("鍮꾪듃肄붿씤", "Risk-on 吏?? BTC??= ?꾪뿕?먯궛 ?좏샇 ???깆옣二?湲곗닠二??숇컲 媛뺤꽭 寃쏀뼢"),
        "VIX":     ("VIX 怨듯룷吏??, "20 誘몃쭔: ?덉젙 | 20~30: 寃쎄퀎 | 30+: 怨듯룷(???留ㅼ닔 湲고쉶). ?ㅻ뒛: " + str(vix_note)),
        "US10Y":   ("誘멸뎅10?꾧뎅梨?, "湲덈━??= ?깆옣二?遺덈━, 諛곕떦二?由ъ툩 遺덈━. 4.5% ?뚰뙆 ???멸뎅???댄깉 寃쎄퀬"),
    }

    def row(d, key=""):
        if not d or d.get("price") is None:
            return ""
        color = chg_color(d.get("chg_pct"))
        arrow = chg_arrow(d.get("chg_pct"))
        # ?앹뾽 ?곗씠??        ctx = INDEX_CONTEXT.get(key) or FX_CONTEXT.get(key) or COM_CONTEXT.get(key)
        popup_title = ctx[0] if ctx else d.get('label','')
        popup_desc  = ctx[1] if ctx else ""
        popup_tag   = ctx[2] if ctx and len(ctx) > 2 else ""
        chg = d.get('chg_pct', 0) or 0
        impact = "?곸듅 ??愿???뱁꽣 湲띿젙?? if float(chg) > 0 else "?섎씫 ??愿???뱁꽣 二쇱쓽" if float(chg) < 0 else "蹂댄빀"
        price_str = str(d.get('price', '-'))
        onclick = f"showInfoPopup('{popup_title}', '{popup_desc}', '{popup_tag}', '{price_str}', '{arrow}', '{impact}')"
        return f"""
        <div class="mcard" onclick="{onclick}" style="cursor:pointer" title="?대┃?섎㈃ ?곸꽭 ?ㅻ챸">
          <div class="mlabel">{d.get('label','')}</div>
          <div class="mprice">{d.get('price', '-'):,.2f}</div>
          <div class="mchg" style="color:{color}">{arrow}</div>
        </div>"""

    idx_html = "".join(row(v, k) for k, v in indices.items())
    fx_html  = "".join(row(v, k) for k, v in fx_rates.items())
    com_html = "".join(row(v, k) for k, v in commodities.items())

    # RSS ?ㅻ뱶?쇱씤 ?곸쐞 10嫄?(紐⑤컮?쇰룄 異⑸텇??
    def _news_summary(title):
        t = title.lower()
        if any(k in t for k in ("cuts", "downgrade", "upgrade")): return "?깃툒蹂寃?
        if "ipo" in t: return "IPO"
        if any(k in t for k in ("earnings", "profit")): return "?ㅼ쟻"
        if any(k in t for k in ("rate", "fed", "fomc")): return "湲덈━"
        if any(k in t for k in ("crash", "disaster", "accident")): return "?ш퀬"
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
  <h2 class="sec-title">?뱻 S0 ??湲濡쒕쾶 ?⑤룄怨?<span style="font-size:11px;color:#888;font-weight:400">移대뱶 ?대┃ ???쒓뎅 ?곹뼢 ?ㅻ챸</span></h2>
  <div class="subsec-label">二쇱슂 吏??/div>
  <div class="market-grid">{idx_html}</div>
  <div class="subsec-label" style="margin-top:12px">?섏쑉</div>
  <div class="market-grid">{fx_html}</div>
  <div class="subsec-label" style="margin-top:12px">?먯옄??& ?먯궛</div>
  <div class="market-grid">{com_html}</div>
  <div class="vix-bar" style="color:{vix_color}">
    VIX {vix_val or '??} ??{vix_note}
  </div>
  <div class="subsec-label" style="margin-top:16px">湲濡쒕쾶 ?댁뒪 ?ㅻ뱶?쇱씤 (?대┃ ???먮Ц)</div>
  <div class="hl-box">{hl_html if hl_html else '<div class="empty">?댁뒪 ?놁쓬</div>'}</div>
</section>"""

# ?? S1: ?ㅻ뒛???쒓뎅 ?곹뼢 ?붿씤 ????????????????????????????????????

def render_s1(radar):
    triggers = radar.get("sector_triggers", [])
    if not triggers:
        return '<section id="s1" class="section"><h2 class="sec-title">?눖?눟 S1 ???ㅻ뒛???쒓뎅 ?곹뼢 ?붿씤</h2><div class="empty">?댁뒪 ?몃━嫄??놁쓬</div></section>'

    pos = [t for t in triggers if t.get("boost", 0) > 0]
    neg = [t for t in triggers if t.get("boost", 0) < 0]

    def trig_card(t):
        color = "#e24b4a" if t.get("boost", 0) > 0 else "#378add"
        sign  = "+" if t.get("boost", 0) > 0 else ""
        tickers_str = ", ".join(t.get("tickers", [])[:4])
        direction = "?곸듅" if t.get("boost",0) > 0 else "?섎씫"
        onclick = f"showInfoPopup('{t.get('sector','')}', '{t.get('headline','').replace(chr(39),'')}', '{t.get('source','')} 쨌 ?ㅼ썙?? {t.get('keyword','')}', '{sign}{t.get('boost',0)}pt boost', '愿??醫낅ぉ肄붾뱶: {tickers_str}', '{direction} ?몃━嫄?)"
        return f"""
        <div class="trig-card" onclick="{onclick}" style="cursor:pointer">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span class="trig-sector">{t.get('sector','')}</span>
            <span style="color:{color};font-weight:500;font-size:12px">{sign}{t.get('boost',0)}pt</span>
          </div>
          <div class="trig-headline">"{t.get('headline','')}"</div>
          <div class="trig-src">{t.get('source','')} 쨌 ?ㅼ썙?? {t.get('keyword','')}</div>
        </div>"""

    pos_html = "".join(trig_card(t) for t in pos[:5])
    neg_html = "".join(trig_card(t) for t in neg[:3])

    return f"""
<section id="s1" class="section">
  <h2 class="sec-title">?눖?눟 S1 ???ㅻ뒛???쒓뎅 ?곹뼢 ?붿씤</h2>
  <div class="two-col">
    <div>
      <div class="subsec-label" style="color:#e24b4a">???곸듅 ?몃━嫄?({len(pos)})</div>
      {pos_html if pos_html else '<div class="empty">?놁쓬</div>'}
    </div>
    <div>
      <div class="subsec-label" style="color:#378add">???섎씫 ?붿씤 ({len(neg)})</div>
      {neg_html if neg_html else '<div class="empty">?놁쓬</div>'}
    </div>
  </div>
</section>"""

# ?? S2: 罹섎┛??寃쎈낫 ???????????????????????????????????????????????

def render_s2(radar):
    alerts = radar.get("calendar_alerts", [])
    if not alerts:
        return '<section id="s2" class="section"><h2 class="sec-title">?뱟 S2 ??罹섎┛??寃쎈낫</h2><div class="empty">D-30 ?대궡 ?대깽???놁쓬</div></section>'

    DAY_KO = ["??,"??,"??,"紐?,"湲?,"??,"??]

    def _fmt_date(date_str):
        try:
            from datetime import datetime as _dt
            d = _dt.strptime(date_str, "%Y-%m-%d")
            return f"{d.month:02d}.{d.day:02d}", DAY_KO[d.weekday()]
        except Exception:
            return (date_str[:5] if date_str else "??), ""

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
        onclick   = f"showInfoPopup('{ev_name}', '{note_esc}', 'D-{days} | {ev_date}', '?섑삙 ?뱁꽣: {sectors}', '{boost_str}', '{u} 湲닿툒??)"
        sector_note = f"?섑삙: {sectors}" + (f" | {a.get('note','')}" if a.get("note") else "")
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
  <h2 class="sec-title">?뱟 S2 ??罹섎┛??寃쎈낫 ({len(alerts)}嫄? <span style="font-size:11px;color:#888;font-weight:400">?대┃ ???곸꽭</span></h2>
  {html}
</section>"""

# ?? S3/S4: 湲됰벑?덉긽 TOP10 + ?대┃ ?앹뾽 ?곸꽭 ??????????????????????

def score_winrate(score):
    """?먯닔?蹂?D+1 ?밸쪧 (諛깊뀒?ㅽ듃 湲곕컲)"""
    try:
        s = float(score)
        if s >= 95: return 0,  "洹뱀냼???곗씠?????좊ː ??쓬"
        if s >= 90: return 9,  "9% (?됯퇏?섏씡 -2.2%)"
        if s >= 85: return 29, "29% ??理쒓퀬 ?밸쪧 援ш컙"
        if s >= 80: return 14, "14% (?됯퇏?섏씡 -2.9%)"
        if s >= 70: return 17, "17% (?됯퇏?섏씡 -1.4%)"
        if s >= 60: return 18, "18% (?됯퇏?섏씡 -2.3%)"
        return 10, "10% 誘몃쭔 ??李멸퀬??
    except Exception:
        return 0, "?곗씠???놁쓬"

def score_holding(score, ma, rsi):
    """?덉긽 蹂댁쑀 湲곌컙 異붿젙"""
    try:
        s = float(score)
        r = float(rsi) if rsi else 50
        if s >= 85 and ma == "3ma_bull" and r < 65:
            return "D+1~3 ?ㅼ쐷", "#1D9E75"
        if s >= 70 and ma == "3ma_bull":
            return "D+1 ?⑦?", "#EF9F27"
        return "?뱀씪 愿李????먮떒", "#888"
    except Exception:
        return "?먮떒 遺덇?", "#888"

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
    """醫낅ぉ蹂??앹뾽 ?곗씠??JSON ?앹꽦"""
    popups = {}
    bands  = backtest.get("score_bands", {})

    for r in top10:
        ticker = r.get("ticker", "")
        score  = r.get("total_score", 0)
        rsi    = r.get("rsi", "")
        ma     = r.get("ma_align", "")

        wr, wr_note  = score_winrate(score)
        holding, h_color = score_holding(score, ma, rsi)

        # ?먯닔 援ъ꽦 (媛?而댄룷?뚰듃)
        tech_s = r.get("tech_score", 0)
        news_s = r.get("news_score", 0)
        inv_s  = r.get("investor_score", 0)
        theme_s= r.get("theme_score", 0)
        fund_s = r.get("fund_score", 0)
        decay_s= r.get("decay_score", 0)

        # ?댁뒪
        news_row = news_map.get(ticker, {})
        news_title = news_row.get("title", "") if news_row else ""
        news_link  = news_row.get("link", "#") if news_row else "#"

        # 由ъ뒪???먮떒
        risks = []
        try:
            if float(rsi) > 70: risks.append("RSI 怨쇰ℓ?????④린 議곗젙 媛??)
        except Exception: pass
        if ma == "bearish": risks.append("MA ??같?????섎씫 異붿꽭 以?)
        if str(r.get("decay_flag","")) not in ("FRESH",""):
            risks.append(f"?좏샇 ?명썑??{r.get('decay_flag','')}) ??吏꾩엯 ??대컢 二쇱쓽")
        if str(r.get("signal_timeout","")).lower() == "true":
            risks.append("?좏샇 ??꾩븘???꾨컯")
        if not risks: risks.append("?뱀씠 由ъ뒪???놁쓬")

        # MA ?댁꽍
        ma_map = {
            "3ma_bull":  "??3MA ?뺣같?????④린/以묎린/?κ린 紐⑤몢 ?곗긽??,
            "2ma_bull":  "??2MA 遺遺??뺣같????異붿꽭 ?꾪솚 珥덉엯",
            "bearish":   "?좑툘 ??같?????섎씫 異붿꽭, 諛섎벑 ??吏꾩엯 怨좊젮",
        }
        ma_desc = ma_map.get(ma, ma)

        # vol ?댁꽍
        vol_map = {
            "healthy_strong":              "嫄곕옒??嫄닿컯 ??媛뺥븳 留ㅼ닔??,
            "healthy_strong_accumulation": "嫄곕옒??嫄닿컯 ??留ㅼ쭛 ?⑦꽩",
            "healthy_mid":                 "嫄곕옒??蹂댄넻 ???뺤긽 ?섏?",
            "neutral_high":                "嫄곕옒??以묐┰ ??愿留?援ш컙",
            "sellout_warn":                "?좑툘 留ㅻ룄 寃쎄퀬 ??嫄곕옒??湲됱쬆",
            "sellout_strong":              "?슚 媛뺥븳 留ㅻ룄 ??二쇱쓽 ?꾩슂",
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
        return '<section id="s3" class="section"><h2 class="sec-title">?? S3 ??湲됰벑?덉긽 TOP10</h2><div class="empty">?좏샇 ?놁쓬</div></section>'

    popups = build_popup_data(top10, news_map, backtest)
    popup_json = json.dumps(popups, ensure_ascii=False)

    # ?⑹뼱 ?뺤쓽 ?곗씠??    GLOSSARY = {
        "?먯닔(pt)": "SFD 醫낇빀 ?먯닔 (理쒕? 225pt). 湲곗닠(93)+?댁뒪(30)+?섍툒(20)+?뚮쭏(10)+??붾찘??15)+遺?ㅽ듃 ?⑹궛. ?믪쓣?섎줉 留ㅼ닔 議곌굔 異⑹”",
        "?좏샇": "RESERVE_BUY(留ㅼ닔?꾨낫): ?먯닔 70pt ?댁긽 / WATCH_ONLY(愿??: 50pt ?댁긽 / SIGNAL_EXPIRED: 5遊??댁긽 寃쎄낵濡??좏샇 留뚮즺",
        "D+1 ?밸쪧": "???먯닔? 醫낅ぉ???ㅼ쓬??D+1) ?뚮윭??留덇컧????궗??鍮꾩쑉. 85~90pt 援ш컙??29%濡?理쒓퀬. 100%???놁쑝誘濡?李멸퀬??,
        "?몃━嫄?: "?벐?댁뒪: ?댁뒪 媛먯꽦?먯닔 5pt ?댁긽 / ?뮥?섍툒: ?멸뎅?맞룰린愿 ?쒕ℓ??10pt ?댁긽 / ?뱢湲곗닠: 3MA ?뺣같??,
        "蹂댁쑀湲곌컙": "D+1 ?⑦?: ?댁씪 ?섎（ / D+3~5 ?ㅼ쐷: 3~5??蹂댁쑀 ?꾨왂 / ?뱀씪 愿李? 異붽? ?뺤씤 ???먮떒",
        "RSI": "?곷?媛뺣룄吏??0~100). 70 ?댁긽: 怨쇰ℓ???④린 議곗젙 二쇱쓽) / 30 ?댄븯: 怨쇰ℓ??諛섎벑 湲곕?) / 50 洹쇱쿂: 以묐┰",
        "MA諛곗뿴": "?대룞?됯퇏??諛곗뿴. ?뺣같??3MA_BULL): ?④린>以묎린>?κ린濡??곗긽????留ㅼ닔 ?좊━. ??같?? ?섎씫 異붿꽭",
        "Decay": "?좏샇 ?명썑??吏?? FRESH: ?ㅻ뒛 諛쒖깮 / ?レ옄 ?댁닔濡??ㅻ옒???좏샇 ??吏꾩엯 ??대컢 二쇱쓽",
        "?꾩씪醫낃?": "??嫄곕옒??留덇컧 湲곗? 二쇨?. ?뱀씪 ?깅씫瑜??먮떒??湲곗???,
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
        # ?꾩씪醫낃?: prev_close ?먮뒗 sfd_technical?먯꽌 ?????덉쓬
        prev_close = r.get("prev_close","") or r.get("close","") or ""
        try:
            prev_close_str = f"{float(prev_close):,.0f}??
        except Exception:
            prev_close_str = "-"

        wr, _ = score_winrate(score)
        holding, h_color = score_holding(score, ma, rsi)

        trigger = []
        try:
            if float(news_s) >= 5:  trigger.append("?벐?댁뒪")
            if float(inv_s) >= 10:  trigger.append("?뮥?섍툒")
            if ma == "3ma_bull":    trigger.append("?뱢湲곗닠")
        except Exception: pass
        trigger_str = " ".join(trigger) if trigger else "?뱢湲곗닠"

        news_row   = news_map.get(ticker)
        news_title = (news_row.get("title","")[:30] + "...") if news_row else ""

        wr_color  = "#1D9E75" if wr >= 25 else "#EF9F27" if wr >= 15 else "#888"
        # ?쒖쐞蹂?諛곌꼍 媛뺤“
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
            <span style="font-size:9px;color:#aaa">D+1 ?밸쪧</span>
          </td>
          <td>
            <button onclick="event.stopPropagation();showPopup('{ticker}')"
              style="font-size:11px;padding:3px 10px;border-radius:20px;border:0.5px solid #ddd;
                     background:#f8f8f6;cursor:pointer;color:#333">
              ?곸꽭??            </button>
          </td>
        </tr>"""

    # ?⑹뼱 ?뺤쓽 ?⑤꼸 (?묎린/?쇱튂湲?
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
        ?뱰 ?⑹뼱 ?뺤쓽 (?쇱튂湲??묎린)
      </button>
      <div style="display:none;background:#f8f8f6;border-radius:10px;padding:12px 16px">
        {glossary_items}
      </div>
    </div>"""

    # ?앹뾽 HTML
    popup_html = """
<div id="popup-overlay" onclick="closePopup()"
  style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;
         background:rgba(0,0,0,0.5);z-index:1000;overflow-y:auto;-webkit-overflow-scrolling:touch">
  <div id="popup-box" onclick="event.stopPropagation()"
    style="background:#fff;border-radius:16px;max-width:680px;margin:40px auto 20px;
           padding:28px;position:relative">
    <button onclick="closePopup()"
      style="position:absolute;top:16px;right:16px;background:none;border:none;
             font-size:20px;cursor:pointer;color:#888">??/button>
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
  const sigLabel = d.signal === 'RESERVE_BUY' ? '狩?留ㅼ닔?꾨낫' : '?몓 愿??;

  // ?먯닔 援ъ꽦 諛?  const totalScore = parseFloat(d.score) || 0;
  const bars = [
    ['湲곗닠?먯닔 (MA/RSI/蹂쇰ⅷ)', d.tech_s, 93, '#378ADD'],
    ['?댁뒪?먯닔', d.news_s, 30, '#7F77DD'],
    ['?섍툒?먯닔 (?멸뎅??湲곌?)', d.inv_s, 20, '#1D9E75'],
    ['?뚮쭏?먯닔', d.theme_s, 10, '#EF9F27'],
    ['??붾찘?덉젏??, d.fund_s, 15, '#639922'],
    ['Decay ?⑤꼸??, d.decay_s, 0, '#E24B4A'],
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

  // ?밸쪧 寃뚯씠吏
  const wrPct = d.winrate;
  const wrColor = wrPct >= 25 ? '#1D9E75' : wrPct >= 15 ? '#EF9F27' : '#888';

  // 由ъ뒪????ぉ
  const riskHtml = d.risks.map(r =>
    `<div style="font-size:12px;padding:4px 0;border-bottom:0.5px solid #f0f0ee;color:#555">?좑툘 ${{r}}</div>`
  ).join('');

  // ?댁뒪
  const newsHtml = d.news_title
    ? `<a href="${{d.news_link}}" target="_blank"
         style="display:block;background:#f0f4ff;padding:8px 12px;border-radius:8px;
                font-size:12px;color:#333;text-decoration:none;margin-top:8px">
         ?벐 ${{d.news_title}}
       </a>`
    : '<div style="font-size:12px;color:#aaa;margin-top:8px">愿???댁뒪 ?놁쓬</div>';

  document.getElementById('popup-content').innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:16px">
      <div>
        <div style="font-size:22px;font-weight:500">${{d.name}}</div>
        <div style="font-size:12px;color:#888;margin-top:2px">${{d.ticker}} 쨌 ${{d.sector}}</div>
        <span style="background:${{sigColor}};color:#fff;padding:2px 10px;border-radius:20px;
                     font-size:11px;font-weight:500;margin-top:6px;display:inline-block">${{sigLabel}}</span>
      </div>
      <div style="text-align:right">
        <div style="font-size:36px;font-weight:500;color:#e24b4a">${{d.score}}<span style="font-size:14px">pt</span></div>
        <div style="font-size:11px;color:#888">理쒕? 225pt 湲곗?</div>
      </div>
    </div>

    <div style="background:#f8f8f6;border-radius:10px;padding:14px;margin-bottom:14px">
      <div style="font-size:11px;font-weight:500;color:#888;margin-bottom:10px;text-transform:uppercase;letter-spacing:.06em">?먯닔 援ъ꽦 ???????먯닔?멸?</div>
      ${{bars}}
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px">
      <div style="background:#f8f8f6;border-radius:10px;padding:12px">
        <div style="font-size:11px;color:#888;margin-bottom:6px">D+1 ?밸쪧 (諛깊뀒?ㅽ듃)</div>
        <div style="font-size:28px;font-weight:500;color:${{wrColor}}">${{wrPct}}%</div>
        <div style="font-size:10px;color:#888;margin-top:2px">${{d.wr_note}}</div>
        <div style="height:6px;background:#eee;border-radius:3px;margin-top:6px">
          <div style="width:${{wrPct}}%;height:100%;background:${{wrColor}};border-radius:3px"></div>
        </div>
      </div>
      <div style="background:#f8f8f6;border-radius:10px;padding:12px">
        <div style="font-size:11px;color:#888;margin-bottom:6px">?덉긽 蹂댁쑀 湲곌컙</div>
        <div style="font-size:16px;font-weight:500;color:${{d.h_color}};margin-top:4px">${{d.holding}}</div>
        <div style="margin-top:10px;font-size:11px;color:#666">RSI: ${{d.rsi}} | ${{d.ma_desc.split('??)[0].trim()}}</div>
      </div>
    </div>

    <div style="background:#f8f8f6;border-radius:10px;padding:12px;margin-bottom:14px">
      <div style="font-size:11px;color:#888;margin-bottom:6px">湲곗닠??遺꾩꽍</div>
      <div style="font-size:12px;color:#333;margin-bottom:4px">${{d.ma_desc}}</div>
      <div style="font-size:12px;color:#555">${{d.vol_desc}}</div>
    </div>

    ${{newsHtml}}

    <div style="margin-top:14px">
      <div style="font-size:11px;color:#888;margin-bottom:6px">由ъ뒪???붿씤</div>
      ${{riskHtml}}
    </div>

    <div style="margin-top:16px;background:#EEEDFE;padding:10px 14px;border-radius:8px;font-size:11px;color:#534AB7">
      ?뱄툘 蹂??먯닔??湲곗닠/?댁뒪/?섍툒/?뚮쭏/??붾찘??蹂듯빀 吏?쒖엯?덈떎.
      D+1 ?밸쪧? 怨쇨굅 諛깊뀒?ㅽ듃 湲곗??대ŉ 誘몃옒 ?섏씡??蹂댁옣?섏? ?딆뒿?덈떎.
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
  <h2 class="sec-title">?? S3 ??湲됰벑?덉긽 TOP20 <span style="font-size:11px;color:#888;font-weight:400">醫낅ぉ ?대┃ ???곸꽭 | ?ㅻ뜑 ???대┃ ???⑹뼱 ?ㅻ챸</span></h2>
  <div style="overflow-x:auto">
  <table class="data-table" style="min-width:780px">
    <thead>
      <tr>
        <th style="width:32px">#</th>
        <th>醫낅ぉ</th>
        <th onclick="showInfoPopup('?좏샇 ?깃툒 ?ㅻ챸','RESERVE_BUY 狩먮ℓ?섑썑蹂? 醫낇빀?먯닔 70pt ?댁긽, 利됱떆 愿???꾩슂\\nWATCH_ONLY ?몓愿?? 50pt ?댁긽, 紐⑤땲?곕쭅 ???\nSIGNAL_EXPIRED ?? ?좏샇 諛쒖깮 ??5遊??댁긽 寃쎄낵濡???대컢 留뚮즺 ???좉퇋 吏꾩엯 鍮꾧텒怨?,'','','?뱦 ?좏샇 ?⑹뼱')" style="cursor:pointer;color:#378ADD">?좏샇 ??/th>
        <th onclick="showInfoPopup('?먯닔(pt) 援ъ꽦 ?ㅻ챸','SFD 醫낇빀 ?먯닔 理쒕? 225pt\\n\\n湲곗닠?먯닔 理쒕? 93pt: MA諛곗뿴/RSI/嫄곕옒???⑦꽩\\n?댁뒪?먯닔 理쒕? 30pt: 愿???댁뒪 媛먯꽦 遺꾩꽍\\n?섍툒?먯닔 理쒕? 20pt: ?멸뎅?맞룰린愿 ?쒕ℓ??\n?뚮쭏?먯닔 10pt: ?뱁꽣 ?뚮쭏 ?대떦 ?щ?\\n??붾찘??15pt: ?щТ 嫄댁쟾??\n湲濡쒕쾶遺?ㅽ듃 짹20pt: 誘멸뎅 ?곕룞 醫낅ぉ\\n\\n70pt ?댁긽??留ㅼ닔?꾨낫, 85~90pt 援ш컙????궗??理쒓퀬 ?밸쪧(29%)','','','?뱦 ?먯닔 ?⑹뼱')" style="cursor:pointer;color:#378ADD">?먯닔 ??/th>
        <th onclick="showInfoPopup('?꾩씪 醫낃? ?섎?','??嫄곕옒????留덇컧 湲곗? 二쇨?(??\\n?ㅻ뒛 ?쒖옣 ?쒖옉 ????媛寃??鍮??깅씫瑜좊줈 ?먮떒\\n嫄곕옒 ???멸? ?뺤씤 沅뚯옣','','','?뱦 ?꾩씪醫낃?')" style="cursor:pointer;color:#378ADD">?꾩씪醫낃? ??/th>
        <th>?뱁꽣</th>
        <th onclick="showInfoPopup('?몃━嫄?& 蹂댁쑀湲곌컙 ?ㅻ챸','?몃━嫄??좏삎:\\n?벐?댁뒪: 愿???댁뒪 媛먯꽦?먯닔 5pt ?댁긽\\n?뮥?섍툒: ?멸뎅?맞룰린愿 ?쒕ℓ??10pt ?댁긽\\n?뱢湲곗닠: 3MA ?뺣같???④린>以묎린>?κ린 ?곗긽??\\n\\n?덉긽 蹂댁쑀湲곌컙:\\nD+1 ?⑦?: ?댁씪 ?섎（ 紐⑺몴\\nD+3~5 ?ㅼ쐷: 3~5??蹂댁쑀 ?꾨왂\\n?뱀씪 愿李? 異붽? ?뺤씤 ???먮떒','','','?뱦 ?몃━嫄?湲곌컙 ?⑹뼱')" style="cursor:pointer;color:#378ADD">?몃━嫄?湲곌컙 ??/th>
        <th>?댁뒪</th>
        <th onclick="showInfoPopup('D+1 ?밸쪧 ?댁꽕','諛깊뀒?ㅽ듃 湲곌컙: 2026.05~06 (7嫄곕옒?? 1,409嫄?\\n\\n?먯닔蹂?D+1 ?듭씪 ?묐큺 ?뺣쪧:\\n85-90pt: 29% ??理쒓퀬 援ш컙\\n70-80pt: 17%\\n60-70pt: 18%\\n90-95pt: 9% (??꽕?곸쑝濡???쓬)\\n\\n?좑툘 ?밸쪧 50% 誘몃쭔???뺤긽?낅땲??\n二쇱떇?쒖옣 ?뱀꽦??100% ?덉륫? 遺덇???\n??吏?쒕뒗 ?좏깮??李멸퀬 湲곗??낅땲??,'','','?뱦 D+1?밸쪧 ?⑹뼱')" style="cursor:pointer;color:#378ADD">D+1?밸쪧 ??/th>
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

# ?? S5: 誘몃옒?곗뾽 紐⑤찘? 寃뚯씠吏 ???????????????????????????????????

def render_s5(calendar):
    sectors  = calendar.get("future_industry_monitor", {}).get("sectors", [])
    last_upd = calendar.get("future_industry_monitor", {}).get("last_updated", "")

    phase_color = {
        "珥덉큹湲?:    "#B5D4F4",
        "珥덇린":      "#378ADD",
        "珥덇린?믪꽦??: "#1D9E75",
        "?깆옣":      "#639922",
        "?쇳겕":      "#EF9F27",
        "?앸뒗 以?:   "#E24B4A",
    }
    phase_pct = {
        "珥덉큹湲?: 10, "珥덇린": 25, "珥덇린?믪꽦??: 40,
        "?깆옣": 60, "?쇳겕": 80, "?앸뒗 以?: 90,
    }
    PHASE_DESC = {
        "珥덉큹湲?:    "?꾩쭅 二쇰쪟 ?ъ옄??愿???놁쓬 ???좎젏 湲고쉶. ??蹂?숈꽦 洹뱀떖, ?뚯븸 遺꾩궛 ?꾩닔",
        "珥덇린":      "湲濡쒕쾶 由ъ꽌移??멸툒 ?쒖옉 ???쇰━ ?대떟??吏꾩엯 援ш컙. ?⑥꽦以묎났??1留뚯썝? ?쒖젅",
        "珥덇린?믪꽦??: "湲곌? ?먭툑 ?좎엯 ?쒖옉 ??二쇰룄二??ㅺ낸 ?뺤꽦 以? 吏湲덉씠 ?⑷툑 援ш컙",
        "?깆옣":      "蹂멸꺽 ?곸듅 異붿꽭 ??二쇰룄 醫낅ぉ ?좊퀎 以묒슂. 怨좎젏 留ㅼ닔 由ъ뒪??利앷?",
        "?쇳겕":      "怨쇱뿴 寃쎄퀬 ???좎젏??李⑥씡 ?ㅽ쁽 援ш컙. ?좉퇋 吏꾩엯 由ъ뒪???믪쓬",
        "?앸뒗 以?:   "紐⑤찘? ?뚯쭊 ???ㅼ쓬 ?ъ씠??以鍮??쒖옉. ?듭젅 ??愿留?沅뚭퀬",
    }

    # horizon 湲곗??쇰줈 ?뺣젹 (吏㏃? 湲곌컙 ??湲?湲곌컙)
    def horizon_sort_key(s):
        h = s.get("horizon", "99??)
        try:
            return int(h.split("~")[0].replace("??,"").strip())
        except Exception:
            return 99

    sorted_sectors = sorted(sectors, key=horizon_sort_key)

    rows = ""
    for s in sorted_sectors:
        phase    = s.get("phase", "珥덇린")
        color    = phase_color.get(phase, "#888")
        pct      = phase_pct.get(phase, 30)
        horizon  = s.get('horizon','')
        name     = s.get('name','')
        tickers_str = " / ".join(s.get("key_tickers", [])[:3])
        phase_desc  = PHASE_DESC.get(phase, "")
        signal      = s.get('global_signal','').replace("'","")
        name_esc    = name.replace("'","")
        onclick = f"showInfoPopup('{horizon} : {name_esc}', '{phase_desc}', '{phase} ?④퀎', '?듭떖 醫낅ぉ: {tickers_str}', '湲濡쒕쾶 ?좏샇: {signal}', '誘몃옒?곗뾽 紐⑤찘?')"

        rows += f"""
        <div class="momentum-row" onclick="{onclick}" style="cursor:pointer;padding:8px;border-radius:8px;transition:background 0.15s" onmouseover="this.style.background='#f8f8f6'" onmouseout="this.style.background=''">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px">
            <div>
              <span style="font-size:12px;font-weight:500;color:{color};background:{color}18;padding:2px 8px;border-radius:20px;margin-right:8px">{horizon}</span>
              <span style="font-weight:500;font-size:13px">{name}</span>
            </div>
            <span style="font-size:11px;color:{color};font-weight:500;white-space:nowrap">{phase} ??/span>
          </div>
          <div class="progress-bar">
            <div class="progress-fill" style="width:{pct}%;background:{color}"></div>
          </div>
          <div style="font-size:10px;color:#888;margin-top:3px">
            ?듭떖 醫낅ぉ: {tickers_str} | {signal}
          </div>
        </div>"""

    return f"""
<section id="s5" class="section">
  <h2 class="sec-title">?뵯 S5 ??誘몃옒?곗뾽 紐⑤찘? <span style="font-size:11px;color:#888;font-weight:400">湲곌컙 ???곗뾽 ??| ?대┃ ???④퀎 ?댁꽕</span></h2>
  <div style="font-size:11px;color:#888;margin-bottom:12px">?낅뜲?댄듃: {last_upd} | ?ㅼ쓬: 遺꾧린 1??/div>
  {rows if rows else '<div class="empty">?곗씠???놁쓬</div>'}
  <div class="phase-legend" style="flex-wrap:wrap">
    <span style="color:#378ADD">??珥덇린(?쇰━)</span>
    <span style="color:#1D9E75">??珥덇린?믪꽦???⑷툑)</span>
    <span style="color:#639922">???깆옣(二쇰쪟)</span>
    <span style="color:#EF9F27">???쇳겕(怨쇱뿴)</span>
    <span style="color:#E24B4A">???앸뒗 以??듭젅)</span>
  </div>
</section>"""

# ?? S6: 踰ㅼ튂留덊궧 + ?먭?吏꾨떒 + ?곸쨷瑜?紐⑤땲?곕쭅 ????????????????????

def render_s6(backtest, expired, recent_trades=None):
    tiers   = backtest.get("tiers", {})
    reserve = tiers.get("RESERVE_BUY", {})
    watch   = tiers.get("WATCH_ONLY", {})
    bands   = backtest.get("score_bands", {})
    meta    = backtest.get("meta", {})

    # 理쒓퀬 ?밸쪧 援ш컙
    best_band = max(bands.items(), key=lambda x: x[1].get("win_rate", 0)) if bands else ("--", {})

    expired_html = ""
    for e in expired[:5]:
        name_e   = e.get("name","")
        ticker_e = e.get("ticker","")
        bars_e   = e.get("signal_bars_elapsed", "?")
        score_e  = e.get("total_score","")
        onclick_e = f"showInfoPopup('?좑툘 {name_e}({ticker_e}) ?좏샇 留뚮즺', 'SIGNAL_EXPIRED???좏샇 諛쒖깮 ??5遊?嫄곕옒?? ?댁긽 寃쎄낵??醫낅ぉ?낅땲?? 二쇨?媛 異⑸텇??諛섏쓳?섏? ?딆? 寃껋쑝濡?蹂댁쑀 以묒씠?쇰㈃ ?ъ????뺣━瑜?寃?좏븯?몄슂.', '{bars_e}遊?寃쎄낵 | ?먯닔: {score_e}pt', '沅뚭퀬: ?좉퇋 吏꾩엯 湲덉?', '蹂댁쑀 以묒씠硫??먯젅 湲곗? ?ы솗??, '?좏샇 留뚮즺 寃쎄퀬')"
        expired_html += f'<div class="expired-row" onclick="{onclick_e}" style="cursor:pointer">?좑툘 <strong>{name_e}({ticker_e})</strong> ??{bars_e}遊?寃쎄낵 | ?대┃ ??泥섎━ 諛⑸쾿</div>'

    # ?먯닔 援ш컙蹂??밸쪧 ?뚯씠釉?    band_rows = ""
    for band, bdata in sorted(bands.items(), key=lambda x: x[0], reverse=True):
        wr  = bdata.get("win_rate", 0)
        cnt = bdata.get("count", 0)
        avg = bdata.get("avg_return_d1", 0)
        bar_w = min(100, wr * 2)
        color = "#1D9E75" if wr >= 25 else "#EF9F27" if wr >= 15 else "#888"
        band_rows += f"""
        <tr>
          <td style="font-weight:500;font-size:12px">{band}pt</td>
          <td style="font-size:12px;text-align:center">{cnt}嫄?/td>
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

    # 理쒓렐 RESERVE_BUY 嫄곕옒 洹쇨굅 ?뚯씠釉?HTML ?앹꽦
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
            _win_badge = "???? if str(_win_raw) in ("1", "True", "true") else "????
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
    <div class="subsec-label">?뱥 理쒓렐 RESERVE_BUY 嫄곕옒 洹쇨굅 (D+1 ?ㅼ쟻) ???섏씡瑜??곸쐞 10嫄?/div>
    <div style="overflow-x:auto;margin-top:6px">
    <table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead>
        <tr style="background:#f8f8f6;border-bottom:2px solid #ddd">
          <th style="padding:6px 8px;text-align:left;font-weight:500">?좎쭨</th>
          <th style="padding:6px 8px;text-align:left;font-weight:500">醫낅ぉ肄붾뱶</th>
          <th style="padding:6px 8px;text-align:right;font-weight:500">?먯닔</th>
          <th style="padding:6px 8px;text-align:right;font-weight:500">吏꾩엯媛</th>
          <th style="padding:6px 8px;text-align:right;font-weight:500">?듭씪醫낃?</th>
          <th style="padding:6px 8px;text-align:right;font-weight:500">D+1?섏씡瑜?/th>
          <th style="padding:6px 8px;text-align:center;font-weight:500">寃곌낵</th>
        </tr>
      </thead>
      <tbody>{_rows_html}
      </tbody>
    </table>
    </div>
  </div>"""

    # ?곸쨷瑜?紐⑤땲?곕쭅 ?ㅻ챸
    date_range = f"{meta.get('date_range_start','')} ~ {meta.get('date_range_end','')}"
    total_dates = meta.get('total_dates', '--')
    total_records = meta.get('total_records', '--')

    return f"""
<section id="s6" class="section">
  <h2 class="sec-title">?뱤 S6 ???곸쨷瑜?紐⑤땲?곕쭅 & ?먭?吏꾨떒</h2>

  <!-- ?듭떖 吏??-->
  <div class="two-col" style="margin-bottom:14px">
    <div class="stat-box">
      <div class="stat-label">狩?RESERVE_BUY D+1 ?밸쪧</div>
      <div class="stat-val" style="color:#e24b4a">{reserve.get('win_rate','--')}%</div>
      <div class="stat-sub">?됯퇏?섏씡 {reserve.get('avg_return_d1','--')}% | {reserve.get('count','--')}嫄?遺꾩꽍</div>
      <div style="height:6px;background:#eee;border-radius:3px;margin-top:8px">
        <div style="width:{min(100, float(reserve.get('win_rate') or 0)*2):.0f}%;height:100%;background:#e24b4a;border-radius:3px"></div>
      </div>
    </div>
    <div class="stat-box">
      <div class="stat-label">?몓 WATCH_ONLY D+1 ?밸쪧</div>
      <div class="stat-val" style="color:#EF9F27">{watch.get('win_rate','--')}%</div>
      <div class="stat-sub">?됯퇏?섏씡 {watch.get('avg_return_d1','--')}% | {watch.get('count','--')}嫄?遺꾩꽍</div>
      <div style="height:6px;background:#eee;border-radius:3px;margin-top:8px">
        <div style="width:{min(100, float(watch.get('win_rate') or 0)*2):.0f}%;height:100%;background:#EF9F27;border-radius:3px"></div>
      </div>
    </div>
  </div>

  <div class="best-band">
    ??理쒓퀬 ?밸쪧 援ш컙: <strong>{best_band[0]}pt</strong> ??    ?밸쪧 {best_band[1].get('win_rate','--')}% |
    {best_band[1].get('count','--')}嫄?|
    ?됯퇏 D+1 ?섏씡 {best_band[1].get('avg_return_d1','--')}%
  </div>

  <!-- ?먯닔 援ш컙蹂??곸꽭 ?밸쪧 -->
  <div style="margin-top:16px">
    <div class="subsec-label">?먯닔 援ш컙蹂?D+1 ?곸쨷瑜??곸꽭 (諛깊뀒?ㅽ듃 {date_range} | {total_dates}嫄곕옒??| {total_records}嫄?</div>
    <div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
      <thead>
        <tr style="background:#f8f8f6">
          <th style="padding:6px 10px;text-align:left;font-weight:500">?먯닔 援ш컙</th>
          <th style="padding:6px 10px;text-align:center;font-weight:500">?섑뵆??/th>
          <th style="padding:6px 10px;font-weight:500">D+1 ?밸쪧</th>
          <th style="padding:6px 10px;text-align:right;font-weight:500">?됯퇏 ?섏씡</th>
        </tr>
      </thead>
      <tbody>{band_rows}</tbody>
    </table>
    </div>
    <div style="font-size:10px;color:#888;margin-top:6px">
      ?뱄툘 ?밸쪧 = D+1 醫낃? > 吏꾩엯 醫낃???鍮꾩쑉 | ?됯퇏?섏씡 留덉씠?덉뒪???먯젅 ?ы븿 ?꾩껜 ?됯퇏
    </div>
  </div>

  <!-- SIGNAL_EXPIRED -->
  {f'<div class="subsec-label" style="margin-top:14px;color:#A32D2D">?좑툘 SIGNAL_EXPIRED 寃쎄퀬 ({len(expired)}嫄? ???ъ????뺣━ 寃??/div>' if expired else ''}
  {expired_html}

  <!-- ?꾩쟻 ?곸쨷瑜?異붿쟻 ?덈궡 -->
  <div style="margin-top:16px;background:#E1F5EE;border-radius:10px;padding:14px;cursor:pointer"
       onclick="showInfoPopup('?뱢 ?꾩쟻 ?곸쨷瑜??몃옒???쒖뒪??, '留ㅼ씪 15:35 ?덊룷?몄뿉???꾩씪 TOP20 醫낅ぉ??D+1 ?ㅼ젣 ?섏씡瑜좎쓣 ?먮룞 吏묎퀎?⑸땲?? ???곗씠?곌? ?볦씠硫?BM(踰ㅼ튂留덊겕 紐⑤뱢) 媛以묒튂瑜??먮룞 議곗젙?섏뿬 ?먯닔 ?덉륫 ?뺥솗?꾧? ?먯쭊?곸쑝濡??μ긽?⑸땲??', '?댁쁺 紐⑺몴: RESERVE_BUY ?밸쪧 30%??/ ?됯퇏 D+1 ?섏씡 +1%??, '?꾩옱: 諛깊뀒?ㅽ듃 {total_records}嫄?遺꾩꽍 ?꾨즺', '?ㅼ쟾 ?곗씠???꾩쟻 吏꾪뻾 以???6/29 Run #93 ?댄썑 蹂멸꺽 吏묎퀎', '?곸쨷瑜??몃옒???ㅻ챸')">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <div style="font-size:12px;font-weight:500;color:#0F6E56">?뱢 ?꾩쟻 ?곸쨷瑜??몃옒?????댁쁺 諛⑹묠</div>
      <span style="font-size:11px;color:#0F6E56">?대┃ ???곸꽭 ??/span>
    </div>
    <div style="font-size:11px;color:#0F6E56;line-height:1.8;margin-top:6px">
      ??留ㅼ씪 15:35 ?덊룷?몄뿉???꾩씪 TOP20??D+1 ?ㅼ젣 ?섏씡瑜??먮룞 吏묎퀎<br>
      ??二쇨컙 ?⑥쐞 ?밸쪧 異붿씠 ???먯닔 ?꾧퀎媛??먮룞 議곗젙 (BM 媛以묒튂 ?쇰뱶諛?<br>
      ??紐⑺몴: RESERVE_BUY ?밸쪧 30% ?댁긽 / ?됯퇏 D+1 ?섏씡 +1% ?댁긽<br>
      ???꾩옱: <strong>諛깊뀒?ㅽ듃 ?곗씠??{total_records}嫄?遺꾩꽍 ?꾨즺</strong> | ?ㅼ쟾 ?꾩쟻 吏묎퀎 吏꾪뻾 以?    </div>
  </div>

  <!-- AI ?먭?吏꾨떒 -->
  <div class="self-diag" style="margin-top:12px;cursor:pointer"
       onclick="showInfoPopup('?쨼 SFD AI ?먭?吏꾨떒 硫붾え', 'SFD(Smart Finance Dynamic)??留??몄뀡留덈떎 誘멸뎄????ぉ怨?媛쒖꽑 諛⑺뼢???ㅼ뒪濡?湲곕줉?⑸땲?? ??硫붾え???ㅼ쓬 AI(Claude)媛 ?몄뀡???댁뼱諛쏆쓣 ??媛??癒쇱? ?쎈뒗 ?몄닔?멸퀎 ?먮즺?낅땲??', '誘멸뎄??1?쒖쐞: Reuters/AP RSS 吏곸젒 ?섏쭛', '誘멸뎄??2?쒖쐞: DART 怨듭떆 ?좏삎?믪쁺??媛뺣룄 留ㅽ븨', '誘멸뎄??3?쒖쐞: 李⑦듃?꾨줈 ?⑦꽩 S3/S4 諛섏쁺', 'AI ?먭?吏꾨떒 ?쒖뒪??)">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <div class="subsec-label" style="margin-bottom:0">?쨼 AI ?먭?吏꾨떒 硫붾え (?대┃ ???곸꽭)</div>
      <span style="font-size:11px;color:#534AB7">??/span>
    </div>
    <div class="diag-item" style="margin-top:8px">???꾨즺: 湲濡쒕쾶 ?덉씠??S0) + 7?뱀뀡 ?덊룷??+ ?대┃ ?앹뾽 + TOP20 + ?곸쨷瑜?紐⑤땲?곕쭅</div>
    <div class="diag-item">??誘멸뎄??1?쒖쐞: Reuters/AP RSS 吏곸젒 ?섏쭛</div>
    <div class="diag-item">??誘멸뎄??2?쒖쐞: DART 怨듭떆 ?좏삎?믪쁺??媛뺣룄 留ㅽ븨</div>
    <div class="diag-item">??誘멸뎄??3?쒖쐞: 李⑦듃?꾨줈 ?⑦꽩 S3 諛섏쁺 / ?꾩씪醫낃? ?곕룞</div>
    <div class="diag-item">???ㅼ?以? 08:10 / 09:05 / 15:35 ?섎（ 3??| 6/29 Run #93 ??TOP20 ?뺤긽??/div>
  </div>
  {recent_table_html}
</section>"""

# ?? HTML 議고빀 ????????????????????????????????????????????????????

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

    # 諛곕꼫/??쒕낫?쒖슜 JSON
    radar_slim = {
        "market": {
            "indices":    radar.get("market",{}).get("indices",{}),
            "fx_rates":   radar.get("market",{}).get("fx_rates",{}),
            "commodities":radar.get("market",{}).get("commodities",{}),
        }
    }
    radar_json = _json.dumps(radar_slim, ensure_ascii=False)

    # ?낆쥌?곸쐞: ?댁뒪 ?몃━嫄곗뿉???곸쐞 3媛?    triggers = radar.get("sector_triggers", [])
    sector_top_html = ""
    for i, t in enumerate(triggers[:5], 1):
        boost = t.get("boost", 0)
        color = "#e24b4a" if boost > 0 else "#378ADD"
        sign  = "+" if boost > 0 else ""
        sector_top_html += f"""
        <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:0.5px solid #f0f0ee;cursor:pointer"
             onclick="showInfoPopup('{t.get('sector','')}','{t.get('headline','').replace("'","")}','{t.get('source','')}','{sign}{boost}pt boost','?ㅼ썙?? {t.get('keyword','')}','?낆쥌 ?몃━嫄?)">
          <span style="font-size:12px;font-weight:500">{t.get('sector','')}</span>
          <span style="font-size:12px;color:{color};font-weight:500">{sign}{boost}pt</span>
        </div>"""
    if not sector_top_html:
        sector_top_html = '<div style="font-size:12px;color:#888;padding:8px 0">?몃━嫄??놁쓬</div>'

    # TOP5 誘몃━蹂닿린
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
        top5_preview_html = '<div style="font-size:12px;color:#888;padding:8px 0">6/29 ?댄썑 ?뺤긽??/div>'

    # 罹섎┛??誘몃━蹂닿린
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
        calendar_preview_html = '<div style="font-size:12px;color:#888;padding:8px 0">?대깽???놁쓬</div>'

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SFD ?쇱씪 ?덊룷??{trade_date}</title>
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

<!-- 怨듭슜 ?뺣낫 ?앹뾽 (S0/S1/S2/S5?? -->
<div id="info-popup-overlay" onclick="closeInfoPopup()"
  style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;
         background:rgba(0,0,0,0.5);z-index:999;overflow-y:auto;-webkit-overflow-scrolling:touch">
  <div id="info-popup-box" onclick="event.stopPropagation()"
    style="background:#fff;border-radius:16px;max-width:520px;margin:60px auto 20px;
           padding:24px;position:relative">
    <button onclick="closeInfoPopup()"
      style="position:absolute;top:14px;right:14px;background:none;border:none;
             font-size:22px;cursor:pointer;color:#888;line-height:1">??/button>
    <div id="info-popup-content"></div>
  </div>
</div>

<script>
function showInfoPopup(title, desc, tag, val1, val2, category) {{
  const tagColor = category === '誘몃옒?곗뾽 紐⑤찘?' ? '#534AB7' :
                   category === '湲濡쒕쾶 ?좏뻾' ? '#185FA5' :
                   category.includes('?몃━嫄?) ? '#e24b4a' :
                   category.includes('湲닿툒') ? '#A32D2D' : '#3B6D11';
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

// ?곷떒 諛곕꼫 ?곗씠??梨꾩슦湲?(function() {{
  const rd = {radar_json};
  const m  = rd.market || {{}};
  const idx = m.indices || {{}};
  const fx  = m.fx_rates || {{}};
  const com = m.commodities || {{}};
  function fmt(d) {{
    if (!d || d.price == null) return '--';
    const c = d.chg_pct >= 0 ? '#ff6b6b' : '#74b9ff';
    const a = d.chg_pct >= 0 ? '?? : '??;
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
    <div class="header-title">?뱤 SFD ??Smart Finance Dynamic</div>
    <div class="header-sub">
      {trade_date[:4]}.{trade_date[4:6]}.{trade_date[6:]} | ?앹꽦: {now_str} KST
      | v3.9 BM-18 | ?쇱씪 ?쒗솴 ?덊룷??    </div>
  </div>
  <nav class="nav">
    <a href="#s0">?뱻?⑤룄怨?/a>
    <a href="#s1">?눖?눟?곹뼢</a>
    <a href="#s2">?뱟罹섎┛??/a>
    <a href="#s3">??TOP20</a>
    <a href="#s5">?뵯誘몃옒</a>
    <a href="#s6">?뱤吏꾨떒</a><a href="#s7">?뱤?쒖쐞</a>
    <a href="sfd_account_latest.html" style="margin-left:8px;background:#1e3a5f;border:1px solid #4a7abf;color:#90caf9;padding:5px 14px;border-radius:12px;text-decoration:none;font-size:12px;white-space:nowrap">?뮳 怨꾩쥖遺꾩꽍 ??/a>
  </nav>
</div>

<!-- ?곷떒 ?붿빟 諛곕꼫 -->
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

<!-- ?? ?ㅼ씠踰?利앷텒 ?ㅽ?????쒕낫????????????????????????????????? -->
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:14px" id="dashboard-grid">

  <!-- ?ㅻ뒛??利앹떆 -->
  <div class="section" style="padding:14px">
    <div class="subsec-label" style="margin-bottom:8px">?ㅻ뒛??利앹떆</div>
    <div id="db-market-rows">
      <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:0.5px solid #f0f0ee">
        <span style="font-size:12px;font-weight:500">肄붿뒪??/span>
        <span id="db-kospi" style="font-size:12px">--</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:0.5px solid #f0f0ee">
        <span style="font-size:12px;font-weight:500">肄붿뒪??/span>
        <span id="db-kosdaq" style="font-size:12px">--</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:0.5px solid #f0f0ee">
        <span style="font-size:12px;color:#888">?섏뒪??/span>
        <span id="db-nasdaq" style="font-size:12px">--</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:0.5px solid #f0f0ee">
        <span style="font-size:12px;color:#888">S&P500</span>
        <span id="db-sp500" style="font-size:12px">--</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:0.5px solid #f0f0ee">
        <span style="font-size:12px;color:#888">?쏆???/span>
        <span id="db-nikkei" style="font-size:12px">--</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:5px 0">
        <span style="font-size:12px;color:#888">?곹븯??/span>
        <span id="db-shanghai" style="font-size:12px">--</span>
      </div>
    </div>
  </div>

  <!-- ?멸뎅??湲곌?/媛쒖씤 ?섍툒 -->
  <div class="section" style="padding:14px">
    <div class="subsec-label" style="margin-bottom:8px">?섍툒 ?숉뼢 (肄붿뒪???뱀씪)</div>
    <div id="db-supply-rows">
      <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:0.5px solid #f0f0ee">
        <span style="font-size:12px;font-weight:500">?뙇 ?멸뎅??/span>
        <div style="text-align:right">
          <span id="db-foreign" style="font-size:13px;font-weight:500">吏묎퀎以?/span><br>
          <span style="font-size:10px;color:#888">?쒕ℓ???듭썝)</span>
        </div>
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:0.5px solid #f0f0ee">
        <span style="font-size:12px;font-weight:500">?룱 湲곌?</span>
        <div style="text-align:right">
          <span id="db-institution" style="font-size:13px;font-weight:500">吏묎퀎以?/span><br>
          <span style="font-size:10px;color:#888">?쒕ℓ???듭썝)</span>
        </div>
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0">
        <span style="font-size:12px;font-weight:500">?뫀 媛쒖씤</span>
        <div style="text-align:right">
          <span id="db-individual" style="font-size:13px;font-weight:500">吏묎퀎以?/span><br>
          <span style="font-size:10px;color:#888">?쒕ℓ???듭썝)</span>
        </div>
      </div>
    </div>
    <div style="font-size:10px;color:#888;margin-top:6px;background:#f8f8f6;padding:5px 8px;border-radius:6px">
      ?뮕 ?멸뎅??100議??쒕ℓ??異붿꽭 吏??以?(2026.01~) ???섍툒 ?낇솕 二쇱쓽
    </div>
  </div>

  <!-- ?섏쑉 + ?먯옄???붿빟 -->
  <div class="section" style="padding:14px">
    <div class="subsec-label" style="margin-bottom:8px">?섏쑉 & ?먯옄??/div>
    <div>
      <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:0.5px solid #f0f0ee">
        <span style="font-size:12px;font-weight:500">?щ윭/??/span>
        <span id="db-usdkrw" style="font-size:12px">--</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:0.5px solid #f0f0ee">
        <span style="font-size:12px;color:#888">?щ윭/??/span>
        <span id="db-usdjpy" style="font-size:12px">--</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:0.5px solid #f0f0ee">
        <span style="font-size:12px;color:#888">湲?$/oz)</span>
        <span id="db-gold" style="font-size:12px">--</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:0.5px solid #f0f0ee">
        <span style="font-size:12px;color:#888">WTI?좉?</span>
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

<!-- ?낆쥌?곸쐞 + ?뚮쭏?곸쐞 + ?멸린寃??-->
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:14px">

  <!-- ?낆쥌?곸쐞 (SFD ?몃━嫄?湲곕컲) -->
  <div class="section" style="padding:14px">
    <div class="subsec-label" style="margin-bottom:8px">?뱢 ?낆쥌?곸쐞 (?댁뒪 ?몃━嫄?</div>
    <div id="db-sector-top">
      {sector_top_html}
    </div>
  </div>

  <!-- SFD 湲됰벑 ?꾨낫 誘몃━蹂닿린 -->
  <div class="section" style="padding:14px">
    <div class="subsec-label" style="margin-bottom:8px">?? SFD TOP5 誘몃━蹂닿린</div>
    <div id="db-top5">
      {top5_preview_html}
    </div>
  </div>

  <!-- 罹섎┛??寃쎈낫 誘몃━蹂닿린 -->
  <div class="section" style="padding:14px">
    <div class="subsec-label" style="margin-bottom:8px">?뱟 ?꾨컯 ?대깽??/div>
    <div id="db-calendar-preview">
      {calendar_preview_html}
    </div>
  </div>

</div>

<script>
// ??쒕낫???쒖옣 ?곗씠??梨꾩슦湲?(function() {{
  const rd  = {radar_json};
  const idx = (rd.market||{{}}).indices    || {{}};
  const fx  = (rd.market||{{}}).fx_rates   || {{}};
  const com = (rd.market||{{}}).commodities|| {{}};

  function priceFmt(d) {{
    if (!d || d.price == null) return '<span style="color:#888">--</span>';
    const c = (d.chg_pct||0) >= 0 ? '#e24b4a' : '#378ADD';
    const a = (d.chg_pct||0) >= 0 ? '?? : '??;
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

  // 諛곕꼫??梨꾩슦湲?  function bannerFmt(d) {{
    if (!d || d.price==null) return '--';
    const c=(d.chg_pct||0)>=0?'#ff6b6b':'#74b9ff';
    const a=(d.chg_pct||0)>=0?'??:'??;
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

<!-- 蹂몃Ц ?뱀뀡 -->
  {s0}
  {s1}
  {s2}
  {s3_s4}
  {s5}
  {s6}
</div>

<div class="footer">
  SFD v3.9 | BM-18 ?곸슜 | Claude Sonnet 4.6 | 蹂??덊룷?몃뒗 ?ъ옄 李멸퀬?⑹씠硫?理쒖쥌 ?먮떒? 蹂몄씤 梨낆엫?낅땲??
</div>

<!-- 紐⑤컮???섎떒 ?ㅻ퉬寃뚯씠??-->
<nav class="mobile-nav">
  <a href="#s0"><span>?뱻</span>?⑤룄怨?/a>
  <a href="#s1"><span>?눖?눟</span>?곹뼢</a>
  <a href="#s2"><span>?뱟</span>罹섎┛??/a>
  <a href="#s3"><span>??</span>TOP10</a>
  <a href="#s5"><span>?뵯</span>誘몃옒</a>
  <a href="#s6"><span>?뱤</span>吏꾨떒</a>
            <a href="#s7"><span>?뱤</span>?쒖쐞</a>
</nav>
{_build_s7_section()}
</body>
</html>"""

# ?? 硫붿씤 ?????????????????????????????????????????????????????????

def main():
    today = datetime.now()
    trade_date = today.strftime("%Y%m%d")
    logger.info(f"=== sfd_daily_report v1.0 START | {trade_date} ===")

    data = prepare_data()
    html = build_html(data, trade_date)

    # ???    out_path = os.path.join(REPORT_DIR, f"sfd_report_{trade_date}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    # latest 蹂듭궗
    latest_path = os.path.join(OUTPUT_DIR, "sfd_report_latest.html")
    with open(latest_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info(f"???덊룷????? {out_path}")
    logger.info(f"??latest 蹂듭궗: {latest_path}")
    logger.info(f"=== sfd_daily_report DONE ===")

if __name__ == "__main__":
    main()

