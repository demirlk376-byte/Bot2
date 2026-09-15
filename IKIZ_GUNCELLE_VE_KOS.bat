@echo off
chcp 65001 >nul
setlocal
title IKIZ - guncelle ve kos

REM ============================================================
REM  Tek tikla: en son kodu indirir, acar, kosar.
REM  Git gerekmez. Masaustune koyup cift tikla, yeter.
REM ============================================================

set "DAL=claude/btc-intraday-trading-engine-U2C8A"
set "ZIPURL=https://github.com/demirlk376-byte/Bot2/archive/refs/heads/%DAL%.zip"
set "HEDEF=%USERPROFILE%\Desktop\IKIZ"
set "ZIP=%TEMP%\ikiz.zip"

echo.
echo   [1/4] En son kod indiriliyor...
powershell -NoProfile -Command ^
  "$ErrorActionPreference='Stop'; Invoke-WebRequest -Uri '%ZIPURL%' -OutFile '%ZIP%' -UseBasicParsing" 2>nul
if errorlevel 1 (
  echo   HATA: indirilemedi. Depo gizliyse tarayicidan indirmen gerekebilir.
  pause & exit /b 1
)

echo   [2/4] Aciliyor...
if exist "%HEDEF%" rmdir /s /q "%HEDEF%"
powershell -NoProfile -Command ^
  "$ErrorActionPreference='Stop'; Expand-Archive -Path '%ZIP%' -DestinationPath '%TEMP%\ikizx' -Force" 2>nul
if errorlevel 1 ( echo   HATA: acilamadi. & pause & exit /b 1 )
for /d %%D in ("%TEMP%\ikizx\*") do move "%%D" "%HEDEF%" >nul
rmdir /s /q "%TEMP%\ikizx" 2>nul
del "%ZIP%" 2>nul

cd /d "%HEDEF%"
echo   [3/4] Paketler kontrol ediliyor...
py -m pip install -q -r requirements.txt

echo   [4/4] Hangi kosu?
echo.
echo      1 = KISA test    (1 ay,  ~5 dk)
echo      2 = TAM kosu     (3.3 yil, ~30 dk)
echo.
set /p SECIM="   Sec (1 veya 2): "
if "%SECIM%"=="2" (py ikiz_tam.py) else (py ikiz_duman.py)

echo.
echo   === BITTI. Kapatmak icin bir tusa bas ===
pause >nul
