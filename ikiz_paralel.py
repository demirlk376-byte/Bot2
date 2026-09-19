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
  py ikiz_paralel.py risk 6        → aynısı, en fazla 6 paralel süreç

Koşu sırasında her 2 dakikada bir durum satırı basılır. Ayrıca her koşu
kendi ikiz_<ad>.log dosyasına CANLI yazar — Not Defteri ile açıp
bakabilirsin, CMD penceresine dokunmana gerek yok.
"""
import os, sys, io, re, json, subprocess, time, threading
from concurrent.futures import ThreadPoolExecutor

KOK = os.path.dirname(os.path.abspath(__file__))

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

ETIKET_ADI = {"adx32": "ADX 32", "korel1": "korel 1", "hold24": "tutus 24",
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
        print("  !! TUM KOSULAR AYNI AYARDA. Tarama yapilmiyor, kosu bosa gidiyor.")
        print("  !! Pencereyi kapat, kodu guncelle (git pull) ve tekrar basla.")
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
    en_fazla = int(sys.argv[2]) if len(sys.argv) > 2 else min(8, os.cpu_count() or 4)
    try:
        tarama = {"risk": RISK_TARAMA, "dusuk": DUSUK_TARAMA,
                  "filtre": FILTRE_TARAMA,
                  # 8 kosu birden: makinede 24 is parcacigi var, ilk tarama
                  # yalniz 4'unu kullandi ve yine 51 dk surdu. Risk sorusu ile
                  # filtre sorusu AYNI 51 dakikada cevaplanir.
                  "hepsi": DUSUK_TARAMA + FILTRE_TARAMA}[hangi]
    except KeyError:
        print(f"bilinmeyen tarama: {hangi}  "
              f"(secenekler: risk, dusuk, filtre, hepsi)")
        return

    print(f"\n{'='*84}")
    print(f"=== PARALEL KOŞU · {len(tarama)} konfigürasyon · en fazla {en_fazla} süreç ===")
    print(f"  çekirdek: {os.cpu_count()} · her koşu ~50 dk · toplam ~{50*max(1,len(tarama)//en_fazla+1)} dk")
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


if __name__ == "__main__":
    main()
