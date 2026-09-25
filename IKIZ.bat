@echo off
setlocal
cd /d "%~dp0"
title IKIZ

REM ============================================================
REM  KENDINI GUNCELLE. Cift tiklamayla acilinca kimse git pull
REM  yapmiyordu; yeni menu tuslari gelmiyor, "gecersiz secim"
REM  cikiyordu. Calisan bir .bat guncellenirse cmd sasirdigi icin
REM  yeni surum AYRI PENCEREDE baslatilir; "guncel" argumani
REM  ikinci turu isaretler, sonsuz donguye girmez.
REM ============================================================
if /i not "%~1"=="guncel" (
  echo.
  echo   Kod guncelleniyor, bekle...
  git pull
  if errorlevel 1 call :zorla
  echo   Menu yeni pencerede aciliyor...
  timeout /t 2 >nul
  start "IKIZ" "%~f0" guncel
  exit /b
)

:menu
cls
echo ==========================================================
echo    I K I Z  -  canli botun gecmis veri uzerindeki ikizi
echo ==========================================================
echo.
echo   TARAMALAR  (her biri ~25 dk, bitince RAPOR kendi gelir)
echo     1   Donchian sahte-kirilim filtreleri
echo     A   Kazananlarin birlesimi (teyit1 + hacim + korel)
echo     S   SON TARAMA - secilen filtre x risk (canli ayari verir)
echo     M   MALIYET - kayma / funding / maker girisi
echo     K   MAKER SINIRLARI - alt/ust sinir + olculen %%27
echo     F   FILTRELER x GERCEK MALIYET  (siralamayi yeniden sor)
echo     Z   SON KOSU - iki aday x risk merdiveni (canli ayari verir)
echo     C   COIN GENISLETME - 12 -^> 31 coin  (~65 dk, uzun!)
echo     S2  SON FILTRE - hacim esigi ucu + SQUEEZE hacmi
echo     Q   SQUEEZE MAKER - kaymanin en cok yedigi kol
echo     P   TEST PROTOKOLU - mum kalitesi / chase / ATR genislemesi
echo     G   GIRIS MODU - basarisiz kirilim / likidite supurmesi
echo     H   SQUEEZE GIRIS MODU - sikisma araligi kirildi mi
echo     Y   AILELER TEK TEK - yapi / fvg / ifvg / orb / sr / asia
echo     N   AYNI-YON KISITI - kar geri vermeyi engelle
echo     O   PORTFOY STOPU - acik zarar toplamina ust sinir
echo     B   CAP TAVANI - en iyi islemlere kirpilan boyut  (YENI)
echo     T   TUTUS SURESI - max_hold uzun/kisa  (YENI)
echo     W   COIN GENISLETME - squeeze 3 coinde, donchian 19/31  (YENI)
echo     2   Cikis yonetimi (basabas / ATR takibi)
echo     3   Risk seviyesi - ust aralik  (%%2.0 - %%4.0)
echo     4   Risk seviyesi - alt aralik  (%%1.0 - %%2.0)
echo     5   Korele pozisyon + risk birlesik
echo.
echo   ARACLAR
echo     6   RAPOR - mevcut sonuclari goster      (saniyeler)
echo     7   Veritabani durumu / tani             (saniyeler)
echo     8   Kisa duman testi - kurulum saglam mi (~2 dk)
echo     9   Tek tam kosu - taban                 (~25 dk)
echo.
echo     0   Cikis
echo.
set "sec="
set /p "sec=Secim: "

if "%sec%"=="1" set "ARGS=ikiz_paralel.py donchian" & goto calistir
if /i "%sec%"=="A" set "ARGS=ikiz_paralel.py eniyi" & goto calistir
if /i "%sec%"=="S" set "ARGS=ikiz_paralel.py son" & goto calistir
if /i "%sec%"=="M" set "ARGS=ikiz_paralel.py maliyet" & goto calistir
if /i "%sec%"=="K" set "ARGS=ikiz_paralel.py sinir" & goto calistir
if /i "%sec%"=="F" set "ARGS=ikiz_paralel.py fmal" & goto calistir
if /i "%sec%"=="Z" set "ARGS=ikiz_paralel.py sonrisk" & goto calistir
if /i "%sec%"=="C" set "ARGS=ikiz_paralel.py coin" & goto calistir
if /i "%sec%"=="S2" set "ARGS=ikiz_paralel.py sonfiltre" & goto calistir
if /i "%sec%"=="Q" set "ARGS=ikiz_paralel.py sqmaker" & goto calistir
if /i "%sec%"=="P" set "ARGS=ikiz_paralel.py protokol" & goto calistir
if /i "%sec%"=="G" set "ARGS=ikiz_paralel.py mod" & goto calistir
if /i "%sec%"=="H" set "ARGS=ikiz_paralel.py sqmod" & goto calistir
if /i "%sec%"=="Y" set "ARGS=ikiz_paralel.py aile" & goto calistir
if /i "%sec%"=="N" set "ARGS=ikiz_paralel.py yon" & goto calistir
if /i "%sec%"=="O" set "ARGS=ikiz_paralel.py portfoy" & goto calistir
if /i "%sec%"=="B" set "ARGS=ikiz_paralel.py cap" & goto calistir
if /i "%sec%"=="T" set "ARGS=ikiz_paralel.py tutus" & goto calistir
if /i "%sec%"=="W" set "ARGS=ikiz_paralel.py coin2" & goto calistir
if "%sec%"=="2" set "ARGS=ikiz_paralel.py cikis"    & goto calistir
if "%sec%"=="3" set "ARGS=ikiz_paralel.py risk"     & goto calistir
if "%sec%"=="4" set "ARGS=ikiz_paralel.py dusuk"    & goto calistir
if "%sec%"=="5" set "ARGS=ikiz_paralel.py birlesik" & goto calistir
if "%sec%"=="6" set "ARGS=ikiz_rapor.py"            & goto calistir
if "%sec%"=="7" set "ARGS=ikiz_tani.py"             & goto calistir
if "%sec%"=="8" set "ARGS=ikiz_duman.py"            & goto calistir
if "%sec%"=="9" set "ARGS=ikiz_tam.py"              & goto calistir
if "%sec%"=="0" goto son
echo.
echo   Gecersiz secim: [%sec%]
echo   Tus listede yoksa once GUNCELLE:  git pull
echo   Menusuz calistirmak icin:  py ikiz_paralel.py ^<ad^>
timeout /t 2 >nul
goto menu

:calistir
echo.
echo   [1/3] Kod guncelleniyor...
git pull
if errorlevel 1 call :zorla
echo   [2/3] Paketler kontrol ediliyor...
py -m pip install -q -r requirements.txt
echo   [3/3] Kosu: %ARGS%
echo.
echo   ** Bu pencereyi KAPATMA. Yarida kesilen kosu bosa gider. **
echo.
py %ARGS%
echo.
echo ==========================================================
echo   BITTI. Menuye donmek icin bir tusa bas.
echo ==========================================================
pause >nul
goto menu

:son
endlocal

goto :eof

:zorla
echo   git pull reddedildi ^(yerel degisiklik^). Zorla senkronlaniyor...
REM .env ve *.db .gitignore'da -- ayarlar ve Ikiz sonuclari ETKILENMEZ.
for /f "tokens=*" %%b in ('git rev-parse --abbrev-ref HEAD') do set "DAL=%%b"
git fetch origin %DAL%
git reset --hard origin/%DAL%
goto :eof
