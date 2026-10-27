@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal enabledelayedexpansion

for /f %%a in ('powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 ^| Where-Object {$_.InterfaceAlias -notmatch 'Loopback' -and $_.IPAddress -notlike '169.*'} ^| Select-Object -First 1).IPAddress"') do set IP=%%a

echo.
echo   ============================================
echo    考研英语核心词 · 手机访问
echo   ============================================
echo.
echo    1. 手机和电脑连同一个 WiFi
echo    2. 手机浏览器打开下面地址：
echo.
echo       http://!IP!:8899/考研核心词.html
echo.
echo    3. 学习进度自动存在手机浏览器里
echo    4. 用完关掉这个窗口即可
echo.
echo   ============================================
echo.

python -m http.server 8899
pause
