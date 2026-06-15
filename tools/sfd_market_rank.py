"""
sfd_market_rank.py v1.0
========================
목적: KIS API 시장 순위 조회
  - 상승률 TOP15
  - 하락률 TOP15
  - 거래량 TOP15
  - 외국인/기관 순매수 TOP15

출력: outputs/latest/sfd_market_rank.json
      outputs/latest/sfd_market_rank_YYYYMMDD.json  (백업)

레포트 연동: sfd_daily_report.py 대시보드 하단 행
스케줄: 09:05 수급반영 단계에서 실행 (장중 실시간 가능)
"""

import os
import json
import time
import requests
import logging
from datetime import datetime, date
from pathlib import Path

# ── 경로 설정 ──────────────────────────────────────────────────
# tools/ 서브폴더에서 실행해도 SFC_DataPipeline 루트를 찾도록
_SCRIPT_DIR = Path(__file__).resolve().parent
# .env 탐색: 현재 디렉터리 → 부모 디렉터리 순
def _find_project_root() -> Path:
    for candidate in [_SCRIPT_DIR, _SCRIPT_DIR.parent]:
        if (candidate / ".env").exists():
            return candidate
    return _SCRIPT_DIR  # fallback

BASE_DIR   = _find_project_root()
OUTPUT_DIR = BASE_DIR / "outputs" / "latest"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── 로깅 ───────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MARKET_RANK] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── .env 로드 ──────────────────────────────────────────────────
def load_env():
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        raw = env_path.read_text(encoding="utf-8-sig")  # BOM 제거
        for line in raw.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()  # setdefault → 강제 덮어쓰기
        log.info(f".env 로드 완료: {env_path}")
    else:
        log.warning(f".env 없음: {env_path}")

load_env()

KIS_APP_KEY    = os.environ.get("KIS_APP_KEY", "")
KIS_APP_SECRET = os.environ.get("KIS_APP_SECRET", "").replace("\n", "").replace("\r", "")
KIS_BASE_URL   = "https://openapi.koreainvestment.com:9443"

# ── 토큰 취득 ──────────────────────────────────────────────────
_token_cache: dict = {}

def get_access_token() -> str:
    """Bearer 토큰 반환 (캐시 30분)"""
    now = time.time()
    if _token_cache.get("token") and now < _token_cache.get("expires", 0):
        return _token_cache["token"]

    url  = f"{KIS_BASE_URL}/oauth2/tokenP"
    body = {
        "grant_type":    "client_credentials",
        "appkey":        KIS_APP_KEY,
        "appsecret":     KIS_APP_SECRET,
    }
    resp = requests.post(url, json=body, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token", "")
    _token_cache["token"]   = token
    _token_cache["expires"] = now + 1700  # ~28분
    log.info("KIS 토큰 취득 완료")
    return token


def kis_get(path: str, params: dict, tr_id: str) -> dict:
    """KIS REST GET 공통 호출"""
    token = get_access_token()
    headers = {
        "content-type":  "application/json",
        "authorization": f"Bearer {token}",
        "appkey":        KIS_APP_KEY,
        "appsecret":     KIS_APP_SECRET,
        "tr_id":         tr_id,
        "custtype":      "P",
    }
    url = f"{KIS_BASE_URL}{path}"
    resp = requests.get(url, headers=headers, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ══════════════════════════════════════════════════════════════
# 1. 상승/하락률 TOP15  — tr_id: FHPST01720000
# ══════════════════════════════════════════════════════════════
def fetch_price_rank(sort_type: str = "1") -> list[dict]:
    """
    sort_type:
      "1" → 상승률 TOP
      "2" → 하락률 TOP
    반환 필드: rank, code, name, price, change_rate, volume
    """
    params = {
        "fid_cond_mrkt_div_code": "J",        # 주식
        "fid_cond_scr_div_code":  "20172",
        "fid_input_iscd":         "0001",      # KOSPI 전체
        "fid_rank_sort_cls_code": sort_type,   # 1=상승 2=하락
        "fid_input_cnt_1":        "0",
        "fid_prc_cls_code":       "1",         # 대비율 기준
        "fid_input_price_1":      "",
        "fid_input_price_2":      "",
        "fid_vol_cnt":            "",
        "fid_trgt_cls_code":      "0",
        "fid_trgt_exls_cls_code": "0",
        "fid_div_cls_code":       "0",
        "fid_rsfl_rate1":         "",
        "fid_rsfl_rate2":         "",
    }
    try:
        raw = kis_get(
            "/uapi/domestic-stock/v1/ranking/fluctuation",
            params,
            "FHPST01720000",
        )
        output = raw.get("output", []) or []
        result = []
        for i, row in enumerate(output[:15], start=1):
            result.append({
                "rank":        i,
                "code":        row.get("stck_shrn_iscd", ""),
                "name":        row.get("hts_kor_isnm", ""),
                "price":       int(row.get("stck_prpr", 0) or 0),
                "change_rate": float(row.get("prdy_ctrt", 0) or 0),
                "volume":      int(row.get("acml_vol", 0) or 0),
                "per":         row.get("per", ""),
                "market_cap":  row.get("stck_avls", ""),
            })
        return result
    except Exception as e:
        log.error(f"price_rank(sort={sort_type}) 실패: {e}")
        return []


# ══════════════════════════════════════════════════════════════
# 2. 거래량 TOP15  — tr_id: FHPST01710000
# ══════════════════════════════════════════════════════════════
def fetch_volume_rank() -> list[dict]:
    """거래량 순위 TOP15 — /uapi/domestic-stock/v1/quotations/volume-rank"""
    params = {
        "FID_COND_MRKT_DIV_CODE":  "J",          # MRKT (오타 수정)
        "FID_COND_SCR_DIV_CODE":   "20171",
        "FID_INPUT_ISCD":          "0001",
        "FID_DIV_CLS_CODE":        "0",
        "FID_BLNG_CLS_CODE":       "0",
        "FID_TRGT_CLS_CODE":       "111111111",
        "FID_TRGT_EXLS_CLS_CODE":  "000000",
        "FID_INPUT_PRICE_1":       "",
        "FID_INPUT_PRICE_2":       "",
        "FID_VOL_CNT":             "",
        "FID_INPUT_DATE_1":        "",
    }
    try:
        raw = kis_get(
            "/uapi/domestic-stock/v1/quotations/volume-rank",
            params,
            "FHPST01710000",
        )
        output = raw.get("output", []) or []
        result = []
        for i, row in enumerate(output[:15], start=1):
            result.append({
                "rank":        i,
                "code":        row.get("mksc_shrn_iscd", "") or row.get("stck_shrn_iscd", ""),
                "name":        row.get("hts_kor_isnm", ""),
                "price":       int(row.get("stck_prpr", 0) or 0),
                "change_rate": float(row.get("prdy_ctrt", 0) or 0),
                "volume":      int(row.get("acml_vol", 0) or 0),
                "vol_ratio":   row.get("vol_inrt", ""),
            })
        return result
    except Exception as e:
        log.error(f"volume_rank 실패: {e}")
        return []


# ══════════════════════════════════════════════════════════════
# 3. 외국인/기관 순매수 TOP15  — investor_flow CSV 기반
# ══════════════════════════════════════════════════════════════
def fetch_investor_rank(inv_type: str = "1") -> list[dict]:
    """
    외국인/기관 순매수 TOP15
    소스: outputs/latest/sfd_investor_flow_latest.csv
    실제 컬럼: foreign_net_buy (외국인), institution_net_buy (기관)
    ticker → master_signal join으로 name 보완
    """
    import csv

    label    = "외국인" if inv_type == "1" else "기관"
    col_map  = {"1": "foreign_net_buy", "2": "institution_net_buy"}
    ntby_col = col_map[inv_type]

    flow_path = OUTPUT_DIR / "sfd_investor_flow_latest.csv"
    if not flow_path.exists():
        log.warning(f"investor_flow CSV 없음 — {label} 스킵")
        return []

    # master_signal에서 name 조회용 dict
    signal_map: dict = {}
    for sig_name in ["sfd_master_signal_latest.csv", "sfd_master_signal.csv"]:
        sig_path = OUTPUT_DIR / sig_name
        if sig_path.exists():
            try:
                with open(sig_path, encoding="utf-8-sig", newline="") as f:
                    for row in csv.DictReader(f):
                        code = row.get("stock_code", row.get("ticker", ""))
                        if code:
                            signal_map[code] = row
            except Exception:
                pass
            break

    try:
        rows = []
        with open(flow_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    val = float(row.get(ntby_col, 0) or 0)
                    if val == 0:
                        continue
                    code = row.get("ticker", "")
                    sig  = signal_map.get(code, {})
                    rows.append({
                        "code":        code,
                        "name":        sig.get("name", sig.get("hts_kor_isnm", code)),
                        "price":       int(float(sig.get("prev_close", sig.get("stck_prpr", 0)) or 0)),
                        "change_rate": float(sig.get("change_rate", sig.get("prdy_ctrt", 0)) or 0),
                        "net_buy":     int(val),
                        "investor":    label,
                    })
                except (ValueError, TypeError):
                    continue

        if not rows:
            log.warning(f"{label}: CSV 데이터 없음 — 파이프라인 실행 후 재시도")
            return []

        rows.sort(key=lambda x: x["net_buy"], reverse=True)
        top15 = rows[:15]
        for i, r in enumerate(top15, start=1):
            r["rank"] = i
        log.info(f"  {label} TOP{len(top15)} 집계 완료")
        return top15

    except Exception as e:
        log.error(f"investor_rank CSV 집계 실패({label}): {e}")
        return []


# ══════════════════════════════════════════════════════════════
# 4. 메인 실행
# ══════════════════════════════════════════════════════════════
def run():
    today_str = date.today().strftime("%Y%m%d")
    ts        = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log.info(f"=== sfd_market_rank.py v1.0 시작 ({ts}) ===")

    if not KIS_APP_KEY or not KIS_APP_SECRET:
        log.error(".env에서 KIS_APP_KEY / KIS_APP_SECRET를 찾을 수 없습니다.")
        return

    result = {
        "generated_at": ts,
        "date":         today_str,
        "rise_top15":   [],
        "fall_top15":   [],
        "volume_top15": [],
        "foreign_top15": [],
        "institution_top15": [],
        "status": "ok",
        "errors": [],
    }

    # 상승 TOP15
    log.info("상승률 TOP15 조회 중...")
    result["rise_top15"] = fetch_price_rank("1")
    log.info(f"  → {len(result['rise_top15'])}건")
    time.sleep(0.3)

    # 하락 TOP15
    log.info("하락률 TOP15 조회 중...")
    result["fall_top15"] = fetch_price_rank("2")
    log.info(f"  → {len(result['fall_top15'])}건")
    time.sleep(0.3)

    # 거래량 TOP15
    log.info("거래량 TOP15 조회 중...")
    result["volume_top15"] = fetch_volume_rank()
    log.info(f"  → {len(result['volume_top15'])}건")
    time.sleep(0.3)

    # 외국인 순매수 TOP15
    log.info("외국인 순매수 TOP15 조회 중...")
    result["foreign_top15"] = fetch_investor_rank("1")
    log.info(f"  → {len(result['foreign_top15'])}건")
    time.sleep(0.3)

    # 기관 순매수 TOP15
    log.info("기관 순매수 TOP15 조회 중...")
    result["institution_top15"] = fetch_investor_rank("2")
    log.info(f"  → {len(result['institution_top15'])}건")

    # 저장
    out_path    = OUTPUT_DIR / "sfd_market_rank.json"
    backup_path = OUTPUT_DIR / f"sfd_market_rank_{today_str}.json"
    for p in [out_path, backup_path]:
        p.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # 요약 출력
    log.info("=" * 50)
    log.info(f"[완료] 저장: {out_path}")
    log.info(f"  상승TOP15  : {len(result['rise_top15'])}건")
    log.info(f"  하락TOP15  : {len(result['fall_top15'])}건")
    log.info(f"  거래량TOP15: {len(result['volume_top15'])}건")
    log.info(f"  외국인TOP15: {len(result['foreign_top15'])}건")
    log.info(f"  기관TOP15  : {len(result['institution_top15'])}건")
    if result["rise_top15"]:
        top = result["rise_top15"][0]
        log.info(f"  상승 1위: {top['name']} ({top['code']}) +{top['change_rate']:.2f}%")
    log.info("=" * 50)

    return result


if __name__ == "__main__":
    run()
