@echo off
title Lossless Video Cutter
cd /d "%~dp0"

set PYTHON_CMD=python
if exist ".venv\Scripts\python.exe" (
    set PYTHON_CMD=.venv\Scripts\python.exe
)

REM Tu dong kiem tra va cai dat python-mpv neu chua co
%PYTHON_CMD% -m pip show python-mpv > nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Phat hien chua co python-mpv, dang cai dat...
    %PYTHON_CMD% -m pip install python-mpv
)

%PYTHON_CMD% src\main.py
