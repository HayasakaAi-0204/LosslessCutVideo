@echo off
title Dong goi ung dung Lossless Video Cutter
cd /d "%~dp0"

echo ======================================================================
echo    BAT DAU DONG GOI UNG DUNG LOSSLESS VIDEO CUTTER
echo ======================================================================
echo.

set PYTHON_CMD=python
if exist ".venv\Scripts\python.exe" (
    set PYTHON_CMD=.venv\Scripts\python.exe
    echo [*] Su dung moi truong ao: .venv\Scripts\python.exe
) else (
    echo [*] Su dung Python he thong: python
)

echo [*] Kiem tra thu vien PyInstaller...
%PYTHON_CMD% -m pip show pyinstaller > nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Dang cai dat PyInstaller vao moi truong...
    %PYTHON_CMD% -m pip install pyinstaller
)

echo [*] Kiem tra thu vien python-mpv...
%PYTHON_CMD% -m pip show python-mpv > nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Dang cai dat python-mpv vao moi truong...
    %PYTHON_CMD% -m pip install python-mpv
)

echo.
echo [*] Bat dau qua trinh build va nen ZIP...
%PYTHON_CMD% package_app.py --mode onedir

echo.
echo ======================================================================
pause
