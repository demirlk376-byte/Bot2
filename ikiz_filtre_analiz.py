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
TEMEL = os.path.join(KOK, "ikiz_risk28.db")      # canli ayar (%2.8)
BOLME = pd.Timestamp("2025-01-01", tz="UTC")     # TRAIN | TEST
ADAYLAR = ["korel1", "adx32", "hold24", "guven"]
ETIKET = {"korel1": "korel 1", "adx32": "ADX 32", "hold24": "tutus 24",
          "guven": "guven boyut"}


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
    stop = (d.entry_price - d.sl_price).abs()
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
    print(f"=== {ad}   (temel: canli %2.8 · n={len(temel)} · ort R {mu:+.4f} "
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
        print(f"temel kosu yok: {TEMEL}\n  once B_RISK_TARAMA.bat calistir.")
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
