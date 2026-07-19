"""
sl_sweep.py — SL MESAFESİ taraması (DÜRÜST). Deploy edilen coin/sleeve'ler için
SL çarpanını (×ATR) değiştirip net$/PF/WR/SL-yeme oranını karşılaştırır. RR sabit
(TP orantılı ölçeklenir). Sinyaller (giriş barları) SL'den BAĞIMSIZ — bir kez
üretilir, farklı SL'lerle simüle edilir; canlı-birebir üretim sınıfı.

Bu "SL öğrenip kaybeden trade'i engelle" DEĞİL (o overfit/look-ahead tuzağı).
Bu "SL ne kadar geniş olsun" trade-off'u: dar SL çok yer ama küçük kayıp;
geniş SL az yer ama büyük kayıp + whipsaw'da az takılır. Bedava öğle yemeği yok.

UYARI: en iyi çarpan mevcut 2.0'a yakınsa DEĞİŞTİRME — fark gürültüdür (overfit).
Sadece net BELİRGİN daha iyi + mantıklıysa değiştir.

Kullanım:
  python sl_sweep.py                       # tüm deploy coinler (VPS/MEXC)
  py sl_sweep.py SOL,ETH,ADA,NEAR,XRP,DOGE,TRX local   # PC (cache, çevrimdışı)
"""
import sys
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAL = 190.0; FEE = 0.0001; RISK = 0.02
SL_MULTS = [1.5, 2.0, 2.5, 3.0]   # denenecek SL×ATR (2.0 = mevcut)

# deploy: coin → (sleeve, rr, max_hold)
DEPLOY = {
    "SOL": ("donchian", 2.0, 30), "ETH": ("donchian", 2.0, 30),
    "ADA": ("donchian", 2.0, 30), "NEAR": ("donchian", 2.0, 30),
    "XRP": ("squeeze", 2.5, 48), "DOGE": ("squeeze", 2.5, 48), "TRX": ("squeeze", 2.5, 48),
}


def don_entries(m):
    d = fast_bt.resample(m, "4h")
    s = DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
    ents = []
    for i in range(260, len(d)):
        sub = d.iloc[max(0, i - 259):i + 1]; a = atr_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if np.isnan(a) or a <= 0: continue
        sg = s.analyze(sub, float(a))
        if sg.direction != 0: ents.append((i, sg.direction, float(a)))
    return d, ents


def sq_entries(m):
    d = fast_bt.resample(m, "1h")
    s = SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True)
    ents = []
    for i in range(260, len(d)):
        sub = d.iloc[max(0, i - 119):i + 1]; a = atr_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if np.isnan(a) or a <= 0: continue
        adxr = adx_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        adxv = float(adxr) if np.isfinite(adxr) else 20.0
        if adxv <= 20.0: continue
        sg = s.analyze(sub, float(a))
        if sg.direction != 0: ents.append((i, sg.direction, float(a)))
    return d, ents


def sim(d, ents, sl_mult, rr, max_hold):
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values; n = len(cl)
    rs = []; slhits = 0; occ = -1
    for (i, dr, av) in ents:
        if i <= occ or i >= n - 1 or av <= 0: continue
        e = cl[i]; sld = sl_mult * av; sl = e - dr * sld; tp = e + dr * rr * sld; ep = None; j = i; hit = False
        for j in range(i + 1, min(i + 1 + max_hold, n)):
            if dr == 1:
                if lo[j] <= sl: ep = sl; hit = True; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= sl: ep = sl; hit = True; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + max_hold, n - 1); ep = cl[j]
        R = dr * (ep - e) / sld - 2 * FEE * e / sld
        rs.append(R); occ = j
        if hit: slhits += 1
    return rs, slhits


def main():
    coins = [c.strip().upper() for c in (sys.argv[1] if len(sys.argv) > 1 else ",".join(DEPLOY)).split(",")]
    source = sys.argv[2] if len(sys.argv) > 2 else "mexc_futures"
    print("SL MESAFESİ TARAMASI — deploy coin/sleeve, RR sabit, SL×ATR değişken\n")
    tot = {sm: 0.0 for sm in SL_MULTS}
    for coin in coins:
        sleeve, rr, mh = DEPLOY.get(coin, ("donchian", 2.0, 30))
        try:
            m = fast_bt.load(coin, source=source)
        except Exception as e:
            print(f"  {coin} veri: {e}"); continue
        d, ents = (don_entries(m) if sleeve == "donchian" else sq_entries(m))
        print(f"=== {coin} ({sleeve}, rr{rr}) — {len(ents)} sinyal ===", flush=True)
        for sm in SL_MULTS:
            rs, slh = sim(d, ents, sm, rr, mh)
            if not rs:
                print(f"  SL{sm}×ATR: işlem yok"); continue
            r = np.array(rs); gp = r[r > 0].sum(); gl = -r[r < 0].sum(); pf = gp / gl if gl > 0 else 9.99
            usd = r.sum() * BAL * RISK
            mark = " ← MEVCUT" if abs(sm - 2.0) < 0.01 else ""
            print(f"  SL{sm}×ATR: n={len(r):>3d} WR{(r>0).mean():>3.0%} PF{pf:4.2f} ${usd:+7.2f}  "
                  f"SL-yeme%{slh/len(r)*100:>2.0f}{mark}", flush=True)
            tot[sm] += usd
    print(f"\n=== ÖZET — SL çarpanı bazında TOPLAM (tüm coinler) ===", flush=True)
    best = max(tot, key=tot.get)
    for sm in SL_MULTS:
        mk = "  ← MEVCUT" if abs(sm - 2.0) < 0.01 else ""
        star = "  ⭐en iyi" if sm == best else ""
        print(f"  SL{sm}×ATR: ${tot[sm]:+8.2f}{mk}{star}", flush=True)
    diff = tot[best] - tot[2.0]
    print(f"\n  En iyi ({best}) mevcut (2.0) farkı: ${diff:+.2f}")
    print("  DÜRÜST: fark küçükse (birkaç coin başına ~$10-20) → DEĞİŞTİRME, gürültü.")
    print("  Belirgin + tutarlı (çoğu coinde aynı yön) ise → değiştirmeyi düşün.")


if __name__ == "__main__":
    main()
