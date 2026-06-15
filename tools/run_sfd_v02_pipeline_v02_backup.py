from __future__ import annotations

import subprocess
import sys
from pathlib import Path

D_ROOT = Path(r"D:\AI_WorkSpace\I_SFC")
ROOT = D_ROOT / r"09_Implementation\SFC_DataPipeline"
TOOLS = ROOT / "tools"


def run(script: str, *args: str) -> None:
    cmd = [sys.executable, str(TOOLS / script), *args]
    print("RUN", " ".join(cmd))
    subprocess.run(cmd, cwd=str(ROOT), check=True)


def main() -> None:
    run("collect_sfd_naver_news.py")
    run("build_sfd_chart_strategy_score.py")
    run("build_sfd_powerbi_latest_csv.py")
    run("run_sfd_benchmark_radar.py", "--mode", "weekly")
    run("build_sfd_pending_approval.py")
    print("SFD v0.2 pipeline complete")


if __name__ == "__main__":
    main()
