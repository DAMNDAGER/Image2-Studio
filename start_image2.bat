@echo off
setlocal
cd /d "%~dp0"

start "Image2 Studio" powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_image2.ps1"

set "IMAGE2_URL=http://127.0.0.1:8765/"
set /a IMAGE2_ATTEMPTS=0

:wait_for_image2
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "try { $response = Invoke-WebRequest -UseBasicParsing -Uri '%IMAGE2_URL%' -TimeoutSec 2; if ($response.StatusCode -eq 200) { exit 0 }; exit 1 } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 goto open_image2
set /a IMAGE2_ATTEMPTS+=1
if %IMAGE2_ATTEMPTS% GEQ 60 goto image2_timeout
timeout /t 1 /nobreak >nul
goto wait_for_image2

:open_image2
start "" "%IMAGE2_URL%"
exit /b 0

:image2_timeout
echo Image2 service did not become ready within 30 seconds.
exit /b 1
