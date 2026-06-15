# 파일명: patch_investor_flow_v11e.py
# 작성자: Claude (Anthropic)
# 목적:
#   1. stock_code NaN 제거
#   2. listed_flag/status_active 필터로 실제 상장종목만 추출
#   3. 중복 stock_code 제거 → 약 2,770건으로 축소

from pathlib import Path

TARGET = Path(
    r"D:\AI_WorkSpace\I_SFC\09_Implementation"
    r"\SFC_DataPipeline\tools\sfd_investor_flow_fetch.py"
)

content = TARGET.read_text(encoding="utf-8")
original = content

# ── load_ticker_list 전체 교체 ────────────────────────────────
OLD = '''def load_ticker_list():
    company_file=MASTER_DIR/"01_DB/sfd_company_master_v1.4_sector_filled.csv"
    if not company_file.exists():
        print("company_master 없음")
        return []
    df=pd.read_csv(company_file,dtype=str)
    # ticker 컬럼 유연 탐색
    for col in ["stock_code","ticker","종목코드","code","Code","TICKER"]:
        if col in df.columns:
            return df[col].astype(str).str.zfill(6).tolist()
    print("[WARN] ticker 컬럼 없음. 컬럼목록:", list(df.columns))
    return []'''

NEW = '''def load_ticker_list():
    company_file=MASTER_DIR/"01_DB/sfd_company_master_v1.4_sector_filled.csv"
    if not company_file.exists():
        print("company_master 없음")
        return []
    df=pd.read_csv(company_file,dtype=str)

    # ── 필터 1: stock_code NaN 제거
    if "stock_code" not in df.columns:
        print("[WARN] stock_code 컬럼 없음:", list(df.columns))
        return []
    df=df[df["stock_code"].notna() & (df["stock_code"].str.strip()!="")]

    # ── 필터 2: 상장 종목만 (listed_flag=True, status_active=True)
    if "listed_flag" in df.columns:
        df=df[df["listed_flag"].astype(str).str.upper().isin(["TRUE","1","YES"])]
    if "status_active" in df.columns:
        df=df[df["status_active"].astype(str).str.upper().isin(["TRUE","1","YES"])]

    # ── 필터 3: stock_code 중복 제거 (재무 연도별 다중행 대응)
    df=df.drop_duplicates(subset=["stock_code"])

    tickers=df["stock_code"].astype(str).str.zfill(6).tolist()
    print(f"  종목수 로드: {len(tickers)}건")
    return tickers'''

if OLD in content:
    content = content.replace(OLD, NEW)
    print("[OK] load_ticker_list filter replaced DONE")
else:
    print("[FAIL] load_ticker_list pattern not found — current function:")
    in_func = False
    for i, line in enumerate(content.splitlines(), 1):
        if "def load_ticker_list" in line:
            in_func = True
        if in_func:
            print(f"  L{i}: {line}")
        if in_func and line.strip() == "" and i > 25:
            break

# ── 저장 ─────────────────────────────────────────────────────
if content != original:
    TARGET.write_text(content, encoding="utf-8")
    print("\n✅ 패치 완료 →", TARGET)
else:
    print("\n[WARN] no changes")

print("   다음 실행: python sfd_investor_flow_fetch.py")
