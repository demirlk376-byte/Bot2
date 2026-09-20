"""
ikiz_profil.py — IKIZ kosusunun ZAMANI NEREDE harcadigini olcer.

NEDEN: "51 dakika kisaltilamaz, sure botun kendi isinde" dedim ama bunu HIC
olcmedim. Olcmeden yapilan hiz iddiasi, bu projede bugun iki kez curudu.

Kisa bir pencere kosar (varsayilan 30 gun) ve cProfile ile en pahali
fonksiyonlari listeler. Cikan tablo, hangi optimizasyonun anlamli oldugunu
tahmin degil OLCUM olarak soyler.

  py ikiz_profil.py [gun]
"""
import asyncio, cProfile, pstats, io as _io, os, sys, time, logging
logging.basicConfig(level=logging.ERROR)
import pandas as pd

GUN = int(sys.argv[1]) if len(sys.argv) > 1 else 30
BAS = "2023-04-06"
BITIS = (pd.Timestamp(BAS) + pd.Timedelta(days=GUN)).strftime("%Y-%m-%d")


async def ana():
    from ikiz.kos import kur, sur
    t0 = time.time()
    M, saat, feed = await kur(BAS, source="local")
    kurulum = time.time() - t0
    print(f"  kurulum {kurulum:.1f}s", flush=True)

    pr = cProfile.Profile()
    t1 = time.time()
    pr.enable()
    n = await sur(M, saat, feed, bitis=BITIS)
    pr.disable()
    gecen = time.time() - t1

    print(f"\n{'='*88}")
    print(f"=== PROFIL · {GUN} gun · {n} olay · {gecen:.1f}s "
          f"· {n/max(gecen,1e-9):.0f} olay/sn · {gecen/max(n,1)*1000:.2f} ms/olay")
    print(f"  TAM TARIH TAHMINI: 345389 olay -> "
          f"{345389/max(n/gecen,1e-9)/60:.0f} dk")
    print(f"{'='*88}")
    for sirala, baslik in (("tottime", "KENDI ICINDE gecen sure"),
                           ("cumulative", "CAGRI AGACI TOPLAMI")):
        s = _io.StringIO()
        pstats.Stats(pr, stream=s).sort_stats(sirala).print_stats(22)
        print(f"\n--- {baslik} ({sirala}) ---")
        cikti = s.getvalue().split("\n")
        bas = next((i for i, x in enumerate(cikti) if "ncalls" in x), 0)
        print("\n".join(cikti[bas:bas + 24]))

asyncio.run(ana())
sys.stdout.flush()
os._exit(0)
