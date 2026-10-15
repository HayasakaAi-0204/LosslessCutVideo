@echo off
chcp 65001 > nul
title Đóng gói ứng dụng Lossless Video Cutter

echo ======================================================================
echo    BẮT ĐẦU ĐÓNG GÓI ỨNG DỤNG LOSSLESS VIDEO CUTTER
echo ======================================================================
echo.

cd /d "%~dp0"

set PYTHON_CMD=python
if exist ".venv\Scripts\python.exe" (
    set PYTHON_CMD=.venv\Scripts\python.exe
    echo [*] Sử dụng môi trường ảo: .venv\Scripts\python.exe
) else (
    echo [*] Sử dụng Python hệ thống: python
)

echo [*] Kiểm tra thư viện PyInstaller...
%PYTHON_CMD% -m pip show pyinstaller > nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Đang cài đặt PyInstaller vào môi trường...
    %PYTHON_CMD% -m pip install pyinstaller
)

echo.
echo [*] Bắt đầu quá trình build và nén ZIP...
%PYTHON_CMD% package_app.py --mode onedir

echo.
echo ======================================================================
pause

