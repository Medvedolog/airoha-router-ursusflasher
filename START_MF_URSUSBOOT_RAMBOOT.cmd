@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "RC=9009"

where python >nul 2>nul
if not errorlevel 1 goto :run_python

where py >nul 2>nul
if not errorlevel 1 goto :run_py

echo [ERROR] Python 3.12+ not found.
goto :done

:run_python
python data\mf_ramboot.py
set "RC=%ERRORLEVEL%"
goto :done

:run_py
py -3 data\mf_ramboot.py
set "RC=%ERRORLEVEL%"
goto :done

:done
echo.
echo MF2 RAMBOOT launcher finished. Exit code: %RC%
echo Press any key to close this window...
pause >nul
exit /b %RC%
