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
# ⚠ TEMEL "taban" OLMALI. Eskiden sabit "risk28" idi ve bu, hukumleri ESKI
# bir kosuya gore veriyordu: 2026-09-20'de gelecek sizintisi duzeltilince taban
# 1778 islem/+0.1581'den 1752/+0.1675'e ve TRAIN MAR 5.87'den 9.77'ye tasindi.
# Hukumler sizintili rakama gore verilince hepsi yanlis cikti. "taban" kosusu
# her taramada var ve DEGISIKLIK ICERMEZ -- dogru referans odur.
TEMEL_ADAYLARI = ("taban", "risk28")
SIRA = ["taban", 'mg', 'mc', 'mgc', 'mgcf', 'mgcf_mk', 'f_taban', 'f_mgcf', 'f_mgcf_mk', 'f', 'f24', 'f20', 'f17', 'f14', 'r24', 'r20', 'r17', 't1', 'h20', 'h15', 't1h20', 't1h15', 't1obv', 't1h20k', 't1h20r20', "adx20", "adx25", 'teyit1', 'teyit2', 'retest2', 'retest4', 'hacim15', 'hacim20', 'obv', 'hacim_obv', 'be_don', 'be_all', 'be15', 'tr30', 'tr20', 'tr15', 'tr20g', 'be_tr', "risk10", "risk14", "risk17", "risk20", "risk28", "risk35", "risk40",
        "korel1", "kor17", "kor20", "kor24", "kor28",
        "adx32", "hold24", "guven",
        "trail10", "trail15", "be05", "bt", "rr15", "buf05", "adxr25", "cl1"]
ETIKET = {"taban": "TABAN canli",
          "mg": "gercek giris",
          "mc": "gercek cikis",
          "mgc": "giris+cikis",
          "mgcf": "GERCEK maliyet",
          "mgcf_mk": "gercek + maker",
          "f_taban": "filtre (eski model)",
          "f_mgcf": "filtre + GERCEK",
          "f_mgcf_mk": "filtre + gercek + maker",
          "f": "FILTRE %2.8",
          "f24": "FILTRE %2.4",
          "f20": "FILTRE %2.0",
          "f17": "FILTRE %1.7",
          "f14": "FILTRE %1.4",
          "r24": "filtresiz %2.4",
          "r20": "filtresiz %2.0",
          "r17": "filtresiz %1.7",
          "t1": "teyit1",
          "h20": "hacim2.0",
          "h15": "hacim1.5",
          "t1h20": "teyit1+h2.0",
          "t1h15": "teyit1+h1.5",
          "t1obv": "teyit1+OBV",
          "t1h20k": "teyit1+h2.0+korel",
          "t1h20r20": "teyit1+h2.0+%2.0risk",
          "adx20": "ADX>=20", "adx25": "ADX>=25",
          "teyit1": "teyit 1 bar",
          "teyit2": "teyit 2 bar",
          "retest2": "retest 2b",
          "retest4": "retest 4b",
          "hacim15": "hacim 1.5x",
          "hacim20": "hacim 2.0x",
          "obv": "OBV teyit",
          "hacim_obv": "hacim+OBV",
          "be_don": "BE donchian",
          "be_all": "BE don+sq",
          "be15": "BE 1.5R",
          "tr30": "takip 3xATR",
          "tr20": "takip 2xATR",
          "tr15": "takip 1.5xATR",
          "tr20g": "takip 2x @1R",
          "be_tr": "BE + takip 2x", "risk10": "%1.0", "risk14": "%1.4", "risk17": "%1.7", "risk20": "%2.0",
          "risk28": "%2.8 CANLI", "risk35": "%3.5", "risk40": "%4.0",
          "korel1": "korel 1", "kor28": "korel+%2.8", "kor24": "korel+%2.4",
          "kor20": "korel+%2.0", "kor17": "korel+%1.7",
          "trail10": "takip 1.0",
          "trail15": "takip 1.5",
          "be05": "basabas 0.5",
          "bt": "basabas+takip",
          "rr15": "RR 1.5",
          "buf05": "tampon 0.5",
          "adxr25": "ADX yatay 25",
          "cl1": "1 zarar/8sa",
          "adx32": "ADX 32", "hold24": "tutus 24",
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
        return {"_hata": f"donemde yalniz {len(alt)} islem"}
    eq = pd.concat([pd.Series([bas_bakiye]),
                    bas_bakiye + alt.pnl_usdt.cumsum()], ignore_index=True)
    tepe = eq.cummax()
    maxdd = float(((tepe - eq) / tepe).max())
    gun = max(1, (alt.cikis.max() - alt.cikis.min()).days)
    buyume = float(eq.iloc[-1]) / bas_bakiye
    if buyume <= 0:
        return {"_hata": f"donem sonu bakiye {eq.iloc[-1]:,.0f} (<=0)"}
    yillik = buyume ** (365.0 / gun) - 1.0
    return {"n": len(alt), "son": float(eq.iloc[-1]), "gun": gun,
            "yillik": yillik, "maxdd": maxdd,
            "mar": (yillik / maxdd) if maxdd > 0 else float("nan")}


def olc(yol):
    # ⚠ SESSIZCE ATLAMA. Ilk surum sorunlu kosulari None dondurup tablodan
    # dusuruyordu ve dort risk seviyesi sebebi GORUNMEDEN kayboldu. Artik
    # her atlama SEBEBIYLE birlikte basiliyor.
    try:
        d = oku(yol)
    except Exception as e:
        return {"_hata": f"okunamadi: {type(e).__name__}: {e}"}
    if len(d) < 20:
        return {"_hata": f"yalniz {len(d)} kapanmis islem"}
    ilk, son = d.cikis.min(), d.cikis.max() + pd.Timedelta(days=1)
    tr = yari(d, BAL0, ilk, BOLME)
    if "_hata" in tr:
        return {"_hata": "TRAIN: " + tr["_hata"]}
    te = yari(d, tr["son"], BOLME, son)
    return {"train": tr, "test": (None if "_hata" in te else te),
            "test_hata": te.get("_hata") if "_hata" in te else None}


def main():
    sonuc, sorunlu = {}, []
    for ad in SIRA:
        y = os.path.join(KOK, f"ikiz_{ad}.db")
        if not os.path.exists(y):
            sorunlu.append(f"ikiz_{ad}.db  -> DOSYA YOK")
            continue
        s = olc(y)
        if "_hata" in s:
            sorunlu.append(f"ikiz_{ad}.db  -> {s['_hata']}")
        else:
            sonuc[ad] = s
    if sorunlu:
        print("\n  ATLANAN KOSULAR:")
        for x in sorunlu:
            print(f"    {x}")

    TEMEL_AD = next((a for a in TEMEL_ADAYLARI if a in sonuc), None)
    if TEMEL_AD is None:
        print("temel kosu yok (ikiz_taban.db veya ikiz_risk28.db gerekli).")
        return
    if TEMEL_AD != "taban":
        print("\n  ⚠ 'taban' kosusu yok; hukumler ESKI bir referansa gore "
              "veriliyor.\n    Dogru karsilastirma icin taramayi taban "
              "kosusuyla birlikte calistir.")

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
