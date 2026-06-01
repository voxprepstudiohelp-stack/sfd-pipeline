# 파일명: run_sfd_v02_pipeline.py
# 버전: v0.7
# 작성: Claude (Anthropic) — 2026.06.01
# 변경점 v0.6 → v0.7:
#   - Layer 0.5 (sfd_global_trigger.py) 신규 추가 — 선행 글로벌 트리거 감지
#   - "뒷북" → "한 발 앞서" 전환의 핵심 레이어
#   - Layer 0.5는 Layer 1 이전 최우선 실행

from __future__ import annotations

import subprocess
import sys
import logging
from pathlib import Path
from datetime import datetime

D_ROOT   = Path(r"D:\AI_WorkSpace\I_SFC")
ROOT     = D_ROOT / r"09_Implementation\SFC_DataPipeline"
TOOLS    = ROOT / "tools"
LOG_PATH = ROOT / "outputs" / "latest" / "run_pipeline.log"

LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(LOG_PATH), level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s", encoding="utf-8"
)

# ── 파이프라인 정의 (v0.7 — Layer 0.5 선행 추가) ──────────────────────────
PIPELINE: list[tuple[str, str, list]] = [
    ("Layer 0.5",  "sfd_global_trigger.py",           []),   # NEW v0.7 — 미국→KR 선행 트리거
    ("Layer 1",    "sfd_prev_close_fetch.py",          []),
    ("Layer 1.5",  "sfd_news_fetcher.py",              []),
    ("Layer 1.6",  "sfd_event_calendar_builder.py",    []),
    ("Layer 2",    "sfd_signal_aggregator.py",         []),
    ("Layer 2.5",  "sfd_rerating_watch.py",            []),
    ("Layer 2.6",  "sfd_fundamental_watch.py",         []),
    ("Layer 2.6b", "sfd_sector_injector.py",           []),
    ("Layer 3",    "sfd_backtest_d1.py",               []),
    ("Layer 4",    "sfd_finalize.py",                  []),
    ("Layer 5",    "sfd_portfolio_monitor.py",         []),
    ("Layer 5.5",  "sfd_trade_guardian.py",            []),
]


def run(layer: str, script: str, args: list) -> str:
    """Returns: 'OK' | 'SKIP' | 'FAIL'"""
    path = TOOLS / script
    if not path.exists():
        msg = f"[SKIP] {layer} | {script} 파일 없음: {path}"
        print(msg); logging.warning(msg)
        return "SKIP"

    cmd = [sys.executable, str(path), *args]
    sep = "=" * 60
    print(f"\n{sep}\n[START] {layer} | {script}")
    logging.info(f"START {layer} | {script}")

    try:
        subprocess.run(cmd, cwd=str(ROOT), check=True)
        logging.info(f"OK    {layer} | {script}")
        print(f"[OK]   {layer} | {script}")
        return "OK"
    except subprocess.CalledProcessError as e:
        msg = f"[FAIL] {layer} | {script} | returncode={e.returncode}"
        print(msg); logging.error(msg)
        return "FAIL"


def main() -> None:
    start  = datetime.now()
    header = f"=== SFD Pipeline v0.7 시작 === {start.strftime('%Y-%m-%d %H:%M:%S')}"
    print(header); logging.info(header)

    results: dict[str, str] = {}
    for layer, script, args in PIPELINE:
        results[layer] = run(layer, script, args)

    elapsed   = int((datetime.now() - start).total_seconds())
    ok_list   = [k for k, v in results.items() if v == "OK"]
    skip_list = [k for k, v in results.items() if v == "SKIP"]
    fail_list = [k for k, v in results.items() if v == "FAIL"]

    sep = "=" * 60
    print(f"\n{sep}")
    print(f"[DONE] OK={len(ok_list)} | SKIP={len(skip_list)} | FAIL={len(fail_list)} | 경과={elapsed}s")
    if skip_list: print(f"  SKIP: {', '.join(skip_list)}")
    if fail_list: print(f"  FAIL: {', '.join(fail_list)}")
    print(f"  LOG: {LOG_PATH}")

    logging.info(f"DONE | OK={len(ok_list)} SKIP={len(skip_list)} FAIL={len(fail_list)} elapsed={elapsed}s")
    if fail_list: logging.warning(f"FAIL: {fail_list}")


if __name__ == "__main__":
    main()
