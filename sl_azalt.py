"""
sl_azalt.py — "TP'ye DOKUNMADAN stopu geriye çek: SL sayısı düşer mi, buna değer mi?"

Kullanıcının sorusu tam olarak bu ve DAHA ÖNCE BU BİÇİMDE SORULMADI.
`cikis_tara.py` (sl_atr × rr × max_hold) ızgarası stop'u genişletirken TP'yi de
ORANTILI genişletiyordu, çünkü rr stop'un KATIDIR. Burada TP fiyat cinsinden
SABİT tutuluyor: sl_atr büyürken rr = (TP_mesafesi / sl_atr) ile küçültülüyor.

Yani: aynı hedef, daha uzak stop. SL'e giden işlem sayısı DÜŞMELİ.
Soru, düşen SL sayısının kârı koruyup korumadığı.

⚠ NEDEN BEDAVA DEĞİL: stop genişlerse aynı dolar riski için POZİSYON KÜÇÜLÜR
   (qty = risk$ / stop_mesafesi). Yani daha az SL yeriz ama her kazançtan da
   daha az kazanırız. R cinsinden RR düşer. Net etki ölçülmeli, varsayılmamalı.

⚠ MEVCUT DEĞERLER KAYNAKTAN OKUNUR, elle yazılmaz.

Kullanım:  py sl_azalt.py local
"""
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
from indicators import atr as atr_fn, adx as adx_fn


def uret(sleeve, m, sl_a, rr, mh):
    """A.gen ile birebir, ama sl_atr ve rr dışarıdan verilir."""
    tf, win, _, _, _ = A.CFG[sleeve]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
    from strategies.donchian import DonchianStrategy
    from strategies.squeeze import SqueezeStrategy
    s = (DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve == "donchian" else
         SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    hi, lo, cl, idx, n = d["high"].values, d["low"].values, d["close"].values, d.index, len(d)
    out = []; occ = -1
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        if sleeve == "squeeze":
            xv = adx_ser[i] if np.isfinite(adx_ser[i]) else 20.0
            if xv <= 20.0: continue
        sg = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)); d_ = sg.direction
        if d_ == 0 or i <= occ: continue
        if sleeve == "donchian":
            dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
            if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue
        e = cl[i]; sld = sl_a * a; slp_ = e - d_ * sld; tp = e + d_ * rr * sld
        ep = None; j = i; cik = None
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp_: ep = slp_; cik = "sl"; break
                if hi[j] >= tp:   ep = tp;   cik = "tp"; break
            else:
                if hi[j] >= slp_: ep = slp_; cik = "sl"; break
                if lo[j] <= tp:   ep = tp;   cik = "tp"; break
        if ep is None:
            j = min(i + mh, n - 1); ep = cl[j]; cik = "sure"
        R = d_ * (ep - e) / sld - 2 * A.FEE * e / sld
        out.append((idx[i].value, idx[j], R, sld / e, cik)); occ = j
    return out


def koltuk(ham):
    import heapq
    ev = sorted(ham, key=lambda t: t[0]); oh = []; tk = []; ctr = 0
    for e, x, R, s, c in ev:
        while oh and oh[0][0].value <= e: heapq.heappop(oh)
        if len(oh) < A.MAXPOS:
            ctr += 1; heapq.heappush(oh, (x, ctr, R)); tk.append((x, R, s, c))
    return sorted(tk, key=lambda t: t[0])


def kos(source, carp):
    """carp = stop genişletme katsayısı. TP mesafesi SABİT kalır."""
    ham = []
    for c in A.DONCH:
        tf, win, sl_a, rr, mh = A.CFG["donchian"]
        hedef = sl_a * rr                      # TP mesafesi, ATR cinsinden — SABİT
        ham += uret("donchian", fast_bt.load(c, source=source),
                    sl_a * carp, hedef / (sl_a * carp), mh)
    for c in A.SQZ:
        tf, win, sl_a, rr, mh = A.CFG["squeeze"]
        hedef = sl_a * rr
        ham += uret("squeeze", fast_bt.load(c, source=source),
                    sl_a * carp, hedef / (sl_a * carp), mh)
    for c in A.BB_COINS:
        ham += [(t[0], t[1], t[2], t[3], "bb") for t in A.gen_bb(fast_bt.load(c, source=source))]
    tk = koltuk(ham)
    R = np.array([x[1] for x in tk]); sp = np.array([x[2] for x in tk])
    ex = pd.to_datetime([x[0] for x in tk]); cik = np.array([x[3] for x in tk])
    eff = np.minimum(A.CANLI_RISKF, A.CANLI_CAP * sp)
    pnl = R * eff * A.BAL0
    eq = A.BAL0 + np.cumsum(pnl)
    ay = pd.Series(pnl, index=ex.tz_localize(None).to_period("M")).groupby(level=0).sum() / A.BAL0 * 100
    return {"n": len(tk), "kar": pnl.sum(), "dd": A.maxdd(np.concatenate([[A.BAL0], eq])),
            "kotu": ay.min(), "sl": (cik == "sl").mean() * 100, "tp": (cik == "tp").mean() * 100,
            "sure": (cik == "sure").mean() * 100, "wr": (R > 0).mean() * 100,
            "stop": sp.mean() * 100,
            "pf": pnl[pnl > 0].sum() / max(-pnl[pnl < 0].sum(), 1e-9)}


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    _, _, sl_a, rr, _ = A.CFG["donchian"]
    print(f"\n{'=' * 104}")
    print(f"=== STOPU GERİYE ÇEK, TP'Yİ YERİNDE BIRAK ===")
    print(f"  donchian bugün: stop {sl_a}×ATR · TP {sl_a*rr:.1f}×ATR (rr {rr})")
    print(f"  ⚠ stop genişlerse pozisyon KÜÇÜLÜR (aynı dolar riski) → kazançlar da küçülür\n")
    print(f"  {'stop×':>6s} {'yeni rr':>8s} {'işlem':>6s} {'SL%':>6s} {'TP%':>6s} {'süre%':>6s} "
          f"{'WR%':>6s} {'PF':>5s} {'kâr $':>10s} {'Δ$':>9s} {'maxDD':>7s} {'en kötü ay':>11s}")
    taban = None
    for carp in (1.0, 1.25, 1.5, 1.75, 2.0):
        r = kos(source, carp)
        if taban is None: taban = r["kar"]
        print(f"  {sl_a*carp:>5.2f}× {rr/carp:>8.3f} {r['n']:>6d} {r['sl']:>5.1f}% {r['tp']:>5.1f}% "
              f"{r['sure']:>5.1f}% {r['wr']:>5.1f}% {r['pf']:>5.2f} {r['kar']:>+10.2f} "
              f"{r['kar']-taban:>+9.2f} {r['dd']:>6.2f}% {r['kotu']:>10.2f}%")
    print(f"\n  ⓘ SL% düşüyorsa kullanıcının istediği olmuş demektir. Δ$ ve en kötü aya bak:")
    print(f"    SL azalması KÂRA mal oluyorsa, 'çok SL yemek' bir sorun değil bir MALİYETTİR.")
    print(f"{'=' * 104}\n")


if __name__ == "__main__":
    main()
