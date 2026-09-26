import pandas as pd, numpy as np
from scipy import stats
exec(open('market_edge.py').read().split('# ---------------- helpers ----------------')[0])
exec('def ols_cluster' + open('market_edge.py').read().split('def ols_cluster')[1].split('# ============ (1)')[0])
betas = {}
for c in COINS:
    others = [o for o in COINS if o != c]
    y = np.log1p(R1[c]); x = np.log1p(R1[others].mean(axis=1)); ok = y.notna() & x.notna()
    betas[c] = np.cov(y[ok], x[ok])[0, 1] / x[ok].var()
d['beta'] = d.coin.map(betas)
for h in [24, 48]:
    own = np.array([at('OWN_' + c, [e + pd.Timedelta(hours=h)])[0] - at('OWN_' + c, [e])[0] for c, e in zip(d.coin, d.et)])
    loo = np.array([at('LOO_' + c, [e + pd.Timedelta(hours=h)])[0] - at('LOO_' + c, [e])[0] for c, e in zip(d.coin, d.et)])
    d['f_own'] = d.sgn * own / d.stop_pct; d['f_mkt'] = d.sgn * d.beta * loo / d.stop_pct; d['f_idio'] = d.f_own - d.f_mkt
    for sp in ['TRAIN', 'TEST']:
        for kol in ['ALL', 'donchian', 'squeeze', 'mean_rev']:
            g = d[(d.split == sp) & ((d.kol == kol) | (kol == 'ALL'))]
            out = []
            for comp in ['f_own', 'f_mkt', 'f_idio']:
                b, se, r2, G, _ = ols_cluster(g[comp].values, np.zeros((len(g), 0)), g.ym.values)
                out.append(f'{comp} {fmt(b[0], se[0], G)}')
            print(f'h={h} {sp:5s} {kol:8s} n={len(g)} ' + ' | '.join(out))
# same-day direction agreement among concurrently OPEN trades
d = d.sort_values('et')
pairs = []
for i, r in d.iterrows():
    ov = d[(d.et < r.xt) & (d.xt > r.et) & (d.index != i)]
    for j, q in ov.iterrows():
        if j > i: pairs.append((r.sgn == q.sgn, r.Rn, q.Rn, r.kol, q.kol))
P = pd.DataFrame(pairs, columns=['same', 'r1', 'r2', 'k1', 'k2'])
print('overlapping pairs', len(P), 'same-direction share', P.same.mean().round(3))
for s_, g in P.groupby('same'):
    print(' same' if s_ else ' opposite', len(g), 'corr(R1,R2)=', np.round(stats.pearsonr(g.r1, g.r2), 4))
g = d.groupby(d.et.dt.floor('D')).sgn.agg(['size', 'sum'])
g = g[g['size'] >= 2]; print('multi-trade entry days', len(g), 'all same dir share', (g['sum'].abs() == g['size']).mean().round(3))
