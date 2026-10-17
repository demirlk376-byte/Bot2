#!/usr/bin/env python3
"""Gun ici v1 -- FINAL implementation of /home/user/sweep/research/gun_ici_v1/ON_KAYIT.md (pre-registration).

Nothing pre-registered is changed: thresholds (|f_prev| >= 0.0003; C1 3*ATR20, 3*median20, 2*ATR20 stop, 12 bars),
costs (NORMAL 10 bp, STRESS 21 bp), periods (KESIF 2023-01-01..2024-12-31, DOGRULAMA 2025-01-01..2026-09-30),
bootstrap (weekly ISO blocks of entry time, 10 000 reps, seed 20261017, Bonferroni lower = 0.83 percentile) and the
three-part KAZANDI criterion.

Conventions:
  * a 5m bar with open_time t is known only at t+5m; a trade "at time X" uses OPEN of the bar whose open_time == X
  * settlement T = funding calc_time rounded to the nearest 5 minutes
  * a missing bar needed by a trade -> trade skipped and counted
  * long gross bp = (exit/entry - 1)*1e4 ; short gross bp = (entry - exit)/entry*1e4 ; net = gross - cost
  * period membership, year and ISO week are taken from the ENTRY time (UTC)
  * F1/F2: f_prev(T) = last_funding_rate of the preceding funding record (settled at T-8h; verified 8h spacing)
  * C1: r_i = c_i/c_{i-1} - 1 ; TR_j = max(h_j, c_{j-1}) - min(l_j, c_{j-1}) ; ATR20_i = SMA(TR, bars i-20..i-1) ;
        MED20_i = median(volume, bars i-20..i-1)  (signal bar excluded -> "only past bars") ;
        entry open of bar i+1 ; stop entry -/+ 2*ATR20_i checked on bars i+1..i+12 (open beyond stop -> exit at that
        open, else range touches stop -> exit at stop) ; otherwise exit at open of bar i+13 (= entry + 60 min) ;
        next eligible signal bar = exit bar (no new signal while the position is open).

Resolution of the A/B discrepancy (C1 KESIF n: A=8864, B=8907):
  The 5m files contain 24 identical-timestamp maintenance filler bars per coin (volume == 0 and o == h == l == c;
  2023-09-12 08:35-08:45, 2024-10-28 16:25-16:30 and 20:00-21:05, 2025-01-29 01:25-01:30, 2025-08-29 06:20-06:30).
  They are not traded candles (the exchange was not trading), so they are MISSING bars. Implementation B treated
  them as real: they entered ATR20 (TR = 0) and MED20 (volume = 0), producing 43 extra KESIF C1 trades, 23 of them
  with MED20 == 0 so that "volume >= 3*median" was satisfied trivially. This script treats them as missing (A's
  rule); the B variant is re-computed as a diagnostic and checked to reproduce B exactly.
"""
import csv
import datetime
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path('/home/user/sweep/research_data/liquidity_sweep_v1/veri')
OUT = Path('/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/gun_ici_final')
REF_A = Path('/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/gun_ici_A/trades_A.csv')
REF_B = Path('/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/gun_ici_B/islemler.csv')
COINS = 'SOL ETH ADA NEAR BCH XRP DOGE TRX XLM LTC ICP BNB'.split()

BAR_MS = 300_000
HOUR_MS = 3_600_000
F_THR = 0.0003
C1_K_RET = 3.0
C1_K_VOL = 3.0
C1_K_STOP = 2.0
C1_HOLD = 12
C1_WIN = 20
COST = {'NORMAL': 10.0, 'STRESS': 21.0}
N_BOOT = 10_000
SEED = 20261017
HYPS = ('F1', 'F2', 'C1')
PERIODS = ('KESIF', 'DOGRULAMA')


def utc_ms(y, m, d):
    return int(datetime.datetime(y, m, d, tzinfo=datetime.timezone.utc).timestamp() * 1000)


P_BOUNDS = [('KESIF', utc_ms(2023, 1, 1), utc_ms(2025, 1, 1)),
            ('DOGRULAMA', utc_ms(2025, 1, 1), utc_ms(2026, 10, 1))]


def period_of(t_ms):
    t_ms = np.asarray(t_ms, dtype=np.int64)
    out = np.full(t_ms.shape, '', dtype=object)
    for name, a, b in P_BOUNDS:
        out[(t_ms >= a) & (t_ms < b)] = name
    return out


def gross_bp(entry, exit_, direction):
    entry = np.asarray(entry, float)
    exit_ = np.asarray(exit_, float)
    long_r = (exit_ / entry - 1.0) * 1e4
    short_r = (entry - exit_) / entry * 1e4
    return np.where(np.asarray(direction) > 0, long_r, short_r)


# =============================================================================================== data

def raw_bars(coin):
    d = np.load(BASE / 'binance_5m' / f'{coin}.npz')
    return {k: np.array(d[k]) for k in ('open_time_ms', 'open', 'high', 'low', 'close', 'volume')}


def synthetic_mask(b):
    return (b['volume'] == 0) & (b['open'] == b['high']) & (b['high'] == b['low']) & (b['low'] == b['close'])


def load_bars(coin, synthetic_missing=True):
    b = raw_bars(coin)
    df = pd.DataFrame(b).sort_values('open_time_ms').drop_duplicates('open_time_ms').reset_index(drop=True)
    grid = np.arange(df.open_time_ms.iloc[0], df.open_time_ms.iloc[-1] + BAR_MS, BAR_MS, dtype=np.int64)
    df = df.set_index('open_time_ms').reindex(grid)          # explicit NaN rows for absent timestamps
    df.index.name = 'open_time_ms'
    df = df.reset_index()
    synth = ((df.volume == 0) & (df.open == df.high) & (df.high == df.low) & (df.low == df.close)).to_numpy()
    if synthetic_missing:
        df.loc[synth, ['open', 'high', 'low', 'close', 'volume']] = np.nan
    df['valid'] = df[['open', 'high', 'low', 'close', 'volume']].notna().all(axis=1)
    df['synth'] = synth
    return df


def load_funding(coin):
    f = pd.read_csv(BASE / 'binance_funding' / f'{coin}.csv').sort_values('calc_time').reset_index(drop=True)
    f['T'] = ((f.calc_time.astype(np.int64) + BAR_MS // 2) // BAR_MS) * BAR_MS
    f['f_prev'] = f.last_funding_rate.shift(1)
    f['T_prev'] = f['T'].shift(1)
    return f


# =============================================================================================== F1 / F2

def funding_trades(coin, bars, fund):
    t0 = int(bars.open_time_ms.iloc[0])
    n = len(bars)
    op = bars.open.to_numpy()
    valid = bars.valid.to_numpy()

    def bar_open(t_ms):
        t_ms = np.asarray(t_ms, dtype=np.int64)
        idx = (t_ms - t0) // BAR_MS
        ok = ((t_ms - t0) % BAR_MS == 0) & (idx >= 0) & (idx < n)
        idx_c = np.clip(idx, 0, n - 1)
        ok &= valid[idx_c]
        return np.where(ok, op[idx_c], np.nan), ok

    sig = fund[fund.f_prev.abs() >= F_THR]
    assert ((sig['T'] - sig['T_prev']) == 8 * HOUR_MS).all(), 'f_prev must be the settlement exactly 8h earlier'
    T = sig['T'].to_numpy(np.int64)
    fp = sig.f_prev.to_numpy()
    out, skips = [], []
    for hyp, e_off, x_off, dir_sign in (('F1', -HOUR_MS, 0, -1), ('F2', 0, HOUR_MS, +1)):
        et, xt = T + e_off, T + x_off
        ep, eok = bar_open(et)
        xp, xok = bar_open(xt)
        direction = (dir_sign * np.sign(fp)).astype(int)     # F1: f>0 -> SHORT ; F2: f>0 -> LONG
        ok = eok & xok
        skips.append(pd.DataFrame({'hyp': hyp, 'coin': coin, 'period': period_of(et)[~ok], 'entry_ms': et[~ok]}))
        out.append(pd.DataFrame({
            'hyp': hyp, 'coin': coin, 'signal_ms': T[ok], 'entry_ms': et[ok], 'exit_ms': xt[ok], 'T_ms': T[ok],
            'f_prev': fp[ok], 'direction': direction[ok], 'entry_px': ep[ok], 'exit_px': xp[ok],
            'stop_px': np.nan, 'atr20': np.nan, 'gross_bp': gross_bp(ep[ok], xp[ok], direction[ok]),
            'exit_type': 'time'}))
    return pd.concat(out, ignore_index=True), pd.concat(skips, ignore_index=True)


# =============================================================================================== C1

def c1_trades(coin, bars, atr_mode='sma', include_current=False, reentry_same_bar=False):
    """Defaults = pre-registered spec. Other switches only for the (non pre-registered) sensitivity table."""
    o = bars.open.to_numpy()
    h = bars.high.to_numpy()
    lo = bars.low.to_numpy()
    c = bars.close.to_numpy()
    v = bars.volume.to_numpy()
    t = bars.open_time_ms.to_numpy(np.int64)
    valid = bars.valid.to_numpy()
    n = len(bars)

    c_prev = np.r_[np.nan, c[:-1]]
    tr = np.fmax(h, c_prev) - np.fmin(lo, c_prev)
    tr[~(valid & np.r_[False, valid[:-1]])] = np.nan          # TR_j needs real bars j and j-1
    lag = 0 if include_current else 1
    if atr_mode == 'sma':
        atr = pd.Series(tr).rolling(C1_WIN, min_periods=C1_WIN).mean().shift(lag).to_numpy()
    else:
        rma = pd.Series(tr).ewm(alpha=1.0 / C1_WIN, adjust=False, ignore_na=True).mean()
        cnt = pd.Series(np.isfinite(tr).astype(float)).rolling(C1_WIN).sum()
        atr = rma.where(cnt == C1_WIN).shift(lag).to_numpy()
    vmed = pd.Series(np.where(valid, v, np.nan)).rolling(C1_WIN, min_periods=C1_WIN).median().shift(lag).to_numpy()
    r = c / c_prev - 1.0
    thr = C1_K_RET * atr / c_prev
    evaluable = valid & np.isfinite(c_prev) & np.isfinite(atr) & np.isfinite(vmed) & (atr > 0)
    with np.errstate(invalid='ignore'):
        vol_ok = v >= C1_K_VOL * vmed
        long_sig = evaluable & vol_ok & (r <= -thr)
        short_sig = evaluable & vol_ok & (r >= thr)
    sig_idx = np.flatnonzero(long_sig | short_sig)
    sig_dir = np.where(long_sig[sig_idx], 1, -1)

    W = C1_HOLD + 1                                           # offsets 1..13 after the signal bar
    pad = W + 1
    Hp = np.r_[h, np.full(pad, np.nan)]
    Lp = np.r_[lo, np.full(pad, np.nan)]
    Op = np.r_[o, np.full(pad, np.nan)]
    Vp = np.r_[valid, np.zeros(pad, bool)]
    offs = np.arange(1, W + 1)
    J = sig_idx[:, None] + offs[None, :]
    entry_px = Op[sig_idx + 1]
    a = atr[sig_idx]
    stop = entry_px - sig_dir * C1_K_STOP * a
    Jh = J[:, :C1_HOLD]                                       # holding bars i+1..i+12
    with np.errstate(invalid='ignore'):
        hit = np.where(sig_dir[:, None] > 0, Lp[Jh] <= stop[:, None], Hp[Jh] >= stop[:, None])
    hit &= Vp[Jh]
    any_hit = hit.any(axis=1)
    first_hit = np.where(any_hit, hit.argmax(axis=1), C1_HOLD)
    exit_idx = sig_idx + 1 + first_hit
    need = offs[None, :] <= (first_hit + 1)[:, None]          # every bar from entry through exit must be real
    tradable = ~((~Vp[J]) & need).any(axis=1) & (exit_idx < n)
    exit_open = Op[np.minimum(exit_idx, n + pad - 1)]
    with np.errstate(invalid='ignore'):
        gap_through = np.where(sig_dir > 0, exit_open <= stop, exit_open >= stop)
    exit_px = np.where(any_hit, np.where(gap_through, exit_open, stop), exit_open)
    exit_type = np.where(any_hit, np.where(gap_through, 'stop_gap', 'stop'), 'time')

    taken = np.zeros(len(sig_idx), bool)
    blocked = np.zeros(len(sig_idx), bool)
    skipped = np.zeros(len(sig_idx), bool)
    next_ok = -1
    for k in range(len(sig_idx)):
        if sig_idx[k] < next_ok:
            blocked[k] = True
            continue
        if not tradable[k]:
            skipped[k] = True
            continue
        taken[k] = True
        next_ok = exit_idx[k] - 1 if reentry_same_bar else exit_idx[k]

    tk = taken
    si = sig_idx[tk]
    trades = pd.DataFrame({
        'hyp': 'C1', 'coin': coin, 'signal_ms': t[si], 'entry_ms': t[si + 1],
        'exit_ms': t[si] + BAR_MS * (1 + first_hit[tk]), 'T_ms': np.nan, 'f_prev': np.nan,
        'direction': sig_dir[tk], 'entry_px': entry_px[tk], 'exit_px': exit_px[tk], 'stop_px': stop[tk],
        'atr20': a[tk], 'gross_bp': gross_bp(entry_px[tk], exit_px[tk], sig_dir[tk]), 'exit_type': exit_type[tk],
        'sig_ret_bp': r[si] * 1e4, 'vmed20': vmed[si], 'sig_idx': si, 'exit_idx': exit_idx[tk]})
    sk_entry = t[sig_idx[skipped]] + BAR_MS
    skips = pd.DataFrame({'hyp': 'C1', 'coin': coin, 'period': period_of(sk_entry), 'entry_ms': sk_entry})
    info = {'candidates': int(len(sig_idx)), 'taken': int(tk.sum()), 'blocked_open_position': int(blocked.sum()),
            'skipped_missing_bar': int(skipped.sum()), 'real_bars_not_evaluable': int((valid & ~evaluable).sum())}
    return trades, skips, info


# =============================================================================================== stats

def iso_week_key(entry_ms):
    iso = pd.to_datetime(entry_ms, unit='ms', utc=True).isocalendar()
    return (iso['year'].astype(int) * 100 + iso['week'].astype(int)).to_numpy()


def boot_ratio_means(values, week_key):
    """Weekly block bootstrap (resample weeks with replacement), ratio-of-sums mean, fresh RNG(SEED) per call."""
    weeks, inv = np.unique(week_key, return_inverse=True)
    s = np.bincount(inv, weights=values)
    m = np.bincount(inv).astype(float)
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(weeks), size=(N_BOOT, len(weeks)))
    return s[idx].sum(axis=1) / m[idx].sum(axis=1), len(weeks)


def summarize(trades, skips):
    rows = []
    for hyp in HYPS:
        for per in PERIODS:
            d = trades[(trades.hyp == hyp) & (trades.period == per)]
            row = {'hyp': hyp, 'period': per, 'n': int(len(d)),
                   'skipped': int(((skips.hyp == hyp) & (skips.period == per)).sum())}
            g = d.gross_bp.to_numpy()
            if len(d):
                wk = d.week.to_numpy()
                bn, n_weeks = boot_ratio_means(g - COST['NORMAL'], wk)
                bs, _ = boot_ratio_means(g - COST['STRESS'], wk)
                cm = d.groupby('coin').gross_bp.mean().reindex(COINS)
                row.update({
                    'gross_bp': float(g.mean()),
                    'net_normal_bp': float((g - COST['NORMAL']).mean()),
                    'net_stress_bp': float((g - COST['STRESS']).mean()),
                    'bonf_lo_normal': float(np.percentile(bn, 0.83)),
                    'bonf_hi_normal': float(np.percentile(bn, 99.17)),
                    'ci95_lo_normal': float(np.percentile(bn, 2.5)),
                    'ci95_hi_normal': float(np.percentile(bn, 97.5)),
                    'bonf_lo_stress': float(np.percentile(bs, 0.83)),
                    'bonf_hi_stress': float(np.percentile(bs, 99.17)),
                    'ci95_lo_stress': float(np.percentile(bs, 2.5)),
                    'ci95_hi_stress': float(np.percentile(bs, 97.5)),
                    'n_weeks': int(n_weeks),
                    'coins_pos_normal': int(((cm - COST['NORMAL']) > 0).sum()),   # coin with no trade -> not positive
                    'coins_pos_stress': int(((cm - COST['STRESS']) > 0).sum()),
                    'coins_with_trades': int(cm.notna().sum()),
                })
            else:
                row.update({'gross_bp': np.nan, 'net_normal_bp': np.nan, 'net_stress_bp': np.nan,
                            'bonf_lo_normal': np.nan, 'coins_pos_normal': 0})
            rows.append(row)
    return pd.DataFrame(rows)


def verdicts(rows):
    out, detail = {}, {}
    for hyp in HYPS:
        k = rows[(rows.hyp == hyp) & (rows.period == 'KESIF')].iloc[0]
        d = rows[(rows.hyp == hyp) & (rows.period == 'DOGRULAMA')].iloc[0]
        c1 = bool(k.net_stress_bp > 0) and bool(d.net_stress_bp > 0)
        c2 = bool(d.bonf_lo_normal > 0)
        c3 = bool(d.coins_pos_normal >= 8)
        out[hyp] = 'KAZANDI' if (c1 and c2 and c3) else 'ELENDI'
        detail[hyp] = {'(1) STRESS net>0 KESIF & DOGRULAMA': c1, '(2) DOGRULAMA NORMAL Bonferroni lower>0': c2,
                       '(3) DOGRULAMA coins NORMAL net>0 >= 8/12': c3}
    return out, detail


# =============================================================================================== run

def run(synthetic_missing=True):
    all_tr, all_sk, c1_info, fund_all = [], [], {}, []
    for coin in COINS:
        bars = load_bars(coin, synthetic_missing)
        fund = load_funding(coin)
        fund['coin'] = coin
        fund_all.append(fund)
        ft, fs = funding_trades(coin, bars, fund)
        ct, cs, info = c1_trades(coin, bars)
        c1_info[coin] = info
        all_tr += [ft, ct]
        all_sk += [fs, cs]
    trades = pd.concat(all_tr, ignore_index=True)
    skips = pd.concat(all_sk, ignore_index=True)
    trades['period'] = period_of(trades.entry_ms.to_numpy())
    out_of_range = int((trades.period == '').sum())
    trades = trades[trades.period != ''].reset_index(drop=True)
    skips = skips[skips.period != ''].reset_index(drop=True)
    trades['week'] = iso_week_key(trades.entry_ms.to_numpy())
    trades['year'] = pd.to_datetime(trades.entry_ms, unit='ms', utc=True).dt.year.to_numpy()
    trades['side'] = np.where(trades.direction > 0, 'LONG', 'SHORT')
    trades['net_normal_bp'] = trades.gross_bp - COST['NORMAL']
    trades['net_stress_bp'] = trades.gross_bp - COST['STRESS']
    return trades, skips, c1_info, pd.concat(fund_all, ignore_index=True), out_of_range


# =============================================================================================== verification

def indep_c1_loop(coin, synthetic_missing=True):
    """Plain-loop C1 written separately from the vectorised code (B-style TR, direct slices, explicit stop loop)."""
    b = raw_bars(coin)
    t = b['open_time_ms'].tolist()
    o, h, l, c, v = (b[k].tolist() for k in ('open', 'high', 'low', 'close', 'volume'))
    n = len(t)
    assert all(t[k + 1] - t[k] == BAR_MS for k in range(n - 1)), 'loop assumes a gap-free grid'
    syn = synthetic_mask(b).tolist()
    real = [not s for s in syn] if synthetic_missing else [True] * n
    TR = [None] * n
    for j in range(1, n):
        if real[j] and real[j - 1]:
            TR[j] = max(h[j] - l[j], abs(h[j] - c[j - 1]), abs(l[j] - c[j - 1]))
    out = []
    i, free_from = C1_WIN + 1, 0
    while i < n:
        if i < free_from or not (real[i] and real[i - 1]):
            i += 1
            continue
        w = TR[i - C1_WIN:i]
        if any(x is None for x in w) or not all(real[i - C1_WIN:i]):
            i += 1
            continue
        atr = sum(w) / C1_WIN
        if atr <= 0:
            i += 1
            continue
        ret = c[i] / c[i - 1] - 1.0
        thr = C1_K_RET * atr / c[i - 1]
        med = statistics.median(v[i - C1_WIN:i])
        side = 0
        if v[i] >= C1_K_VOL * med:
            if ret <= -thr:
                side = 1
            elif ret >= thr:
                side = -1
        if side == 0:
            i += 1
            continue
        e_i = i + 1
        if e_i >= n or not real[e_i]:
            i += 1
            continue
        e = o[e_i]
        stop = e - side * C1_K_STOP * atr
        xp = xj = rs = None
        bad = False
        for j in range(e_i, e_i + C1_HOLD):
            if j >= n or not real[j]:
                bad = True
                break
            if side == 1:
                if o[j] <= stop:
                    xp, xj, rs = o[j], j, 'stop_gap'
                    break
                if l[j] <= stop:
                    xp, xj, rs = stop, j, 'stop'
                    break
            else:
                if o[j] >= stop:
                    xp, xj, rs = o[j], j, 'stop_gap'
                    break
                if h[j] >= stop:
                    xp, xj, rs = stop, j, 'stop'
                    break
        if not bad and xp is None:
            xj = e_i + C1_HOLD
            if xj >= n or not real[xj]:
                bad = True
            else:
                xp, rs = o[xj], 'time'
        if bad:
            i += 1
            continue
        g = (xp / e - 1.0) * 1e4 if side == 1 else (e - xp) / e * 1e4
        out.append((coin, t[i], t[e_i], t[xj], side, e, xp, g, rs))
        free_from = xj
        i += 1
    return pd.DataFrame(out, columns=['coin', 'signal_ms', 'entry_ms', 'exit_ms', 'direction', 'entry_px', 'exit_px',
                                      'g', 'rs'])


def indep_f_loop(coin):
    b = raw_bars(coin)
    syn = synthetic_mask(b)
    pos = {int(x): k for k, x in enumerate(b['open_time_ms']) if not syn[k]}
    o = b['open']
    rows, skipped = [], 0
    with open(BASE / 'binance_funding' / f'{coin}.csv', newline='') as fh:
        rec = sorted(((int(r['calc_time']), float(r['last_funding_rate'])) for r in csv.DictReader(fh)))
    for k in range(1, len(rec)):
        T = int(round(rec[k][0] / BAR_MS)) * BAR_MS
        Tp = int(round(rec[k - 1][0] / BAR_MS)) * BAR_MS
        fp = rec[k - 1][1]
        assert T - Tp == 8 * HOUR_MS
        if abs(fp) < F_THR:
            continue
        for hyp, a_, b_ in (('F1', T - HOUR_MS, T), ('F2', T, T + HOUR_MS)):
            if a_ not in pos or b_ not in pos:
                skipped += 1
                continue
            e, x = float(o[pos[a_]]), float(o[pos[b_]])
            short = (fp > 0) if hyp == 'F1' else (fp < 0)
            g = (e - x) / e * 1e4 if short else (x / e - 1.0) * 1e4
            rows.append((hyp, coin, a_, b_, -1 if short else 1, g))
    return pd.DataFrame(rows, columns=['hyp', 'coin', 'entry_ms', 'exit_ms', 'direction', 'g']), skipped


def indep_boot(net, entry_ms):
    """Sequential per-replicate draws, datetime-based ISO weeks, explicit per-week sums."""
    wk = [datetime.datetime.fromtimestamp(m / 1000.0, tz=datetime.timezone.utc).isocalendar()[:2] for m in entry_ms]
    keys = sorted(set(wk))
    kp = {k: j for j, k in enumerate(keys)}
    s = np.zeros(len(keys))
    cnt = np.zeros(len(keys))
    for x, w in zip(net, wk):
        s[kp[w]] += x
        cnt[kp[w]] += 1
    rng = np.random.default_rng(SEED)
    st = np.empty(N_BOOT)
    for rep in range(N_BOOT):
        p = rng.integers(0, len(keys), size=len(keys))
        st[rep] = s[p].sum() / cnt[p].sum()
    return {q: float(np.percentile(st, q)) for q in (0.83, 99.17, 2.5, 97.5)}


def verify(trades, rows, trades_var, rows_var, verd):
    V = {}
    ok_all = True

    def chk(name, cond, info):
        nonlocal ok_all
        V[name] = {'pass': bool(cond), 'info': info}
        ok_all &= bool(cond)

    # V1 data audit
    synth_ts, audit = None, {}
    for coin in COINS:
        b = raw_bars(coin)
        dt = np.diff(b['open_time_ms'])
        syn = synthetic_mask(b)
        ts = b['open_time_ms'][syn]
        synth_ts = ts if synth_ts is None else synth_ts
        audit[coin] = {'n': int(len(dt) + 1), 'gaps': int((dt != BAR_MS).sum()),
                       'nan': int(sum(np.isnan(b[k]).sum() for k in ('open', 'high', 'low', 'close', 'volume'))),
                       'synthetic': int(syn.sum()), 'zero_volume': int((b['volume'] == 0).sum()),
                       'synth_same_ts_as_SOL': bool(np.array_equal(ts, synth_ts))}
    chk('V1_data_audit', all(a['gaps'] == 0 and a['nan'] == 0 and a['synthetic'] == 24 and a['zero_volume'] == 24
                             and a['synth_same_ts_as_SOL'] for a in audit.values()),
        {'per_coin': audit['SOL'], 'all_coins_identical': True,
         'synthetic_times_utc': [str(pd.to_datetime(x, unit='ms')) for x in synth_ts]})

    # V2 independent C1 loop, all coins, synthetic = missing
    c1 = trades[trades.hyp == 'C1']
    loop = pd.concat([indep_c1_loop(c) for c in COINS], ignore_index=True)
    loop['period'] = period_of(loop.entry_ms.to_numpy())
    loop = loop[loop.period != '']
    m = c1.merge(loop, on=['coin', 'entry_ms'], how='outer', indicator=True, suffixes=('', '_l'))
    both = m[m._merge == 'both']
    info = {'vectorised': int(len(c1)), 'loop': int(len(loop)), 'merge': m._merge.value_counts().to_dict(),
            'dir_mismatch': int((both.direction != both.direction_l).sum()),
            'exit_ms_mismatch': int((both.exit_ms != both.exit_ms_l).sum()),
            'exit_type_mismatch': int((both.exit_type != both.rs).sum()),
            'max_abs_gross_diff': float((both.gross_bp - both.g).abs().max())}
    chk('V2_C1_independent_loop_all_coins', info['merge'].get('both', 0) == len(c1) == len(loop)
        and info['dir_mismatch'] == 0 and info['exit_ms_mismatch'] == 0 and info['exit_type_mismatch'] == 0
        and info['max_abs_gross_diff'] < 1e-9, info)

    # V3 independent F1/F2 loop, all coins
    fl, fsk = [], 0
    for c in COINS:
        x, s = indep_f_loop(c)
        fl.append(x)
        fsk += s
    fl = pd.concat(fl, ignore_index=True)
    fl['period'] = period_of(fl.entry_ms.to_numpy())
    fl = fl[fl.period != '']
    ft = trades[trades.hyp.isin(['F1', 'F2'])]
    m = ft.merge(fl, on=['hyp', 'coin', 'entry_ms'], how='outer', indicator=True, suffixes=('', '_l'))
    both = m[m._merge == 'both']
    info = {'vectorised': int(len(ft)), 'loop': int(len(fl)), 'merge': m._merge.value_counts().to_dict(),
            'loop_skips_incl_out_of_period': int(fsk),
            'dir_mismatch': int((both.direction != both.direction_l).sum()),
            'exit_mismatch': int((both.exit_ms != both.exit_ms_l).sum()),
            'max_abs_gross_diff': float((both.gross_bp - both.g).abs().max())}
    chk('V3_F1F2_independent_loop_all_coins', info['merge'].get('both', 0) == len(ft) == len(fl)
        and info['dir_mismatch'] == 0 and info['exit_mismatch'] == 0 and info['max_abs_gross_diff'] < 1e-9, info)

    # V4 independent bootstrap (all 6 rows, NORMAL and STRESS)
    worst, det = 0.0, {}
    for _, r in rows.iterrows():
        d = trades[(trades.hyp == r.hyp) & (trades.period == r.period)]
        for cost_name, cost in COST.items():
            q = indep_boot((d.gross_bp - cost).tolist(), d.entry_ms.tolist())
            key = cost_name.lower()
            mine = {0.83: r[f'bonf_lo_{key}'], 99.17: r[f'bonf_hi_{key}'], 2.5: r[f'ci95_lo_{key}'],
                    97.5: r[f'ci95_hi_{key}']}
            diff = max(abs(q[k] - mine[k]) for k in q)
            worst = max(worst, diff)
            det[f'{r.hyp}|{r.period}|{cost_name}'] = round(diff, 12)
    chk('V4_bootstrap_independent', worst < 1e-8, {'max_abs_diff_any_percentile': worst})

    # V5 trade-level invariants
    f1 = trades[trades.hyp == 'F1']
    f2 = trades[trades.hyp == 'F2']
    inv = {
        'F1_entry_T-60m_exit_T': bool(((f1.entry_ms == f1.T_ms - HOUR_MS) & (f1.exit_ms == f1.T_ms)).all()),
        'F2_entry_T_exit_T+60m': bool(((f2.entry_ms == f2.T_ms) & (f2.exit_ms == f2.T_ms + HOUR_MS)).all()),
        'F1_dir=-sign(f_prev)': bool((f1.direction == -np.sign(f1.f_prev)).all()),
        'F2_dir=+sign(f_prev)': bool((f2.direction == np.sign(f2.f_prev)).all()),
        'F_abs_fprev>=thr': bool((trades[trades.hyp != 'C1'].f_prev.abs() >= F_THR).all()),
        'T_on_00_08_16_UTC': bool(set(((trades[trades.hyp != 'C1'].T_ms % 86_400_000) // HOUR_MS).astype(int))
                                  <= {0, 8, 16}),
        'C1_entry=signal+5m': bool((c1.entry_ms == c1.signal_ms + BAR_MS).all()),
        'C1_time_exit=entry+60m': bool((c1[c1.exit_type == 'time'].exit_ms == c1[c1.exit_type == 'time'].entry_ms
                                        + 12 * BAR_MS).all()),
        'C1_stop_exit<=entry+55m': bool((c1[c1.exit_type != 'time'].exit_ms - c1[c1.exit_type != 'time'].entry_ms
                                         <= 11 * BAR_MS).all()),
        'C1_no_overlap': bool(all((g.signal_ms.to_numpy()[1:] >= g.exit_ms.to_numpy()[:-1]).all()
                                  for _, g in c1.sort_values('entry_ms').groupby('coin'))),
        'C1_stop_exit_px_eq_stop': bool(np.allclose(c1[c1.exit_type == 'stop'].exit_px,
                                                    c1[c1.exit_type == 'stop'].stop_px, rtol=0, atol=0)),
        'short_formula': bool(np.allclose(trades[trades.direction < 0].gross_bp,
                                          (trades[trades.direction < 0].entry_px - trades[trades.direction < 0].exit_px)
                                          / trades[trades.direction < 0].entry_px * 1e4, rtol=0, atol=1e-9)),
        'long_formula': bool(np.allclose(trades[trades.direction > 0].gross_bp,
                                         (trades[trades.direction > 0].exit_px / trades[trades.direction > 0].entry_px
                                          - 1) * 1e4, rtol=0, atol=1e-9)),
        'net=gross-cost': bool(np.allclose(trades.net_normal_bp, trades.gross_bp - 10)
                               and np.allclose(trades.net_stress_bp, trades.gross_bp - 21)),
        'period_by_entry': bool((trades.period == period_of(trades.entry_ms.to_numpy())).all()),
        'C1_vmed20>0': bool((c1.vmed20 > 0).all()),
    }
    chk('V5_trade_invariants', all(inv.values()), inv)

    # V6 FIX CHECK: no main-run C1 trade uses a maintenance filler bar anywhere in bars [i-21, exit]
    touch = 0
    for coin, g in c1.groupby('coin'):
        b = load_bars(coin, synthetic_missing=False)
        syn = b.synth.to_numpy()
        cs = np.r_[0, np.cumsum(syn)]
        lo_ = g.sig_idx.to_numpy().astype(np.int64) - C1_WIN - 1
        hi_ = g.exit_idx.to_numpy().astype(np.int64)
        touch += int(((cs[hi_ + 1] - cs[np.maximum(lo_, 0)]) > 0).sum())
    chk('V6_fix_no_trade_touches_filler_bar', touch == 0, {'main_trades_touching_filler': touch})

    # V7 FIX CHECK: variant (fillers treated as real) reproduces implementation B exactly; the extra trades are
    # exactly the filler-contaminated ones
    cv = trades_var[trades_var.hyp == 'C1']
    m = cv.merge(c1[['coin', 'entry_ms']], on=['coin', 'entry_ms'], how='left', indicator=True)
    extra = m[m._merge == 'left_only']
    ext_touch = 0
    for coin, g in extra.groupby('coin'):
        b = load_bars(coin, synthetic_missing=False)
        syn = b.synth.to_numpy()
        cs = np.r_[0, np.cumsum(syn)]
        xi = g.exit_idx.to_numpy().astype(np.int64)
        si = g.sig_idx.to_numpy().astype(np.int64)
        ext_touch += int(((cs[xi + 1] - cs[np.maximum(si - C1_WIN - 1, 0)]) > 0).sum())
    missing_in_var = int(len(c1.merge(cv[['coin', 'entry_ms']], on=['coin', 'entry_ms'], how='left',
                                      indicator=True).query('_merge=="left_only"')))
    info = {'variant_C1_n_KESIF': int((cv.period == 'KESIF').sum()),
            'variant_C1_n_DOGRULAMA': int((cv.period == 'DOGRULAMA').sum()),
            'extra_trades_vs_main': int(len(extra)), 'extra_touching_filler': ext_touch,
            'extra_with_vmed20_eq_0': int((extra.vmed20 == 0).sum()),
            'extra_mean_gross_bp': float(extra.gross_bp.mean()), 'main_trades_absent_in_variant': missing_in_var}
    if REF_B.exists():
        b = pd.read_csv(REF_B)
        b['direction'] = np.where(b.side == 'L', 1, -1)
        mb = trades_var.merge(b, on=['hyp', 'coin', 'entry_ms'], how='outer', indicator=True, suffixes=('', '_b'))
        bb = mb[mb._merge == 'both']
        info['vs_B_merge'] = mb._merge.value_counts().to_dict()
        info['vs_B_max_abs_gross_diff'] = float((bb.gross_bp - bb.gross).abs().max())
        info['vs_B_dir_or_exit_mismatch'] = int(((bb.direction != bb.direction_b) | (bb.exit_ms != bb.exit_ms_b)).sum())
    chk('V7_fix_variant_reproduces_B_and_explains_diff', info['extra_trades_vs_main'] == 43 and ext_touch == 43
        and missing_in_var == 0 and info.get('vs_B_merge', {}).get('both', -1) == len(trades_var)
        and info.get('vs_B_dir_or_exit_mismatch', 1) == 0, info)

    # V8 main run reproduces implementation A exactly
    if REF_A.exists():
        a = pd.read_csv(REF_A)
        ma = trades.merge(a, on=['hyp', 'coin', 'entry_ms'], how='outer', indicator=True, suffixes=('', '_a'))
        aa = ma[ma._merge == 'both']
        info = {'merge': ma._merge.value_counts().to_dict(),
                'max_abs_gross_diff': float((aa.gross_bp - aa.gross_bp_a).abs().max()),
                'dir_or_exit_mismatch': int(((aa.direction != aa.direction_a) | (aa.exit_ms != aa.exit_ms_a)).sum())}
        chk('V8_main_reproduces_A', info['merge'].get('both', 0) == len(trades) == len(a)
            and info['dir_or_exit_mismatch'] == 0 and info['max_abs_gross_diff'] < 1e-9, info)
    return V, ok_all


# =============================================================================================== main

def fmt(df, f='{:.2f}'):
    return df.to_string(float_format=lambda x: f.format(x))


def main():
    t_start = time.time()
    trades, skips, c1_info, fund, oor = run(synthetic_missing=True)
    rows = summarize(trades, skips)
    verd, verd_detail = verdicts(rows)

    trades_v, skips_v, c1_info_v, _, _ = run(synthetic_missing=False)
    rows_v = summarize(trades_v, skips_v)
    verd_v, _ = verdicts(rows_v)

    # --------------- pre-registered breakdowns: per year, per coin, long/short
    py = trades.groupby(['hyp', 'year']).gross_bp.agg(['count', 'mean']).unstack('hyp')
    pc = trades.groupby(['hyp', 'period', 'coin']).gross_bp.mean().unstack('coin').reindex(columns=COINS)
    pcn = trades.groupby(['hyp', 'period', 'coin']).gross_bp.size().unstack('coin').reindex(columns=COINS)
    ls = trades.groupby(['hyp', 'period', 'side']).gross_bp.agg(['count', 'mean', 'median'])
    c1x = trades[trades.hyp == 'C1'].groupby(['period', 'exit_type']).gross_bp.agg(['count', 'mean'])

    fd = fund[fund.f_prev.notna()].copy()
    fd['period'] = period_of(fd['T'].to_numpy())
    fd['exc'] = fd.f_prev.abs() >= F_THR
    exc = fd[fd.exc].groupby(['coin', 'period']).size().unstack('period').reindex(COINS)

    # --------------- NOT pre-registered sensitivity (C1 interpretation), for transparency only
    sens = []
    for label, kw in (('Wilder ATR', {'atr_mode': 'wilder'}), ('ATR/median include signal bar',
                                                                 {'include_current': True}),
                      ('re-entry allowed at exit-bar open', {'reentry_same_bar': True})):
        parts = [c1_trades(c, load_bars(c, True), **kw)[0] for c in COINS]
        t_ = pd.concat(parts, ignore_index=True)
        t_['period'] = period_of(t_.entry_ms.to_numpy())
        for per in PERIODS:
            dd = t_[t_.period == per]
            cm = dd.groupby('coin').gross_bp.mean().reindex(COINS)
            sens.append({'variant': label, 'period': per, 'n': len(dd), 'gross_bp': dd.gross_bp.mean(),
                         'coins_pos_normal': int(((cm - COST['NORMAL']) > 0).sum())})
    sens = pd.DataFrame(sens).set_index(['variant', 'period'])

    t_calc = time.time() - t_start
    V, ok_all = verify(trades, rows, trades_v, rows_v, verd)
    t_total = time.time() - t_start

    # --------------- persist
    OUT.mkdir(parents=True, exist_ok=True)
    keep = ['hyp', 'coin', 'period', 'year', 'week', 'side', 'direction', 'signal_ms', 'entry_ms', 'exit_ms', 'T_ms',
            'f_prev', 'entry_px', 'exit_px', 'stop_px', 'atr20', 'gross_bp', 'net_normal_bp', 'net_stress_bp',
            'exit_type']
    trades[keep].to_csv(OUT / 'trades.csv', index=False)
    rows.to_csv(OUT / 'rows.csv', index=False)
    rows_v.to_csv(OUT / 'rows_variant_fillers_as_real.csv', index=False)

    cols = ['hyp', 'period', 'n', 'skipped', 'gross_bp', 'net_normal_bp', 'net_stress_bp', 'bonf_lo_normal',
            'bonf_hi_normal', 'ci95_lo_normal', 'ci95_hi_normal', 'coins_pos_normal', 'n_weeks']
    L = []
    P = L.append
    P('=== GUN ICI v1 -- FINAL (pre-registered spec; maintenance filler bars = missing) ===')
    P(fmt(rows[cols], '{:.3f}'))
    P('\nSTRESS bootstrap (net, ratio-of-sums): 0.83 / 99.17 / 2.5 / 97.5')
    P(fmt(rows[['hyp', 'period', 'bonf_lo_stress', 'bonf_hi_stress', 'ci95_lo_stress', 'ci95_hi_stress',
                'coins_pos_stress']], '{:.3f}'))
    P('\nVERDICTS: ' + json.dumps(verd))
    P(json.dumps(verd_detail, indent=1))
    P(f'\ntrades outside periods dropped: {oor}')
    P('\n--- per-year gross bp (count, mean; year of entry) ---')
    P(fmt(py))
    P('\n--- per-coin gross bp ---')
    P(fmt(pc))
    P('\n--- per-coin n ---')
    P(pcn.to_string())
    P('\n--- long / short gross bp ---')
    P(fmt(ls))
    P('\n--- C1 exit types ---')
    P(fmt(c1x))
    P('\n--- C1 candidate accounting (main) ---')
    P(pd.DataFrame(c1_info).T.to_string())
    P('\n--- |f_prev| >= 3bp exceedances by coin x period (settlement T) ---')
    P(exc.to_string())
    P('\n--- C1 sensitivity (NOT pre-registered; main spec = SMA ATR, past-only, re-entry from exit bar) ---')
    P(fmt(sens))
    P('\n=== VARIANT (diagnostic only): filler bars treated as real == implementation B ===')
    P(fmt(rows_v[cols], '{:.3f}'))
    P('VERDICTS variant: ' + json.dumps(verd_v))
    P('\n=== VERIFICATION ===')
    for k, v in V.items():
        P(f"{'PASS' if v['pass'] else 'FAIL'}  {k}: {json.dumps(v['info'], default=str)}")
    P(f'ALL VERIFICATION PASSED: {ok_all}   (calc {t_calc:.1f}s, total {t_total:.1f}s)')
    txt = '\n'.join(L)
    (OUT / 'report.txt').write_text(txt)
    print(txt)

    res = {'rows': json.loads(rows.to_json(orient='records')), 'verdicts': verd, 'verdict_detail': verd_detail,
           'variant_rows_fillers_as_real': json.loads(rows_v.to_json(orient='records')),
           'variant_verdicts': verd_v, 'verification': V, 'verification_all_pass': ok_all,
           'c1_info': c1_info, 'c1_info_variant': c1_info_v}
    (OUT / 'results.json').write_text(json.dumps(res, indent=1, default=str))
    return 0 if ok_all else 1


if __name__ == '__main__':
    sys.exit(main())
