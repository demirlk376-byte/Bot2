#!/usr/bin/env python3
"""Yeni listelenen coinleri short'lama -- FINAL uygulama (ON_KAYIT.md 2026-10-19).

Kullanim:  python3 -I analiz.py <veri_dizini> <cikti_dizini>
  <veri_dizini> = .../liste_veri/veri  (1d/<SYM>.csv, funding/<SYM>.csv, semboller.json)
Veri salt-okunur ve guvenilmez kabul edilir: yalnizca CSV/JSON sayi/metin olarak okunur, hicbir sey calistirilmaz.
Ciktilar: trades.csv, trades_all_incl_excluded.csv, ozet.json, cikti.txt (hepsi <cikti_dizini> altinda).

Kurallar (ON_KAYIT + gorev metni; hicbir parametre ayarlanmadi):
  L        = sembolun 1d dosyasindaki ilk satirin gunu (UTC)  ("ilk gunluk mum = listeleme", literal).
  Giris    = (L + 3 takvim gunu) satirinin ACILISI; o gun satiri yoksa (ya da gercek islem yoksa, hacim 0) islem yok.
  Gun sayimi: giris gunu = gun 1.  S30 hedef cikis gunu T = giris+29 gun, S14 T = giris+13 gun (takvim).
             T satiri yoksa T'den sonraki ilk mevcut satirin kapanisi.
  Stop     : giris gunu dahil, cikis satirina kadar (dahil) her satirda high >= stop ise max(open, stop) fiyatindan
             cikis (stop, ayni gunku sure dolumundan once kontrol edilir).  S30 stop = giris*1.40, S14 = giris*1.25.
  VERI SONU / DELIST (duzeltme):  Arsiv, delist sonrasinda 2026-09-30'a kadar duz "zombi" satirlar yaziyor
             (open=high=low=close=son fiyat, volume=0).  Bunlar gercek veri DEGILDIR.  Bir islemin verisi,
             giris satirindan sonraki ilk volume==0 satirindan bir onceki satirda (ya da dosya sonunda) biter.
             Hedef gune ulasmadan veri biterse son GERCEK kapanistan cikis, neden='delist'.
             (Ic bolgelerdeki volume==0 kosulari = delist + ayni sembolle yeniden listeleme; ayni kural.)
  Funding  : calc_time (dakikaya yuvarlanmis; ham veride ms-jitter var, 00:00 settlement'i giris anina esittir)
             > giris acilis ms  ve  <= cikis gununun kapanisi (open_time + 86400000 - 1).  Stop gunlerinde cikis zamani
             = stop gununun kapanisi (yaklasim; gun ici stop saati gunluk veriden bilinemez).  Delist'te cikis zamani
             = son gercek gunun kapanisi (zombi donemdeki funding kayitlari sayilmaz).  Short +oran alir (negatifse
             oder); notional = giris notional'i (funding_toplami = oranlarin toplami).
  Maliyet  : NORMAL 65 bp, STRESS 125 bp (notional uzerinden).
  R        = [(giris-cikis)/giris + funding - maliyet] / stop_mesafesi (0.40 / 0.25).
  Beta R   = [ret + funding - 65bp - btc_short] / sd ; btc_short = (BTC acilis[giris gunu] - BTC kapanis[cikis gunu])
             / BTC acilis[giris gunu]  (funding'siz, maliyetsiz; ayni giris/cikis gunleri).
  Donemler : L'ye gore KESIF [2021-01-01, 2023-12-31], DOGRULAMA [2024-01-01, 2026-08-15] (cikis <= 2026-09-30).
  Bootstrap: giris ayi bloklari, 10 000 tekrar, np.random.default_rng(20261019) her (varyant, donem, metrik) icin
             yeniden kurulur; aylar iadeli k kez cekilir (k = ay sayisi); istatistik = sum(R)/count (ratio-of-sums);
             Bonferroni alt = %1.25 persentil (np.percentile, linear).
  Haric    : taban (SYM eksi 'USDT') icinde USDC/BUSD/TUSD/FDUSD/DAI/USDP gecenler; BTCDOM, DEFI; tabani 'BTC' veya
             'ETH' ile bitenler (gorev metnindeki literal kurallar; anlamsal yanlis-pozitifler loglanir ve duyarlilik
             olarak raporlanir).  BTCUSDT/ETHUSDT 2020 oncesi listelendigi icin donem disi.  1000x onekliler DAHIL.
  Karar    : varyant KAZANDI <=> her iki donemde NORMAL ve STRESS ort R > 0, beta ort R > 0, n >= 50 ve
             DOGRULAMA NORMAL Bonferroni alt > 0.  Aksi halde ELENDI.
"""
import sys, os, json, io
import numpy as np
import pandas as pd

DAY_MS = 86_400_000
SEED = 20261019
B = 10_000
BONF_Q = 1.25
COST = {'NORMAL': 0.0065, 'STRESS': 0.0125}
VARIANTS = {'S30': dict(H=30, sd=0.40), 'S14': dict(H=14, sd=0.25)}
PERIODS = {'KESIF': ('2021-01-01', '2023-12-31'), 'DOGRULAMA': ('2024-01-01', '2026-08-15')}
EXIT_LIMIT = '2026-09-30'
STABLE_TOKENS = ['USDC', 'BUSD', 'TUSD', 'FDUSD', 'DAI', 'USDP']
INDEX_BASES = ['BTCDOM', 'DEFI']
SEMANTIC_FALSE_POS = ['HYUNDAIUSDT', 'NEIROETHUSDT', 'PUMPBTCUSDT']   # literal kuralin yakaladigi, sabit/endeks olmayanlar
FUND_GAP_TOL_MS = 9 * 3_600_000   # Binance azami funding araligi 8 s; > 9 s bosluk = eksik kayit


def day_str(ms):
    return pd.to_datetime(int(ms), unit='ms').strftime('%Y-%m-%d')


def exclusion_reason(sym):
    if not sym.endswith('USDT'):
        return 'not_usdt'
    base = sym[:-4]
    for t in STABLE_TOKENS:
        if t in base:
            return f'stable_token:{t}'
    if base in INDEX_BASES:
        return f'index:{base}'
    if base.endswith('BTC') and base != 'BTC':
        return 'base_endswith_BTC'
    if base.endswith('ETH') and base != 'ETH':
        return 'base_endswith_ETH'
    return ''


def period_of(L):
    for p, (a, b) in PERIODS.items():
        if a <= L <= b:
            return p
    return ''


def simulate(k, i0, i_end, fund, btc_open, btc_close, H, sd, stop_fund='close'):
    """k: dict of numpy arrays (ot, op, hi, lo, cl, vol) sorted by ot.  i0 = entry row, i_end = last usable row (inclusive).
    fund: dict(ctr=rounded calc_time, ct=raw calc_time, rate) or None."""
    ot, op, hi, cl = k['ot'], k['op'], k['hi'], k['cl']
    entry_ms = int(ot[i0])
    E = float(op[i0])
    stop = E * (1.0 + sd)
    T_ms = entry_ms + (H - 1) * DAY_MS
    seg = np.arange(i0, i_end + 1)
    after = seg[ot[seg] >= T_ms]
    if len(after):
        last_i, data_ended = int(after[0]), False
    else:
        last_i, data_ended = int(i_end), True
    win = np.arange(i0, last_i + 1)
    hit = win[hi[win] >= stop]
    if len(hit):
        ei = int(hit[0])
        X = max(float(op[ei]), stop)
        reason = 'stop'
    else:
        ei = last_i
        X = float(cl[ei])
        reason = 'delist' if data_ended else 'time'
    exit_ms = int(ot[ei])
    exit_close_ms = exit_ms + DAY_MS - 1
    held = ot[i0:ei + 1]
    gaps = np.diff(held) // DAY_MS
    maxgap = int(gaps.max()) if len(gaps) else 1
    f_end = exit_ms if (reason == 'stop' and stop_fund == 'open') else exit_close_ms
    if fund is not None and len(fund['rate']):
        ctr, ct, rate = fund['ctr'], fund['ct'], fund['rate']
        m = (ctr > entry_ms) & (ctr <= f_end)
        m_lit = (ct > entry_ms) & (ct <= f_end)
        f_sum, n_set, f_lit = float(rate[m].sum()), int(m.sum()), float(rate[m_lit].sum())
        pts = np.concatenate([[entry_ms], ctr[m], [exit_close_ms]])
        fgap = int(np.diff(pts).max())
    else:
        f_sum, n_set, f_lit, fgap = 0.0, 0, 0.0, exit_close_ms - entry_ms
    ret = (E - X) / E
    b_o = btc_open.get(entry_ms, np.nan)
    b_c = btc_close.get(exit_ms, np.nan)
    btc_ret = (b_o - b_c) / b_o
    out = dict(entry_px=E, stop_px=stop, planned_exit_day=day_str(T_ms), exit_day=day_str(exit_ms),
               exit_px=X, reason=reason, data_ended_before_T=data_ended,
               days_held=int((exit_ms - entry_ms) // DAY_MS + 1), rows_held=int(ei - i0 + 1), maxgap_in_window=maxgap,
               ret_short=ret, fund_sum=f_sum, fund_sum_literal_ts=f_lit, n_settle=n_set,
               fund_max_gap_h=round(fgap / 3_600_000, 3), fund_coverage_gap=bool(fgap > FUND_GAP_TOL_MS),
               btc_ret=btc_ret)
    for c, v in COST.items():
        out[f'R_{c.lower()}'] = (ret + f_sum - v) / sd
    out['R_beta'] = (ret + f_sum - COST['NORMAL'] - btc_ret) / sd
    out['R_normal_literal_ts'] = (ret + f_lit - COST['NORMAL']) / sd
    out['R_fund'] = f_sum / sd
    return out


def boot_lo(df, col, q=BONF_Q):
    g = df.groupby('entry_month')[col].agg(['sum', 'count'])
    s, c = g['sum'].values, g['count'].values
    k = len(g)
    if k == 0:
        return np.nan
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, k, size=(B, k))
    stat = s[idx].sum(1) / c[idx].sum(1)
    return float(np.percentile(stat, q))


def summarize(t, with_boot=True):
    if len(t) == 0:
        return dict(n=0)
    m = t.groupby('entry_month').R_normal.sum()
    s = dict(n=int(len(t)), meanR_normal=float(t.R_normal.mean()), meanR_stress=float(t.R_stress.mean()),
             meanR_beta=float(t.R_beta.mean()))
    if with_boot:
        s.update(bonf_lo=boot_lo(t, 'R_normal'), bonf_lo_stress=boot_lo(t, 'R_stress'), bonf_lo_beta=boot_lo(t, 'R_beta'))
    s.update(win_rate=float((t.R_normal > 0).mean()), pos_month_share=float((m > 0).mean()), n_months=int(len(m)),
             stop_share=float((t.reason == 'stop').mean()), delist_share=float((t.reason == 'delist').mean()),
             time_share=float((t.reason == 'time').mean()), median_R=float(t.R_normal.median()),
             sumR_normal=float(t.R_normal.sum()), mean_ret_short=float(t.ret_short.mean()),
             mean_fund=float(t.fund_sum.mean()), mean_R_fund=float(t.R_fund.mean()), mean_btc_ret=float(t.btc_ret.mean()))
    return s


def concurrency(t):
    if len(t) == 0:
        return {}
    a = pd.to_datetime(t.entry_day).values.astype('datetime64[D]')
    b = pd.to_datetime(t.exit_day).values.astype('datetime64[D]')
    lo, hi = a.min(), b.max()
    n = int((hi - lo).astype(int)) + 2
    diff = np.zeros(n, dtype=int)
    np.add.at(diff, (a - lo).astype(int), 1)
    np.add.at(diff, (b - lo).astype(int) + 1, -1)
    cnt = np.cumsum(diff)[:-1]
    imax = int(cnt.argmax())
    return dict(max=int(cnt.max()), max_day=str(lo + np.timedelta64(imax, 'D')), mean_all_days=float(cnt.mean()),
                mean_days_with_pos=float(cnt[cnt > 0].mean()), median_all_days=float(np.median(cnt)),
                p95=float(np.percentile(cnt, 95)), share_days_zero=float((cnt == 0).mean()), span_days=int(len(cnt)))


def zero_runs(vol, ot):
    """interior/trailing volume==0 runs as list of (start_day, length, trailing?)"""
    z = vol == 0
    runs, i, n = [], 0, len(vol)
    while i < n:
        if z[i]:
            j = i
            while j + 1 < n and z[j + 1]:
                j += 1
            runs.append((day_str(ot[i]), int(j - i + 1), bool(j == n - 1)))
            i = j + 1
        else:
            i += 1
    return runs


def main():
    D, OUT = sys.argv[1], sys.argv[2]
    os.makedirs(OUT, exist_ok=True)
    buf = io.StringIO()

    def P(*a):
        print(*a)
        print(*a, file=buf)

    log = []
    with open(os.path.join(D, 'semboller.json')) as fh:
        meta = json.load(fh)
    syms = sorted(f[:-4] for f in os.listdir(os.path.join(D, '1d')) if f.endswith('.csv'))
    log.append(f'1d dosyasi: {len(syms)}, semboller.json: {len(meta)}')
    btc = pd.read_csv(os.path.join(D, '1d', 'BTCUSDT.csv'))
    btc_open = dict(zip(btc.open_time.astype('int64').tolist(), btc.open.astype(float).tolist()))
    btc_close = dict(zip(btc.open_time.astype('int64').tolist(), btc.close.astype(float).tolist()))

    recs, recs_literal, recs_stopopen, excl_log, notrade, gun_mismatch, integrity = [], [], [], [], [], [], []
    sym_info = {}
    n_out_period = 0
    out_period_excl = []
    for sym in syms:
        d = pd.read_csv(os.path.join(D, '1d', sym + '.csv')).sort_values('open_time').reset_index(drop=True)
        if len(d) == 0:
            integrity.append((sym, 'empty'))
            continue
        k = dict(ot=d.open_time.values.astype('int64'), op=d.open.values.astype(float), hi=d.high.values.astype(float),
                 lo=d.low.values.astype(float), cl=d.close.values.astype(float), vol=d.volume.values.astype(float))
        if d.open_time.duplicated().any():
            integrity.append((sym, 'dup_open_time'))
        if (k['ot'] % DAY_MS != 0).any():
            integrity.append((sym, 'open_time_not_midnight'))
        if d[['open', 'high', 'low', 'close', 'volume']].isna().any().any():
            integrity.append((sym, 'nan'))
        if ((k['hi'] < np.maximum(k['op'], k['cl']) - 1e-12) | (k['lo'] > np.minimum(k['op'], k['cl']) + 1e-12)).any():
            integrity.append((sym, 'ohlc_inconsistent'))
        if sym in meta and isinstance(meta[sym], dict) and meta[sym].get('gun') != len(d):
            gun_mismatch.append((sym, meta[sym].get('gun'), len(d)))
        nz = np.where(k['vol'] > 0)[0]
        last_real_i = int(nz.max()) if len(nz) else -1
        runs = zero_runs(k['vol'], k['ot'])
        L_ms = int(k['ot'][0])
        L = day_str(L_ms)
        sym_info[sym] = dict(L=L, last_row=day_str(k['ot'][-1]),
                             last_real=day_str(k['ot'][last_real_i]) if last_real_i >= 0 else None,
                             n_zombie_trailing=int(len(k['vol']) - 1 - last_real_i), zero_runs=runs)
        per = period_of(L)
        ex = exclusion_reason(sym)
        if ex:
            excl_log.append(dict(sym=sym, L=L, period=per or '-', reason=ex))
        if not per:
            n_out_period += 1
            if sym[:-4] in ('BTC', 'ETH'):
                out_period_excl.append(dict(sym=sym, L=L, note='BTC/ETH itself, listed pre-2021 -> out of period'))
            continue
        entry_ms = L_ms + 3 * DAY_MS
        er = np.where(k['ot'] == entry_ms)[0]
        if len(er) == 0:
            notrade.append(dict(sym=sym, L=L, period=per, excluded=ex, why='L+3 row missing',
                                last=day_str(k['ot'][-1]), rows=len(d)))
            continue
        i0 = int(er[0])
        if k['vol'][i0] <= 0:
            notrade.append(dict(sym=sym, L=L, period=per, excluded=ex, why='L+3 row has zero volume (no real data)'))
            continue
        zr = np.where(k['vol'][i0:] <= 0)[0]
        i_end = int(i0 + zr[0] - 1) if len(zr) else len(d) - 1      # last real row of this trading stretch
        i_end_lit = len(d) - 1                                       # literal file rows (zombie rows as data)
        fp = os.path.join(D, 'funding', sym + '.csv')
        fund = None
        if os.path.exists(fp):
            f = pd.read_csv(fp).sort_values('calc_time')
            f = f[pd.notna(f.last_funding_rate)]
            ct = f.calc_time.values.astype('int64')
            fund = dict(ct=ct, ctr=((ct + 30_000) // 60_000) * 60_000, rate=f.last_funding_rate.values.astype(float))
        # funding-based product proxy (sensitivity only): modal rate of records in [L, L+33d]
        if fund is not None:
            mm = (fund['ct'] >= L_ms) & (fund['ct'] <= L_ms + 33 * DAY_MS)
            rr = pd.Series(np.round(fund['rate'][mm], 8))
            fmode = float(rr.mode().iloc[0]) if len(rr) else np.nan
            fund_first = int(fund['ct'].min()) if len(fund['ct']) else -1
            n_after_real = int((fund['ct'] > k['ot'][last_real_i] + DAY_MS).sum())
        else:
            fmode, fund_first, n_after_real = np.nan, -1, 0
        sym_info[sym].update(fund_mode_first33d=fmode, n_funding_after_last_real_day=n_after_real,
                             funding_first=day_str(fund_first) if fund_first >= 0 else None)
        pre_hours = (L_ms - fund_first) / 3_600_000 if fund_first >= 0 else 0.0
        pre = d[d.open_time < entry_ms]
        common = dict(sym=sym, base=sym[:-4], period=per, L=L, L_year=L[:4], entry_day=day_str(entry_ms),
                      entry_month=day_str(entry_ms)[:7], entry_year=day_str(entry_ms)[:4],
                      qv_entry=float(d.quote_volume.iloc[i0]),
                      qv_first3_mean=float(pre.quote_volume.mean()) if len(pre) else np.nan,
                      data_last_row_day=day_str(k['ot'][-1]), last_real_day=day_str(k['ot'][last_real_i]),
                      trade_stretch_end_day=day_str(k['ot'][i_end]),
                      eventually_delisted=bool(day_str(k['ot'][last_real_i]) < EXIT_LIMIT),
                      ever_zero_volume_gap=bool(len(runs) > 0),
                      tradfi_like_zero_funding_mode=bool(fmode == 0.0),
                      funding_starts_days_before_L=round(pre_hours / 24, 2),
                      excluded=bool(ex), excl_reason=ex)
        for v, p in VARIANTS.items():
            r = simulate(k, i0, i_end, fund, btc_open, btc_close, p['H'], p['sd'])
            rl = simulate(k, i0, i_end_lit, fund, btc_open, btc_close, p['H'], p['sd'])
            ro = simulate(k, i0, i_end, fund, btc_open, btc_close, p['H'], p['sd'], stop_fund='open')
            recs.append(dict(variant=v, **common, **r))
            recs_literal.append(dict(variant=v, sym=sym, period=per, excluded=bool(ex), **{c: rl[c] for c in
                                ['exit_day', 'exit_px', 'reason', 'fund_sum', 'btc_ret', 'R_normal', 'R_stress', 'R_beta']}))
            recs_stopopen.append(dict(variant=v, sym=sym, R_normal_stopfund_open=ro['R_normal'], R_beta_stopfund_open=ro['R_beta']))

    allt = pd.DataFrame(recs)
    lit = pd.DataFrame(recs_literal).set_index(['variant', 'sym'])
    so = pd.DataFrame(recs_stopopen).set_index(['variant', 'sym'])
    allt = allt.join(so, on=['variant', 'sym'])
    assert allt.btc_ret.notna().all(), 'BTC row missing for some entry/exit day'
    allt.to_csv(os.path.join(OUT, 'trades_all_incl_excluded.csv'), index=False)
    T = allt[~allt.excluded].copy()
    T.to_csv(os.path.join(OUT, 'trades.csv'), index=False)

    rows, res = [], {}
    for v in VARIANTS:
        for p in PERIODS:
            t = T[(T.variant == v) & (T.period == p)]
            s = summarize(t)
            res[(v, p)] = s
            rows.append(dict(variant=v, period=p, **s))
    verdicts = {}
    for v in VARIANTS:
        kk, dg = res[(v, 'KESIF')], res[(v, 'DOGRULAMA')]
        crit = {
            'c1_normal_stress_pos_both': bool(kk['meanR_normal'] > 0 and kk['meanR_stress'] > 0 and
                                              dg['meanR_normal'] > 0 and dg['meanR_stress'] > 0),
            'c2_dogrulama_bonf_lo_pos': bool(dg['bonf_lo'] > 0),
            'c3_beta_pos_both': bool(kk['meanR_beta'] > 0 and dg['meanR_beta'] > 0),
            'c4_n_ge_50_both': bool(kk['n'] >= 50 and dg['n'] >= 50),
        }
        verdicts[v] = dict(verdict='KAZANDI' if all(crit.values()) else 'ELENDI', **crit)

    # ---------------- diagnostics ----------------
    diag = {}
    diag['rules_note'] = ('Zombie rows (volume==0, flat OHLC) after a delisting are NOT data: a trade\'s data ends at the row '
                          'before the first volume==0 row on/after entry. eventually_delisted = symbol\'s last volume>0 row '
                          f'< {EXIT_LIMIT}. Funding window (entry_open, exit_day_close]; stop/delist exit day close used as exit '
                          'time (approximation). calc_time rounded to the minute.')
    diag['log'] = log
    diag['data_integrity_issues'] = integrity
    diag['excluded'] = excl_log
    diag['excluded_in_period_counts'] = {p: int(sum(1 for e in excl_log if e['period'] == p)) for p in PERIODS}
    diag['btc_eth_out_of_period'] = out_period_excl
    diag['n_out_of_period_symbols'] = n_out_period
    diag['no_trade'] = notrade
    diag['semboller_gun_mismatch'] = gun_mismatch[:20]
    traded = sorted(T.sym.unique())
    zt = [dict(sym=s, L=sym_info[s]['L'], last_real=sym_info[s]['last_real'], last_row=sym_info[s]['last_row'],
               n_zombie_trailing=sym_info[s]['n_zombie_trailing'], zero_runs=sym_info[s]['zero_runs'])
          for s in traded if sym_info[s]['zero_runs']]
    diag['zombie_rows'] = dict(
        n_symbols_all_with_zero_volume_runs=int(sum(1 for s in sym_info if sym_info[s]['zero_runs'])),
        n_traded_symbols_with_trailing_zombie_rows=int(sum(1 for z in zt if z['n_zombie_trailing'] > 0)),
        n_traded_symbols_with_interior_zero_runs=int(sum(1 for z in zt if any(not r[2] for r in z['zero_runs']))),
        n_traded_symbols_funding_records_after_last_real_day=int(sum(1 for s in traded if sym_info[s].get('n_funding_after_last_real_day', 0) > 0)),
        traded_symbols=zt)
    # reconciliation vs. literal-rows implementation (zombie rows treated as data; = liste_A / liste_B behaviour)
    rec = []
    for v in VARIANTS:
        for p in PERIODS:
            t = T[(T.variant == v) & (T.period == p)]
            l = lit.loc[[(v, s) for s in t.sym]]
            rec.append(dict(variant=v, period=p, meanR_normal_literal_rows=float(l.R_normal.mean()),
                            meanR_stress_literal_rows=float(l.R_stress.mean()), meanR_beta_literal_rows=float(l.R_beta.mean()),
                            delist_literal_rows=int((l.reason == 'delist').sum()),
                            meanR_normal_final=float(t.R_normal.mean()), meanR_beta_final=float(t.R_beta.mean())))
    diag['reconciliation_vs_literal_rows'] = rec
    chg = []
    for _, r in T.iterrows():
        l = lit.loc[(r.variant, r.sym)]
        if (l.exit_day != r.exit_day) or abs(l.R_normal - r.R_normal) > 1e-12:
            chg.append(dict(variant=r.variant, sym=r.sym, period=r.period, entry=r.entry_day,
                            exit_literal=l.exit_day, reason_literal=l.reason, R_literal=round(l.R_normal, 4),
                            Rbeta_literal=round(l.R_beta, 4), fund_literal=round(l.fund_sum, 5),
                            exit_final=r.exit_day, reason_final=r.reason, R_final=round(r.R_normal, 4),
                            Rbeta_final=round(r.R_beta, 4), fund_final=round(r.fund_sum, 5)))
    diag['trades_changed_by_zombie_fix'] = chg
    yearly = (T.groupby(['variant', 'L_year'])
              .apply(lambda g: pd.Series(dict(n=len(g), meanR_normal=g.R_normal.mean(), meanR_stress=g.R_stress.mean(),
                                              meanR_beta=g.R_beta.mean(), win=(g.R_normal > 0).mean(),
                                              stop=(g.reason == 'stop').mean(), delist=(g.reason == 'delist').mean(),
                                              eventually_delisted=g.eventually_delisted.mean(),
                                              sumR=g.R_normal.sum(), mean_btc_ret=g.btc_ret.mean())), include_groups=False)
              .reset_index())
    diag['yearly_by_L_year'] = yearly.round(4).to_dict('records')
    monthly = []
    for v in VARIANTS:
        for p in PERIODS:
            t = T[(T.variant == v) & (T.period == p)]
            m = t.groupby('entry_month').R_normal.agg(['sum', 'count', 'mean'])
            monthly.append(dict(variant=v, period=p, n_months=int(len(m)), pos_month_share=float((m['sum'] > 0).mean()),
                                pos_month_share_beta=float((t.groupby('entry_month').R_beta.sum() > 0).mean()),
                                best_month=str(m['sum'].idxmax()), best_month_sumR=float(m['sum'].max()),
                                worst_month=str(m['sum'].idxmin()), worst_month_sumR=float(m['sum'].min())))
    diag['monthly'] = monthly
    dl, ev = [], []
    for v in VARIANTS:
        for p in PERIODS:
            t = T[(T.variant == v) & (T.period == p)]
            x = t[t.reason == 'delist']
            tot = t.R_normal.sum()
            dl.append(dict(variant=v, period=p, n_delist_exit=int(len(x)), share=float(len(x) / len(t)),
                           meanR_delist=float(x.R_normal.mean()) if len(x) else None,
                           sumR_delist=float(x.R_normal.sum()), sumR_total=float(tot),
                           meanR_beta_delist=float(x.R_beta.mean()) if len(x) else None,
                           meanR_ex_delist=float(t[t.reason != 'delist'].R_normal.mean()),
                           syms=x.sym.tolist()))
            x = t[t.eventually_delisted]
            o = t[~t.eventually_delisted]
            ev.append(dict(variant=v, period=p, n_eventually_delisted=int(len(x)), share=float(len(x) / len(t)),
                           meanR=float(x.R_normal.mean()) if len(x) else None, sumR=float(x.R_normal.sum()),
                           sumR_total=float(tot), contribution_share_of_sumR=float(x.R_normal.sum() / tot) if tot != 0 else None,
                           meanR_stress=float(x.R_stress.mean()) if len(x) else None,
                           meanR_beta=float(x.R_beta.mean()) if len(x) else None,
                           n_others=int(len(o)), meanR_others=float(o.R_normal.mean()),
                           meanR_stress_others=float(o.R_stress.mean()), meanR_beta_others=float(o.R_beta.mean()),
                           n_ever_zero_volume_gap=int(t.ever_zero_volume_gap.sum())))
    diag['delist_exits'] = dl
    diag['eventually_delisted_symbols'] = ev
    diag['trades_without_funding_records'] = T[T.n_settle == 0][['variant', 'sym', 'period', 'entry_day', 'exit_day', 'R_normal']].round(4).to_dict('records')
    diag['trades_with_funding_coverage_gap'] = T[T.fund_coverage_gap][['variant', 'sym', 'period', 'entry_day', 'exit_day', 'n_settle', 'fund_max_gap_h', 'R_normal']].round(4).to_dict('records')
    diag['trades_with_data_gap_in_window'] = T[T.maxgap_in_window > 1][['variant', 'sym', 'period', 'entry_day', 'exit_day', 'maxgap_in_window', 'reason', 'R_normal']].round(4).to_dict('records')
    diag['n_btc_ret_nan'] = int(T.btc_ret.isna().sum())
    diag['max_exit_day'] = str(T.exit_day.max())
    worst = {}
    cols = ['sym', 'period', 'L', 'entry_day', 'exit_day', 'reason', 'entry_px', 'exit_px', 'ret_short', 'fund_sum',
            'R_normal', 'R_beta']
    for v in VARIANTS:
        worst[v] = T[T.variant == v].nsmallest(10, 'R_normal')[cols].round(5).to_dict('records')
    diag['worst10'] = worst
    conc = {}
    for v in VARIANTS:
        conc[v] = {p: concurrency(T[(T.variant == v) & (T.period == p)]) for p in PERIODS}
        conc[v]['ALL'] = concurrency(T[T.variant == v])
    diag['concurrency'] = conc
    fc = []
    for v in VARIANTS:
        for p in PERIODS:
            t = T[(T.variant == v) & (T.period == p)]
            fc.append(dict(variant=v, period=p, mean_fund_sum=float(t.fund_sum.mean()), mean_R_fund=float(t.R_fund.mean()),
                           meanR_normal=float(t.R_normal.mean()), meanR_normal_without_funding=float((t.R_normal - t.R_fund).mean()),
                           mean_n_settle=float(t.n_settle.mean()), n_zero_settle=int((t.n_settle == 0).sum()),
                           n_coverage_gap=int(t.fund_coverage_gap.sum()), share_fund_neg=float((t.fund_sum < 0).mean())))
    diag['funding'] = fc
    vol = []
    for p in PERIODS:
        t = T[(T.variant == 'S30') & (T.period == p)]
        vol.append(dict(period=p, median_qv_entry_usdt=float(t.qv_entry.median()),
                        median_qv_first3_mean_usdt=float(t.qv_first3_mean.median()),
                        p10_qv_entry=float(t.qv_entry.quantile(0.1)), p90_qv_entry=float(t.qv_entry.quantile(0.9))))
    diag['volume_at_entry'] = vol
    lsus = sorted(T[T.funding_starts_days_before_L > 7].sym.unique())
    diag['listing_day_check'] = dict(
        note=('Funding records before the first kline exist for many symbols but are constant placeholder rates '
              '(0.0001 / 0 / 0.00005) for hours to days before trading; first-of-month listings occur at the expected '
              'rate; archive starts 2020-01 (before both periods). Literal first candle kept as L. Suspects with funding '
              'records > 7 days before the first kline (possible earlier listing missing from the kline archive) are '
              'excluded only in a sensitivity.'),
        dom1_share_in_period=float((pd.to_datetime(T.drop_duplicates('sym').L).dt.day == 1).mean()),
        suspects_funding_gt7d_before_first_kline=lsus)
    # sensitivities (not used in verdict)
    sens = []
    for v in VARIANTS:
        for p in PERIODS:
            t = T[(T.variant == v) & (T.period == p)]
            a = allt[(allt.variant == v) & (allt.period == p)]
            row = dict(variant=v, period=p)

            def add(tag, tt):
                s = summarize(tt, with_boot=True) if len(tt) else dict(n=0)
                row[f'{tag}_n'] = s.get('n', 0)
                for c in ('meanR_normal', 'meanR_stress', 'meanR_beta', 'bonf_lo'):
                    row[f'{tag}_{c}'] = s.get(c)
            add('keep_semantic_false_pos', a[(~a.excluded) | (a.sym.isin(SEMANTIC_FALSE_POS))])
            add('excl_tradfi_like', t[~t.tradfi_like_zero_funding_mode])
            add('only_tradfi_like', t[t.tradfi_like_zero_funding_mode])
            add('excl_no_or_gappy_funding', t[(t.n_settle > 0) & (~t.fund_coverage_gap)])
            add('excl_listing_suspects', t[~t.sym.isin(lsus)])
            add('excl_eventually_delisted', t[~t.eventually_delisted])
            add('excl_L2026', t[t.L_year != '2026'])
            row['meanR_normal_literal_funding_ts'] = float(t.R_normal_literal_ts.mean())
            row['n_trades_literal_ts_differs'] = int((t.fund_sum != t.fund_sum_literal_ts).sum())
            row['meanR_normal_stop_funding_to_open'] = float(t.R_normal_stopfund_open.mean())
            row['meanR_beta_stop_funding_to_open'] = float(t.R_beta_stopfund_open.mean())
            row['meanR_ex_top5'] = float(t.nsmallest(len(t) - 5, 'R_normal').R_normal.mean())
            row['meanR_ex_worst5'] = float(t.nlargest(len(t) - 5, 'R_normal').R_normal.mean())
            row['n_tradfi_like'] = int(t.tradfi_like_zero_funding_mode.sum())
            sens.append(row)
    diag['sensitivity_not_for_verdict'] = sens

    with open(os.path.join(OUT, 'ozet.json'), 'w') as fh:
        json.dump(dict(rows=rows, verdicts=verdicts, diagnostics=diag), fh, indent=1, default=str)

    pd.set_option('display.width', 250)
    pd.set_option('display.max_columns', 60)
    pd.set_option('display.max_rows', 300)
    P('=== ANA SATIRLAR (karar) ===')
    P(pd.DataFrame(rows).round(4).to_string(index=False))
    P('=== KARAR ===')
    P(json.dumps(verdicts, indent=1))
    P('=== HARIC (log) ===')
    for e in excl_log:
        P('  ', e)
    P('   BTC/ETH:', out_period_excl)
    P('donem disi sembol:', n_out_period, ' islem yok:', notrade, ' veri butunlugu:', integrity, ' gun uyumsuz:', gun_mismatch[:10])
    P('=== ZOMBI SATIR DUZELTMESI ===')
    P({k2: v2 for k2, v2 in diag['zombie_rows'].items() if k2 != 'traded_symbols'})
    P(pd.DataFrame(rec).round(4).to_string(index=False))
    P(pd.DataFrame(chg).to_string(index=False) if chg else 'no trade changed')
    P('=== YIL YIL (L yili) ===')
    P(yearly.round(4).to_string(index=False))
    P('=== AYLIK ===')
    P(pd.DataFrame(monthly).round(4).to_string(index=False))
    P('=== DELIST: elde tutarken veri biten islemler ===')
    P(pd.DataFrame(dl).round(4).to_string(index=False))
    P('=== DELIST: sonradan delist edilen semboller (son volume>0 satiri < 2026-09-30) ===')
    P(pd.DataFrame(ev).round(4).to_string(index=False))
    P('=== FUNDING ===')
    P(pd.DataFrame(fc).round(4).to_string(index=False))
    P('funding kaydi olmayan islemler:', diag['trades_without_funding_records'])
    P('funding kapsama boslugu olan islemler:', len(diag['trades_with_funding_coverage_gap']))
    P(pd.DataFrame(diag['trades_with_funding_coverage_gap']).to_string(index=False) if diag['trades_with_funding_coverage_gap'] else '')
    P('pencere icinde gun boslugu:', diag['trades_with_data_gap_in_window'])
    P('btc nan', diag['n_btc_ret_nan'], ' max exit day', diag['max_exit_day'])
    for v in VARIANTS:
        P(f'=== {v} EN KOTU 10 ===')
        P(pd.DataFrame(worst[v]).to_string(index=False))
    P('=== ESZAMANLI ACIK POZISYON ===')
    P(json.dumps(conc, indent=1))
    P('=== GIRIS HACMI ===')
    P(pd.DataFrame(vol).round(0).to_string(index=False))
    P('=== LISTELEME GUNU KONTROLU ===')
    P(diag['listing_day_check'])
    P('=== DUYARLILIK (karar icin degil) ===')
    P(pd.DataFrame(sens).round(4).T.to_string())
    with open(os.path.join(OUT, 'cikti.txt'), 'w') as fh:
        fh.write(buf.getvalue())


if __name__ == '__main__':
    main()
