$ErrorActionPreference = 'Stop'

$taskName = 'SFD News Sentinel'
$hiddenLauncher = 'D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline\tools\run_sfd_news_sentinel_hidden.vbs'
$workingDirectory = 'D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline\tools'
$wscript = 'C:\Windows\System32\wscript.exe'

if (-not (Test-Path -LiteralPath $hiddenLauncher)) {
    throw "숨김 실행 래퍼를 찾을 수 없습니다: $hiddenLauncher"
}

$arguments = '"' + $hiddenLauncher + '"'
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

$service = New-Object -ComObject 'Schedule.Service'
$service.Connect()
$folder = $service.GetFolder('\')
$definition = $service.NewTask(0)

$definition.RegistrationInfo.Description = 'SFD RSS news monitor: hidden execution and one consolidated Kakao report card per run.'
$definition.Principal.UserId = $userId
$definition.Principal.LogonType = 3
$definition.Principal.RunLevel = 0
$definition.Settings.Enabled = $true
$definition.Settings.StartWhenAvailable = $true
$definition.Settings.ExecutionTimeLimit = 'PT10M'
$definition.Settings.MultipleInstances = 2

$trigger = $definition.Triggers.Create(2)
$trigger.StartBoundary = (Get-Date).AddMinutes(2).ToString('s')
$trigger.DaysInterval = 1
$trigger.Enabled = $true
$trigger.Repetition.Interval = 'PT30M'
$trigger.Repetition.Duration = 'P1D'
$trigger.Repetition.StopAtDurationEnd = $false

$action = $definition.Actions.Create(0)
$action.Path = $wscript
$action.Arguments = $arguments
$action.WorkingDirectory = $workingDirectory

# 6 = create/update, 3 = interactive token logon.
$folder.RegisterTaskDefinition($taskName, $definition, 6, $userId, $null, 3, $null) | Out-Null

Write-Output "REGISTERED=$taskName"
