"""Ayni-mum farkinda yon butcesi -- POST-HOC. Islem dizisi degismez, yalniz boyut."""
import numpy as np, pandas as pd
d = pd.read_pickle("islemler3.pkl").sort_values(["giris", "coin"]).reset_index(drop=True)
R_net = (d.ret / d.risk_pct).values; risk0 = d.risk_pct.values
g = d.giris.values; c = d.cikis.values; s = d.sgn.values; kol = d.kol.values
TR = (d.cikis < pd.Timestamp("2025-01-01", tz="UTC")).values
# ayni mum + ayni yon grup buyuklugu
grp = d.groupby(["giris", "side"]).R.transform("size").values

def boyutla(B=None, grup_esik=None, grup_carp=None, sadece_grup=False):
    risk = np.zeros(len(d))
    for i in range(len(d)):
        r = risk0[i]
        if grup_esik is not None and grp[i] >= grup_esik:
            r = r * grup_carp(grp[i])
        if B is not None:
            once = (g < g[i]) & (c > g[i]) & (s == s[i])                # daha once acilmis ayni yon
            acik = risk[once].sum()
            pay = (B - acik) / grp[i]                                  # ayni mumdaki gruba esit pay
            if not sadece_grup or grp[i] >= 2:
                r = max(0.0, min(r, pay))
        risk[i] = r
    return risk

def olc(risk, m):
    x = d.loc[m].assign(r=R_net[m] * risk[m]).sort_values("cikis")
    eq = np.cumprod(1 + x.r.values); dd = (1 - eq / np.maximum.accumulate(eq)).max()
    yil = (x.cikis.iloc[-1] - x.giris.iloc[0]).days / 365.25
    cagr = eq[-1] ** (1 / yil) - 1
    return cagr, dd, cagr / dd, x.groupby(x.cikis.dt.floor("D")).r.sum().min()

var = [("taban", {}),
       ("grup>=3 -> toplam 2 poz", dict(grup_esik=3, grup_carp=lambda n: 2.0 / n)),
       ("grup>=3 -> toplam 3 poz", dict(grup_esik=3, grup_carp=lambda n: 3.0 / n)),
       ("grup>=2 -> 1/sqrt(n)", dict(grup_esik=2, grup_carp=lambda n: 1 / np.sqrt(n))),
       ("grup>=3 -> 1/sqrt(n)", dict(grup_esik=3, grup_carp=lambda n: 1 / np.sqrt(n))),
       ("yon butce %7 +aynimum", dict(B=0.070)),
       ("yon butce %10.5 +aynimum", dict(B=0.105)),
       ("yon butce %14 +aynimum", dict(B=0.140)),
      ]
print(f"{'kural':<26s} | {'TR yil%':>7s} {'DD%':>5s} {'MAR':>6s} | {'TE yil%':>7s} {'DD%':>5s} {'MAR':>6s} {'kotu gun':>8s} | {'dTR':>6s} {'dTE':>6s}  ort risk")
t0 = None
for ad, kw in var:
    r = boyutla(**kw); a = olc(r, TR); b = olc(r, ~TR)
    t0 = t0 or (a[2], b[2])
    print(f"{ad:<26s} | {a[0]*100:7.1f} {a[1]*100:5.1f} {a[2]:6.2f} | {b[0]*100:7.1f} {b[1]*100:5.1f} {b[2]:6.2f} {b[3]*100:7.1f}% | {a[2]-t0[0]:+6.2f} {b[2]-t0[1]:+6.2f}  %{r.mean()*100:.2f}")
