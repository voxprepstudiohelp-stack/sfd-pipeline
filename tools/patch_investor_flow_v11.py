# 파일명: patch_investor_flow_v11.py
# 작성자: Claude (Anthropic)
# 목적: sfd_investor_flow_fetch.py (GPT v1.1) 경로 오류 패치
#   - BASE_DIR parents[2] → MASTER_DIR/PIPE_DIR 분리
#   - company_master 경로: I_SFC\01_DB\
#   - outputs/inputs 경로: SFC_DataPipeline\

from pathlib import Path

TARGET = Path(
    r"D:\AI_WorkSpace\I_SFC\09_Implementation"
    r"\SFC_DataPipeline\tools\sfd_investor_flow_fetch.py"
)

content = TARGET.read_text(encoding="utf-8")

# ── 수정 1: BASE_DIR 분리 ──────────────────────────────────────
OLD = "BASE_DIR = Path(__file__).resolve().parents[2]"
NEW = (
    "MASTER_DIR = Path(__file__).resolve().parents[3]  # I_SFC\\\n"
    "BASE_DIR   = Path(__file__).resolve().parents[1]  # SFC_DataPipeline\\"
)

if OLD not in content:
    print(f"[WARN] pattern not found — manual check required:\n  {OLD}")
else:
    content = content.replace(OLD, NEW)
    print("[OK] BASE_DIR split patch DONE")

# ── 수정 2: company_master 경로 교체 ──────────────────────────
OLD2_CANDIDATES = [
    'BASE_DIR / "01_DB/company_master.csv"',
    "BASE_DIR / '01_DB/company_master.csv'",
    'BASE_DIR / "outputs/latest/sfd_stock_map_latest.csv"',
    "BASE_DIR / 'outputs/latest/sfd_stock_map_latest.csv'",
]
NEW2 = 'MASTER_DIR / "01_DB/company_master.csv"'

patched2 = False
for old2 in OLD2_CANDIDATES:
    if old2 in content:
        content = content.replace(old2, NEW2)
        print(f"[OK] company_master path replaced: {old2}")
        patched2 = True
        break

if not patched2:
    print("[WARN] company_master path pattern not found — check current code:")
    for i, line in enumerate(content.splitlines(), 1):
        if "master" in line.lower() or "stock_map" in line.lower() or "01_DB" in line:
            print(f"  L{i}: {line}")

# ── 수정 3: load_ticker_list 컬럼명 안전화 ────────────────────
# company_master CSV의 ticker 컬럼명이 다를 수 있으므로 안전 로드 삽입
OLD3 = 'return df["ticker"].astype(str).tolist()'
NEW3 = (
    '    # 컬럼명 유연 탐색 (ticker / 종목코드 등)\n'
    '    for col in ["ticker", "종목코드", "code", "Code"]:\n'
    '        if col in df.columns:\n'
    '            return df[col].astype(str).str.zfill(6).tolist()\n'
    '    print("[WARN] ticker 컬럼 탐지 실패:", list(df.columns))\n'
    '    return []'
)
if OLD3 in content:
    content = content.replace(OLD3, NEW3)
    print("[OK] ticker column flexible search patch DONE")
else:
    print("[WARN] ticker return pattern not found — manual check required")

# ── 저장 ──────────────────────────────────────────────────────
TARGET.write_text(content, encoding="utf-8")
print("\n✅ 패치 완료 →", TARGET)
print("   다음 실행: python sfd_investor_flow_fetch.py")
