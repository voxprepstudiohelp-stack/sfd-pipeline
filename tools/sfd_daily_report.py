# sfd_daily_report.py v1.0
# SFD 일일 레포트 생성기 (장전/장마감 겸용)
#
# 실행: python -X utf8 tools\sfd_daily_report.py
# 출력: outputs/latest/sfd_daily_report_YYYYMMDD_HHMM.txt
#       콘솔 출력 (즉시 확인)
#
# 스케줄러 등록 권장:
#   [1회] 08:10 장전 — 매수 신호
#   [4회] 16:10 장마감 — 포트 점검 (kiwoom_portfolio 실행 후)

import io, os, sys
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from config import LATEST_DIR
except ImportError:
    LATEST_DIR = str(Path(__file__).resolve().parent.parent / "outputs" / "latest")

now       = datetime.now()
now_str   = now.strftime("%Y-%m-%d %H:%M")
file_tag  = now.strftime("%Y%m%d_%H%M")
hour      = now.hour
session   = "장전" if hour < 10 else ("장마감" if hour >= 15 else "장중")

# ── 파일 경로
SIGNAL_CSV  = os.path.join(LATEST_DIR, "sfd_master_signal_latest.csv")
GRID_CSV    = os.path.join(LATEST_DIR, "sfd_grid_signal_latest.csv")
SECTOR_JSON = os.path.join(LATEST_DIR, "sfd_sector_strength_latest.json")
MACRO_CSV   = os.path.join(LATEST_DIR, "sfd_macro_radar_latest.csv")
REPORT_PATH = os.path.join(LATEST_DIR, f"sfd_daily_report_{file_tag}.txt")

SEP  = "=" * 60
SEP2 = "-" * 60

lines = []
def p(s=""):
    lines.append(s)
    print(s)

# ── 헤더
p(SEP)
p(f"  SFD 일일 레포트 [{session}]  {now_str}")
p(SEP)

# ── 1. 신호 요약
if os.path.exists(SIGNAL_CSV):
    df = pd.read_csv(SIGNAL_CSV, dtype={"ticker": str}, encoding="utf-8-sig")
    for col in ["total_score", "tech_score", "news_score", "investor_score",
                "decay_score", "score_52w"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    reserve = df[df["signal"] == "RESERVE_BUY"].copy()
    watch   = df[df["signal"] == "WATCH_ONLY"].copy()
    expired = df[df["signal"] == "SIGNAL_EXPIRED"] if "signal" in df.columns else pd.DataFrame()

    trade_date = df["fetch_date"].iloc[0] if "fetch_date" in df.columns else "?"
    p(f"  기준 거래일: {trade_date}  |  총 {len(df)}종목")
    p(f"  RESERVE_BUY: {len(reserve)}  |  WATCH_ONLY: {len(watch)}  |  EXPIRED: {len(expired)}")
    p(SEP2)

    # ── RESERVE_BUY 상세
    p("【 RESERVE_BUY — 매수 후보 】")
    if reserve.empty:
        p("  해당 없음")
    else:
        for _, r in reserve.iterrows():
            ticker = r.get("ticker", "?")
            name   = r.get("name", "")[:8]
            score  = r.get("total_score", 0)
            tech   = r.get("tech_score",  0)
            news   = r.get("news_score",  0)
            inv    = r.get("investor_score", 0)
            dec    = r.get("decay_score",  0)
            s52    = r.get("score_52w", 0)
            rsi    = r.get("rsi", 0)
            ma     = r.get("ma_align", "")
            dflag  = r.get("decay_flag", "")
            pc     = r.get("prev_close", 0)
            grade_label = "A" if score >= 110 else "B"

            p(f"  [{grade_label}] {ticker} {name:<8} | 총점:{score:5.1f}pt "
              f"| tech:{tech:.0f} news:{news:.0f} inv:{inv:.0f} "
              f"decay:{dec:.1f}({dflag[:2]}) 52w:{s52:.0f}")
            p(f"       RSI:{rsi:.1f} MA:{ma} | 전일종가:{pc:,.0f}원")
    p(SEP2)

    # ── WATCH_ONLY 상위 10
    p("【 WATCH_ONLY — 관심 상위 10 】")
    top_w = watch.head(10)
    if top_w.empty:
        p("  해당 없음")
    else:
        for _, r in top_w.iterrows():
            ticker = r.get("ticker", "?")
            name   = r.get("name", "")[:8]
            score  = r.get("total_score", 0)
            rsi    = r.get("rsi", 0)
            ma     = r.get("ma_align", "")
            p(f"  {ticker} {name:<8} | {score:5.1f}pt | RSI:{rsi:.1f} {ma}")
    p(SEP2)

    # ── SIGNAL_EXPIRED 경보
    if not expired.empty:
        p("【 ⚠️ SIGNAL_EXPIRED — 신호 만료 종목 】")
        for _, r in expired.iterrows():
            p(f"  {r.get('ticker','')} {r.get('name','')[:8]} | "
              f"bars:{r.get('signal_bars_elapsed',0)} | 발행:{r.get('signal_issued_date','')}")
        p(SEP2)
else:
    p("  [ERROR] sfd_master_signal_latest.csv 없음")
    p(SEP2)

# ── 2. 섹터 강도 TOP 3
if os.path.exists(SECTOR_JSON):
    import json
    with open(SECTOR_JSON, encoding="utf-8") as f:
        sec = json.load(f)
    sectors = sec.get("sectors", [])
    p("【 섹터 강도 TOP 3 】")
    for s in sectors[:3]:
        p(f"  {s['sector']:<20} | {s['tier']} | 동적배수:{s['dynamic_multiplier']:.2f}x")
    p(SEP2)

# ── 3. 그리드 신호
if os.path.exists(GRID_CSV):
    gdf = pd.read_csv(GRID_CSV, dtype={"ticker": str}, encoding="utf-8-sig")
    buy_soon = gdf[gdf["action"] == "BUY_SOON"] if "action" in gdf.columns else pd.DataFrame()
    if not buy_soon.empty:
        p("【 그리드 매수 대기 종목 】")
        for _, r in buy_soon.iterrows():
            p(f"  {r.get('ticker','')} {r.get('name','')[:8]} | "
              f"1차매수가:{r.get('buy_step1',0):,}원 | 현재:{r.get('current',0):,}원 | "
              f"phase:{r.get('phase','')}")
        p(SEP2)

# ── 4. 매크로 요약 (있을 경우)
if os.path.exists(MACRO_CSV):
    try:
        mdf = pd.read_csv(MACRO_CSV, encoding="utf-8-sig")
        p("【 매크로 요약 】")
        for _, r in mdf.head(5).iterrows():
            key = r.get("indicator", r.get(mdf.columns[0], ""))
            val = r.get("value",    r.get(mdf.columns[1], ""))
            sig = r.get("signal",   "")
            p(f"  {key:<20} | {val}  {sig}")
        p(SEP2)
    except Exception:
        pass

# ── 푸터
p(f"  생성: {now_str}  |  SFD v4.0")
p(SEP)

# ── 파일 저장
os.makedirs(LATEST_DIR, exist_ok=True)
with open(REPORT_PATH, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print(f"\n[OK] 레포트 저장: {REPORT_PATH}")
