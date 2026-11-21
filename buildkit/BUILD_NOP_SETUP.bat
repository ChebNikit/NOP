@echo off
setlocal
rem NOP 1.1 - builds dist\NOP_Setup.exe. Needs Windows 10/11 x64 and an internet connection for the first run.
rem Options are passed through:  BUILD_NOP_SETUP.bat --offline | --skip-verify | --verify-install | --clean
title NOP 1.1 - building the installer
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build\stage0.ps1" %*
set CODE=%ERRORLEVEL%
echo.
if not "%CODE%"=="0" (
  echo The build did not finish. Read the message above; see README.md - Troubleshooting.
) else (
  echo Finished. The installer is in the "dist" folder.
)
if /I not "%NOP_NOPAUSE%"=="1" pause
exit /b %CODE%
