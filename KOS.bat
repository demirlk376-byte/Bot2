@echo off
REM ============================================================
REM  IKIZ - guncelle ve kos (GIT surumu)
REM  Klasoru SILMEZ, hicbir dosyayi ucurmaz. Sadece `git pull`
REM  yapip istenen betigi kosar. .env ve sonuc dosyalari kalir.
REM  Kullanim:  KOS.bat ikiz_tam.py
REM             KOS.bat ikiz_paralel.py risk
REM             KOS.bat ikiz_coin_analiz.py
REM ============================================================
cd /d "%~dp0"
echo.
echo   [1/3] Kod guncelleniyor (git pull)...
git pull
if errorlevel 1 (
  echo   UYARI: git pull basarisiz. Mevcut kodla devam ediliyor.
)
echo   [2/3] Paketler kontrol ediliyor...
py -m pip install -q -r requirements.txt
echo   [3/3] Kosu: %*
echo.
if "%~1"=="" (
  echo   Hangi betik kosulacak belirtilmedi.
  echo   Ornek:  KOS.bat ikiz_paralel.py risk
  pause & exit /b 1
)
py %*
echo.
echo   ================================================
echo    BITTI. Kapatmak icin bir tusa bas.
echo   ================================================
pause >nul
