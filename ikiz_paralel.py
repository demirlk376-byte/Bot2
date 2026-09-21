"""
ikiz_paralel.py — AYNI ANDA birden çok konfigürasyon koşar (çok çekirdek).

NEDEN: tek İkiz koşusu ~50 dk ve kısaltılamıyor (süre botun kendi işinde).
Ama koşular BİRBİRİNDEN BAĞIMSIZ → N çekirdekte N konfigürasyon aynı sürede.
Kullanıcının makinesi 24 iş parçacığı: 4 risk seviyesi ~50 dk'da biter,
sırayla koşulsa 3.3 saat sürerdi.

Her alt süreç kendi ortam değişkenleriyle ve KENDİ veritabanıyla çalışır;
birbirine karışmaz.

Kullanım:
  py ikiz_paralel.py risk          → ust aralik: %2.0 / %2.8 / %3.5 / %4.0
  py ikiz_paralel.py dusuk         → alt aralik: %1.0 / %1.4 / %1.7 / %2.0
  py ikiz_paralel.py filtre        → filtreler: ADX32 / korel1 / tutus24 / guven
  py ikiz_paralel.py hepsi         → ikisi birden, 8 surec, ayni 51 dk
  py ikiz_paralel.py birlesik      → korel1 x 4 risk + 4 saf risk, 8 surec
  py ikiz_paralel.py geriverme     → acik karin geri verilmesi, 8 surec
  py ikiz_paralel.py cikis         → basabas/ATR takibi, 9 surec
  py ikiz_paralel.py donchian      → sahte-kirilim filtreleri, 11 surec
  py ikiz_paralel.py eniyi         → kazananlarin birlesimi, 9 surec
  py ikiz_paralel.py son           → secilen filtre x risk merdiveni, 9 surec
  py ikiz_paralel.py risk 6        → aynısı, en fazla 6 paralel süreç

Koşu sırasında her 2 dakikada bir durum satırı basılır. Ayrıca her koşu
kendi ikiz_<ad>.log dosyasına CANLI yazar — Not Defteri ile açıp
bakabilirsin, CMD penceresine dokunmana gerek yok.
"""
import os, sys, io, re, json, subprocess, time, threading
from concurrent.futures import ThreadPoolExecutor

KOK = os.path.dirname(os.path.abspath(__file__))

# Tam tarih (345.389 mum olayi) icin kaba sure tahmini. 2026-09-20'de
# indicators.py numpy'a tasinip CandleBuffer.to_dataframe onbelleklenince
# olculen hiz 61 -> 166 olay/sn oldu (2.74 kat), yani ~50 dk -> ~20 dk.
DK_TAHMIN = 20

# RISK_SCALE × MAX_RISK_PCT(0.02) = işlem başına risk
# ⚠ etiket dosya adina giriyor → % ve Turkce karakter KULLANMA
RISK_TARAMA = [
    ("risk20", {"RISK_SCALE": "1.00"}),    # islem basina %2.0
    ("risk28", {"RISK_SCALE": "1.40"}),    # islem basina %2.8  ← CANLI
    ("risk35", {"RISK_SCALE": "1.75"}),    # islem basina %3.5
    ("risk40", {"RISK_SCALE": "2.00"}),    # islem basina %4.0
]
# ⚠ ALT ARALIK. Ilk tarama (2026-09-19) MAR'in SOL KENARDA hala yukseldigini
# gosterdi: %4.0 -> 2.53, %3.5 -> 2.79, %2.8 -> 3.29, %2.0 -> 3.89. Yani en iyi
# denge test edilen aralikta DEGIL, altinda. Ayrica son bakiye ~%3.3'te tepe
# yapiyor -> bu stratejinin TAM KELLY noktasi orasi; yarim Kelly ~%1.65.
# Bu tarama o bolgeyi olcer. %2.0 ortak capa: iki taramanin ayni sonucu
# vermesi kosunun tekrarlanabilirligini de dogrular.
DUSUK_TARAMA = [
    ("risk10", {"RISK_SCALE": "0.50"}),    # islem basina %1.0
    ("risk14", {"RISK_SCALE": "0.70"}),    # islem basina %1.4
    ("risk17", {"RISK_SCALE": "0.85"}),    # islem basina %1.7  ~yarim Kelly
    ("risk20", {"RISK_SCALE": "1.00"}),    # islem basina %2.0  ← ortak capa
]

# ⚠ FILTRE TARAMASI. Hepsi ZATEN URETIM KODUNDA, env ile aciliyor -- yeni kod
# yok, dolayisiyla canli sadakat garantisi bozulmuyor. RISK_SCALE verilmiyor:
# CANLI_ENV 1.4'e (canli %2.8) dolduruyor, yani hepsi mevcut %2.8 satiriyla
# DOGRUDAN karsilastirilabilir.
#
# ⚠ ORDERFLOW/CVD BURADA YOK. main.py:2106 -- order-flow toplayici yalniz
# GOZLEM modunda, ticarete hic etki etmiyor; ustelik watchTrades canli tick
# akisi istiyor ve gecmis tick verimiz yok. Test edilemez, kosu bosa giderdi.
#
# Guc sirasi: donchian 1195/1777 islem (%67), o yuzden tum kollari etkileyen
# ayarlar sectim. mean_rev'e ozel ayarlar (ornegin SNIPER_MIN_GRADE) yalnizca
# 159 islemi etkiliyor -- bu veride ayirt edilemeyecek kadar kucuk.
FILTRE_TARAMA = [
    # ADX rejim kapisi 28 -> 32: daha guclu trend sarti, daha az ama daha
    # secili giris. Tum kollari etkiler.
    ("adx32",  {"ADX_TRENDING_THRESHOLD": "32.0"}),
    # Ayni yonde en fazla 2 korele pozisyon -> 1. Kripto neredeyse tek blok
    # hareket ettigi icin bu, gizli yogunlasma riskini keser.
    ("korel1", {"MAX_CORRELATED_DIRECTION": "1"}),
    # Max tutus 48 -> 24 mum. Cikislarin %17.9'u (318/1777) max_hold; yarisi
    # ne yapar?
    ("hold24", {"MAX_HOLD_CANDLES": "24"}),
    # Sinyal guvenine gore boyutlandirma (execution.py:495). Boyut degisikligi
    # oldugu icin -- risk taramasi gibi -- gurultu esigine tabi degil.
    ("guven",  {"CONFIDENCE_SIZING": "true"}),
]

# ⚠ BIRLESIK TARAMA. korel1 iki yarida da GECTI (TRAIN dMAR +1.69, TEST +0.59)
# ve mekanizmasi es zamanli korele pozisyonu azaltip oynaklik suruklenmesini
# dusurmek -- yani ZATEN bir risk azaltmasi iceriyor. Bu yuzden korel1'i ayrica
# dusuk riskle birlestirmek FAZLA temkinli olabilir; olcmeden oneremem.
# Ayrica dort saf dusuk-risk kosusu (kazayla silinmisti) geri aliniyor: ayni
# 52 dakikada iki soru birden cevaplanir.
BIRLESIK_TARAMA = [
    ("kor28", {"MAX_CORRELATED_DIRECTION": "1", "RISK_SCALE": "1.40"}),
    ("kor24", {"MAX_CORRELATED_DIRECTION": "1", "RISK_SCALE": "1.20"}),
    ("kor20", {"MAX_CORRELATED_DIRECTION": "1", "RISK_SCALE": "1.00"}),
    ("kor17", {"MAX_CORRELATED_DIRECTION": "1", "RISK_SCALE": "0.85"}),
    ("risk10", {"RISK_SCALE": "0.50"}),
    ("risk14", {"RISK_SCALE": "0.70"}),
    ("risk17", {"RISK_SCALE": "0.85"}),
    ("risk20", {"RISK_SCALE": "1.00"}),
]

# ⚠ GERI VERME TARAMASI. Hedef net: yukselis bitip fiyat bayrak/sikisma
# cizerken acik karin geri verilmesi. Mevcut ayarlar bunu neredeyse hic
# engellemiyor:
#   trailing_atr_mult = 2.0  -> zirvenin 2xATR altina kadar geri vermeye izin
#   breakeven_atr_mult = 1.0 -> basabasa ancak 1xATR kar sonra cekiliyor
#   donchian_buffer_atr = 0  -> bayrak icindeki SAHTE kirilimlar hic filtresiz
#   cikislarin %17.8'i max_hold -> zamani dolup kapananlar
#
# Tarama ayni zamanda TESHIS: hangi grup kazanirsa sorunun kaynagi odur.
#   trail*/be* kazanirsa -> sorun ACIK KARIN solmasi (cikis tarafi)
#   buf/adxr/cl kazanirsa -> sorun CHOP'TA ACILAN YENI ISLEMLER (giris tarafi)
GERIVERME_TARAMA = [
    # ⚠ DEGISIKLIK ICERMEYEN TABAN. Iki isi birden goruyor:
    #   1) filtrelerin karsilastirilacagi referans, AYNI kosuda uretilmis olur
    #   2) HIZLANDIRMA DOGRULAMASI: indikatorler numpy'a tasindi ve mum tablosu
    #      onbelleklendi (2026-09-20, 2.74 kat). Birim testler bit duzeyinde
    #      esitlik gosterdi ama 20 gunluk uctan uca kontrol yalniz 14 islemdi.
    #      Bu kosu TAM TARIHTE 1778 islem / ort R +0.1581 / MAR 3.29 vermeli --
    #      hizlandirma oncesi olculen degerler. Sapma varsa hizlandirma geri
    #      alinir; hiz icin sadakat feda edilmez.
    ("taban",   {}),
    # --- cikis tarafi: kari kilitle ---
    ("trail10", {"TRAILING_ATR_MULT": "1.0"}),                  # dar takip
    ("trail15", {"TRAILING_ATR_MULT": "1.5"}),
    ("be05",    {"BREAKEVEN_ATR_MULT": "0.5"}),                 # erken basabas
    ("bt",      {"BREAKEVEN_ATR_MULT": "0.5",
                 "TRAILING_ATR_MULT": "1.25"}),                 # ikisi birden
    ("rr15",    {"DONCHIAN_RR": "1.5"}),                        # kari erken al
    # --- giris tarafi: chop'ta islem acma ---
    ("buf05",   {"DONCHIAN_BUFFER_ATR": "0.5"}),                # guclu kirilim sart
    ("adxr25",  {"ADX_RANGING_THRESHOLD": "25.0"}),             # daha cok "yatay" say
    ("cl1",     {"CONSECUTIVE_LOSS_LIMIT": "1",
                 "COOLDOWN_MINUTES": "480"}),                   # chop'tan hizli cik
]

# ⚠ CIKIS YONETIMI TARAMASI. Once TRAILING_ATR_MULT/BREAKEVEN_ATR_MULT'u
# taradim ve dort kosu da tabanla BIREBIR ayni cikti: o iki ayar hicbir yerde
# OKUNMUYORDU. Sebep main.py'de sabit kol listesiydi -- stop tasima yalniz
# orb/ifvg'ye uygulaniyor, ikisi de canlida KAPALI, yani calisan uc kol hic
# stop yonetimi almiyordu. Mekanizma artik uretim kodunda ve ayarla aciliyor
# (varsayilan = bugunku davranis).
CIKIS_TARAMA = [
    ("taban",   {}),                                     # dogrulama capasi
    # --- basabasa cekme ---
    ("be_don",  {"BE_SLEEVES": "orb,ifvg,donchian"}),
    ("be_all",  {"BE_SLEEVES": "orb,ifvg,donchian,squeeze"}),
    ("be15",    {"BE_SLEEVES": "orb,ifvg,donchian,squeeze",
                 "BE_TRIGGER_R": "1.5"}),
    # --- ATR takibi (zirvenin N x ATR altinda) ---
    ("tr30",    {"TRAIL_SLEEVES": "donchian,squeeze", "TRAIL_ATR_MULT": "3.0"}),
    ("tr20",    {"TRAIL_SLEEVES": "donchian,squeeze", "TRAIL_ATR_MULT": "2.0"}),
    ("tr15",    {"TRAIL_SLEEVES": "donchian,squeeze", "TRAIL_ATR_MULT": "1.5"}),
    # --- takip yalniz 1R kardan SONRA (erken bogulmayi onler) ---
    ("tr20g",   {"TRAIL_SLEEVES": "donchian,squeeze", "TRAIL_ATR_MULT": "2.0",
                 "TRAIL_START_R": "1.0"}),
    # --- ikisi birden ---
    ("be_tr",   {"BE_SLEEVES": "orb,ifvg,donchian,squeeze",
                 "TRAIL_SLEEVES": "donchian,squeeze", "TRAIL_ATR_MULT": "2.0"}),
]

# ⚠ DONCHIAN SAHTE-KIRILIM TARAMASI. Kullanicinin listesinden GERCEKTEN YENI
# olanlar. Listenin yarisi zaten koddaydi: kapanis teyidi (donchian kirilimi
# close ile siniyor), ATR tamponu (buffer_atr, bugun 0.5 denendi -> TRAIN
# +13.35 / TEST -1.10, uydurma), EMA200+gunluk MTF trend hizasi (stratejinin
# cekirdegi), ADX rejim kapisi (bugun iki kez denendi, ikisi de kaldi).
DONCHIAN_TARAMA = [
    ("taban",     {}),                                  # dogrulama capasi
    ("teyit1",    {"DONCHIAN_CONFIRM_BARS": "1"}),      # 1 bar seviyeyi korusun
    ("teyit2",    {"DONCHIAN_CONFIRM_BARS": "2"}),
    ("retest2",   {"DONCHIAN_RETEST_BARS": "2"}),       # 2 bar icinde geri donus
    ("retest4",   {"DONCHIAN_RETEST_BARS": "4"}),
    ("hacim15",   {"DONCHIAN_VOL_MULT": "1.5"}),        # hacim SMA20'nin 1.5 kati
    ("hacim20",   {"DONCHIAN_VOL_MULT": "2.0"}),
    ("obv",       {"DONCHIAN_OBV": "true"}),            # OBV de yeni uc yapmali
    ("hacim_obv", {"DONCHIAN_VOL_MULT": "1.5", "DONCHIAN_OBV": "true"}),
    # ⚠ ADX bu kolda HIC denenmemis (main.py:681 rejim kapisi Donchian'i
    # kapsamiyor). Bugunku iki ADX kosum squeeze/mean_rev'i etkiledi.
    ("adx20", {"DONCHIAN_ADX_MIN": "20"}),
    ("adx25", {"DONCHIAN_ADX_MIN": "25"}),
]

# ⚠ HAYATTA KALANLARIN BIRLESIMI. Donchian taramasinda (duzeltilmis motor,
# taban MAR 5.00 / TRAIN 9.77 / TEST 3.31) iki fikir IKI YARIDA DA temelden
# iyi cikti: teyit 1 bar (dMAR TRAIN +5.50 / TEST +0.47) ve hacim 2.0x
# (+0.13 / +1.60). Hacim 1.5x ve OBV yalniz TEST'te one gecti. ADX ve retest
# iki yarida da kaybetti. Bu tarama, kazananlarin UST USTE BINIP binmedigini
# olcer -- iki filtre de ayni sahte kirilimlari eliyorsa birlesim bir sey
# katmaz, hatta orneklemi gereksiz kuculturur.
EN_IYI_TARAMA = [
    ("taban",    {}),
    ("t1",       {"DONCHIAN_CONFIRM_BARS": "1"}),
    ("h20",      {"DONCHIAN_VOL_MULT": "2.0"}),
    ("h15",      {"DONCHIAN_VOL_MULT": "1.5"}),
    ("t1h20",    {"DONCHIAN_CONFIRM_BARS": "1", "DONCHIAN_VOL_MULT": "2.0"}),
    ("t1h15",    {"DONCHIAN_CONFIRM_BARS": "1", "DONCHIAN_VOL_MULT": "1.5"}),
    ("t1obv",    {"DONCHIAN_CONFIRM_BARS": "1", "DONCHIAN_OBV": "true"}),
    ("t1h20k",   {"DONCHIAN_CONFIRM_BARS": "1", "DONCHIAN_VOL_MULT": "2.0",
                  "MAX_CORRELATED_DIRECTION": "1"}),
    ("t1h20r20", {"DONCHIAN_CONFIRM_BARS": "1", "DONCHIAN_VOL_MULT": "2.0",
                  "RISK_SCALE": "1.00"}),
]

# ⚠ SON TARAMA. Filtre tarafi kapandi: "eniyi" taramasinda dort ayar iki
# yarida da temelden iyi cikti ve en iyi TEST dengesi teyit1+hacim1.5'te
# (dMAR TRAIN +0.46 / TEST +2.32). Onemli bulgu: teyit1+hacim2.0 KALDI
# (TEST -0.46) -- iki filtrenin SERT halleri ust uste binince orneklem
# 1752'den 1125'e dusuyor ve kenar kayboluyor; yumusak hali (1.5x) birlikte
# calisiyor.
# Geriye TEK soru kaldi: risk seviyesi. Risk taramasini duzeltilmis motorda
# HIC yapmadik (eski kosular sizintiliydi, dusuk-risk veritabanlari da
# silinmisti). Bu tarama secilen filtreyi risk merdiveniyle birlikte olcer
# ve CANLIYA YAZILACAK ayari verir. Bundan sonra tarama YOK -- her yeni
# tarama uydurma riskini buyutur.
SON_TARAMA = [
    ("taban",   {}),
    ("f",       {"DONCHIAN_CONFIRM_BARS": "1", "DONCHIAN_VOL_MULT": "1.5"}),
    ("f24",     {"DONCHIAN_CONFIRM_BARS": "1", "DONCHIAN_VOL_MULT": "1.5",
                 "RISK_SCALE": "1.20"}),
    ("f20",     {"DONCHIAN_CONFIRM_BARS": "1", "DONCHIAN_VOL_MULT": "1.5",
                 "RISK_SCALE": "1.00"}),
    ("f17",     {"DONCHIAN_CONFIRM_BARS": "1", "DONCHIAN_VOL_MULT": "1.5",
                 "RISK_SCALE": "0.85"}),
    ("f14",     {"DONCHIAN_CONFIRM_BARS": "1", "DONCHIAN_VOL_MULT": "1.5",
                 "RISK_SCALE": "0.70"}),
    ("r24",     {"RISK_SCALE": "1.20"}),
    ("r20",     {"RISK_SCALE": "1.00"}),
    ("r17",     {"RISK_SCALE": "0.85"}),
]

ETIKET_ADI = {"f": "FILTRE %2.8", "f24": "FILTRE %2.4", "f20": "FILTRE %2.0",
              "f17": "FILTRE %1.7", "f14": "FILTRE %1.4",
              "r24": "filtresiz %2.4", "r20": "filtresiz %2.0",
              "r17": "filtresiz %1.7",
              "t1": "teyit1", "h20": "hacim2.0", "h15": "hacim1.5",
              "t1h20": "teyit1+h2.0", "t1h15": "teyit1+h1.5",
              "t1obv": "teyit1+OBV", "t1h20k": "teyit1+h2.0+korel",
              "t1h20r20": "teyit1+h2.0+%2.0risk",
              "adx20": "ADX>=20", "adx25": "ADX>=25",
              "teyit1": "teyit 1 bar", "teyit2": "teyit 2 bar",
              "retest2": "retest 2b", "retest4": "retest 4b",
              "hacim15": "hacim 1.5x", "hacim20": "hacim 2.0x",
              "obv": "OBV teyit", "hacim_obv": "hacim+OBV",
              "taban": "TABAN (canli)",
              "be_don": "BE donchian", "be_all": "BE don+sq",
              "be15": "BE 1.5R", "tr30": "takip 3xATR",
              "tr20": "takip 2xATR", "tr15": "takip 1.5xATR",
              "tr20g": "takip 2x @1R", "be_tr": "BE + takip 2x",
              "trail10": "takip 1.0", "trail15": "takip 1.5",
              "be05": "basabas 0.5", "bt": "basabas+takip",
              "rr15": "RR 1.5", "buf05": "tampon 0.5",
              "adxr25": "ADX yatay 25", "cl1": "1 zarar/8sa",
              "kor28": "korel+%2.8", "kor24": "korel+%2.4",
              "kor20": "korel+%2.0", "kor17": "korel+%1.7",
              "adx32": "ADX 32", "korel1": "korel 1", "hold24": "tutus 24",
              "guven": "guven boyut",
              "risk10": "%1.0", "risk14": "%1.4", "risk17": "%1.7",
              "risk20": "%2.0", "risk28": "%2.8 (CANLI)",
              "risk35": "%3.5", "risk40": "%4.0"}


def kos(ad_ve_env):
    ad, ek = ad_ve_env
    env = dict(os.environ)
    env.update(ek)
    # ⚠ WINDOWS TUZAGI: cocuk surecin stdout'u BORUYA baglandiginda Python
    # yerel kod sayfasini (Turkce Windows'ta cp1254) kullanir ve ciktidaki
    # "→ · ğ İ" gibi karakterleri kodlayamayip UnicodeEncodeError ile ANINDA
    # duser (rc=1, 0 dk). Terminale basarken sorun cikmaz — bu yuzden tek
    # kosu calisip paralel kosu dusuyordu. UTF-8'i zorla.
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    # ⚠ stdout DOSYAYA baglandiginda Python 8 KB'lik BLOK tamponu kullanir:
    # kosu basindaki satirlar (ETKIN AYAR dahil) dakikalarca diske inmez, o
    # yuzden 2 dakikalik ayar dogrulamasi ilk nabizda bos doner. logging ise
    # stderr'e satir satir yazdigi icin gorunur -- gunluk dolu ama print'ler
    # eksik gorunuyordu. Tamponu kapat.
    env["PYTHONUNBUFFERED"] = "1"
    # ⚠ Bu kosunun DEGISTIRDIGI anahtarlari bildir ki kosu onlari da yazsin;
    # yoksa ayar dogrulamasi taranan alani goremez (bkz. ikiz/kos.py).
    env["IKIZ_IZLE"] = ",".join(sorted(ek.keys()))
    env["REPLAY_DB"] = os.path.join(KOK, f"ikiz_{ad}.db")
    env["IKIZ_ETIKET"] = ad
    gunluk = os.path.join(KOK, f"ikiz_{ad}.log")
    t0 = time.time()
    # ⚠ capture_output=True KULLANMA. Ciktiyi bellekte tutuyordu, yani
    # kosu bitene kadar (1+ saat) HICBIR ilerleme gorunmuyordu ve kullanici
    # donmus mu koşuyor mu ayirt edemiyordu. Dosyaya yaz: hem canli izlenir,
    # hem CMD kapansa bile kayit kalir.
    with io.open(gunluk, "w", encoding="utf-8", errors="replace") as f:
        p = subprocess.run([sys.executable, os.path.join(KOK, "ikiz_tam.py")],
                           env=env, cwd=KOK, stdout=f,
                           stderr=subprocess.STDOUT)
    sure = (time.time() - t0) / 60
    satirlar = _satirlar(gunluk)
    n = 30 if p.returncode == 0 else 40
    cikti = "\n".join(satirlar[-n:])
    return ad, ek, sure, cikti, p.returncode


def _satirlar(yol):
    """Gunlugu satirlara ayir. ⚠ ilerleme cubugu \r kullaniyor; yalniz \n ile
    bolersek tek dev satir cikar ve son durum gorunmez. Ikisiyle de bol."""
    try:
        with io.open(yol, encoding="utf-8", errors="replace") as f:
            ham = f.read()
    except OSError:
        return []
    return [x.strip() for x in re.split(r"[\r\n]+", ham) if x.strip()]


def _ayar_dogrula(tarama):
    """⚠ ILK 2 DAKIKADA taramanin GERCEKTEN farkli ayarlarla kostugunu
    dogrula. 2026-09-19'da dort kosu da ayni ayarla kostu (CANLI_ENV caginin
    RISK_SCALE'ini eziyordu) ve bu ancak 5 SAAT sonra, sonuc tablosunda dort
    ozdes satir gorunce anlasildi. Kosu kendi ayarini basta yaziyor; burada
    okuyup karsilastiriyoruz. Ayni cikarsa kosmaya devam etmenin anlami yok."""
    bulunan = {}
    for ad, _ in tarama:
        for sat in _satirlar(os.path.join(KOK, f"ikiz_{ad}.log")):
            if "ETKİN AYAR" in sat:
                bulunan[ad] = sat
                break
    if len(bulunan) < len(tarama):
        return  # hepsi henuz yazmadi; sonraki nabizda tekrar bakilir
    print("\n  --- AYAR DOGRULAMA ---")
    for ad, sat in bulunan.items():
        print(f"  {ETIKET_ADI.get(ad, ad):<14s} {sat.strip()}")
    if len(set(bulunan.values())) == 1:
        print("\n  " + "!" * 84)
        print("  !! TUM KOSULARIN AYAR SATIRI AYNI.")
        print("  !! Yukaridaki satirlarda taranan anahtarlarin DEGERLERINE bak:")
        print("  !! " + " / ".join(sorted({k for _, e in tarama for k in e})
                                   or ["(bu tarama hicbir anahtar degistirmiyor)"]))
        print("  !! Gercekten ayniysa kosu bosa gidiyor; pencereyi kapat,")
        print("  !! git pull yapip tekrar basla.")
        print("  " + "!" * 84, flush=True)
    else:
        print("  ayarlar farkli ✓ tarama gercek.\n", flush=True)


def _nabiz(tarama, bitti, aralik=120):
    """Her 2 dk'da bir her kosunun son satirini bas -- kullanici donup
    kalmadigini gorsun."""
    dogrulandi = False
    while not bitti.is_set():
        bitti.wait(aralik)
        if bitti.is_set():
            break
        if not dogrulandi:
            try:
                _ayar_dogrula(tarama)
                dogrulandi = all(
                    any("ETKİN AYAR" in x for x in
                        _satirlar(os.path.join(KOK, f"ikiz_{ad}.log")))
                    for ad, _ in tarama)
            except Exception as e:
                print(f"  (ayar dogrulama atlandi: {type(e).__name__}: {e})")
                dogrulandi = True
        parcalar = []
        for ad, _ in tarama:
            sat = _satirlar(os.path.join(KOK, f"ikiz_{ad}.log"))
            son = sat[-1][-58:] if sat else "basliyor..."
            parcalar.append(f"  {ETIKET_ADI.get(ad, ad):<14s} {son}")
        print(f"\n[{time.strftime('%H:%M:%S')}] hala kosuyor:\n"
              + "\n".join(parcalar), flush=True)


def main():
    hangi = sys.argv[1] if len(sys.argv) > 1 else "risk"
    en_fazla = int(sys.argv[2]) if len(sys.argv) > 2 else min(12, os.cpu_count() or 4)
    try:
        tarama = {"risk": RISK_TARAMA, "dusuk": DUSUK_TARAMA,
                  "filtre": FILTRE_TARAMA,
                  # 8 kosu birden: makinede 24 is parcacigi var, ilk tarama
                  # yalniz 4'unu kullandi ve yine 51 dk surdu. Risk sorusu ile
                  # filtre sorusu AYNI 51 dakikada cevaplanir.
                  "hepsi": DUSUK_TARAMA + FILTRE_TARAMA,
                  "birlesik": BIRLESIK_TARAMA,
                  "geriverme": GERIVERME_TARAMA,
                  "cikis": CIKIS_TARAMA,
                  "donchian": DONCHIAN_TARAMA,
                  "eniyi": EN_IYI_TARAMA,
                  "son": SON_TARAMA}[hangi]
    except KeyError:
        print(f"bilinmeyen tarama: {hangi}  "
              f"(secenekler: risk, dusuk, filtre, hepsi, "
              f"birlesik, geriverme, cikis, donchian, eniyi, son)")
        return

    print(f"\n{'='*84}")
    print(f"=== PARALEL KOŞU · {len(tarama)} konfigürasyon · en fazla {en_fazla} süreç ===")
    # ⚠ SABIT METIN TUTMA. Burada "~50 dk" yaziyordu ve indikatorler numpy'a
    # tasinip mum tablosu onbelleklendikten sonra (2026-09-20, 2.74 kat) YANLIS
    # kaldi: kullanici 20 dakikalik kosuda 50 dakika bekleyecegini sandi.
    # Gercek sureyi ilerleme cubugu olcuyor; buradaki yalnizca kaba bir on
    # tahmindir ve olculen hizdan turetilir.
    _tur = max(1, (len(tarama) + en_fazla - 1) // en_fazla)
    print(f"  çekirdek: {os.cpu_count()} · her koşu ~{DK_TAHMIN} dk · "
          f"{_tur} tur · kaba toplam ~{DK_TAHMIN*_tur} dk "
          f"(kesin süreyi ilerleme çubuğu gösterir)")
    for ad, ek in tarama:
        print(f"    {ETIKET_ADI.get(ad, ad):<14s} {ek}")
    print(f"{'='*84}\n  başladı. Her 2 dk'da bir durum satırı gelecek.\n  Canlı takip: ikiz_<ad>.log dosyalarını Not Defteri ile aç.\n", flush=True)

    t0 = time.time()
    bitti = threading.Event()
    threading.Thread(target=_nabiz, args=(tarama, bitti), daemon=True).start()
    with ThreadPoolExecutor(max_workers=en_fazla) as ex:
        for ad, ek, sure, cikti, rc in ex.map(kos, tarama):
            print(f"\n{'─'*84}\n### {ETIKET_ADI.get(ad, ad)}  ({ek})  ·  {sure:.0f} dk  ·  "
                  f"{'OK' if rc == 0 else f'HATA rc={rc}'}\n{'─'*84}")
            print(cikti, flush=True)
    bitti.set()
    print(f"\n{'='*84}\nTOPLAM {(time.time()-t0)/60:.0f} dk\n{'='*84}")

    # ⚠ RAPORU KENDI BAS. Eskiden kullanici taramadan sonra uc ayri .bat
    # calistirmak zorundaydi (ozet / filtre / donem) ve hangisinin ne yaptigini
    # hatirlamasi gerekiyordu. Tarama bitti demek sonuclar hazir demek; raporu
    # beklemenin bir sebebi yok.
    try:
        import ikiz_rapor
        ikiz_rapor.main()
    except Exception as e:
        print(f"\n  (rapor uretilemedi: {type(e).__name__}: {e})")
        print("  elle: py ikiz_rapor.py")


if __name__ == "__main__":
    main()
