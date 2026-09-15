@echo off
chcp 65001 >nul
REM Ortak cekirdek. %1 = kosulacak python dosyasi.
set "DAL=claude/btc-intraday-trading-engine-U2C8A"
set "ZIPURL=https://github.com/demirlk376-byte/Bot2/archive/refs/heads/%DAL%.zip"
set "HEDEF=%USERPROFILE%\Desktop\IKIZ"
set "ZIP=%TEMP%\ikiz.zip"

echo.
echo   [1/4] En son kod indiriliyor...
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; Invoke-WebRequest -Uri '%ZIPURL%' -OutFile '%ZIP%' -UseBasicParsing" 2>nul
if errorlevel 1 ( echo   HATA: indirilemedi. & pause & exit /b 1 )

echo   [2/4] Aciliyor...
if exist "%HEDEF%" rmdir /s /q "%HEDEF%"
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; Expand-Archive -Path '%ZIP%' -DestinationPath '%TEMP%\ikizx' -Force" 2>nul
if errorlevel 1 ( echo   HATA: acilamadi. & pause & exit /b 1 )
for /d %%D in ("%TEMP%\ikizx\*") do move "%%D" "%HEDEF%" >nul
rmdir /s /q "%TEMP%\ikizx" 2>nul
del "%ZIP%" 2>nul

cd /d "%HEDEF%"
echo   [3/4] Paketler kontrol ediliyor...
py -m pip install -q -r requirements.txt

echo   [4/4] Kosu basliyor: %1
echo.
py %1

echo.
echo   ================================================
echo    BITTI. Ekrandaki tabloyu Claude'a gonder.
echo    Kapatmak icin bir tusa bas.
echo   ================================================
pause >nul
