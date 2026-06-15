from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"


def run(cmd: list[str]) -> None:
    print("RUN", " ".join(cmd))
    subprocess.run(cmd, cwd=str(ROOT), check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", default="0835", help="0730/0835/0930/1130/1330/1510/1610/2230")
    args = parser.parse_args()

    run([sys.executable, str(TOOLS / "collect_sfd_news_sources.py")])
    run([sys.executable, str(TOOLS / "build_sfd_report.py"), "--slot", args.slot])


if __name__ == "__main__":
    main()
