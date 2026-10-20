#!/usr/bin/env python3
"""Momentum v2 -- criterion 2 (PORTFOLIO contribution) for W and H on ESKI12.

Pre-registration: /home/user/sweep/research/momentum_v2/ON_KAYIT.md (2026-10-19).
Trade generation: COPIED (not imported) from scratchpad/mom2_A/analiz.py (load, weekly, simulate, constants);
the only addition is an optional data cut (px/funding truncated at t_cut) used solely by the "_E" sensitivity.
Combined engine: research/trend_gelistirme/birlesik.py MotorBirlesik, UNMODIFIED, run exactly like
scratchpad/iki_yil_15.py / aylik_tablo.py / trend_genislet_V/dogrula.py (trend B0, risk 0.015, MAL['NORMAL'], C0 10 000,
bot = twin trades R = pnl/(|E-sl0|*q), teminat_oran = notional / twin closed-trade balance / 10, squeeze removed,
window entries >= t_bas and exits < t_bit).
Momentum sleeve: appended to the bot list. Engine bot PnL = R * BOT_RISK(0.035) * equity (asserted from source
+ numeric unit check), so each momentum trade is passed as R = R_normal * 0.01/0.035 (=> 1 % risk) and
teminat_oran = notional_over_risk * 0.01 / 10 (10x margin on the 1 %-risk notional). Same window rule as the bot.

Usage (cwd /home/user/sweep):
  python3 analiz.py gen                 -> mom_trades.csv (+ cross-check vs mom2_A/trades.csv)
  python3 analiz.py birim               -> engine unit check (R scaling)
  python3 analiz.py kos <VAR> <DONEM>   -> R_<VAR>_<DONEM>.pkl  VAR in BASE W H W_S H_S W_E H_E
  python3 analiz.py ozet                -> results.json + report.txt
"""
import inspect
import json
import os
import pickle
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/user/sweep")

OUT = os.path.dirname(os.path.abspath(__file__))
SP = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad"
DATA = '/home/user/sweep/research_data/h4_kirilim_v6/veri'

# ===================================================================== COPIED from mom2_A/analiz.py (begin)
ESKI12 = 'SOL ETH ADA NEAR BCH XRP DOGE TRX XLM LTC ICP BNB'.split()
assert len(ESKI12) == 12

H4 = 4 * 3600 * 1000
WEEK = 7 * 86400 * 1000


def ms(s):
    return int(pd.Timestamp(s, tz='UTC').value // 10**6)


ATR_K, ATR_N = 3.0, 10
W_LB = 12
H_LB, H_FRAC, H_HOLD = 52, 0.95, 4
COM_BP, SLIP_IN_BP, SLIP_OUT_BP = 1.0, 15.85, 0.24
COST_N = (2 * COM_BP + SLIP_IN_BP + SLIP_OUT_BP) / 1e4             # 18.09 bp
COST_S = (2 * COM_BP + 2 * SLIP_IN_BP + 2 * SLIP_OUT_BP) / 1e4     # 34.18 bp


def load(coin, t_cut=None):
    px = pd.read_csv(f'{DATA}/{coin}_4h.csv')
    px = px.sort_values('open_time').drop_duplicates('open_time').reset_index(drop=True)
    assert (px.open_time % H4 == 0).all()
    fu = pd.read_csv(f'{DATA}/{coin}_funding.csv')
    fu['s'] = (np.round(fu.calc_time / 1000.0) * 1000).astype('int64')   # ms jitter -> exact second
    fu = fu.sort_values('s').drop_duplicates('s').reset_index(drop=True)
    if t_cut is not None:     # (addition) sensitivity only: data known up to t_cut
        px = px[px.open_time + H4 <= t_cut].reset_index(drop=True)
        fu = fu[fu.s <= t_cut].reset_index(drop=True)
    return px, fu


def weekly(px):
    s = px.set_index(pd.to_datetime(px.open_time, unit='ms', utc=True))
    r = s.resample('W-MON', label='left', closed='left')
    wk = pd.DataFrame({'open': r.open.first(), 'high': r.high.max(), 'low': r.low.min(),
                       'close': r.close.last(), 'first_ms': r.open_time.first(),
                       'last_ms': r.open_time.last(), 'nbar': r.open_time.count()})
    wk = wk[wk.nbar > 0].copy()
    wk['wk_ms'] = (wk.index.as_unit('ms').asi8).astype('int64')
    assert (wk.index.dayofweek == 0).all() and (wk.wk_ms % 86400000 == 0).all()
    assert (wk.first_ms >= wk.wk_ms).all() and (wk.last_ms < wk.wk_ms + WEEK).all()
    if wk.first_ms.iloc[0] != wk.wk_ms.iloc[0]:
        wk = wk.iloc[1:]
    wk = wk.reset_index(drop=True)
    t4 = px.open_time.values
    wk['i0'] = np.searchsorted(t4, wk.wk_ms.values, side='left')
    wk['i1'] = np.searchsorted(t4, wk.wk_ms.values + WEEK, side='left')
    assert (wk.i1 - wk.i0 == wk.nbar).all()
    return wk


def simulate(coin, px, fu, wk, strat, w_reset=False, ret_def='open12'):
    o, h, l, c = (wk[k].values.astype(float) for k in ('open', 'high', 'low', 'close'))
    wms, fms, i0, i1 = wk.wk_ms.values, wk.first_ms.values, wk.i0.values, wk.i1.values
    po, pl, pc, pt = (px[k].values for k in ('open', 'low', 'close', 'open_time'))
    n = len(wk)
    tr = np.empty(n)
    tr[0] = h[0] - l[0]
    tr[1:] = np.maximum(h[1:], c[:-1]) - np.minimum(l[1:], c[:-1])
    fs = fu.s.values
    fcum = np.concatenate([[0.0], np.cumsum(fu.last_funding_rate.values)])

    def fsum(a, b):   # sum of rates with a < s <= b
        return fcum[np.searchsorted(fs, b, 'right')] - fcum[np.searchsorted(fs, a, 'right')]

    trades = []
    pos = None
    need_reset = False
    warm = W_LB if strat == 'W' else H_LB

    def close_pos(px_exit, t_exit, reason):
        e, atr = pos['entry'], pos['atr']
        ret = px_exit / e - 1.0
        fund = -fsum(pos['entry_ms'], t_exit)
        rk = ATR_K * atr / e
        trades.append(dict(coin=coin, strat=strat, entry_ms=int(pos['entry_ms']), exit_ms=int(t_exit),
                           entry=e, stop=pos['stop'], exit=float(px_exit),
                           R_normal=(ret + fund - COST_N) / rk, R_stress=(ret + fund - COST_S) / rk,
                           notional_over_risk=e / (ATR_K * atr), atr=atr, ret=ret, funding=fund,
                           reason=reason, entry_wk_ms=int(pos['wk_ms'])))

    for t in range(warm, n):
        atr = tr[t - ATR_N:t].mean()
        if strat == 'W':
            base = o[t - W_LB] if ret_def == 'open12' else c[t - W_LB - 1] if t - W_LB - 1 >= 0 else np.nan
            sig = (c[t - 1] / base - 1.0) > 0
        else:
            sig = c[t - 1] >= H_FRAC * c[t - H_LB:t].max()
        P, T = o[t], int(fms[t])
        # 1) Monday-open exits
        if pos is not None:
            if strat == 'W' and not sig:
                close_pos(P, T, 'signal'); pos = None
            elif strat == 'H' and wms[t] >= pos['wk_ms'] + H_HOLD * WEEK:
                close_pos(P, T, 'time'); pos = None
        if w_reset and not sig:
            need_reset = False
        # 2) Monday-open entries
        if pos is None and sig and not (w_reset and need_reset):
            pos = dict(entry=P, entry_ms=T, wk_ms=int(wms[t]), atr=atr, stop=P - ATR_K * atr)
        # 3) intra-week stop scan on 4h bars of week t
        if pos is not None:
            st = pos['stop']
            for j in range(i0[t], i1[t]):
                if po[j] <= st:
                    close_pos(po[j], int(pt[j]), 'stop_gap'); pos = None; break
                if pl[j] <= st:
                    close_pos(st, int(pt[j]), 'stop'); pos = None; break
            if pos is None:
                need_reset = True
    if pos is not None:   # still open at end of data
        close_pos(pc[-1], int(pt[-1] + H4), 'eod')
    return trades
# ===================================================================== COPIED from mom2_A/analiz.py (end)


GEN_FROM, GEN_TO_EXCL = ms('2020-01-01'), ms('2026-07-19')     # entries 2020-01-01 .. 2026-07-18 inclusive
C0 = 10_000.0
TREND_RISK = 0.015
MOM_RISK = 0.01
LEV = 10.0
DONEM = {"BAGIMSIZ": (ms("2020-02-01"), ms("2023-04-07"), f"{SP}/ikiz_kanit/ikiz_eski.db"),
         "KESIF": (ms("2023-04-07"), ms("2026-07-18"), f"{SP}/ikiz_kanit/ikiz_gercek.db")}
VARS = ["BASE", "W", "H", "W_S", "H_S", "W_E", "H_E"]


def gen():
    rows = []
    for coin in ESKI12:
        px, fu = load(coin)
        wk = weekly(px)
        for strat in ('W', 'H'):
            rows += simulate(coin, px, fu, wk, strat)
    d = pd.DataFrame(rows)
    d = d[(d.entry_ms >= GEN_FROM) & (d.entry_ms < GEN_TO_EXCL)].sort_values(['strat', 'coin', 'entry_ms'])
    d = d.reset_index(drop=True)
    d.to_csv(f'{OUT}/mom_trades.csv', index=False)
    # cross-check vs the verified implementation-A output (ESKI12 entries 2020-01-01 .. 2025-08-08)
    ref = pd.read_csv(f'{SP}/mom2_A/trades_detail.csv')
    ref = ref[ref.universe == 'ESKI12'].sort_values(['strat', 'coin', 'entry_ms']).reset_index(drop=True)
    mine = d[d.entry_ms < ms('2025-08-09')].reset_index(drop=True)
    cols = ['coin', 'strat', 'entry_ms', 'exit_ms', 'reason']
    same_keys = mine[cols].astype(str).equals(ref[cols].astype(str))
    num = ['entry', 'stop', 'exit', 'R_normal', 'R_stress', 'notional_over_risk']
    maxdiff = float(np.abs(mine[num].to_numpy() - ref[num].to_numpy()).max()) if same_keys else None
    # exits after 2025-08-08 in ref used the full data too -> must be identical
    # E-sensitivity trades (data cut at t_bit): trades still open at t_bit closed at the t_bit price
    ek = []
    for don, (t_bas, t_bit, _) in DONEM.items():
        for coin in ESKI12:
            px, fu = load(coin, t_cut=t_bit)
            wk = weekly(px)
            for strat in ('W', 'H'):
                for tdict in simulate(coin, px, fu, wk, strat):
                    if tdict['reason'] == 'eod' and tdict['entry_ms'] >= t_bas:
                        assert tdict['exit_ms'] == t_bit
                        tdict['donem'] = don
                        ek.append(tdict)
    pd.DataFrame(ek).to_csv(f'{OUT}/mom_trades_eod.csv', index=False)
    info = dict(n=len(d), by_strat=d.strat.value_counts().to_dict(), crosscheck_keys_identical=bool(same_keys),
                crosscheck_n=[len(mine), len(ref)], crosscheck_max_abs_diff=maxdiff, n_eod_at_tbit=len(ek),
                last_entry=str(pd.to_datetime(d.entry_ms.max(), unit='ms')),
                last_exit=str(pd.to_datetime(d.exit_ms.max(), unit='ms')))
    json.dump(info, open(f'{OUT}/gen_info.json', 'w'), indent=1)
    print(json.dumps(info, indent=1))


# --------------------------------------------------------------------------- bot (twin) trades
def ikiz_islemleri(db, t_bas, t_bit):
    """As scratchpad/aylik_tablo.py + trend_genislet_V/dogrula.py (squeeze removed; window a>=t_bas, z<t_bit)."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    satir = con.execute("select symbol, entry_price, quantity, entry_time, exit_time, pnl_usdt, strategy_scores "
                        "from trades").fetchall()
    con.close()
    kayit = []
    for sym, E, q, et, xt, pnl, sc in satir:
        js = json.loads(sc) if sc else {}
        if pnl is None or xt is None:
            continue
        sl0 = float(js.get("sl0") or 0.0)
        r = abs(E - sl0) * q
        if r <= 0:
            continue
        kayit.append(dict(sym=sym, kol=js.get("strategy"), a=int(pd.Timestamp(et).value // 10**6),
                          z=int(pd.Timestamp(xt).value // 10**6), R=pnl / r, notional=E * q, pnl=pnl))
    d = pd.DataFrame(kayit)
    zs = np.sort(d.z.to_numpy())
    pz = d.sort_values("z", kind="mergesort").pnl.to_numpy().cumsum()
    k = np.searchsorted(zs, d.a.to_numpy(), side="right")
    d["ikiz_bakiye"] = C0 + np.where(k > 0, pz[np.maximum(k - 1, 0)], 0.0)
    d["teminat_oran"] = d.notional / d.ikiz_bakiye / 10.0
    n_sq = int((d.kol == "squeeze").sum())
    d = d[d.kol != "squeeze"]
    d = d[(d.a >= t_bas) & (d.z < t_bit)].sort_values("a", kind="mergesort").reset_index(drop=True)
    return d, n_sq


def mom_rows(strat, t_bas, t_bit, rcol='R_normal', eod=None):
    d = pd.read_csv(f'{OUT}/mom_trades.csv')
    d = d[d.strat == strat].copy()
    if eod is not None:
        e = eod[eod.strat == strat].copy()
        e['exit_ms'] = t_bit - H4          # realized at the end of the last engine step (T = t_bit)
        d = pd.concat([d[d.exit_ms < t_bit], e], ignore_index=True)
    d = d[(d.entry_ms >= t_bas) & (d.exit_ms < t_bit)].copy()
    out = pd.DataFrame(dict(sym=d.coin.values, kol=f"mom_{strat}", a=d.entry_ms.astype('int64').values,
                            z=d.exit_ms.astype('int64').values,
                            R=d[rcol].values * (MOM_RISK / BL_BOT_RISK()),
                            R_raw=d[rcol].values, notional=np.nan, pnl=np.nan, ikiz_bakiye=np.nan,
                            teminat_oran=d.notional_over_risk.values * MOM_RISK / LEV,
                            entry=d.entry.values, atr=d.atr.values))
    return out


def BL_BOT_RISK():
    from research.trend_gelistirme import birlesik as BL
    return BL.BOT_RISK


def engine_source_check():
    from research.trend_gelistirme import birlesik as BL
    src = inspect.getsource(BL.MotorBirlesik._adim)
    assert BL.BOT_RISK == 0.035
    assert "self.bot_acik.append((int(r.z), BOT_RISK * deger0, tem, float(r.R)))" in src
    assert "gercek += R * risk" in src
    assert "tem = r.teminat_oran * deger0" in src
    assert "if self._toplam_teminat() + tem > 0.95 * deger0:" in src
    return True


def birim():
    """Numeric check: one 1 %-risk momentum trade -> equity change == R_normal * 1 % of equity."""
    from research.trend_gelistirme import birlesik as BL
    from research.trend_gelistirme.kos import MAL
    from research.trend_gelistirme.veri import yukle
    engine_source_check()
    veri, _ = yukle(["ETH"])
    t_bas, t_bit = ms("2020-02-01"), ms("2020-04-01")
    res = {}
    for Rn in (2.5, -1.0):
        bot = pd.DataFrame(dict(a=[ms("2020-02-03")], z=[ms("2020-02-10 08:00")], R=[Rn * MOM_RISK / BL.BOT_RISK],
                                teminat_oran=[0.3 * MOM_RISK / LEV]))
        m = BL.MotorBirlesik(veri, "ETH", "B0", MAL["NORMAL"], C0=C0, t_bas=t_bas, t_bit=t_bit, bot=bot,
                             risk=TREND_RISK, trend_kapali=True).kos()
        son = m.seri[-1][1]
        assert abs(son - C0 * (1 + Rn * MOM_RISK)) < 1e-6, (son, Rn)
        s = pd.DataFrame(m.seri, columns=["t", "deger", "a", "b", "c"])
        # realized exactly at the end of the exit step (T = z + 4h)
        ch = s[s.deger != C0].t.min()
        assert ch == ms("2020-02-10 12:00"), pd.to_datetime(ch, unit='ms')
        res[Rn] = son
    print("unit check OK:", res)
    return res


def kos(var, don):
    from research.trend_gelistirme import birlesik as BL
    from research.trend_gelistirme.kos import MAL
    from research.trend_gelistirme.veri import yukle, BOT12
    engine_source_check()
    t_bas, t_bit, db = DONEM[don]
    bot, n_sq = ikiz_islemleri(db, t_bas, t_bit)
    bot["R_raw"] = bot.R
    mom = None
    if var != "BASE":
        strat = var[0]
        rcol = 'R_stress' if var.endswith('_S') else 'R_normal'
        eod = None
        if var.endswith('_E'):
            e = pd.read_csv(f'{OUT}/mom_trades_eod.csv')
            eod = e[e.donem == don]
        mom = mom_rows(strat, t_bas, t_bit, rcol, eod)
        allb = pd.concat([bot, mom], ignore_index=True)
    else:
        allb = bot.copy()
    allb = allb.sort_values("a", kind="mergesort").reset_index(drop=True)
    veri, dis = yukle(BOT12)
    assert not dis
    m = BL.MotorBirlesik(veri, "ETH", "B0", MAL["NORMAL"], C0=C0, t_bas=t_bas, t_bit=t_bit, bot=allb,
                         risk=TREND_RISK).kos()
    seri = pd.DataFrame(m.seri, columns=["t", "deger", "acik_poz", "acik_risk", "teminat"])
    out = dict(var=var, don=don, t_bas=t_bas, t_bit=t_bit, seri=seri, islemler=pd.DataFrame(m.islemler),
               bot=bot, mom=mom, n_squeeze_removed=n_sq, bot_alinan=m.bot_alinan, bot_atlanan=m.bot_atlanan,
               n_bot_list=len(allb), acik_kalan_bot=len(m.bot_acik), acik_trend=sorted(m.poz),
               trend_acik=[dict(coin=k, giris_t=p.giris_t) for k, p in m.poz.items()])
    pickle.dump(out, open(f'{OUT}/R_{var}_{don}.pkl', 'wb'))
    print(var, don, "x", round(seri.deger.iloc[-1] / C0, 3), "bot_alinan", m.bot_alinan, "atlanan", m.bot_atlanan)


# ------------------------------------------------------------------------------- summary
def aylik(seri, col="deger"):
    s = seri.set_index(pd.to_datetime(seri.t, unit="ms"))[col].resample("ME").last()
    return pd.concat([pd.Series([C0], index=[s.index[0] - pd.offsets.MonthEnd(1)]), s])


def olc(s):
    yil = (s.index[-1] - s.index[0]).days / 365.25
    carpan = s.iloc[-1] / C0
    cagr = carpan ** (1 / yil) - 1
    dd = float((1 - s / s.cummax()).max())
    return dict(mult=float(carpan), cagr=float(cagr), maxdd=float(dd), ratio=float(cagr / dd))


def yillik(s):
    y = {}
    for yr in sorted(set(s.index.year)):
        prev = s[s.index.year < yr]
        b = prev.iloc[-1] if len(prev) else C0
        e = s[s.index.year == yr].iloc[-1]
        y[int(yr)] = round(float(e / b), 4)
    return y


def mtm_seri(r, PX):
    """Post-hoc: add the momentum sleeve's open (unrealized, price-only) PnL to the engine series."""
    seri, mom = r["seri"], r["mom"]
    T = seri.t.to_numpy()
    V = seri.deger.to_numpy()
    adj = np.zeros(len(T))
    for x in mom.itertuples():
        k = np.searchsorted(T, x.a, 'right') - 1
        d0 = V[k] if k >= 0 else C0
        risk = MOM_RISK * d0
        m = (T >= x.a + H4) & (T <= x.z)
        if not m.any():
            continue
        t4, c4 = PX[x.sym]
        j = np.searchsorted(t4, T[m] - H4, 'right') - 1
        c = c4[np.maximum(j, 0)]
        adj[m] += risk * (c / x.entry - 1.0) / (ATR_K * x.atr / x.entry)
    s2 = seri.copy()
    s2["deger"] = V + adj
    return s2


def week_id(msv):
    return (np.asarray(msv, dtype=np.int64) - 4 * 86400000) // WEEK     # Monday-aligned weeks


def wsum(ids, R, allw):
    s = pd.Series(R).groupby(ids).sum()
    return s.reindex(allw, fill_value=0.0).to_numpy()


def ozet():
    eng_ok = engine_source_check()
    R = {}
    for don in DONEM:
        for v in VARS:
            p = f'{OUT}/R_{v}_{don}.pkl'
            if os.path.exists(p):
                R[(v, don)] = pickle.load(open(p, 'rb'))
    PX = {}
    for coin in ESKI12:
        px, _ = load(coin)
        PX[coin] = (px.open_time.to_numpy(), px.close.to_numpy(float))
    L = []
    P = lambda *a: L.append(" ".join(str(x) for x in a))
    res = dict(engine_source_check=eng_ok, gen=json.load(open(f'{OUT}/gen_info.json')), metrics={}, verdict={},
               corr={}, concurrency={}, yearly={}, sleeve={}, sens={})
    P("== Criterion 2: month-end series (C0 prepended); ratio = CAGR / maxDD ==")
    P(f"{'period':9s} {'variant':6s} {'mult':>9s} {'CAGR%':>8s} {'maxDD%':>7s} {'ratio':>7s} {'momN':>5s} "
      f"{'botN':>5s} {'alinan':>6s} {'atlanan':>7s} {'trendN':>6s} {'momPnL':>12s} {'mtm_maxDD%':>10s} {'mtm_ratio':>9s}")
    for don in DONEM:
        for v in VARS:
            if (v, don) not in R:
                continue
            r = R[(v, don)]
            s = aylik(r["seri"])
            mt = olc(s)
            mom = r["mom"]
            momn = 0 if mom is None else len(mom)
            row = dict(**mt, mom_n=momn, bot_n=len(r["bot"]), bot_alinan=r["bot_alinan"], bot_atlanan=r["bot_atlanan"],
                       trend_n=len(r["islemler"]), n_squeeze_removed=r["n_squeeze_removed"],
                       first_t=str(pd.to_datetime(r["seri"].t.iloc[0], unit='ms')),
                       last_t=str(pd.to_datetime(r["seri"].t.iloc[-1], unit='ms')))
            if mom is not None and momn:
                sm = olc(aylik(mtm_seri(r, PX)))
                row["mtm"] = sm
                T_, V_ = r["seri"].t.to_numpy(), r["seri"].deger.to_numpy()
                k_ = np.searchsorted(T_, mom.a.to_numpy(), 'right') - 1
                d0_ = np.where(k_ >= 0, V_[np.maximum(k_, 0)], C0)
                row["mom_pnl_usd"] = float((mom.R_raw.to_numpy() * MOM_RISK * d0_).sum())
                row["mom_pnl_share_of_final"] = row["mom_pnl_usd"] / float(V_[-1])
            res["metrics"][f"{v}|{don}"] = row
            res["yearly"][f"{v}|{don}"] = yillik(s)
            mtm = row.get("mtm", {})
            P(f"{don:9s} {v:6s} {mt['mult']:9.3f} {mt['cagr']*100:8.1f} {mt['maxdd']*100:7.2f} {mt['ratio']:7.3f} "
              f"{momn:5d} {len(r['bot']):5d} {r['bot_alinan']:6d} {r['bot_atlanan']:7d} {len(r['islemler']):6d} "
              f"{row.get('mom_pnl_usd', 0.0):12.0f} {mtm.get('maxdd', float('nan'))*100:10.2f} {mtm.get('ratio', float('nan')):9.3f}")
    # sanity
    b = res["metrics"].get("BASE|KESIF")
    if b:
        res["sanity_BASE_KESIF"] = dict(mult=round(b["mult"], 3), maxdd=round(b["maxdd"] * 100, 2),
                                        ok=bool(abs(b["mult"] - 116.467) < 0.05 and abs(b["maxdd"] * 100 - 28.94) < 0.05))
        P(f"SANITY BASE KESIF x{b['mult']:.3f} maxDD {b['maxdd']*100:.2f}% (expect x116.467 / 28.94%) -> "
          f"{'OK' if res['sanity_BASE_KESIF']['ok'] else 'MISMATCH'}")
    bb = res["metrics"].get("BASE|BAGIMSIZ")
    if bb:
        P(f"cross-ref BASE BAGIMSIZ x{bb['mult']:.3f} maxDD {bb['maxdd']*100:.2f}% (trend_genislet_V T12 BAGIMSIZ: x42.160 / 58.67%)")
    # verdicts
    P("")
    P("== Criterion 2 verdict (both periods: ratio > BASE AND mult > BASE AND maxDD <= BASE + 3 pt) ==")
    for v in ("W", "H", "W_S", "H_S", "W_E", "H_E"):
        det, ok = {}, True
        for don in DONEM:
            x, b0 = res["metrics"].get(f"{v}|{don}"), res["metrics"].get(f"BASE|{don}")
            if x is None or b0 is None:
                ok = False
                continue
            c = dict(ratio_up=x["ratio"] > b0["ratio"], mult_up=x["mult"] > b0["mult"],
                     dd_ok=(x["maxdd"] - b0["maxdd"]) * 100 <= 3.0)
            det[don] = dict(**{k: bool(vv) for k, vv in c.items()}, d_ratio=round(x["ratio"] - b0["ratio"], 3),
                            mult_x_over_base=round(x["mult"] / b0["mult"], 4),
                            d_maxdd_pt=round((x["maxdd"] - b0["maxdd"]) * 100, 2))
            ok = ok and all(c.values())
        res["verdict" if v in ("W", "H") else "sens"][v] = dict(PASS=bool(ok), detail=det)
        P(f"{v:4s} {'PASS' if ok else 'FAIL'}  " + " | ".join(
            f"{d}: ratio {'Y' if q['ratio_up'] else 'N'} ({q['d_ratio']:+.3f}) mult {'Y' if q['mult_up'] else 'N'} "
            f"(x{q['mult_x_over_base']:.3f}) DD {'Y' if q['dd_ok'] else 'N'} ({q['d_maxdd_pt']:+.2f}pt)"
            for d, q in det.items()) + ("" if v in ("W", "H") else "   [sensitivity, not decisional]"))
    # weekly correlation, concurrency, sleeve stats
    P("")
    P("== Weekly R-sum Pearson correlation (all Monday-weeks of the period, empty = 0; sleeve R_normal unscaled) ==")
    for don, (t_bas, t_bit, _) in DONEM.items():
        base = R.get(("BASE", don))
        if base is None:
            continue
        allw = np.arange(week_id([t_bas])[0], week_id([t_bit - 1])[0] + 1)
        bot = base["bot"]
        don_t = bot[bot.kol == "donchian"]
        mr_t = bot[bot.kol == "mean_rev"]
        tr = base["islemler"].copy()
        tr["R"] = tr.pnl / tr.ilk_risk
        for v in ("W", "H"):
            r = R.get((v, don))
            if r is None:
                continue
            mom = r["mom"]
            cc = {}
            for key, cm, cb, ct in (("exit_week", "z", "z", "cikis_t"), ("entry_week", "a", "a", "giris_t")):
                xm = wsum(week_id(mom[cm]), mom.R_raw.to_numpy(), allw)
                xd = wsum(week_id(don_t[cb]), don_t.R.to_numpy(), allw)
                xr = wsum(week_id(mr_t[cb]), mr_t.R.to_numpy(), allw)
                xt = wsum(week_id(tr[ct]), tr.R.to_numpy(), allw)
                xb = wsum(week_id(bot[cb]), bot.R.to_numpy(), allw)
                cc[key] = dict(donchian=float(np.corrcoef(xm, xd)[0, 1]), trend=float(np.corrcoef(xm, xt)[0, 1]),
                               mean_rev=float(np.corrcoef(xm, xr)[0, 1]), bot_all=float(np.corrcoef(xm, xb)[0, 1]),
                               donchian_vs_trend=float(np.corrcoef(xd, xt)[0, 1]))
            cc["n_weeks"] = int(len(allw))
            res["corr"][f"{v}|{don}"] = cc
            P(f"{don:9s} {v}: exit-week  donchian {cc['exit_week']['donchian']:+.3f} trend {cc['exit_week']['trend']:+.3f}"
              f" (mean_rev {cc['exit_week']['mean_rev']:+.3f}, bot {cc['exit_week']['bot_all']:+.3f}; donchian~trend "
              f"{cc['exit_week']['donchian_vs_trend']:+.3f}) | entry-week donchian {cc['entry_week']['donchian']:+.3f} "
              f"trend {cc['entry_week']['trend']:+.3f}  [weeks {len(allw)}]")
            # concurrency on the 4h grid of the period
            grid = np.arange(t_bas, t_bit, H4)

            def cnt(a, z):
                a, z = np.sort(np.asarray(a)), np.sort(np.asarray(z))
                return np.searchsorted(a, grid, 'right') - np.searchsorted(z, grid, 'right')
            tz = tr.cikis_t.to_numpy()
            ta = tr.giris_t.to_numpy()
            if base["trend_acik"]:
                ta = np.r_[ta, [x["giris_t"] for x in base["trend_acik"]]]
                tz = np.r_[tz, [t_bit + H4] * len(base["trend_acik"])]
            cm_, cb_, ct_ = cnt(mom.a, mom.z), cnt(bot.a, bot.z), cnt(ta, tz)
            # same-coin overlap: share of momentum position-time where the same coin has a trend position
            pt_same, pt_all = 0, 0
            trc = pd.concat([tr[["coin", "giris_t", "cikis_t"]],
                             pd.DataFrame([dict(coin=x["coin"], giris_t=x["giris_t"], cikis_t=t_bit + H4)
                                           for x in base["trend_acik"]])], ignore_index=True) \
                if base["trend_acik"] else tr[["coin", "giris_t", "cikis_t"]]
            for x in mom.itertuples():
                g = np.arange(x.a, x.z, H4) if x.z > x.a else np.array([x.a])
                pt_all += len(g)
                tt = trc[trc.coin == x.sym]
                if len(tt):
                    inn = np.zeros(len(g), bool)
                    for y in tt.itertuples():
                        inn |= (g >= y.giris_t) & (g < y.cikis_t)
                    pt_same += int(inn.sum())
            cr = dict(mom_mean=round(float(cm_.mean()), 3), mom_max=int(cm_.max()),
                      mom_share_time_any=round(float((cm_ > 0).mean()), 4),
                      bot_mean=round(float(cb_.mean()), 3), trend_mean=round(float(ct_.mean()), 3),
                      total_mean=round(float((cm_ + cb_ + ct_).mean()), 3), total_max=int((cm_ + cb_ + ct_).max()),
                      share_time_mom_and_trend=round(float(((cm_ > 0) & (ct_ > 0)).mean()), 4),
                      share_mom_postime_same_coin_trend=round(pt_same / pt_all, 4) if pt_all else None)
            res["concurrency"][f"{v}|{don}"] = cr
            P(f"           concurrency: mom mean {cr['mom_mean']} max {cr['mom_max']} (any {cr['mom_share_time_any']:.0%}); "
              f"trend mean {cr['trend_mean']}; bot mean {cr['bot_mean']}; total mean {cr['total_mean']} max {cr['total_max']}; "
              f"mom&trend both {cr['share_time_mom_and_trend']:.0%}; mom pos-time with same-coin trend "
              f"{cr['share_mom_postime_same_coin_trend']}")
            # sleeve stats + realized PnL contribution in the combined run
            yr = pd.to_datetime(mom.a, unit='ms').dt.year
            g = mom.groupby(yr).R_raw.agg(['count', 'mean', 'sum'])
            res["sleeve"][f"{v}|{don}"] = dict(n=int(len(mom)), meanR=float(mom.R_raw.mean()), sumR=float(mom.R_raw.sum()),
                                               win=float((mom.R_raw > 0).mean()),
                                               yearly={int(k): [int(a), round(float(b), 3), round(float(c), 2)]
                                                       for k, (a, b, c) in g.iterrows()})
            P(f"           sleeve: n {len(mom)} meanR {mom.R_raw.mean():+.3f} sumR {mom.R_raw.sum():+.1f} win "
              f"{(mom.R_raw > 0).mean():.0%} | by entry year [n, meanR, sumR]: " +
              ", ".join(f"{k}:{list(x)}" for k, x in res['sleeve'][f'{v}|{don}']['yearly'].items()))
    P("")
    P("== Yearly multipliers (calendar year, month-end) ==")
    for don in DONEM:
        for v in VARS:
            if f"{v}|{don}" in res["yearly"]:
                P(f"{don:9s} {v:5s} " + "  ".join(f"{k}:{x:.3f}" for k, x in res["yearly"][f"{v}|{don}"].items()))
    # monthly series out
    for (v, don), r in R.items():
        aylik(r["seri"]).to_csv(f"{OUT}/aylik_{v}_{don}.csv", header=["deger"])
    json.dump(res, open(f'{OUT}/results.json', 'w'), indent=1, default=str)
    txt = "\n".join(L)
    open(f'{OUT}/report.txt', 'w').write(txt + "\n")
    print(txt)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "gen":
        gen()
    elif cmd == "birim":
        birim()
    elif cmd == "kos":
        kos(sys.argv[2], sys.argv[3])
    elif cmd == "ozet":
        ozet()
