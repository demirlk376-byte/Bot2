"""
dow_test.py — Donchian gün-içi (day-of-week) filtresi testi (canlı-doğru, yıl-yıl).

loser_analysis DONCHIAN'da yapısal bir sinyal buldu:
  Pzt %61 SL, Sal %65 SL  vs  Çar %41, Per %37, Cum %42.
Hipotez: hafta-başı breakout'ları (ince likidite / hafta-sonu sahte hareketleri)
daha çok fail ediyor. UYARI: bu VERİ-TARANMIŞ bir lead (aynı veride bulundu) →
tek koruma yıl-yıl sağlamlık: HER YIL koruyup artırırsa gerçek, yoksa overfit.

Filtreler (giriş anında, üretimde = canlı-doğru):
  baseline
  -MonTue    : Pzt(0)+Sal(1) girişleri atla
  -Mon       : sadece Pzt atla
  -MonTueSun : Pzt+Sal+Paz (üç zayıf gün) atla
  WedThuOnly : sadece Çar(2)+Per(3) (en güçlü iki gün) — agresif, az işlem

Kullanım:  py dow_test.py local
"""
import sys
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn
from strategies.donchian import DonchianStrategy

BAL = 190.0; FEE = 0.0001; RISK = 0.02
COINS = ["SOL", "ETH", "ADA", "NEAR", "BCH"]
TF, WIN, SL_A, RR, MH = "4h", 259, 2.0, 2.5, 30
FILTERS = {
    "baseline":   None,
    "-MonTue":    lambda dw: dw not in (0, 1),
    "-Mon":       lambda dw: dw != 0,
    "-MonTueSun": lambda dw: dw not in (0, 1, 6),
    "WedThuOnly": lambda dw: dw in (2, 3),
}


def precompute(m):
    d = fast_bt.resample(m, TF)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    s = DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
    cl = d["close"].values; n = len(cl)
    dirs = np.zeros(n, dtype=int)
    for i in range(260, n):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        dirs[i] = s.analyze(d.iloc[max(0, i - WIN):i + 1], float(a)).direction
    return dict(atr=atr_ser, dirs=dirs, hi=d["high"].values, lo=d["low"].values,
                cl=cl, idx=d.index, dow=d.index.dayofweek.values, n=n)


def walk(pc, keep):
    atr = pc["atr"]; dirs = pc["dirs"]; hi = pc["hi"]; lo = pc["lo"]; cl = pc["cl"]
    idx = pc["idx"]; dow = pc["dow"]; n = pc["n"]
    out = []; occ = -1
    for i in range(260, n - 1):
        if dirs[i] == 0 or i <= occ: continue
        if keep is not None and not keep(int(dow[i])): continue   # filtre üretimde
        d_ = dirs[i]; e = cl[i]; sld = SL_A * atr[i]
        slp = e - d_ * sld; tp = e + d_ * RR * sld; ep = None; j = i
        for j in range(i + 1, min(i + 1 + MH, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + MH, n - 1); ep = cl[j]
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
    pcs = []
    for c in COINS:
        try: pcs.append(precompute(fast_bt.load(c, source=source)))
        except Exception as e: print(f"  {c}: {e}")
    print(f"\n{'='*70}\n=== DONCHIAN gün-filtresi (üretimde — canlı-doğru) ===")
    res = {}
    for name, keep in FILTERS.items():
        tr = []
        for pc in pcs: tr += walk(pc, keep)
        res[name] = tr
        print(f"  {name:11s}: {st(tr)}")
    print(f"\n  --- yıl-yıl ---")
    for name in FILTERS:
        print(f"  {name:11s}: {yrbits(res[name])}")
    print("\n  Bir filtre PF+total'i HER YIL koruyup artırıyorsa GERÇEK; bir yıl bile")
    print("  bozuyorsa VERİ-TARAMASI (overfit) → REDDET. Aday çıkarsa filter_test ile de doğrula.")


if __name__ == "__main__":
    main()
