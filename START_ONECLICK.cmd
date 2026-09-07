@echo off
chcp 65001 >nul 2>nul
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 goto use_py
where python >nul 2>nul
if not errorlevel 1 goto use_python
echo Python 3 not found.
set "rc=1"
goto done
:use_py
py -3 data\one_key.py
set "rc=%errorlevel%"
goto done
:use_python
python data\one_key.py
set "rc=%errorlevel%"
:done
echo.
echo Press Enter to close / Нажмите Enter для закрытия...
pause >nul
exit /b %rc%
