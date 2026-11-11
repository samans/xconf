@echo off
REM Convenience wrapper so the PowerShell launcher can be called from
REM cmd.exe (or double-clicked) without adjusting the execution policy.
REM
REM Usage:  run.cmd start all
REM         run.cmd stop client
REM         run.cmd status
REM         run.cmd reset all
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
