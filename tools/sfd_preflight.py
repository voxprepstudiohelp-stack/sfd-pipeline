#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sfd_preflight.py — SFD Pipeline Preflight Check v1.0

점검 항목:
  [1] YML 문법   — .github/workflows/*.yml 파일별 'jobs:' 키 존재 확인
  [2] 파이썬 파일 — tools/sfd_*.py 전수: 크기 STUB 경고 + py_compile 문법 검사
  [3] 환경변수    — 필수 키가 .env 또는 os.environ에 존재하는지 확인
  [4] 데이터 파일 — data/sfd_company_master... 및 portfolio.json 존재 확인

결과:
  각 항목: [PASS] / [WARN] / [FAIL]
  최종:    PREFLIGHT PASS (exit 0) 또는 PREFLIGHT FAIL (exit 1)

Usage:
  py tools/sfd_preflight.py
  python tools/sfd_preflight.py

Version: v1.0
Author:  Claude Sonnet 4.6 (2026-06-07)
"""

import os
import subprocess
import sys
from pathlib import Path

# ── 경로 설정 ─────────────────────────────────────────────────────────────
_HERE   = Path(__file__).resolve().parent           # tools/
_ROOT   = _HERE.parent                               # repo root
_WF_DIR = _ROOT / ".github" / "workflows"
_ENV    = _ROOT / ".env"

# SFD_BASE_DIR 대응 (Actions: /tmp/sfd, local: repo root)
_SFD_BASE = Path(os.environ.get("SFD_BASE_DIR", str(_ROOT)))
_DATA     = _SFD_BASE / "data"

# ── 필수 환경변수 목록 ────────────────────────────────────────────────────
REQUIRED_ENV_VARS = [
    "DART_API_KEY",
    "KIS_APP_KEY",
    "KIS_APP_SECRET",
    "KIS_ACCOUNT_NO",
    "KIS_ACCT_PROD",
    "GOOGLE_DRIVE_FOLDER_ID",
    "NAVER_CLIENT_ID",
    "NAVER_CLIENT_SECRET",
]

# ── 필수 데이터 파일 ──────────────────────────────────────────────────────
REQUIRED_DATA_FILES = [
    _ROOT / "data" / "sfd_company_master_v1.4_sector_filled.csv",
    _ROOT / "portfolio.json",
]

# ── 크기 임계값 (이하이면 STUB 경고) ─────────────────────────────────────
STUB_SIZE_BYTES = 100

# ── ANSI 색상 (터미널 미지원 시 공백) ────────────────────────────────────
_USE_COLOR = sys.stdout.isatty() or os.environ.get("TERM", "") != ""
GREEN  = "\033[32m" if _USE_COLOR else ""
YELLOW = "\033[33m" if _USE_COLOR else ""
RED    = "\033[31m" if _USE_COLOR else ""
CYAN   = "\033[36m" if _USE_COLOR else ""
RESET  = "\033[0m"  if _USE_COLOR else ""

_STATUS = {
    "PASS": f"{GREEN}PASS{RESET}",
    "WARN": f"{YELLOW}WARN{RESET}",
    "FAIL": f"{RED}FAIL{RESET}",
}
COL_W = 56   # label column width


def _row(label: str, status: str, detail: str = "") -> None:
    detail_str = f"  ({detail})" if detail else ""
    print(f"  {label:<{COL_W}} [{_STATUS[status]}]{detail_str}")


# ── .env 파서 (python-dotenv 미필요) ─────────────────────────────────────
def _load_dotenv(path: Path) -> dict:
    env = {}
    if not path.exists():
        return env
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    except Exception:
        pass
    return env


# ── [1] YML 문법 검증 ─────────────────────────────────────────────────────
def check_yml() -> tuple:
    print(f"\n{CYAN}[1] YML 파일 검증  (.github/workflows/){RESET}")
    p = w = f = 0

    if not _WF_DIR.exists():
        _row(".github/workflows/ 디렉토리", "FAIL", "경로 없음")
        return 0, 0, 1

    ymls = sorted(_WF_DIR.glob("*.yml")) + sorted(_WF_DIR.glob("*.yaml"))
    if not ymls:
        _row(".github/workflows/ (yml 없음)", "WARN")
        return 0, 1, 0

    for yml in ymls:
        try:
            content = yml.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            _row(yml.name, "FAIL", f"읽기 오류: {e}")
            f += 1
            continue

        has_jobs = any(ln.startswith("jobs:") for ln in content.splitlines())
        if has_jobs:
            _row(yml.name, "PASS")
            p += 1
        else:
            _row(yml.name, "FAIL", "'jobs:' 키 없음")
            f += 1

    return p, w, f


# ── [2] tools/sfd_*.py 전수 검증 ─────────────────────────────────────────
def check_tools() -> tuple:
    print(f"\n{CYAN}[2] tools/ sfd_*.py 파일 검증{RESET}")
    p = w = f = 0

    scripts = sorted(_HERE.glob("sfd_*.py"))
    if not scripts:
        _row("tools/sfd_*.py", "FAIL", "파일 없음")
        return 0, 0, 1

    print(f"  ({len(scripts)}개 파일 검사)")

    for script in scripts:
        name  = script.name
        size  = script.stat().st_size

        # STUB 크기 경고
        if size <= STUB_SIZE_BYTES:
            _row(f"tools/{name}", "WARN",
                 f"STUB 의심 — {size}B ≤ {STUB_SIZE_BYTES}B")
            w += 1
            continue

        # py_compile 문법 검사
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(script)],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            _row(f"tools/{name}", "PASS")
            p += 1
        else:
            stderr = result.stderr.strip()
            last_line = stderr.splitlines()[-1] if stderr else "syntax error"
            _row(f"tools/{name}", "FAIL", last_line)
            f += 1

    return p, w, f


# ── [3] 필수 환경변수 확인 ────────────────────────────────────────────────
def check_env() -> tuple:
    print(f"\n{CYAN}[3] 필수 환경변수 확인{RESET}")
    p = w = f = 0
    dot_env = _load_dotenv(_ENV)

    for var in REQUIRED_ENV_VARS:
        in_os   = bool(os.environ.get(var, "").strip())
        in_file = bool(dot_env.get(var, "").strip())

        if in_os:
            _row(var, "PASS", "os.environ")
            p += 1
        elif in_file:
            _row(var, "PASS", ".env 파일")
            p += 1
        else:
            # Actions Secret은 런타임에 주입되므로 로컬에 없어도 WARN (FAIL 아님)
            _row(var, "WARN", ".env/os.environ 없음 -- Actions Secret 런타임 주입 확인")
            w += 1

    return p, w, f


# ── [4] 필수 데이터 파일 확인 ─────────────────────────────────────────────
def check_data() -> tuple:
    print(f"\n{CYAN}[4] 필수 데이터 파일 확인{RESET}")
    p = w = f = 0

    for fpath in REQUIRED_DATA_FILES:
        try:
            rel = fpath.relative_to(_ROOT)
        except ValueError:
            rel = fpath
        label = str(rel).replace("\\", "/")

        if fpath.exists():
            size_kb = fpath.stat().st_size // 1024
            _row(label, "PASS", f"{size_kb} KB")
            p += 1
        else:
            _row(label, "FAIL", "파일 없음")
            f += 1

    return p, w, f


# ── 메인 ─────────────────────────────────────────────────────────────────
def main():
    print("=" * 65)
    print("  SFD PREFLIGHT CHECK v1.0")
    print("=" * 65)

    total_p = total_w = total_f = 0

    for fn in (check_yml, check_tools, check_env, check_data):
        cp, cw, cf = fn()
        total_p += cp
        total_w += cw
        total_f += cf

    print()
    print("=" * 65)
    print(f"  결과 요약:  "
          f"{GREEN}PASS {total_p}{RESET}  /  "
          f"{YELLOW}WARN {total_w}{RESET}  /  "
          f"{RED}FAIL {total_f}{RESET}")
    print("=" * 65)

    if total_f == 0:
        print(f"  {GREEN}PREFLIGHT PASS{RESET}  -- 배포 진행 가능")
        print("=" * 65)
        sys.exit(0)
    else:
        print(f"  {RED}PREFLIGHT FAIL{RESET}  -- FAIL {total_f}건 해결 후 재실행")
        print("=" * 65)
        sys.exit(1)


if __name__ == "__main__":
    main()
