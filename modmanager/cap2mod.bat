@echo off
rem Capitalism 2 Mod Manager launcher (Windows). No arguments = GUI.
rem Picks the first Python 3.8+ that can run the GUI (tkinter/Tcl) - some installs lack Tcl.
setlocal
cd /d "%~dp0"
set "TEST=import sys, tkinter; assert sys.version_info >= (3, 8); tkinter.Tcl()"
if not "%~1"=="" if /i not "%~1"=="gui" set "TEST=import sys, json; assert sys.version_info >= (3, 8)"
set "PYCMD="
for %%V in (3 3.13 3.12 3.11 3.10 3.9 3.8) do (
  if not defined PYCMD (
    py -%%V -c "%TEST%" >nul 2>nul && set "PYCMD=py -%%V"
  )
)
if not defined PYCMD (
  python -c "%TEST%" >nul 2>nul && set "PYCMD=python"
)
if not defined PYCMD (
  echo [cap2mod] No usable Python 3.8+ with tkinter was found.
  echo Install Python from https://www.python.org/downloads/ with "tcl/tk and IDLE" checked.
  pause
  exit /b 1
)
%PYCMD% cap2mod.py %*
if errorlevel 1 if "%~1"=="" pause
endlocal
