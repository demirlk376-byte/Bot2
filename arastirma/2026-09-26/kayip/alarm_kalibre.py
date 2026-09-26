"""Durdurma kurallarinin kalibrasyonu: saglikli botu ne siklikla durdurur, olu edge'i ne kadar gec yakalar?
Ay-blok bootstrap (IKIZ taban islemleri, CAP 1.5). Dunyalar: edge %100 / %75 / %50 / %0 / negatif."""
import numpy as np, pandas as pd
d = pd.read_pickle("islemler3.pkl").sort_values("cikis").reset_index(drop=True)
R = (d.ret / d.risk_pct).values; risk = d.risk_pct.values; mR = R.mean()
ay_id = pd.factorize(d.ay)[0]; AY = ay_id.max() + 1
ay_idx = [np.where(ay_id == a)[0] for a in range(AY)]
H = 24; YOL = 3000; rng = np.random.default_rng(99)
# 1) orneklenmis yollar (ayni ay secimleri tum dunyalarda ortak -> adil kiyas)
secim = rng.integers(0, AY, size=(YOL, H))

def yol_verisi(i):
    idx = np.concatenate([ay_idx[a] for a in secim[i]])
    ay = np.concatenate([np.full(len(ay_idx[a]), m) for m, a in enumerate(secim[i])])
    return idx, ay

def kurallar(Rp, rk, ay, k_list, h_list):
    ret = Rp * rk
    eq = np.cumprod(1 + ret); tepe = np.maximum.accumulate(np.concatenate([[1.0], eq]))[1:]
    dd = 1 - eq / tepe
    ay_ret = np.array([np.prod(1 + ret[ay == m]) - 1 if (ay == m).any() else 0.0 for m in range(H)])
    neg = ay_ret < 0
    out = {}
    for L in (3, 4):
        a = np.inf
        for m in range(L - 1, H):
            if neg[m-L+1:m+1].all(): a = m + 1; break
        out[f"{L} ay ust uste negatif"] = a
    hit = np.where(dd > 0.60)[0]
    out["tepeden -%60"] = ay[hit[0]] + 1 if len(hit) else np.inf
    # live_verify literal: ay sonlarinda (n>=30) R ortalamasinin %95 alt siniri < 0, iki ay ust uste
    a = np.inf; onceki = False
    for m in range(H):
        x = Rp[ay <= m]
        if len(x) < 30: continue
        lb = x.mean() - 1.96 * x.std(ddof=1) / np.sqrt(len(x))
        if lb < 0 and onceki: a = m + 1; break
        onceki = lb < 0
    out["canli R alt siniri<0 (2 ay)"] = a
    # CUSUM: S = max(0, S + k - R); alarm S > h
    for k in k_list:
        for h in h_list:
            S = 0.0; a = np.inf
            for j, r in enumerate(Rp):
                S = max(0.0, S + k - r)
                if S > h: a = ay[j] + 1; break
            out[f"CUSUM k={k} h={h}"] = a
    return out, eq[-1]

dunyalar = {"edge %100 (IKIZ)": 1.0, "edge %75": 0.75, "edge %50": 0.5, "edge %0 (olu)": 0.0, "edge -0.10R": None}
K = [0.09]; Hs = [8, 10, 12, 15]
sonuc = {}
for ad, e in dunyalar.items():
    Rw = R - (1 - e) * mR if e is not None else R - mR - 0.10
    rows = []
    for i in range(YOL):
        idx, ay = yol_verisi(i)
        o, son = kurallar(Rw[idx], risk[idx], ay, K, Hs)
        rows.append(o)
    df = pd.DataFrame(rows)
    sonuc[ad] = df
    print(f"\n=== {ad}  (islem basi ort R {Rw.mean():+.3f}) ===")
    print(f"  {'kural':<28s} {'12 ayda alarm':>13s} {'24 ayda alarm':>13s} {'alarm ayi (medyan)':>19s}")
    for c in df.columns:
        v = df[c].values
        med = np.median(v[np.isfinite(v)]) if np.isfinite(v).any() else np.nan
        print(f"  {c:<28s} {np.mean(v <= 12)*100:12.1f}% {np.mean(v <= 24)*100:12.1f}% {med:18.1f}")
pd.to_pickle(sonuc, "alarm_sonuc.pkl")
