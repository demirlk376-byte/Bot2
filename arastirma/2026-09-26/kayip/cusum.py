import numpy as np, pandas as pd
d = pd.read_pickle("islemler3.pkl").sort_values("cikis").reset_index(drop=True)
R = (d.ret / d.risk_pct).values; mR = R.mean()
ay_id = pd.factorize(d.ay)[0]; AY = ay_id.max() + 1
ay_idx = [np.where(ay_id == a)[0] for a in range(AY)]
H = 24; YOL = 3000; rng = np.random.default_rng(99)
secim = rng.integers(0, AY, size=(YOL, H))
yollar = []
for i in range(YOL):
    idx = np.concatenate([ay_idx[a] for a in secim[i]])
    ay = np.concatenate([np.full(len(ay_idx[a]), m) for m, a in enumerate(secim[i])])
    yollar.append((idx, ay))
Hs = [20, 25, 30, 35, 40, 50]
print(f"islem/ay ~{len(d)/AY:.1f} | R std {R.std():.2f} | ort R {mR:.3f}")
for k in (0.09, 0.06, 0.12):
    print(f"\n=== CUSUM k={k}: S = max(0, S + {k} - R), alarm S > h ===")
    print(f"  {'dunya':<16s}" + "".join(f"  h={h:<2d} 12a/24a/med".rjust(24) for h in Hs))
    for ad, e in (("edge %100", 1.0), ("edge %75", 0.75), ("edge %50", 0.5), ("edge %0", 0.0), ("edge -0.10R", None)):
        Rw = R - (1 - e) * mR if e is not None else R - mR - 0.10
        ilk = np.full((YOL, len(Hs)), np.inf)
        for i, (idx, ay) in enumerate(yollar):
            x = Rw[idx]; S = np.empty(len(x)); s = 0.0
            for j in range(len(x)):
                s = s + k - x[j]
                if s < 0: s = 0.0
                S[j] = s
            for hi, h in enumerate(Hs):
                w = np.nonzero(S > h)[0]
                if len(w): ilk[i, hi] = ay[w[0]] + 1
        satir = f"  {ad:<16s}"
        for hi in range(len(Hs)):
            v = ilk[:, hi]; med = np.median(v[np.isfinite(v)]) if np.isfinite(v).any() else np.nan
            satir += f"{np.mean(v<=12)*100:6.0f}%/{np.mean(v<=24)*100:3.0f}%/{med:4.0f}".rjust(24)
        print(satir)
