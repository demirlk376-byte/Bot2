"""
ikiz_tani.py — klasordeki her IKIZ veritabaninin DURUMUNU gosterir.

NEDEN: 2026-09-20'de dort dusuk-risk veritabani bosaldi. Ozet araci onlarda
1778 islem gordu, bir sonraki arac 0 gordu. Sebep, islemlerin ana .db dosyasina
hic aktarilmamis olup yalnizca -wal dosyasinda durmasi olabilir. Bu arac,
tahmin yurutmeden, her dosya icin:

  .db boyutu · -wal boyutu · ana dosyadaki islem · WAL dahil islem

gosterir. -wal buyuk ama ana dosya bossa VERI DURUYOR ve kurtarilabilir;
ikisi de bossa kosu gercekten kaybolmustur ve yeniden kosmak gerekir.

  py ikiz_tani.py            → durumu goster
  py ikiz_tani.py kurtar     → -wal'da kalanlari ana dosyaya kalicilastir
"""
import os, sys, glob, sqlite3

KOK = os.path.dirname(os.path.abspath(__file__))


def boyut(y):
    try:
        return os.path.getsize(y)
    except OSError:
        return 0


def sayim(yol, salt_okunur):
    """salt_okunur=True: -wal'a DOKUNMADAN ana dosyayi oku (immutable).
    False: normal ac -- SQLite -wal'i da hesaba katar."""
    try:
        if salt_okunur:
            con = sqlite3.connect(f"file:{yol}?immutable=1", uri=True, timeout=10)
        else:
            con = sqlite3.connect(yol, timeout=30)
        try:
            return con.execute(
                "SELECT COUNT(*) FROM trades WHERE exit_time IS NOT NULL"
            ).fetchone()[0]
        finally:
            con.close()
    except Exception as e:
        return f"HATA: {type(e).__name__}"


def main():
    kurtar = len(sys.argv) > 1 and sys.argv[1].lower().startswith("kurtar")
    yollar = sorted(glob.glob(os.path.join(KOK, "ikiz_*.db")))
    if not yollar:
        print("ikiz_*.db bulunamadi. Bu betigi IKIZ klasorunde calistir.")
        return

    print(f"\n{'='*96}")
    print("=== IKIZ VERITABANI DURUMU ===")
    print(f"{'='*96}")
    print(f"{'dosya':<26s}{'.db KB':>10s}{'-wal KB':>10s}"
          f"{'ana dosyada':>14s}{'WAL dahil':>12s}   durum")
    print("-" * 96)

    for y in yollar:
        ad = os.path.basename(y)
        ana = sayim(y, True)
        tum = sayim(y, False)
        wkb = boyut(y + "-wal") / 1024
        if isinstance(ana, int) and isinstance(tum, int):
            if tum == 0:
                d = "BOS - kosu yeniden yapilmali"
            elif ana == tum:
                d = "saglam"
            else:
                d = f"WAL'da {tum-ana} islem BEKLIYOR"
        else:
            d = "okunamadi"
        print(f"{ad:<26s}{boyut(y)/1024:>10.0f}{wkb:>10.0f}"
              f"{str(ana):>14s}{str(tum):>12s}   {d}")

    if kurtar:
        print(f"\n{'-'*96}\n  KURTARMA: -wal'daki islemler ana dosyaya yediriliyor...")
        for y in yollar:
            try:
                # ⚠ yazilabilir acip TRUNCATE checkpoint + duzgun close:
                # ikisi birlikte -wal'i ana dosyaya yedirir ve siler.
                con = sqlite3.connect(y, timeout=60)
                try:
                    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    con.commit()
                finally:
                    con.close()
                print(f"    {os.path.basename(y):<26s} -> {sayim(y, True)} islem "
                      f"ana dosyada")
            except Exception as e:
                print(f"    {os.path.basename(y):<26s} -> HATA {type(e).__name__}: {e}")
    else:
        print(f"\n  ('WAL'da ... BEKLIYOR' goren olursa:  py ikiz_tani.py kurtar)")
    print(f"{'='*96}")


if __name__ == "__main__":
    main()
