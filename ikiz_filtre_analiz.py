"""
ikiz_filtre_analiz.py — bir filtrenin GERCEKTEN ise yarayip yaramadigini olcer.

NEDEN AYRI BIR TEST: ozet tablosu filtrenin son bakiyesini gosteriyor, ama
bakiye tek bir yolun sonucu. korel1 ornegin +%31 daha fazla bakiye verdi,
oysa ortalama R farki yalnizca +0.0084 -- gurultu esiginin cok altinda. Bakiye
farki gercek bir etkiden de gelebilir, elenen 98 islemin sansli secilmesinden
de. Ayirmak icin dogru soru su:

  FILTRENIN ELEDIGI ISLEMLER, ORTALAMADAN KOTU MUYDU?

Bu soru cok daha guclu, cunku dogrudan test edilebilir. H0: filtre rastgele bir
alt kume eliyor. O zaman elenenlerin ortalama R'si N(mu_temel, sigma/sqrt(n))
dagilir. Elenenlerin ortalamasi bu dagilimin belirgin ALTINDAysa filtre gercek
is yapiyor demektir.

Ayrica TRAIN/TEST bolmesi: etki YALNIZ tek bir donemde varsa uydurmadir.
Gercek bir filtre iki yarida da ayni yone basar.

Kullanim:
  py ikiz_filtre_analiz.py                    → tum filtreleri ikiz_risk28'e karsi
  py ikiz_filtre_analiz.py temel.db aday.db   → iki belirli kosu
"""
import os, sys, glob, json, sqlite3
import pandas as pd, numpy as np

KOK = os.path.dirname(os.path.abspath(__file__))
# ⚠ temel tercihen AYNI TARAMADAN gelmeli. ikiz_taban.db, geri-verme
# taramasinda degisiklik icermeyen kosudur; yoksa onceki taramanin canli
# ayarina (ikiz_risk28.db) dusulur.
_T1 = os.path.join(KOK, "ikiz_taban.db")
_T2 = os.path.join(KOK, "ikiz_risk28.db")
TEMEL = _T1 if os.path.exists(_T1) else _T2
BOLME = pd.Timestamp("2025-01-01", tz="UTC")     # TRAIN | TEST
ADAYLAR = ["adx20", "adx25", 'teyit1', 'teyit2', 'retest2', 'retest4', 'hacim15', 'hacim20', 'obv', 'hacim_obv', 'be_don', 'be_all', 'be15', 'tr30', 'tr20', 'tr15', 'tr20g', 'be_tr', "trail10", "trail15", "be05", "bt", "rr15",
           "buf05", "adxr25", "cl1", "korel1", "adx32", "hold24", "guven"]
ETIKET = {"adx20": "ADX>=20", "adx25": "ADX>=25",
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
          "be_tr": "BE + takip 2x",
          "korel1": "korel 1", "adx32": "ADX 32", "hold24": "tutus 24",
          "guven": "guven boyut",
          "trail10": "takip 1.0",
          "trail15": "takip 1.5",
          "be05": "basabas 0.5",
          "bt": "basabas+takip",
          "rr15": "RR 1.5",
          "buf05": "tampon 0.5",
          "adxr25": "ADX yatay 25",
          "cl1": "1 zarar/8sa"}


def _stop_mesafesi(d):
    """R'nin paydasi: giris ile BASLANGIC stop'u arasi.

    ⚠ sl_price sutunu kullanilmaz -- stop tasinirsa (basabas/ATR takibi) o
    sutun guncelleniyor ve payda sifira yakinsayip R'yi patlatiyor. Islem
    acilirken strategy_scores'a yazilan sl0 hic degismez. Eski kosularda sl0
    yoksa sl_price'a dusulur (o kosularda stop zaten tasinmiyordu)."""
    sl0 = d.strategy_scores.apply(
        lambda s: (json.loads(s or "{}") or {}).get("sl0"))
    taban = sl0.where(sl0.notna(), d.sl_price).astype("float64")
    return (d.entry_price - taban).abs()


def oku(yol):
    con = sqlite3.connect(yol, timeout=60)
    try:
        d = pd.read_sql(
            "SELECT symbol,side,entry_price,exit_price,sl_price,entry_time,"
            "exit_time,pnl_usdt,strategy_scores FROM trades "
            "WHERE exit_time IS NOT NULL", con)
    finally:
        con.close()
    d["giris"] = pd.to_datetime(d.entry_time, utc=True, format="mixed")
    yon  = 1 - 2 * d.side.str.lower().str.startswith("s").astype(int)
    stop = _stop_mesafesi(d)
    d["R"] = np.where(stop > 0,
                      yon * (d.exit_price - d.entry_price) / stop.replace(0, np.nan),
                      np.nan)
    d["kol"] = d.strategy_scores.apply(
        lambda s: (json.loads(s or "{}") or {}).get("strategy", "?"))
    # ⚠ anahtar BOYUTTAN BAGIMSIZ alanlardan kurulmali. Filtre bakiye yolunu
    # degistirdigi icin miktarlar farklilasir, ama sinyalin kendisi (hangi coin,
    # hangi yon, hangi an) degismez. R de boyuttan bagimsiz -- bu yuzden iki
    # kosunun ayni islemi guvenle eslesir.
    d["anahtar"] = (d.symbol + "|" + d.side.str.lower() + "|"
                    + d.giris.astype("int64").astype(str))
    return d


def _z(alt, mu, sigma):
    """H0: 'alt' temelden rastgele secilmis bir alt kume. z<0 => elenenler
    ortalamadan KOTUYDU => filtre is yapiyor."""
    n = len(alt)
    if n < 2 or not np.isfinite(sigma) or sigma <= 0:
        return float("nan"), float("nan")
    ort = float(alt.R.mean())
    return ort, (ort - mu) / (sigma / np.sqrt(n))


def karsilastir(temel, aday, ad):
    mu, sg = float(temel.R.mean()), float(temel.R.std())
    t_anah, a_anah = set(temel.anahtar), set(aday.anahtar)
    elenen = temel[temel.anahtar.isin(t_anah - a_anah)]
    eklenen = aday[aday.anahtar.isin(a_anah - t_anah)]

    print(f"\n{'='*94}")
    print(f"=== {ad}   (temel: {os.path.basename(TEMEL)} · n={len(temel)} "
          f"· ort R {mu:+.4f} "
          f"· sigma {sg:.3f})")
    print(f"{'='*94}")
    print(f"  aday n={len(aday)}   elenen {len(elenen)}   yeni acilan {len(eklenen)}")
    if not len(elenen):
        print("  hicbir islem elenmemis -> bu bir SECIM filtresi degil, "
              "yalnizca boyut/zamanlama degistiriyor.")
        return

    print(f"\n  {'donem':<8s}{'elenen':>8s}{'elenen ortR':>14s}"
          f"{'z':>8s}{'karar':>26s}")
    print("  " + "-" * 62)
    satirlar = [("TUMU", elenen),
                ("TRAIN", elenen[elenen.giris <  BOLME]),
                ("TEST",  elenen[elenen.giris >= BOLME])]
    zler = {}
    for etiket, alt in satirlar:
        ort, z = _z(alt, mu, sg)
        zler[etiket] = z
        if not np.isfinite(z):
            karar = "veri yetersiz"
        elif z <= -1.96:
            karar = "elenenler GERCEKTEN kotu"
        elif z >= 1.96:
            karar = "elenenler IYIYDI (zarar)"
        else:
            karar = "ayirt edilemiyor"
        print(f"  {etiket:<8s}{len(alt):>8d}{ort:>+14.4f}{z:>8.2f}{karar:>26s}")

    print(f"\n  elendigi kollar: "
          + "  ".join(f"{k} {len(g)}" for k, g in elenen.groupby("kol")))
    tr, te = zler.get("TRAIN"), zler.get("TEST")
    print("\n  HUKUM: ", end="")
    if (np.isfinite(tr) and np.isfinite(te)
            and tr <= -1.96 and te <= -1.96):
        print("GECTI - filtre her iki yarida da kotu islemleri eliyor.")
    elif (np.isfinite(tr) and np.isfinite(te) and tr < 0 and te < 0):
        print("ZAYIF - iki yarida da dogru yone basiyor ama gurultuden "
              "ayrilmiyor.\n          Daha fazla veri olmadan karar verilemez.")
    else:
        print("KALDI - etki iki yarida tutarli degil. Bakiye farki "
              "muhtemelen\n          sans; canliya ALINMAMALI.")


def main():
    if len(sys.argv) > 2:
        karsilastir(oku(sys.argv[1]), oku(sys.argv[2]),
                    os.path.basename(sys.argv[2]))
        return
    if not os.path.exists(TEMEL):
        print(f"temel kosu yok: {TEMEL}\n  once L_GERIVERME.bat calistir.")
        return
    temel = oku(TEMEL)
    for ad in ADAYLAR:
        yol = os.path.join(KOK, f"ikiz_{ad}.db")
        if os.path.exists(yol):
            karsilastir(temel, oku(yol), ETIKET.get(ad, ad))
        else:
            print(f"\n  (yok, atlandi: ikiz_{ad}.db)")
    print(f"\n{'='*94}")
    print("  Not: TRAIN 2023-04 -> 2024-12, TEST 2025-01 -> 2026-07.")
    print("  Bir filtre YALNIZ TRAIN'de calisiyorsa gecmise uydurulmus demektir.")
    print(f"{'='*94}")


if __name__ == "__main__":
    main()
