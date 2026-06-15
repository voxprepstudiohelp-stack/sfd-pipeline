from __future__ import annotations

from datetime import datetime
from pathlib import Path
import pandas as pd

D_ROOT = Path(r"D:\AI_WorkSpace\I_SFC")
ROOT = D_ROOT / r"09_Implementation\SFC_DataPipeline"
INPUT = ROOT / r"inputs\sfd_user_approval_queue.csv"
OUTPUT = ROOT / r"outputs\latest\sfd_pending_approval_latest.csv"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(INPUT, encoding="utf-8-sig")
    df.insert(0, "created_at", datetime.now().isoformat(timespec="seconds"))
    df[df["status"].isin(["PENDING", "BLOCKED"])].to_csv(OUTPUT, index=False, encoding="utf-8-sig")
    print("OK pending approval")
    print(OUTPUT)


if __name__ == "__main__":
    main()
