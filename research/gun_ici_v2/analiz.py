#!/usr/bin/env python3
"""Gun ici v2 -- FINAL implementation of /home/user/sweep/research/gun_ici_v2/ON_KAYIT.md (pre-registration).

Limit-only (maker) mean reversion on 1h SMA20 +/- k*std20 bands, executed on Binance 5m bars.

Pre-registered and NOT changed: k = 2.5 (M1) / 3.0 (M2); fill / TP queue buffer 0.0002; TP = SMA20 at entry
(resting limit, filled only when the 5m range passes TP by the buffer, at the TP price); stop = entry -/+ 2*ATR14(1h)
at entry (touch -> stop price, open beyond -> open); stop wins over TP in the same 5m bar; 24 h time limit -> market
exit at the next 5m open; TP/stop/time checked only from the 5m bar AFTER the entry bar; costs (entry and TP 0;
stop and time exits NORMAL 5.5 bp, STRESS 12.5 bp); periods KESIF 2023-01-01..2024-12-31, DOGRULAMA
2025-01-01..2026-09-30 by entry time; weekly (ISO week of entry, UTC) block bootstrap, 10 000 reps, seed 20261018,
ratio of sums, Bonferroni lower = 1.25 percentile (2 variants); the 4-part KAZANDI criterion.

Conventions where the pre-registration is silent (MAIN spec):
  data    gap-free 5m grid (asserted). The 24 zero-volume flat outage bars (volume == 0 and o == h == l == c;
          2023-09-12, 2024-10-28, 2025-01-29, 2025-08-29; identical in all 12 coins, asserted) are MISSING:
          no fill and no exit on them and they are not used for 1h bars.
  1h bars [H, H+1h) from the real 5m bars of that hour (O first, H max, L min, C last). An hour with 0 real bars
          does not exist in the 1h series. An hour with 1..11 real bars is a bar of the series (it enters later
          rolling windows) but the indicators computed at ITS close are unavailable -> no orders in [H+1h, H+2h).
  indic.  known at H+1h from 1h bars closed at or before H+1h:
          SMA20 = mean of the last 20 closes;
          std20 = SAMPLE std (ddof = 1) of the same 20 closes -- house band convention: Bot2 indicators.bollinger_bands
                  (pandas rolling std) and research/kalabalik_v1 zskor;
          ATR14 = Wilder, seeded with the first TR: TR[0] = H-L, TR[i] = max(H-L, |H-Cprev|, |L-Cprev|) with Cprev the
                  previous bar of the 1h series, ATR[0] = TR[0], ATR[i] = TR[i]*(1/14) + ATR[i-1]*(1-1/14) -- house
                  ATR14 contract: research/liquidity_sweep_v1/indicators_adapter.py ("sartname s4"), Bot2
                  indicators.atr, research/trend_gelistirme/motor.atr_wilder.
          available iff the bar has 12 real 5m bars, the series has >= 20 bars, std20 > 0 and ATR14 > 0.
  orders  flat and allowed -> BUY = SMA20 - k*std20 and SELL = SMA20 + k*std20 rest during [H+1h, H+2h) only,
          checked on its real 5m bars in time order: low <= BUY*(1-0.0002) -> long at BUY, high >= SELL*(1+0.0002)
          -> short at SELL (level price also when the open is already beyond it). Both in the same 5m bar -> no trade
          and both orders are consumed (both would have executed) -> nothing rests for the rest of that hour.
  exits   from the next 5m bar, real bars only, in this order per bar:
          (1) time: the fill happens somewhere inside the entry bar [t_e, t_e+5m), so 24 h are certainly complete at
              t_e + 5m + 24h -> market exit at the OPEN of the first real bar with open_time >= t_e + 289*5m;
          (2) stop: long open <= stop -> open ('stop_gap'), else low <= stop -> stop price ('stop'); short mirrored;
          (3) TP: long high >= TP*(1+0.0002), short low <= TP*(1-0.0002) -> TP price ('tp').
  state   one position per coin and variant; no orders while in a position; after an exit in the 5m bar with open
          time t_x the next orders rest from floor_hour(t_x) + 1h. A position still open when the data end is
          dropped (counted). M1 and M2 are simulated independently.
  returns long (exit-entry)/entry*1e4, short (entry-exit)/entry*1e4; cost only for stop / stop_gap / time exits.
  stats   period, year and ISO week from the entry 5m bar's open time (UTC). Bootstrap per (variant, period):
          the ISO weeks containing trades (pooled over coins) are resampled with replacement, statistic =
          sum(net) / count over the resampled weeks; numpy default_rng(20261018) freshly seeded per call,
          idx = rng.integers(0, W, size=(10000, W)), np.percentile (linear). A coin without a trade is not positive.

A/B discrepancy (verified in this script by reproducing BOTH implementations trade by trade):
  The two implementations contain no logic error; they differ only in three unspecified conventions:
    A: std ddof=1, ATR14 = simple 14-mean of TR,        ambiguous bar -> orders keep resting in that hour
    B: std ddof=0, ATR14 = Wilder (house contract),      ambiguous bar -> hour finished
  The FINAL main spec takes the house convention for each: std20 ddof=1 (as A; Bot2 bollinger_bands) and
  ATR14 Wilder (as B; the explicit ATR14 contract of the data's own research package and of Bot2). The ambiguous
  rule follows B (both limit orders would have executed -> nothing can fill later in that hour); it changes 1 trade.
  All convention variants are re-run as NOT pre-registered sensitivities; the verdict uses the MAIN spec only.

Two independent engines run the MAIN spec and must agree trade by trade:
  ENGINE 1: numpy (grid-indexed hourly aggregation, vectorised fill masks, jump state machine, vectorised exit scan)
  ENGINE 2: pure Python (dict-keyed hourly aggregation from real bars, statistics.stdev, bar-by-bar state loop)

Run:  python3 -I analiz.py
Outputs (only into OUT): trades_final.csv, rows_final.csv, results_final.json, report_final.txt
"""
import csv
import datetime
import json
import math
import statistics
import time

import numpy as np

DATA = '/home/user/sweep/research_data/liquidity_sweep_v1/veri/binance_5m'
OUT = '/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/gun_ici2_final'
REF_A = '/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/gun_ici2_A/islemler_A.csv'
REF_B = '/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/gun_ici2_B/trades_B.csv'
COINS = 'SOL ETH ADA NEAR BCH XRP DOGE TRX XLM LTC ICP BNB'.split()
VARIANTS = ('M1', 'M2')
K_BAND = {'M1': 2.5, 'M2': 3.0}
BUF = 0.0002
K_STOP = 2.0
N_SMA, N_ATR = 20, 14
BAR_MS, HOUR_MS, BPH = 300_000, 3_600_000, 12
TIME_BARS = 289
COST = {'NORMAL': 5.5, 'STRESS': 12.5}
N_BOOT, SEED = 10_000, 20261018
Q_BONF = (1.25, 98.75)
Q_95 = (2.5, 97.5)
PERIOD_NAMES = ('KESIF', 'DOGRULAMA')


def utc_ms(y, m, d):
    return int(datetime.datetime(y, m, d, tzinfo=datetime.timezone.utc).timestamp() * 1000)


PERIODS = (('KESIF', utc_ms(2023, 1, 1), utc_ms(2025, 1, 1)), ('DOGRULAMA', utc_ms(2025, 1, 1), utc_ms(2026, 10, 1)))

MAIN = {'ddof': 1, 'atr': 'wilder', 'amb': 'stop_hour', 'time_bars': TIME_BARS, 'block_incomplete': False}
CONV_A = {'ddof': 1, 'atr': 'sma', 'amb': 'continue', 'time_bars': TIME_BARS, 'block_incomplete': False}
CONV_B = {'ddof': 0, 'atr': 'wilder', 'amb': 'stop_hour', 'time_bars': TIME_BARS, 'block_incomplete': False}


def period_of(t):
    for name, a, b in PERIODS:
        if a <= t < b:
            return name
    return ''


def dt(t):
    return datetime.datetime.fromtimestamp(t / 1000, tz=datetime.timezone.utc)


def utc_str(t):
    return dt(t).strftime('%Y-%m-%d %H:%M')


def iso_week(t):
    y, w, _ = dt(t).isocalendar()
    return y * 100 + w


# ============================================================================================================ data
def load_coin(coin):
    d = np.load(f'{DATA}/{coin}.npz')
    t = d['open_time_ms'].astype(np.int64)
    o, h, lo, c, v = (d[k].astype(np.float64) for k in ('open', 'high', 'low', 'close', 'volume'))
    n = len(t)
    assert np.all(np.diff(t) == BAR_MS), coin
    assert t[0] % HOUR_MS == 0 and n % BPH == 0, coin
    assert t[0] == PERIODS[0][1] and t[-1] == PERIODS[1][2] - BAR_MS, coin
    outage = (v == 0) & (o == h) & (h == lo) & (lo == c)
    real = ~outage
    assert np.all(v[real] > 0), coin
    assert np.all(lo[real] <= np.minimum(o[real], c[real])) and np.all(h[real] >= np.maximum(o[real], c[real])), coin
    return {'coin': coin, 't': t, 'o': o, 'h': h, 'l': lo, 'c': c, 'real': real, 'n': n, 'outage_ts': t[outage]}


# ============================================================================================================ ENGINE 1
def hourly(D):
    n, nh = D['n'], D['n'] // BPH
    R = D['real'].reshape(nh, BPH)
    n_real = R.sum(axis=1)
    H = np.where(R, D['h'].reshape(nh, BPH), -np.inf).max(axis=1)
    L = np.where(R, D['l'].reshape(nh, BPH), np.inf).min(axis=1)
    last = BPH - 1 - np.argmax(R[:, ::-1], axis=1)
    C = D['c'].reshape(nh, BPH)[np.arange(nh), last]
    return {'nh': nh, 'n_real': n_real, 'H': H, 'L': L, 'C': C, 'exists': n_real > 0}


def indicators(hr, ddof, atr_mode):
    nh = hr['nh']
    s = np.flatnonzero(hr['exists'])
    Hs, Ls, Cs = hr['H'][s], hr['L'][s], hr['C'][s]
    m = len(s)
    sma = np.full(m, np.nan)
    sd = np.full(m, np.nan)
    W = np.lib.stride_tricks.sliding_window_view(Cs, N_SMA)
    sma[N_SMA - 1:] = W.mean(axis=1)
    sd[N_SMA - 1:] = W.std(axis=1, ddof=ddof)
    cp = np.r_[np.nan, Cs[:-1]]
    tr = np.fmax(np.fmax(Hs - Ls, np.abs(Hs - cp)), np.abs(Ls - cp))     # first bar: H-L (NaN skipped)
    atr = np.full(m, np.nan)
    if atr_mode == 'wilder':
        k = 1.0 / N_ATR
        prev = None
        for i in range(m):
            prev = tr[i] if prev is None else tr[i] * k + prev * (1 - k)
            atr[i] = prev
    else:                                    # simple mean of the last 14 TRs that have a previous close
        for i in range(N_ATR, m):
            atr[i] = tr[i - N_ATR + 1:i + 1].mean()
    out = {}
    for name, arr in (('sma', sma), ('sd', sd), ('atr', atr)):
        a = np.full(nh, np.nan)
        a[s] = arr
        out[name] = a
    with np.errstate(invalid='ignore'):
        out['avail'] = (hr['n_real'] == BPH) & np.isfinite(out['sma']) & np.isfinite(out['sd']) & \
            np.isfinite(out['atr']) & (out['sd'] > 0) & (out['atr'] > 0)
    return out


def simulate(D, hr, ind, var, conv):
    t, o, h, lo, real, n = D['t'], D['o'], D['h'], D['l'], D['real'], D['n']
    nh = hr['nh']
    kb = K_BAND[var]
    ok_h = np.zeros(nh, dtype=bool)
    ok_h[1:] = ind['avail'][:-1]                         # orders in hour k use the indicators of hour k-1
    if conv['block_incomplete']:
        ok_h &= hr['n_real'] == BPH
    sma_o = np.r_[np.nan, ind['sma'][:-1]]
    sd_o = np.r_[np.nan, ind['sd'][:-1]]
    atr_o = np.r_[np.nan, ind['atr'][:-1]]
    buy_h = sma_o - kb * sd_o
    sell_h = sma_o + kb * sd_o
    hb = np.arange(n) // BPH
    okb = ok_h[hb] & real
    with np.errstate(invalid='ignore'):
        lh = okb & (lo <= (buy_h * (1 - BUF))[hb])
        sh = okb & (h >= (sell_h * (1 + BUF))[hb])
    cand = np.flatnonzero(lh | sh)
    real_idx = np.flatnonzero(real)
    oh_mask = ok_h & (hr['n_real'] > 0)
    cum = np.r_[0, np.cumsum(oh_mask)]
    st = {'order_hours': {p: 0 for p in PERIOD_NAMES}, 'fills': {p: 0 for p in PERIOD_NAMES}, 'ambiguous': 0,
          'open_at_end': 0, 'oh_by_utc': np.zeros(24, dtype=np.int64), 'fill_by_utc': np.zeros(24, dtype=np.int64)}
    hour_t = t[::BPH]
    hour_utc = (hour_t // HOUR_MS) % 24
    hour_per = np.where(hour_t < PERIODS[0][2], 0, 1)

    def count_oh(a, b):                                   # order hours in [a, b)
        if b <= a:
            return
        sel = np.flatnonzero(oh_mask[a:b]) + a
        np.add.at(st['oh_by_utc'], hour_utc[sel], 1)
        for pi, pn in enumerate(PERIOD_NAMES):
            st['order_hours'][pn] += int(np.sum(hour_per[sel] == pi))

    trades = []
    i0 = BPH                                              # hour 0 has no previous 1h bar
    acc = 1
    while True:
        p = int(np.searchsorted(cand, i0))
        if p >= len(cand):
            count_oh(acc, nh)
            break
        j = int(cand[p])
        kh = j // BPH
        if lh[j] and sh[j]:
            st['ambiguous'] += 1
            i0 = (kh + 1) * BPH if conv['amb'] == 'stop_hour' else j + 1
            continue
        side = 1 if lh[j] else -1
        count_oh(acc, kh + 1)
        st['fills'][PERIOD_NAMES[hour_per[kh]]] += 1
        st['fill_by_utc'][hour_utc[kh]] += 1
        sma, sd, atr = sma_o[kh], sd_o[kh], atr_o[kh]
        entry = buy_h[kh] if side == 1 else sell_h[kh]
        tp = sma
        stop = entry - side * K_STOP * atr
        lim = j + conv['time_bars']
        q = int(np.searchsorted(real_idx, lim))
        kd = int(real_idx[q]) if q < len(real_idx) else n
        seg = slice(j + 1, min(lim, n))
        rs = real[seg]
        if side == 1:
            s_hit = rs & (lo[seg] <= stop)
            t_hit = rs & (h[seg] >= tp * (1 + BUF))
        else:
            s_hit = rs & (h[seg] >= stop)
            t_hit = rs & (lo[seg] <= tp * (1 - BUF))
        ev = s_hit | t_hit
        if ev.any():
            f = int(np.argmax(ev))
            x = j + 1 + f
            if s_hit[f]:
                gap = (o[x] <= stop) if side == 1 else (o[x] >= stop)
                xp, typ = (o[x], 'stop_gap') if gap else (stop, 'stop')
            else:
                xp, typ = tp, 'tp'
        elif kd < n:
            x, xp, typ = kd, o[kd], 'time'
        else:
            st['open_at_end'] += 1
            break
        gross = side * (xp - entry) / entry * 1e4
        cost = 0.0 if typ == 'tp' else 1.0
        trades.append({
            'variant': var, 'coin': D['coin'], 'side': side, 'order_hour_ms': int(t[kh * BPH]),
            'entry_ms': int(t[j]), 'exit_ms': int(t[x]), 'entry_px': float(entry), 'exit_px': float(xp),
            'sma20': float(sma), 'std20': float(sd), 'atr14': float(atr), 'tp_px': float(tp), 'stop_px': float(stop),
            'exit_type': typ, 'hold_bars': x - j, 'entry_bar_in_hour': j - kh * BPH,
            'entry_open_beyond': int(o[j] <= entry) if side == 1 else int(o[j] >= entry),
            'gross_bp': float(gross), 'net_normal_bp': float(gross - COST['NORMAL'] * cost),
            'net_stress_bp': float(gross - COST['STRESS'] * cost), 'period': period_of(int(t[j])),
            'year': dt(int(t[j])).year, 'iso_week': iso_week(int(t[j])), 'entry_idx': j, 'exit_idx': x})
        i0 = (x // BPH + 1) * BPH
        acc = x // BPH + 1
        if i0 >= n:
            break
    return trades, st


def run_engine1(datas, conv):
    trades, stats = [], {}
    for coin in COINS:
        D = datas[coin]
        hr = hourly(D)
        ind = indicators(hr, conv['ddof'], conv['atr'])
        for var in VARIANTS:
            tr, st = simulate(D, hr, ind, var, conv)
            trades += tr
            stats[(var, coin)] = st
    assert all(x['period'] for x in trades)
    return trades, stats


# ============================================================================================================ ENGINE 2
def ref_coin(D, conv):
    """Pure-Python reference, independent of the grid indexing used by engine 1."""
    t, o, h, lo, c, real = (D[k].tolist() for k in ('t', 'o', 'h', 'l', 'c', 'real'))
    bars, order = {}, []
    for i in range(len(t)):
        if not real[i]:
            continue
        H = t[i] // HOUR_MS
        b = bars.get(H)
        if b is None:
            bars[H] = [h[i], lo[i], c[i], 1]
            order.append(H)
        else:
            b[0] = max(b[0], h[i])
            b[1] = min(b[1], lo[i])
            b[2] = c[i]
            b[3] += 1
    closes, trs = [], []
    atr_w = None
    levels = {}
    for H in order:
        bh, bl, bc, cnt = bars[H]
        if closes:
            pc = closes[-1]
            tr = max(bh - bl, abs(bh - pc), abs(bl - pc))
            trs.append(tr)
        else:
            tr = bh - bl
        atr_w = tr if atr_w is None else tr * (1.0 / N_ATR) + atr_w * (1 - 1.0 / N_ATR)
        closes.append(bc)
        if cnt < BPH or len(closes) < N_SMA:
            continue
        w = closes[-N_SMA:]
        mu = math.fsum(w) / N_SMA
        sd = statistics.stdev(w) if conv['ddof'] == 1 else statistics.pstdev(w)
        if conv['atr'] == 'wilder':
            a = atr_w
        else:
            if len(trs) < N_ATR:
                continue
            a = math.fsum(trs[-N_ATR:]) / N_ATR
        if sd > 0 and a > 0:
            levels[H + 1] = (mu, sd, a)
    out = {}
    for var in VARIANTS:
        kb = K_BAND[var]
        res = []
        pos = 0
        next_hour = -1
        dead_hour = None
        for m in range(len(t)):
            if not real[m]:
                continue
            H = t[m] // HOUR_MS
            if pos == 0:
                if H < next_hour or H == dead_hour:
                    continue
                if conv['block_incomplete'] and bars[H][3] < BPH:
                    continue
                lv = levels.get(H)
                if lv is None:
                    continue
                mu, sd, a = lv
                buy, sell = mu - kb * sd, mu + kb * sd
                lo_hit = lo[m] <= buy * (1 - BUF)
                hi_hit = h[m] >= sell * (1 + BUF)
                if lo_hit and hi_hit:
                    if conv['amb'] == 'stop_hour':
                        dead_hour = H
                    continue
                if not (lo_hit or hi_hit):
                    continue
                pos = 1 if lo_hit else -1
                e = buy if pos == 1 else sell
                tp, stp = mu, e - pos * K_STOP * a
                te = t[m]
                continue
            if t[m] >= te + conv['time_bars'] * BAR_MS:
                xp, ty = o[m], 'time'
            elif pos == 1 and lo[m] <= stp:
                xp, ty = (o[m], 'stop_gap') if o[m] <= stp else (stp, 'stop')
            elif pos == -1 and h[m] >= stp:
                xp, ty = (o[m], 'stop_gap') if o[m] >= stp else (stp, 'stop')
            elif (pos == 1 and h[m] >= tp * (1 + BUF)) or (pos == -1 and lo[m] <= tp * (1 - BUF)):
                xp, ty = tp, 'tp'
            else:
                continue
            res.append((te, t[m], pos, e, xp, ty))
            pos = 0
            next_hour = H + 1
        out[var] = res
    return out


# ============================================================================================================ stats
def boot(values, weeks):
    wk, inv = np.unique(np.asarray(weeks), return_inverse=True)
    s = np.bincount(inv, weights=np.asarray(values, dtype=np.float64))
    m = np.bincount(inv).astype(np.float64)
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(wk), size=(N_BOOT, len(wk)))
    stat = s[idx].sum(axis=1) / m[idx].sum(axis=1)
    q = np.percentile(stat, [Q_BONF[0], Q_BONF[1], Q_95[0], Q_95[1]])
    return {'lo125': float(q[0]), 'hi9875': float(q[1]), 'lo25': float(q[2]), 'hi975': float(q[3]), 'n_weeks': len(wk)}


def mean(xs):
    return float(np.mean(xs)) if len(xs) else float('nan')


def summarize(trades, with_boot=True):
    rows = []
    for var in VARIANTS:
        for per in PERIOD_NAMES:
            d = [x for x in trades if x['variant'] == var and x['period'] == per]
            r = {'variant': var, 'period': per, 'n': len(d)}
            nn = [x['net_normal_bp'] for x in d]
            ns = [x['net_stress_bp'] for x in d]
            wk = [x['iso_week'] for x in d]
            r['gross_bp'] = mean([x['gross_bp'] for x in d])
            r['net_normal_bp'] = mean(nn)
            r['net_stress_bp'] = mean(ns)
            if with_boot and d:
                bn, bs = boot(nn, wk), boot(ns, wk)
                r.update({'bonf_lo_normal': bn['lo125'], 'bonf_hi_normal': bn['hi9875'], 'ci95_lo_normal': bn['lo25'],
                          'ci95_hi_normal': bn['hi975'], 'bonf_lo_stress': bs['lo125'], 'bonf_hi_stress': bs['hi9875'],
                          'ci95_lo_stress': bs['lo25'], 'ci95_hi_stress': bs['hi975'], 'n_weeks': bn['n_weeks']})
            pn = ps = 0
            for coin in COINS:
                dc = [x for x in d if x['coin'] == coin]
                if dc and mean([x['net_normal_bp'] for x in dc]) > 0:
                    pn += 1
                if dc and mean([x['net_stress_bp'] for x in dc]) > 0:
                    ps += 1
            r['coins_pos_normal'] = pn
            r['coins_pos_stress'] = ps
            ty = [x['exit_type'] for x in d]
            nd = max(len(d), 1)
            r['tp_share'] = ty.count('tp') / nd
            r['stop_share'] = (ty.count('stop') + ty.count('stop_gap')) / nd
            r['stop_gap_share'] = ty.count('stop_gap') / nd
            r['time_share'] = ty.count('time') / nd
            r['long_n'] = sum(1 for x in d if x['side'] == 1)
            r['short_n'] = sum(1 for x in d if x['side'] == -1)
            rows.append(r)
    return rows


def verdicts(rows):
    out, det = {}, {}
    for var in VARIANTS:
        k = next(r for r in rows if r['variant'] == var and r['period'] == 'KESIF')
        d = next(r for r in rows if r['variant'] == var and r['period'] == 'DOGRULAMA')
        c = {'1_stress_mean_pos_kesif_and_dogrulama': bool(k['n'] > 0 and d['n'] > 0 and k['net_stress_bp'] > 0
                                                           and d['net_stress_bp'] > 0),
             '2_dogrulama_normal_bonf_lo_pos': bool(d['n'] > 0 and d.get('bonf_lo_normal', float('nan')) > 0),
             '3_dogrulama_coins_normal_pos_ge8': bool(d['coins_pos_normal'] >= 8),
             '4_dogrulama_n_ge300': bool(d['n'] >= 300)}
        out[var] = 'KAZANDI' if all(c.values()) else 'ELENDI'
        det[var] = c
    return out, det


def group(d, keyf):
    g = {}
    for x in d:
        g.setdefault(keyf(x), []).append(x)
    res = {}
    for k in sorted(g):
        v = g[k]
        ty = [x['exit_type'] for x in v]
        res[str(k)] = {'n': len(v), 'gross': mean([x['gross_bp'] for x in v]),
                       'net_normal': mean([x['net_normal_bp'] for x in v]),
                       'net_stress': mean([x['net_stress_bp'] for x in v]),
                       'tp': ty.count('tp') / len(v), 'stop': (ty.count('stop') + ty.count('stop_gap')) / len(v),
                       'time': ty.count('time') / len(v)}
    return res


# ============================================================================================================ checks
def compare_to_csv(trades, path, label):
    """Trade-by-trade comparison of engine-1 output against a stored implementation's trades file."""
    ref = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            side = r['side']
            side = 1 if side in ('1', 'LONG') else -1
            typ = 'stop' if r['exit_type'] == 'stop_gap' else r['exit_type']
            ref[(r['variant'], r['coin'], int(r['entry_ms']))] = (side, int(r['exit_ms']), typ, float(r['entry_px']),
                                                                   float(r['exit_px']), float(r['gross_bp']))
    mine = {(x['variant'], x['coin'], x['entry_ms']): x for x in trades}
    only_ref = set(ref) - set(mine)
    only_mine = set(mine) - set(ref)
    bad = 0
    max_rel = 0.0
    for k in set(ref) & set(mine):
        side, xm, typ, ep, xp, g = ref[k]
        x = mine[k]
        mt = 'stop' if x['exit_type'] == 'stop_gap' else x['exit_type']
        rel = max(abs(ep - x['entry_px']), abs(xp - x['exit_px'])) / ep
        max_rel = max(max_rel, rel)
        if side != x['side'] or xm != x['exit_ms'] or typ != mt or rel > 1e-8 or abs(g - x['gross_bp']) > 1e-4:
            bad += 1
    return {'label': label, 'ref_trades': len(ref), 'mine_trades': len(mine), 'only_ref': len(only_ref),
            'only_mine': len(only_mine), 'field_mismatch': bad, 'max_rel_px_diff': max_rel}


def audit(datas, trades, conv):
    """Independent per-trade re-check from raw arrays (no earlier fill in the order hour, entry condition,
    no earlier exit, exit rule, no overlap, orders only from the hour after the previous exit)."""
    by = {}
    for x in trades:
        by.setdefault((x['variant'], x['coin']), []).append(x)
    n_checked = 0
    for (var, coin), lst in by.items():
        D = datas[coin]
        t, o, h, lo, real = D['t'], D['o'], D['h'], D['l'], D['real']
        kb = K_BAND[var]
        last_x = -1
        for x in sorted(lst, key=lambda r: r['entry_ms']):
            j, xx = x['entry_idx'], x['exit_idx']
            kh = j // BPH
            assert t[kh * BPH] == x['order_hour_ms']
            assert last_x < 0 or kh >= last_x // BPH + 1
            assert real[j] and real[xx] and xx > j
            buy, sell = x['sma20'] - kb * x['std20'], x['sma20'] + kb * x['std20']
            prev = np.arange(kh * BPH, j)
            prev = prev[real[prev]]
            if conv['amb'] == 'stop_hour':
                assert not ((lo[prev] <= buy * (1 - BUF)) | (h[prev] >= sell * (1 + BUF))).any()
            else:
                assert not ((lo[prev] <= buy * (1 - BUF)) ^ (h[prev] >= sell * (1 + BUF))).any()
            lh_, sh_ = lo[j] <= buy * (1 - BUF), h[j] >= sell * (1 + BUF)
            assert lh_ != sh_ and (1 if lh_ else -1) == x['side']
            e = buy if x['side'] == 1 else sell
            assert abs(e - x['entry_px']) <= 1e-12 * e
            stop = e - x['side'] * K_STOP * x['atr14']
            tp = x['sma20']
            mid = np.arange(j + 1, xx)
            mid = mid[real[mid]]
            assert (t[mid] < t[j] + conv['time_bars'] * BAR_MS).all()
            if x['side'] == 1:
                assert not ((lo[mid] <= stop) | (h[mid] >= tp * (1 + BUF))).any()
                s_hit, t_hit, gap = lo[xx] <= stop, h[xx] >= tp * (1 + BUF), o[xx] <= stop
            else:
                assert not ((h[mid] >= stop) | (lo[mid] <= tp * (1 - BUF))).any()
                s_hit, t_hit, gap = h[xx] >= stop, lo[xx] <= tp * (1 - BUF), o[xx] >= stop
            if x['exit_type'] == 'time':
                assert t[xx] >= t[j] + conv['time_bars'] * BAR_MS and x['exit_px'] == o[xx]
                assert not real[np.arange(j + conv['time_bars'], xx)].any()
            elif x['exit_type'] == 'stop_gap':
                assert t[xx] < t[j] + conv['time_bars'] * BAR_MS and s_hit and gap and x['exit_px'] == o[xx]
            elif x['exit_type'] == 'stop':
                assert t[xx] < t[j] + conv['time_bars'] * BAR_MS and s_hit and not gap and x['exit_px'] == stop
            else:
                assert t[xx] < t[j] + conv['time_bars'] * BAR_MS and t_hit and not s_hit and x['exit_px'] == tp
            g = (x['exit_px'] - e) / e * 1e4 if x['side'] == 1 else (e - x['exit_px']) / e * 1e4
            assert abs(g - x['gross_bp']) < 1e-9
            c = 0.0 if x['exit_type'] == 'tp' else 1.0
            assert abs(x['net_normal_bp'] - (g - 5.5 * c)) < 1e-9 and abs(x['net_stress_bp'] - (g - 12.5 * c)) < 1e-9
            last_x = xx
            n_checked += 1
    return n_checked


def indicator_spot_check(datas, conv, n_checks=200):
    """Recompute indicators at random order hours straight from raw 5m arrays (lookahead + arithmetic)."""
    rng = np.random.default_rng(7)
    done = 0
    for coin in COINS:
        D = datas[coin]
        hr = hourly(D)
        ind = indicators(hr, conv['ddof'], conv['atr'])
        ks = np.flatnonzero(ind['avail'])
        for k in rng.choice(ks, size=n_checks // len(COINS), replace=False):
            k = int(k)
            # closes of the last 20 existing 1h bars ending with bar k, from raw 5m bars only up to hour k's end
            end = (k + 1) * BPH
            beg = max(0, (k - 40) * BPH)                   # >= 20 existing 1h bars (only 1 hour is fully missing)
            tt, cc, rr = D['t'][beg:end], D['c'][beg:end], D['real'][beg:end]
            hk = tt[rr] // HOUR_MS
            cl = {}
            for hh, cv in zip(hk.tolist(), cc[rr].tolist()):
                cl[hh] = cv
            seq = [cl[hh] for hh in sorted(cl)][-N_SMA:]
            assert sorted(cl)[-1] == D['t'][0] // HOUR_MS + k and len(cl) >= N_SMA
            mu = sum(seq) / N_SMA
            sd = statistics.stdev(seq) if conv['ddof'] == 1 else statistics.pstdev(seq)
            assert abs(mu - ind['sma'][k]) <= 1e-9 * abs(mu) and abs(sd - ind['sd'][k]) <= 1e-7 * sd
            done += 1
    return done


# ============================================================================================================ main
def fmt(x, nd=2):
    return 'nan' if x is None or (isinstance(x, float) and math.isnan(x)) else f'{x:+.{nd}f}'


def main():
    t0 = time.time()
    lines = []

    def P(s=''):
        print(s, flush=True)
        lines.append(s)

    datas = {c: load_coin(c) for c in COINS}
    ref_out = datas[COINS[0]]['outage_ts']
    assert len(ref_out) == 24
    for c in COINS:
        assert np.array_equal(datas[c]['outage_ts'], ref_out), c
    hr0 = hourly(datas['SOL'])
    inc = np.flatnonzero(hr0['n_real'] < BPH)
    P('Gun ici v2 -- FINAL (pre-registration /home/user/sweep/research/gun_ici_v2/ON_KAYIT.md)')
    P(f'data 2023-01-01 00:00 .. 2026-09-30 23:55, 5m grid gap-free; 24 outage bars treated as missing '
      f'({", ".join(sorted({utc_str(int(x))[:10] for x in ref_out}))}); hours with <12 real 5m bars: '
      f'{[utc_str(int(datas["SOL"]["t"][k * BPH])) + "(" + str(int(hr0["n_real"][k])) + ")" for k in inc]}')
    P(f'MAIN conventions: {MAIN}')

    # ---------------- main run (engine 1)
    trades, stats = run_engine1(datas, MAIN)
    n_aud = audit(datas, trades, MAIN)
    n_ind = indicator_spot_check(datas, MAIN)
    P(f'engine 1 trades {len(trades)}; per-trade raw-array audit OK ({n_aud} trades); indicator spot checks OK ({n_ind})')

    # ---------------- engine 2 cross-check (main spec)
    e2_total = 0
    e2_mism = 0
    e2_maxrel = 0.0
    for coin in COINS:
        ref = ref_coin(datas[coin], MAIN)
        for var in VARIANTS:
            mine = sorted([x for x in trades if x['coin'] == coin and x['variant'] == var], key=lambda r: r['entry_ms'])
            rr = ref[var]
            e2_total += len(rr)
            if len(rr) != len(mine):
                e2_mism += abs(len(rr) - len(mine)) + 1
                P(f'  ENGINE2 count mismatch {coin} {var}: {len(rr)} vs {len(mine)}')
                continue
            for (te, tx, side, e, xp, ty), x in zip(rr, mine):
                rel = max(abs(e - x['entry_px']), abs(xp - x['exit_px'])) / e
                e2_maxrel = max(e2_maxrel, rel)
                if te != x['entry_ms'] or tx != x['exit_ms'] or side != x['side'] or ty != x['exit_type'] or rel > 1e-9:
                    e2_mism += 1
    P(f'engine 2 (pure Python, independent aggregation and bar loop): trades {e2_total}, mismatches {e2_mism}, '
      f'max rel price diff {e2_maxrel:.1e}')
    assert e2_mism == 0 and e2_total == len(trades)

    # ---------------- reproduce A and B exactly (explains the A/B discrepancy)
    P('')
    P('A/B RECONCILIATION -- engine 1 re-run with each implementation\'s conventions, compared trade by trade:')
    repro = {}
    for label, conv, path in (('A', CONV_A, REF_A), ('B', CONV_B, REF_B)):
        tr_c, _ = run_engine1(datas, conv)
        audit(datas, tr_c, conv)
        cmpr = compare_to_csv(tr_c, path, label)
        rows_c = summarize(tr_c)
        repro[label] = {'conv': conv, 'compare': cmpr, 'rows': rows_c}
        P(f'  {label} {conv}: {cmpr}')
        for r in rows_c:
            P(f"     {r['variant']} {r['period']:<10} n {r['n']:>6} gross {r['gross_bp']:9.4f} netN {r['net_normal_bp']:9.4f} "
              f"netS {r['net_stress_bp']:9.4f} bonfLoN {r['bonf_lo_normal']:8.3f}")
    # attribution: one convention at a time from MAIN
    P('  attribution (one convention changed from MAIN at a time):')
    sens = {}
    for name, ch in (('std ddof=0 (B)', {'ddof': 0}), ('ATR14 simple 14-mean (A)', {'atr': 'sma'}),
                     ('ambiguous bar -> orders keep resting (A)', {'amb': 'continue'}),
                     ('no orders during an incomplete hour itself too', {'block_incomplete': True}),
                     ('time exit at first bar >= entry bar open + 24h (288 bars)', {'time_bars': 288})):
        conv = dict(MAIN, **ch)
        tr_s, _ = run_engine1(datas, conv)
        rs = summarize(tr_s)
        vs, _ = verdicts(rs)
        km = {(x['variant'], x['coin'], x['entry_ms']) for x in trades}
        ks = {(x['variant'], x['coin'], x['entry_ms']) for x in tr_s}
        sens[name] = {'conv': conv, 'rows': rs, 'verdicts': vs, 'only_main': len(km - ks), 'only_alt': len(ks - km)}
        P(f'   - {name}: verdicts {vs}; trades only in MAIN {len(km - ks)}, only in alt {len(ks - km)}')
        for r in rs:
            P(f"       {r['variant']} {r['period']:<10} n {r['n']:>6} netN {fmt(r['net_normal_bp'])} "
              f"bonfLoN {fmt(r['bonf_lo_normal'])} netS {fmt(r['net_stress_bp'])} +coinN {r['coins_pos_normal']}/12")
    for label in ('A', 'B'):
        vs, _ = verdicts(repro[label]['rows'])
        sens[f'implementation {label} conventions'] = {'conv': repro[label]['conv'], 'rows': repro[label]['rows'],
                                                       'verdicts': vs}

    # ---------------- main table
    rows = summarize(trades)
    verd, vdet = verdicts(rows)
    P('')
    P('=== MAIN (pre-registered rule, final conventions) ===')
    P('var period         n    gross    netN    netS  bonfLoN [1.25 , 98.75]N    [2.5 , 97.5]N    bonfLoS +coinN +coinS'
      '   tp%  stop%(gap)  time%  long/short weeks')
    for r in rows:
        P(f"{r['variant']:<3} {r['period']:<10} {r['n']:>6} {fmt(r['gross_bp']):>8} {fmt(r['net_normal_bp']):>7} "
          f"{fmt(r['net_stress_bp']):>7} {fmt(r['bonf_lo_normal']):>8} [{fmt(r['bonf_lo_normal'])},{fmt(r['bonf_hi_normal'])}] "
          f"[{fmt(r['ci95_lo_normal'])},{fmt(r['ci95_hi_normal'])}] {fmt(r['bonf_lo_stress']):>8} "
          f"{r['coins_pos_normal']:>3}/12 {r['coins_pos_stress']:>3}/12 {100 * r['tp_share']:5.1f} "
          f"{100 * r['stop_share']:5.1f}({100 * r['stop_gap_share']:3.1f}) {100 * r['time_share']:5.1f}  "
          f"{r['long_n']}/{r['short_n']} {r['n_weeks']}")
    P('')
    for v in VARIANTS:
        P(f'VERDICT {v}: {verd[v]}   {vdet[v]}')

    # ---------------- diagnostics
    diag = {'fill': {}, 'fill_by_utc_hour': {}, 'exit_mix': {}, 'yearly': {}, 'coin': {}, 'side': {},
            'entry_open_beyond': {}, 'ambiguous_bars': {}, 'open_at_end_dropped': {}}
    P('')
    P('FILL RATE (order-hour = flat hour with available indicators and >= 1 real 5m bar; fill = entry in that hour)')
    for var in VARIANTS:
        for per in PERIOD_NAMES:
            oh = sum(stats[(var, c)]['order_hours'][per] for c in COINS)
            fl = sum(stats[(var, c)]['fills'][per] for c in COINS)
            d = [x for x in trades if x['variant'] == var and x['period'] == per]
            diag['fill'][f'{var}_{per}'] = {'order_hours': oh, 'fills': fl, 'fill_rate': fl / oh,
                                            'long': sum(1 for x in d if x['side'] == 1),
                                            'short': sum(1 for x in d if x['side'] == -1)}
            P(f'  {var} {per:<10} order-hours {oh:>7} fills {fl:>6} rate {100 * fl / oh:6.3f}%  '
              f'(completed trades long {diag["fill"][f"{var}_{per}"]["long"]}, short {diag["fill"][f"{var}_{per}"]["short"]})')
        amb = sum(stats[(var, c)]['ambiguous'] for c in COINS)
        oe = sum(stats[(var, c)]['open_at_end'] for c in COINS)
        diag['ambiguous_bars'][var] = amb
        diag['open_at_end_dropped'][var] = oe
        ohu = sum(stats[(var, c)]['oh_by_utc'] for c in COINS)
        flu = sum(stats[(var, c)]['fill_by_utc'] for c in COINS)
        diag['fill_by_utc_hour'][var] = [float(a / b) for a, b in zip(flu, ohu)]
        P(f'  {var} ambiguous both-side bars {amb}; open at data end (dropped) {oe}')
        P(f'  {var} fill rate by UTC hour (%): ' + ' '.join(f'{hh:02d}:{100 * a / b:.2f}' for hh, (a, b) in
                                                       enumerate(zip(flu, ohu))))
    P('')
    P('EXIT MIX (n, share, mean gross bp, mean hold in 5m bars)')
    for var in VARIANTS:
        for per in PERIOD_NAMES:
            d = [x for x in trades if x['variant'] == var and x['period'] == per]
            ex = {}
            for typ in ('tp', 'stop', 'stop_gap', 'time'):
                dd = [x for x in d if x['exit_type'] == typ]
                ex[typ] = {'n': len(dd), 'share': len(dd) / len(d), 'gross': mean([x['gross_bp'] for x in dd]),
                           'hold_bars': mean([x['hold_bars'] for x in dd])}
            diag['exit_mix'][f'{var}_{per}'] = ex
            P(f'  {var} {per:<10} ' + '  '.join(f"{k} {v['n']} {100 * v['share']:.1f}% g{fmt(v['gross'], 1)} "
                                               f"h{v['hold_bars']:.1f}" for k, v in ex.items()))
    P('')
    P('YEARLY (entry year): n gross netN netS tp/stop/time %')
    for var in VARIANTS:
        diag['yearly'][var] = group([x for x in trades if x['variant'] == var], lambda x: x['year'])
        for yr, v in diag['yearly'][var].items():
            P(f"  {var} {yr} n {v['n']:>5} g {fmt(v['gross'])} N {fmt(v['net_normal'])} S {fmt(v['net_stress'])} "
              f"{100 * v['tp']:.1f}/{100 * v['stop']:.1f}/{100 * v['time']:.1f}")
    P('')
    P('PER COIN: n netN (netS)')
    for var in VARIANTS:
        for per in PERIOD_NAMES:
            key = f'{var}_{per}'
            d = [x for x in trades if x['variant'] == var and x['period'] == per]
            diag['coin'][key] = group(d, lambda x: x['coin'])
            P(f'  {key:<13} ' + '  '.join(f"{c} {diag['coin'][key][c]['n']} {fmt(diag['coin'][key][c]['net_normal'], 1)}"
                                        f"({fmt(diag['coin'][key][c]['net_stress'], 1)})" if c in diag['coin'][key]
                                        else f'{c} 0' for c in COINS))
    P('')
    P('LONG / SHORT: n gross netN netS tp/stop/time %')
    for var in VARIANTS:
        for per in PERIOD_NAMES:
            key = f'{var}_{per}'
            d = [x for x in trades if x['variant'] == var and x['period'] == per]
            diag['side'][key] = group(d, lambda x: 'LONG' if x['side'] == 1 else 'SHORT')
            for sd_, v in diag['side'][key].items():
                P(f"  {key:<13} {sd_:<5} n {v['n']:>5} g {fmt(v['gross'])} N {fmt(v['net_normal'])} "
                  f"S {fmt(v['net_stress'])} {100 * v['tp']:.1f}/{100 * v['stop']:.1f}/{100 * v['time']:.1f}")
    P('')
    P('ENTRY BAR OPEN ALREADY BEYOND THE LEVEL (filled at level, better price not credited): n share gross netN')
    for var in VARIANTS:
        for per in PERIOD_NAMES:
            key = f'{var}_{per}'
            d = [x for x in trades if x['variant'] == var and x['period'] == per]
            for flag in (1, 0):
                dd = [x for x in d if x['entry_open_beyond'] == flag]
                diag['entry_open_beyond'][f'{key}_{flag}'] = {'n': len(dd), 'gross': mean([x['gross_bp'] for x in dd]),
                                                              'net_normal': mean([x['net_normal_bp'] for x in dd])}
                P(f"  {key:<13} open_beyond={flag} n {len(dd):>5} ({100 * len(dd) / len(d):5.1f}%) "
                  f"g {fmt(mean([x['gross_bp'] for x in dd]))} N {fmt(mean([x['net_normal_bp'] for x in dd]))}")
    P('')
    P(f'runtime {time.time() - t0:.1f}s')

    # ---------------- outputs
    cols = ['variant', 'coin', 'side', 'period', 'year', 'iso_week', 'order_hour_ms', 'entry_ms', 'exit_ms',
            'entry_utc', 'exit_utc', 'entry_px', 'exit_px', 'exit_type', 'hold_bars', 'entry_bar_in_hour',
            'entry_open_beyond', 'gross_bp', 'net_normal_bp', 'net_stress_bp', 'sma20', 'std20', 'atr14', 'tp_px',
            'stop_px']
    for x in trades:
        x['entry_utc'] = utc_str(x['entry_ms'])
        x['exit_utc'] = utc_str(x['exit_ms'])
    with open(f'{OUT}/trades_final.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(cols)
        for x in sorted(trades, key=lambda r: (r['variant'], r['coin'], r['entry_ms'])):
            w.writerow([repr(x[c]) if isinstance(x[c], float) else x[c] for c in cols])
    rcols = ['variant', 'period', 'n', 'gross_bp', 'net_normal_bp', 'net_stress_bp', 'bonf_lo_normal', 'bonf_hi_normal',
             'ci95_lo_normal', 'ci95_hi_normal', 'bonf_lo_stress', 'bonf_hi_stress', 'ci95_lo_stress', 'ci95_hi_stress',
             'coins_pos_normal', 'coins_pos_stress', 'tp_share', 'stop_share', 'stop_gap_share', 'time_share',
             'long_n', 'short_n', 'n_weeks']
    with open(f'{OUT}/rows_final.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(rcols)
        for r in rows:
            w.writerow([r.get(c) for c in rcols])
    with open(f'{OUT}/results_final.json', 'w') as f:
        json.dump({'main_conventions': MAIN, 'rows': rows, 'verdicts': verd, 'verdict_detail': vdet,
                   'diagnostics': diag, 'engine2': {'trades': e2_total, 'mismatches': e2_mism},
                   'reproduction': repro, 'sensitivity': sens, 'n_trades': len(trades)}, f, indent=1, default=str)
    with open(f'{OUT}/report_final.txt', 'w') as f:
        f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
