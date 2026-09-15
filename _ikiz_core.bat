@echo off
setlocal
REM ============================================================
REM  IKIZ ortak cekirdek. %1 = kosulacak python dosyasi.
REM  ONEMLI: bu dosya SAF ASCII olmali. Turkce karakter veya
REM  sembol (UTF-8 cok baytli) CMD'nin ayristiricisini bozuyor
REM  ve "'DAL' is not recognized" gibi hatalar veriyor.
REM ============================================================

set "DAL=claude/btc-intraday-trading-engine-U2C8A"
set "ZIPURL=https://github.com/demirlk376-byte/Bot2/archive/refs/heads/%DAL%.zip"
set "HEDEF=%USERPROFILE%\Desktop\IKIZ"
set "ZIP=%TEMP%\ikiz.zip"
set "SAKLA=%TEMP%\ikiz_sakla"

echo.
echo   [1/4] En son kod indiriliyor...
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%ZIPURL%' -OutFile '%ZIP%' -UseBasicParsing" 2>nul
if errorlevel 1 goto :indirme_hatasi

echo   [2/4] Aciliyor...
REM Kullanici dosyalarini sakla (.env ve uretilmis sonuclar)
if not exist "%SAKLA%" mkdir "%SAKLA%" >nul 2>&1
if exist "%HEDEF%\.env" copy /y "%HEDEF%\.env" "%SAKLA%\" >nul 2>&1
if exist "%HEDEF%\ikiz_tam_islemler.csv" copy /y "%HEDEF%\ikiz_tam_islemler.csv" "%SAKLA%\" >nul 2>&1
if exist "%HEDEF%\ikiz_trades.db" copy /y "%HEDEF%\ikiz_trades.db*" "%SAKLA%\" >nul 2>&1

if exist "%TEMP%\ikizx" rmdir /s /q "%TEMP%\ikizx" 2>nul
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; Expand-Archive -Path '%ZIP%' -DestinationPath '%TEMP%\ikizx' -Force" 2>nul
if errorlevel 1 goto :acma_hatasi

REM Yeni kodu yerine koy (eski klasor ancak BURADA silinir)
if exist "%HEDEF%" rmdir /s /q "%HEDEF%"
for /d %%D in ("%TEMP%\ikizx\*") do move "%%D" "%HEDEF%" >nul
rmdir /s /q "%TEMP%\ikizx" 2>nul
del "%ZIP%" >nul 2>&1
if not exist "%HEDEF%\ikiz_tam.py" goto :acma_hatasi

REM Kullanici dosyalarini geri koy
copy /y "%SAKLA%\*" "%HEDEF%\" >nul 2>&1
rmdir /s /q "%SAKLA%" 2>nul

cd /d "%HEDEF%"
echo   [3/4] Paketler kontrol ediliyor...
py -m pip install -q -r requirements.txt

echo   [4/4] Kosu basliyor: %1
echo.
py %1
goto :bitti

:indirme_hatasi
echo.
echo   HATA: kod indirilemedi. Internet baglantisini kontrol et.
goto :bitti

:acma_hatasi
echo.
echo   HATA: arsiv acilamadi. Eski klasor KORUNDU, veri kaybi yok.
echo   Cozum: ZIP'i tarayicidan elle indir.
goto :bitti

:bitti
echo.
echo   ================================================
echo    BITTI. Ekrandaki tabloyu Claude'a gonder.
echo    Kapatmak icin bir tusa bas.
echo   ================================================
pause >nul
