# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


PIPELINE_DIR = Path(r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline")
SECRETS_DIR = Path(r"D:\AI_WorkSpace\I_SFC\00_Local_Secrets\kiwoom")
APPKEY_PATH = SECRETS_DIR / "64988566_appkey.txt"
SECRETKEY_PATH = SECRETS_DIR / "64988566_secretkey.txt"

DEFAULT_ENV_PATH = PIPELINE_DIR / ".env"
DEFAULT_OUTPUT_DIR = PIPELINE_DIR / "data" / "kiwoom_readonly"
DEFAULT_DOWNLOAD_HOLDINGS = Path(r"D:\AI_WorkSpace\I_SFC\download\holdings_current_from_kiwoom.csv")
DEFAULT_ENDPOINT = "/api/dostk/acnt"

SFD_HOLDINGS_COLUMNS = [
    "stock_code",
    "corp_name",
    "quantity",
    "avg_price",
    "current_price",
    "target_sell_price",
    "target_buy_price",
    "note",
]

READONLY_TRS = [
    {
        "api_id": "kt00004",
        "name": "계좌평가현황요청",
        "bodies": [
            {},
            {"qry_tp": "1", "dmst_stex_tp": "KRX"},
            {"qry_tp": "2", "dmst_stex_tp": "KRX"},
            {"dmst_stex_tp": "KRX"},
        ],
    },
    {
        "api_id": "kt00005",
        "name": "체결잔고요청",
        "bodies": [
            {},
            {"dmst_stex_tp": "KRX"},
            {"qry_tp": "1", "dmst_stex_tp": "KRX"},
        ],
    },
    {
        "api_id": "ka10085",
        "name": "계좌수익률요청",
        "bodies": [
            {},
            {"qry_tp": "1", "dmst_stex_tp": "KRX"},
        ],
    },
    {
        "api_id": "kt00017",
        "name": "계좌평가잔고내역요청",
        "bodies": [
            {"qry_tp": "1", "dmst_stex_tp": "KRX"},
            {"qry_tp": "2", "dmst_stex_tp": "KRX"},
            {},
        ],
    },
]


def kst_now() -> datetime:
    return datetime.now(timezone(timedelta(hours=9)))


def kst_stamp() -> str:
    return kst_now().strftime("%Y%m%d_%H%M%S_KST")


def read_text_secret(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"secret file not found: {path}")
    return path.read_text(encoding="utf-8", errors="ignore").strip()


def ensure_env(env_path: Path, overwrite: bool = False) -> Path:
    app_key = read_text_secret(APPKEY_PATH)
    app_secret = read_text_secret(SECRETKEY_PATH)

    env_lines = [
        f"KIWOOM_APP_KEY={app_key}",
        f"KIWOOM_APP_SECRET={app_secret}",
        "KIWOOM_BASE_URL=https://api.kiwoom.com",
        "KIWOOM_TOKEN_CACHE_PATH=data/raw/kiwoom_rest/token_cache.json",
        "KIWOOM_RAW_SNAPSHOT_DIR=data/raw/kiwoom_rest/snapshots",
        "KIWOOM_TIMEOUT_SEC=30",
        "KIWOOM_MAX_RETRIES=3",
        "KIWOOM_BACKOFF_SEC=1.5",
    ]

    if env_path.exists() and not overwrite:
        existing = env_path.read_text(encoding="utf-8", errors="ignore")
        needed = []
        for line in env_lines:
            key = line.split("=", 1)[0]
            if f"{key}=" not in existing:
                needed.append(line)
        if needed:
            with env_path.open("a", encoding="utf-8", newline="\n") as f:
                f.write("\n# Added by SFD Kiwoom readonly multitr setup\n")
                for line in needed:
                    f.write(line + "\n")
    else:
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")

    return env_path


def import_kiwoom_client():
    sys.path.insert(0, str(PIPELINE_DIR))
    from collectors.kiwoom_rest_client import KiwoomRestClient, KiwoomRestConfig
    return KiwoomRestClient, KiwoomRestConfig


def make_client(env_path: Path):
    KiwoomRestClient, KiwoomRestConfig = import_kiwoom_client()
    cfg = KiwoomRestConfig.from_env(base_dir=PIPELINE_DIR, env_file=env_path)
    return KiwoomRestClient(cfg)


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def find_list_candidates(payload: Any, path: str = "") -> List[Tuple[str, List[Dict[str, Any]]]]:
    found: List[Tuple[str, List[Dict[str, Any]]]] = []
    if isinstance(payload, dict):
        for k, v in payload.items():
            next_path = f"{path}.{k}" if path else str(k)
            found.extend(find_list_candidates(v, next_path))
    elif isinstance(payload, list):
        dict_items = [x for x in payload if isinstance(x, dict)]
        if dict_items:
            found.append((path, dict_items))
            for idx, item in enumerate(dict_items[:1]):
                found.extend(find_list_candidates(item, f"{path}[{idx}]"))
    return found


def flatten_key_summary(payload: Any, prefix: str = "") -> List[str]:
    keys = []
    if isinstance(payload, dict):
        for k, v in payload.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            keys.append(p)
            keys.extend(flatten_key_summary(v, p))
    elif isinstance(payload, list) and payload:
        keys.append(f"{prefix}[]")
        keys.extend(flatten_key_summary(payload[0], f"{prefix}[]"))
    return keys


def get_first(item: Dict[str, Any], keys: Iterable[str]) -> str:
    lowered = {str(k).lower(): v for k, v in item.items()}
    for k in keys:
        if k in item and str(item[k]).strip():
            return str(item[k]).strip()
        lk = k.lower()
        if lk in lowered and str(lowered[lk]).strip():
            return str(lowered[lk]).strip()
    return ""


def only_digits(value: str) -> str:
    return "".join(ch for ch in str(value) if ch.isdigit())


def parse_number(value: str) -> str:
    if value is None:
        return ""
    s = str(value).replace(",", "").replace("+", "").strip()
    sign = "-" if s.startswith("-") else ""
    if sign:
        s = s[1:]
    digits = "".join(ch for ch in s if ch.isdigit() or ch == ".")
    return sign + digits if digits else ""


def normalize_stock_code(raw: str) -> str:
    s = str(raw).strip().upper()
    if s.startswith("A"):
        s = s[1:]
    digits = only_digits(s)
    if len(digits) >= 6:
        return digits[-6:]
    return digits.zfill(6) if digits else ""


def score_candidate_list(items: List[Dict[str, Any]]) -> int:
    if not items:
        return 0
    sample = items[:10]
    keys = set()
    for item in sample:
        keys.update(str(k).lower() for k in item.keys())

    code_keys = {
        "stk_cd", "stkcode", "stk_cd_nm", "code", "stock_code", "pdno", "isu_cd",
        "jm_cd", "종목코드", "종목번호"
    }
    name_keys = {
        "stk_nm", "stkname", "name", "corp_name", "stock_name", "prdt_name",
        "isu_nm", "종목명", "상품명"
    }
    qty_keys = {
        "rmnd_qty", "hldg_qty", "quantity", "qty", "ord_psbl_qty", "poss_qty",
        "유가잔고수량", "보유수량", "잔고수량"
    }
    price_keys = {
        "avg_prc", "pchs_avg_pric", "pur_pric", "avg_price", "pchs_pric",
        "cur_prc", "now_prc", "current_price", "prpr", "evlt_pric",
        "매입평균가", "평균단가", "평단", "현재가"
    }

    code_hits = sum(1 for k in keys if k in code_keys or "stk_cd" in k or "종목코드" in k)
    name_hits = sum(1 for k in keys if k in name_keys or "stk_nm" in k or "종목명" in k)
    qty_hits = sum(1 for k in keys if k in qty_keys or "qty" in k or "수량" in k)
    price_hits = sum(1 for k in keys if k in price_keys or "prc" in k or "pric" in k or "현재가" in k or "평균" in k)
    return code_hits * 4 + name_hits * 2 + qty_hits * 3 + price_hits


def choose_best_items(payload: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]], int]:
    candidates = find_list_candidates(payload)
    if not candidates:
        return "", [], 0
    scored = [(score_candidate_list(items), path, items) for path, items in candidates]
    scored.sort(key=lambda x: x[0], reverse=True)
    score, path, items = scored[0]
    return path, items, score


def normalize_items_to_holdings(items: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for item in items:
        raw_code = get_first(item, [
            "stk_cd", "stock_code", "code", "pdno", "isu_cd", "jm_cd", "stkcode", "종목코드", "종목번호"
        ])
        code = normalize_stock_code(raw_code)
        name = get_first(item, [
            "stk_nm", "corp_name", "stock_name", "name", "prdt_name", "isu_nm", "stkname", "종목명", "상품명"
        ])
        qty = parse_number(get_first(item, [
            "rmnd_qty", "hldg_qty", "quantity", "qty", "poss_qty", "ord_psbl_qty",
            "유가잔고수량", "보유수량", "잔고수량"
        ]))
        avg = parse_number(get_first(item, [
            "avg_prc", "pchs_avg_pric", "pur_pric", "avg_price", "pchs_pric",
            "매입평균가", "평균단가", "평단"
        ]))
        cur = parse_number(get_first(item, [
            "cur_prc", "now_prc", "current_price", "prpr", "evlt_pric", "현재가", "평가가격"
        ]))

        if not code and not name:
            continue
        if qty in {"", "0", "0.0"}:
            continue

        rows.append({
            "stock_code": code,
            "corp_name": name,
            "quantity": qty,
            "avg_price": avg,
            "current_price": cur,
            "target_sell_price": "",
            "target_buy_price": "",
            "note": "kiwoom_readonly_multitr",
        })
    return rows


def write_holdings_csv(path: Path, rows: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SFD_HOLDINGS_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def run_multitr_probe(env_path: Path, output_dir: Path, output_holdings: Path, endpoint: str) -> Dict[str, Any]:
    client = make_client(env_path)
    stamp = kst_stamp()
    output_dir.mkdir(parents=True, exist_ok=True)

    report: Dict[str, Any] = {
        "stamp": stamp,
        "endpoint": endpoint,
        "attempts": [],
        "selected": None,
        "holdings_csv": None,
        "download_holdings_csv": None,
    }

    for tr in READONLY_TRS:
        api_id = tr["api_id"]
        tr_name = tr["name"]
        for body_idx, body in enumerate(tr["bodies"], start=1):
            attempt = {
                "api_id": api_id,
                "tr_name": tr_name,
                "body_idx": body_idx,
                "body": body,
                "ok": False,
            }
            try:
                response = client.post_tr(
                    api_id=api_id,
                    endpoint=endpoint,
                    body=body,
                    collect_all_pages=True,
                    max_pages=5,
                )
                payload = response.body
                raw_path = output_dir / f"{stamp}_{api_id}_body{body_idx}_raw.json"
                save_json(raw_path, payload)

                list_path, items, score = choose_best_items(payload)
                rows = normalize_items_to_holdings(items)

                attempt.update({
                    "ok": True,
                    "status_code": response.status_code,
                    "pages": response.pages,
                    "raw_json": str(raw_path),
                    "return_code": payload.get("return_code"),
                    "return_msg": payload.get("return_msg"),
                    "top_level_keys": list(payload.keys()) if isinstance(payload, dict) else [],
                    "selected_list_path": list_path,
                    "selected_list_count": len(items),
                    "selected_score": score,
                    "normalized_rows": len(rows),
                    "key_summary_preview": flatten_key_summary(payload)[:120],
                })

                if rows and report["selected"] is None:
                    holdings_path = output_dir / f"{stamp}_holdings_current_from_kiwoom.csv"
                    write_holdings_csv(holdings_path, rows)
                    write_holdings_csv(output_holdings, rows)
                    report["selected"] = {
                        "api_id": api_id,
                        "tr_name": tr_name,
                        "body_idx": body_idx,
                        "selected_list_path": list_path,
                        "rows": len(rows),
                    }
                    report["holdings_csv"] = str(holdings_path)
                    report["download_holdings_csv"] = str(output_holdings)

            except Exception as exc:
                attempt.update({
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                })

            report["attempts"].append(attempt)
            print(f"[SFD] {api_id} body{body_idx} ok={attempt.get('ok')} rows={attempt.get('normalized_rows')} list={attempt.get('selected_list_path')} msg={attempt.get('return_msg','')} err={attempt.get('error','')}")

            if report["selected"] is not None:
                # Continue probing? no. Stop once we have usable holdings.
                report_path = output_dir / f"{stamp}_multitr_probe_report.json"
                save_json(report_path, report)
                report["probe_report"] = str(report_path)
                return report

    report_path = output_dir / f"{stamp}_multitr_probe_report.json"
    save_json(report_path, report)
    report["probe_report"] = str(report_path)
    return report


def read_text_if_exists(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""


def main() -> None:
    parser = argparse.ArgumentParser(description="SFD Kiwoom readonly multitr balance probe v1.1")
    parser.add_argument("--env-path", default=str(DEFAULT_ENV_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--output-holdings", default=str(DEFAULT_DOWNLOAD_HOLDINGS))
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    args = parser.parse_args()

    env_path = Path(args.env_path)
    output_dir = Path(args.output_dir)
    output_holdings = Path(args.output_holdings)

    ensure_env(env_path, overwrite=False)

    report = run_multitr_probe(
        env_path=env_path,
        output_dir=output_dir,
        output_holdings=output_holdings,
        endpoint=args.endpoint,
    )

    print()
    print("[DONE] Kiwoom readonly Multi-TR balance probe completed.")
    print(f"- selected: {report.get('selected')}")
    print(f"- holdings_csv: {report.get('holdings_csv')}")
    print(f"- download_holdings_csv: {report.get('download_holdings_csv')}")
    print(f"- probe_report: {report.get('probe_report')}")


if __name__ == "__main__":
    main()
