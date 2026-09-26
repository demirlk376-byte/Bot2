import numpy as np, pandas as pd
from scipy import stats
d = pd.read_pickle("islemler2.pkl")
rng = np.random.default_rng(7)
win = (d.R > 0).astype(int).values
p = win.mean()
# 1) Ay bazinda WR asiri-dagilim (binom'a gore)
ay = d.groupby("ay").agg(n=("R", "size"), k=("R", lambda x: (x > 0).sum()))
chi = (((ay.k - ay.n*p)**2) / (ay.n*p*(1-p))).sum(); df = len(ay) - 1
print(f"1) aylik WR asiri-dagilim: chi2={chi:.1f} df={df} p={1-stats.chi2.cdf(chi, df):.3f}  (p kucukse: kotu donemler sanstan FAZLA kumeleniyor)")
# 2) Kazan/kaybet sirasinda kosu (runs) testi
n1 = win.sum(); n0 = len(win) - n1; runs = 1 + (np.diff(win) != 0).sum()
mu = 2*n1*n0/(n1+n0) + 1; var = (mu-1)*(mu-2)/(n1+n0-1)
print(f"2) runs testi: gozlenen {runs} kosu, beklenen {mu:.0f}, z={(runs-mu)/np.sqrt(var):+.2f}  (negatif z = kayiplar kumeleniyor)")
# 3) sonuc otokorelasyonu: onceki k islemin sonucu sonrakini tahmin ediyor mu?
for lag in (1, 2, 3, 5, 10):
    r = np.corrcoef(d.R.values[:-lag], d.R.values[lag:])[0, 1]
    print(f"3) R otokorelasyon lag {lag}: {r:+.3f}  (%95 esik ~ +/-{1.96/np.sqrt(len(d)):.3f})")
# 4) son 10 islemin WR'i -> sonraki 10 islemin ortR'si (DD-durdurma mantiginin testi)
w = pd.Series(win); R = d.R
son10 = w.rolling(10).mean().shift(1); sonraki10 = R[::-1].rolling(10).mean()[::-1]
t = pd.DataFrame({"son10": son10, "sonraki10": sonraki10}).dropna()
t["b"] = pd.cut(t.son10, [-0.01, 0.2, 0.3, 0.4, 0.5, 0.6, 1.0])
print("4) son 10 islemin WR'i -> SONRAKI 10 islemin ort R'si:")
print(t.groupby("b", observed=True).sonraki10.agg(["mean", "size"]).round(3).to_string())
# 5) iid karistirma: gercek maxDD sansla uyumlu mu? (ayni islemler, rastgele sira)
def maxdd(rets):
    eq = np.cumprod(1 + rets); return (1 - eq/np.maximum.accumulate(eq)).max()
gercek = maxdd(d.ret.values)
sim = np.array([maxdd(rng.permutation(d.ret.values)) for _ in range(5000)])
print(f"5) gercek maxDD %{gercek*100:.1f} | ayni islemler rastgele sirada: medyan %{np.median(sim)*100:.1f}, "
      f"%5-%95 [%{np.percentile(sim,5)*100:.1f}, %{np.percentile(sim,95)*100:.1f}], gercekten kotu olma olasiligi %{(sim>=gercek).mean()*100:.0f}")
for yari in ("TR", "TE"):
    x = d[d.yari == yari].ret.values; g = maxdd(x)
    s2 = np.array([maxdd(rng.permutation(x)) for _ in range(3000)])
    print(f"   {yari}: gercek %{g*100:.1f} | rastgele sira medyan %{np.median(s2)*100:.1f}, %95 %{np.percentile(s2,95)*100:.1f}, P(>=gercek) %{(s2>=g).mean()*100:.0f}")
