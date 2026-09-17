@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
where py >nul 2>nul && (py -3 ursusflasher\src\expert_item4_initramfs_test.py & exit /b %errorlevel%)
python ursusflasher\src\expert_item4_initramfs_test.py
exit /b %errorlevel%
