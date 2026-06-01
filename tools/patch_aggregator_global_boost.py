"""
patch_aggregator_global_boost.py
=================================
sfd_signal_aggregator.py v2.9 → v3.0 패치
변경: global_boost (Layer 0.5 글로벌 트리거) 통합

실행 위치: D:\\AI_WorkSpace\\I_SFC\\09_Implementation\\sfd-pipeline\\
실행 방법: python tools\\patch_aggregator_global_boost.py
작성: Claude (Anthropic) | 2026.06.01
"""

import os, re, sys, shutil
from pathlib import Path

BASE   = Path(__file__).parent.parent
TARGET = BASE / "tools" / "sfd_signal_aggregator.py"
BACKUP = BASE / "tools" / "sfd_signal_aggregator.py.bak_v2.9"

def main():
    if not TARGET.exists():
        print(f"[ERROR] 대상 파일 없음: {TARGET}"); sys.exit(1)

    src = TARGET.read_text(encoding="utf-8")

    # 이미 패치 적용 여부 확인
    if "GLOBAL_TRIGGER_CSV" in src:
        print("[SKIP] 이미 global_boost 패치 적용됨"); sys.exit(0)

    # ── 백업 ─────────────────────────────────────────────────────────────
    shutil.copy2(TARGET, BACKUP)
    print(f"[BACKUP] {BACKUP}")

    # ── 패치 1: 경로 상수 추가 ─────────────────────────────────────────
    src = re.sub(
        r'(TIMEOUT_STATE_JSON\s+=\s+os\.path\.join\([^)]+\)[^\n]*)',
        r'\1\nGLOBAL_TRIGGER_CSV  = os.path.join(LATEST_DIR, "sfd_global_trigger_latest.csv")  # Layer 0.5',
        src, count=1
    )
    print("[PATCH 1] GLOBAL_TRIGGER_CSV 경로 추가")

    # ── 패치 2: load_global_trigger_map 함수 추가 ──────────────────────
    NEW_FUNC = '''
# ── [Layer 0.5] global_trigger_map 로드 ────────────────────────────────────
def load_global_trigger_map() -> dict:
    """
    sfd_global_trigger_latest.csv 로드.
    반환: {ticker: {"boost_score": int, "signal": str, "trigger_source": str}}
    """
    if not os.path.exists(GLOBAL_TRIGGER_CSV):
        logging.info("[L0.5] global_trigger CSV 없음 -- 건너뜀")
        return {}
    try:
        df = pd.read_csv(GLOBAL_TRIGGER_CSV, encoding="utf-8-sig", dtype={"ticker": str})
        if "ticker" not in df.columns or "boost_score" not in df.columns:
            return {}
        df["ticker"] = df["ticker"].str.strip().str.zfill(6)
        result = {}
        for _, row in df.iterrows():
            t = str(row["ticker"])
            result[t] = {
                "boost_score":    int(row.get("boost_score", 0) or 0),
                "signal":         str(row.get("signal", "") or ""),
                "trigger_source": str(row.get("trigger_source", "") or ""),
            }
        logging.info(f"[L0.5] global_trigger_map: {len(result)}개 종목")
        return result
    except Exception as e:
        logging.warning(f"[L0.5] global_trigger_map 로드 실패: {e}")
        return {}

'''
    # load_timeout_state 앞에 삽입
    src = re.sub(
        r'(def load_timeout_state)',
        NEW_FUNC + r'\1',
        src, count=1
    )
    print("[PATCH 2] load_global_trigger_map 함수 추가")

    # ── 패치 3: main() 내 global_trigger_map 로드 ─────────────────────
    src = re.sub(
        r'(timeout_state\s+=\s+load_timeout_state\(\)[^\n]*)',
        r'\1\n    global_trigger_map = load_global_trigger_map()   # Layer 0.5',
        src, count=1
    )
    print("[PATCH 3] main()에 global_trigger_map 로드 추가")

    # ── 패치 4: zp_data 계산 직전에 global_boost 변수 초기화 ──────────
    src = re.sub(
        r'(\s+zp_data\s+=\s+zone_pullback_map\.get\(ticker)',
        (
            '\n        gb_data       = global_trigger_map.get(ticker, {})'
            '\n        global_boost  = int(gb_data.get("boost_score", 0))'
            '\n        global_src    = str(gb_data.get("trigger_source", ""))'
            '\n        global_sig    = str(gb_data.get("signal", ""))'
            '\n'
            r'\n        \g<0>'.replace(r'\g<0>', '')
            + '\n        zp_data       = zone_pullback_map.get(ticker'
        ),
        src, count=1
    )
    # 더 안전한 방식으로 재시도
    if 'global_boost' not in src:
        src = re.sub(
            r'(        zp_data\s+=\s+zone_pullback_map\.get\(ticker)',
            (
                '        gb_data       = global_trigger_map.get(ticker, {})\n'
                '        global_boost  = int(gb_data.get("boost_score", 0))\n'
                '        global_src    = str(gb_data.get("trigger_source", ""))\n'
                '        global_sig    = str(gb_data.get("signal", ""))\n\n'
                r'        \1'
            ),
            src, count=1
        )
    print("[PATCH 4] global_boost 변수 초기화 추가")

    # ── 패치 5: total 계산에 + global_boost 추가 ──────────────────────
    src = re.sub(
        r'(\+ bias_score \+ vs_score \+ zp_score\))',
        r'+ bias_score + vs_score + zp_score + global_boost)',
        src, count=1
    )
    print("[PATCH 5] total += global_boost 적용")

    # ── 패치 6: results.append에 컬럼 추가 ────────────────────────────
    src = re.sub(
        r'("tech_ver":\s+tech_ver,\s*\n(\s+)\})',
        (
            '"tech_ver":            tech_ver,\n'
            r'\2"global_boost":        global_boost,\n'
            r'\2"global_trigger_src":  global_src,\n'
            r'\2"global_trigger_sig":  global_sig,\n'
            r'\2}'
        ),
        src, count=1
    )
    print("[PATCH 6] results.append에 global 컬럼 추가")

    # ── 패치 7: 버전 헤더 v3.0 ────────────────────────────────────────
    src = src.replace("v2.9 START", "v3.0 START", 1)
    src = re.sub(r'(# sfd_signal_aggregator\.py \| v)2\.9', r'\g<1>3.0', src, count=1)
    print("[PATCH 7] 버전 v3.0 업데이트")

    # ── 저장 ──────────────────────────────────────────────────────────
    TARGET.write_text(src, encoding="utf-8")
    print(f"\n[OK] {TARGET}")
    print("     sfd_signal_aggregator v2.9 -> v3.0 패치 완료")
    print("     신규 컬럼: global_boost, global_trigger_src, global_trigger_sig")
    print("     스코어 아키텍처: max 190pt -> 210pt (+20 global_boost cap)")

if __name__ == "__main__":
    main()
