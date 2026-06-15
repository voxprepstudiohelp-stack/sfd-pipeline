# 파일명: patch_investor_flow_v11d.py
# 작성자: Claude (Anthropic)
# 목적:
#   1. ticker 컬럼 → stock_code 추가
#   2. rows 빈 상태에서 input_df 접근 오류 방지

from pathlib import Path

TARGET = Path(
    r"D:\AI_WorkSpace\I_SFC\09_Implementation"
    r"\SFC_DataPipeline\tools\sfd_investor_flow_fetch.py"
)

content = TARGET.read_text(encoding="utf-8")
original = content

# ── 수정 1: stock_code 컬럼 추가 ─────────────────────────────
OLD = (
    '    for col in ["ticker","종목코드","code","Code","TICKER"]:\n'
    '        if col in df.columns:\n'
    '            return df[col].astype(str).str.zfill(6).tolist()\n'
    '    print("[WARN] ticker 컬럼 없음. 컬럼목록:", list(df.columns))\n'
    '    return []'
)
NEW = (
    '    for col in ["stock_code","ticker","종목코드","code","Code","TICKER"]:\n'
    '        if col in df.columns:\n'
    '            return df[col].astype(str).str.zfill(6).tolist()\n'
    '    print("[WARN] ticker 컬럼 없음. 컬럼목록:", list(df.columns))\n'
    '    return []'
)
if OLD in content:
    content = content.replace(OLD, NEW)
    print("[OK] stock_code column added DONE")
else:
    print("[FAIL] column search pattern not found")

# ── 수정 2: 빈 rows 방어 — input_df 생성 전 체크 ─────────────
OLD2 = (
    '    input_df=df[["ticker","foreign_net_buy","institution_net_buy","individual_net_buy"]]\n'
    '    input_df.to_csv(INPUT_PATH,index=False,encoding="utf-8-sig")'
)
NEW2 = (
    '    if df.empty or "ticker" not in df.columns:\n'
    '        print("[WARN] 수집 결과 없음 — input 저장 생략")\n'
    '    else:\n'
    '        input_df=df[["ticker","foreign_net_buy","institution_net_buy","individual_net_buy"]]\n'
    '        input_df.to_csv(INPUT_PATH,index=False,encoding="utf-8-sig")'
)
if OLD2 in content:
    content = content.replace(OLD2, NEW2)
    print("[OK] empty rows guard patch DONE")
else:
    print("[FAIL] input_df pattern not found — current code:")
    for i, line in enumerate(content.splitlines(), 1):
        if "input_df" in line:
            print(f"  L{i}: {line}")

# ── 저장 ─────────────────────────────────────────────────────
if content != original:
    TARGET.write_text(content, encoding="utf-8")
    print("\n✅ 패치 완료 →", TARGET)
else:
    print("\n[WARN] no changes")

print("   다음 실행: python sfd_investor_flow_fetch.py")
