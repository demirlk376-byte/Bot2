"""
ikiz_paralel.py — AYNI ANDA birden çok konfigürasyon koşar (çok çekirdek).

NEDEN: tek İkiz koşusu ~50 dk ve kısaltılamıyor (süre botun kendi işinde).
Ama koşular BİRBİRİNDEN BAĞIMSIZ → N çekirdekte N konfigürasyon aynı sürede.
Kullanıcının makinesi 24 iş parçacığı: 4 risk seviyesi ~50 dk'da biter,
sırayla koşulsa 3.3 saat sürerdi.

Her alt süreç kendi ortam değişkenleriyle ve KENDİ veritabanıyla çalışır;
birbirine karışmaz.

Kullanım:
  py ikiz_paralel.py risk          → RISK_SCALE taraması (1.0 / 1.4 / 1.75 / 2.0)
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
ETIKET_ADI = {"risk20": "%2.0", "risk28": "%2.8 (CANLI)",
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


def _nabiz(tarama, bitti, aralik=120):
    """Her 2 dk'da bir her kosunun son satirini bas -- kullanici donup
    kalmadigini gorsun."""
    while not bitti.is_set():
        bitti.wait(aralik)
        if bitti.is_set():
            break
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
    tarama = {"risk": RISK_TARAMA}[hangi]

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
