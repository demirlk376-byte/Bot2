"""
btc_eksen.py — BTC / ÇAPRAZ-VARLIK BOYUTU: kötü ay araştırmasının son ekseni.

MANTIK: tek bir coinin rejimi gürültülü olabilir ama PİYASA GENELİ rejim daha
kararlı olabilir. Eski bulgu "rejim anti-persistent" (ADX ay-ay otokorelasyon
−0.379) TEK COİN ADX'i içindi. BTC farklı çıkarsa bu yeni bir olgudur.

⚠ DOĞRU NULL — bu betiğin varlık sebebi:
   288 kötü-ay işlemi yalnız 8 AYDAN geliyor. İşlemleri bağımsız sayan her test
   (i.i.d. Mann-Whitney, düz AUC p'si) serbestlik derecesini ~36 kat şişirir ve
   gürültüyü "p=0.00001" diye raporlar. Gerçek serbestlik 8 vs 32 AY.
   Bu yüzden anlamlılık AY-ETİKETİ PERMÜTASYONU ile ölçülüyor: hangi ayların
   "kötü" olduğu karıştırılıyor, işlemlerin ay içi grupları BOZULMADAN.

⚠ GEOMETRİK ÇITA (2026-09-09'da ölçüldü): kullanıcının "iyi aylardan ≤%5 sil"
   şartı, 288 kötü-ay işlemini yakalarken en fazla 64 iyi-ay işlemi harcamaya
   izin veriyor → TPR≈1.00 @ FPR≈0.05 → AUC≈0.99 gerekiyor. Bu betikte bulunan
   her AUC o çıtaya karşı raporlanıyor. 0.60 ile 0.99 arası arama ile kapanmaz.

Kullanım:  py btc_eksen.py
"""
import sys

import numpy as np
import pandas as pd

VERI = "data/ay_analiz.csv"
BTC = ["btc_adx", "btc_er20", "btc_get20", "btc_atr_pct", "btc_ic40"]
COIN = ["adx14", "er20", "get20", "atr_pct", "ic_oran40"]
TOHUM = 20260909
PERM = 20000
AUC_GEREKEN = 0.99


def yukle():
    df = pd.read_csv(VERI)
    if len(df) != 1579:
        print(f"✗ {len(df)} satır, 1579 bekleniyordu"); sys.exit(2)
    df["cikis_ts"] = pd.to_datetime(df["cikis_ts"])
    df["ay"] = df["cikis_ts"].dt.tz_localize(None).dt.to_period("M")
    df["pnl"] = df["R"] * df["eff"] * 100.0
    return df


def auc(skor, etiket):
    """etiket=1 olanların skoru daha YÜKSEK olma olasılığı."""
    ok = np.isfinite(skor)
    s, e = skor[ok], etiket[ok]
    if e.sum() == 0 or e.sum() == len(e): return np.nan
    r = pd.Series(s).rank().values
    n1 = e.sum(); n0 = len(e) - n1
    return (r[e == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


def main():
    df = yukle()
    rng = np.random.default_rng(TOHUM)
    ay_pnl = df.groupby("ay")["pnl"].sum()
    aylar = ay_pnl.index.values
    kotu_ay = set(ay_pnl[ay_pnl <= 0].index)
    df["kotu"] = df["ay"].isin(kotu_ay).astype(int)
    n_kotu = len(kotu_ay)

    print(f"\n{'=' * 100}")
    print(f"=== BTC / ÇAPRAZ-VARLIK EKSENİ ===")
    print(f"  {len(aylar)} ay ({n_kotu} kötü) · {len(df)} işlem ({df.kotu.sum()} kötü ayda)")
    print(f"  Anlamlılık: AY-ETİKETİ permütasyonu ({PERM:,} tekrar), i.i.d. DEĞİL.\n")

    # ── (a) AYRIM GÜCÜ ──
    print(f"  [a] AYRIM GÜCÜ — BTC özellikleri kötü-ay işlemlerini ayırıyor mu?")
    print(f"      gereken AUC ≈ {AUC_GEREKEN} (kullanıcının %5 şartı)   "
          f"| eşik yön: |AUC−0.5|")
    print(f"      {'özellik':<14s} {'kötü ort':>10s} {'iyi ort':>10s} {'AUC':>7s} "
          f"{'|AUC-.5|':>9s} {'ay-perm p':>10s}")
    ay_dizi = df["ay"].values
    sonuc = {}
    for f in BTC + COIN:
        s = df[f].values.astype(float)
        a = auc(s, df["kotu"].values)
        k = df.loc[df.kotu == 1, f].mean(); i = df.loc[df.kotu == 0, f].mean()
        # ay-etiketi permütasyonu: rastgele n_kotu ay "kötü" seçilir
        null = np.empty(PERM // 20)
        for t in range(len(null)):
            sec = set(rng.choice(aylar, size=n_kotu, replace=False))
            null[t] = abs(auc(s, np.isin(ay_dizi, list(sec)).astype(int)) - 0.5)
        p = (null >= abs(a - 0.5)).mean()
        sonuc[f] = (a, p)
        yildiz = " ←" if f in BTC else ""
        print(f"      {f:<14s} {k:>10.4f} {i:>10.4f} {a:>7.4f} {abs(a-0.5):>9.4f} "
              f"{p:>10.4f}{yildiz}")
    en = max(BTC, key=lambda f: abs(sonuc[f][0] - 0.5))
    print(f"      → BTC'nin en iyisi: {en} AUC {sonuc[en][0]:.4f} "
          f"(gereken {AUC_GEREKEN}) · p={sonuc[en][1]:.4f}")

    # ── (b) BTC REJİMİ PERSISTENT Mİ ──
    print(f"\n  [b] BTC REJİMİ KENDİ İÇİNDE KARARLI MI?")
    print(f"      Eski bulgu: tek-coin ADX ay-ay otokorelasyon −0.379 (ANTI-persistent).")
    print(f"      BTC farklıysa bu YENİ bir olgudur — filtre vermese bile.")
    print(f"      {'özellik':<14s} {'ay-ay otokor':>13s} {'permütasyon p':>14s}")
    aylik = df.groupby("ay")[BTC + COIN].mean()
    for f in BTC + COIN:
        v = aylik[f].values
        ok = np.isfinite(v); v = v[ok]
        r = np.corrcoef(v[:-1], v[1:])[0, 1]
        null = np.array([np.corrcoef(x[:-1], x[1:])[0, 1]
                         for x in (rng.permutation(v) for _ in range(2000))])
        p = (np.abs(null) >= abs(r)).mean()
        print(f"      {f:<14s} {r:>+13.3f} {p:>14.4f}")

    # ── (c) ÖNCEKİ AY ÖNGÖRÜYOR MU ──
    print(f"\n  [c] ÖNCEKİ AYIN BTC REJİMİ, BU AYIN SONUCUNU ÖNGÖRÜYOR MU?")
    print(f"      (uygulanabilir tek ay-seviyesi biçim: geçen ayı bilirsin)")
    p_ay = ay_pnl.values
    print(f"      {'özellik':<14s} {'korelasyon':>11s} {'işaret isabeti':>15s} {'perm p':>8s}")
    for f in BTC:
        v = aylik[f].values
        x, y = v[:-1], p_ay[1:]
        ok = np.isfinite(x) & np.isfinite(y); x, y = x[ok], y[ok]
        r = np.corrcoef(x, y)[0, 1]
        med = np.median(x)
        isabet = ((x > med) == (y > np.median(y))).mean()
        null = np.array([abs(np.corrcoef(rng.permutation(x), y)[0, 1]) for _ in range(4000)])
        print(f"      {f:<14s} {r:>+11.3f} {isabet*100:>14.1f}% {(null >= abs(r)).mean():>8.4f}")
    print(f"      referans: hiçbir şey yapmamak = %{(p_ay > 0).mean()*100:.0f} isabet")

    # ── (d) BİRLEŞİM: coin ADX × BTC ADX ──
    print(f"\n  [d] BİRLEŞİM — coinin kendi ADX'i × BTC ADX (3×3 kova, ort R)")
    qc = pd.qcut(df["adx14"], 3, labels=["düşük", "orta", "yüksek"])
    qb = pd.qcut(df["btc_adx"], 3, labels=["düşük", "orta", "yüksek"])
    tab = df.groupby([qc, qb], observed=True)["R"].agg(["mean", "size"])
    baslik = "coin/BTC"
    print(f"      {baslik:<10s}" + "".join(f"{c:>16s}" for c in ["düşük", "orta", "yüksek"]))
    for c in ["düşük", "orta", "yüksek"]:
        sat = f"      {c:<10s}"
        for b in ["düşük", "orta", "yüksek"]:
            try:
                m, n = tab.loc[(c, b), "mean"], int(tab.loc[(c, b), "size"])
                sat += f"{m:>+10.3f}(n{n:>3d})"
            except KeyError:
                sat += f"{'—':>16s}"
        print(sat)
    neg = tab[tab["mean"] < 0]
    print(f"      → 9 kovanın {len(neg)}'ünde ort R negatif"
          f"{'' if len(neg) == 0 else ' → aday üretilebilir'}")
    print(f"{'=' * 100}\n")


if __name__ == "__main__":
    main()
