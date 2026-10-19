@echo off
title Lossless Video Cutter
cd /d "%~dp0"

echo ========================================================
echo   KHOI DONG LOSSLESS VIDEO CUTTER
echo ========================================================
echo.

set "PATH=%~dp0tools;%PATH%"
set "PY_CMD="

rem 1. Uu tien moi truong ao .venv trong thu muc du an
if not exist "%~dp0.venv\Scripts\python.exe" goto :check_system_python
"%~dp0.venv\Scripts\python.exe" -c "exit(0)" >nul 2>&1
if errorlevel 1 goto :check_system_python
set "PY_CMD=%~dp0.venv\Scripts\python.exe"
echo [*] Da nhan dien moi truong ao .venv.
goto :launch

:check_system_python
echo [*] Dang tim kiem trinh thuc thi Python he thong...
python -c "exit(0)" >nul 2>&1
if errorlevel 1 goto :check_py_launcher
set "PY_CMD=python"
echo [*] Tim thay trinh thuc thi: python
goto :launch

:check_py_launcher
py -c "exit(0)" >nul 2>&1
if errorlevel 1 goto :no_python
set "PY_CMD=py"
echo [*] Tim thay trinh thuc thi: py
goto :launch

:no_python
echo ========================================================
echo [LOI] Khong tim thay trinh thuc thi Python tren may tinh!
echo Vui long cai dat Python 3.10 tro len tai:
echo   https://www.python.org/downloads/
echo (Luu y: Nho tich chon vao muc "Add Python to PATH" khi cai).
echo ========================================================
echo.
pause
exit /b 1

:launch
echo [*] Dang khoi chay ung dung...
echo.

"%PY_CMD%" "%~dp0main.py"

if errorlevel 1 (
    echo.
    echo ========================================================
    echo [THONG BAO] Ung dung da dung lai voi ma loi: %errorlevel%.
    echo Neu can ho tro, vui long chup lai toan bo man hinh cmd nay.
    echo ========================================================
    echo.
    pause
)
