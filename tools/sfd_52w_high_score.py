# sfd_52w_high_score.py v1.0  — BM-19 52주 신고가 근접도
# Layer 2.5b (technical scorer 보조)
#
# 입력: sfd_prev_close_latest.csv (ticker, prev_close, prev_high)
# 출력: sfd_52w_high_latest.csv   (ticker, high_52w, proximity_pct, score_52w)
#
# 로직:
#   - 캐시 없음(첫날): yfinance period=1y → 52주 고가 계산 + 캐시 저장
#   - 캐시 있음(매일): 캐시의 rolling_high vs 오늘 prev_high → max 갱신
#
# 점수:
#   proximity_pct = (prev_close - high_52w) / high_52w * 100
#   >= -3%  : +10pt  (신고가 돌파 임박)
#   -3~-8%  :  +7pt
#   -8~-15% :  +4pt
#   -15~-25%:  +1pt
#   < -25%  :   0pt
#
# aggregator 통합:
#   tech_score += score_52w  (cap 85pt 유지)
#   출력 컬럼: score_52w, high_52w, proximity_pct

import io, os, sys, time, logging, json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import LATEST_DIR, HISTORY_DIR, INPUT_DIR

LATEST_PATH    = os.path.join(LATEST_DIR, "sfd_prev_close_latest.csv")
OUTPUT_PATH    = os.path.join(LATEST_DIR, "sfd_52w_high_latest.csv")
CACHE_PATH     = os.path.join(LATEST_DIR, "sfd_52w_high_cache.csv")
LOG_PATH       = os.path.join(LATEST_DIR, "sfd_52w_high_score.log")

os.makedirs(LATEST_DIR, exist_ok=True)

logging.basicConfig(filename=LOG_PATH, level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s", encoding="utf-8")

START_TIME = time.time()
now        = datetime.now()
today_str  = now.strftime("%Y%m%d")

BATCH_SIZE = 300
PERIOD     = "1y"

# 점수 테이블
SCORE_TABLE = [
    (-3,   10),
    (-8,    7),
    (-15,   4),
    (-25,   1),
    (-9999, 0),
]

def calc_score(proximity_pct: float) -> int:
    for threshold, score in SCORE_TABLE:
        if proximity_pct >= threshold:
            return score
    return 0


print("\n========== SFD BM-19 52w High Score v1.0 ==========")
print(f"Start: {now.strftime('%Y-%m-%d %H:%M:%S')}")


# ── 캐시 로드
def load_cache() -> dict:
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        df = pd.read_csv(CACHE_PATH, encoding="utf-8-sig", dtype={"ticker": str})
        cache = {}
        for _, row in df.iterrows():
            t = str(row["ticker"]).zfill(6)
            buf = json.loads(row["high_buf"]) if pd.notna(row.get("high_buf")) else []
            cache[t] = {
                "high_52w": float(row["high_52w"]) if pd.notna(row.get("high_52w")) else None,
                "high_buf": buf,  # 최근 252거래일 고가 리스트
            }
        return cache
    except Exception as e:
        logging.warning(f"Cache load failed: {e}")
        return {}


def save_cache(cache: dict):
    rows = []
    for ticker, v in cache.items():
        rows.append({
            "ticker":   ticker,
            "high_52w": v.get("high_52w"),
            "high_buf": json.dumps(v.get("high_buf", [])),
        })
    pd.DataFrame(rows).to_csv(CACHE_PATH, index=False, encoding="utf-8-sig")


# ── prev_close_latest 로드
if not os.path.exists(LATEST_PATH):
    print("ERROR: sfd_prev_close_latest.csv not found")
    sys.exit(1)

prev_df = pd.read_csv(LATEST_PATH, dtype={"ticker": str}, encoding="utf-8-sig")
prev_df["ticker"] = prev_df["ticker"].astype(str).str.zfill(6)
prev_df["prev_close"] = pd.to_numeric(prev_df["prev_close"], errors="coerce")
prev_df["prev_high"]  = pd.to_numeric(prev_df.get("prev_high", pd.Series()), errors="coerce") \
                        if "prev_high" in prev_df.columns else pd.Series(dtype=float)

tickers_all = prev_df["ticker"].tolist()
print(f"  Tickers loaded: {len(tickers_all)}")


# ── 캐시 확인
cache     = load_cache()
has_cache = len(cache) > 100
mode      = "FAST(cache)" if has_cache else "FULL(1y, init)"
print(f"  Cache: {len(cache)} tickers | mode: {mode}")


# ── FULL fetch (첫날만)
if not has_cache:
    print(f"  Downloading 1y high for {len(tickers_all)} tickers...")

    # market suffix 매핑
    suffix_map = {}
    for _, row in prev_df.iterrows():
        t = str(row["ticker"]).zfill(6)
        mkt = str(row.get("market", "")).upper()
        suffix_map[t] = ".KS" if mkt == "KOSPI" else ".KQ"

    yf_map = {}  # ticker -> high_52w, high_buf
    all_yf = [f"{t}{suffix_map.get(t, '.KS')}" for t in tickers_all]

    for i in range(0, len(all_yf), BATCH_SIZE):
        batch    = all_yf[i:i + BATCH_SIZE]
        raw_tickers = tickers_all[i:i + BATCH_SIZE]
        try:
            data = yf.download(batch, period=PERIOD, auto_adjust=True,
                               progress=False, threads=True)
            if data.empty:
                continue

            def get_col(col):
                if isinstance(data.columns, pd.MultiIndex):
                    return data[col] if col in data.columns.get_level_values(0) else pd.DataFrame()
                return data[[col]] if col in data.columns else pd.DataFrame()

            high_df  = get_col("High")
            close_df = get_col("Close")

            def safe_ser(df, yf_t):
                try:
                    if isinstance(df.columns, pd.MultiIndex):
                        s = df[yf_t] if yf_t in df.columns.get_level_values(1) else pd.Series()
                    else:
                        s = df[yf_t] if yf_t in df.columns else pd.Series()
                    return s.dropna()
                except Exception:
                    return pd.Series()

            for raw_t, yf_t in zip(raw_tickers, batch):
                h_ser = safe_ser(high_df,  yf_t)
                c_ser = safe_ser(close_df, yf_t)
                if len(h_ser) < 5:
                    continue
                high_52w = float(h_ser.max())
                high_buf = h_ser.tolist()[-252:]  # 최대 252거래일
                yf_map[raw_t] = {"high_52w": high_52w, "high_buf": high_buf}

            print(f"  batch {i//BATCH_SIZE+1:02d}/{(len(all_yf)-1)//BATCH_SIZE+1:02d} done")
        except Exception as e:
            print(f"  batch {i//BATCH_SIZE+1:02d} ERROR: {e}")
        time.sleep(0.5)

    cache = yf_map


# ── 점수 계산 + incremental cache update
new_cache = {}
results   = []

for _, row in prev_df.iterrows():
    ticker    = str(row["ticker"]).zfill(6)
    prev_close = float(row["prev_close"]) if pd.notna(row["prev_close"]) else None
    today_high = float(row["prev_high"])  if "prev_high" in row and pd.notna(row["prev_high"]) else None

    cached = cache.get(ticker, {})
    high_buf = list(cached.get("high_buf", []))

    # incremental: 오늘 고가 추가 → 252일 rolling max
    if today_high and today_high > 0:
        high_buf.append(today_high)
        if len(high_buf) > 252:
            high_buf = high_buf[-252:]

    high_52w = float(max(high_buf)) if high_buf else None

    new_cache[ticker] = {
        "high_52w": high_52w,
        "high_buf": high_buf,
    }

    if prev_close and high_52w and high_52w > 0:
        proximity_pct = round((prev_close - high_52w) / high_52w * 100, 2)
        score_52w     = calc_score(proximity_pct)
    else:
        proximity_pct = None
        score_52w     = 0

    results.append({
        "ticker":        ticker,
        "high_52w":      round(high_52w, 2) if high_52w else None,
        "proximity_pct": proximity_pct,
        "score_52w":     score_52w,
    })

# ── 저장
out_df = pd.DataFrame(results)
out_df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
save_cache(new_cache)

scored   = out_df[out_df["score_52w"] > 0]
top10    = out_df.nlargest(10, "score_52w")[["ticker", "proximity_pct", "score_52w"]]
elapsed  = round(time.time() - START_TIME)

print(f"\n[OK] output : {OUTPUT_PATH}")
print(f"  Total={len(out_df)} | scored={len(scored)} | elapsed={elapsed}s | mode={mode}")
print(f"  Top10 proximity:\n{top10.to_string(index=False)}")

logging.info(f"DONE | total={len(out_df)} | scored={len(scored)} | elapsed={elapsed}s | mode={mode}")
