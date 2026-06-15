# patch_fundamental_v14.py
# 용도: sfd_fundamental_watch.py v1.4 apply_sector_priority 제거 패치
#       sector_injector v1.1이 post-processor 담당 → 중복 호출 불필요
# 실행: python tools\patch_fundamental_v14.py
# 작성: Claude (Anthropic) 2026-05-25

import os

TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sfd_fundamental_watch.py")

with open(TARGET, "r", encoding="utf-8") as f:
    src = f.read()

# SECTOR_PRIORITY_AVAILABLE = True → False 강제
src = src.replace(
    "SECTOR_PRIORITY_AVAILABLE = True",
    "SECTOR_PRIORITY_AVAILABLE = False  # v1.4: sector_injector post-processor 담당"
)

with open(TARGET, "w", encoding="utf-8") as f:
    f.write(src)

# 확인
if "SECTOR_PRIORITY_AVAILABLE = False" in src:
    print("[OK] Patch DONE — SECTOR_PRIORITY_AVAILABLE = False applied")
    print("     sector_injector v1.1 handles sector_major + adjusted_fund_score")
else:
    print("[WARN] Patch target not found — already applied or manual check required")
