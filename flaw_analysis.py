"""
flaw_analysis.py — Stratejinin SİSTEMATİK zaaflarını bul (nedensel, test edilebilir).
Deploy sleeve'lerin (donchian, squeeze) TÜM işlemlerini üretir, kaybı DESENE göre
diler:
  1) YÖN: long vs short (crypto yukarı-meyli → short'lar zayıf mı?)
  2) REJİM: giriş ADX'i (düşük ADX = zayıf trend = kötü breakout mu?)
  3) COIN: hangi coin sürükdüyor?
Bulunan zaaf bir HİPOTEZ; sonra filtreyi test edip net'i iyileştiriyor mu bakarız
(overfit'e dikkat: tek nedensel kesim, parametre taraması değil).

Kullanım:  py flaw_analysis.py local
"""
import sys
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAL = 190.0; FEE = 0.0001; RISK = 0.02
DEPLOY = {
    "donchian": (["SOL", "ETH", "ADA", "NEAR", "BCH"], "4h", 259, 2.0, 2.0, 30),
    "squeeze":  (["XRP", "DOGE", "TRX", "XLM"], "1h", 119, 2.0, 2.5, 48),
}


def gen_trades(sleeve, coin, m):
    _, tf, win, sl_a, rr, mh = DEPLOY[sleeve]
    d = fast_bt.resample(m, tf)
    if sleeve == "donchian":
        s = DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
    else:
        s = SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True)
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values; idx = d.index; n = len(cl)
    out = []; occ = -1
    for i in range(260, n):
        sub = d.iloc[max(0, i - win):i + 1]
        a = atr_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if np.isnan(a) or a <= 0:
            continue
        adxv = adx_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        adxv = float(adxv) if np.isfinite(adxv) else 20.0
        if sleeve == "squeeze" and adxv <= 20.0:      # canlı bo_allowed
            continue
        sg = s.analyze(sub, float(a))
        if sg.direction == 0:
            continue
        # simüle
        if i <= occ or i >= n - 1:
            continue
        d_ = sg.direction; e = cl[i]; sld = sl_a * a; slp = e - d_ * sld; tp = e + d_ * rr * sld; ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None:
            j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * FEE * e / sld
        out.append({"dir": d_, "adx": adxv, "R": R, "year": idx[i].year, "coin": coin}); occ = j
    return out


def stats(tr):
    if not tr: return "yok"
    r = np.array([t["R"] for t in tr]); gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    pf = gp / gl if gl > 0 else 9.99
    return f"n={len(r):>4d} WR{(r>0).mean():>3.0%} PF{pf:4.2f} ${r.sum()*BAL*RISK:+8.2f}"


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    allt = {}
    for sleeve, (coins, *_ ) in DEPLOY.items():
        trs = []
        for coin in coins:
            try: m = fast_bt.load(coin, source=source)
            except Exception as e: print(f"  {coin}: {e}"); continue
            trs += gen_trades(sleeve, coin, m)
        allt[sleeve] = trs
        print(f"\n{'='*66}\n=== {sleeve.upper()} — {len(trs)} işlem ===")
        print(f"  GENEL     : {stats(trs)}")
        print(f"  --- YÖN ---")
        print(f"  LONG      : {stats([t for t in trs if t['dir']==1])}")
        print(f"  SHORT     : {stats([t for t in trs if t['dir']==-1])}")
        print(f"  --- REJİM (giriş ADX) ---")
        print(f"  ADX<25    : {stats([t for t in trs if t['adx']<25])}")
        print(f"  ADX 25-35 : {stats([t for t in trs if 25<=t['adx']<35])}")
        print(f"  ADX>=35   : {stats([t for t in trs if t['adx']>=35])}")
        print(f"  --- COIN ---")
        for coin in DEPLOY[sleeve][0]:
            print(f"  {coin:5s}     : {stats([t for t in trs if t['coin']==coin])}")
    print(f"\n{'='*66}\n=== YORUM ===")
    print("  SHORT belirgin zayıf/eksi ise → yön filtresi (long-bias) test edilir.")
    print("  Düşük ADX'te PF<1 ise → giriş rejim filtresi sıkılaştırılır.")
    print("  Bir coin sürükdüyorsa → o coin/sleeve eşlemesi gözden geçirilir.")
    print("  Bulunan hipotez SONRA test edilir — overfit'e karşı tek nedensel kesim.")


if __name__ == "__main__":
    main()
