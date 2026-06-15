# 파일명: patch_investor_flow_v11b.py
# 작성자: Claude (Anthropic)
# 목적: sfd_investor_flow_fetch.py BASE_DIR 경로 오류 수정
#   parents[2]=09_Implementation → MASTER_DIR/PIPE_DIR 분리

from pathlib import Path

TARGET = Path(
    r"D:\AI_WorkSpace\I_SFC\09_Implementation"
    r"\SFC_DataPipeline\tools\sfd_investor_flow_fetch.py"
)

content = TARGET.read_text(encoding="utf-8")
original = content

# ── 수정 1: BASE_DIR 단일 → MASTER_DIR / PIPE_DIR 분리 ────────
OLD = "BASE_DIR=Path(__file__).resolve().parents[2]"
NEW = (
    "MASTER_DIR=Path(__file__).resolve().parents[3]  # I_SFC\\\n"
    "PIPE_DIR  =Path(__file__).resolve().parents[1]  # SFC_DataPipeline\\"
)
if OLD in content:
    content = content.replace(OLD, NEW)
    print("[OK] BASE_DIR split DONE")
else:
    print("[FAIL] BASE_DIR pattern not found:", repr(OLD))

# ── 수정 2: PIPE_DIR 경로 3개 교체 ───────────────────────────
replacements = [
    (
        'LATEST_PATH=BASE_DIR/"outputs/latest/sfd_investor_flow_latest.csv"',
        'LATEST_PATH=PIPE_DIR/"outputs/latest/sfd_investor_flow_latest.csv"'
    ),
    (
        'HISTORY_DIR=BASE_DIR/"outputs/history"',
        'HISTORY_DIR=PIPE_DIR/"outputs/history"'
    ),
    (
        'INPUT_PATH=BASE_DIR/"inputs/sfd_investor_flow_input.csv"',
        'INPUT_PATH=PIPE_DIR/"inputs/sfd_investor_flow_input.csv"'
    ),
]
for old, new in replacements:
    if old in content:
        content = content.replace(old, new)
        print(f"[OK] {old[:40]}...")
    else:
        print(f"[WARN] pattern not found: {old[:40]}...")

# ── 수정 3: company_file MASTER_DIR 교체 ─────────────────────
OLD3 = 'company_file=BASE_DIR/"01_DB/company_master.csv"'
NEW3 = 'company_file=MASTER_DIR/"01_DB/company_master.csv"'
if OLD3 in content:
    content = content.replace(OLD3, NEW3)
    print("[OK] company_master path replaced DONE")
else:
    print("[FAIL] company_master pattern not found:", repr(OLD3))

# ── 저장 ─────────────────────────────────────────────────────
if content != original:
    TARGET.write_text(content, encoding="utf-8")
    print("\n✅ 패치 완료 →", TARGET)
else:
    print("\n[WARN] no changes — re-check file content")

print("   다음 실행: python sfd_investor_flow_fetch.py")
