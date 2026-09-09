"""
maruziyet.py — EŞZAMANLI MARUZİYET TAVANI: silen sürüm vs küçülten sürüm.

TEŞHİS (korele.py, 2026-09-09):
  · örtüşen AYNI YÖN çiftlerinin R korelasyonu +0.3102
  · örtüşen TERS YÖN çiftlerinin                −0.2247
  · aylık std %31.45, R-karıştırma null'u %24.98 → p=0.0105, ORTAK HAREKET GERÇEK
  · AMA kalabalıkla ort R DÜŞMÜYOR (1→7 için +0.137…+0.451, trend yok)

Bu son madde her şeyi belirliyor: **kalabalık işlemler KÖTÜ işlemler değil,
sadece KORELE işlemler.** Dolayısıyla:

  · SİLEN sürüm (klasik cap: N'inci aynı-yön pozisyonu REDDET) pozitif
    beklentili işlemleri atar → ledger'ın "silmek negatif beklentidir"
    kuralına çarpar. K=4 daha önce denendi, dolar-negatif çıktı. Kontrol
    olarak burada da var, aynı sonucu vermesi BEKLENİR.

  · KÜÇÜLTEN sürüm hiçbir işlemi atmaz: kalabalık anda açılanı küçültür,
    tenha anda açılanı büyütür, TOPLAM RİSKİ SABİT tutar. Korele varyansı
    hedefler, beklentiyi değil. Asıl aday budur.

f(n) = n^(-p) ailesi. p=0.5 korele pozisyonlar için klasik varyans
normalizasyonu (n korele pozisyonun toplam oynaklığı ~√n ile büyür).

⚠ NEDENSELLİK: n, açılış anında AÇIK olan aynı-yön pozisyon sayısıdır.
   Gelecek sayılmaz. Canlıda da tam olarak bu bilinir.

⚠ ÖLÇEK SABİTİ C: Σeff'i eşitleyen çarpan. Tam örneklemde hesaplanırsa
   ufak bir ileri-bakış olur. Walk-forward bölümünde C YALNIZ EĞİTİMDEN
   hesaplanıyor ve teste öyle taşınıyor.

Kullanım:  py maruziyet.py
"""
import sys

import numpy as np
import pandas as pd

import deployed_backtest as A
from korele import yukle, esZamanli

TOHUM = 20260909
BAR_KAR = 28.0 * A.CANLI_OLCEK


def olc(df, eff, sirali=True):
    pnl = df["R"].values * eff * A.BAL0
    # ⚠ kind="stable" ZORUNLU. 1579 işlemin 281'inin çıkış damgası EŞİT ve
    # np.argsort varsayılanı (quicksort) KARARSIZ: eşitleri keyfi sıralıyor,
    # equity yolu değişiyor, maxDD %27.35 çıkıyor. Ankorun yolu Python'un
    # stable sorted()'ı ve doğru değer %27.98. 0.63 puanlık sahte fark.
    idx = (np.argsort(df["cikis_ts"].values, kind="stable") if sirali
           else np.arange(len(df)))
    eq = A.BAL0 + np.cumsum(pnl[idx])
    ay = pd.Series(pnl, index=df["ay"].values).groupby(level=0).sum() / A.BAL0 * 100
    return {"kar": pnl.sum(), "dd": A.maxdd(np.concatenate([[A.BAL0], eq])),
            "kotu_ay": ay.min(), "std": ay.std(), "ay": ay,
            "sharpe": ay.mean() / ay.std(),
            "pf": pnl[pnl > 0].sum() / max(-pnl[pnl < 0].sum(), 1e-9)}


def kucult(df, p, C=None):
    """eff × n^(-p), sonra Σeff eşitlenecek şekilde ölçekle."""
    ham = df["eff"].values * df["es_ayni"].values ** (-float(p))
    if C is None:
        C = df["eff"].values.sum() / ham.sum()
    return ham * C, C


def sil(df, K):
    """Klasik cap: aynı yönde K'dan fazlası varken açılanı REDDET (KONTROL)."""
    return df["es_ayni"].values <= K


def tepe_marjin(df, eff, kald=10.0):
    m = eff / df["slp"].values / kald
    ol = []
    for g, c, mm in zip(df["giris_ts"].values, df["cikis_ts"].values, m):
        ol.append((g, +mm)); ol.append((c, -mm))
    ol.sort(key=lambda x: (x[0], -x[1]))
    cur = tp = 0.0
    for _, d in ol:
        cur += d; tp = max(tp, cur)
    return tp * 100


def main():
    df = esZamanli(yukle())
    t = olc(df, df["eff"].values)
    tm = tepe_marjin(df, df["eff"].values)
    print(f"\n{'=' * 100}")
    print(f"=== EŞZAMANLI MARUZİYET TAVANI ===")
    print(f"  TABAN  ${t['kar']:+.2f} · maxDD %{t['dd']:.2f} · en kötü ay %{t['kotu_ay']:.2f} · "
          f"aylık std %{t['std']:.2f} · Sharpe {t['sharpe']:.3f} · tepe marjin %{tm:.1f}")

    print(f"\n  [A] SİLEN SÜRÜM — klasik cap (KONTROL, negatif çıkması beklenir)")
    print(f"      {'K':>3s} {'kalan':>6s} {'Δ$':>9s} {'Δkötüay':>8s} {'Δstd':>7s} "
          f"{'ΔmaxDD':>7s} {'ΔSharpe':>8s} {'marjin':>7s}")
    for K in (2, 3, 4, 5, 6):
        m_ = sil(df, K); s = df[m_]
        if len(s) < 200: continue
        r = olc(s, s["eff"].values)
        print(f"      {K:>3d} {len(s):>6d} {r['kar']-t['kar']:>+9.2f} "
              f"{r['kotu_ay']-t['kotu_ay']:>+8.2f} {r['std']-t['std']:>+7.2f} "
              f"{r['dd']-t['dd']:>+7.2f} {r['sharpe']-t['sharpe']:>+8.3f} "
              f"{tepe_marjin(s, s['eff'].values):>6.1f}%")

    print(f"\n  [B] KÜÇÜLTEN SÜRÜM — hiçbir işlem silinmez, Σrisk SABİT (ASIL ADAY)")
    print(f"      {'p':>5s} {'Δ$':>9s} {'Δkötüay':>8s} {'Δstd':>7s} {'ΔmaxDD':>7s} "
          f"{'ΔSharpe':>8s} {'marjin':>7s}  bar")
    for p in (0.25, 0.5, 0.75, 1.0):
        e, C = kucult(df, p)
        assert abs(e.sum() - df["eff"].values.sum()) < 1e-9, "RİSK EŞİTLEME BOZUK"
        r = olc(df, e)
        gecti = (r["kar"] - t["kar"] >= BAR_KAR and r["kotu_ay"] >= t["kotu_ay"]
                 and r["dd"] - t["dd"] <= 2.0)
        print(f"      {p:>5.2f} {r['kar']-t['kar']:>+9.2f} {r['kotu_ay']-t['kotu_ay']:>+8.2f} "
              f"{r['std']-t['std']:>+7.2f} {r['dd']-t['dd']:>+7.2f} "
              f"{r['sharpe']-t['sharpe']:>+8.3f} {tepe_marjin(df, e):>6.1f}%  "
              f"{'✓ GEÇTİ' if gecti else '✗'}")
    print(f"      (Σeff eşitlemesi her satırda doğrulandı)")
    print(f"{'=' * 100}\n")


if __name__ == "__main__":
    main()
