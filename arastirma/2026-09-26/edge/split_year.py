"""TRAIN vs TEST mean net R, per-year mean R CIs, monthly table, worst-10 window anatomy. Research only."""
import json, sys
import numpy as np, pandas as pd
from scipy import stats as ss

rng = np.random.default_rng(11)
F = sys.argv[1] if len(sys.argv) > 1 else '/home/user/Bot2/ikiz_k25_cap25_islemler.csv'
d = pd.read_csv(F)
s = d.strategy_scores.apply(json.loads)
d['ie'] = s.apply(lambda x: x['intended_entry']); d['sl0'] = s.apply(lambda x: x['sl0'])
d['Rn'] = d.pnl_usdt / (d.quantity * (d.ie - d.sl0).abs())
d['sp'] = (d.ie - d.sl0).abs() / d.ie
d['xt'] = pd.to_datetime(d.exit_time); d['et'] = pd.to_datetime(d.entry_time)
o = d.sort_values(['xt', 'et']).reset_index(drop=True)
eqb = 10000 + o.pnl_usdt.cumsum().shift(fill_value=0)
o['r'] = o.pnl_usdt / eqb
o['day'] = o.et.dt.tz_localize(None).dt.floor('D')
o['mon'] = o.xt.dt.tz_localize(None).dt.to_period('M')
o['yr'] = o.xt.dt.year
o['test'] = o.xt >= pd.Timestamp('2025-01-01', tz='UTC')
R = o.Rn.values
print(f'{F.split("/")[-1]}  n={len(o)}  meanR={R.mean():.4f}  WR={(R>0).mean():.4f}')
w = R[R > 0]; l = R[R <= 0]
print(f'avg win {w.mean():.3f}R  avg loss {l.mean():.3f}R  breakeven WR={-l.mean()/(w.mean()-l.mean()):.3f}')


def cluster_boot_mean(sub, B=10000, key='day'):
    g = sub.groupby(key).Rn.agg(['sum', 'count'])
    S, C = g['sum'].values, g['count'].values
    idx = rng.integers(0, len(g), (B, len(g)))
    return S[idx].sum(1) / C[idx].sum(1)


# ---- TRAIN vs TEST ----
tr, te = o[~o.test], o[o.test]
diff = te.Rn.mean() - tr.Rn.mean()
lab = o.test.values.copy(); cnt = 0; NP = 20000
for _ in range(NP):
    rng.shuffle(lab)
    if R[lab].mean() - R[~lab].mean() <= diff: cnt += 1
p_iid = (cnt + 1) / (NP + 1)
# cluster (entry-day) permutation of labels: can't permute days across the split without mixing
# time; instead use day-cluster bootstrap CI for the difference, and a month-cluster Welch test.
bt = cluster_boot_mean(tr); be = cluster_boot_mean(te)
bd = be - bt
bm_t = cluster_boot_mean(tr, key='mon'); bm_e = cluster_boot_mean(te, key='mon'); bmd = bm_e - bm_t
it = rng.integers(0, len(tr), (10000, len(tr))); ie_ = rng.integers(0, len(te), (10000, len(te)))
bdi = te.Rn.values[ie_].mean(1) - tr.Rn.values[it].mean(1)
print(f'\nTRAIN n={len(tr)} meanR={tr.Rn.mean():+.4f} WR={(tr.Rn>0).mean():.3f} | TEST n={len(te)} meanR={te.Rn.mean():+.4f} WR={(te.Rn>0).mean():.3f}')
print(f'diff TEST-TRAIN={diff:+.4f}R  one-sided iid perm p(TEST<=obs)={p_iid:.4f}  two-sided~{min(1,2*p_iid):.3f}')
print(f'  95% CI iid boot [{np.percentile(bdi,2.5):+.3f},{np.percentile(bdi,97.5):+.3f}]  '
      f'day-cluster boot [{np.percentile(bd,2.5):+.3f},{np.percentile(bd,97.5):+.3f}]  '
      f'month-cluster boot [{np.percentile(bmd,2.5):+.3f},{np.percentile(bmd,97.5):+.3f}]  P(boot diff>=0) day={np.mean(bd>=0):.3f}')
print(f'  Welch t p={ss.ttest_ind(te.Rn, tr.Rn, equal_var=False).pvalue:.4f}  Mann-Whitney p={ss.mannwhitneyu(te.Rn, tr.Rn).pvalue:.4f}')
# power: what TEST effect would be detectable? SE of diff under day-cluster boot
print(f'  day-cluster SE(diff)={bd.std():.3f}R -> minimal detectable drop (80% power, a=.05 2s) ~{2.8*bd.std():.3f}R')
for k in ['donchian', 'squeeze', 'mean_rev']:
    a, b = tr[tr.kol == k].Rn, te[te.kol == k].Rn
    print(f'  {k:9s} TRAIN n={len(a)} {a.mean():+.3f}  TEST n={len(b)} {b.mean():+.3f}  Welch p={ss.ttest_ind(b, a, equal_var=False).pvalue:.3f}')

# ---- per year ----
print('\nper-year (exit year): n, meanR, t-95%CI, day-cluster boot 95%CI, WR, compounded equity return')
yrs = sorted(o.yr.unique()); groups = []
for y in yrs:
    sub = o[o.yr == y]; x = sub.Rn.values; groups.append(x)
    se = x.std(ddof=1) / np.sqrt(len(x)); tq = ss.t.ppf(.975, len(x) - 1)
    b = cluster_boot_mean(sub)
    print(f'  {y}: n={len(x):3d} meanR={x.mean():+.3f}  t[{x.mean()-tq*se:+.3f},{x.mean()+tq*se:+.3f}]  '
          f'boot[{np.percentile(b,2.5):+.3f},{np.percentile(b,97.5):+.3f}]  WR={(x>0).mean():.3f}  eq {np.prod(1+sub.r)-1:+.1%}')
print(f'  heterogeneity across years: ANOVA p={ss.f_oneway(*groups).pvalue:.3f}  Kruskal p={ss.kruskal(*groups).pvalue:.3f}')
# trend in yearly R: Spearman of R vs time (trade-level)
rho = ss.spearmanr(np.arange(len(R)), R)
print(f'  trade-level Spearman(R, time) rho={rho.statistic:+.4f} p={rho.pvalue:.3f}')

# ---- monthly table ----
m = o.groupby('mon').agg(n=('Rn', 'size'), meanR=('Rn', 'mean'), WR=('Rn', lambda v: (v > 0).mean()),
                         ret=('r', lambda v: np.prod(1 + v) - 1))
print('\nmonthly (exit month):')
print(m.round(3).to_string())
mr = m.ret.values
print(f'lag-1 autocorr of monthly returns: {np.corrcoef(mr[:-1], mr[1:])[0,1]:+.3f} (n={len(mr)})')
# overdispersion of monthly mean R vs trade-level iid: chi2 on sum of z^2
sd = R.std(ddof=1)
z = (m.meanR - R.mean()) / (sd / np.sqrt(m.n))
chi = (z ** 2).sum(); print(f'monthly meanR dispersion chi2={chi:.1f} df={len(m)-1} p={ss.chi2.sf(chi, len(m)-1):.3f}')

# ---- anatomy of worst 10-trade window ----
c = np.r_[0, np.cumsum(R)]; ws = c[10:] - c[:-10]; i = int(np.argmin(ws))
win = o.iloc[i:i + 10]
print(f'\nworst 10-trade R window: sumR={ws[i]:.2f}  {win.xt.iloc[0]} .. {win.xt.iloc[-1]}')
print(win[['symbol', 'side', 'kol', 'entry_time', 'exit_time', 'exit_reason', 'Rn', 'sp', 'r']].round(4).to_string(index=False))
lr = np.log1p(o.r.values); cl = np.r_[0, np.cumsum(lr)]; wl = cl[10:] - cl[:-10]; j = int(np.argmin(wl))
print(f'worst 10-trade equity window: {np.expm1(wl[j]):.1%} starting trade {j} ({o.xt.iloc[j]}); same window as R? {i==j}')
print(f'loss magnitude: mean loser R={l.mean():.3f}; losers with stop<1%: n={((R<=0)&(o.sp<0.01)).sum()} mean R={R[(R<=0)&(o.sp.values<0.01)].mean():.3f}')
