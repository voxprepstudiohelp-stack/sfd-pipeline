# 파일명: run_sfd_v02_pipeline.py
# 버전: v0.3 (SESSION_BRIEF V5.3 기준 전면 재작성)
# 작성: Claude (Anthropic) — 2026.05.23
# 배포 경로: D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline\tools\run_sfd_v02_pipeline.py
#
# [v0.2 -> v0.3 변경사항]
# - 구버전 스크립트(collect_sfd_naver_news 등) 전부 제거
# - SESSION_BRIEF V5.3 기준 Layer 1~3 순차 실행 구조로 전면 재작성
# - 레이어별 SKIP(파일 없음) vs FAIL(에러) 분리 처리
# - 전체 결과 요약 로그 추가

from __future__ import annotations

import subprocess
import sys
import logging
from pathlib import Path
from datetime import datetime

D_ROOT = Path(r"D:\AI_WorkSpace\I_SFC")
ROOT   = D_ROOT / r"09_Implementation\SFC_DataPipeline"
TOOLS  = ROOT / "tools"
LOG_PATH = ROOT / "outputs" / "latest" / "run_pipeline.log"

LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(LOG_PATH), level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s", encoding="utf-8"
)

PIPELINE = [
    ("Layer 1",   "sfd_prev_close_fetch.py",       []),
    ("Layer 1.5", "sfd_news_fetcher.py",            []),
    ("Layer 1.6", "sfd_event_calendar_builder.py",  []),
    ("Layer 2",   "sfd_signal_aggregator.py",       []),
    ("Layer 2.5", "sfd_rerating_watch.py",          []),
    ("Layer 2.6", "sfd_fundamental_watch.py",       []),
    ("Layer 3",   "sfd_backtest_d1.py",             []),
]


def run(layer, script, args):
    path = TOOLS / script
    if not path.exists():
        msg = f"[SKIP] {layer} | {script} not found: {path}"
        print(msg); logging.warning(msg)
        return False
    cmd = [sys.executable, str(path), *args]
    print(f"\n{'='*60}\n[START] {layer} | {script}")
    logging.info(f"START {layer} | {script}")
    try:
        subprocess.run(cmd, cwd=str(ROOT), check=True)
        logging.info(f"OK    {layer} | {script}")
        print(f"[OK]   {layer} | {script}")
        return True
    except subprocess.CalledProcessError as e:
        msg = f"[FAIL] {layer} | {script} | returncode={e.returncode}"
        print(msg); logging.error(msg)
        return False


def main():
    start = datetime.now()
    logging.info(f"=== SFD Pipeline v0.3 START === {start.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"SFD Pipeline v0.3 | {start.strftime('%Y-%m-%d %H:%M:%S')}")

    results = {}
    for layer, script, args in PIPELINE:
        results[layer] = run(layer, script, args)

    elapsed = int((datetime.now() - start).total_seconds())
    ok_list = [k for k, v in results.items() if v]
    ng_list = [k for k, v in results.items() if not v]
    print(f"\n{'='*60}")
    print(f"[DONE] OK={len(ok_list)} | FAIL/SKIP={len(ng_list)} | elapsed={elapsed}s")
    if ng_list:
        print(f"  failed layers: {', '.join(ng_list)}")
    print(f"  LOG: {LOG_PATH}")
    logging.info(f"DONE | OK={len(ok_list)} FAIL={len(ng_list)} elapsed={elapsed}s")


if __name__ == "__main__":
    main()
