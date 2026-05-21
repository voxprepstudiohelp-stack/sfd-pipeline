# sfd_signal_aggregator.py v2.0 (yfinance 배치 — 목표 5분)
# GitHub: sfd-pipeline/tools/sfd_signal_aggregator.py

import os, sys, time, logging, glob
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import yfinance as yf
import FinanceDataReader as fdr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import LATEST_DIR, HISTORY_DIR, INPUT_DIR

LATEST_CSV  = os.path.join(LATEST_DIR, "sfd_master_signal_latest.csv")
INPUT_CSV   = os.path.join(INPUT_DIR,  "sfd_master_signal_input.csv")
LOG_PATH    = os.path.join(LATEST_DIR, "sfd_signal_aggregator.log")
PREV_CSV    = os.path.join(LATEST_DIR, "sfd_prev_close_latest.csv")
INVESTOR_CSV= os.path.join(LATEST_DIR, "sfd_investor_flow_latest.csv")
NEWS_CSV    = os.path.join(LATEST_DIR, "sfd_news_signal_latest.csv")

os.makedirs(LATEST_DIR,  exist_ok=True)
os.makedirs(HISTORY_DIR, exist_ok=True)
os.makedirs(INPUT_DIR,   exist_ok=True)

logging.basicConfig(filename=LOG_PATH, level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s", encoding="utf-8")

START_TIME  = time.time()
now         = datetime.now()
fetch_time  = now.strftime("%Y-%m-%d %H:%M:%S")

# ── 임계값
THRESHOLD_RESERVE = 30
THRESHOLD_WATCH   = 20
MODE              = "TEMP"

RSI_PERIOD    = 14
MA_SHORT, MA_MID, MA_LONG = 5, 20, 60
VOL_PERIOD    = 20
BATCH_SIZE    = 400   # yfinance 1회 배치 크기
TOP_VALUE_PCT = 0.20

print(f"\n========== SFD Signal Aggregator v2.0 (yfinance 배치) ==========")
print(f"모드: {MODE} | RESERVE≥{THRESHOLD_RESERVE} / WATCH≥{THRESHOLD_WATCH}")
print(f"실행 시각: {fetch_time}")

# ── 1. prev_close 로드
if not os.path.exists(PREV_CSV):
    print(f"❌ prev_close 없음: {PREV_CSV}")
    sys.exit(1)

prev_df = pd.read_csv(PREV_CSV, dtype={"ticker": str})
prev_df["ticker"] = prev_df["ticker"].astype(str).str.zfill(6)
print(f"총 종목: {len(prev_df)}")

# ── 2. 거래대금 상위 20% 임계값
value_threshold = 0
if "prev_value" in prev_df.columns:
    vs = pd.to_numeric(prev_df["prev_value"], errors="coerce").dropna()
    value_threshold = vs.quantile(1 - TOP_VALUE_PCT) if len(vs) > 0 else 0

# ── 3. 뉴스 점수 맵
news_score_map = {}
if os.path.exists(NEWS_CSV):
    news_df = pd.read_csv(NEWS_CSV)
    for _, row in news_df.iterrows():
        raw = row.get("detected_stocks", "")
        imp = row.get("importance_score", 0)
        if pd.isna(raw) or str(raw).strip() == "":
            continue
        try: imp = float(imp)
        except: imp = 0
        pts = round(imp * 0.3, 1)
        for t in str(raw).split(";"):
            t = t.strip().zfill(6)
            news_score_map[t] = min(30, news_score_map.get(t, 0) + pts)

# ── 4. 수급 점수 맵
investor_df = pd.read_csv(INVESTOR_CSV, dtype={"ticker": str}) if os.path.exists(INVESTOR_CSV) else None

# ── 5. yfinance 배치 기술지표 수집
def calc_rsi(series, period=14):
    delta = series.diff()
    gain  = delta.clip(lower=0).ewm(com=period-1, min_periods=period).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=period-1, min_periods=period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def build_tech_map(tickers_raw, market_suffix):
    tech_map = {}
    yf_tickers = [f"{t}{market_suffix}" for t in tickers_raw]

    end_dt   = now.strftime("%Y-%m-%d")
    start_dt = (now - timedelta(days=150)).strftime("%Y-%m-%d")

    for i in range(0, len(yf_tickers), BATCH_SIZE):
        batch_yf  = yf_tickers[i:i+BATCH_SIZE]
        batch_raw = tickers_raw[i:i+BATCH_SIZE]
        print(f"  기술지표 배치 {i//BATCH_SIZE+1}/{(len(yf_tickers)-1)//BATCH_SIZE+1} ({market_suffix}): {len(batch_yf)}종목")

        try:
            data = yf.download(
                batch_yf,
                start=start_dt,
                end=end_dt,
                auto_adjust=True,
                progress=False,
                threads=True
            )
            if data.empty:
                continue

            # 단일 종목이면 컬럼 구조 다름 → 표준화
            if isinstance(data.columns, pd.MultiIndex):
                close_df  = data["Close"]
                vol_df    = data["Volume"]
            else:
                close_df  = data[["Close"]].rename(columns={"Close": batch_yf[0]})
                vol_df    = data[["Volume"]].rename(columns={"Volume": batch_yf[0]})

            for yf_t, raw_t in zip(batch_yf, batch_raw):
                try:
                    if yf_t not in close_df.columns:
                        continue
                    close = close_df[yf_t].dropna()
                    vol   = vol_df[yf_t].dropna()
                    if len(close) < MA_LONG:
                        continue

                    rsi      = calc_rsi(close, RSI_PERIOD).iloc[-1]
                    ma_s     = close.rolling(MA_SHORT).mean().iloc[-1]
                    ma_m     = close.rolling(MA_MID).mean().iloc[-1]
                    ma_l     = close.rolling(MA_LONG).mean().iloc[-1]
                    vol_last = vol.iloc[-1]
                    vol_avg  = vol.rolling(VOL_PERIOD).mean().iloc[-1]

                    tech_map[raw_t] = {
                        "rsi": round(rsi, 2) if not np.isnan(rsi) else None,
                        "ma_short": ma_s, "ma_mid": ma_m, "ma_long": ma_l,
                        "volume": vol_last, "vol_avg": vol_avg
                    }
                except:
                    pass
            time.sleep(0.5)

        except Exception as e:
            print(f"  배치 오류: {e}")

    return tech_map

# KOSPI / KOSDAQ 분리 처리
kospi_df  = prev_df[prev_df["market"] == "KOSPI"]  if "market" in prev_df.columns else prev_df
kosdaq_df = prev_df[prev_df["market"] == "KOSDAQ"] if "market" in prev_df.columns else pd.DataFrame()

print("\nKOSPI 기술지표 수집...")
tech_map = build_tech_map(kospi_df["ticker"].tolist(), ".KS")

print("\nKOSDAQ 기술지표 수집...")
tech_map.update(build_tech_map(kosdaq_df["ticker"].tolist(), ".KQ"))

print(f"\n기술지표 수집 완료: {len(tech_map)}종목")

# ── 6. 점수 함수
def score_rsi(rsi):
    if rsi is None: return 0
    if rsi < 30: return 15
    if rsi < 50: return 10
    if rsi < 70: return 5
    return 0

def score_ma(ms, mm, ml):
    if None in [ms, mm, ml]: return 0
    if ms > mm > ml: return 15
    if ms > mm:      return 8
    if ms > ml:      return 4
    return 0

def score_volume(v, va):
    if not va or va == 0: return 0
    r = v / va
    if r >= 2.0: return 10
    if r >= 1.5: return 7
    if r >= 1.0: return 4
    return 0

def score_investor(ticker):
    if investor_df is None or investor_df.empty: return 0
    row = investor_df[investor_df["ticker"] == ticker]
    if row.empty: return 0
    try:
        f = float(row.iloc[0].get("foreign_net_buy", 0))
        i = float(row.iloc[0].get("institution_net_buy", 0))
        return (10 if f > 0 else 0) + (10 if i > 0 else 0)
    except: return 0

# ── 7. 전종목 스코어링
trade_date = (now - timedelta(days=1)).strftime("%Y%m%d")
results    = []

for _, row in prev_df.iterrows():
    ticker = row["ticker"]
    name   = row.get("name", "")
    tech   = tech_map.get(ticker, {})

    rsi      = tech.get("rsi")
    ma_s     = tech.get("ma_short")
    ma_m     = tech.get("ma_mid")
    ma_l     = tech.get("ma_long")
    volume   = tech.get("volume")
    vol_avg  = tech.get("vol_avg")

    tech_score     = score_rsi(rsi) + score_ma(ma_s, ma_m, ma_l) + score_volume(volume, vol_avg)
    news_score     = round(news_score_map.get(ticker, 0), 1)
    investor_score = score_investor(ticker)

    prev_val   = pd.to_numeric(row.get("prev_value", 0), errors="coerce") or 0
    theme_score= 10 if (value_threshold > 0 and prev_val >= value_threshold) else 0

    total = tech_score + news_score + investor_score + theme_score

    signal = "RESERVE_BUY" if total >= THRESHOLD_RESERVE else \
             "WATCH_ONLY"  if total >= THRESHOLD_WATCH   else "HOLD"

    ma_label = "정배열" if (ma_s and ma_m and ma_l and ma_s > ma_m > ma_l) else \
               "역배열" if (ma_s and ma_m and ma_l and ma_s < ma_m < ma_l) else "혼합"

    results.append({
        "ticker": ticker, "name": name,
        "signal": signal, "total_score": total,
        "tech_score": tech_score, "news_score": news_score,
        "investor_score": investor_score, "theme_score": theme_score,
        "rsi": rsi, "ma_alignment": ma_label,
        "vol_ratio": round(volume/vol_avg, 2) if (volume and vol_avg and vol_avg > 0) else None,
        "trade_date": trade_date, "generated_at": fetch_time, "mode": MODE
    })

result_df = pd.DataFrame(results).sort_values("total_score", ascending=False).reset_index(drop=True)

# ── 8. 저장
result_df.to_csv(LATEST_CSV, index=False, encoding="utf-8-sig")
print(f"\n✅ latest : {LATEST_CSV}")

history_file = os.path.join(HISTORY_DIR, f"sfd_master_signal_{trade_date}.csv")
result_df.to_csv(history_file, index=False, encoding="utf-8-sig")
print(f"✅ history: {history_file}")

input_df = result_df[result_df["signal"].isin(["RESERVE_BUY","WATCH_ONLY"])][
    ["ticker","name","signal","total_score"]].copy()
input_df.to_csv(INPUT_CSV, index=False, encoding="utf-8-sig")
print(f"✅ input  : {INPUT_CSV}")

reserve = len(result_df[result_df["signal"]=="RESERVE_BUY"])
watch   = len(result_df[result_df["signal"]=="WATCH_ONLY"])
elapsed = round(time.time() - START_TIME)
print(f"\nRESERVE: {reserve} | WATCH: {watch} | 소요: {elapsed}초")
logging.info(f"완료 | RESERVE={reserve} | WATCH={watch} | 소요={elapsed}s | MODE={MODE}")
