"""Are bad streaks / bad periods within expected variance?  Research only.
Null A: iid permutation of trades over the fixed exit-order slots (slot months fixed).
Null B: permutation of entry-calendar-day blocks (same-day trades kept together, internal order kept),
        concatenated sequence re-mapped onto the fixed exit-order slots (slot months fixed).
Null C: month-block bootstrap (40 months drawn with replacement, within-month order kept).
Null D: month-order permutation (without replacement) - tests only sequencing of months.
"""
import json, sys
import numpy as np, pandas as pd

rng = np.random.default_rng(20260926)
NP = 5000
F = sys.argv[1] if len(sys.argv) > 1 else '/home/user/Bot2/ikiz_k25_cap25_islemler.csv'
RET = sys.argv[2] if len(sys.argv) > 2 else 'realized'

d = pd.read_csv(F)
s = d.strategy_scores.apply(json.loads)
d['ie'] = s.apply(lambda x: x['intended_entry']); d['sl0'] = s.apply(lambda x: x['sl0'])
d['Rn'] = d.pnl_usdt / (d.quantity * (d.ie - d.sl0).abs())
d['f'] = np.minimum(0.035, 2.5 * (d.ie - d.sl0).abs() / d.ie)
d['xt'] = pd.to_datetime(d.exit_time); d['et'] = pd.to_datetime(d.entry_time)
o = d.sort_values(['xt', 'et']).reset_index(drop=True)
eqb = 10000 + o.pnl_usdt.cumsum().shift(fill_value=0)
o['r'] = o.pnl_usdt / eqb if RET == 'realized' else o.Rn * o.f
n = len(o)
R = o.Rn.values; r = o.r.values; lr = np.log1p(r)
mon = o.xt.dt.tz_localize(None).dt.to_period('M')
mcodes, muniq = pd.factorize(mon, sort=True)
mstarts = np.r_[0, np.flatnonzero(np.diff(mcodes)) + 1]  # contiguous since exit-sorted
day = o.et.dt.tz_localize(None).dt.floor('D')
dcodes, _ = pd.factorize(day, sort=True)
blocks = [np.flatnonzero(dcodes == k) for k in range(dcodes.max() + 1)]
mblocks = [np.flatnonzero(mcodes == k) for k in range(mcodes.max() + 1)]
print(f'file={F.split("/")[-1]} ret={RET} n={n} months={len(mblocks)} entry-day blocks={len(blocks)} '
      f'max block={max(len(b) for b in blocks)} meanR={R.mean():.4f} WR={(R>0).mean():.4f} '
      f'final eq x{np.exp(lr.sum()):.2f}')


def longest_run(mask):
    best = cur = 0
    for v in mask:
        cur = cur + 1 if v else 0
        if cur > best: best = cur
    return best


def min_window(x, k):
    c = np.r_[0, np.cumsum(x)]
    return (c[k:] - c[:-k]).min() if len(x) >= k else np.nan


def dd_stats(lrs):
    eq = np.r_[0, np.cumsum(lrs)]
    pk = np.maximum.accumulate(eq)
    dd = eq - pk
    t = int(np.argmin(dd)); mdd = 1 - np.exp(dd[t])
    p = int(np.flatnonzero(eq[:t + 1] == pk[t])[0])
    after = np.flatnonzero(eq[t:] >= pk[t])
    rec = (t + int(after[0]) - p) if len(after) else (len(eq) - 1 - p)  # censored at end
    uw = longest_run(dd < -1e-12)
    return mdd, rec, int(len(after) > 0), uw


def stats(Rs, lrs, starts):
    mret = np.add.reduceat(lrs, starts)
    neg = mret < 0
    out = dict(
        streak=longest_run(Rs < 0),
        w10=min_window(Rs, 10), w20=min_window(Rs, 20), w50=min_window(Rs, 50),
        negm=int(neg.sum()), negrun=longest_run(neg),
        roll50=min_window(Rs, 50) / 50,
        w10eq=np.expm1(min_window(lrs, 10)), w50eq=np.expm1(min_window(lrs, 50)),
        lag1=np.corrcoef(Rs[:-1], Rs[1:])[0, 1],
        runs=int(1 + np.sum((Rs[1:] > 0) != (Rs[:-1] > 0))),
    )
    mdd, rec, recd, uw = dd_stats(lrs)
    out.update(maxdd=mdd, rec=rec, uw=uw)
    return out


obs = stats(R, lr, mstarts)
mdd, rec, recd, uw = dd_stats(lr)
print('observed:', {k: (round(v, 4) if isinstance(v, float) else v) for k, v in obs.items()}, 'deepest DD recovered:', bool(recd))

KEYS = ['streak', 'w10', 'w20', 'w50', 'negm', 'negrun', 'roll50', 'maxdd', 'rec', 'uw', 'w10eq', 'w50eq', 'lag1', 'runs']
BAD_HIGH = {'streak', 'negm', 'negrun', 'maxdd', 'rec', 'uw', 'lag1'}  # lag1: + = clustering; runs: low = clustering  # larger = worse


def run_null(gen, label, fixed_slots=True):
    res = {k: np.empty(NP) for k in KEYS}
    for i in range(NP):
        idx, starts = gen()
        st = stats(R[idx], lr[idx], starts)
        for k in KEYS: res[k][i] = st[k]
    return res


def genA():
    return rng.permutation(n), mstarts


def genB():
    perm = rng.permutation(len(blocks))
    return np.concatenate([blocks[j] for j in perm]), mstarts


def genC():
    pick = rng.integers(0, len(mblocks), len(mblocks))
    parts = [mblocks[j] for j in pick]
    lens = np.array([len(p) for p in parts])
    return np.concatenate(parts), np.r_[0, np.cumsum(lens)[:-1]]


def genD():
    perm = rng.permutation(len(mblocks))
    parts = [mblocks[j] for j in perm]
    lens = np.array([len(p) for p in parts])
    return np.concatenate(parts), np.r_[0, np.cumsum(lens)[:-1]]


nulls = {}
for lab, g in [('A_iid', genA), ('B_dayblock', genB), ('C_monthboot', genC), ('D_monthperm', genD)]:
    nulls[lab] = run_null(g, lab)

rows = []
for k in KEYS:
    row = {'stat': k, 'obs': obs[k]}
    for lab, res in nulls.items():
        x = res[k]
        # p = P(null at least as bad as observed), one-sided, +1 correction
        bad = (x >= obs[k]) if k in BAD_HIGH else (x <= obs[k])
        good = (x <= obs[k]) if k in BAD_HIGH else (x >= obs[k])
        row[lab + '_med'] = np.median(x)
        row[lab + '_pbad'] = (bad.sum() + 1) / (NP + 1)
        row[lab + '_pgood'] = (good.sum() + 1) / (NP + 1)
    # B-consistent observed: same-entry-day trades contiguous in chronological day order
    idxB = np.concatenate(blocks)
    row['obs_dayorder'] = stats(R[idxB], lr[idxB], mstarts)[k]
    rows.append(row)
tab = pd.DataFrame(rows)
pd.set_option('display.width', 250); pd.set_option('display.max_columns', 30)
print(tab.drop(columns=[c for c in tab.columns if c.startswith(('C_','D_'))]).round(4).to_string(index=False))
print(tab[['stat','obs']+[c for c in tab.columns if c.startswith(('C_','D_'))]].round(4).to_string(index=False))
for lab in ['A_iid','B_dayblock']:
    nr = nulls[lab]['negrun']; nm = nulls[lab]['negm']; st = nulls[lab]['streak']
    print(lab, 'negrun dist', {int(v): round(float(np.mean(nr==v)),3) for v in np.unique(nr)},
          '| negm 5-95%', np.percentile(nm,[5,50,95]), '| streak 5-50-95%', np.percentile(st,[5,50,95]),
          '| maxdd 5-50-95%', np.percentile(nulls[lab]['maxdd'],[5,50,95]).round(3))
np.savez('/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/edge/nulls_' + RET + '_' + F.split('/')[-1].replace('.csv', '') + '.npz',
         **{f'{lab}_{k}': v for lab, res in nulls.items() for k, v in res.items()})

# ---- scan statistic for the drawdown episodes -------------------------------------------------
eq = np.r_[0, np.cumsum(lr)]; pk = np.maximum.accumulate(eq); dd = eq - pk
# find underwater episodes: peak index -> trough index -> recovery
eps = []; i = 0
while i < n:
    if dd[i + 1] < 0:
        p = i  # eq index of peak
        j = i + 1
        while j <= n and dd[j] < 0: j += 1
        seg = dd[p:j]; t = p + int(np.argmin(seg))
        eps.append((1 - np.exp(dd[t]), p, t, j))
        i = j
    else:
        i += 1
eps.sort(reverse=True)
print('\nTop drawdown episodes (trades peak+1..trough):')
fullmR, fullWR = R.mean(), (R > 0).mean()
from scipy import stats as ss
for depth, p, t, j in eps[:4]:
    seg = slice(p, t)  # trades p..t-1 are the trades between equity index p and t
    Rs = R[seg]; k = len(Rs); w = int((Rs > 0).sum())
    t0, t1 = o.xt.iloc[p].date(), o.xt.iloc[t - 1].date()
    binom_p = ss.binom.cdf(w, k, fullWR)
    # scan: P(some window of length k in n trades has sum R <= observed, and wins <= observed)
    sc = {}
    for lab in ['A_iid', 'B_dayblock']:
        g = genA if lab == 'A_iid' else genB
        cntS = cntW = 0
        rr = np.random.default_rng(7)
        for _ in range(2000):
            idx, _s = g()
            x = R[idx]
            if min_window(x, k) <= Rs.sum() + 1e-12: cntS += 1
            if min_window((x > 0).astype(float), k) <= w: cntW += 1
        sc[lab] = ((cntS + 1) / 2001, (cntW + 1) / 2001)
    print(f'  DD {depth*100:.1f}%  {t0}..{t1}  n={k}  meanR={Rs.mean():+.3f} (full {fullmR:+.3f})  '
          f'WR={w/k:.3f} (full {fullWR:.3f})  sumR={Rs.sum():+.1f}  naive binom p(WR)={binom_p:.4f}  '
          f'scan p sumR A={sc["A_iid"][0]:.3f} B={sc["B_dayblock"][0]:.3f} | scan p wins A={sc["A_iid"][1]:.3f} B={sc["B_dayblock"][1]:.3f}  '
          f'recovered={"yes" if j <= n else "no (open)"}')
