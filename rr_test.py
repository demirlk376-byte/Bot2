"""
rr_test.py — TP mesafesi (RR) taraması. SL sabit (2×ATR), TP'yi değiştir.
donchian rr2 / squeeze rr2.5 mevcut. Farklı rr net'i iyileştiriyor mu?
Sinyaller rr'den BAĞIMSIZ → bir kez üret, farklı rr'lerle simüle et (canlı-doğru:
occ her rr için ayrı, çünkü farklı rr farklı çıkış barı → farklı slot doluluğu).

Kullanım:  py rr_test.py local
"""
import sys
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAL = 190.0; FEE = 0.0001; RISK = 0.02
RRS = [1.5, 2.0, 2.5, 3.0, 3.5]
DEPLOY = {
    "donchian": (["SOL", "ETH", "ADA", "NEAR", "BCH"], "4h", 259, 2.0, 2.0, 30),
    "squeeze":  (["XRP", "DOGE", "TRX", "XLM"], "1h", 119, 2.0, 2.5, 48),
}


def run(sleeve, coin, m, rr):
    """rr ÜRETİMDE (çıkış barı rr'ye bağlı → occ doğru)."""
    _, tf, win, sl_a, cur_rr, mh = DEPLOY[sleeve]
    d = fast_bt.resample(m, tf)
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


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    for sleeve, (coins, *rest) in DEPLOY.items():
        cur = rest[2]
        ms = {}
        for coin in coins:
            try: ms[coin] = fast_bt.load(coin, source=source)
            except Exception as e: print(f"  {coin}: {e}")
        print(f"\n{'='*66}\n=== {sleeve.upper()} — TP/RR taraması (SL sabit 2×ATR) ===")
        for rr in RRS:
            allt = []
            for coin, m in ms.items():
                allt += run(sleeve, coin, m, rr)
            mark = " ← MEVCUT" if abs(rr - cur) < 0.01 else ""
            print(f"  rr{rr}: {st(allt)}{mark}")
    print("\n  Mevcut rr en iyiyse → dokunma. Belirgin daha iyi rr varsa → test/deploy.")


if __name__ == "__main__":
    main()
