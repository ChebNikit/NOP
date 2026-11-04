@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "NOP_PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe" set "NOP_PS=%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
pushd "%~dp0"
if errorlevel 1 exit /b 1
"%NOP_PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_build.ps1"
set "NOP_RESULT=%errorlevel%"
popd
if not "%NOP_NONINTERACTIVE%"=="1" pause
exit /b %NOP_RESULT%
