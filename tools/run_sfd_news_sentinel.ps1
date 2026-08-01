$ErrorActionPreference = 'Stop'

$python = 'C:\Users\ncssd\AppData\Local\Microsoft\WindowsApps\python.exe'
$script = 'D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline\tools\sfd_news_sentinel.py'
$environmentNames = @(
    'NOTIFY_KAKAO_TOKEN',
    'NOTIFY_KAKAO_REFRESH_TOKEN',
    'KAKAO_REST_API_KEY',
    'KAKAO_CLIENT_SECRET'
)

[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

foreach ($name in $environmentNames) {
    $value = [Environment]::GetEnvironmentVariable($name, 'User')
    if ($value) {
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
}

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python 실행 파일을 찾을 수 없습니다: $python"
}
if (-not (Test-Path -LiteralPath $script)) {
    throw "뉴스 감시 스크립트를 찾을 수 없습니다: $script"
}

& $python $script
exit $LASTEXITCODE
