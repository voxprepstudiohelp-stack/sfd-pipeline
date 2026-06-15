# patch_threshold_semi.py
# 용도: sfd_signal_aggregator.py THRESHOLD ORIGINAL(70/50) → SEMI(45/35) 패치
# 배경: investor_flow 3거래일 전 데이터 → 점수 분포 낮음 (max=76, mean=30.7)
#       RESERVE=2 과소 → SEMI 모드로 실용적 종목수 확보
# 실행: python tools\patch_threshold_semi.py
# 작성: Claude (Anthropic) 2026-05-25

import os

TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sfd_signal_aggregator.py")

with open(TARGET, "r", encoding="utf-8") as f:
    src = f.read()

# 백업
bak = TARGET.replace(".py", "_original_bak.py")
with open(bak, "w", encoding="utf-8") as f:
    f.write(src)
print(f"[BACKUP] {bak}")

# 패치: ORIGINAL(70/50) → SEMI(45/35)
src = src.replace('THRESHOLD_RESERVE = 70', 'THRESHOLD_RESERVE = 45')
src = src.replace('THRESHOLD_WATCH   = 50', 'THRESHOLD_WATCH   = 35')
src = src.replace('MODE = "ORIGINAL"',      'MODE = "SEMI"')

changed = sum([
    'THRESHOLD_RESERVE = 45' in src,
    'THRESHOLD_WATCH   = 35' in src,
    'MODE = "SEMI"'          in src,
])

if changed == 3:
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(src)
    print(f"[OK] THRESHOLD SEMI applied")
    print(f"     RESERVE=45 / WATCH=35 / MODE=SEMI")
    print(f"     예상 RESERVE: 30~40종목 / WATCH: 70~100종목")
    print(f"[파일] {TARGET}")
    print(f"[NOTE] Will revert to ORIGINAL(70/50) after investor_flow is normalized")
else:
    print(f"[WARN] Patch target not found ({changed}/3) — current THRESHOLD lines:")
    for i, line in enumerate(src.splitlines(), 1):
        if "THRESHOLD" in line or 'MODE = ' in line:
            print(f"  L{i}: {line}")
