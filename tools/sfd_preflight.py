"""
sfd_preflight.py
SFD Pipeline Pre-Push Validation Gate
Version: 2.2  (SEARCH_ROOTS 방식 - tools/ 서브폴더 포함 탐색)
Date: 2026-06-09

실제 파일 구조:
  SFC_DataPipeline/         ← PIPELINE_ROOT (로컬 작업, .env, outputs)
    sfd_signal_aggregator.py
    sfd_sector_injector.py
    investor_flow_fetch.py
    ...
    tools/                  ← TOOLS_DIR (보조 모듈)
    outputs/latest/
    .env

  sfd-pipeline/             ← REPO_ROOT (git repo)
    .github/workflows/sfd_daily.yml
    sfd_signal_aggregator.py  (또는 pipeline 동기화)
    ...

검사 항목:
  [ENV]   .env 필수 키 + APP_SECRET 줄바꿈
  [FILE]  PIPELINE_ROOT 또는 REPO_ROOT 중 어느 쪽에든 존재하면 PASS
  [TOOLS] tools/ 필수 파일
  [DATA]  outputs/latest/ 디렉토리 (csv는 Run 전 없어도 WARNING)
  [YAML]  sfd_daily.yml 존재 + outputs/latest copy step
  [GIT]   불필요 파일 경고 (실패 아님)
"""

import os
import sys
import subprocess
from pathlib import Path

PIPELINE_ROOT = Path(os.environ.get(
    "SFD_PIPELINE",
    r"D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline"
))
REPO_ROOT = Path(os.environ.get(
    "SFD_REPO",
    r"D:\AI_WorkSpace\I_SFC\09_Implementation\sfd-pipeline"
))
ENV_PATH      = PIPELINE_ROOT / ".env"
OUTPUT_LATEST = PIPELINE_ROOT / "outputs" / "latest"
TOOLS_DIR     = PIPELINE_ROOT / "tools"
YML_PATH      = REPO_ROOT / ".github" / "workflows" / "sfd_daily.yml"

# 탐색 루트: root + tools/ 서브폴더를 양쪽 repo 모두 포함
SEARCH_ROOTS = [
    PIPELINE_ROOT,
    PIPELINE_ROOT / "tools",
    REPO_ROOT,
    REPO_ROOT / "tools",
]

# tools/ 전용 탐색 루트 (REQUIRED_TOOL_FILES용)
TOOL_SEARCH_ROOTS = [
    PIPELINE_ROOT / "tools",
    PIPELINE_ROOT,
    REPO_ROOT / "tools",
    REPO_ROOT,
]

# 핵심 파일: SEARCH_ROOTS 중 어디든 있으면 PASS
REQUIRED_PY_FILES = [
    "sfd_signal_aggregator.py",
    "sfd_macro_radar.py",
    "sfd_sector_injector.py",
    "sfd_global_trigger.py",
    "sfd_sector_strength.py",
    "sfd_dart_booster.py",
    "sfd_hoga_score.py",
    "sfd_trade_guardian.py",
    "sfd_backtest_d1.py",
    "sfd_investor_flow_fetch.py",
]

REQUIRED_TOOL_FILES = [
    "sfd_candle_pattern.py",
    "sfd_backtest_analyzer_v2.py",
    "sfd_signal_quality.py",
    "sfd_competitive_scan.py",
    "sfd_threshold_optimizer.py",
]

REQUIRED_ENV_KEYS = ["KIS_APP_KEY", "KIS_APP_SECRET", "KIS_ACCOUNT_NO", "DART_API_KEY"]

_results = []
_fail = False

def _check(label, ok, msg="", warn_only=False):
    global _fail
    if ok:
        icon = "OK"
    elif warn_only:
        icon = "WW"  # warning
    else:
        icon = "XX"
    line = f"  [{icon}] {label}"
    if msg:
        line += f"  ({msg})"
    print(line)
    _results.append({"label": label, "pass": ok or warn_only, "msg": msg})
    if not ok and not warn_only:
        _fail = True
    return ok


def check_env():
    print("\n[ENV] .env file and required keys")
    if not ENV_PATH.exists():
        _check(".env exists", False, f"not found: {ENV_PATH}")
        return
    _check(".env exists", True)
    lines = ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    for key in REQUIRED_ENV_KEYS:
        _check(f"  {key}", any(l.startswith(f"{key}=") for l in lines))
    sl = [l for l in lines if l.startswith("KIS_APP_SECRET=")]
    if sl:
        val = sl[0].split("=", 1)[1].strip()
        ok = "\n" not in val and "\r" not in val and len(val) > 10
        _check("  APP_SECRET no newline", ok, "OK" if ok else "re-enter required")


def check_python_files():
    """SEARCH_ROOTS 중 어느 경로에 있어도 PASS"""
    print("\n[FILE] Core Python files (pipeline/repo/tools subfolder included)")
    for fname in REQUIRED_PY_FILES:
        found_in = next((r for r in SEARCH_ROOTS if (r / fname).exists()), None)
        ok = found_in is not None
        if ok:
            try:
                loc = str(found_in.relative_to(PIPELINE_ROOT.parent)).replace("\\", "/")
            except ValueError:
                loc = str(found_in)
        else:
            loc = "NOT FOUND"
        _check(fname, ok, loc)


def check_tool_files():
    print("\n[TOOLS] tools/ required files (searching both pipeline/repo)")
    for fname in REQUIRED_TOOL_FILES:
        found_in = next((r for r in TOOL_SEARCH_ROOTS if (r / fname).exists()), None)
        ok = found_in is not None
        if ok:
            try:
                loc = str(found_in.relative_to(PIPELINE_ROOT.parent)).replace("\\", "/")
            except ValueError:
                loc = str(found_in)
        else:
            loc = "NOT FOUND"
        _check(fname, ok, loc)
    # BM-14 구문 검사
    bm14 = next((r / "sfd_candle_pattern.py" for r in TOOL_SEARCH_ROOTS
                  if (r / "sfd_candle_pattern.py").exists()), None)
    if bm14 is not None and bm14.exists():
        try:
            import ast
            ast.parse(bm14.read_text(encoding="utf-8"))
            _check("sfd_candle_pattern.py syntax", True)
        except SyntaxError as e:
            _check("sfd_candle_pattern.py syntax", False, str(e))


def check_output_dir():
    """outputs/latest/ 디렉토리만 확인. CSV는 Run 전에 없어도 WARNING"""
    print("\n[DATA] outputs/latest/ directory")
    if not OUTPUT_LATEST.exists():
        _check("outputs/latest/ directory", False, f"missing: {OUTPUT_LATEST}")
        return
    _check("outputs/latest/ directory", True)
    # signal_input.csv: Run 전 없어도 WARNING (FAIL 아님)
    csv_ok = (OUTPUT_LATEST / "signal_input.csv").exists()
    _check("  signal_input.csv", csv_ok,
           "exists" if csv_ok else "normal before Run (WARN only)",
           warn_only=not csv_ok)


def check_yaml():
    print("\n[YAML] sfd_daily.yml")
    if not YML_PATH.exists():
        _check("sfd_daily.yml", False, f"missing: {YML_PATH}")
        return
    _check("sfd_daily.yml", True)
    content = YML_PATH.read_text(encoding="utf-8", errors="replace")
    _check("  outputs/latest copy step", "outputs/latest" in content)
    # on.push 는 없어도 WARNING (schedule 기반 yml이면 정상)
    has_push = "push" in content
    _check("  on.push trigger", has_push,
           "exists" if has_push else "schedule-based yml - OK",
           warn_only=not has_push)


def check_git_junk():
    """cd/copy/git 등 잘못된 파일이 repo에 있는지 경고"""
    print("\n[GIT] checking for unnecessary files in repo")
    junk_names = {"cd", "copy", "git", "dir", "ls"}
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10
        )
        lines  = result.stdout.strip().splitlines()
        dirty  = [l for l in lines if l.strip()]
        junks  = [l for l in dirty if any(
            Path(l[3:].strip()).name.lower() in junk_names for _ in [1]
        )]
        if junks:
            print(f"  [WW] unnecessary files detected - recommend deletion:")
            for j in junks:
                print(f"    {j}")
        elif dirty:
            print(f"  [WW] uncommitted {len(dirty)} files (review before deploy)")
        else:
            print("  [OK] working tree clean")
    except Exception as e:
        print(f"  [WW] git check skipped ({e})")


def main():
    print("=" * 55)
    print("SFD Preflight v2.2")
    print(f"pipeline: {PIPELINE_ROOT}")
    print(f"repo    : {REPO_ROOT}")
    print("=" * 55)

    check_env()
    check_python_files()
    check_tool_files()
    check_output_dir()
    check_yaml()
    check_git_junk()

    total  = len(_results)
    passed = sum(1 for r in _results if r["pass"])
    failed = total - passed

    print("\n" + "=" * 55)
    print(f"RESULT: {passed}/{total} PASS  |  {failed} FAIL")
    if _fail:
        print("PREFLIGHT FAILED - fix the above items before push")
        sys.exit(1)
    else:
        print("ALL PASS - ready to push")
        print("  next: .\\scripts\\run93_deploy.ps1")
        sys.exit(0)


if __name__ == "__main__":
    main()
