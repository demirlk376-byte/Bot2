"""
loser_analysis.py — SL kaybedenleri ile TP kazananları GİRİŞ-ANI özelliklerine
göre ayır. Amaç: kazananları BOZMADAN kaybedenleri elen bir nedensel filtre var mı?

Her işlem için giriş anında (nedensel, sonuç değil) özellikler:
  adx, atr% (volatilite), ema200-uzaklığı (ATR cinsinden = aşırı-uzama),
  ema50>ema200 (rejim), günlük EMA20 hizası (MTF), haftagünü, 10-bar momentum.
Sonra TP-outcome vs SL-outcome işlemlerin özellik ORTALAMALARINI karşılaştırır.
Belirgin ayrışan özellik = filtre adayı (SONRA canlı-doğru + yıl-yıl test edilir).

DÜRÜST: çoğu özellik ayrışMAZ (giriş anında winner/loser benzer görünür — edge'in
doğası). Ayrışan çıkarsa test ederiz; çıkmazsa "önlenemez, tasarım" deriz.

HIZ: ATR/ADX full-series (vektörize), analyze coin başına tek geçiş. win=259/119 için
i>=260'ta pencere-yerel ile örtüşür (AV aracı; aday sonra filter_test ile doğrulanır).

Kullanım:  py loser_analysis.py local
"""
import sys
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn, ema as ema_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAL = 190.0; FEE = 0.0001; RISK = 0.02
DEPLOY = {   # rr2.5 canlı
    "donchian": (["SOL", "ETH", "ADA", "NEAR", "BCH"], "4h", 259, 2.0, 2.5, 30),
    "squeeze":  (["XRP", "DOGE", "TRX", "XLM"], "1h", 119, 2.0, 2.5, 48),
}


def gen(sleeve, coin, m):
    _, tf, win, sl_a, rr, mh = DEPLOY[sleeve]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values     # full-series
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    ema50 = ema_fn(d["close"], 50).values; ema200 = ema_fn(d["close"], 200).values
    # CANLI-BİREBİR MTF (lookahead YOK): canlı d1d=df_4h.resample("1D").close.last() +
    # ewm20 dahil-bugün; cebirsel olarak == kapanış > DÜNE kadar tamamlanmış EMA20.
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up_daily = d["close"].values > _dprev
    s = (DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve == "donchian" else
         SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values; idx = d.index; n = len(cl)
    out = []; occ = -1
    for i in range(260, n):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        adxv = adx_ser[i] if np.isfinite(adx_ser[i]) else 20.0
        if sleeve == "squeeze" and adxv <= 20.0: continue
        sub = d.iloc[max(0, i - win):i + 1]
        sg = s.analyze(sub, float(a))
        if sg.direction == 0 or i <= occ or i >= n - 1: continue
        if np.isnan(ema200[i]) or np.isnan(ema50[i]): continue
        d_ = sg.direction; e = cl[i]; sld = sl_a * a; slp = e - d_ * sld; tp = e + d_ * rr * sld
        ep = None; j = i; outcome = "hold"
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; outcome = "sl"; break
                if hi[j] >= tp: ep = tp; outcome = "tp"; break
            else:
                if hi[j] >= slp: ep = slp; outcome = "sl"; break
                if lo[j] <= tp: ep = tp; outcome = "tp"; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * FEE * e / sld
        dup = bool(up_daily[i]) if not (isinstance(up_daily[i], float) and np.isnan(up_daily[i])) else True
        out.append({
            "outcome": outcome, "R": R,
            "adx": adxv,
            "atr_pct": a / e * 100,
            "ema200_dist": (e - ema200[i]) / a * d_,           # +: yön lehine uzama (ATR)
            "ema50_gt_200": 1.0 if ema50[i] > ema200[i] else 0.0,
            "mtf_aligned": 1.0 if ((d_ == 1 and dup) or (d_ == -1 and not dup)) else 0.0,
            "dow": idx[i].dayofweek,
            "mom10": (e - cl[i - 10]) / cl[i - 10] * 100 * d_,  # yön lehine 10-bar momentum
        }); occ = j
    return out


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    feats = ["adx", "atr_pct", "ema200_dist", "ema50_gt_200", "mtf_aligned", "mom10"]
    for sleeve, (coins, *_) in DEPLOY.items():
        trs = []
        for coin in coins:
            try: trs += gen(sleeve, coin, fast_bt.load(coin, source=source))
            except Exception as e: print(f"  {coin}: {e}")
        tp = [t for t in trs if t["outcome"] == "tp"]
        sl = [t for t in trs if t["outcome"] == "sl"]
        hold = [t for t in trs if t["outcome"] == "hold"]
        print(f"\n{'='*70}\n=== {sleeve.upper()} — {len(trs)} işlem (TP {len(tp)} / SL {len(sl)} / hold {len(hold)}) ===")
        print(f"  {'özellik':13s}  {'TP-kazanan ort':>15s}  {'SL-kaybeden ort':>15s}  {'ayrışma?':>10s}")
        for f in feats:
            tv = np.mean([t[f] for t in tp]) if tp else 0
            sv = np.mean([t[f] for t in sl]) if sl else 0
            # ayrışma: iki grubun std'ine göre fark büyük mü (kabaca)
            allv = np.array([t[f] for t in trs]); sd = allv.std() + 1e-9
            gap = abs(tv - sv) / sd
            mark = "*BUYUK" if gap > 0.4 else ("orta" if gap > 0.2 else "yok")
            print(f"  {f:13s}  {tv:>15.3f}  {sv:>15.3f}  {mark:>10s} ({gap:.2f}sd)")
        # haftagünü kırılımı (SL oranı günlere göre)
        print(f"  --- haftagunu SL orani (Pzt=0..Paz=6) ---")
        for dw in range(7):
            ddd = [t for t in trs if t["dow"] == dw]
            if ddd:
                slr = sum(1 for t in ddd if t["outcome"] == "sl") / len(ddd)
                print(f"    gun{dw}: n={len(ddd):>3d} SL%{slr*100:>3.0f}", end="  ")
        print()
    print("\n  *BUYUK ayrisma (>0.4sd) = filtre adayi -> canli-dogru + yil-yil test.")
    print("  Hicbiri ayrismiyorsa -> SL'ler giris aninda ongorulemez (tasarim geregi).")


if __name__ == "__main__":
    main()
