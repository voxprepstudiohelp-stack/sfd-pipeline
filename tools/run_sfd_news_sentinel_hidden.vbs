Option Explicit

Dim shell, command, exitCode
Set shell = CreateObject("WScript.Shell")

command = "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File ""D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline\tools\run_sfd_news_sentinel.ps1"""
exitCode = shell.Run(command, 0, True)

WScript.Quit exitCode
