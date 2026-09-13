@echo off
chcp 65001 >nul 2>nul
setlocal
cd /d "%~dp0"

set "ramtest=data\xg140_initramfs_test.py"
if not exist "%ramtest%" set "ramtest=ursusflasher\src\xg140_initramfs_test.py"
set "backup=data\xg140_full_backup.ps1"
if not exist "%backup%" set "backup=ursusflasher\src\xg140_full_backup.ps1"

if not exist "%ramtest%" (
  echo XG-140G-MD initramfs RAM-test backend not found.
  set "rc=2"
  goto done
)
if not exist "%backup%" (
  echo XG-140G-MD backup helper not found.
  set "rc=2"
  goto done
)

echo ============================================================
echo XG-140G-MD FULL READ-ONLY BACKUP
echo Existing initramfs only - no firmware build will be started.
echo First stage boots the selected initramfs to RAM over UART.
echo Second stage reads /dev/mtd* over SSH and stores gzip backups.
echo ============================================================
echo.

where py >nul 2>nul
if not errorlevel 1 goto use_py
where python >nul 2>nul
if not errorlevel 1 goto use_python
echo Python 3 not found.
set "rc=1"
goto done

:use_py
py -3 "%ramtest%"
set "rc=%errorlevel%"
goto after_ram

:use_python
python "%ramtest%"
set "rc=%errorlevel%"

:after_ram
if not "%rc%"=="0" goto done
echo.
echo OpenWrt initramfs should now be running from RAM.
echo Connect the PC to the router LAN if not already connected.
echo Starting read-only MTD backup...
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%backup%"
set "rc=%errorlevel%"

:done
if not "%rc%"=="0" (
  echo.
  echo Press Enter to close / Нажмите Enter для закрытия...
  pause >nul
)
exit /b %rc%
