"""
sfd_report_rank_patch.py
=========================
목적: sfd_daily_report.py에 삽입할 시장 순위 섹션 (S7) HTML 스니펫 생성기
사용: sfd_daily_report.py 내 generate_report() 함수에서 호출

# ── sfd_daily_report.py 수정 지침 ──────────────────────────────
# 1. import 상단에 추가:
#      from sfd_report_rank_patch import build_rank_section
#
# 2. generate_report() 내 S6 섹션 직후에 삽입:
#      rank_html = build_rank_section()
#      html_body += rank_html
#
# 3. 사이드 네비게이션(모바일 하단 바)에 S7 버튼 추가:
#      <a href="#s7" class="nav-item">📊순위</a>
# ─────────────────────────────────────────────────────────────────
"""

import json
import os
from pathlib import Path
from datetime import datetime

BASE_DIR   = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs" / "latest"
RANK_FILE  = OUTPUT_DIR / "sfd_market_rank.json"


def _load_rank() -> dict:
    if RANK_FILE.exists():
        try:
            return json.loads(RANK_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _color(rate: float) -> str:
    """등락률 → 색상"""
    if rate > 0:
        return "#e53935"  # 빨강
    elif rate < 0:
        return "#1565c0"  # 파랑
    return "#888"


def _rank_table(rows: list[dict], show_vol: bool = False,
                show_net: bool = False, label: str = "") -> str:
    """TOP15 테이블 HTML"""
    if not rows:
        return f'<p style="color:#888;font-size:12px">{label} 데이터 없음</p>'
    
    header_extra = ""
    if show_vol:
        header_extra = "<th>거래량</th><th>증감%</th>"
    elif show_net:
        header_extra = "<th>순매수</th>"
    else:
        header_extra = "<th>거래량</th>"

    rows_html = ""
    for r in rows:
        rate  = r.get("change_rate", 0)
        color = _color(rate)
        sign  = "+" if rate > 0 else ""
        
        if show_vol:
            vol = r.get("volume", 0)
            vr  = r.get("vol_ratio", "")
            extra_td = f"<td>{vol:,}</td><td>{vr}</td>"
        elif show_net:
            nb = r.get("net_buy", 0)
            sign_nb = "+" if nb > 0 else ""
            extra_td = f'<td style="color:{color}">{sign_nb}{nb:,}</td>'
        else:
            vol = r.get("volume", 0)
            extra_td = f"<td>{vol:,}</td>"

        code_link = f'<a href="https://finance.naver.com/item/main.nhn?code={r["code"]}" target="_blank" style="color:inherit;text-decoration:none">{r["name"]}</a>'
        rows_html += f"""
        <tr>
          <td style="color:#888">{r['rank']}</td>
          <td style="font-weight:500">{code_link}</td>
          <td>{r['price']:,}원</td>
          <td style="color:{color};font-weight:600">{sign}{rate:.2f}%</td>
          {extra_td}
        </tr>"""

    return f"""
    <table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead>
        <tr style="border-bottom:1px solid #333;color:#aaa">
          <th style="width:28px">#</th>
          <th style="text-align:left">종목</th>
          <th>현재가</th>
          <th>등락률</th>
          {header_extra}
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>"""


def build_rank_section() -> str:
    """S7 시장 순위 섹션 전체 HTML 반환"""
    data    = _load_rank()
    updated = data.get("generated_at", "데이터 없음")
    
    rise_tbl     = _rank_table(data.get("rise_top15", []),     label="상승률")
    fall_tbl     = _rank_table(data.get("fall_top15", []),     label="하락률")
    vol_tbl      = _rank_table(data.get("volume_top15", []),   show_vol=True, label="거래량")
    foreign_tbl  = _rank_table(data.get("foreign_top15", []),  show_net=True, label="외국인")
    inst_tbl     = _rank_table(data.get("institution_top15",[]),show_net=True, label="기관")

    section = f"""
<!-- ===== S7: 시장 순위 (Market Rank) ===== -->
<section id="s7" style="margin:24px 0">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
    <h2 style="margin:0;font-size:16px;color:#e0e0e0">📊 시장 순위 <span style="font-size:11px;color:#888;font-weight:normal">TOP 15</span></h2>
    <span style="font-size:10px;color:#666">업데이트: {updated}</span>
  </div>

  <!-- 탭 컨트롤 -->
  <div id="rank-tabs" style="display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap">
    <button onclick="showRankTab('rise')"   class="rtab active" id="rtab-rise">🔴 상승</button>
    <button onclick="showRankTab('fall')"   class="rtab"        id="rtab-fall">🔵 하락</button>
    <button onclick="showRankTab('vol')"    class="rtab"        id="rtab-vol">📈 거래량</button>
    <button onclick="showRankTab('foreign')" class="rtab"       id="rtab-foreign">🌍 외국인</button>
    <button onclick="showRankTab('inst')"   class="rtab"        id="rtab-inst">🏦 기관</button>
  </div>

  <style>
    .rtab {{
      padding:4px 10px;border-radius:12px;border:1px solid #444;
      background:#1e1e1e;color:#ccc;cursor:pointer;font-size:12px;
    }}
    .rtab.active {{ background:#2a4a7f;border-color:#4a7abf;color:#fff; }}
    .rank-panel {{ display:none; }}
    .rank-panel.active {{ display:block; }}
  </style>

  <div id="rank-rise"    class="rank-panel active">{rise_tbl}</div>
  <div id="rank-fall"    class="rank-panel">{fall_tbl}</div>
  <div id="rank-vol"     class="rank-panel">{vol_tbl}</div>
  <div id="rank-foreign" class="rank-panel">{foreign_tbl}</div>
  <div id="rank-inst"    class="rank-panel">{inst_tbl}</div>

  <script>
  function showRankTab(name) {{
    document.querySelectorAll('.rank-panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.rtab').forEach(b => b.classList.remove('active'));
    document.getElementById('rank-' + name).classList.add('active');
    document.getElementById('rtab-' + name).classList.add('active');
  }}
  </script>
</section>
<!-- ===== /S7 ===== -->
"""
    return section


if __name__ == "__main__":
    # 테스트: 스니펫 출력
    html = build_rank_section()
    out  = Path("/tmp/test_rank_section.html")
    out.write_text(f"<html><body style='background:#111;color:#eee'>{html}</body></html>",
                   encoding="utf-8")
    print(f"테스트 파일 저장: {out}")
    print(f"HTML 길이: {len(html)} chars")
