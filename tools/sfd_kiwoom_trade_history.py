"""
sfd_kiwoom_trade_history.py
키움 REST API 매매이력 자동 추출 모듈
SFD Pipeline 통합용 | v1.2 | 2026.06.10
"""

import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pathlib import Path

# ── 환경변수 로드 ──────────────────────────────────────────
ENV_PATH = Path(r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline\.env")
load_dotenv(ENV_PATH)

APPKEY     = os.getenv("KIWOOM_APP_KEY")
SECRETKEY  = os.getenv("KIWOOM_SECRET_KEY")
ACCOUNT_NO = os.getenv("KIWOOM_ACCOUNT_NO")   # 예: 6498-8566

BASE_URL   = "https://api.kiwoom.com"          # 실전투자

OUTPUT_DIR = Path(r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline\data\trade_history")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ── 1. 토큰 발급 ───────────────────────────────────────────
def get_token() -> str:
    url = f"{BASE_URL}/oauth2/token"
    payload = {
        "grant_type": "client_credentials",
        "appkey":     APPKEY,
        "secretkey":  SECRETKEY
    }
    res = requests.post(url, json=payload, timeout=10)
    res.raise_for_status()
    data  = res.json()
    token = data.get("token")
    if not token:
        raise ValueError(f"토큰 발급 실패: {data}")
    print(f"[TOKEN] 발급 완료 (만료: {data.get('expires_dt')})")
    return token


# ── 2. 체결내역 조회 (ka10076) ─────────────────────────────
def get_filled_orders(token: str, strt_dt: str, end_dt: str) -> list:
    """
    키움 REST API 헤더 규칙:
      - Authorization : Bearer {token}
      - api-id        : TR ID (ka10076)
      - cont-yn / next-key : 연속조회 시
    """
    url     = f"{BASE_URL}/api/dostk/acnt"
    acnt_no = ACCOUNT_NO.replace("-", "") if ACCOUNT_NO else ""

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json;charset=UTF-8",
        "api-id":        "ka10076",          # ← 핵심 수정
    }
    payload = {
        "acnt_no": acnt_no,
        "strt_dt": strt_dt,
        "end_dt":  end_dt,
        "qry_tp":  "0",
        "sell_tp": "0",     # 0=전체, 1=매수, 2=매도
    }

    all_records = []
    page        = 1

    while True:
        print(f"[FETCH] 페이지 {page} 요청 중...")
        res = requests.post(url, headers=headers, json=payload, timeout=15)
        res.raise_for_status()
        data = res.json()

        # 디버그
        print(f"  return_code={data.get('return_code')} / {data.get('return_msg')}")
        print(f"  응답 키: {list(data.keys())}")
        for k, v in data.items():
            if isinstance(v, list):
                print(f"  리스트 키='{k}' ({len(v)}건)")

        # 리스트 자동 탐색
        records = []
        for k, v in data.items():
            if isinstance(v, list):
                records = v
                break
        all_records.extend(records)

        # 연속조회 (헤더 기반)
        cont_yn  = res.headers.get("cont-yn",  "N")
        next_key = res.headers.get("next-key", "")
        if cont_yn != "Y" or not next_key:
            break

        headers["cont-yn"]  = "Y"
        headers["next-key"] = next_key
        page += 1

    print(f"[FETCH] 총 {len(all_records)}건 조회 완료 ({strt_dt}~{end_dt})")
    return all_records


# ── 3. DataFrame 정규화 ────────────────────────────────────
COLUMN_MAP = {
    "ord_dt":      "date",
    "stk_cd":      "ticker",
    "stk_nm":      "name",
    "buy_sell_tp": "side",
    "ccld_qty":    "qty",
    "ccld_uv":     "price",
    "ccld_amt":    "amount",
    "fee":         "fee",
    "rlzt_pfls":   "pnl",
    "ccld_tm":     "time",
}

def normalize(records: list) -> pd.DataFrame:
    if not records:
        print("[WARN] 조회된 체결내역 없음")
        return pd.DataFrame()

    df = pd.DataFrame(records)
    print(f"[DEBUG] 원본 컬럼: {list(df.columns)}")

    rename = {k: v for k, v in COLUMN_MAP.items() if k in df.columns}
    df = df.rename(columns=rename)

    if "side" in df.columns:
        df["side"] = df["side"].map({"1": "매수", "2": "매도"}).fillna(df["side"])

    for col in ["qty", "price", "amount", "fee", "pnl"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    if "date" in df.columns:
        df = df.sort_values("date", ascending=False).reset_index(drop=True)

    return df


# ── 4. CSV 저장 ────────────────────────────────────────────
def save_csv(df: pd.DataFrame, strt_dt: str, end_dt: str) -> Path:
    fname = OUTPUT_DIR / f"trade_history_{strt_dt}_{end_dt}.csv"
    df.to_csv(fname, index=False, encoding="utf-8-sig")
    print(f"[SAVE] {fname}")
    return fname


# ── 5. 메인 ───────────────────────────────────────────────
def run(strt_dt: str = None, end_dt: str = None):
    if end_dt is None:
        end_dt = datetime.today().strftime("%Y%m%d")
    if strt_dt is None:
        strt_dt = (datetime.today() - timedelta(days=30)).strftime("%Y%m%d")

    print(f"[START] 키움 매매이력 추출 | {strt_dt} ~ {end_dt}")
    print(f"[INFO]  계좌번호: {ACCOUNT_NO}")

    token   = get_token()
    records = get_filled_orders(token, strt_dt, end_dt)
    df      = normalize(records)

    if df.empty:
        print("[END] 저장할 데이터 없음")
        return None

    path = save_csv(df, strt_dt, end_dt)

    print("\n── 매매 요약 ──────────────────────────")
    if "side" in df.columns:
        print(df.groupby("side")["qty"].sum().to_string())
    if "pnl" in df.columns:
        print(f"총 실현손익: {df['pnl'].sum():,.0f}원")
    print(f"총 체결건수: {len(df)}건")
    print("────────────────────────────────────")
    return df


# ── CLI ────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3:
        run(sys.argv[1], sys.argv[2])
    else:
        run("20260101", datetime.today().strftime("%Y%m%d"))
