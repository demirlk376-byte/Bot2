"""Yon risk butcesi -- POST-HOC (islem dizisi degismez, yalniz boyut). IKIZ'de dogrulanmadan karar YOK."""
import numpy as np, pandas as pd
d = pd.read_pickle("islemler2.pkl").sort_values("giris").reset_index(drop=True)
R_net = (d.ret / d.risk_pct).values           # islem basina net R (ret = R_net * risk)
risk0 = d.risk_pct.values
g = d.giris.values; c = d.cikis.values; s = d.sgn.values

def yeniden_boyutla(kural):
    risk = np.zeros(len(d))
    for i in range(len(d)):
        acik = (g < g[i]) & (c > g[i])
        ayni = acik & (s == s[i])
        risk[i] = kural(risk0[i], risk[ayni].sum(), int(ayni.sum()), risk[acik & (s != s[i])].sum())
    return risk

def olc(risk, maske):
    x = d.loc[maske].copy(); x["r"] = R_net[maske] * risk[maske]
    x = x.sort_values("cikis")
    eq = np.cumprod(1 + x.r.values); dd = (1 - eq / np.maximum.accumulate(eq)).max()
    yil = (x.cikis.iloc[-1] - x.giris.iloc[0]).days / 365.25
    cagr = eq[-1] ** (1 / yil) - 1
    gun = x.groupby(x.cikis.dt.floor("D")).r.sum().min()
    return cagr, dd, cagr / dd, gun

kurallar = {
    "taban":              lambda r, a, k, z: r,
    "butce %7 (2 poz)":   lambda r, a, k, z: max(0.0, min(r, 0.070 - a)),
    "butce %8.75":        lambda r, a, k, z: max(0.0, min(r, 0.0875 - a)),
    "butce %10.5 (3 poz)":lambda r, a, k, z: max(0.0, min(r, 0.105 - a)),
    "butce %7 taban%1":   lambda r, a, k, z: max(0.010, min(r, 0.070 - a)),
    "1/sqrt(1+k)":        lambda r, a, k, z: r / np.sqrt(1 + k),
    "k>=2 yarim":         lambda r, a, k, z: r * (0.5 if k >= 2 else 1.0),
    "k>=3 yarim":         lambda r, a, k, z: r * (0.5 if k >= 3 else 1.0),
    "NET butce %7":       lambda r, a, k, z: max(0.0, min(r, 0.070 - (a - z))) if a - z > 0 else r,
}
TR = (d.cikis < pd.Timestamp("2025-01-01", tz="UTC")).values
print(f"{'kural':<22s} | {'TR yil%':>8s} {'TR DD%':>7s} {'TR MAR':>7s} | {'TE yil%':>8s} {'TE DD%':>7s} {'TE MAR':>7s} {'TE kotu gun':>11s} | dTR   dTE")
tab = None
for ad, k in kurallar.items():
    r = yeniden_boyutla(k)
    a = olc(r, TR); b = olc(r, ~TR)
    if tab is None: tab = (a[2], b[2])
    print(f"{ad:<22s} | {a[0]*100:8.1f} {a[1]*100:7.1f} {a[2]:7.2f} | {b[0]*100:8.1f} {b[1]*100:7.1f} {b[2]:7.2f} {b[3]*100:10.1f}% | {a[2]-tab[0]:+.2f} {b[2]-tab[1]:+.2f}"
          f"   (sifirlanan islem {(r == 0).sum()}, ort risk %{r.mean()*100:.2f})")
