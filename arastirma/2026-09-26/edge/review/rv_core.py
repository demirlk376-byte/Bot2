"""Independent re-derivation (reviewer). Research only; nothing written to repo.
Loads twin trades, builds R, equity returns, and prints descriptive + null-model statistics."""
import json, sys
import numpy as np, pandas as pd
from scipy import stats as ss

F = sys.argv[1] if len(sys.argv) > 1 else '/home/user/Bot2/ikiz_k25_cap25_islemler.csv'
NP = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
rng = np.random.default_rng(987654)

d = pd.read_csv(F)
js = d.strategy_scores.map(json.loads)
d['ie'] = js.map(lambda z: z['intended_entry']).astype(float)
d['sl0'] = js.map(lambda z: z['sl0']).astype(float)
d['strat'] = js.map(lambda z: z['strategy'])
d['risk_px'] = (d.ie - d.sl0).abs()
d['Rme'] = d.pnl_usdt / (d.quantity * d.risk_px)
d['stop_pct'] = d.risk_px / d.ie
d['et'] = pd.to_datetime(d.entry_time, utc=True)
d['xt'] = pd.to_datetime(d.exit_time, utc=True)
print('file', F.split('/')[-1], 'n', len(d), 'entry', d.et.min(), 'exit max', d.xt.max())
print('max |Rme - R column|:', float((d.Rme - d.R).abs().max()), ' strat==kol:', bool((d.strat == d.kol).all()))
# exit-order (stable tie-break by entry then original row)
d['row'] = np.arange(len(d))
o = d.sort_values(['xt', 'et', 'row'], kind='mergesort').reset_index(drop=True)
eq_before = 10000 + o.pnl_usdt.cumsum().shift(fill_value=0.0)
o['r'] = o.pnl_usdt / eq_before
# sizing check: equity at ENTRY = 10000 + pnl of trades exited strictly before entry time
cum = np.r_[0, o.pnl_usdt.cumsum().values]
pos = np.searchsorted(o.xt.values, o.et.values, side='left')
o['eq_entry'] = 10000 + cum[pos]
o['risk_frac'] = o.quantity * o.risk_px / o.eq_entry
o['notional_x'] = o.quantity * o.ie / o.eq_entry
print('sizing: risk_frac pctl 5/50/95/max', np.percentile(o.risk_frac, [5, 50, 95, 100]).round(4),
      ' notional/eq max', round(o.notional_x.max(), 3),
      ' share risk<3.4%', round((o.risk_frac < 0.034).mean(), 3))
o['f'] = np.minimum(0.035, 2.5 * o.stop_pct)
print('corr(r, Rme*f)=', round(np.corrcoef(o.r, o.Rme * o.f)[0, 1], 4),
      ' prod(1+r)=', round(np.prod(1 + o.r), 2), ' final eq', round(10000 + o.pnl_usdt.sum(), 0),
      ' prod(1+R*f)=', round(np.prod(1 + o.Rme * o.f), 1))
R = o.Rme.values; n = len(R); lr = np.log1p(o.r.values)
win = R > 0
print(f'meanR {R.mean():+.4f} sd {R.std(ddof=1):.3f} WR {win.mean():.4f} ({win.sum()}/{n}) avgW {R[win].mean():+.3f} '
      f'avgL {R[~win].mean():+.3f} BE-WR {-R[~win].mean()/(R[win].mean()-R[~win].mean()):.4f}')
print('exit reasons', o.exit_reason.value_counts().to_dict())
o.to_pickle('/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/edge/review/o_' + F.split('/')[-1].replace('.csv', '') + '.pkl')


def longest_true(m):
    m = np.r_[False, m, False].astype(np.int8)
    dm = np.diff(m); s = np.flatnonzero(dm == 1); e = np.flatnonzero(dm == -1)
    return int((e - s).max()) if len(s) else 0


def minwin(x, k):
    c = np.r_[0.0, np.cumsum(x)]
    return float((c[k:] - c[:-k]).min())


def dd(lrs):
    e = np.r_[0.0, np.cumsum(lrs)]
    pk = np.maximum.accumulate(e)
    ddv = e - pk
    t = int(ddv.argmin())
    under = ddv < -1e-12
    return 1 - np.exp(ddv[t]), longest_true(under)


mon = o.xt.dt.strftime('%Y-%m').values
mcode = pd.factorize(mon)[0]
mst = np.r_[0, np.flatnonzero(np.diff(mcode)) + 1]


def stat(Rs, lrs, starts=mst):
    mret = np.add.reduceat(lrs, starts)
    mdd, uw = dd(lrs)
    return dict(streak=longest_true(Rs < 0), w10=minwin(Rs, 10), w20=minwin(Rs, 20), w50=minwin(Rs, 50),
                maxdd=mdd, uw=uw, negm=int((mret < 0).sum()), negrun=longest_true(mret < 0),
                w10eq=np.expm1(minwin(lrs, 10)), w50eq=np.expm1(minwin(lrs, 50)),
                lag1=float(np.corrcoef(Rs[:-1], Rs[1:])[0, 1]), runs=int(1 + ((Rs[1:] > 0) != (Rs[:-1] > 0)).sum()))


obs = stat(R, lr)
print('OBS', {k: round(v, 4) for k, v in obs.items()})
HIGHBAD = {'streak', 'maxdd', 'uw', 'negm', 'negrun', 'lag1'}

# entry-day blocks (UTC calendar day of entry)
eday = o.et.dt.strftime('%Y-%m-%d').values
dcode = pd.factorize(eday, sort=True)[0]
blocks = [np.flatnonzero(dcode == k) for k in range(dcode.max() + 1)]
# overlap clusters: connected components of overlapping holding intervals (entry order)
eo = np.argsort(o.et.values, kind='mergesort')
cl = np.empty(n, int); cid = 0; mx = o.xt.values[eo[0]]; cl[eo[0]] = 0
for i in eo[1:]:
    if o.et.values[i] >= mx:
        cid += 1; mx = o.xt.values[i]
    else:
        mx = max(mx, o.xt.values[i])
    cl[i] = cid
oblocks = [np.flatnonzero(cl == k) for k in range(cid + 1)]
print('entry-day blocks', len(blocks), 'max', max(map(len, blocks)), '| overlap clusters', len(oblocks),
      'max', max(map(len, oblocks)), 'median', np.median(list(map(len, oblocks))))

gens = {
    'A_perm': lambda: rng.permutation(n),
    'A2_boot': lambda: rng.integers(0, n, n),  # iid bootstrap: mean edge also random
    'B_day': lambda: np.concatenate([blocks[j] for j in rng.permutation(len(blocks))]),
}


def sbb(L):  # stationary block bootstrap on exit order, mean block length L (circular)
    def g():
        idx = np.empty(n, int); i = 0
        while i < n:
            s = rng.integers(n); ln = rng.geometric(1 / L)
            take = (s + np.arange(ln)) % n
            idx[i:i + ln] = take[:n - i]; i += ln
        return idx
    return g


gens['S_sbb20'] = sbb(20)
res = {}
for lab, g in gens.items():
    rows = []
    for _ in range(NP):
        idx = g()
        rows.append(stat(R[idx], lr[idx]))
    res[lab] = pd.DataFrame(rows)
# observed in day-block order (for B consistency)
idxB = np.concatenate(blocks)
obsB = stat(R[idxB], lr[idxB])
out = []
for k in obs:
    row = dict(stat=k, obs=obs[k], obs_dayord=obsB[k])
    for lab, df in res.items():
        x = df[k].values
        ob = obsB[k] if lab == 'B_day' else obs[k]
        bad = (x >= ob) if k in HIGHBAD else (x <= ob)
        row[lab + '_med'] = np.median(x)
        row[lab + '_p05_95'] = f'[{np.percentile(x,5):.3g},{np.percentile(x,95):.3g}]'
        row[lab + '_pbad'] = (bad.sum() + 1) / (NP + 1)
        # use B's own comparison with exit-order obs too
        if lab == 'B_day':
            row['B_pbad_exitobs'] = (((x >= obs[k]) if k in HIGHBAD else (x <= obs[k])).sum() + 1) / (NP + 1)
    out.append(row)
pd.set_option('display.width', 300); pd.set_option('display.max_columns', 40)
T = pd.DataFrame(out)
print(T.round(4).to_string(index=False))
print('Note A2_boot/S_sbb20 also randomize the mean; pbad = P(null at least as bad as observed), +1 corrected.')
for lab in res:
    print(lab, 'maxdd 5/50/95', np.percentile(res[lab].maxdd, [5, 50, 95]).round(3),
          'streak 5/50/95', np.percentile(res[lab].streak, [5, 50, 95]))
