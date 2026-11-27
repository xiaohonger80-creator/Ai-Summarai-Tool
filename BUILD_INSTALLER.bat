@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Ai Summarai - Windows App Builder

set "PY_CMD="

:: 1. Check python directly
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1
if not errorlevel 1 set "PY_CMD=python"

:: 2. Check py launcher
if not defined PY_CMD (
    py -3 -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PY_CMD=py -3"
)

:: 3. Check virtualenvs
if not defined PY_CMD (
    if exist ".venv\Scripts\python.exe" set "PY_CMD=%~dp0.venv\Scripts\python.exe"
)
if not defined PY_CMD (
    if exist "venv\Scripts\python.exe" set "PY_CMD=%~dp0venv\Scripts\python.exe"
)

:: 4. Check AppData Python installations
if not defined PY_CMD (
    for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do (
        if exist "%%D\python.exe" set "PY_CMD=%%D\python.exe"
    )
)

:: 5. Check ProgramFiles Python installations
if not defined PY_CMD (
    for /d %%D in ("%ProgramFiles%\Python3*") do (
        if exist "%%D\python.exe" set "PY_CMD=%%D\python.exe"
    )
)

if not defined PY_CMD (
    echo [ERROR] Python 3 was not found on this system!
    echo Please install Python 3.10 or higher from https://www.python.org.
    pause
    exit /b 1
)

echo [*] Starting build process with %PY_CMD%...
%PY_CMD% "%~dp0tools\build_app.py" %*
if errorlevel 1 (
    echo [ERROR] Build process failed.
    pause
    exit /b 1
)

echo [OK] Build completed successfully.
pause
exit /b 0
