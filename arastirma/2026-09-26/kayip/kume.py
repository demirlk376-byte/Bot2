import numpy as np, pandas as pd
d = pd.read_pickle("islemler2.pkl")
rng = np.random.default_rng(11)
def kume_payi(df, pencere_h=6):
    """Zararli islemleri cikis zamanina gore grupla: aralarinda <= pencere olanlar ayni kume."""
    z = df[df.ret < 0].sort_values("cikis")
    t = z.cikis.values.astype("datetime64[s]").astype(np.int64) / 3600.0
    kume = np.zeros(len(z), int); k = 0
    for i in range(1, len(z)):
        if t[i] - t[i-1] > pencere_h: k += 1
        kume[i] = k
    boy = pd.Series(kume).map(pd.Series(kume).value_counts())
    top = z.ret.sum()
    return {b: z.ret.values[(boy.values >= b)].sum() / top for b in (2, 3, 4)}
g = kume_payi(d)
print("Zarar $'inin eszamanli kumelerden gelen payi (6 saat icinde kapanan zararlar):")
print("  gercek:", {f">={b}": f"%{v*100:.0f}" for b, v in g.items()})
# null: her coin'in islem zaman cizelgesini kendi icinde rastgele kaydir (coinler arasi eszamanlilik bozulur)
bas, son = d.giris.min(), d.cikis.max(); T = (son - bas)
sims = {2: [], 3: [], 4: []}
for _ in range(400):
    x = d.copy()
    for c in x.coin.unique():
        m = x.coin == c
        off = pd.Timedelta(hours=int(rng.integers(0, int(T.total_seconds() // 3600))))
        yeni = x.loc[m, "cikis"] + off
        yeni = yeni.where(yeni <= son, yeni - T)
        x.loc[m, "cikis"] = yeni
    s = kume_payi(x)
    for b in sims: sims[b].append(s[b])
print("  coinler arasi eszamanlilik bozulunca (null) medyan:", {f">={b}": f"%{np.median(v)*100:.0f}" for b, v in sims.items()},
      "| gercek >= null olasiligi:", {f">={b}": f"%{(np.array(v) >= g[b]).mean()*100:.0f}" for b, v in sims.items()})
# en buyuk tek-gun zararlari: kac pozisyon, ayni yon mu?
d["gun"] = d.cikis.dt.floor("D")
gun = d.groupby("gun").agg(ret=("ret", "sum"), n=("ret", "size"), zarar_n=("ret", lambda x: (x < 0).sum()),
                           long=("side", lambda x: (x == "long").sum()))
print("\nEn kotu 8 GUN (o gun kapanan islemler):")
print(gun.sort_values("ret").head(8).assign(ret=lambda x: (x.ret*100).round(1)).to_string())
print(f"\nGunluk zarar dagilimi: en kotu gun %{gun.ret.min()*100:.1f} | -%7'den kotu gun sayisi {(gun.ret < -0.07).sum()} / {len(gun)}")
