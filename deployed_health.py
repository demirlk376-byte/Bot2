"""
deployed_health.py — Deploy'daki HER coin'i sleeve'inde yıl-yıl denetle (occ-doğru).

backtest'te PF yıllar içinde düşüyor (1.54→1.37). Soru: bu soğuma TÜM coinlere mi yayılmış
(piyasa geneli, kabul et) yoksa BELİRLİ bir coin ÖLÜ AĞIRLIK mı (son yıllar negatif → ÇIKAR)?
Ölü ağırlığı çıkarmak = en düşük-riskli iyileştirme (ekleme/tuning yok → overfit yok).

Her deploy coin+sleeve: yıl-yıl $, PF, WR. Bayrak: son 2 yıl (2025-26) negatif/zayıf mı.

Kullanım:  py deployed_health.py local
"""
import sys
import numpy as np
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn, ema as ema_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAL0 = 190.0; FEE = 0.0001; RISKF = 0.0225
DEPLOY = [("donchian", c) for c in ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB"]] + \
         [("squeeze", c) for c in ["XRP", "DOGE", "TRX", "XLM"]]
CFG = {"donchian": ("4h", 259, 2.0, 2.5, 30), "squeeze": ("1h", 119, 2.0, 2.5, 48)}


def gen(sleeve, m):
    tf, win, sl_a, rr, mh = CFG[sleeve]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    dd = fast_bt.resample(m, "1d"); dema = ema_fn(dd["close"], 20)
    up = (dd["close"] > dema).reindex(d.index, method="ffill").values
    s = (DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve == "donchian" else
         SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values; idx = d.index; n = len(cl)
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
        e = cl[i]; sld = sl_a * a; slp = e - d_ * sld; tp = e + d_ * rr * sld; ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * FEE * e / sld
        out.append({"R": R, "year": idx[i].year}); occ = j
    return out


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    yrs = [2023, 2024, 2025, 2026]
    print(f"\n{'='*78}\n=== DEPLOY COİN SAĞLIK (izole, occ-doğru, %2.25) — ölü ağırlık var mı? ===")
    print(f"  {'coin/sleeve':16s} {'PF':>5s} {'toplam$':>8s}  " + " ".join(f"{y:>7d}" for y in yrs) + "  bayrak")
    for sleeve, c in DEPLOY:
        tr = gen(sleeve, fast_bt.load(c, source=source))
        r = np.array([t["R"] for t in tr]); gp = r[r > 0].sum(); gl = -r[r < 0].sum()
        pf = gp / gl if gl > 0 else 9.99
        yv = {y: sum(t["R"] for t in tr if t["year"] == y) * RISKF * BAL0 for y in yrs}
        recent = yv[2025] + yv[2026]
        flag = "ÖLÜ-AĞIRLIK?" if recent < 0 else ("zayıf-son" if recent < 15 else "sağlam")
        ystr = " ".join(f"${yv[y]:+6.0f}" for y in yrs)
        print(f"  {c+'/'+sleeve:16s} {pf:>5.2f} {r.sum()*RISKF*BAL0:>+8.0f}  {ystr}  {flag}")
    print("\n  ÖLÜ-AĞIRLIK (2025+2026 toplamı negatif) = ÇIKARMA adayı → çıkarınca portföy iyileşir mi")
    print("  diye faithful/portfolio ile doğrula. 'zayıf-son' = izle. 'sağlam' = dokunma.")
    print("  Hepsi benzer soğuyorsa = piyasa geneli edge-decay (coin suçu değil, kabul).")


if __name__ == "__main__":
    main()
