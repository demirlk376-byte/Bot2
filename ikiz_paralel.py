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
RISK_TARAMA = [
    ("risk_%2.0", {"RISK_SCALE": "1.00"}),
    ("risk_%2.8", {"RISK_SCALE": "1.40"}),   # ← CANLI
    ("risk_%3.5", {"RISK_SCALE": "1.75"}),
    ("risk_%4.0", {"RISK_SCALE": "2.00"}),
]


def kos(ad_ve_env):
    ad, ek = ad_ve_env
    env = dict(os.environ)
    env.update(ek)
    env["REPLAY_DB"] = os.path.join(KOK, f"ikiz_{ad}.db")
    env["IKIZ_ETIKET"] = ad
    t0 = time.time()
    p = subprocess.run([sys.executable, os.path.join(KOK, "ikiz_tam.py")],
                       env=env, capture_output=True, text=True, errors="replace")
    sure = (time.time() - t0) / 60
    son = [x for x in p.stdout.split("\n") if x.strip()][-30:]
    return ad, ek, sure, "\n".join(son), p.returncode


def main():
    hangi = sys.argv[1] if len(sys.argv) > 1 else "risk"
    en_fazla = int(sys.argv[2]) if len(sys.argv) > 2 else min(8, os.cpu_count() or 4)
    tarama = {"risk": RISK_TARAMA}[hangi]

    print(f"\n{'='*84}")
    print(f"=== PARALEL KOŞU · {len(tarama)} konfigürasyon · en fazla {en_fazla} süreç ===")
    print(f"  çekirdek: {os.cpu_count()} · her koşu ~50 dk · toplam ~{50*max(1,len(tarama)//en_fazla+1)} dk")
    for ad, ek in tarama:
        print(f"    {ad:<12s} {ek}")
    print(f"{'='*84}\n  başladı, çıktılar koşular bitince gelecek...\n", flush=True)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=en_fazla) as ex:
        for ad, ek, sure, cikti, rc in ex.map(kos, tarama):
            print(f"\n{'─'*84}\n### {ad}  ({ek})  ·  {sure:.0f} dk  ·  "
                  f"{'OK' if rc == 0 else f'HATA rc={rc}'}\n{'─'*84}")
            print(cikti, flush=True)
    print(f"\n{'='*84}\nTOPLAM {(time.time()-t0)/60:.0f} dk\n{'='*84}")


if __name__ == "__main__":
    main()
