"""Reviewer: TRAIN/TEST, per-year, episodes + scan, change-point, streak anatomy. Research only."""
import sys
import numpy as np, pandas as pd
from scipy import stats as ss

P = '/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/edge/review/'
tag = sys.argv[1] if len(sys.argv) > 1 else 'ikiz_k25_cap25_islemler'
o = pd.read_pickle(P + 'o_' + tag + '.pkl')
rng = np.random.default_rng(4242)
R = o.Rme.values; n = len(R); lr = np.log1p(o.r.values)
o['day'] = o.et.dt.strftime('%Y-%m-%d'); o['mon'] = o.xt.dt.strftime('%Y-%m'); o['yr'] = o.xt.dt.year
test = (o.xt >= pd.Timestamp('2025-01-01', tz='UTC')).values


def clus_boot(x, g, B=20000):
    codes = pd.factorize(g)[0]
    S = np.bincount(codes, x); C = np.bincount(codes)
    idx = rng.integers(0, len(S), (B, len(S)))
    return S[idx].sum(1) / C[idx].sum(1)


tr, te = R[~test], R[test]
diff = te.mean() - tr.mean()
perm = np.array([(lambda l: R[l].mean() - R[~l].mean())(rng.permutation(test)) for _ in range(20000)])
p1 = (np.sum(perm <= diff) + 1) / 20001
bi = te[rng.integers(0, len(te), (20000, len(te)))].mean(1) - tr[rng.integers(0, len(tr), (20000, len(tr)))].mean(1)
bd = clus_boot(te, o.day.values[test]) - clus_boot(tr, o.day.values[~test])
bm = clus_boot(te, o.mon.values[test]) - clus_boot(tr, o.mon.values[~test])
print(f'TRAIN n={len(tr)} {tr.mean():+.4f} WR {np.mean(tr>0):.3f} | TEST n={len(te)} {te.mean():+.4f} WR {np.mean(te>0):.3f} | diff {diff:+.4f}')
print(f' perm one-sided p={p1:.3f}  CI iid {np.percentile(bi,[2.5,97.5]).round(3)} day {np.percentile(bd,[2.5,97.5]).round(3)} '
      f'month {np.percentile(bm,[2.5,97.5]).round(3)}  SE day {bd.std():.3f} -> MDE80 (2s .05) {2.80*bd.std():.3f}; month SE {bm.std():.3f} -> {2.8*bm.std():.3f}')
# TEST-alone CI, day cluster
bt = clus_boot(te, o.day.values[test]); print(' TEST alone day-cluster CI', np.percentile(bt, [2.5, 97.5]).round(3))
for k in ['donchian', 'squeeze', 'mean_rev']:
    m = (o.kol == k).values
    a, b = R[m & ~test], R[m & test]
    print(f'  {k:9s} TRAIN n={len(a)} {a.mean():+.3f} TEST n={len(b)} {b.mean():+.3f} Welch p={ss.ttest_ind(b,a,equal_var=False).pvalue:.3f}')

print('\nper-year (exit year) day-cluster boot CI:')
grp = []
for y, sub in o.groupby('yr'):
    x = sub.Rme.values; grp.append(x); b = clus_boot(x, sub.day.values)
    print(f'  {y}: n={len(x)} mean {x.mean():+.3f} CI [{np.percentile(b,2.5):+.3f},{np.percentile(b,97.5):+.3f}] WR {np.mean(x>0):.3f}')
print(f'  ANOVA p={ss.f_oneway(*grp).pvalue:.3f}  Kruskal p={ss.kruskal(*grp).pvalue:.3f}')
# linear trend of R on time (trade index), day-cluster robust via permutation of day blocks
t_idx = np.arange(n) / n
slope = np.polyfit(t_idx, R, 1)[0]
print(f'  OLS slope of R over full sample (per whole period) {slope:+.3f}')

# ---------- change-point test: max standardized drop in mean after breakpoint ----------
def cp_stat(x, minseg=30):
    c = np.cumsum(x); N = len(x); tot = c[-1]
    k = np.arange(minseg, N - minseg + 1)
    m1 = c[k - 1] / k; m2 = (tot - c[k - 1]) / (N - k)
    z = (m1 - m2) / np.sqrt(1 / k + 1 / (N - k))  # positive = later segment worse
    j = int(z.argmax()); return z[j] / x.std(ddof=1), int(k[j])


cz, ck = cp_stat(R)
day_code = pd.factorize(o.day.values, sort=True)[0]
blocks = [np.flatnonzero(day_code == q) for q in range(day_code.max() + 1)]
nullA = np.array([cp_stat(R[rng.permutation(n)])[0] for _ in range(5000)])
nullB = np.array([cp_stat(R[np.concatenate([blocks[q] for q in rng.permutation(len(blocks))])])[0] for _ in range(5000)])
print(f'\nChange-point (single mean drop, max over breaks, min seg 30): z={cz:.2f} at trade {ck} ({o.xt.iloc[ck].date()}), '
      f'before {R[:ck].mean():+.3f} (n={ck}) after {R[ck:].mean():+.3f} (n={n-ck}); p A={np.mean(nullA>=cz):.3f} B={np.mean(nullB>=cz):.3f}')
# Recent-tail specific: last k trades vs prior, for several k (post-hoc, reported as a family)
for k in [30, 60, 122, 150, 200, 300]:
    a, b = R[:-k], R[-k:]
    z = (a.mean() - b.mean()) / (R.std(ddof=1) * np.sqrt(1 / len(a) + 1 / len(b)))
    print(f'  last {k:3d} trades mean {b.mean():+.3f} vs prior {a.mean():+.3f}: z={z:.2f} one-sided p={ss.norm.sf(z):.3f} WR {np.mean(b>0):.3f}')

# ---------- episodes ----------
e = np.r_[0.0, np.cumsum(lr)]; pk = np.maximum.accumulate(e); ddv = e - pk
eps = []; i = 0
while i < n:
    if ddv[i + 1] < -1e-12:
        j = i + 1
        while j <= n and ddv[j] < -1e-12: j += 1
        t = i + int(np.argmin(ddv[i:j])); eps.append((1 - np.exp(ddv[t]), i, t, j)); i = j
    else:
        i += 1
eps.sort(reverse=True)


def scan_p(x_obs_sum, k, gen, NP=5000, stat='sum', xs=R):
    c_ = 0
    for _ in range(NP):
        y = xs[gen()] if stat == 'sum' else (xs[gen()] > 0).astype(float)
        cc = np.r_[0.0, np.cumsum(y)]
        if (cc[k:] - cc[:-k]).min() <= x_obs_sum + 1e-9: c_ += 1
    return (c_ + 1) / (NP + 1)


gA = lambda: rng.permutation(n)
gB = lambda: np.concatenate([blocks[q] for q in rng.permutation(len(blocks))])
print('\nTop drawdown episodes (trades after peak through trough):')
mu, sd, wr = R.mean(), R.std(ddof=1), np.mean(R > 0)
for dep, p, t, j in eps[:4]:
    x = R[p:t]; k = len(x); w = int((x > 0).sum())
    sub = o.iloc[p:t]
    zfix = (x.mean() - mu) / (sd / np.sqrt(k))
    print(f' DD {dep:.1%} peak {o.xt.iloc[p-1] if p else "start"} trough {o.xt.iloc[t-1]} rec {"trade "+str(j) if j<=n else "OPEN"} '
          f'n={k} meanR {x.mean():+.3f} WR {w/k:.3f} ({w}/{k}) sumR {x.sum():+.2f}')
    print(f'    fixed-window p(mean)={ss.norm.cdf(zfix):.4f} binom p(WR)={ss.binom.cdf(w,k,wr):.4f} | '
          f'scan sumR A={scan_p(x.sum(),k,gA):.3f} B={scan_p(x.sum(),k,gB):.3f} | scan wins A={scan_p(w,k,gA,stat="w"):.3f} B={scan_p(w,k,gB,stat="w"):.3f}'
          f' | exits {sub.exit_reason.value_counts().to_dict()} kol {sub.kol.value_counts().to_dict()}')

# multi-scale scan: worst standardized window over all lengths 10..200 (corrects for post-hoc length)
def ms(x, ks=range(10, 201)):
    c = np.r_[0.0, np.cumsum(x - mu)]
    best = np.inf
    for k in ks:
        best = min(best, (c[k:] - c[:-k]).min() / (sd * np.sqrt(k)))
    return best


obs_ms = ms(R)
nA = np.array([ms(R[gA()]) for _ in range(1500)]); nB = np.array([ms(R[gB()]) for _ in range(1500)])
print(f'\nMulti-scale scan (min over k=10..200 of standardized window deficit): obs {obs_ms:.2f}; '
      f'P(null <= obs) A={np.mean(nA<=obs_ms):.3f} B={np.mean(nB<=obs_ms):.3f}; null median A {np.median(nA):.2f} B {np.median(nB):.2f}')

# ---------- streak / worst-10 anatomy ----------
neg = R < 0
m = np.r_[False, neg, False].astype(int); dm = np.diff(m); s = np.flatnonzero(dm == 1); en = np.flatnonzero(dm == -1)
L = en - s; j = L.argmax()
st = o.iloc[s[j]:en[j]]
print(f'\nLongest losing streak {L[j]}: {st.xt.iloc[0]} .. {st.xt.iloc[-1]} exits {st.exit_reason.value_counts().to_dict()} '
      f'kol {st.kol.value_counts().to_dict()} sumR {st.Rme.sum():+.2f}')
c = np.r_[0.0, np.cumsum(R)]; w10 = c[10:] - c[:-10]; q = int(w10.argmin())
wv = o.iloc[q:q + 10]
print(f'Worst 10-trade window sumR {w10[q]:+.2f}: kol {wv.kol.value_counts().to_dict()} exits {wv.exit_reason.value_counts().to_dict()} '
      f'stop% range {wv.stop_pct.min()*100:.2f}-{wv.stop_pct.max()*100:.2f} meanR {wv.Rme.mean():+.3f}')
sl = o[o.exit_reason == 'sl_hit']
print(f'All SL hits: n={len(sl)} meanR {sl.Rme.mean():+.3f}; by kol', sl.groupby('kol').Rme.mean().round(3).to_dict())
# is SL-loss size (in R) serially clustered in time? corr of consecutive SL-loss R
x = sl.Rme.values
print(f' lag-1 corr of consecutive SL-hit R sizes: {np.corrcoef(x[:-1],x[1:])[0,1]:+.3f} (n={len(x)})')
