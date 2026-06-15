# patch_threshold_v23.py
# 용도: sfd_signal_aggregator.py THRESHOLD TEMP → ORIGINAL 패치
# 실행: python tools\patch_threshold_v23.py
# 작성: Claude (Anthropic) 2026-05-25

import os

TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sfd_signal_aggregator.py")

with open(TARGET, "r", encoding="utf-8") as f:
    src = f.read()

# 백업
bak = TARGET.replace(".py", "_temp_bak.py")
with open(bak, "w", encoding="utf-8") as f:
    f.write(src)
print(f"[BACKUP] {bak}")

# 패치
before = src
src = src.replace('THRESHOLD_RESERVE = 30', 'THRESHOLD_RESERVE = 70')
src = src.replace('THRESHOLD_WATCH   = 20', 'THRESHOLD_WATCH   = 50')
src = src.replace('MODE = "TEMP"',          'MODE = "ORIGINAL"')

changed = sum([
    'THRESHOLD_RESERVE = 70' in src,
    'THRESHOLD_WATCH   = 50' in src,
    'MODE = "ORIGINAL"'      in src,
])

if changed == 3:
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(src)
    print(f"[OK] THRESHOLD 정상화 완료 (RESERVE=70 / WATCH=50 / MODE=ORIGINAL)")
    print(f"[파일] {TARGET}")
else:
    print(f"[WARN] Patch target not found ({changed}/3) — already applied or check file structure")
    print("Current THRESHOLD-related lines:")
    for i, line in enumerate(src.splitlines(), 1):
        if "THRESHOLD" in line or "MODE" in line:
            print(f"  L{i}: {line}")
