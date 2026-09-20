"""
ikiz_donem_analiz.py — her konfigurasyonu TRAIN ve TEST yarisinda AYRI olcer.

NEDEN: filtre gecerlilik testi (ikiz_filtre_analiz) korel1'in kotu islemleri
ELEMEDIGINI gosterdi -- elenen 130 islem ortalama kaliteydi (z=-0.25). Yani
+%31 bakiye farki SECIMDEN gelmiyor. Geriye tek mekanizma kaliyor: ayni yonde
es zamanli korele pozisyonu 2'den 1'e indirmek portfoy oynakligini dusuruyor,
oynaklik dusunce ayni aritmetik kenar daha yuksek BILESIK buyume veriyor
("oynaklik suruklenmesi"). Bu bir sans degil, matematik -- ama olculen BUYUKLUK
tek bir yolun sonucu ve sansli olabilir.

Ayirt etme yolu: etki iki donemde de duruyor mu? Gercek bir yapisal etki her
donemde ayni yone basar; tek donemde parlayip digerinde sonen sey uydurmadir.

ONEMLI: buyume YARI ICINDE olculur. TEST yarisinin baslangic bakiyesi TRAIN'in
bitis bakiyesidir; boylece TRAIN'de sansli buyuyen bir konfigurasyon TEST'te
otomatik olarak one gecmis sayilmaz.

Kullanim:  py ikiz_donem_analiz.py
"""
import os, sys, glob, sqlite3
import pandas as pd, numpy as np

KOK = os.path.dirname(os.path.abspath(__file__))
BAL0 = 10_000.0
BOLME = pd.Timestamp("2025-01-01", tz="UTC")
TEMEL_AD = "risk28"
SIRA = ["risk10", "risk14", "risk17", "risk20", "risk28", "risk35", "risk40",
        "korel1", "adx32", "hold24", "guven"]
ETIKET = {"risk10": "%1.0", "risk14": "%1.4", "risk17": "%1.7", "risk20": "%2.0",
          "risk28": "%2.8 CANLI", "risk35": "%3.5", "risk40": "%4.0",
          "korel1": "korel 1", "adx32": "ADX 32", "hold24": "tutus 24",
          "guven": "guven boyut"}


def oku(yol):
    con = sqlite3.connect(yol, timeout=60)
    try:
        d = pd.read_sql("SELECT exit_time,entry_time,pnl_usdt FROM trades "
                        "WHERE exit_time IS NOT NULL", con)
    finally:
        con.close()
    d["cikis"] = pd.to_datetime(d.exit_time, utc=True, format="mixed")
    d["giris"] = pd.to_datetime(d.entry_time, utc=True, format="mixed")
    return d.sort_values("cikis").reset_index(drop=True)


def yari(d, bas_bakiye, t0, t1):
    """Bir donemin KENDI ICINDE buyumesi ve en derin dususu.

    ⚠ tepe noktasi donemin BASLANGIC bakiyesinden baslatilir. eq.cummax() ile
    baslatilsaydi donem zararla basladiginda tepe yanlis yerden olculur ve
    drawdown oldugundan KUCUK cikardi."""
    alt = d[(d.cikis >= t0) & (d.cikis < t1)]
    if len(alt) < 5:
        return None
    eq = pd.concat([pd.Series([bas_bakiye]),
                    bas_bakiye + alt.pnl_usdt.cumsum()], ignore_index=True)
    tepe = eq.cummax()
    maxdd = float(((tepe - eq) / tepe).max())
    gun = max(1, (alt.cikis.max() - alt.cikis.min()).days)
    buyume = float(eq.iloc[-1]) / bas_bakiye
    if buyume <= 0:
        return None
    yillik = buyume ** (365.0 / gun) - 1.0
    return {"n": len(alt), "son": float(eq.iloc[-1]), "gun": gun,
            "yillik": yillik, "maxdd": maxdd,
            "mar": (yillik / maxdd) if maxdd > 0 else float("nan")}


def olc(yol):
    d = oku(yol)
    if len(d) < 20:
        return None
    ilk, son = d.cikis.min(), d.cikis.max() + pd.Timedelta(days=1)
    tr = yari(d, BAL0, ilk, BOLME)
    if tr is None:
        return None
    te = yari(d, tr["son"], BOLME, son)
    return {"train": tr, "test": te}


def main():
    sonuc = {}
    for ad in SIRA:
        y = os.path.join(KOK, f"ikiz_{ad}.db")
        if os.path.exists(y):
            s = olc(y)
            if s:
                sonuc[ad] = s

    if TEMEL_AD not in sonuc:
        print("temel kosu (ikiz_risk28.db) yok."); return

    print(f"\n{'='*102}")
    print("=== DONEM BOLMESI · her yari KENDI ICINDE olculdu ===")
    print(f"  TRAIN 2023-04 -> 2024-12   |   TEST 2025-01 -> 2026-07")
    print(f"{'='*102}")
    bas = f"{'config':<13s}"
    bas += f"{'n':>6s}{'TR yillik%':>12s}{'TR maxDD%':>11s}{'TR MAR':>8s}"
    bas += f"   |{'n':>6s}{'TE yillik%':>12s}{'TE maxDD%':>11s}{'TE MAR':>8s}"
    print(bas); print("-" * 102)
    for ad in SIRA:
        if ad not in sonuc:
            continue
        tr, te = sonuc[ad]["train"], sonuc[ad]["test"]
        s = f"{ETIKET.get(ad, ad):<13s}"
        s += f"{tr['n']:>6d}{tr['yillik']*100:>12.1f}{tr['maxdd']*100:>11.1f}{tr['mar']:>8.2f}"
        if te:
            s += f"   |{te['n']:>6d}{te['yillik']*100:>12.1f}{te['maxdd']*100:>11.1f}{te['mar']:>8.2f}"
        else:
            s += "   |   (TEST verisi yetersiz)"
        print(s)
    print("-" * 102)

    t = sonuc[TEMEL_AD]
    print(f"\n  TEMEL = {ETIKET[TEMEL_AD]}   "
          f"TRAIN MAR {t['train']['mar']:.2f}  "
          f"TEST MAR {t['test']['mar']:.2f}" if t["test"] else "")
    print("\n  HUKUMLER (temele gore, IKI yarida da iyilesme sarti):")
    for ad in SIRA:
        if ad == TEMEL_AD or ad not in sonuc:
            continue
        a, b = sonuc[ad], t
        if not (a["test"] and b["test"]):
            continue
        dtr = a["train"]["mar"] - b["train"]["mar"]
        dte = a["test"]["mar"] - b["test"]["mar"]
        if dtr > 0 and dte > 0:
            h = "GECTI - iki yarida da daha iyi denge"
        elif dtr > 0 or dte > 0:
            h = "KALDI - yalnizca tek yarida iyi (uydurma riski)"
        else:
            h = "KALDI - iki yarida da daha kotu"
        print(f"    {ETIKET.get(ad, ad):<13s} dMAR TRAIN {dtr:+.2f}   "
              f"TEST {dte:+.2f}   -> {h}")
    print(f"\n{'='*102}")
    print("  ⚠ Risk seviyeleri AYNI islemleri farkli boyutlarla kosuyor;")
    print("  aralarindaki fark yapisaldir, uydurma riski tasimaz. Filtreler")
    print("  (korel1/adx32/hold24) ISLEM SECIMINI degistirir -- onlar icin")
    print("  iki-yari sarti GERCEK bir sinavdir.")
    print(f"{'='*102}")


if __name__ == "__main__":
    main()
