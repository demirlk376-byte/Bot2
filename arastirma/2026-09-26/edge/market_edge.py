"""Edge vs market: tailwind regression, long/short x up/down months, trendiness regimes.
Research only. Reads repo data, writes nothing to repo."""
import json, sys
import numpy as np, pandas as pd
from scipy import stats

ROOT = '/home/user/Bot2'
OUT = '/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/edge'
COINS = ['SOL', 'ETH', 'ADA', 'NEAR', 'BCH', 'ICP', 'BNB', 'XRP', 'DOGE', 'XLM', 'LTC']
SPLIT = pd.Timestamp('2025-01-01', tz='UTC')
rng = np.random.default_rng(12345)

# ---------------- market data ----------------
closes = {}
for c in COINS + ['BTC']:
    x = pd.read_csv(f'{ROOT}/data/{c}_fut_1h.csv')
    x['ts'] = pd.to_datetime(x.ts)
    closes[c] = x.set_index('ts').close
C = pd.DataFrame(closes).sort_index()
C = C.asfreq('1h')  # expose gaps
C = C.ffill(limit=3)
R1 = C.pct_change()                      # simple hourly returns, bar ts -> return over bar ending ts+1h
idx_r = R1[COINS].mean(axis=1, skipna=True)   # equal-weight, hourly rebalanced
lvl = pd.DataFrame(index=C.index)
lvl['IDX'] = np.log1p(idx_r.fillna(0)).cumsum()
lvl['BTC'] = np.log(C['BTC']).ffill()
for c in COINS:  # leave-one-out index (excludes traded coin)
    others = [o for o in COINS if o != c]
    lvl['LOO_' + c] = np.log1p(R1[others].mean(axis=1, skipna=True).fillna(0)).cumsum()
    lvl['OWN_' + c] = np.log(C[c]).ffill()
# price level at wall-clock time T = close of bar with ts = T-1h  -> shift index by +1h
lvlT = lvl.copy(); lvlT.index = lvlT.index + pd.Timedelta('1h')


def at(col, t):
    t = pd.DatetimeIndex(t)
    pos = lvlT.index.get_indexer(t, method='ffill')
    return lvlT[col].values[pos]

# ---------------- trades ----------------
d = pd.read_csv(f'{ROOT}/ikiz_k25_cap25_islemler.csv')
s = d.strategy_scores.apply(json.loads)
d['ie'] = s.apply(lambda z: z['intended_entry']); d['sl0'] = s.apply(lambda z: z['sl0'])
d['coin'] = d.symbol.str.split('/').str[0]
d['et'] = pd.to_datetime(d.entry_time); d['xt'] = pd.to_datetime(d.exit_time)
d['sgn'] = np.where(d.side == 'long', 1, -1)
d['Rn'] = d.pnl_usdt / (d.quantity * (d.ie - d.sl0).abs())
d['stop_pct'] = (d.ie - d.sl0).abs() / d.ie
d['hours'] = (d.xt - d.et).dt.total_seconds() / 3600
# equity reconstruction by exit order
d = d.sort_values(['xt', 'et']).reset_index(drop=True)
d['eq_before'] = 10000 + d.pnl_usdt.cumsum().shift(fill_value=0)
d['r_eq'] = d.pnl_usdt / d.eq_before
d['risk_frac'] = np.minimum(0.035, 2.5 * d.stop_pct)
d['split'] = np.where(d.xt < SPLIT, 'TRAIN', 'TEST')

d['m_idx'] = at('IDX', d.xt) - at('IDX', d.et)
d['m_btc'] = at('BTC', d.xt) - at('BTC', d.et)
d['m_loo'] = [at('LOO_' + c, [x])[0] - at('LOO_' + c, [e])[0] for c, x, e in zip(d.coin, d.xt, d.et)]
d['m_own'] = [at('OWN_' + c, [x])[0] - at('OWN_' + c, [e])[0] for c, x, e in zip(d.coin, d.xt, d.et)]
for k in ['idx', 'btc', 'loo', 'own']:
    d['tw_' + k] = d.sgn * d['m_' + k]          # signed market move (log), + = tailwind
    d['twR_' + k] = d['tw_' + k] / d.stop_pct   # tailwind in units of the trade's stop distance
d['ym'] = d.et.dt.tz_convert(None).dt.to_period('M')
print('trades', len(d), 'NaN tailwind', d.tw_idx.isna().sum(), d.tw_loo.isna().sum())


# ---------------- helpers ----------------
def ols_cluster(y, X, groups):
    """OLS with intercept; returns coef, cluster-robust SE (CR1), R2."""
    X = np.column_stack([np.ones(len(y)), X]); y = np.asarray(y, float)
    XtXi = np.linalg.inv(X.T @ X); b = XtXi @ X.T @ y; e = y - X @ b
    g = pd.factorize(groups)[0]; G = g.max() + 1
    meat = np.zeros((X.shape[1],) * 2)
    for j in range(G):
        sj = X[g == j].T @ e[g == j]; meat += np.outer(sj, sj)
    n, k = X.shape
    V = XtXi @ meat @ XtXi * G / (G - 1) * (n - 1) / (n - k)
    se = np.sqrt(np.diag(V))
    r2 = 1 - (e @ e) / ((y - y.mean()) @ (y - y.mean()))
    return b, se, r2, G, e


def fmt(b, se, G):
    tcrit = stats.t.ppf(0.975, G - 1)
    return f'{b:+.4f} [{b - tcrit * se:+.4f},{b + tcrit * se:+.4f}] p={2 * stats.t.sf(abs(b / se), G - 1):.3g}'


def month_boot_mean(df, col, B=5000):
    """block bootstrap by month (clusters) for a mean"""
    gs = [g[col].values for _, g in df.groupby('ym')]
    m = np.array([np.concatenate([gs[i] for i in rng.integers(0, len(gs), len(gs))]).mean() for _ in range(B)])
    return np.percentile(m, [2.5, 97.5])


# ============ (1) tailwind regression ============
print('\n==== (1) per-trade net R on signed market move over trade life ====')
res1 = {}
for sub_name, sub in [('ALL', d), ('TRAIN', d[d.split == 'TRAIN']), ('TEST', d[d.split == 'TEST'])]:
    for k in ['idx', 'loo', 'btc']:
        for xv in ['tw_', 'twR_']:
            x = sub[xv + k].values * (100 if xv == 'tw_' else 1)
            b, se, r2, G, e = ols_cluster(sub.Rn.values, x, sub.ym.values)
            totR = sub.Rn.sum(); n = len(sub)
            mkt_part = b[1] * x.sum(); alpha_part = b[0] * n
            print(f'{sub_name:5s} {xv}{k:4s} n={n} G={G} alpha {fmt(b[0], se[0], G)}  slope {fmt(b[1], se[1], G)} '
                  f'R2={r2:.3f} | totR={totR:.1f} = alpha*n {alpha_part:.1f} + slope*sum(x) {mkt_part:.1f} '
                  f'({100 * mkt_part / totR:.0f}% mkt) mean x={x.mean():+.3f}')
            res1[(sub_name, xv + k)] = dict(n=n, a=b[0], a_se=se[0], b=b[1], b_se=se[1], r2=r2, totR=totR, mkt=mkt_part, G=G)

# Own-coin move as a sanity reference (R is essentially determined by own move)
b, se, r2, G, e = ols_cluster(d.Rn.values, d.twR_own.values, d.ym.values)
print(f'reference: R on own-coin signed move/stop: slope {b[1]:.3f} R2={r2:.3f}')

# ---- beta decomposition of each trade's own signed move: own = beta_c * LOO-market + idio ----
print('\n-- own-coin signed move split into market (beta*LOO index) and idiosyncratic parts --')
betas = {}
for c in COINS:
    others = [o for o in COINS if o != c]
    y = np.log1p(R1[c]); x = np.log1p(R1[others].mean(axis=1))
    ok = y.notna() & x.notna()
    betas[c] = np.cov(y[ok], x[ok])[0, 1] / x[ok].var()
print('hourly beta to LOO index:', {k: round(v, 2) for k, v in betas.items()})
d['beta'] = d.coin.map(betas)
d['own_mkt'] = d.beta * d.tw_loo / d.stop_pct
d['own_idio'] = d.twR_own - d.own_mkt
for sp in ['ALL', 'TRAIN', 'TEST']:
    g = d if sp == 'ALL' else d[d.split == sp]
    tot = g.twR_own.sum()
    print(f'{sp}: sum own signed move (stop units) {tot:.1f} = market {g.own_mkt.sum():.1f} ({100 * g.own_mkt.sum() / tot:.0f}%) + idio {g.own_idio.sum():.1f} '
          f'({100 * g.own_idio.sum() / tot:.0f}%) ; mean per trade mkt {g.own_mkt.mean():+.3f} idio {g.own_idio.mean():+.3f}')
    for comp in ['own_mkt', 'own_idio']:
        ci = month_boot_mean(g, comp, 3000)
        print(f'     {comp} mean {g[comp].mean():+.3f} CI95 month-boot [{ci[0]:+.3f},{ci[1]:+.3f}]')
# regress R on both parts
b, se, r2, G, e = ols_cluster(d.Rn.values, np.column_stack([d.own_mkt, d.own_idio]), d.ym.values)
print(f'R ~ mkt part + idio part: const {fmt(b[0], se[0], G)} mkt {fmt(b[1], se[1], G)} idio {fmt(b[2], se[2], G)} R2={r2:.3f}')
print(f'  => R attributable: mkt {b[1] * d.own_mkt.sum():.1f}, idio {b[2] * d.own_idio.sum():.1f}, const {b[0] * len(d):.1f}, total {d.Rn.sum():.1f}')

# ---- exogenous fixed-horizon timing test: signed LOO/BTC move from entry to entry+h (not ending at exit) ----
print('\n-- market timing: signed market move over FIXED horizons around entry (month-clustered t) --')
for k in ['IDX', 'BTC']:
    for h in [-24, -4, 4, 12, 24, 48, 120]:
        if k == 'IDX':
            if h < 0:
                mv = np.array([at('LOO_' + c, [e])[0] - at('LOO_' + c, [e + pd.Timedelta(hours=h)])[0] for c, e in zip(d.coin, d.et)])
            else:
                mv = np.array([at('LOO_' + c, [e + pd.Timedelta(hours=h)])[0] - at('LOO_' + c, [e])[0] for c, e in zip(d.coin, d.et)])
        else:
            a0 = at('BTC', d.et); a1 = at('BTC', d.et + pd.Timedelta(hours=h))
            mv = (a0 - a1) if h < 0 else (a1 - a0)
        sm = d.sgn.values * mv * 100
        ok = ~np.isnan(sm)
        b, se, r2, G, _ = ols_cluster(sm[ok], np.zeros((ok.sum(), 0)), d.ym.values[ok])
        # also demeaned version: remove static long-bias x drift
        print(f'  {k if k == "BTC" else "LOO-idx":7s} h={h:+4d}h mean signed move {fmt(b[0], se[0], G)} %  (n={ok.sum()})'
              + (f'  TRAIN {np.nanmean(sm[(d.split == "TRAIN").values]):+.3f} TEST {np.nanmean(sm[(d.split == "TEST").values]):+.3f}'))
        if k == 'IDX' and h in (24, 48):
            d[f'fw{h}'] = sm / 100 / d.stop_pct
# regress R on exogenous fixed-horizon forward market move (stop units)
for h in (24, 48):
    b, se, r2, G, _ = ols_cluster(d.Rn.values, d[f'fw{h}'].values, d.ym.values)
    print(f'R ~ signed LOO move entry..entry+{h}h (stop units): alpha {fmt(b[0], se[0], G)} slope {fmt(b[1], se[1], G)} R2={r2:.3f} '
          f'mkt share {100 * b[1] * d[f"fw{h}"].sum() / d.Rn.sum():.0f}%')

# decompose own signed move into market-beta part + idiosyncratic part (per coin beta to LOO index)
print('\n-- tailwind: static long-bias vs timing --')
H = d.hours.values
mu_h = lvlT['IDX'].diff().mean()  # avg hourly log drift of index over whole sample
static = d.sgn * mu_h * H
print(f'index total log return over sample: {lvlT.IDX.iloc[-1]:.3f}; BTC {lvlT.BTC.iloc[-1] - lvlT.BTC.dropna().iloc[0]:.3f}')
print(f'mean signed index move per trade {100 * d.tw_idx.mean():+.3f}% (t={d.tw_idx.mean() / d.tw_idx.std() * np.sqrt(len(d)):.2f} naive); '
      f'static long-bias part {100 * static.mean():+.4f}% ; timing part {100 * (d.tw_idx - static).mean():+.3f}%')
# Null: random direction (keep each trade's window, flip sign at random with the book's long share)
pl = (d.sgn == 1).mean()
null = np.array([(np.where(rng.random(len(d)) < pl, 1, -1) * d.m_idx.values).mean() for _ in range(20000)])
print(f'null (random side, P(long)={pl:.3f}, same windows): mean tailwind {100 * null.mean():+.3f}%, '
      f'observed {100 * d.tw_idx.mean():+.3f}%, p(one-sided)={(null >= d.tw_idx.mean()).mean():.4f}')
# same for LOO index
nullL = np.array([(np.where(rng.random(len(d)) < pl, 1, -1) * d.m_loo.values).mean() for _ in range(20000)])
print(f'LOO: observed {100 * d.tw_loo.mean():+.3f}%, null mean {100 * nullL.mean():+.3f}% p={(nullL >= d.tw_loo.mean()).mean():.4f}')
# Signed tailwind: fraction of trades with positive tailwind, by outcome
print('share trades with market tailwind>0:', (d.tw_idx > 0).mean().round(3),
      '| among tp_hit', (d[d.exit_reason == 'tp_hit'].tw_idx > 0).mean().round(3),
      '| among sl_hit', (d[d.exit_reason == 'sl_hit'].tw_idx > 0).mean().round(3))

# R conditional on tailwind sign / quintile
d['tw_q'] = pd.qcut(d.twR_idx, 5, labels=False)
print('\nR by quintile of signed market move (stop units):')
print(d.groupby('tw_q').agg(n=('Rn', 'size'), x_lo=('twR_idx', 'min'), x_hi=('twR_idx', 'max'), meanR=('Rn', 'mean'),
                            WR=('Rn', lambda r: (r > 0).mean())).round(3).to_string())
# Residual (market-neutral) R: R minus beta*tailwind, i.e. residual + alpha
b, se, r2, G, e = ols_cluster(d.Rn.values, d.twR_idx.values, d.ym.values)
d['R_resid'] = d.Rn - b[1] * d.twR_idx
# when market tailwind ~0 (|x| small), what's mean R?
near0 = d[d.twR_idx.abs() < 0.25]
print(f'trades with |signed index move| < 0.25 stop: n={len(near0)} meanR={near0.Rn.mean():+.3f} '
      f'CI(month-boot)={month_boot_mean(near0, "Rn").round(3)}  WR={(near0.Rn > 0).mean():.3f}')

# $ decomposition in equity-return space: r_eq ~ a + b*tw (pct), weighted naturally
for k in ['idx', 'btc']:
    b2, se2, r22, G2, _ = ols_cluster(d.r_eq.values * 100, d['tw_' + k].values * 100, d.ym.values)
    tot = (d.r_eq * 100).sum()
    print(f'equity-return space ({k}): alpha {fmt(b2[0], se2[0], G2)} %/trade, slope {fmt(b2[1], se2[1], G2)}, R2={r22:.3f}, '
          f'sum r_eq={tot:.1f}%: mkt {b2[1] * (d["tw_" + k] * 100).sum():.1f}%, alpha {b2[0] * len(d):.1f}%')

# By sleeve
print('\nBy sleeve (index, stop units):')
for kol, sub in d.groupby('kol'):
    b, se, r2, G, e = ols_cluster(sub.Rn.values, sub.twR_idx.values, sub.ym.values)
    print(f'{kol:9s} n={len(sub)} meanR={sub.Rn.mean():+.3f} alpha {fmt(b[0], se[0], G)} slope {fmt(b[1], se[1], G)} R2={r2:.3f} '
          f'share mkt={100 * b[1] * sub.twR_idx.sum() / sub.Rn.sum():.0f}%  mean tw={sub.twR_idx.mean():+.3f}')

# ============ monthly level ============
# index monthly return (calendar month, by level at month boundaries)
def mret(col):
    z = lvlT[col].dropna(); z = z[z.index <= pd.Timestamp('2026-07-19 12:00', tz='UTC')]
    last = z.resample('ME').last(); first = z.iloc[0]
    r = last.diff(); r.iloc[0] = last.iloc[0] - first
    r.index = r.index.tz_convert(None).to_period('M'); return r
mret_idx = mret('IDX'); mret_btc = mret('BTC')
# daily index log returns for efficiency ratio
dl = lvlT['IDX'][lvlT.index <= pd.Timestamp('2026-07-19 12:00', tz='UTC')].resample('1D').last().diff().dropna()
dl.index = dl.index.tz_convert(None)
er = dl.groupby(dl.index.to_period('M')).apply(lambda r: abs(r.sum()) / r.abs().sum())
nd = dl.groupby(dl.index.to_period('M')).size()
# per-coin average ER (each coin's own trendiness), alternative measure
cer = []
for c in COINS:
    dc = lvlT['OWN_' + c].resample('1D').last().diff().dropna(); dc.index = dc.index.tz_convert(None)
    cer.append(dc.groupby(dc.index.to_period('M')).apply(lambda r: abs(r.sum()) / r.abs().sum()))
cer = pd.concat(cer, axis=1).mean(axis=1)
vol = dl.groupby(dl.index.to_period('M')).std() * np.sqrt(30)

# book monthly return by exit month
d['xm'] = d.xt.dt.tz_convert(None).dt.to_period('M')
eq_start = d.groupby('xm').eq_before.first()
M = pd.DataFrame({'pnl': d.groupby('xm').pnl_usdt.sum(), 'eq0': eq_start})
M['ret'] = M.pnl / M.eq0
M = M.join(pd.DataFrame({'idx': mret_idx, 'btc': mret_btc, 'er': er, 'cer': cer, 'vol': vol, 'ndays': nd}), how='left')
# per-month R stats by entry month
Rm = d.groupby('ym').agg(nR=('Rn', 'size'), meanR=('Rn', 'mean'), WR=('Rn', lambda r: (r > 0).mean()),
                         nlong=('sgn', lambda z: (z > 0).sum()))
M = M.join(Rm, how='left')
print('ndays', M.ndays.head(2).to_dict(), M.ndays.tail(2).to_dict())
M = M[M.ndays >= 15]  # drop very partial months at edges
M['split'] = np.where(M.index.to_timestamp() < SPLIT.tz_convert(None), 'TRAIN', 'TEST')
print('\nmonths', len(M), M.index.min(), M.index.max())

print('\n==== monthly book return vs index (beta and convexity) ====')
for nm, y in [('ret', M.ret)]:
    X = np.column_stack([M.idx]);
    b, se, r2, G, _ = ols_cluster(y.values, X, np.arange(len(M)))
    print(f'ret ~ idx: alpha {fmt(b[0], se[0], G)} beta {fmt(b[1], se[1], G)} R2={r2:.3f} n={len(M)}')
    X = np.column_stack([M.idx, M.idx.abs()])
    b3 = np.linalg.lstsq(np.column_stack([np.ones(len(M)), X]), y.values, rcond=None)[0]
    Xf = np.column_stack([np.ones(len(M)), X]); e = y.values - Xf @ b3
    V = np.linalg.inv(Xf.T @ Xf) * (e @ e) / (len(M) - 3)
    # HC1
    XtXi = np.linalg.inv(Xf.T @ Xf); meat = (Xf * e[:, None]).T @ (Xf * e[:, None])
    Vh = XtXi @ meat @ XtXi * len(M) / (len(M) - 3); seh = np.sqrt(np.diag(Vh))
    r2b = 1 - e @ e / ((y - y.mean()) @ (y - y.mean()))
    print(f'ret ~ idx + |idx|: const {b3[0]:+.4f}(se {seh[0]:.4f}) beta {b3[1]:+.3f}(se {seh[1]:.3f}, p={2 * stats.t.sf(abs(b3[1] / seh[1]), len(M) - 3):.3g}) '
          f'|idx| {b3[2]:+.3f}(se {seh[2]:.3f}, p={2 * stats.t.sf(abs(b3[2] / seh[2]), len(M) - 3):.3g}) R2={r2b:.3f}')
    print('corr(ret, idx) =', np.round(stats.pearsonr(M.ret, M.idx), 4), ' corr(ret,|idx|)=', np.round(stats.pearsonr(M.ret, M.idx.abs()), 4),
          ' corr(ret, btc)=', np.round(stats.pearsonr(M.ret, M.btc), 4))
    print('spearman ret vs |idx|', stats.spearmanr(M.ret, M.idx.abs()))

# ============ (2) long/short x up/down months ============
print('\n==== (2) long vs short by index month sign (entry month) ====')
d = d.join(mret_idx.rename('m_idx_month'), on='ym')
d['mkt_up'] = np.where(d.m_idx_month > 0, 'UP', 'DOWN')
for sp in ['ALL', 'TRAIN', 'TEST']:
    sub = d if sp == 'ALL' else d[d.split == sp]
    print(f'-- {sp}')
    for (mk, sd), g in sub.groupby(['mkt_up', 'side']):
        ci = month_boot_mean(g, 'Rn', 3000)
        print(f'  {mk:4s} {sd:5s} n={len(g):4d} meanR={g.Rn.mean():+.3f} CI95(month-boot)=[{ci[0]:+.3f},{ci[1]:+.3f}] WR={(g.Rn > 0).mean():.3f} '
              f'sumR={g.Rn.sum():+.1f} mean signed idx move={100 * g.tw_idx.mean():+.2f}%')
    # months count
    mm = sub.groupby('mkt_up').ym.nunique().to_dict()
    lr = sub.groupby('mkt_up').apply(lambda g: (g.sgn > 0).mean()).round(3).to_dict()
    print('  months', mm, 'long share of trades', lr)
    # interaction test: R ~ long + up + long*up, cluster by month
    L = (sub.sgn > 0).astype(float).values; U = (sub.mkt_up == 'UP').astype(float).values
    b, se, r2, G, _ = ols_cluster(sub.Rn.values, np.column_stack([L, U, L * U]), sub.ym.values)
    print(f'  R ~ long + up + long:up : long {fmt(b[1], se[1], G)} | up {fmt(b[2], se[2], G)} | interaction {fmt(b[3], se[3], G)}')
    # "aligned" (long in UP or short in DOWN) vs "against"
    al = ((L == 1) & (U == 1)) | ((L == 0) & (U == 0))
    ga, gb = sub[al], sub[~al]
    b, se, r2, G, _ = ols_cluster(sub.Rn.values, al.astype(float), sub.ym.values)
    print(f'  aligned-with-month n={len(ga)} R={ga.Rn.mean():+.3f} vs against n={len(gb)} R={gb.Rn.mean():+.3f}; diff {fmt(b[1], se[1], G)}')
    print(f'  overall long n={(L == 1).sum()} R={sub.Rn[L == 1].mean():+.3f} short n={(L == 0).sum()} R={sub.Rn[L == 0].mean():+.3f}')

# ============ (3) trendiness terciles ============
print('\n==== (3) regime: index efficiency ratio (daily, calendar month) terciles ====')
print('ER summary', M.er.describe().round(3).to_dict())
cuts = M.er.quantile([1 / 3, 2 / 3]).values
M['ter'] = pd.cut(M.er, [-1, cuts[0], cuts[1], 2], labels=['CHOP', 'MID', 'TREND'])
d = d.join(M[['ter', 'er', 'cer']], on='ym')
for sp in ['ALL', 'TRAIN', 'TEST']:
    subM = M if sp == 'ALL' else M[M.split == sp]
    subT = d if sp == 'ALL' else d[d.split == sp]
    print(f'-- {sp}  (cutoffs full-sample ER {cuts.round(3)})')
    for t in ['CHOP', 'MID', 'TREND']:
        gM = subM[subM.ter == t]; gT = subT[subT.ter == t]
        if len(gM) == 0: continue
        ci = month_boot_mean(gT, 'Rn', 3000) if len(gT) else [np.nan, np.nan]
        print(f'  {t:5s} months={len(gM):2d} trades={len(gT):3d} meanR={gT.Rn.mean():+.3f} [{ci[0]:+.3f},{ci[1]:+.3f}] WR={(gT.Rn > 0).mean():.3f} '
              f'monthly ret mean={100 * gM.ret.mean():+.1f}% median={100 * gM.ret.median():+.1f}% pos months={(gM.ret > 0).mean():.2f} '
              f'|idx| mean={100 * gM.idx.abs().mean():.1f}% vol={100 * gM.vol.mean():.1f}%')
    r_s = stats.spearmanr(subM.er, subM.ret); r_p = stats.pearsonr(subM.er, subM.ret)
    kw = stats.kruskal(*[subM[subM.ter == t].ret for t in ['CHOP', 'MID', 'TREND'] if (subM.ter == t).any()])
    print(f'  same-month ER vs book ret: pearson r={r_p[0]:+.3f} p={r_p[1]:.3g}; spearman rho={r_s[0]:+.3f} p={r_s[1]:.3g}; KW p={kw.pvalue:.3g}; n={len(subM)}')
    b, se, r2, G, _ = ols_cluster(subT.Rn.values, subT.er.values, subT.ym.values)
    print(f'  trade-level R ~ same-month ER: slope {fmt(b[1], se[1], G)}')
# sleeve x tercile
print('\nsleeve x tercile mean R (n):')
print(d.pivot_table(index='kol', columns='ter', values='Rn', aggfunc=['mean', 'size'], observed=False).round(3).to_string())
# alt measures
for nm in ['cer', 'vol']:
    r_s = stats.spearmanr(M[nm], M.ret)
    print(f'same-month {nm} vs ret spearman {r_s[0]:+.3f} p={r_s[1]:.3g}')
print('corr(ER, |idx|)', np.round(stats.spearmanr(M.er, M.idx.abs())[0], 3), 'corr(ER, vol)', np.round(stats.spearmanr(M.er, M.vol)[0], 3))

# ============ knowable in advance? ============
print('\n==== lagged regime: previous month ER vs this month ====')
M['er_lag'] = M.er.shift(1); M['cer_lag'] = M.cer.shift(1); M['ret_lag'] = M.ret.shift(1)
Ml = M.dropna(subset=['er_lag'])
for nm in ['er_lag', 'cer_lag']:
    for y in ['ret', 'meanR']:
        p = stats.pearsonr(Ml[nm], Ml[y]); s_ = stats.spearmanr(Ml[nm], Ml[y])
        print(f'{nm} vs {y}: pearson r={p[0]:+.3f} p={p[1]:.3g} | spearman {s_[0]:+.3f} p={s_[1]:.3g} n={len(Ml)}')
print('ACF(1) ER:', np.round(stats.pearsonr(Ml.er, Ml.er_lag), 3), ' ACF(1) coinER:', np.round(stats.pearsonr(Ml.cer, Ml.cer_lag), 3),
      ' ACF(1) book ret:', np.round(stats.pearsonr(Ml.ret, Ml.ret_lag), 3))
for sp in ['TRAIN', 'TEST']:
    g = Ml[Ml.split == sp]
    p = stats.pearsonr(g.er_lag, g.ret)
    print(f'  {sp}: er_lag vs ret r={p[0]:+.3f} p={p[1]:.3g} n={len(g)}')
# tercile of lagged ER
Ml = Ml.copy(); Ml['ter_lag'] = pd.cut(Ml.er_lag, [-1, cuts[0], cuts[1], 2], labels=['CHOP', 'MID', 'TREND'])
print(Ml.groupby('ter_lag', observed=False).agg(n=('ret', 'size'), ret=('ret', 'mean'), meanR=('meanR', 'mean')).round(3).to_string())
# trade-level ex-ante: index ER over the 30 days before entry
dl_full = lvlT['IDX'].resample('1D').last()
def er_before(t, n=30):
    w = dl_full[:t.floor('D')].diff().dropna().iloc[-n:]
    return abs(w.sum()) / w.abs().sum()
d['er30_pre'] = [er_before(t) for t in d.et]
b, se, r2, G, _ = ols_cluster(d.Rn.values, d.er30_pre.values, d.ym.values)
rr = stats.spearmanr(d.er30_pre, d.Rn)
print(f'trade-level R ~ ER(30d before entry): slope {fmt(b[1], se[1], G)} R2={r2:.4f}; spearman {rr[0]:+.3f} (naive p={rr[1]:.3g}) n={len(d)}')
for sp in ['TRAIN', 'TEST']:
    g = d[d.split == sp]
    b, se, r2, G, _ = ols_cluster(g.Rn.values, g.er30_pre.values, g.ym.values)
    print(f'  {sp}: slope {fmt(b[1], se[1], G)}')
# what does trade-life ER / same-window move say (ex-post): R on |index move| over trade life
b, se, r2, G, _ = ols_cluster(d.Rn.values, d.m_idx.abs().values * 100, d.ym.values)
print(f'ex-post: R ~ |index move over trade| (%): slope {fmt(b[1], se[1], G)} R2={r2:.3f}')

M.to_csv(f'{OUT}/monthly.csv'); d.drop(columns=['strategy_scores']).to_csv(f'{OUT}/trades_enriched.csv', index=False)
print(M[['ret', 'idx', 'btc', 'er', 'ter', 'nR', 'meanR', 'WR', 'nlong', 'split']].round(3).to_string())

# ======================= EXTRA =======================
print('\n==== EXTRA A: where does the mean come from? fixed-horizon forward moves, stop units ====')
for h in [4, 12, 24, 48]:
    own = np.array([at('OWN_' + c, [e + pd.Timedelta(hours=h)])[0] - at('OWN_' + c, [e])[0] for c, e in zip(d.coin, d.et)])
    loo = np.array([at('LOO_' + c, [e + pd.Timedelta(hours=h)])[0] - at('LOO_' + c, [e])[0] for c, e in zip(d.coin, d.et)])
    # measured from intended entry (signal close) so costs/slippage excluded: gross mark-to-market in stop units
    so = d.sgn.values * own / d.stop_pct.values; sm = d.sgn.values * d.beta.values * loo / d.stop_pct.values; si = so - sm
    for nm, v in [('own', so), ('beta*mkt', sm), ('idio', si)]:
        b, se, r2, G, _ = ols_cluster(v, np.zeros((len(v), 0)), d.ym.values)
        print(f'  h=+{h:3d}h signed {nm:8s} move/stop mean {fmt(b[0], se[0], G)}')
# pre-entry decomposition (why the book is "aligned"): 24h before entry
own = np.array([at('OWN_' + c, [e])[0] - at('OWN_' + c, [e - pd.Timedelta(hours=24)])[0] for c, e in zip(d.coin, d.et)])
loo = np.array([at('LOO_' + c, [e])[0] - at('LOO_' + c, [e - pd.Timedelta(hours=24)])[0] for c, e in zip(d.coin, d.et)])
so = d.sgn.values * own / d.stop_pct.values; sm = d.sgn.values * d.beta.values * loo / d.stop_pct.values
print(f'  pre-entry 24h: own {so.mean():+.3f} stop, of which beta*mkt {sm.mean():+.3f} ({100 * sm.mean() / so.mean():.0f}%) idio {(so - sm).mean():+.3f}')
for kol, g in d.groupby('kol'):
    ix = (d.kol == kol).values
    print(f'    {kol}: pre-entry own {so[ix].mean():+.3f}, mkt {sm[ix].mean():+.3f}')

print('\n==== EXTRA B: is month-to-month variation more than trade-sampling noise? ====')
g = d.groupby('ym').Rn
obs_sd = g.mean().std()
ns = g.size().values; allR = d.Rn.values
sims = []
for _ in range(5000):
    p = rng.permutation(allR); k = 0; ms = []
    for n in ns:
        ms.append(p[k:k + n].mean()); k += n
    sims.append(np.std(ms, ddof=1))
sims = np.array(sims)
print(f'SD of monthly mean R: observed {obs_sd:.3f}; iid-shuffle null median {np.median(sims):.3f} [95%: {np.percentile(sims, 2.5):.3f},{np.percentile(sims, 97.5):.3f}] p(>=obs)={(sims >= obs_sd).mean():.3f}')
# same but shuffling whole entry-days (keeps simultaneous-trade correlation) -> just report within-day corr
d['eday'] = d.et.dt.floor('D')
dd = d.groupby('eday').Rn.agg(['size', 'mean'])
print(f'entry-days {len(dd)}, trades/day mean {dd["size"].mean():.2f}; days with >=2 trades {(dd["size"] >= 2).sum()}')
# intra-day correlation of R among trades opened same day (ICC via one-way ANOVA)
k = dd['size']; grand = d.Rn.mean()
msb = (k * (dd['mean'] - grand) ** 2).sum() / (len(dd) - 1)
msw = ((d.Rn - d.eday.map(dd['mean'])) ** 2).sum() / (len(d) - len(dd))
k0 = (len(d) - (k ** 2).sum() / len(d)) / (len(dd) - 1)
icc = (msb - msw) / (msb + (k0 - 1) * msw)
print(f'ICC of R within entry-day: {icc:.3f} (k0={k0:.2f}) -> design effect ~ {1 + (k0 - 1) * icc:.2f}')
# same-day same-direction share
sd_ = d.groupby('eday').sgn.agg(lambda z: abs(z.sum()) == len(z) if len(z) >= 2 else np.nan).dropna()
print(f'multi-trade entry-days all same direction: {sd_.mean():.3f} (n={len(sd_)})')

print('\n==== EXTRA C: trade-horizon trendiness (variance ratio) instead of month ER ====')
lr = np.log1p(R1[COINS])
lr = lr[lr.index <= pd.Timestamp('2026-07-19 11:00', tz='UTC')]
def vr_month(x, q=24):
    x = x.dropna()
    if len(x) < 200: return np.nan
    s1 = x.var(); sq = x.rolling(q).sum().dropna().var()
    return sq / (q * s1)
mon = lr.index.tz_convert(None).to_period('M')
VR = lr.groupby(mon).apply(lambda df: np.nanmean([vr_month(df[c]) for c in COINS]))
idxr = np.log1p(idx_r[idx_r.index <= pd.Timestamp('2026-07-19 11:00', tz='UTC')])
VRi = idxr.groupby(idxr.index.tz_convert(None).to_period('M')).apply(vr_month)
M['vr_coin'] = VR; M['vr_idx'] = VRi
for nm in ['vr_coin', 'vr_idx']:
    for y in ['ret', 'meanR', 'WR']:
        p = stats.spearmanr(M[nm], M[y])
        print(f'  same-month {nm} vs {y}: spearman {p[0]:+.3f} p={p[1]:.3g} n={len(M)}')
    q = pd.qcut(M[nm], 3, labels=['LOW', 'MID', 'HIGH'])
    print(M.groupby(q, observed=False).agg(months=('ret', 'size'), vr=(nm, 'mean'), ret=('ret', 'mean'), meanR=('meanR', 'mean'), WR=('WR', 'mean')).round(3).to_string())
    lag = M[nm].shift(1)
    p = stats.spearmanr(lag[1:], M.ret[1:]); a = stats.pearsonr(lag[1:], M[nm][1:])
    print(f'  lagged {nm} vs ret: spearman {p[0]:+.3f} p={p[1]:.3g}; ACF(1) of {nm} r={a[0]:+.3f} p={a[1]:.3g}')

print('\n==== EXTRA D: sleeve x ER interaction (trade-level, month-clustered) ====')
for kol, g in d.groupby('kol'):
    b, se, r2, G, _ = ols_cluster(g.Rn.values, g.er.values, g.ym.values)
    print(f'  {kol}: R ~ month ER slope {fmt(b[1], se[1], G)} n={len(g)}')

print('\n==== EXTRA E: bad months profile ====')
M['bad'] = M.ret < 0
print(M.groupby('bad').agg(months=('ret', 'size'), ret=('ret', 'mean'), meanR=('meanR', 'mean'), WR=('WR', 'mean'), nR=('nR', 'mean'),
                           idx=('idx', 'mean'), absidx=('idx', lambda z: z.abs().mean()), er=('er', 'mean'), vol=('vol', 'mean'),
                           vr=('vr_coin', 'mean')).round(3).to_string())
for nm in ['idx', 'er', 'vol', 'vr_coin', 'nR']:
    u = stats.mannwhitneyu(M[M.bad][nm], M[~M.bad][nm])
    print(f'  bad vs good months {nm}: MWU p={u.pvalue:.3g}')
# aligned share in bad vs good months
d['aligned'] = ((d.sgn > 0) & (d.mkt_up == 'UP')) | ((d.sgn < 0) & (d.mkt_up == 'DOWN'))
al = d.groupby('ym').aligned.mean(); M['aligned'] = al
p = stats.spearmanr(M.aligned, M.ret)
print(f'  share of trades aligned with month sign vs month ret: spearman {p[0]:+.3f} p={p[1]:.3g}')
# signed-tailwind month aggregate (trade-life) vs ret
tw = d.groupby('ym').twR_idx.mean(); M['tw'] = tw
p = stats.spearmanr(M.tw, M.ret); print(f'  month mean trade-life signed index move vs ret: spearman {p[0]:+.3f} p={p[1]:.3g}')
M.to_csv(f'{OUT}/monthly.csv')
