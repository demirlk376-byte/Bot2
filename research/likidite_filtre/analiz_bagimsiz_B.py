#!/usr/bin/env python3
"""Likidite filtresi (donchian girisleri) -- implementation B.

Follows /home/user/sweep/research/likidite_filtre/ON_KAYIT.md exactly.
Style: explicit per-trade loops; every feature is computed from data that is
filtered by time for that single trade, with assertions that nothing after
the entry instant E is used.

Run:  python3 -I analiz.py
Writes only into its own directory (sonuc.json, ozellikler_*.csv).
"""
import json
import math
import os
import sqlite3
import sys

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------
# Paths (read-only inputs)
# ----------------------------------------------------------------------------
SP = '/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad'
DB_KESIF = SP + '/ikiz_kanit/ikiz_gercek.db'
DB_BAG = SP + '/ikiz_kanit/ikiz_eski.db'
PX_KESIF = '/tmp/claude-0/canli_wt/data/{coin}_fut_1h.csv'
PX_BAG = SP + '/eski_kos/data/{coin}_fut_1h.csv'
BOOK = '/home/user/sweep/research_data/kalabalik/veri/{coin}_bookdepth_5m.csv.gz'
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ----------------------------------------------------------------------------
# Constants from the spec
# ----------------------------------------------------------------------------
EPOCH = pd.Timestamp('1970-01-01', tz='UTC')
MS = pd.Timedelta(milliseconds=1)
H1 = pd.Timedelta(hours=1)
D1 = pd.Timedelta(days=1)
KESIF_START = pd.Timestamp('2023-04-07 00:00:00', tz='UTC')
BAG_END = pd.Timestamp('2023-04-07 00:00:00', tz='UTC')      # BAGIMSIZ: E < this
L2_END = pd.Timestamp('2026-01-08 00:00:00', tz='UTC')       # L2 window: E < this
L2_SPLIT = pd.Timestamp('2024-09-01 00:00:00', tz='UTC')     # halves
RISK = 0.035
SEED = 20261007
NBOOT = 10000
N_NUM = 7          # last 7 full days
N_DEN = 90         # 90 full days before them
MIN_DEN = 60       # at least 60 days of data
BOOK_MAX_AGE_MS = 15 * 60 * 1000

THRESH = {'L1a': 1.00, 'L1b': 0.75, 'L2a': 0.0, 'L2b': -0.10}
FEATURE_OF = {'L1a': 'LQ', 'L1b': 'LQ', 'L2a': 's', 'L2b': 's'}


def to_ms(t):
    """Timestamp -> integer epoch ms without relying on datetime resolution."""
    return int((t - EPOCH) // MS)


def isnan(x):
    return x is None or (isinstance(x, float) and math.isnan(x))


# ----------------------------------------------------------------------------
# Trades
# ----------------------------------------------------------------------------
def load_trades(db):
    # immutable=1: open strictly read-only, never touch -wal / -shm
    con = sqlite3.connect(f'file:{db}?immutable=1', uri=True)
    rows = con.execute(
        'SELECT id, symbol, side, entry_price, quantity, entry_time, exit_time, '
        'pnl_usdt, strategy_scores FROM trades').fetchall()
    con.close()
    n_rows = len(rows)
    n_donch_all = 0
    n_donch_null = 0
    trades = []
    for (tid, sym, side, ep, qty, et, xt, pnl, ss) in rows:
        sc = json.loads(ss) if ss else {}
        if sc.get('strategy') != 'donchian':
            continue
        n_donch_all += 1
        if pnl is None:
            n_donch_null += 1
            continue
        E = pd.Timestamp(et)
        assert E.tzinfo is not None, et
        E = E.tz_convert('UTC')
        assert xt is not None, tid
        X = pd.Timestamp(xt)
        assert X.tzinfo is not None, xt
        X = X.tz_convert('UTC')
        assert X >= E, tid
        sl0 = float(sc['sl0'])
        risk_usdt = abs(float(ep) - sl0) * float(qty)
        assert risk_usdt > 0, tid
        R = float(pnl) / risk_usdt
        assert side in ('long', 'short'), side
        trades.append(dict(id=tid, symbol=sym, coin=sym.split('/')[0], side=side,
                           dir=(1 if side == 'long' else -1), E=E, X=X, R=R))
    trades.sort(key=lambda t: (t['E'], t['symbol'], t['id']))
    return trades, dict(rows=n_rows, donchian_all=n_donch_all,
                        donchian_null_pnl=n_donch_null, donchian_used=len(trades))


# ----------------------------------------------------------------------------
# L1: market liquidity LQ
# ----------------------------------------------------------------------------
def load_px(path):
    df = pd.read_csv(path)
    df['t'] = pd.to_datetime(df['ts'], utc=True)     # bar OPEN time
    df = df.sort_values('t').reset_index(drop=True)
    assert not df['t'].duplicated().any(), path
    df['qv'] = df['volume'].astype(float) * df['close'].astype(float)
    df['day'] = df['t'].dt.floor('D')
    return df[['t', 'day', 'qv']]


def known_days(px, E):
    """Per-UTC-day (bar count, cash volume) using only bars known at E and
    only days that have ended at or before E."""
    known = px[px['t'] + H1 <= E]                    # bar fully closed by E
    if len(known) == 0:
        return pd.DataFrame(columns=['n', 'q'])
    # NO FUTURE DATA
    assert known['t'].max() + H1 <= E
    g = known.groupby('day').agg(n=('qv', 'size'), q=('qv', 'sum')).sort_index()
    g = g[g.index + D1 <= E]                        # day ended by E
    if len(g):
        assert g.index.max() + D1 <= E
    return g


def ratio(num, den):
    m = float(np.mean(num))
    md = float(np.median(den))
    if md > 0:
        return m / md
    if m > 0:
        return math.inf          # base median 0 (dead market) -> LQ=inf (kept)
    return math.nan


def lq_primary(g):
    """PRIMARY: 'full day' = UTC day ended <= E with all 24 hourly bars.
    numerator = mean q_d of the last 7 full days,
    denominator = median q_d of the (up to) 90 full days preceding them,
    requires >= 60 such days else n/a."""
    full = g[g['n'] == 24].sort_index()
    if len(full) < N_NUM + MIN_DEN:
        return math.nan
    num = full['q'].iloc[-N_NUM:].to_numpy()
    den = full['q'].iloc[-(N_NUM + N_DEN):-N_NUM].to_numpy()
    assert len(num) == N_NUM and MIN_DEN <= len(den) <= N_DEN
    return ratio(num, den)


def lq_alt_calendar(g, E):
    """SENSITIVITY A: calendar windows. L = last day ended by E.
    num = full days in [L-6, L]; den = full days in [L-96, L-7] (>=60 needed)."""
    L = E.floor('D') - D1
    assert L + D1 <= E and L + 2 * D1 > E
    full = g[g['n'] == 24]
    num = full[(full.index >= L - 6 * D1) & (full.index <= L)]['q'].to_numpy()
    den = full[(full.index >= L - 96 * D1) & (full.index <= L - 7 * D1)]['q'].to_numpy()
    if len(den) < MIN_DEN or len(num) == 0:
        return math.nan
    return ratio(num, den)


def lq_alt_anybars(g):
    """SENSITIVITY C: as primary but any ended day with >=1 bar counts as full."""
    full = g[g['n'] >= 1].sort_index()
    if len(full) < N_NUM + MIN_DEN:
        return math.nan
    num = full['q'].iloc[-N_NUM:].to_numpy()
    den = full['q'].iloc[-(N_NUM + N_DEN):-N_NUM].to_numpy()
    return ratio(num, den)


def lq_alt_nozero(g):
    """SENSITIVITY Z: as primary but zero-volume days are treated as no data."""
    full = g[(g['n'] == 24) & (g['q'] > 0)].sort_index()
    if len(full) < N_NUM + MIN_DEN:
        return math.nan
    num = full['q'].iloc[-N_NUM:].to_numpy()
    den = full['q'].iloc[-(N_NUM + N_DEN):-N_NUM].to_numpy()
    return ratio(num, den)


def add_lq(trades, px_tmpl):
    cache = {}
    for t in trades:
        coin = t['coin']
        if coin not in cache:
            p = px_tmpl.format(coin=coin)
            cache[coin] = load_px(p) if os.path.exists(p) else None
        px = cache[coin]
        if px is None:
            t['LQ'] = t['LQ_cal'] = t['LQ_any'] = t['LQ_nz'] = math.nan
            t['px_missing'] = True
            continue
        t['px_missing'] = False
        g = known_days(px, t['E'])
        t['LQ'] = lq_primary(g)
        t['LQ_cal'] = lq_alt_calendar(g, t['E'])
        t['LQ_any'] = lq_alt_anybars(g)
        t['LQ_nz'] = lq_alt_nozero(g)
        t['n_full_days'] = int((g['n'] == 24).sum()) if len(g) else 0


# ----------------------------------------------------------------------------
# L2: order book imbalance s
# ----------------------------------------------------------------------------
def load_book(path):
    b = pd.read_csv(path, usecols=['t_kapanis', 'imb1'])
    b = b.sort_values('t_kapanis').reset_index(drop=True)
    assert not b['t_kapanis'].duplicated().any(), path
    return b['t_kapanis'].to_numpy(np.int64), b['imb1'].to_numpy(float)


def add_s(trades):
    cache = {}
    for t in trades:
        coin = t['coin']
        if coin not in cache:
            p = BOOK.format(coin=coin)
            cache[coin] = load_book(p) if os.path.exists(p) else None
        bk = cache[coin]
        t['s'] = math.nan
        t['book_age_min'] = math.nan
        if bk is None:
            continue
        tk, imb = bk
        e_ms = to_ms(t['E'])
        idx = np.nonzero(tk <= e_ms)[0]
        if len(idx) == 0:
            continue
        i = idx[-1]                                  # last record with t_kapanis <= E
        # NO FUTURE DATA
        assert tk[i] <= e_ms
        assert i + 1 >= len(tk) or tk[i + 1] > e_ms
        age = e_ms - tk[i]
        t['book_age_min'] = age / 60000.0
        if age > BOOK_MAX_AGE_MS:
            continue
        v = float(imb[i])
        if math.isnan(v):
            continue
        t['s'] = v * t['dir']
    # SENSITIVITY (not in verdict): strict t_kapanis < E instead of <= E
    for t in trades:
        bk = cache[t['coin']]
        t['s_strict'] = math.nan
        if bk is None:
            continue
        tk, imb = bk
        e_ms = to_ms(t['E'])
        idx = np.nonzero(tk < e_ms)[0]
        if len(idx) == 0:
            continue
        i = idx[-1]
        assert tk[i] < e_ms
        if e_ms - tk[i] > BOOK_MAX_AGE_MS or math.isnan(float(imb[i])):
            continue
        t['s_strict'] = float(imb[i]) * t['dir']


# ----------------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------------
def max_dd(trs):
    """Compound eq *= 1 + 0.035 R in exit order, month-end last (ffill),
    prepend 1.0 at the month-end before the first exit; maxDD in %."""
    if len(trs) == 0:
        return 0.0
    trs = sorted(trs, key=lambda t: (t['X'], t['E'], t['id']))
    eq = 1.0
    times, vals = [], []
    for t in trs:
        eq *= (1.0 + RISK * t['R'])
        times.append(t['X'])
        vals.append(eq)
    s = pd.Series(vals, index=pd.DatetimeIndex(times))
    m = s.resample('ME').last().ffill()
    prev = m.index[0] - pd.offsets.MonthEnd(1)
    m = pd.concat([pd.Series([1.0], index=pd.DatetimeIndex([prev])), m])
    assert m.index.is_monotonic_increasing
    return float((1.0 - m / m.cummax()).max() * 100.0)


def boot_ci(skipped):
    if len(skipped) == 0:
        return math.nan, math.nan, math.nan, 0
    blocks = {}
    for t in skipped:
        iy, iw, _ = t['E'].isocalendar()
        k = (int(iy), int(iw))
        if k not in blocks:
            blocks[k] = [0.0, 0]
        blocks[k][0] += t['R']
        blocks[k][1] += 1
    keys = sorted(blocks)
    bs = np.array([blocks[k][0] for k in keys], dtype=float)
    bc = np.array([blocks[k][1] for k in keys], dtype=float)
    mean = float(bs.sum() / bc.sum())
    rng = np.random.default_rng(SEED)
    nb = len(keys)
    idx = rng.integers(0, nb, size=(NBOOT, nb))
    means = bs[idx].sum(axis=1) / bc[idx].sum(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return mean, float(lo), float(hi), nb


def evaluate(trs, feat, thr, with_boot=True):
    skipped, kept = [], []
    n_nofeat = 0
    for t in trs:
        v = t[feat]
        if isnan(v):
            n_nofeat += 1
            kept.append(t)
        elif v < thr:
            skipped.append(t)
        else:
            kept.append(t)
    assert len(skipped) + len(kept) == len(trs)
    res = dict(n_base=len(trs), n_kept=len(kept), n_skipped=len(skipped),
               n_no_feature=n_nofeat,
               sumR_base=float(sum(t['R'] for t in trs)),
               sumR_kept=float(sum(t['R'] for t in kept)),
               dd_base=max_dd(trs), dd_kept=max_dd(kept))
    if with_boot:
        m, lo, hi, nb = boot_ci(skipped)
        res.update(skipped_meanR=m, skipped_ci_lo=lo, skipped_ci_hi=hi, skipped_weeks=nb)
    return res


def good(r):
    return (r['sumR_kept'] > r['sumR_base']) and (r['dd_kept'] <= r['dd_base'] + 1.0)


def quintiles(trs, feat):
    av = [t for t in trs if not isnan(t[feat])]
    av = sorted(av, key=lambda t: (t[feat], t['E'], t['id']))
    out = []
    for qi, part in enumerate(np.array_split(np.arange(len(av)), 5)):
        grp = [av[i] for i in part]
        if not grp:
            continue
        out.append(dict(q=qi + 1, n=len(grp), lo=grp[0][feat], hi=grp[-1][feat],
                        meanR=float(np.mean([g['R'] for g in grp])),
                        sumR=float(np.sum([g['R'] for g in grp]))))
    return out, len(av)


# ----------------------------------------------------------------------------
def main():
    pd.set_option('display.width', 200)
    kes_all, kes_info = load_trades(DB_KESIF)
    bag_all, bag_info = load_trades(DB_BAG)

    kesif = [t for t in kes_all if t['E'] >= KESIF_START]
    bag = [t for t in bag_all if t['E'] < BAG_END]
    print('KESIF db info', kes_info, 'window trades', len(kesif),
          'E range', kesif[0]['E'], kesif[-1]['E'])
    print('BAG   db info', bag_info, 'window trades', len(bag),
          'E range', bag[0]['E'], bag[-1]['E'])

    add_lq(kesif, PX_KESIF)
    add_lq(bag, PX_BAG)
    l2_tum = [t for t in kesif if KESIF_START <= t['E'] < L2_END]
    add_s(l2_tum)
    for t in kesif + bag:
        t.setdefault('s', math.nan)          # L2 not defined outside L2 window
        t.setdefault('book_age_min', math.nan)
        t.setdefault('s_strict', math.nan)

    windows = {
        'KESIF': kesif,
        'BAGIMSIZ': bag,
        'L2_TUM': l2_tum,
        'L2_YARI1': [t for t in l2_tum if t['E'] < L2_SPLIT],
        'L2_YARI2': [t for t in l2_tum if L2_SPLIT <= t['E'] < L2_END],
    }
    assert len(windows['L2_YARI1']) + len(windows['L2_YARI2']) == len(l2_tum)

    rows = []
    res = {}
    for v in ('L1a', 'L1b'):
        for w in ('KESIF', 'BAGIMSIZ'):
            r = evaluate(windows[w], FEATURE_OF[v], THRESH[v])
            r.update(variant=v, window=w)
            rows.append(r)
            res[(v, w)] = r
    for v in ('L2a', 'L2b'):
        for w in ('L2_TUM', 'L2_YARI1', 'L2_YARI2'):
            r = evaluate(windows[w], FEATURE_OF[v], THRESH[v])
            r.update(variant=v, window=w)
            rows.append(r)
            res[(v, w)] = r

    verdicts = {}
    for v in ('L1a', 'L1b'):
        ok = good(res[(v, 'KESIF')]) and good(res[(v, 'BAGIMSIZ')])
        verdicts[v] = 'IYI' if ok else 'ELENDI'
    for v in ('L2a', 'L2b'):
        y1, y2, tm = res[(v, 'L2_YARI1')], res[(v, 'L2_YARI2')], res[(v, 'L2_TUM')]
        ok = (y1['sumR_kept'] > y1['sumR_base'] and y2['sumR_kept'] > y2['sumR_base']
              and tm['dd_kept'] <= tm['dd_base'] + 1.0)
        verdicts[v] = 'IYI (zayif kanit)' if ok else 'ELENDI'

    # ---------------- print main table
    cols = ['variant', 'window', 'n_base', 'n_kept', 'n_skipped', 'n_no_feature',
            'sumR_base', 'sumR_kept', 'dd_base', 'dd_kept', 'skipped_meanR',
            'skipped_ci_lo', 'skipped_ci_hi', 'skipped_weeks']
    print('\n=== RESULTS ===')
    print(pd.DataFrame(rows)[cols].round(4).to_string(index=False))
    print('\nVERDICTS', verdicts)

    # ---------------- coverage
    cov = {}
    for w, trs in windows.items():
        cov[w] = dict(n=len(trs),
                      LQ_avail=sum(not isnan(t['LQ']) for t in trs),
                      LQ_inf=sum((not isnan(t['LQ'])) and math.isinf(t['LQ']) for t in trs),
                      s_avail=sum(not isnan(t['s']) for t in trs) if w != 'BAGIMSIZ' else 0,
                      px_missing=sum(t['px_missing'] for t in trs))
    print('\nCOVERAGE', json.dumps(cov))
    first_lq = {}
    for t in kesif:
        if not isnan(t['LQ']) and t['coin'] not in first_lq:
            first_lq[t['coin']] = str(t['E'])
    print('first KESIF trade with LQ per coin', first_lq)
    nolq_late = [(t['coin'], str(t['E'])) for t in kesif
                 if isnan(t['LQ']) and t['E'] > pd.Timestamp('2023-07-20', tz='UTC')]
    print('KESIF trades w/o LQ after 2023-07-20:', nolq_late)
    nolq_bag = [(t['coin'], str(t['E']), t['n_full_days']) for t in bag if isnan(t['LQ'])]
    print('BAG trades w/o LQ (coin, E, n_full_days_known):', len(nolq_bag))
    inf_list = [(t['coin'], str(t['E'])) for w in ('KESIF', 'BAGIMSIZ') for t in windows[w]
                if not isnan(t['LQ']) and math.isinf(t['LQ'])]
    print('LQ=inf trades:', inf_list)
    nos = [(t['coin'], str(t['E']), round(t['book_age_min'], 1)) for t in l2_tum if isnan(t['s'])]
    print('L2 trades without s (coin, E, age_min of last rec):', nos)

    # ---------------- diagnostics: quintiles
    diag = {}
    print('\n=== DIAGNOSTICS (quintiles, decision-free) ===')
    for w in ('KESIF', 'BAGIMSIZ'):
        q, n = quintiles(windows[w], 'LQ')
        diag['LQ_' + w] = q
        print(f'LQ quintiles {w} (n={n})')
        print(pd.DataFrame(q).round(4).to_string(index=False))
    for w in ('L2_TUM',):
        q, n = quintiles(windows[w], 's')
        diag['s_' + w] = q
        print(f's quintiles {w} (n={n})')
        print(pd.DataFrame(q).round(4).to_string(index=False))

    # ---------------- sensitivity of LQ definition (decision-free)
    sens = {}
    print('\n=== LQ DEFINITION SENSITIVITY (not part of verdict) ===')
    for alt in ('LQ_cal', 'LQ_any', 'LQ_nz'):
        sens[alt] = {}
        for v in ('L1a', 'L1b'):
            thr = THRESH[v]
            out = {}
            okall = True
            for w in ('KESIF', 'BAGIMSIZ'):
                trs = windows[w]
                diff = 0
                for t in trs:
                    a = (not isnan(t['LQ'])) and t['LQ'] < thr
                    b = (not isnan(t[alt])) and t[alt] < thr
                    diff += int(a != b)
                r = evaluate(trs, alt, thr, with_boot=False)
                okall = okall and good(r)
                out[w] = dict(n_decisions_differ=diff, n_skipped=r['n_skipped'],
                              n_no_feature=r['n_no_feature'],
                              sumR_kept=round(r['sumR_kept'], 4), dd_kept=round(r['dd_kept'], 4))
            out['verdict'] = 'IYI' if okall else 'ELENDI'
            sens[alt][v] = out
            print(alt, v, json.dumps(out))

    ages = pd.Series([t['book_age_min'] for t in l2_tum]).value_counts(dropna=False).sort_index()
    print('L2 book age (min) of last record <= E:', ages.to_dict())
    for v in ('L2a', 'L2b'):
        out = {}
        for w in ('L2_TUM', 'L2_YARI1', 'L2_YARI2'):
            r = evaluate(windows[w], 's_strict', THRESH[v], with_boot=False)
            out[w] = dict(n_skipped=r['n_skipped'], sumR_base=round(r['sumR_base'], 4),
                          sumR_kept=round(r['sumR_kept'], 4), dd_base=round(r['dd_base'], 4),
                          dd_kept=round(r['dd_kept'], 4))
        okv = (out['L2_YARI1']['sumR_kept'] > out['L2_YARI1']['sumR_base']
               and out['L2_YARI2']['sumR_kept'] > out['L2_YARI2']['sumR_base']
               and out['L2_TUM']['dd_kept'] <= out['L2_TUM']['dd_base'] + 1.0)
        out['verdict'] = 'IYI (zayif kanit)' if okv else 'ELENDI'
        sens['s_strict_' + v] = out
        print('s_strict', v, json.dumps(out))

    # ---------------- save per-trade features for cross-check
    for w in ('KESIF', 'BAGIMSIZ'):
        pd.DataFrame([dict(id=t['id'], symbol=t['symbol'], side=t['side'], E=str(t['E']),
                           X=str(t['X']), R=t['R'], LQ=t['LQ'], s=t['s'],
                           LQ_cal=t['LQ_cal'], LQ_any=t['LQ_any'], LQ_nz=t['LQ_nz'])
                      for t in windows[w]]).to_csv(
            os.path.join(OUT_DIR, f'ozellikler_{w}.csv'), index=False)

    def clean(x):
        if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
            return str(x)
        return x
    out = dict(rows=[{k: clean(v) for k, v in r.items()} for r in rows], verdicts=verdicts,
               coverage=cov, db_info=dict(KESIF=kes_info, BAGIMSIZ=bag_info),
               diagnostics={k: [{kk: clean(vv) for kk, vv in d.items()} for d in q]
                            for k, q in diag.items()},
               sensitivity=sens)
    with open(os.path.join(OUT_DIR, 'sonuc.json'), 'w') as f:
        json.dump(out, f, indent=1, default=str)
    print('\nwrote', os.path.join(OUT_DIR, 'sonuc.json'))


if __name__ == '__main__':
    main()
