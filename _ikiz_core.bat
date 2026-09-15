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
REM ⚠ .env'i KORU: klasoru silmeden once yedekle, actiktan sonra geri koy.
REM (Ilk surum klasoru komple siliyordu ve kullanicinin kopyaladigi .env
REM  her guncellemede uçuyordu -> "konfigurasyon: .env YOK" uyarisi.)
REM .env VE uretilmis sonuc dosyalarini koru
set "ENVYEDEK="
if exist "%HEDEF%\.env" (
  copy /y "%HEDEF%\.env" "%TEMP%\ikiz_env_yedek" >nul
  set "ENVYEDEK=1"
)
if not exist "%TEMP%\ikiz_veri" mkdir "%TEMP%\ikiz_veri" >nul 2>&1
if exist "%HEDEF%\ikiz_tam_islemler.csv" copy /y "%HEDEF%\ikiz_tam_islemler.csv" "%TEMP%\ikiz_veri\" >nul
if exist "%HEDEF%\ikiz_trades.db" copy /y "%HEDEF%\ikiz_trades.db" "%TEMP%\ikiz_veri\" >nul
if exist "%HEDEF%" rmdir /s /q "%HEDEF%"
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; Expand-Archive -Path '%ZIP%' -DestinationPath '%TEMP%\ikizx' -Force" 2>nul
if errorlevel 1 ( echo   HATA: acilamadi. & pause & exit /b 1 )
for /d %%D in ("%TEMP%\ikizx\*") do move "%%D" "%HEDEF%" >nul
rmdir /s /q "%TEMP%\ikizx" 2>nul
del "%ZIP%" 2>nul
REM ⚠ ACMA BASARILI MI? Degilse DUR -- yarim klasor birakma (bir kez
REM  klasoru silip kodu koyamadi ve kullanicinin CSV'si ucup gitti).
if not exist "%HEDEF%\ikiz_tam.py" (
  echo.
  echo   HATA: kod acilamadi. Klasor eksik kaldi.
  echo   Cozum: %HEDEF% klasorunu silip ZIP'i elle indir.
  pause & exit /b 1
)

if defined ENVYEDEK (
  copy /y "%TEMP%\ikiz_env_yedek" "%HEDEF%\.env" >nul
  del "%TEMP%\ikiz_env_yedek" >nul
  echo        .env korundu ve geri konuldu.
)
if exist "%TEMP%\ikiz_veri\*" (
  copy /y "%TEMP%\ikiz_veri\*" "%HEDEF%\" >nul 2>&1
  echo        onceki kosu sonuclari korundu.
)

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
