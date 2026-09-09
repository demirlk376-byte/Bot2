"""
funding_test.py — POZİSYONLANMA HİPOTEZİ: funding sahte kırılımı ayırt ediyor mu?

Bugüne kadar denenen 17 özelliğin hepsi FİYATTAN türetilmişti (adx, atr, kanal,
verimlilik, BTC bağlamı) ve hepsi null çıktı. Funding fiyat değil POZİSYONLANMA
verisidir — örneklenmemiş tek kanal.

NEDENSEL HİPOTEZ (yön-asimetrik, bu yüzden ham oran değil YÖNLÜ oran bakılır):
  LONG kırılım + yüksek POZİTİF funding = long'lar kalabalık ve ödüyor → SAHTE
  SHORT kırılım + yüksek NEGATİF funding = short'lar kalabalık        → SAHTE
  → tek değişken:  f_yon = funding_rate × yon   (yüksek = "benim yönümde kalabalık")
  Hipotez: f_yon yükseldikçe R DÜŞMELİ.

⚠ KAPSAM: MEXC'in API'si `since`'i yok sayıyor, elde 2025-10-11 sonrası var.
   Ankorun %22.9'u. Taban bu betikte PENCERE İÇİNDEN hesaplanıyor — tüm ankorla
   kıyaslamak sahte fark üretirdi.

⚠ GÜÇ: pencerede 361 işlem. %20'lik bir kesimin (n≈72) ort R'sinin standart
   hatası ±0.163; gürültüden ayrılmak için |ort R| > 0.319 gerekir. Bu pencerede
   NULL SONUÇ KESİN KAPANIŞ DEĞİLDİR — yalnız "güçlü bir etki yok" der.
   Kesin hüküm için funding_binance.py ile tam geçmiş gerekir.

Kullanım:  py funding_test.py
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

import deployed_backtest as A

TOHUM = 20260909
PERM = 4000


def funding_yukle():
    d = {}
    for p in glob.glob("data/*_funding_bnc.csv") or glob.glob("data/*_funding.csv"):
        coin = os.path.basename(p).split("_funding")[0]
        s = pd.read_csv(p, parse_dates=["dt"]).sort_values("dt")
        d[coin] = s.set_index("dt")["rate"]
    kaynak = "Binance (tam geçmiş)" if glob.glob("data/*_funding_bnc.csv") else "MEXC (kısıtlı)"
    return d, kaynak


def main():
    df = pd.read_csv("data/ay_analiz.csv")
    if len(df) != 1579:
        print(f"✗ ay_analiz.csv {len(df)} satır"); sys.exit(2)
    df["giris"] = pd.to_datetime(df["giris"])
    df["cikis_ts"] = pd.to_datetime(df["cikis_ts"])
    fd, kaynak = funding_yukle()
    if not fd:
        print("✗ funding verisi yok"); sys.exit(2)

    # giriş anında YÜRÜRLÜKTE olan funding (girişten ÖNCEKİ son kayıt) — lookahead yok
    par = []
    for coin, g in df.groupby("coin"):
        s = fd.get(coin)
        if s is None:
            continue
        m = pd.merge_asof(g.sort_values("giris"), s.rename("fund").reset_index(),
                          left_on="giris", right_on="dt", direction="backward",
                          tolerance=pd.Timedelta("16h"))
        par.append(m)
    d = pd.concat(par).dropna(subset=["fund"]).reset_index(drop=True)
    d["f_yon"] = d["fund"] * d["yon"]
    # coin-içi z: oranların ölçeği coinden coine değişir
    d["f_z"] = d.groupby("coin")["fund"].transform(lambda x: (x - x.mean()) / (x.std() + 1e-12))
    d["fz_yon"] = d["f_z"] * d["yon"]

    print(f"\n{'=' * 96}")
    print(f"=== FUNDING / POZİSYONLANMA TESTİ ===   kaynak: {kaynak}")
    print(f"  eşleşen {len(d)}/1579 işlem (%{len(d)/1579*100:.1f})  ·  "
          f"{d.giris.min().date()} → {d.giris.max().date()}")
    print(f"  pencere içi taban: ort R {d.R.mean():+.4f} · σ {d.R.std():.3f} · "
          f"WR %{(d.R>0).mean()*100:.1f}")
    se20 = d.R.std() / np.sqrt(len(d) * 0.2)
    print(f"  GÜÇ: %20'lik kesim için ort R std hatası ±{se20:.3f}; "
          f"anlamlılık eşiği |R|>{1.96*se20:.3f}\n")

    print(f"  [1] HİPOTEZ DOĞRUDAN — f_yon yükseldikçe R düşüyor mu?")
    print(f"      (hipotez DOĞRUYSA soldan sağa ort R AZALMALI)")
    for ad, kol in (("yönlü ham oran", "f_yon"), ("yönlü z-skor", "fz_yon")):
        q = pd.qcut(d[kol], 5, labels=False, duplicates="drop")
        g = d.groupby(q)["R"].agg(["mean", "size"])
        print(f"      {ad:<16s}" + "".join(f"{r['mean']:>+9.3f}(n{int(r['size']):>3d})"
                                            for _, r in g.iterrows()))
        rho = np.corrcoef(pd.Series(d[kol]).rank(), pd.Series(d.R).rank())[0, 1]
        rng = np.random.default_rng(TOHUM)
        null = np.array([np.corrcoef(rng.permutation(pd.Series(d[kol]).rank().values),
                                     pd.Series(d.R).rank().values)[0, 1] for _ in range(2000)])
        print(f"      {'':16s}  Spearman {rho:+.4f}  permütasyon p={(np.abs(null)>=abs(rho)).mean():.4f}"
              f"   {'← hipotez yönü' if rho < 0 else '← hipotezin TERSİ'}")

    print(f"\n  [2] ADAY FİLTRELER — pencere içi, aynı çıta")
    print(f"      {'aday':<30s} {'sil%':>5s} {'ortR':>7s} {'Δ$':>8s} {'perm%':>6s}  hüküm")
    taban_kar = (d.R * d.eff * A.BAL0).sum()
    rng = np.random.default_rng(TOHUM)
    adaylar = [("fz_yon > 1.0", d.fz_yon > 1.0), ("fz_yon > 1.5", d.fz_yon > 1.5),
               ("fz_yon > 0.5", d.fz_yon > 0.5),
               ("f_yon > 0 (basit)", d.f_yon > 0),
               ("fz_yon > 1 & kol=='donchian'", (d.fz_yon > 1.0) & (d.kol == "donchian"))]
    for ad, mask in adaylar:
        k = int(mask.sum())
        if k < 15 or k > len(d) * 0.6:
            print(f"      {ad:<30s} {k/len(d)*100:>4.1f}%  {'—':>7s}  n uygun değil"); continue
        yeni = (d.R[~mask] * d.eff[~mask] * A.BAL0).sum()
        perm = np.array([(d.R.values * d.eff.values * A.BAL0)[
            np.setdiff1d(np.arange(len(d)), rng.choice(len(d), k, replace=False))].sum()
            for _ in range(PERM // 4)])
        yz = (perm < yeni).mean() * 100
        r_sil = d.R[mask].mean()
        gec = (r_sil < 0 and yz >= 95 and yeni - taban_kar > 0)
        print(f"      {ad:<30s} {k/len(d)*100:>4.1f}% {r_sil:>+7.3f} {yeni-taban_kar:>+8.2f} "
              f"{yz:>5.1f}%  {'✓' if gec else '✗'}")
    print(f"{'=' * 96}\n")


if __name__ == "__main__":
    main()
