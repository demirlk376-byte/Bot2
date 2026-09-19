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
"""
import os, sys, json, subprocess, time
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
    t0 = time.time()
    p = subprocess.run([sys.executable, os.path.join(KOK, "ikiz_tam.py")],
                       env=env, cwd=KOK, capture_output=True, text=True,
                       errors="replace")
    sure = (time.time() - t0) / 60
    if p.returncode != 0:
        # ⚠ HATAYI GOSTER. Ilk surum yalniz stdout basiyordu; dort kosu da
        # rc=1 ile aninda dustu ve sebep GORUNMEDI.
        cikti = ("--- STDERR (son 25 satir) ---\n"
                 + "\n".join([x for x in p.stderr.split("\n") if x.strip()][-25:])
                 + "\n--- STDOUT (son 10 satir) ---\n"
                 + "\n".join([x for x in p.stdout.split("\n") if x.strip()][-10:]))
    else:
        cikti = "\n".join([x for x in p.stdout.split("\n") if x.strip()][-30:])
    return ad, ek, sure, cikti, p.returncode


def main():
    hangi = sys.argv[1] if len(sys.argv) > 1 else "risk"
    en_fazla = int(sys.argv[2]) if len(sys.argv) > 2 else min(8, os.cpu_count() or 4)
    tarama = {"risk": RISK_TARAMA}[hangi]

    print(f"\n{'='*84}")
    print(f"=== PARALEL KOŞU · {len(tarama)} konfigürasyon · en fazla {en_fazla} süreç ===")
    print(f"  çekirdek: {os.cpu_count()} · her koşu ~50 dk · toplam ~{50*max(1,len(tarama)//en_fazla+1)} dk")
    for ad, ek in tarama:
        print(f"    {ETIKET_ADI.get(ad, ad):<14s} {ek}")
    print(f"{'='*84}\n  başladı, çıktılar koşular bitince gelecek...\n", flush=True)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=en_fazla) as ex:
        for ad, ek, sure, cikti, rc in ex.map(kos, tarama):
            print(f"\n{'─'*84}\n### {ETIKET_ADI.get(ad, ad)}  ({ek})  ·  {sure:.0f} dk  ·  "
                  f"{'OK' if rc == 0 else f'HATA rc={rc}'}\n{'─'*84}")
            print(cikti, flush=True)
    print(f"\n{'='*84}\nTOPLAM {(time.time()-t0)/60:.0f} dk\n{'='*84}")


if __name__ == "__main__":
    main()
