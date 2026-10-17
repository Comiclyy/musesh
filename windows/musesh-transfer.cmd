@echo off
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0musesh-transfer.ps1" %*
exit /b %errorlevel%
