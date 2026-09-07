@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
copy /b parts\openwrt-sdk-r35906.tar.zst.part00+parts\openwrt-sdk-r35906.tar.zst.part01 openwrt-sdk-r35906.tar.zst >nul
if errorlevel 1 exit /b 1
for /f "tokens=1" %%H in (SDK_SHA256SUMS) do set EXPECTED=%%H
for /f "tokens=1" %%H in ('certutil -hashfile openwrt-sdk-r35906.tar.zst SHA256 ^| findstr /r /v "hash CertUtil"') do set ACTUAL=%%H
if /i not "!ACTUAL!"=="!EXPECTED!" (
  echo SDK SHA256 mismatch
  del /q openwrt-sdk-r35906.tar.zst 2>nul
  exit /b 1
)
echo %CD%\openwrt-sdk-r35906.tar.zst
