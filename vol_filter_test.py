"""
vol_filter_test.py — Literatürden false-breakout filtreleri (canlı-doğru).
Hedef: SL'yi (sahte breakout) önle, TP'yi (gerçek breakout) bozma.

Filtreler (giriş anında, nedensel; filtre ÜRETİMDE = canlı-doğru):
  baseline
  +Hacim     : breakout barı hacmi > 1.5 × 20-bar hacim ortalaması (zayıf hacim = sahte)
  +ATRexp    : ATR yükseliyor (atr[i] > atr[i-5]) — gerçek breakout volatilite genişletir
  +VolFloor  : ATR% > medyanın yarısı (ölü piyasada girme; squeeze'e ters olabilir)
  +Hacim+ATR : ikisi birden

Kaynak fikirler: Donchian/turtle false-breakout literatürü (hacim ≥%50 üstü,
ATR genişlemesi, volatilite rejimi). Bulunan iyi filtre → yıl-yıl doğrula → deploy.

Kullanım:  py vol_filter_test.py local
"""
import sys
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAL = 190.0; FEE = 0.0001; RISK = 0.02
DEPLOY = {   # rr2.5 canlı
    "donchian": (["SOL", "ETH", "ADA", "NEAR", "BCH"], "4h", 259, 2.0, 2.5, 30),
    "squeeze":  (["XRP", "DOGE", "TRX", "XLM"], "1h", 119, 2.0, 2.5, 48),
}
FILTERS = ["baseline", "+Hacim", "+ATRexp", "+VolFloor", "+Hacim+ATR"]


def run(sleeve, coin, m, which):
    _, tf, win, sl_a, rr, mh = DEPLOY[sleeve]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    vol = d["volume"].values
    volma = pd.Series(vol).rolling(20).mean().values
    atr_pct = atr_ser / d["close"].values * 100
    atr_pct_med = np.nanmedian(atr_pct[np.isfinite(atr_pct)])
    s = (DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve == "donchian" else
         SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values; idx = d.index; n = len(cl)
    out = []; occ = -1
    for i in range(260, n):
        sub = d.iloc[max(0, i - win):i + 1]
        a = atr_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if np.isnan(a) or a <= 0: continue
        if sleeve == "squeeze":
            adxv = adx_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
            if (float(adxv) if np.isfinite(adxv) else 20.0) <= 20.0: continue
        sg = s.analyze(sub, float(a))
        if sg.direction == 0 or i <= occ or i >= n - 1: continue
        # ── FİLTRE (üretimde) ──
        if which == "+Hacim":
            if np.isnan(volma[i]) or volma[i] <= 0 or vol[i] < 1.5 * volma[i]: continue
        elif which == "+ATRexp":
            if i < 5 or not (atr_ser[i] > atr_ser[i - 5]): continue
        elif which == "+VolFloor":
            if not (atr_pct[i] > 0.5 * atr_pct_med): continue
        elif which == "+Hacim+ATR":
            if np.isnan(volma[i]) or volma[i] <= 0 or vol[i] < 1.5 * volma[i]: continue
            if i < 5 or not (atr_ser[i] > atr_ser[i - 5]): continue
        d_ = sg.direction; e = cl[i]; sld = sl_a * a; slp = e - d_ * sld; tp = e + d_ * rr * sld; ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        out.append({"R": d_ * (ep - e) / sld - 2 * FEE * e / sld, "year": idx[i].year}); occ = j
    return out


def st(tr):
    if not tr: return "yok"
    r = np.array([t["R"] for t in tr]); gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    pf = gp / gl if gl > 0 else 9.99
    return f"n={len(r):>4d} WR{(r>0).mean():>3.0%} PF{pf:4.2f} ${r.sum()*BAL*RISK:+8.2f}"


def yrbits(tr):
    return " ".join(f"{y}:${np.array([t['R'] for t in tr if t['year']==y]).sum()*BAL*RISK:+.0f}"
                    for y in sorted(set(t["year"] for t in tr)))


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    grand = {f: [] for f in FILTERS}
    for sleeve, (coins, *_) in DEPLOY.items():
        per = {f: [] for f in FILTERS}
        ms = {c: fast_bt.load(c, source=source) for c in coins}
        for f in FILTERS:
            for c, m in ms.items():
                per[f] += run(sleeve, c, m, f)
            grand[f] += per[f]
        print(f"\n{'='*70}\n=== {sleeve.upper()} (filtre üretimde — canlı-doğru) ===")
        for f in FILTERS:
            print(f"  {f:11s}: {st(per[f])}")
        for f in FILTERS:
            print(f"     {f:11s} yıl-yıl: {yrbits(per[f])}")
    print(f"\n{'='*70}\n=== TOPLAM ===")
    for f in FILTERS:
        print(f"  {f:11s}: {st(grand[f])}")
    print("\n  PF+total'i HER YIL koruyup artıran filtre = gerçek → deploy. Yoksa geç.")
    print("  (VolFloor squeeze'e ters olabilir — squeeze sıkışmadan patlar.)")


if __name__ == "__main__":
    main()
