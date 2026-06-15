# -*- coding: utf-8 -*-
"""
SFD 07:00 Reservation Order Builder v1.2

목적:
- 08:35 실행표를 훼손하지 않고 07:00 예약주문 후보표를 별도 생성한다.
- NAVER 뉴스 수집 정상화 이후, 아침 07:00 예약주문 판단용 CSV를 만든다.
- 엑셀에서 종목코드 앞자리 0이 사라지는 문제를 방지하기 위해 '종목코드_표시' 컬럼을 추가한다.

입력:
- outputs/latest/sfd_0835_order_plan_latest.csv
- 없으면 outputs/sfd_0835_order_plan_latest.csv 사용

출력:
- outputs/latest/sfd_0700_reservation_order_latest.csv
- outputs/history/YYYYMMDD_HHMMSS_sfd_0700_reservation_order.csv
"""

from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import csv
import re


ROOT = Path(r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline")

INPUT_LATEST = ROOT / "outputs" / "latest" / "sfd_0835_order_plan_latest.csv"
INPUT_FALLBACK = ROOT / "outputs" / "sfd_0835_order_plan_latest.csv"

OUTPUT_LATEST = ROOT / "outputs" / "latest" / "sfd_0700_reservation_order_latest.csv"
HISTORY_DIR = ROOT / "outputs" / "history"

KST = ZoneInfo("Asia/Seoul")
NOW = datetime.now(KST)
CREATED_AT = NOW.strftime("%Y-%m-%dT%H:%M:%S%z")
HISTORY_FILE = HISTORY_DIR / f"{NOW.strftime('%Y%m%d_%H%M%S')}_sfd_0700_reservation_order.csv"


def clean_text(value):
    """빈 값 방지용 문자열 정리."""
    if value is None:
        return ""
    return str(value).strip()


def normalize_stock_code(value):
    """
    종목코드를 6자리 문자로 정규화한다.

    예:
    5930   -> 005930
    660    -> 000660
    1440   -> 001440
    024840 -> 024840
    """
    s = clean_text(value)

    # 엑셀이 만든 수식형 문자열이 들어올 가능성 방지
    s = s.replace('="', "").replace('"', "").strip()

    # 숫자만 추출
    digits = re.sub(r"\D", "", s)

    if not digits:
        return ""

    # 6자리보다 짧으면 앞에 0을 붙인다
    if len(digits) <= 6:
        return digits.zfill(6)

    # 혹시 너무 길면 마지막 6자리 사용
    return digits[-6:]


def excel_stock_code_display(stock_code):
    """
    엑셀에서 CSV를 바로 열어도 005930이 5930으로 깨지지 않게 표시용 컬럼을 만든다.
    CSV 안에는 ="005930" 형태로 들어간다.
    """
    if not stock_code:
        return ""
    return f'="{stock_code}"'


def parse_price(value, mode="first"):
    """
    가격 문자열을 안전하게 숫자로 변환한다.

    예:
    226,000원 -> 226000
    205,065~211,680원 -> 205065
    231,525 / 242,550원 -> 231525

    mode:
    - first: 첫 번째 숫자
    - min  : 여러 가격 중 가장 낮은 값
    - max  : 여러 가격 중 가장 높은 값
    - last : 마지막 숫자
    """
    if value is None:
        return None

    s = str(value).strip()
    if not s:
        return None

    matches = re.findall(r"-?\d[\d,]*(?:\.\d+)?", s)

    if not matches:
        return None

    nums = []

    for m in matches:
        try:
            n = float(m.replace(",", ""))
            if abs(n - round(n)) < 0.000001:
                n = int(round(n))
            nums.append(n)
        except ValueError:
            continue

    if not nums:
        return None

    if mode == "min":
        return min(nums)

    if mode == "max":
        return max(nums)

    if mode == "last":
        return nums[-1]

    return nums[0]


def first_present(row, *keys):
    """여러 후보 컬럼 중 처음으로 값이 있는 값을 반환한다."""
    for key in keys:
        value = clean_text(row.get(key))
        if value:
            return value
    return ""


def read_csv_header(path):
    """CSV 헤더만 빠르게 읽는다."""
    for enc in ("utf-8-sig", "cp949"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                reader = csv.reader(f)
                return next(reader, [])
        except UnicodeDecodeError:
            continue

    raise RuntimeError(f"CSV 인코딩을 읽을 수 없습니다: {path}")


def select_input_path():
    """
    기본 latest 경로는 유지하되, 현재 08:35 실행표 원본 형식이 fallback에만 있으면
    fallback을 우선 사용한다.
    """
    if INPUT_LATEST.exists():
        latest_header = set(read_csv_header(INPUT_LATEST))
        if {"buy_price_1", "buy_qty_1", "sell_price_1", "sell_qty_1"} & latest_header:
            return INPUT_LATEST

    if INPUT_FALLBACK.exists():
        fallback_header = set(read_csv_header(INPUT_FALLBACK))
        if {"buy_price_1", "buy_qty_1", "sell_price_1", "sell_qty_1"} & fallback_header:
            return INPUT_FALLBACK

    return INPUT_LATEST if INPUT_LATEST.exists() else INPUT_FALLBACK


def action_text(row):
    """주문 방향 판단에 필요한 주요 텍스트를 합친다."""
    return " ".join([
        first_present(row, "action_type", "구분"),
        first_present(row, "execution_signal", "실행 판단"),
        first_present(row, "final_signal", "sfd_signal"),
    ]).strip()


def order_side(row, decision):
    """매수/매도/관찰 중 예약수량을 채울 방향을 결정한다."""
    text = action_text(row)
    upper_text = text.upper()
    action = first_present(row, "action_type", "구분").upper()

    if decision.startswith("WATCH_ONLY") or decision == "RISK_BLOCK":
        return "watch"

    if any(word in action for word in ("CASH", "WATCH_NO_ADD", "WATCH_ONLY", "NO_NEW_BUY")):
        return "watch"

    if "BUY" in action or "매수" in text or "신규" in text or "대기" in text:
        return "buy"

    if any(word in action for word in ("SELL", "PROFIT")) or "매도" in text or "보유" in text:
        return "sell"

    if any(word in upper_text for word in ("CASH", "WATCH_NO_ADD", "WATCH_ONLY", "NO_NEW_BUY")):
        return "watch"

    if decision in ("RESERVE_BUY_A", "RESERVE_BUY_B", "RESERVE_REVIEW"):
        return "buy"

    if decision == "HOLD_SELL_REVIEW":
        return "sell"

    return "watch"


def reservation_quantities(row, decision, buy_qty, sell_qty, legacy_qty):
    """예약 매수/매도 수량을 분리한다."""
    side = order_side(row, decision)

    if side == "buy":
        qty = buy_qty if buy_qty is not None else legacy_qty
        return (0 if qty is None else qty, 0)

    if side == "sell":
        qty = sell_qty if sell_qty is not None else legacy_qty
        return (0, 0 if qty is None else qty)

    return (0, 0)


def read_csv(path):
    """utf-8-sig 우선, 실패 시 cp949로 읽는다."""
    for enc in ("utf-8-sig", "cp949"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue

    raise RuntimeError(f"CSV 인코딩을 읽을 수 없습니다: {path}")


def decide_reservation(row, buy_price, sell_price, buy_qty, sell_qty, chart_score):
    """
    07:00 예약판단 생성.
    실제 자동주문이 아니라 사람이 아침에 확인할 후보 분류다.
    """
    kind = first_present(row, "구분", "action_type")
    exec_judgment = first_present(row, "실행 판단", "execution_signal", "final_signal")
    risk = first_present(row, "리스크", "risk", "data_memo")

    merged = f"{kind} {exec_judgment} {risk}"
    upper_merged = merged.upper()

    risk_block_words = [
        "RISK_BLOCK",
        "투자주의",
        "투자경고",
        "관리종목",
        "시장관리",
        "거래정지",
        "상장폐지",
        "불성실",
    ]

    if any(word in merged for word in risk_block_words):
        return "RISK_BLOCK"

    if any(word in upper_merged for word in ("CASH", "WATCH_NO_ADD", "WATCH_ONLY", "NO_NEW_BUY")):
        return "WATCH_ONLY_관찰전용"

    primary_action = first_present(row, "action_type", "구분")
    upper_primary_action = primary_action.upper()

    if "BUY" not in upper_primary_action and (
        any(word in upper_merged for word in ("SELL", "PROFIT")) or "매도" in merged or "보유" in merged
    ):
        if sell_price is None:
            return "WATCH_ONLY_매도가확인"
        if sell_qty is None or sell_qty <= 0:
            return "WATCH_ONLY_매도수량확인"
        return "HOLD_SELL_REVIEW"

    if buy_price is None:
        return "WATCH_ONLY_진입가확인"

    if buy_qty is None or buy_qty <= 0:
        return "WATCH_ONLY_수량확인"

    # 계좌 규모 보호용: 고가주는 실제 매수보다 나침반 역할 우선
    if buy_price >= 300000:
        return "WATCH_ONLY_고가주"

    if "신규" in kind or "매수" in exec_judgment or "대기" in kind or "BUY" in upper_merged:
        if chart_score is not None and chart_score >= 70:
            return "RESERVE_BUY_A"
        if chart_score is not None and chart_score >= 60:
            return "RESERVE_BUY_B"
        return "RESERVE_REVIEW"

    if "매도" in exec_judgment or "보유" in kind:
        return "HOLD_SELL_REVIEW"

    return "REVIEW"


def order_type(decision):
    """예약판단을 사람이 읽는 주문유형으로 변환."""
    if decision in ("RESERVE_BUY_A", "RESERVE_BUY_B"):
        return "지정가_예약매수_후보"

    if decision == "RESERVE_REVIEW":
        return "예약검토"

    if decision.startswith("WATCH_ONLY"):
        return "관찰전용"

    if decision == "RISK_BLOCK":
        return "주문금지"

    if decision == "HOLD_SELL_REVIEW":
        return "보유_매도검토"

    return "검토"


def main():
    input_path = select_input_path()

    if not input_path.exists():
        raise FileNotFoundError(f"입력 파일이 없습니다: {input_path}")

    rows = read_csv(input_path)

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_LATEST.parent.mkdir(parents=True, exist_ok=True)

    out_rows = []

    for row in rows:
        stock_code = normalize_stock_code(first_present(row, "종목코드", "stock_code"))

        prev_close = parse_price(first_present(row, "어제 종가", "prev_close"), mode="first")
        current_price = parse_price(first_present(row, "현재가", "prev_close_or_current"), mode="first")

        # 진입가는 범위가 있으면 보수적으로 낮은 가격을 사용
        buy_price = parse_price(first_present(row, "buy_price_1", "목표 진입가"), mode="min")

        # 매도가는 범위가 있으면 1차 목표가로 낮은 가격을 사용
        sell_price = parse_price(first_present(row, "sell_price_1", "목표 매도가"), mode="min")

        qty = parse_price(row.get("수량"), mode="first")
        buy_qty = parse_price(first_present(row, "buy_qty_1", "수량"), mode="first")
        sell_qty = parse_price(first_present(row, "sell_qty_1", "수량"), mode="first")
        chart_score = parse_price(row.get("차트점수"), mode="first")

        gap_pct = ""
        if prev_close and buy_price:
            gap_pct = round((buy_price - prev_close) / prev_close * 100, 2)

        decision = decide_reservation(row, buy_price, sell_price, buy_qty, sell_qty, chart_score)
        reserve_buy_qty, reserve_sell_qty = reservation_quantities(row, decision, buy_qty, sell_qty, qty)

        out_rows.append({
            "created_at": CREATED_AT,
            "기준시각": "07:00_KST",
            "기준구분": first_present(row, "구분", "action_type"),
            "종목명": first_present(row, "종목명", "corp_name_kr", "corp_name"),
            "종목코드": stock_code,
            "종목코드_표시": excel_stock_code_display(stock_code),
            "기준전일종가_원": "" if prev_close is None else prev_close,
            "0835현재가_원": "" if current_price is None else current_price,
            "예약매수가_원": "" if buy_price is None else buy_price,
            "예약매수수량": reserve_buy_qty,
            "예약매도가_원": "" if sell_price is None else sell_price,
            "예약매도수량": reserve_sell_qty,
            "예약수량": "" if qty is None else qty,
            "차트점수": "" if chart_score is None else chart_score,
            "전일종가대비_예약괴리율_pct": gap_pct,
            "예약판단": decision,
            "주문유형": order_type(decision),
            "특장점": first_present(row, "특장점", "execution_reason"),
            "리스크": first_present(row, "리스크", "data_memo"),
            "상승_하락_원인": first_present(row, "상승/하락 원인", "price_change_direction", "price_direction_basis"),
            "source_file": str(input_path),
        })

    fieldnames = [
        "created_at",
        "기준시각",
        "기준구분",
        "종목명",
        "종목코드",
        "종목코드_표시",
        "기준전일종가_원",
        "0835현재가_원",
        "예약매수가_원",
        "예약매수수량",
        "예약매도가_원",
        "예약매도수량",
        "예약수량",
        "차트점수",
        "전일종가대비_예약괴리율_pct",
        "예약판단",
        "주문유형",
        "특장점",
        "리스크",
        "상승_하락_원인",
        "source_file",
    ]

    for path in (OUTPUT_LATEST, HISTORY_FILE):
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(out_rows)

    print(f"OK 07:00 reservation rows={len(out_rows)}")
    print(OUTPUT_LATEST)
    print(HISTORY_FILE)


if __name__ == "__main__":
    main()
