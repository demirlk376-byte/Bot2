"""
quality_test.py — PF'i itmek için KALİTE FİLTRELERİ testi (dürüst takas).
Deploy sleeve'lere (donchian, squeeze) nedensel filtreler ekleyip baseline ile
karşılaştırır. Her filtre PF'i artırabilir ama total'i düşürür — takası GÖSTERİR.

Filtreler:
  baseline  : mevcut (filtre yok)
  +MTF      : günlük trend hizası (long ancak günlük close>EMA20, short tersi)
              → ters-trend breakout'ları eler
  +ADXtavan : ADX>=35 girişleri atla (aşırı-uzamış geç girişler)
  +HER İKİSİ

PF 2.0 bekleme — amaç kaliteyi bir tık artırıp total bedelini görmek.
Kullanım:  py quality_test.py local
"""
import sys
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn, ema as ema_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAL = 190.0; FEE = 0.0001; RISK = 0.02
DEPLOY = {
    "donchian": (["SOL", "ETH", "ADA", "NEAR", "BCH"], "4h", 259, 2.0, 2.0, 30),
    "squeeze":  (["XRP", "DOGE", "TRX", "XLM"], "1h", 119, 2.0, 2.5, 48),
}


def gen(sleeve, coin, m):
    _, tf, win, sl_a, rr, mh = DEPLOY[sleeve]
    d = fast_bt.resample(m, tf)
    # günlük trend (MTF): EMA20 üstünde mi
    dd = fast_bt.resample(m, "1d")
    dema = ema_fn(dd["close"], 20)
    up_daily = (dd["close"] > dema).reindex(d.index, method="ffill")
    s = (DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve == "donchian" else
         SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values; n = len(cl)
    out = []; occ = -1
    for i in range(260, n):
        sub = d.iloc[max(0, i - win):i + 1]
        a = atr_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if np.isnan(a) or a <= 0: continue
        adxv = adx_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        adxv = float(adxv) if np.isfinite(adxv) else 20.0
        if sleeve == "squeeze" and adxv <= 20.0: continue
        sg = s.analyze(sub, float(a))
        if sg.direction == 0 or i <= occ or i >= n - 1: continue
        d_ = sg.direction; e = cl[i]; sld = sl_a * a; slp = e - d_ * sld; tp = e + d_ * rr * sld; ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * FEE * e / sld
        dup = bool(up_daily.iloc[i]) if not pd.isna(up_daily.iloc[i]) else True
        aligned = (d_ == 1 and dup) or (d_ == -1 and not dup)
        out.append({"R": R, "adx": adxv, "aligned": aligned}); occ = j
    return out


def st(tr):
    if not tr: return "yok"
    r = np.array([t["R"] for t in tr]); gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    pf = gp / gl if gl > 0 else 9.99
    return f"n={len(r):>4d} WR{(r>0).mean():>3.0%} PF{pf:4.2f} ${r.sum()*BAL*RISK:+8.2f}"


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    grand = {"baseline": [], "+MTF": [], "+ADXtavan": [], "+HER İKİSİ": []}
    for sleeve, (coins, *_) in DEPLOY.items():
        trs = []
        for coin in coins:
            try: m = fast_bt.load(coin, source=source)
            except Exception as e: print(f"  {coin}: {e}"); continue
            trs += gen(sleeve, coin, m)
        base = trs
        mtf = [t for t in trs if t["aligned"]]
        adxc = [t for t in trs if t["adx"] < 35]
        both = [t for t in trs if t["aligned"] and t["adx"] < 35]
        print(f"\n{'='*68}\n=== {sleeve.upper()} ===")
        print(f"  baseline   : {st(base)}")
        print(f"  +MTF       : {st(mtf)}")
        print(f"  +ADXtavan  : {st(adxc)}")
        print(f"  +HER İKİSİ : {st(both)}")
        grand["baseline"] += base; grand["+MTF"] += mtf
        grand["+ADXtavan"] += adxc; grand["+HER İKİSİ"] += both
    print(f"\n{'='*68}\n=== TOPLAM (donchian+squeeze) ===")
    for k, v in grand.items():
        print(f"  {k:11s}: {st(v)}")
    print("\n  Bak: filtre PF'i artırıyor mu, total'i ne kadar düşürüyor mu?")
    print("  PF belirgin artıp total ~aynı kalıyorsa → uygula. Total çok düşüyorsa → değmez.")


if __name__ == "__main__":
    main()
