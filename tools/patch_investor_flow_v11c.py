# 파일명: patch_investor_flow_v11c.py
# 작성자: Claude (Anthropic)
# 목적: company_master 파일명 불일치 수정
#   company_master.csv → sfd_company_master_v1.4_sector_filled.csv

from pathlib import Path

TARGET = Path(
    r"D:\AI_WorkSpace\I_SFC\09_Implementation"
    r"\SFC_DataPipeline\tools\sfd_investor_flow_fetch.py"
)

content = TARGET.read_text(encoding="utf-8")
original = content

# ── 수정 1: 파일명 교체 ───────────────────────────────────────
OLD = 'company_file=MASTER_DIR/"01_DB/company_master.csv"'
NEW = 'company_file=MASTER_DIR/"01_DB/sfd_company_master_v1.4_sector_filled.csv"'

if OLD in content:
    content = content.replace(OLD, NEW)
    print("[OK] company_master filename replaced DONE")
else:
    print("[FAIL] pattern not found:", repr(OLD))
    # 현재 파일에서 01_DB 관련 행 출력
    for i, line in enumerate(content.splitlines(), 1):
        if "01_DB" in line or "company" in line.lower():
            print(f"  L{i}: {line}")

# ── 수정 2: ticker 컬럼 유연 탐색 ─────────────────────────────
# sfd_company_master의 ticker 컬럼명이 다를 수 있으므로 안전화
OLD2 = (
    '    df=pd.read_csv(company_file,dtype={"ticker":str})\n'
    '    return df["ticker"].astype(str).str.zfill(6).tolist()'
)
NEW2 = (
    '    df=pd.read_csv(company_file,dtype=str)\n'
    '    # ticker 컬럼 유연 탐색\n'
    '    for col in ["ticker","종목코드","code","Code","TICKER"]:\n'
    '        if col in df.columns:\n'
    '            return df[col].astype(str).str.zfill(6).tolist()\n'
    '    print("[WARN] ticker 컬럼 없음. 컬럼목록:", list(df.columns))\n'
    '    return []'
)

if OLD2 in content:
    content = content.replace(OLD2, NEW2)
    print("[OK] ticker column flexible search patch DONE")
else:
    print("[WARN] ticker return pattern mismatch — manual check:")
    for i, line in enumerate(content.splitlines(), 1):
        if "ticker" in line and ("read_csv" in line or "return" in line):
            print(f"  L{i}: {line}")

# ── 저장 ─────────────────────────────────────────────────────
if content != original:
    TARGET.write_text(content, encoding="utf-8")
    print("\n✅ 패치 완료 →", TARGET)
else:
    print("\n[WARN] no changes")

print("   다음 실행: python sfd_investor_flow_fetch.py")
