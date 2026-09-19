"""
ikiz_risk_ozet.py — risk taramasi kosularinin SONUCUNU veritabanindan okur.

NEDEN AYRI BIR ARAC: paralel kosu 51 dakikada simulasyonu bitirdi ama koşu
sonundaki WAL aktariminda dondu (dort surec de ayni anda, sifir CPU). Islemler
kaybolmadi — .db-wal dosyasinda duruyorlar. Bu arac surecleri beklemeden o
veriyi okur, WAL'i ana dosyaya birlestirir ve karsilastirma tablosunu basar.

ARADIGIMIZ SEY: daha fazla kar DEGIL. Riski artirinca hem kar hem drawdown
artar, bu zaten biliniyor. Soru kar/drawdown dengesinin NEREDE en iyi oldugu.

Kullanim:
  py ikiz_risk_ozet.py              → klasordeki tum ikiz_risk*.db
  py ikiz_risk_ozet.py yol.db ...   → belirtilen veritabanlari
"""
import os, sys, glob, json, sqlite3
import pandas as pd, numpy as np

KOK = os.path.dirname(os.path.abspath(__file__))
BAL0 = 10_000.0
ETIKET = {"risk20": "%2.0", "risk28": "%2.8 CANLI", "risk35": "%3.5",
          "risk40": "%4.0"}


def oku(yol):
    """⚠ mode=ro KULLANMA. SQLite bir WAL veritabanini okumak icin -shm
    dosyasina YAZABILMEK zorunda; salt-okunur acilista WAL'daki islemleri
    GOREMEZ ve tablo bos gorunur. Kosu dondugu icin islemlerin tamami
    -wal'da duruyor, o yuzden yazilabilir acip birlestiriyoruz."""
    con = sqlite3.connect(yol, timeout=60)
    try:
        d = pd.read_sql(
            "SELECT symbol,side,entry_price,exit_price,sl_price,entry_time,"
            "exit_time,pnl_usdt,exit_reason,strategy_scores "
            "FROM trades WHERE exit_time IS NOT NULL", con)
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.commit()
    finally:
        con.close()
    return d


def olc(d):
    """Kar ve drawdown'i AYNI egriden olcer.

    ⚠ Drawdown BILESIK egriden okunmali: bot pozisyon buyuklugunu o anki
    bakiyeden hesapliyor, yani kayiplar buyudukce pozisyonlar kuculuyor.
    Sabit-kesir egrisinden okunan drawdown gercek hesabin yasadigini vermez.
    pnl_usdt zaten kosunun kendi bilesik bakiyesinden uretildi."""
    d = d.copy()
    d["giris"] = pd.to_datetime(d.entry_time, utc=True, format="mixed")
    d["cikis"] = pd.to_datetime(d.exit_time,  utc=True, format="mixed")
    d = d.sort_values("cikis").reset_index(drop=True)

    yon  = 1 - 2 * d.side.str.lower().str.startswith("s").astype(int)
    stop = (d.entry_price - d.sl_price).abs()
    d["R"] = np.where(stop > 0,
                      yon * (d.exit_price - d.entry_price) / stop.replace(0, np.nan),
                      np.nan)
    d["kol"] = d.strategy_scores.apply(
        lambda s: (json.loads(s or "{}") or {}).get("strategy", "?"))

    # ⚠ egri BAL0'dan baslamali; yoksa ilk islem zararliysa tepe noktasi
    # yanlis yerden baslar ve drawdown oldugundan KUCUK olcunur.
    eq   = pd.concat([pd.Series([BAL0]), BAL0 + d.pnl_usdt.cumsum()],
                     ignore_index=True)
    tepe = eq.cummax()
    dd   = (tepe - eq) / tepe
    maxdd = float(dd.max())

    gun  = max(1, (d.cikis.max() - d.giris.min()).days)
    son  = float(eq.iloc[-1])
    yillik = (son / BAL0) ** (365.0 / gun) - 1.0

    return {
        "d": d, "n": len(d), "gun": gun, "gunde": len(d) / gun,
        "ortR": float(d.R.mean()), "sigmaR": float(d.R.std()),
        "kazanma": float((d.R > 0).mean()),
        "son": son, "getiri": son / BAL0 - 1.0, "yillik": yillik,
        "maxdd": maxdd, "mar": (yillik / maxdd) if maxdd > 0 else float("nan"),
        "ilk": d.giris.min(), "sonT": d.cikis.max(),
    }


def main():
    yollar = sys.argv[1:] or sorted(glob.glob(os.path.join(KOK, "ikiz_risk*.db")))
    if not yollar:
        print("ikiz_risk*.db bulunamadi. Bu betigi IKIZ klasorunde calistir.")
        return

    sonuc = []
    for y in yollar:
        ad = os.path.splitext(os.path.basename(y))[0].replace("ikiz_", "")
        try:
            d = oku(y)
        except Exception as e:
            print(f"  {ad}: OKUNAMADI  {type(e).__name__}: {e}")
            continue
        if not len(d):
            print(f"  {ad}: kapanmis islem yok")
            continue
        s = olc(d); s["ad"] = ETIKET.get(ad, ad)
        sonuc.append(s)

    if not sonuc:
        return

    print(f"\n{'='*104}")
    print("=== RISK TARAMASI · kar/drawdown dengesi ===")
    print(f"  baslangic ${BAL0:,.0f} · bilesik boyutlama (bot bakiyeden hesapliyor)")
    print(f"{'='*104}")
    bas = f"{'risk':<12s}{'islem':>7s}{'gunde':>7s}{'ort R':>9s}{'kazan%':>8s}"
    bas += f"{'bakiye':>14s}{'yillik%':>9s}{'maxDD%':>8s}{'MAR':>7s}"
    print(bas)
    print("-" * 104)
    for s in sonuc:
        print(f"{s['ad']:<12s}{s['n']:>7d}{s['gunde']:>7.2f}{s['ortR']:>+9.4f}"
              f"{s['kazanma']*100:>8.1f}{s['son']:>14,.0f}"
              f"{s['yillik']*100:>9.1f}{s['maxdd']*100:>8.1f}{s['mar']:>7.2f}")
    print("-" * 104)

    # ⚠ SESSİZ BAŞARISIZLIK MUHAFIZI. 2026-09-19: dört koşu da aynı ayarla
    # koştu (ikiz/kos.py:77 CANLI_ENV çağıranın RISK_SCALE'ini EZİYORDU) ve bu
    # tablo dört ÖZDEŞ satır bastı. Tablo geldiği için sonuç doğru sanıldı;
    # oysa tarama hiç yapılmamıştı ve 5 saat boşa gitti. Bir daha sessizce
    # geçmesin: aynı sonuç = tarama olmamış demektir.
    imza = {(s["n"], round(s["son"], 2), round(s["ortR"], 6)) for s in sonuc}
    if len(sonuc) > 1 and len(imza) == 1:
        print("\n  " + "!" * 88)
        print("  !! TARAMA YAPILMAMIŞ: tüm koşular BİREBİR aynı sonucu verdi.")
        print("  !! Farklı ayarlar alt süreçlere ULAŞMAMIŞ demektir; bu tablo")
        print("  !! risk sorusu hakkında hiçbir şey söylemez.")
        print("  !! Koşu başındaki 'ETKİN AYAR' satırını kontrol et: her koşu")
        print("  !! kendi RISK_SCALE değerini yazmalı.")
        print("  " + "!" * 88)
        return

    # ⚠ MAR = yillik getiri / en derin dusus. Karsilastirmanin ASIL sutunu bu.
    # Cunku riski buyutunce bakiye sutunu HER ZAMAN buyur; tek basina bakmak
    # "daha cok risk her zaman daha iyi" yanlis sonucunu verir.
    en = max(sonuc, key=lambda s: s["mar"] if s["mar"] == s["mar"] else -9e9)
    canli = next((s for s in sonuc if "CANLI" in s["ad"]), None)
    print(f"\n  en iyi MAR (yillik getiri / maxDD): {en['ad']}  "
          f"MAR {en['mar']:.2f}  (yillik %{en['yillik']*100:.1f} · "
          f"maxDD %{en['maxdd']*100:.1f})")
    if canli is not None and canli is not en:
        print(f"  su anki CANLI ayar:                {canli['ad']}  "
              f"MAR {canli['mar']:.2f}  (yillik %{canli['yillik']*100:.1f} · "
              f"maxDD %{canli['maxdd']*100:.1f})")
    elif canli is not None:
        print("  su anki CANLI ayar zaten en iyi MAR'a sahip.")

    s0 = sonuc[0]
    print(f"\n  veri araligi: {s0['ilk'].date()} -> {s0['sonT'].date()}  "
          f"({s0['gun']} gun)")
    print(f"  (kosu tamamsa bitis 2026-07 civari olmali; cok erkense kosu "
          f"yarida kalmis demektir)")

    print(f"\n  kol dagilimi (islem sayisi · ort R):")
    for s in sonuc:
        par = "  ".join(f"{k} {len(g)}/{g.R.mean():+.3f}"
                        for k, g in s["d"].groupby("kol"))
        print(f"    {s['ad']:<12s} {par}")
    print(f"{'='*104}")


if __name__ == "__main__":
    main()
