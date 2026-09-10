@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "RC=9009"
set "SCRIPT=data\mf_recovery.py"
if not exist "%SCRIPT%" set "SCRIPT=ursusflasher\src\mf_recovery.py"

where python >nul 2>nul
if not errorlevel 1 goto :run_python

where py >nul 2>nul
if not errorlevel 1 goto :run_py

echo [ERROR] Python 3.12+ not found.
goto :done

:run_python
python "%SCRIPT%" %*
set "RC=%ERRORLEVEL%"
goto :done

:run_py
py -3 "%SCRIPT%" %*
set "RC=%ERRORLEVEL%"
goto :done

:done
echo.
echo MF UrsusBoot RAM recovery finished. Exit code: %RC%
echo Press any key to close this window...
pause >nul
exit /b %RC%
