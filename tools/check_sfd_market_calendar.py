# -*- coding: utf-8 -*-
"""
SFD Market Calendar Guard v1.0

목적:
- 07:00 예약주문 루프 실행 전, 오늘이 거래 가능일인지 확인한다.
- 주말이면 실행 중단.
- config/krx_holidays.csv에 등록된 날짜이면 실행 중단.
- 아직 KRX 공식 휴장일 자동연동 전 단계의 안전 가드다.
"""

from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import csv
import sys


ROOT = Path(r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline")
CONFIG_DIR = ROOT / "config"
HOLIDAY_FILE = CONFIG_DIR / "krx_holidays.csv"

KST = ZoneInfo("Asia/Seoul")


def ensure_holiday_file():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if not HOLIDAY_FILE.exists():
        with open(HOLIDAY_FILE, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "market", "status", "reason"])
        print(f"[INFO] Holiday file created: {HOLIDAY_FILE}")


def load_holidays():
    ensure_holiday_file()

    holidays = {}

    with open(HOLIDAY_FILE, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            date = (row.get("date") or "").strip()
            status = (row.get("status") or "").strip().upper()
            reason = (row.get("reason") or "").strip()

            if not date:
                continue

            if status in ("CLOSED", "HOLIDAY", "NO_TRADE", "휴장"):
                holidays[date] = reason or "manual_holiday"

    return holidays


def main():
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    weekday = now.weekday()

    holidays = load_holidays()

    print("==========================================")
    print("SFD Market Calendar Guard")
    print("==========================================")
    print(f"Today: {today}")
    print(f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S KST')}")

    if weekday >= 5:
        print("[STOP] Today is a weekend. Stopping the 07:00 order loop.")
        print("SFD_MARKET_OPEN=NO")
        sys.exit(10)

    if today in holidays:
        print(f"[STOP] Today is a market holiday: {holidays[today]}")
        print("SFD_MARKET_OPEN=NO")
        sys.exit(11)

    print("[OK] Today is judged as a trading day.")
    print("SFD_MARKET_OPEN=YES")
    sys.exit(0)


if __name__ == "__main__":
    main()