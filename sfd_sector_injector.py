# -*- coding: utf-8 -*-
"""
sfd_sector_injector.py  v1.5
역할: sfd_fundamental_watch.py 출력에 sector_major + adjusted_fund_score 주입
수정: Claude (Anthropic) 2026-05-31
  v1.4 → v1.5
  ① [BM-9] Sector_Strength_Ranker 추가
     - 섹터 ETF 5일 수익률 / KOSPI 5일 수익률 = sector_score
     - sector_score >= 1.0 → 정적 multiplier 그대로 적용 (강세 섹터 확인)
     - sector_score <  1.0 → multiplier를 sector_score로 하향 보정
     - ETF 맵 없는 섹터 → 기존 정적 SECTOR_PRIORITY multiplier 유지 (fallback)
  ② 신규 출력 컬럼: sector_score (float, 소수점 4자리)
  ③ 로그: sector_score 상위 섹터 랭킹 출력
"""

import os
import warnings
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)

# ──────────────────────────────────────────────────────────────
# 경로 설정
# ──────────────────────────────────────────────────────────────
_BASE = os.environ.get(
    "SFD_BASE_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)

MASTER   = os.path.join(_BASE, "data", "sfd_company_master_v1.4_sector_filled.csv")
FUND_CSV = os.path.join(_BASE, "outputs", "latest", "sfd_fundamental_latest.csv")

# ──────────────────────────────────────────────────────────────
# [BM-9] 섹터 ETF 맵  (sector_major → KRX ETF 티커)
# ETF 맵 없는 섹터는 기존 정적 multiplier 유지
# ──────────────────────────────────────────────────────────────
SECTOR_ETF_MAP = {
    "반도체/반도체장비":           "091160",   # KODEX 반도체
    "2차전지/배터리소재/이차전지":  "305720",   # KODEX 2차전지산업
    "바이오/헬스케어":             "143460",   # KODEX 바이오
    "철강/금속/비철금속":          "140710",   # KODEX 철강
    "원전/방산":                   "329200",   # KODEX K-방산&우주
    "조선/해양":                   "466920",   # KODEX K-조선해양
    "자동차/자동차부품":           "091180",   # KODEX 자동차
    "소프트웨어/IT서비스/IT솔루션": "266360",   # KODEX K-게임&엔터 (IT서비스 대체)
    "건설/건자재":                 "102960",   # KODEX 건설
    "전력/전선/변압기":            "381170",   # KODEX K-뉴딜&그린인프라
    "화학/정밀화학":               "100220",   # KODEX 화학
    "신재생에너지/태양광풍력":     "381170",   # KODEX K-뉴딜&그린인프라
}

# KOSPI 벤치마크 ETF
KOSPI_ETF = "069500"   # KODEX 200

# ──────────────────────────────────────────────────────────────
# 섹터 우선순위 (정적 multiplier — ETF 맵 없는 섹터의 fallback)
# ──────────────────────────────────────────────────────────────
SECTOR_PRIORITY = {
    "원전/방산":                   ("HIGH",    1.2),
    "2차전지/배터리소재/이차전지":  ("HIGH",    1.2),
    "반도체/반도체장비":            ("HIGH",    1.2),
    "조선/해양":                    ("HIGH",    1.2),
    "소프트웨어/IT서비스/IT솔루션": ("HIGH",    1.15),
    "신재생에너지/태양광풍력":      ("HIGH",    1.15),
    "바이오/헬스케어":              ("MEDIUM",  1.1),
    "자동차/자동차부품":            ("MEDIUM",  1.05),
    "철강/금속/비철금속":           ("MEDIUM",  1.05),
    "건설/건자재":                  ("MEDIUM",  1.0),
    "화학/정밀화학":                ("MEDIUM",  1.0),
    "LG계열":                       ("MEDIUM",  1.0),
    "음식료/유통":                  ("NEUTRAL", 1.0),
    "섬유/의류/잡화":               ("NEUTRAL", 1.0),
    "금융투자/은행/증권":           ("NEUTRAL", 1.0),
    "통신/인터넷/미디어":           ("NEUTRAL", 1.0),
    "운송/물류/항공":               ("NEUTRAL", 1.0),
    "서비스/레저/엔터":             ("MEDIUM",  1.05),
    "지주회사/복합기업":            ("NEUTRAL", 1.0),
    "에너지/가스/정유":             ("NEUTRAL", 0.95),
    "부동산":                       ("NEUTRAL", 1.0),
    "기타":                         ("NEUTRAL", 1.0),
    "전력/전선/변압기":             ("MEDIUM",  1.05),
}

MANUAL_SECTOR_MAP = {
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
}


# ──────────────────────────────────────────────────────────────
# [BM-9] Sector_Strength_Ranker
# ──────────────────────────────────────────────────────────────
def fetch_sector_scores() -> dict:
    """
    섹터 ETF 5일 수익률 / KOSPI ETF 5일 수익률 = sector_score
    반환: { sector_major: sector_score(float) }
    ETF 데이터 취득 실패 시 → {} (전체 정적 fallback)
    """
    try:
        import yfinance as yf
    except ImportError:
        print("[BM-9] yfinance 미설치 → sector_score 전체 정적 fallback")
        return {}

    # 중복 제거된 ETF 티커 목록
    etf_tickers = list(set(SECTOR_ETF_MAP.values()) | {KOSPI_ETF})
    krx_tickers = [f"{t}.KS" for t in etf_tickers]

    try:
        raw = yf.download(
            krx_tickers,
            period="10d",         # 5거래일 확보 위해 10일 요청
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
        if raw.empty:
            print("[BM-9] ETF 데이터 수신 실패 → 정적 fallback")
            return {}

        # Close 추출
        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"]
        else:
            close = raw[["Close"]]

        close = close.dropna(how="all").tail(6)   # 최소 2행 필요(수익률 계산)
        if len(close) < 2:
            print("[BM-9] ETF 데이터 부족 → 정적 fallback")
            return {}

        # 5거래일 수익률: (최신종가 / 5거래일전종가) - 1
        latest = close.iloc[-1]
        base   = close.iloc[0]
        ret    = (latest / base - 1).fillna(0)

        kospi_col = f"{KOSPI_ETF}.KS"
        kospi_ret = float(ret.get(kospi_col, 0))
        if kospi_ret == 0:
            print("[BM-9] KOSPI 수익률 0 → 정적 fallback")
            return {}

        # sector_score 계산
        scores = {}
        for sector, etf in SECTOR_ETF_MAP.items():
            col = f"{etf}.KS"
            etf_ret = float(ret.get(col, 0))
            scores[sector] = round(etf_ret / kospi_ret, 4) if kospi_ret != 0 else 1.0

        return scores

    except Exception as e:
        print(f"[BM-9] ETF 조회 오류: {e} → 정적 fallback")
        return {}


def print_sector_ranking(scores: dict):
    if not scores:
        return
    print("\n[BM-9] Sector_Strength_Ranker (5일 ETF/KOSPI 수익률 비율)")
    sorted_s = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    for rank, (sec, sc) in enumerate(sorted_s, 1):
        flag = "▲ 강세" if sc >= 1.0 else "▼ 약세"
        print(f"  {rank:2d}. {sec:<30s} {sc:+.4f}  {flag}")


# ──────────────────────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────────────────────
def get_parent_ticker(ticker: str):
    t = str(ticker).strip()
    if t.endswith("K"):
        return t[:-1] + "0"
    if len(t) == 6 and t[-1] in ("5", "7", "9"):
        return t[:-1] + "0"
    return None


def apply_priority(score, sector, sector_scores: dict):
    """
    [BM-9] 적용 로직:
    1. ETF 맵 있는 섹터 → sector_score 계산
       - sector_score >= 1.0: 정적 multiplier 그대로 사용 (강세 확인)
       - sector_score <  1.0: sector_score로 multiplier 하향 보정
    2. ETF 맵 없는 섹터 → 기존 정적 multiplier 유지
    반환: (grade, static_mult, effective_mult, sector_score, adjusted_score)
    """
    if not sector or str(sector).strip() in ("", "nan", "None"):
        return "NEUTRAL", 1.0, 1.0, 1.0, float(score)

    grade, static_mult = SECTOR_PRIORITY.get(str(sector).strip(), ("NEUTRAL", 1.0))
    sc = sector_scores.get(str(sector).strip())   # None이면 ETF 맵 없음

    if sc is not None:
        # ETF 맵 있는 섹터: BM-9 동적 보정
        effective_mult = static_mult if sc >= 1.0 else round(static_mult * sc, 4)
    else:
        # ETF 맵 없는 섹터: 정적 유지
        effective_mult = static_mult
        sc = 1.0   # 로그용 기본값

    adj = round(float(score) * effective_mult, 2)
    return grade, static_mult, effective_mult, round(sc, 4), adj


# ──────────────────────────────────────────────────────────────
# main
# ──────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("SFD Sector Injector — post-processor  v1.5  [BM-9]")
    print(f"  MASTER : {MASTER}")
    print(f"  FUND   : {FUND_CSV}")
    print("=" * 60)

    if not os.path.exists(MASTER):
        print(f"[FATAL] MASTER CSV 없음: {MASTER}")
        raise SystemExit(1)
    if not os.path.exists(FUND_CSV):
        print(f"[FATAL] FUND CSV 없음: {FUND_CSV}")
        raise SystemExit(1)

    # ── company_master 로드
    master = pd.read_csv(MASTER, dtype={"stock_code": str},
                         usecols=["stock_code", "sector_major"], low_memory=False)
    master["stock_code"] = master["stock_code"].astype(str).str.strip()
    valid = master[
        master["sector_major"].notna() &
        (master["sector_major"].str.strip() != "") &
        (~master["sector_major"].str.strip().isin(["nan", "None"]))
    ]
    sector_map = dict(zip(valid["stock_code"], valid["sector_major"]))
    print(f"company_master sector_map: {len(sector_map)}건")

    # ── fund CSV 로드
    fund = pd.read_csv(FUND_CSV, dtype={"ticker": str})
    fund["ticker"] = fund["ticker"].astype(str).str.strip()
    print(f"fund 로드: {len(fund)}건")

    # 컬럼 초기화
    for col, default in [
        ("sector_major",          ""),
        ("sector_priority_grade", ""),
    ]:
        if col not in fund.columns:
            fund[col] = default
        fund[col] = fund[col].astype(object)

    for col, default in [
        ("sector_multiplier",    1.0),
        ("sector_score",         1.0),   # ★ BM-9 신규
        ("adjusted_fund_score",  0.0),
    ]:
        if col not in fund.columns:
            fund[col] = default
        fund[col] = fund[col].astype(float)

    # ── [BM-9] 섹터 강도 조회
    print("\n[BM-9] 섹터 ETF 5일 수익률 조회 중...")
    sector_scores = fetch_sector_scores()
    if sector_scores:
        print(f"  → sector_score 계산 완료: {len(sector_scores)}개 섹터")
        print_sector_ranking(sector_scores)
    else:
        print("  → 정적 multiplier 전체 적용 (ETF 데이터 없음)")

    # ── 종목별 섹터 주입
    stats = {"master": 0, "manual": 0, "preferred": 0, "neutral": 0}
    bm9_active = 0   # sector_score < 1.0 으로 보정된 건수

    for idx, row in fund.iterrows():
        ticker = row["ticker"]
        sector = sector_map.get(ticker)
        if sector:
            source = "master"
        else:
            sector = MANUAL_SECTOR_MAP.get(ticker)
            if sector:
                source = "manual"
            else:
                parent = get_parent_ticker(ticker)
                if parent:
                    sector = sector_map.get(parent) or MANUAL_SECTOR_MAP.get(parent)
                    source = "preferred" if sector else "neutral"
                else:
                    source = "neutral"

        if sector:
            grade, static_m, eff_m, sc, adj = apply_priority(
                row["fundamental_score"], sector, sector_scores
            )
            fund.at[idx, "sector_major"]           = sector
            fund.at[idx, "sector_priority_grade"]  = grade
            fund.at[idx, "sector_multiplier"]      = eff_m
            fund.at[idx, "sector_score"]           = sc
            fund.at[idx, "adjusted_fund_score"]    = adj
            if sc < 1.0 and sector in sector_scores:
                bm9_active += 1
        else:
            fund.at[idx, "sector_priority_grade"]  = "NEUTRAL"
            fund.at[idx, "sector_multiplier"]      = 1.0
            fund.at[idx, "sector_score"]           = 1.0
            fund.at[idx, "adjusted_fund_score"]    = float(row["fundamental_score"])

        stats[source] += 1

    fund.to_csv(FUND_CSV, index=False, encoding="utf-8-sig")

    # ── 결과 로그
    nan_remain = fund["sector_major"].isna().sum()
    print(f"\n주입 결과 ({len(fund)}건):")
    print(f"  company_master  : {stats['master']}건")
    print(f"  수동 매핑       : {stats['manual']}건")
    print(f"  우선주 연결     : {stats['preferred']}건")
    print(f"  NEUTRAL         : {stats['neutral']}건")
    print(f"  NaN 잔여        : {nan_remain}건  → 목표: 0")
    print(f"  [BM-9] 약세 하향 보정 종목: {bm9_active}건 (sector_score<1.0)")

    top = fund.nlargest(10, "adjusted_fund_score")[
        ["ticker", "name", "fundamental_score", "sector_major",
         "sector_score", "sector_multiplier", "adjusted_fund_score"]
    ]
    print(f"\n[adjusted_fund_score TOP10]\n{top.to_string(index=False)}")
    print(f"\n✅ 저장: {FUND_CSV}")


if __name__ == "__main__":
    main()
