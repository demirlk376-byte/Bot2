"""Reviewer: is the 'smoother than chance' path explained by cross-sleeve offsetting or cross-day anti-persistence?
Research only."""
import sys
import numpy as np, pandas as pd
P = '/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/edge/review/'
tag = sys.argv[1] if len(sys.argv) > 1 else 'ikiz_k25_cap25_islemler'
o = pd.read_pickle(P + 'o_' + tag + '.pkl')
rng = np.random.default_rng(55)
R = o.Rme.values; lr = np.log1p(o.r.values); n = len(R)


def maxdd(l):
    e = np.r_[0, np.cumsum(l)]; return 1 - np.exp((e - np.maximum.accumulate(e)).min())


def w50(x):
    c = np.r_[0, np.cumsum(x)]; return (c[50:] - c[:-50]).min()


obs = (maxdd(lr), w50(R))
kol = o.kol.values
slots = {k: np.flatnonzero(kol == k) for k in np.unique(kol)}
# N1: within-sleeve permutation (each sleeve's outcomes shuffled among its own slots)
# N2: independent circular shift of each sleeve's sequence (keeps within-sleeve serial structure, breaks cross-sleeve timing)
res = {'within_sleeve_perm': [], 'sleeve_circ_shift': []}
for _ in range(4000):
    idx = np.arange(n)
    for k, s in slots.items(): idx[s] = rng.permutation(s)
    res['within_sleeve_perm'].append((maxdd(lr[idx]), w50(R[idx])))
    idx = np.arange(n)
    for k, s in slots.items(): idx[s] = np.roll(s, rng.integers(1, len(s)))
    res['sleeve_circ_shift'].append((maxdd(lr[idx]), w50(R[idx])))
print(tag, 'obs maxDD %.3f w50 %.2f' % obs)
for k, v in res.items():
    v = np.array(v)
    print(f'  {k:20s} maxDD med {np.median(v[:,0]):.3f} P(null<=obs, i.e. milder)={np.mean(v[:,0]<=obs[0]):.3f} | '
          f'w50 med {np.median(v[:,1]):.2f} P(null>=obs, milder)={np.mean(v[:,1]>=obs[1]):.3f}')
# weekly sleeve R sums: cross-sleeve correlation (exit week)
wk = o.xt.dt.strftime('%G-%V')
W = o.pivot_table(index=wk, columns='kol', values='Rme', aggfunc='sum').fillna(0)
print('  weekly sleeve R-sum correlations (n weeks=%d):' % len(W)); print(W.corr().round(3).to_string())
M = o.pivot_table(index=o.xt.dt.strftime('%Y-%m'), columns='kol', values='Rme', aggfunc='sum').fillna(0)
print('  monthly sleeve R-sum correlations (n=%d):' % len(M)); print(M.corr().round(3).to_string())
# autocorrelation of weekly total R (anti-persistence?)
tw = W.sum(1).values
for lag in [1, 2, 4]:
    print(f'  weekly total R autocorr lag {lag}: {np.corrcoef(tw[:-lag], tw[lag:])[0,1]:+.3f} (n={len(tw)})')
# lag-1 corr among consecutive exit-order pairs with different entry days
day = o.et.dt.strftime('%Y-%m-%d').values
m = day[1:] != day[:-1]
print(f'  lag-1 R corr, consecutive pairs from different entry days: {np.corrcoef(R[:-1][m], R[1:][m])[0,1]:+.3f} (n={m.sum()}); '
      f'same entry day: {np.corrcoef(R[:-1][~m], R[1:][~m])[0,1]:+.3f} (n={(~m).sum()})')
# monthly dispersion chi2 check
from scipy import stats as ss
g = o.groupby(o.xt.dt.strftime('%Y-%m')).Rme.agg(['mean', 'count'])
chi = (((g['mean'] - R.mean()) ** 2) * g['count'] / R.var(ddof=1)).sum()
print(f'  monthly meanR dispersion chi2={chi:.1f} df={len(g)-1} p={ss.chi2.sf(chi, len(g)-1):.3f}')
mret = o.groupby(o.xt.dt.strftime('%Y-%m')).r.apply(lambda v: np.prod(1 + v) - 1).values
print(f'  monthly equity-return lag-1 autocorr {np.corrcoef(mret[:-1], mret[1:])[0,1]:+.3f} (n={len(mret)}), neg months {np.sum(mret<0)}')
