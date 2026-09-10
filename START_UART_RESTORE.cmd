@echo off
chcp 65001 >nul 2>nul
setlocal
cd /d "%~dp0"
set "entry=data\uart_bootarea_restore.py"
if not exist "%entry%" set "entry=ursusflasher\src\uart_bootarea_restore.py"
if not exist "%entry%" (
  echo [ERROR] uart_bootarea_restore.py not found.
  exit /b 2
)
where py >nul 2>nul
if not errorlevel 1 goto use_py
where python >nul 2>nul
if not errorlevel 1 goto use_python
echo Python 3 not found.
exit /b 1
:use_py
py -3 "%entry%" %*
exit /b %errorlevel%
:use_python
python "%entry%" %*
exit /b %errorlevel%
