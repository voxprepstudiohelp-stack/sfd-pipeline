from __future__ import annotations

from datetime import datetime
from pathlib import Path
import argparse
import pandas as pd

D_ROOT = Path(r"D:\AI_WorkSpace\I_SFC")
ROOT = D_ROOT / r"09_Implementation\SFC_DataPipeline"
IN = ROOT / "inputs"
OUT = ROOT / r"outputs\latest"
REPORT = ROOT / r"reports\latest\sfd_weekly_benchmark_report_latest.md"

SCORES = {
    "TradingView": 92,
    "Trade Ideas": 86,
    "Moneytoring": 82,
    "Koyfin": 78,
    "TrendSpider": 76,
    "AlphaSense": 74,
    "BlackRock Aladdin": 72,
    "Bitpass": 65,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="weekly")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    platforms = pd.read_csv(IN / "sfd_benchmark_platforms.csv", encoding="utf-8-sig")
    rows = []
    for _, r in platforms.iterrows():
        name = r.get("platform_name", "")
        score = SCORES.get(name, 60)
        if score >= 85:
            decision = "즉시 도입 후보"
        elif score >= 70:
            decision = "다음 버전 반영 후보"
        elif score >= 50:
            decision = "관찰"
        else:
            decision = "보류"
        rows.append({
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "mode": args.mode,
            "platform_name": name,
            "platform_type": r.get("platform_type", ""),
            "key_features": r.get("key_features", ""),
            "benchmark_use": r.get("benchmark_use", ""),
            "sfd_score": score,
            "decision": decision,
            "notes": r.get("notes", ""),
        })
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "sfd_benchmark_radar_latest.csv", index=False, encoding="utf-8-sig")

    md = f"""# SFD Weekly Benchmark Radar v0.2

- 생성시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} KST
- 모드: {args.mode}
- 목적: 새로운/강력한 유사 플랫폼을 정기 벤치마킹하여 SFD Evolution Loop에 반영

{df.to_markdown(index=False)}

## 원칙
- 자동 검색/정리/점수화는 SFD가 수행
- 핵심전략 변경, 비용 발생, 실매매는 사용자 승인 필요
"""
    REPORT.write_text(md, encoding="utf-8")
    print("OK benchmark radar")
    print(OUT / "sfd_benchmark_radar_latest.csv")
    print(REPORT)


if __name__ == "__main__":
    main()
