@echo off
rem Capitalism 2 모드 매니저 런처 (Windows). 인수 없이 실행하면 GUI.
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 cap2mod.py %*
) else (
  python cap2mod.py %*
)
if errorlevel 1 if "%~1"=="" pause
endlocal
