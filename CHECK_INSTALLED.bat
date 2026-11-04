@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
set "NOP_REPORT=%TEMP%\NOP-functional-check.json"
if not exist "%~dp0NOP.exe" (echo NOP.exe is missing& pause& exit /b 1)
del /q "%NOP_REPORT%" 2>nul
if exist "%NOP_REPORT%" (echo Report is locked. Close it and retry.& pause& exit /b 1)
set "PYTHONHOME="
set "PYTHONPATH="
set "QT_PLUGIN_PATH="
set "QT_QPA_PLATFORM_PLUGIN_PATH="
set "YAMI_BACKEND="
set "PATH=%SystemRoot%\System32;%SystemRoot%"
echo Testing this Windows host. A NOP test window will appear.
start "" /wait "%~dp0NOP.exe" --nop-functional-check "%NOP_REPORT%"
set "NOP_RESULT=%errorlevel%"
echo Exit code: %NOP_RESULT%
echo Report: %NOP_REPORT%
if exist "%NOP_REPORT%" powershell.exe -NoProfile -Command "Get-Content -LiteralPath $env:NOP_REPORT -Raw -Encoding UTF8"
pause
exit /b %NOP_RESULT%
