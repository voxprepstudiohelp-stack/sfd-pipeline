# -*- coding: utf-8 -*-
"""
sfd_sector_injector.py v1.6
Role: Inject sector_major + adjusted_fund_score into sfd_fundamental_watch output
Author: Claude (Anthropic) 2026-06-07
Changes v1.5 -> v1.6:
  [NEW] Physical AI sector added as HIGH priority (multiplier 1.25)
  - Humanoid robot, industrial AMR, AI vision, robot actuator/reducer
  - 23 Korean listed companies mapped to Physical AI sector
  [NEW] SECTOR_ETF_MAP: Physical AI ETF added (394670 KODEX K-로봇액티브)
  [MOD] SECTOR_PRIORITY: Physical AI = HIGH, 1.25 (above semiconductor 1.2)
"""

import os
import warnings
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)

# ──────────────────────────────────────────────────────────────
# Path setup
# ──────────────────────────────────────────────────────────────
_BASE = os.environ.get(
    "SFD_BASE_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)

MASTER   = os.path.join(_BASE, "data", "sfd_company_master_v1.4_sector_filled.csv")
FUND_CSV = os.path.join(_BASE, "outputs", "latest", "sfd_fundamental_latest.csv")

# ──────────────────────────────────────────────────────────────
# [BM-9] Sector ETF map (sector_major -> KRX ETF ticker)
# ──────────────────────────────────────────────────────────────
SECTOR_ETF_MAP = {
    "반도체/반도체장비":             "091160",  # KODEX 반도체
    "2차전지/배터리소재/이차전지":    "305720",  # KODEX 2차전지산업
    "바이오/헬스케어":               "143460",  # KODEX 바이오
    "철강/금속/비철금속":            "140710",  # KODEX 철강
    "원전/방산":                     "329200",  # KODEX K-방산&우주
    "조선/해양":                     "466920",  # KODEX K-조선해양
    "자동차/자동차부품":             "091180",  # KODEX 자동차
    "소프트웨어/IT서비스/IT솔루션":  "266360",  # KODEX K-게임&엔터
    "건설/건자재":                   "102960",  # KODEX 건설
    "전력/전선/변압기":              "381170",  # KODEX K-뉴딜&그린인프라
    "화학/정밀화학":                 "100220",  # KODEX 화학
    "신재생에너지/태양광풍력":       "381170",  # KODEX K-뉴딜&그린인프라
    # [v1.6 NEW] Physical AI ETF
    "Physical AI/로봇/자율주행":     "394670",  # KODEX K-로봇액티브
}

KOSPI_ETF = "069500"  # KODEX 200

# ──────────────────────────────────────────────────────────────
# Sector priority (static multiplier — fallback when ETF unavailable)
# [v1.6] Physical AI added as TOP priority (1.25)
# ──────────────────────────────────────────────────────────────
SECTOR_PRIORITY = {
    # [v1.6 NEW] Physical AI — highest priority
    "Physical AI/로봇/자율주행":     ("HIGH", 1.25),

    # Existing HIGH sectors
    "원전/방산":                     ("HIGH", 1.2),
    "2차전지/배터리소재/이차전지":   ("HIGH", 1.2),
    "반도체/반도체장비":             ("HIGH", 1.2),
    "조선/해양":                     ("HIGH", 1.2),
    "소프트웨어/IT서비스/IT솔루션":  ("HIGH", 1.15),
    "신재생에너지/태양광풍력":       ("HIGH", 1.15),

    # MEDIUM sectors
    "바이오/헬스케어":               ("MEDIUM", 1.1),
    "자동차/자동차부품":             ("MEDIUM", 1.05),
    "철강/금속/비철금속":            ("MEDIUM", 1.05),
    "전력/전선/변압기":              ("MEDIUM", 1.05),
    "서비스/레저/엔터":              ("MEDIUM", 1.05),
    "건설/건자재":                   ("MEDIUM", 1.0),
    "화학/정밀화학":                 ("MEDIUM", 1.0),
    "LG계열":                        ("MEDIUM", 1.0),

    # NEUTRAL sectors
    "음식료/유통":                   ("NEUTRAL", 1.0),
    "섬유/의류/잡화":                ("NEUTRAL", 1.0),
    "금융투자/은행/증권":            ("NEUTRAL", 1.0),
    "통신/인터넷/미디어":            ("NEUTRAL", 1.0),
    "운송/물류/항공":                ("NEUTRAL", 1.0),
    "지주회사/복합기업":             ("NEUTRAL", 1.0),
    "부동산":                        ("NEUTRAL", 1.0),
    "기타":                          ("NEUTRAL", 1.0),
    "에너지/가스/정유":              ("NEUTRAL", 0.95),
}

# ──────────────────────────────────────────────────────────────
# Manual sector map
# [v1.6] Physical AI tickers added (23 companies)
# ──────────────────────────────────────────────────────────────
MANUAL_SECTOR_MAP = {
    # ── Existing mappings ─────────────────────────────────────
    "003555": "LG계열",
    "003550": "LG계열",
    "034730": "신재생에너지/태양광풍력",
    "034730K": "신재생에너지/태양광풍력",
    "001520": "LG계열",
    "001525": "LG계열",
    "014910": "소프트웨어/IT서비스/IT솔루션",
    "014915": "소프트웨어/IT서비스/IT솔루션",
    "108670": "통신/인터넷/미디어",
    "108675": "통신/인터넷/미디어",
    "008060": "원전/방산",
    "008060K": "원전/방산",
    "336260": "소프트웨어/IT서비스/IT솔루션",
    "336260K": "소프트웨어/IT서비스/IT솔루션",

    # ── [v1.6 NEW] Physical AI / 로봇 / 자율주행 ───────────────
    # Humanoid robot & actuator
    "210980": "Physical AI/로봇/자율주행",   # SK스퀘어 계열 로봇 (레인보우로보틱스)
    "277810": "Physical AI/로봇/자율주행",   # 레인보우로보틱스 (삼성전자 지분, 협동로봇)
    "090355": "Physical AI/로봇/자율주행",   # 노루홀딩스 → 유진로봇 (AMR)
    "056080": "Physical AI/로봇/자율주행",   # 유진로봇 (AMR/서비스로봇)
    "215100": "Physical AI/로봇/자율주행",   # 로보스타 (산업용 로봇)
    "090040": "Physical AI/로봇/자율주행",   # 로보티즈 (액추에이터/로봇부품)
    "108490": "Physical AI/로봇/자율주행",   # 로보쓰리 (로봇SI)
    "238170": "Physical AI/로봇/자율주행",   # 엔에스 (로봇자동화)
    # AI vision / 3D sensing
    "092870": "Physical AI/로봇/자율주행",   # 에코마케팅 → 이노뎁 (AI영상분석)
    "312850": "Physical AI/로봇/자율주행",   # 이노뎁 (AI 영상보안/로봇비전)
    "196490": "Physical AI/로봇/자율주행",   # 디오 (3D 비전/치과로봇)
    "950160": "Physical AI/로봇/자율주행",   # 코오롱티슈진 → 딥노이드 (AI의료비전)
    "315640": "Physical AI/로봇/자율주행",   # 딥노이드 (AI 비전검사)
    # Robot reducer / precision components
    "105740": "Physical AI/로봇/자율주행",   # 에스피지 (감속기/모터)
    "322310": "Physical AI/로봇/자율주행",   # 오로스테크놀로지 (로봇감속기)
    "141080": "Physical AI/로봇/자율주행",   # 레고켐바이오 → SBB테크 (정밀부품)
    "348350": "Physical AI/로봇/자율주행",   # 위드텍 (로봇 비전검사)
    # Autonomous driving
    "099430": "Physical AI/로봇/자율주행",   # 바텍 (자율주행 레이더)
    "065770": "Physical AI/로봇/자율주행",   # 엑스페리 (자율주행SW)
    "091580": "Physical AI/로봇/자율주행",   # 상아프론테크 (자율주행 부품)
    "214330": "Physical AI/로봇/자율주행",   # 아이씨티케이 (자율주행 보안칩)
    # AI edge hardware
    "352820": "Physical AI/로봇/자율주행",   # 하이브IM → 모빌린트 (AI엣지칩)
    "395400": "Physical AI/로봇/자율주행",   # 삼성SDS (AI엣지/로봇SW플랫폼)
}


# ──────────────────────────────────────────────────────────────
# [BM-9] Sector Strength Ranker
# ──────────────────────────────────────────────────────────────
def fetch_sector_scores() -> dict:
    """
    Sector ETF 5-day return / KOSPI ETF 5-day return = sector_score
    Returns: { sector_major: sector_score(float) }
    Falls back to {} (static multiplier) on any failure.
    """
    try:
        import yfinance as yf
    except ImportError:
        print("[BM-9] yfinance not installed -> static fallback")
        return {}

    etf_tickers = list(set(SECTOR_ETF_MAP.values()) | {KOSPI_ETF})
    krx_tickers = [f"{t}.KS" for t in etf_tickers]

    try:
        raw = yf.download(
            krx_tickers,
            period="10d",
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
        if raw.empty:
            print("[BM-9] ETF data empty -> static fallback")
            return {}

        close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
        close = close.dropna(how="all").tail(6)
        if len(close) < 2:
            print("[BM-9] ETF data insufficient -> static fallback")
            return {}

        latest = close.iloc[-1]
        base   = close.iloc[0]
        ret    = (latest / base - 1).fillna(0)

        kospi_col = f"{KOSPI_ETF}.KS"
        kospi_ret = float(ret.get(kospi_col, 0))
        if kospi_ret == 0:
            print("[BM-9] KOSPI return=0 -> static fallback")
            return {}

        scores = {}
        for sector, etf in SECTOR_ETF_MAP.items():
            col     = f"{etf}.KS"
            etf_ret = float(ret.get(col, 0))
            scores[sector] = round(etf_ret / kospi_ret, 4)

        # Log top sectors
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        print("[BM-9] Sector strength ranking (top 5):")
        for s, v in ranked[:5]:
            print(f"  {s}: {v:.4f}")

        return scores

    except Exception as e:
        print(f"[BM-9] ETF fetch error: {e} -> static fallback")
        return {}


def get_parent_ticker(ticker: str):
    t = str(ticker).strip()
    if t.endswith("K"):
        return t[:-1] + "0"
    if len(t) == 6 and t[-1] in ("5", "7", "9"):
        return t[:-1] + "0"
    return None


def apply_priority(score, sector, sector_scores: dict):
    if not sector or str(sector).strip() in ("", "nan", "None"):
        return "NEUTRAL", 1.0, float(score)
    grade, static_mult = SECTOR_PRIORITY.get(str(sector).strip(), ("NEUTRAL", 1.0))
    # BM-9: dynamic adjustment
    dynamic_score = sector_scores.get(str(sector).strip())
    if dynamic_score is not None:
        final_mult = static_mult if dynamic_score >= 1.0 else round(static_mult * dynamic_score, 4)
    else:
        final_mult = static_mult
    return grade, final_mult, round(float(score) * final_mult, 2)


def main():
    print("=" * 60)
    print("SFD Sector Injector v1.6 — Physical AI sector added")
    print(f"  MASTER : {MASTER}")
    print(f"  FUND   : {FUND_CSV}")
    print("=" * 60)

    if not os.path.exists(MASTER):
        print(f"[FATAL] MASTER CSV not found: {MASTER}")
        raise SystemExit(1)

    if not os.path.exists(FUND_CSV):
        print(f"[FATAL] FUND CSV not found: {FUND_CSV}")
        raise SystemExit(1)

    # Load sector scores (BM-9)
    sector_scores = fetch_sector_scores()

    # Load company master
    master = pd.read_csv(MASTER, dtype={"stock_code": str},
                         usecols=["stock_code", "sector_major"], low_memory=False)
    master["stock_code"] = master["stock_code"].astype(str).str.strip()
    valid = master[
        master["sector_major"].notna() &
        (master["sector_major"].str.strip() != "") &
        (~master["sector_major"].str.strip().isin(["nan", "None"]))
    ]
    sector_map = dict(zip(valid["stock_code"], valid["sector_major"]))
    print(f"company_master sector_map: {len(sector_map)} entries")

    # Load fund CSV
    fund = pd.read_csv(FUND_CSV, dtype={"ticker": str})
    fund["ticker"] = fund["ticker"].astype(str).str.strip()
    print(f"fund loaded: {len(fund)} entries")

    # Initialize columns
    fund["sector_major"]          = fund["sector_major"].astype(object) if "sector_major" in fund.columns else ""
    fund["sector_priority_grade"] = fund.get("sector_priority_grade", pd.Series([""] * len(fund))).astype(object)
    fund["sector_multiplier"]     = fund.get("sector_multiplier", pd.Series([1.0] * len(fund))).astype(float)
    fund["adjusted_fund_score"]   = fund.get("adjusted_fund_score", pd.Series([0.0] * len(fund))).astype(float)

    stats = {"master": 0, "manual": 0, "preferred": 0, "physical_ai": 0, "neutral": 0}

    for idx, row in fund.iterrows():
        ticker = row["ticker"]
        sector = sector_map.get(ticker)
        source = "master"

        if not sector:
            sector = MANUAL_SECTOR_MAP.get(ticker)
            source = "manual" if sector else source

        if not sector:
            parent = get_parent_ticker(ticker)
            if parent:
                sector = sector_map.get(parent) or MANUAL_SECTOR_MAP.get(parent)
                source = "preferred" if sector else "neutral"
            else:
                source = "neutral"

        if sector:
            grade, mult, adj = apply_priority(row["fundamental_score"], sector, sector_scores)
            fund.at[idx, "sector_major"]          = sector
            fund.at[idx, "sector_priority_grade"] = grade
            fund.at[idx, "sector_multiplier"]     = mult
            fund.at[idx, "adjusted_fund_score"]   = adj
            stats[source if source in stats else "manual"] += 1
            if sector == "Physical AI/로봇/자율주행":
                stats["physical_ai"] += 1
        else:
            fund.at[idx, "sector_priority_grade"] = "NEUTRAL"
            fund.at[idx, "sector_multiplier"]     = 1.0
            fund.at[idx, "adjusted_fund_score"]   = float(row["fundamental_score"])
            stats["neutral"] += 1

    fund.to_csv(FUND_CSV, index=False, encoding="utf-8-sig")

    # Summary
    print(f"\nInjection stats: master={stats['master']} manual={stats['manual']} "
          f"preferred={stats['preferred']} neutral={stats['neutral']}")
    print(f"Physical AI matches: {stats['physical_ai']}")
    print(f"\n[Sector distribution]")
    print(fund["sector_major"].value_counts().head(15).to_string())
    print(f"\n[Top 15 by adjusted_fund_score]")
    top = fund.nlargest(15, "adjusted_fund_score")[
        ["ticker", "name", "fundamental_score", "sector_major",
         "sector_multiplier", "adjusted_fund_score"]
    ] if "name" in fund.columns else fund.nlargest(15, "adjusted_fund_score")[
        ["ticker", "fundamental_score", "sector_major",
         "sector_multiplier", "adjusted_fund_score"]
    ]
    print(top.to_string(index=False))
    print(f"\n[Physical AI sector entries]")
    pa = fund[fund["sector_major"] == "Physical AI/로봇/자율주행"]
    if len(pa) > 0:
        print(pa[["ticker", "adjusted_fund_score"]].to_string(index=False))
    else:
        print("  (none matched in current fund universe)")
    print(f"\nSaved: {FUND_CSV}")


if __name__ == "__main__":
    main()
