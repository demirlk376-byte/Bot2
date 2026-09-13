"""
denetim_esdegerlik.py — GECICI DENETIM ARACI (uretim kodunu DEGISTIRMEZ).
deployed_backtest.py (ANKOR) ile CANLI cagri sozlesmesi arasindaki farklari
TEK GECISTE olcer. Sinyal kumesi occ'den bagimsiz oldugu icin (gen() analyze'i
her barda cagirir, occ'yi SONRA kontrol eder) once tum sinyaller onbelleklenir,
sonra her varyant icin kapi+occ+koltuk ucuza uygulanir.

Varyantlar:
  V0  ankor (deployed_backtest ile birebir)
  V1  donchian gunluk-EMA20 MTF kapisi KAPALI  (DONCHIAN_MTF varsayilani False)
  V2  pencere-yerel ATR/ADX (canli get_candles(260)/(120) gibi)
  V3  BB hafta-sonu kapisi bar KAPANIS saatine gore (canli wall-clock)
  V4  ucret duyarliligi (1bp / 2bp / 4bp tek taraf)
  V5  CANLI olcek (CAP=1.50, RISKF=0.028) dogrulamasi
"""
import sys, heapq, pickle, os
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy
import deployed_backtest as DB

CACHE = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/sig_cache.pkl"


def raw_signals(sleeve, m, coin):
    """Tum barlarda sinyal + yardimci diziler. KAPI YOK (kapilar sonra uygulanir)."""
    tf, win, sl_a, rr, mh = DB.CFG[sleeve]
    d = fast_bt.resample(m, tf)
    atr_full = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_full = adx_fn(d["high"], d["low"], d["close"], 14).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
    s = (DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve == "donchian" else
         SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    n = len(d)
    sigs = []
    for i in range(260, n - 1):
        a = atr_full[i]
        if not np.isfinite(a) or a <= 0:
            continue
        sub = d.iloc[max(0, i - win):i + 1]
        sg = s.analyze(sub, float(a))
        if sg.direction == 0:
            continue
        # canli-tarzi pencere-yerel gostergeler (YALNIZ sinyal barlarinda: ucuz)
        a_win = float(atr_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1])
        x_win = float(adx_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1])
        sigs.append(dict(i=i, dir=int(sg.direction), atr_full=float(a), atr_win=a_win,
                         adx_full=float(adx_full[i]) if np.isfinite(adx_full[i]) else 20.0,
                         adx_win=x_win if np.isfinite(x_win) else 20.0,
                         up=bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True))
    return d, sigs


def raw_bb(m, coin):
    from indicators import bollinger_bands
    from strategies.mean_reversion import MeanReversionStrategy
    from config import load_config
    s = MeanReversionStrategy(load_config().strategy)
    d = fast_bt.resample(m, DB.BB_TF)
    cl = d["close"].values; n = len(cl); idx = d.index
    up_b, _mid, lo_b = bollinger_bands(d["close"], 20, 2.0)
    outside = (cl < lo_b.values) | (cl > up_b.values)
    volma = d["volume"].rolling(20).mean().values
    volok = ~(np.isfinite(volma) & (d["volume"].values < volma))
    sigs = []
    for i in np.where(outside & volok)[0]:
        i = int(i)
        if i < 260 or i >= n - 1:
            continue
        sub = d.iloc[max(0, i - 119):i + 1]
        av = atr_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if not np.isfinite(av) or av <= 0:
            continue
        adxr = adx_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        adxv = float(adxr) if np.isfinite(adxr) else 20.0
        dd = s.analyze(sub).direction
        if dd == 0:
            continue
        sigs.append(dict(i=i, dir=int(dd), atr_full=float(av), atr_win=float(av),
                         adx_full=adxv, adx_win=adxv,
                         wd_open=int(idx[i].weekday()),
                         wd_close=int((idx[i] + pd.Timedelta(hours=1)).weekday())))
    return d, sigs


def simulate(d, sigs, sleeve, *, mtf_on, win_local, bb_close_gate, coin):
    """Kapilari uygula + occ zinciri + cikis simulasyonu. Ham R (ucretsiz) dondurur."""
    if sleeve == "bb":
        sl_a, rr, mh = DB.BB_SL_ATR, DB.BB_RR, DB.BB_MH
    else:
        _tf, _w, sl_a, rr, mh = DB.CFG[sleeve]
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    out = []; occ = -1
    for g in sigs:
        i = g["i"]
        if i <= occ:
            continue
        if sleeve == "squeeze":
            xv = g["adx_win"] if win_local else g["adx_full"]
            if xv <= 20.0:
                continue
        if sleeve == "donchian" and mtf_on:
            if not ((g["dir"] == 1 and g["up"]) or (g["dir"] == -1 and not g["up"])):
                continue
        if sleeve == "bb":
            wd = g["wd_close"] if bb_close_gate else g["wd_open"]
            if wd < 5:
                continue
            if (g["adx_win"] if win_local else g["adx_full"]) >= DB.BB_ADX_MAX:
                continue
        d_ = g["dir"]; a = g["atr_win"] if win_local else g["atr_full"]
        e = cl[i]; sld = sl_a * a; slp = e - d_ * sld; tp = e + d_ * rr * sld
        ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None:
            j = min(i + mh, n - 1); ep = cl[j]
        Rraw = d_ * (ep - e) / sld
        hours = (idx[j] - idx[i]).total_seconds() / 3600.0
        out.append(dict(entry_ns=idx[i].value, exit_ts=idx[j], Rraw=Rraw,
                        slp=sld / e, e_over_sld=e / sld, hours=hours,
                        coin=coin, sleeve=sleeve, dir=d_))
        occ = j
    return out


def seat(trades, maxpos=7):
    ev = sorted(trades, key=lambda t: t["entry_ns"]); openh = []; taken = []; ctr = 0
    for t in ev:
        while openh and openh[0][0].value <= t["entry_ns"]:
            heapq.heappop(openh)
        if len(openh) < maxpos:
            ctr += 1
            heapq.heappush(openh, (t["exit_ts"], ctr, 0))
            taken.append(t)
    return sorted(taken, key=lambda t: t["exit_ts"])


def book(taken, fee=0.0001, riskf=0.0225, cap=1.25, bal0=190.0):
    R = np.array([t["Rraw"] - 2 * fee * t["e_over_sld"] for t in taken])
    slp = np.array([t["slp"] for t in taken])
    eff = np.minimum(riskf, cap * slp)
    pnl = R * eff * bal0
    eq = bal0 + np.cumsum(pnl)
    peak = np.maximum.accumulate(np.concatenate([[bal0], eq]))
    dd = ((peak - np.concatenate([[bal0], eq])) / peak).max() * 100
    exits = [pd.Timestamp(t["exit_ts"]) for t in taken]
    dfm = pd.DataFrame({"pnl": pnl, "m": [x.tz_localize(None).to_period("M") for x in exits]})
    mon = dfm.groupby("m")["pnl"].sum() / bal0 * 100
    return dict(n=len(R), meanR=R.mean(), tot=pnl.sum(), dd=dd, worst=mon.min(),
                pf=R[R > 0].sum() / max(-R[R < 0].sum(), 1e-9), wr=(R > 0).mean() * 100)


def main():
    if os.path.exists(CACHE):
        allsig = pickle.load(open(CACHE, "rb"))
        print(f"  onbellek okundu: {CACHE}")
    else:
        allsig = {}
        for c in DB.DONCH:
            print(f"  donchian {c} ...", flush=True)
            d, s = raw_signals("donchian", fast_bt.load(c, source="local"), c)
            allsig[("donchian", c)] = (d, s)
        for c in DB.SQZ:
            print(f"  squeeze {c} ...", flush=True)
            d, s = raw_signals("squeeze", fast_bt.load(c, source="local"), c)
            allsig[("squeeze", c)] = (d, s)
        for c in DB.BB_COINS:
            print(f"  bb {c} ...", flush=True)
            d, s = raw_bb(fast_bt.load(c, source="local"), c)
            allsig[("bb", c)] = (d, s)
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        pickle.dump(allsig, open(CACHE, "wb"))
        print(f"  onbellek yazildi: {CACHE}")

    def build(mtf_on=True, win_local=False, bb_close_gate=False):
        tr = []
        for (sl, c), (d, s) in allsig.items():
            tr += simulate(d, s, sl, mtf_on=mtf_on, win_local=win_local,
                           bb_close_gate=bb_close_gate, coin=c)
        return seat(tr)

    print("\n" + "=" * 78)
    variants = {
        "V0 ANKOR (mtf ON, tam-seri gosterge, BB gate=bar acilisi)":
            dict(mtf_on=True, win_local=False, bb_close_gate=False),
        "V1 donchian MTF KAPALI (DONCHIAN_MTF=false -> canli varsayilan)":
            dict(mtf_on=False, win_local=False, bb_close_gate=False),
        "V2 pencere-yerel ATR/ADX (canli get_candles)":
            dict(mtf_on=True, win_local=True, bb_close_gate=False),
        "V3 BB hafta-sonu kapisi bar KAPANISINA gore (canli wall-clock)":
            dict(mtf_on=True, win_local=False, bb_close_gate=True),
        "V4 V1+V2+V3 hepsi (canli varsayilanlarina en yakin)":
            dict(mtf_on=False, win_local=True, bb_close_gate=True),
    }
    res = {}
    for name, kw in variants.items():
        tk = build(**kw)
        b = book(tk)
        res[name] = (tk, b)
        print(f"{name}\n   n={b['n']:4d}  ortR {b['meanR']:+.4f}  PF {b['pf']:.3f}  "
              f"WR {b['wr']:.1f}%  toplam ${b['tot']:+.2f}  maxDD {b['dd']:.2f}%  "
              f"en kotu ay {b['worst']:+.2f}%")

    base_tk, base_b = res["V0 ANKOR (mtf ON, tam-seri gosterge, BB gate=bar acilisi)"]

    print("\n--- UCRET DUYARLILIGI (V0 islem kumesi, cap=1.25 riskf=0.0225) ---")
    for f in (0.0, 0.0001, 0.0002, 0.0004):
        b = book(base_tk, fee=f)
        print(f"   fee {f*1e4:.0f}bp/taraf -> ortR {b['meanR']:+.4f}  toplam ${b['tot']:+.2f}")

    print("\n--- CANLI OLCEK DOGRULAMA (CAP=1.50, RISKF=0.028) ---")
    for nm, (tk, _) in res.items():
        b = book(tk, cap=DB.CANLI_CAP, riskf=DB.CANLI_RISKF)
        print(f"   {nm[:42]:42s} ${b['tot']:+.2f}  maxDD {b['dd']:.2f}%  en kotu ay {b['worst']:+.2f}%")

    print("\n--- STOP MESAFESI DAGILIMI (kaymanin R bedeli icin) ---")
    slp = np.array([t["slp"] for t in base_tk])
    print(f"   medyan {np.median(slp)*100:.3f}%  ort {slp.mean()*100:.3f}%  "
          f"p10 {np.percentile(slp,10)*100:.3f}%  p90 {np.percentile(slp,90)*100:.3f}%")
    print(f"   15.85bp kaymanin ort R bedeli (tek taraf) = {0.001585/slp.mean():.4f}R, "
          f"cift taraf {2*0.001585/slp.mean():.4f}R")

    print("\n--- TUTMA SURESI (funding maliyeti icin) ---")
    hrs = np.array([t["hours"] for t in base_tk])
    print(f"   ort {hrs.mean():.1f}h  medyan {np.median(hrs):.1f}h  toplam {hrs.sum():.0f}h")
    for sl in ("donchian", "squeeze", "bb"):
        h = np.array([t["hours"] for t in base_tk if t["sleeve"] == sl])
        if len(h):
            print(f"   {sl:9s} n={len(h):4d} ort {h.mean():6.1f}h  toplam {h.sum():8.0f}h")

    pickle.dump({k: v[0] for k, v in res.items()},
                open(CACHE.replace("sig_cache", "variant_trades"), "wb"))


if __name__ == "__main__":
    main()
