@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul && (py -3 data\master.py & exit /b %errorlevel%)
where python >nul 2>nul && (python data\master.py & exit /b %errorlevel%)
echo Python 3 not found. Install Python 3 and run START.cmd again.
exit /b 1
