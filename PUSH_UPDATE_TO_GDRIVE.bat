@echo off
cd /d "%~dp0"
title Ai Summarai - Push Update to Google Drive

set "PY_CMD="
if exist ".venv\Scripts\python.exe" set PY_CMD="%CD%\.venv\Scripts\python.exe"
if not defined PY_CMD if exist "venv\Scripts\python.exe" set PY_CMD="%CD%\venv\Scripts\python.exe"
if not defined PY_CMD (
    where python >nul 2>&1
    if not errorlevel 1 set PY_CMD=python
)
if not defined PY_CMD (
    where py >nul 2>&1
    if not errorlevel 1 set PY_CMD=py -3
)
if not defined PY_CMD (
    for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do (
        if exist "%%D\python.exe" set PY_CMD="%%D\python.exe"
    )
)
if not defined PY_CMD (
    for /d %%D in ("%ProgramFiles%\Python3*") do (
        if exist "%%D\python.exe" set PY_CMD="%%D\python.exe"
    )
)

if not defined PY_CMD (
    echo [ERROR] Python not found on this computer!
    echo Please install Python 3.10 or higher.
    pause
    exit /b 1
)

%PY_CMD% tools\push_to_gdrive.py
if errorlevel 1 pause
exit /b 0
