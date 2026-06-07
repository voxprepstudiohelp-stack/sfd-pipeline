# scripts/run93_deploy.ps1
# SFD Pipeline — Run #93 Deploy
# 전제: GitHub Actions 예산 리셋(2026-06-29) 이후 실행
# 동작: sfd_daily_v10.4.yml → sfd_daily.yml 활성화 + push
# 작성: Claude Sonnet 4.6 | 2026-06-07

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot   = Split-Path -Parent $PSScriptRoot
$wfDir      = Join-Path $repoRoot ".github\workflows"
$srcYml     = Join-Path $wfDir "sfd_daily_v10.4.yml"
$dstYml     = Join-Path $wfDir "sfd_daily.yml"
$actionsUrl = "https://github.com/voxprepstudiohelp-stack/sfd-pipeline/actions"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  SFD Pipeline --- Run #93 Deploy" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  작업 내용:" -ForegroundColor Yellow
Write-Host "    [1] sfd_daily_v10.4.yml  ->  sfd_daily.yml  (복사)"
Write-Host "    [2] sfd_daily_v10.4.yml  삭제"
Write-Host "    [3] git add .github/workflows/"
Write-Host "    [4] git commit -m 'feat: activate sfd_daily.yml V10.4 for Run #93'"
Write-Host "    [5] git push origin main"
Write-Host ""
Write-Host "  !! GitHub Actions 예산 리셋(2026-06-29) 이후에만 실행하세요 !!" -ForegroundColor Red
Write-Host ""

$confirm = Read-Host "계속 진행하시겠습니까? (Y/N)"
if ($confirm -notin @("Y", "y")) {
    Write-Host ""
    Write-Host "[ABORT] 배포가 취소되었습니다." -ForegroundColor Yellow
    exit 0
}

Write-Host ""

# ── Step 0: 사전 점검 ────────────────────────────────────────────────────
if (-not (Test-Path $srcYml)) {
    Write-Host "[ERROR] 소스 파일 없음: $srcYml" -ForegroundColor Red
    Write-Host "        현재 위치에서 스크립트를 실행했는지 확인하세요." -ForegroundColor Red
    exit 1
}

if (Test-Path $dstYml) {
    Write-Host "[WARN]  $dstYml 이미 존재합니다. 덮어씁니다." -ForegroundColor Yellow
}

# ── Step 1: 복사 ─────────────────────────────────────────────────────────
Write-Host "[1/5] 복사: sfd_daily_v10.4.yml  ->  sfd_daily.yml" -ForegroundColor Green
Copy-Item -Path $srcYml -Destination $dstYml -Force
if (-not (Test-Path $dstYml)) {
    Write-Host "[ERROR] 복사 실패: $dstYml 생성되지 않음" -ForegroundColor Red
    exit 1
}
Write-Host "       OK: $dstYml"

# ── Step 2: 삭제 ─────────────────────────────────────────────────────────
Write-Host "[2/5] 삭제: sfd_daily_v10.4.yml" -ForegroundColor Green
Remove-Item -Path $srcYml -Force
Write-Host "       OK"

# ── Step 3: git add ───────────────────────────────────────────────────────
Write-Host "[3/5] git add .github/workflows/" -ForegroundColor Green
git -C $repoRoot add ".github/workflows/"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] git add 실패 (exit $LASTEXITCODE)" -ForegroundColor Red
    exit 1
}
Write-Host "       OK"

# ── Step 4: git commit ────────────────────────────────────────────────────
Write-Host "[4/5] git commit" -ForegroundColor Green
git -C $repoRoot commit -m "feat: activate sfd_daily.yml V10.4 for Run #93"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] git commit 실패 (exit $LASTEXITCODE)" -ForegroundColor Red
    exit 1
}
Write-Host "       OK"

# ── Step 5: git push ──────────────────────────────────────────────────────
Write-Host "[5/5] git push origin main" -ForegroundColor Green
git -C $repoRoot push origin main
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] git push 실패 (exit $LASTEXITCODE)" -ForegroundColor Red
    Write-Host "        수동으로 실행하세요: git push origin main" -ForegroundColor Yellow
    exit 1
}
Write-Host "       OK"

# ── 완료 ─────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Run #93 triggered." -ForegroundColor Green
Write-Host "  Check: $actionsUrl" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
