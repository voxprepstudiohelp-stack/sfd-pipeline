"""
sfd_kiwoom_portfolio.py
키움 REST API 포트폴리오 모니터링 + 거미줄 매매 트리거
SFD Pipeline 통합용 | v1.0 | 2026.06.10

기능:
  1. 보유잔고 + 평가현황 (kt00004, kt00005)
  2. 기간별 실현손익 (ka10073)
  3. 당일 체결내역 (ka10076)
  4. 거미줄 매매 트리거 (-20% 하락 시 추가매수 알림)
  5. SFD 기술지표 연동 (sfd_technical_analyzer 스코어)
"""

import os
import sys
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pathlib import Path

# ── 환경변수 ───────────────────────────────────────────────
ENV_PATH = Path(r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline\.env")
load_dotenv(ENV_PATH)

APPKEY    = os.getenv("KIWOOM_APP_KEY")
SECRETKEY = os.getenv("KIWOOM_SECRET_KEY")
BASE_URL  = "https://api.kiwoom.com"

# 거미줄 매매 설정
GRID_THRESHOLD = -0.20   # -20% 트리거
GRID_QTY       = 1       # 추가매수 수량

OUTPUT_DIR = Path(r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline\data\portfolio")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ══════════════════════════════════════════════════════════
# 1. 인증
# ══════════════════════════════════════════════════════════
def get_token() -> str:
    res = requests.post(f"{BASE_URL}/oauth2/token", json={
        "grant_type": "client_credentials",
        "appkey": APPKEY,
        "secretkey": SECRETKEY
    }, timeout=10)
    res.raise_for_status()
    data = res.json()
    token = data.get("token")
    if not token:
        raise ValueError(f"토큰 발급 실패: {data}")
    print(f"[TOKEN] 발급 완료 (만료: {data.get('expires_dt')})")
    return token


def _post(token: str, api_id: str, body: dict,
          cont_yn: str = "N", next_key: str = "") -> dict:
    """공통 POST 요청"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json;charset=UTF-8",
        "api-id":        api_id,
        "cont-yn":       cont_yn,
        "next-key":      next_key,
    }
    res = requests.post(
        f"{BASE_URL}/api/dostk/acnt",
        headers=headers, json=body, timeout=15
    )
    res.raise_for_status()
    return res.json(), res.headers


# ══════════════════════════════════════════════════════════
# 2. 계좌 평가현황 (kt00004)
# ══════════════════════════════════════════════════════════
def get_account_evaluation(token: str) -> dict:
    """계좌 평가현황 — 보유종목 avg_prc, cur_prc, pl_rt 포함"""
    data, _ = _post(token, "kt00004", {
        "qry_tp": "0",        # 0=전체
        "dmst_stex_tp": "KRX"
    })
    if data.get("return_code") != 0:
        print(f"[WARN] kt00004: {data.get('return_msg')}")
    return data


# ══════════════════════════════════════════════════════════
# 3. 체결잔고 (kt00005)
# ══════════════════════════════════════════════════════════
def get_filled_position(token: str) -> dict:
    """체결잔고 — buy_uv(매입단가), cur_prc, evltv_prft, pl_rt"""
    data, _ = _post(token, "kt00005", {"dmst_stex_tp": "KRX"})
    if data.get("return_code") != 0:
        print(f"[WARN] kt00005: {data.get('return_msg')}")
    return data


# ══════════════════════════════════════════════════════════
# 4. 기간별 실현손익 (ka10073)
# ══════════════════════════════════════════════════════════
def get_realized_pnl(token: str, ticker: str,
                     strt_dt: str, end_dt: str) -> list:
    """종목별 기간 실현손익"""
    all_records = []
    cont_yn, next_key = "N", ""
    while True:
        data, hdrs = _post(token, "ka10073", {
            "stk_cd":  ticker,
            "strt_dt": strt_dt,
            "end_dt":  end_dt,
        }, cont_yn, next_key)
        records = data.get("dt_stk_rlzt_pl", [])
        all_records.extend(records)
        cont_yn  = hdrs.get("cont-yn", "N")
        next_key = hdrs.get("next-key", "")
        if cont_yn != "Y":
            break
    return all_records


# ══════════════════════════════════════════════════════════
# 5. 당일 체결내역 (ka10076)
# ══════════════════════════════════════════════════════════
def get_today_filled(token: str) -> list:
    """당일 전체 체결내역"""
    all_records = []
    cont_yn, next_key = "N", ""
    while True:
        data, hdrs = _post(token, "ka10076", {
            "qry_tp":  "0",   # 전체
            "sell_tp": "0",   # 매수+매도
            "stex_tp": "0",   # 통합
        }, cont_yn, next_key)
        records = data.get("cntr", [])
        all_records.extend(records)
        cont_yn  = hdrs.get("cont-yn", "N")
        next_key = hdrs.get("next-key", "")
        if cont_yn != "Y":
            break
    return all_records


# ══════════════════════════════════════════════════════════
# 6. 거미줄 매매 트리거
# ══════════════════════════════════════════════════════════
def check_grid_trigger(holdings: list) -> list:
    """
    보유종목 중 마지막 매입단가 대비 현재가 -20% 이하 종목 탐지
    holdings: kt00004의 stk_acnt_evlt_prst 리스트
    """
    triggers = []
    for h in holdings:
        ticker   = h.get("stk_cd", "")
        name     = h.get("stk_nm", "")
        avg_prc  = float(h.get("avg_prc", 0) or 0)
        cur_prc  = float(h.get("cur_prc", 0) or 0)
        rmnd_qty = int(h.get("rmnd_qty", 0) or 0)

        if avg_prc <= 0 or cur_prc <= 0:
            continue

        chg_rate = (cur_prc - avg_prc) / avg_prc   # 등락률

        if chg_rate <= GRID_THRESHOLD:
            target_prc = cur_prc  # 현재가로 매수
            triggers.append({
                "ticker":    ticker,
                "name":      name,
                "avg_prc":   avg_prc,
                "cur_prc":   cur_prc,
                "chg_rate":  round(chg_rate * 100, 2),
                "rmnd_qty":  rmnd_qty,
                "add_qty":   GRID_QTY,
                "target_prc": target_prc,
                "action":    f"⚠️ 거미줄 매수 알림: {name}({ticker}) "
                             f"평균단가 {avg_prc:,.0f}원 → 현재가 {cur_prc:,.0f}원 "
                             f"({chg_rate*100:.1f}%) | 추가 {GRID_QTY}주 매수 고려"
            })

    return triggers


# ══════════════════════════════════════════════════════════
# 7. SFD 기술지표 연동 (선택)
# ══════════════════════════════════════════════════════════
def get_sfd_scores(tickers: list) -> dict:
    """
    SFD 최신 신호 파일에서 보유종목 스코어 조회
    outputs/latest/signal_output.csv 기반
    """
    signal_path = Path(r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline\outputs\latest\signal_output.csv")
    if not signal_path.exists():
        print(f"[WARN] SFD 신호 파일 없음: {signal_path}")
        return {}

    try:
        df = pd.read_csv(signal_path, dtype=str)
        # 티커 컬럼 자동 탐색
        ticker_col = next((c for c in df.columns
                           if c.lower() in ["ticker", "종목코드", "stk_cd"]), None)
        score_col  = next((c for c in df.columns
                           if c.lower() in ["score", "total_score", "신호점수"]), None)
        if not ticker_col:
            print("[WARN] SFD 신호 파일에서 티커 컬럼 못 찾음")
            return {}
        result = {}
        for t in tickers:
            row = df[df[ticker_col] == t]
            if not row.empty and score_col:
                result[t] = float(row.iloc[0][score_col])
        return result
    except Exception as e:
        print(f"[WARN] SFD 신호 로드 실패: {e}")
        return {}


# ══════════════════════════════════════════════════════════
# 8. 통합 리포트
# ══════════════════════════════════════════════════════════
def run_portfolio_report(strt_dt: str = None, end_dt: str = None):
    today = datetime.today().strftime("%Y%m%d")
    if end_dt is None:
        end_dt = today
    if strt_dt is None:
        strt_dt = (datetime.today() - timedelta(days=30)).strftime("%Y%m%d")

    print("=" * 60)
    print(f"  SFD 포트폴리오 리포트  |  {strt_dt} ~ {end_dt}")
    print("=" * 60)

    token = get_token()

    # ── 계좌 평가 ──────────────────────────────────────────
    print("\n[1] 계좌 평가현황")
    eval_data = get_account_evaluation(token)
    print(f"  총평가금액  : {eval_data.get('tot_est_amt','N/A'):>15}")
    print(f"  당일손익    : {eval_data.get('tdy_lspft_amt','N/A'):>15}")
    print(f"  당일수익률  : {eval_data.get('tdy_lspft_rt','N/A'):>15}")
    print(f"  누적손익    : {eval_data.get('lspft_amt','N/A'):>15}")
    print(f"  누적수익률  : {eval_data.get('lspft_rt','N/A'):>15}")

    holdings = eval_data.get("stk_acnt_evlt_prst", [])

    # ── 보유종목 테이블 ────────────────────────────────────
    print(f"\n[2] 보유종목 ({len(holdings)}개)")
    if holdings:
        tickers = [h.get("stk_cd","") for h in holdings]
        sfd_scores = get_sfd_scores(tickers)

        rows = []
        for h in holdings:
            ticker = h.get("stk_cd","")
            rows.append({
                "종목코드": ticker,
                "종목명":   h.get("stk_nm",""),
                "보유수량": h.get("rmnd_qty",""),
                "평균단가": h.get("avg_prc",""),
                "현재가":   h.get("cur_prc",""),
                "평가손익": h.get("pl_amt",""),
                "수익률(%)": h.get("pl_rt",""),
                "SFD점수":  sfd_scores.get(ticker, "-"),
            })
        df_h = pd.DataFrame(rows)
        print(df_h.to_string(index=False))

        # ── 거미줄 매매 트리거 ─────────────────────────────
        print("\n[3] 거미줄 매매 트리거 (평균단가 대비 -20% 이하)")
        triggers = check_grid_trigger(holdings)
        if triggers:
            for t in triggers:
                print(f"  {t['action']}")
        else:
            print("  현재 트리거 없음")

        # ── 기간 실현손익 ──────────────────────────────────
        print(f"\n[4] 기간별 실현손익 ({strt_dt}~{end_dt})")
        all_pnl = []
        for ticker in tickers:
            records = get_realized_pnl(token, ticker, strt_dt, end_dt)
            all_pnl.extend(records)

        if all_pnl:
            df_pnl = pd.DataFrame(all_pnl)
            if "tdy_sel_pl" in df_pnl.columns:
                df_pnl["tdy_sel_pl"] = pd.to_numeric(
                    df_pnl["tdy_sel_pl"], errors="coerce").fillna(0)
                total_pnl = df_pnl["tdy_sel_pl"].sum()
                print(f"  총 실현손익: {total_pnl:,.0f}원 ({len(df_pnl)}건)")
                # CSV 저장
                pnl_path = OUTPUT_DIR / f"realized_pnl_{strt_dt}_{end_dt}.csv"
                df_pnl.to_csv(pnl_path, index=False, encoding="utf-8-sig")
                print(f"  저장: {pnl_path}")
        else:
            print("  실현손익 데이터 없음")

    # ── 당일 체결 ──────────────────────────────────────────
    print("\n[5] 당일 체결내역")
    filled = get_today_filled(token)
    if filled:
        df_f = pd.DataFrame(filled)
        print(f"  체결건수: {len(df_f)}건")
        show_cols = [c for c in ["stk_nm","io_tp_nm","ord_pric","cntr_pric",
                                  "cntr_qty","ord_stt"] if c in df_f.columns]
        if show_cols:
            print(df_f[show_cols].to_string(index=False))
        filled_path = OUTPUT_DIR / f"today_filled_{today}.csv"
        df_f.to_csv(filled_path, index=False, encoding="utf-8-sig")
        print(f"  저장: {filled_path}")
    else:
        print("  당일 체결 없음")

    print("\n" + "=" * 60)
    print("  리포트 완료")
    print("=" * 60)


# ── CLI ────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) == 3:
        run_portfolio_report(sys.argv[1], sys.argv[2])
    else:
        run_portfolio_report()
