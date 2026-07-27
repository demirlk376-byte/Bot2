"""
partial_tp_test.py — KISMİ TP (scale-out): chop'ta kazancın bir kısmını cebe koy.

NEDEN BU (yeni bulguya dayanıyor): negatif aylarda ort KAYIP değişmiyor (−0.94R vs −0.95R),
KAZANÇ küçülüyor (1.56R vs 1.91R) ve WR düşüyor (%34 vs %48). Yani sorun "SL'ler" değil,
"TP'ye ulaşamamak". Fiyat lehimize gidip 2.5R'ye varmadan dönüyorsa, yolun bir kısmını
bankaya yatırabilir miyiz?

Trailing/BE'den FARKLI: trailing stop'u oynatır (elenmişti); kısmi TP GERÇEK kâr realize eder.
Chop'ta 1R'ye değip dönen işlem: tam −1R yerine (0.5×+1R) + (0.5×−1R) = 0 olur.

VARYANTLAR (TP2 = 2.5R sabit, SL = 2×ATR sabit — canlı config değişmiyor):
  baseline        : tamamı 2.5R'de
  p50@1R          : %50'si 1R'de, kalanı 2.5R'de (kalan orijinal SL'i korur)
  p50@1R+BE       : %50'si 1R'de, kalan BAŞABAŞ stop'a çekilir
  p33@1R / p67@1R : farklı oranlar
  p50@1.5R        : daha uzak kısmi hedef
  p50@1.5R+BE

DÜRÜST BEKLENTİ: trend sistemlerinde scale-out genelde toplam kârı DÜŞÜRÜR (büyük kazananlar
kırpılır, onlar edge'i taşır). Ama hiç test edilmedi ve keşfedilen mekanizmayı hedefliyor.
KARAR KURALI: toplam $ VE PF'i HER YIL koruyup artırmalı. Sadece WR/en-kötü-ay iyileşip toplam
düşüyorsa → takas, iyileştirme değil → RED.

Mum-içi belirsizlik: aynı barda hem hedef hem SL varsa MUHAFAZAKÂR (SL önce) — diğer araçlarla aynı.

Kullanım:  py partial_tp_test.py local
"""
import sys, heapq
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAL0 = 190.0; FEE = 0.0001; RISKF = 0.0225; CAP = 1.0; MAXPOS = 7
DONCH = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB"]
SQZ = ["XRP", "DOGE", "TRX", "XLM"]
CFG = {"donchian": ("4h", 259, 2.0, 2.5, 30), "squeeze": ("1h", 119, 2.0, 2.5, 48)}
# (isim, kısmi_oran, kısmi_hedef_R, kalan_BE_mi)
VARIANTS = [
    ("baseline",    0.0,  0.0, False),
    ("p33@1R",      0.33, 1.0, False),
    ("p50@1R",      0.50, 1.0, False),
    ("p67@1R",      0.67, 1.0, False),
    ("p50@1R+BE",   0.50, 1.0, True),
    ("p50@1.5R",    0.50, 1.5, False),
    ("p50@1.5R+BE", 0.50, 1.5, True),
]


def prep(sleeve, m):
    tf, win, sl_a, rr, mh = CFG[sleeve]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    s = (DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve == "donchian" else
         SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    # sinyal akışı bir kez (varyanttan bağımsız — giriş kuralı değişmiyor)
    cl = d["close"].values; n = len(cl); dirs = np.zeros(n, dtype=int)
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        if sleeve == "squeeze":
            xv = adx_ser[i] if np.isfinite(adx_ser[i]) else 20.0
            if xv <= 20.0: continue
        dirs[i] = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)).direction
    return dict(d=d, atr=atr_ser, dirs=dirs, hi=d["high"].values, lo=d["low"].values,
                cl=cl, idx=d.index, n=n, sl_a=sl_a, rr=rr, mh=mh)


def walk(pk, sleeve, coin, frac, ptarget, be):
    """Kısmi TP simülasyonu. R = risk birimi cinsinden ağırlıklı toplam."""
    atr = pk["atr"]; dirs = pk["dirs"]; hi = pk["hi"]; lo = pk["lo"]; cl = pk["cl"]
    idx = pk["idx"]; n = pk["n"]; sl_a = pk["sl_a"]; rr = pk["rr"]; mh = pk["mh"]
    out = []; occ = -1
    for i in range(260, n - 1):
        if dirs[i] == 0 or i <= occ: continue
        d_ = dirs[i]; e = cl[i]; a = atr[i]; sld = sl_a * a
        slp = e - d_ * sld                      # orijinal SL
        tp2 = e + d_ * rr * sld                 # nihai TP (2.5R) — DEĞİŞMEZ
        tp1 = e + d_ * ptarget * sld if frac > 0 else None
        got1 = False; realized = 0.0; rem = 1.0
        cur_sl = slp; ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            # MUHAFAZAKÂR sıra: aynı barda önce stop, sonra hedefler
            if d_ == 1:
                if lo[j] <= cur_sl: ep = cur_sl; break
                if (not got1) and tp1 is not None and hi[j] >= tp1:
                    realized += frac * ptarget; rem -= frac; got1 = True
                    if be: cur_sl = e                      # kalan başabaşa
                if hi[j] >= tp2: ep = tp2; break
            else:
                if hi[j] >= cur_sl: ep = cur_sl; break
                if (not got1) and tp1 is not None and lo[j] <= tp1:
                    realized += frac * ptarget; rem -= frac; got1 = True
                    if be: cur_sl = e
                if lo[j] <= tp2: ep = tp2; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        # kalan kısmın R'si
        rem_R = d_ * (ep - e) / sld
        R = realized + rem * rem_R
        # ücret: giriş tam boy + çıkışlar (kısmi varsa iki çıkış)
        nfee = 2 + (1 if got1 else 0)
        R -= nfee * FEE * e / sld
        sl_pct = sld / e
        out.append({"entry_ns": idx[i].value, "exit": idx[j], "R": R, "sl_pct": sl_pct,
                    "coin": coin, "sleeve": sleeve}); occ = j
    return out


def portfolio(trades):
    ev = sorted(trades, key=lambda t: t["entry_ns"]); openh = []; taken = []; ctr = 0
    for t in ev:
        while openh and openh[0][0].value <= t["entry_ns"]: heapq.heappop(openh)
        if len(openh) < MAXPOS:
            ctr += 1; heapq.heappush(openh, (t["exit"], ctr, t)); taken.append(t)
    taken.sort(key=lambda t: t["exit"])
    r = np.array([t["R"] for t in taken])
    eff = np.minimum(RISKF, CAP * np.array([t["sl_pct"] for t in taken]))   # canlı boyut
    pnl = r * eff * BAL0
    eq = BAL0 + np.cumsum(pnl); peak = np.maximum.accumulate(np.concatenate([[BAL0], eq]))
    mdd = ((peak - np.concatenate([[BAL0], eq])) / peak).max() * 100
    gp = r[r > 0].sum(); gl = -r[r < 0].sum(); pf = gp / gl if gl > 0 else 9.99
    ex = [pd.Timestamp(t["exit"]) for t in taken]
    mon = pd.Series(pnl, index=[x.to_period("M") for x in ex]).groupby(level=0).sum() / BAL0 * 100
    yrs = {}
    ya = np.array([x.year for x in ex])
    for y in sorted(set(ya)): yrs[y] = pnl[ya == y].sum()
    return dict(n=len(r), pf=pf, wr=(r > 0).mean() * 100, tot=pnl.sum(), mdd=mdd,
                worst=mon.min(), posm=(mon > 0).mean() * 100, yrs=yrs)


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    dpk = {c: prep("donchian", fast_bt.load(c, source=source)) for c in DONCH}
    spk = {c: prep("squeeze", fast_bt.load(c, source=source)) for c in SQZ}
    print(f"\n{'='*100}\n=== KISMİ TP (scale-out) — canlı boyut (cap), MP={MAXPOS} ===")
    print(f"  {'varyant':13s} {'n':>5s} {'WR':>4s} {'PF':>5s} {'toplam$':>9s} {'maxDD%':>7s} {'enKötüAy':>9s} {'poz-ay':>7s}  yıl-yıl")
    base = None
    for name, frac, pt, be in VARIANTS:
        tr = []
        for c in DONCH: tr += walk(dpk[c], "donchian", c, frac, pt, be)
        for c in SQZ: tr += walk(spk[c], "squeeze", c, frac, pt, be)
        m = portfolio(tr)
        if name == "baseline": base = m
        flag = ""
        if base and name != "baseline":
            hurt = [y for y in m["yrs"] if m["yrs"][y] < base["yrs"].get(y, 0) - 1e-6]
            flag = "HER-YIL-OK" if not hurt else f"BOZDU:{sorted(hurt)}"
        ys = " ".join(f"{y}:${v:+.0f}" for y, v in m["yrs"].items())
        print(f"  {name:13s} {m['n']:>5d} {m['wr']:>3.0f}% {m['pf']:>5.2f} {m['tot']:>+9.0f} "
              f"{m['mdd']:>7.1f} {m['worst']:>+9.1f} {m['posm']:>6.0f}%  {ys}  {flag}")
    print("\n  KARAR: toplam$ VE PF'i HER YIL koruyup artıran varyant = gerçek → deploy adayı.")
    print("  WR/en-kötü-ay iyileşip toplam DÜŞÜYORSA → takas (kaldıraç azaltmakla aynı şey), RED.")


if __name__ == "__main__":
    main()
