"""
risk_dd.py — Riski artırmanın GERÇEK bedeli: portföy getiri + MAX DRAWDOWN.
7 deploy coinin işlemlerini TEK hesaba (bileşik) zaman sırasıyla uygular, farklı
işlem-başı risk%'lerde final getiri VE max drawdown gösterir.

"Riski 2x yapınca ne olur?" → getiri büyür AMA drawdown da büyür, ve bir yerden
sonra (Kelly aşımı) getiri DÜŞMEYE başlar. Karar rakamlarla verilsin.

Not: işlemler çıkış zamanına göre sıralı, bileşik sabit-oran boyutlama (tahmin;
eşzamanlı pozisyonlar yaklaşık). Gerçek değil ama risk trade-off'unu dürüst gösterir.

Kullanım:
  py risk_dd.py SOL,ETH,ADA,NEAR,XRP,DOGE,TRX local
"""
import sys
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAL0 = 190.0; FEE = 0.0001
RISKS = [0.02, 0.03, 0.04, 0.06, 0.08, 0.10, 0.12]   # işlem başı risk (0.02 = mevcut)
# NOT: yüksek seviyeler Kelly'yi aşar — MAX DD patlar ama final $ ARTMAYI durdurur
# / DÜŞER (over-betting). Amaç bunu GÖSTERMEK, öneri DEĞİL.
DEPLOY = {
    "SOL": ("donchian", 2.0, 2.0, 30), "ETH": ("donchian", 2.0, 2.0, 30),
    "ADA": ("donchian", 2.0, 2.0, 30), "NEAR": ("donchian", 2.0, 2.0, 30),
    "XRP": ("squeeze", 2.0, 2.5, 48), "DOGE": ("squeeze", 2.0, 2.5, 48), "TRX": ("squeeze", 2.0, 2.5, 48),
}


def entries_don(m):
    d = fast_bt.resample(m, "4h"); s = DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
    out = []
    for i in range(260, len(d)):
        sub = d.iloc[max(0, i - 259):i + 1]; a = atr_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if np.isnan(a) or a <= 0: continue
        sg = s.analyze(sub, float(a))
        if sg.direction != 0: out.append((i, sg.direction, float(a)))
    return d, out


def entries_sq(m):
    d = fast_bt.resample(m, "1h"); s = SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True)
    out = []
    for i in range(260, len(d)):
        sub = d.iloc[max(0, i - 119):i + 1]; a = atr_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if np.isnan(a) or a <= 0: continue
        adxr = adx_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if (float(adxr) if np.isfinite(adxr) else 20.0) <= 20.0: continue
        sg = s.analyze(sub, float(a))
        if sg.direction != 0: out.append((i, sg.direction, float(a)))
    return d, out


def trades_of(d, ents, sl_mult, rr, mh):
    """(çıkış_zamanı, R) listesi döndürür."""
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values; idx = d.index; n = len(cl)
    out = []; occ = -1
    for (i, dr, av) in ents:
        if i <= occ or i >= n - 1 or av <= 0: continue
        e = cl[i]; sld = sl_mult * av; sl = e - dr * sld; tp = e + dr * rr * sld; ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if dr == 1:
                if lo[j] <= sl: ep = sl; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= sl: ep = sl; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        R = dr * (ep - e) / sld - 2 * FEE * e / sld
        out.append((idx[j], R)); occ = j
    return out


def main():
    coins = [c.strip().upper() for c in (sys.argv[1] if len(sys.argv) > 1 else ",".join(DEPLOY)).split(",")]
    source = sys.argv[2] if len(sys.argv) > 2 else "mexc_futures"
    all_tr = []
    for coin in coins:
        if coin not in DEPLOY: continue
        sleeve, sl_m, rr, mh = DEPLOY[coin]
        try:
            m = fast_bt.load(coin, source=source)
        except Exception as e:
            print(f"  {coin} veri: {e}"); continue
        d, ents = (entries_don(m) if sleeve == "donchian" else entries_sq(m))
        tr = trades_of(d, ents, sl_m, rr, mh)
        all_tr += tr
        print(f"  {coin} ({sleeve}): {len(tr)} işlem", flush=True)
    all_tr.sort(key=lambda x: x[0])   # çıkış zamanına göre
    print(f"\n  Toplam {len(all_tr)} işlem, {all_tr[0][0].date()}→{all_tr[-1][0].date()}")
    print(f"\n=== RİSK vs GETİRİ vs MAX DRAWDOWN (bileşik, $190 başlangıç) ===", flush=True)
    print(f"  {'risk/işlem':<12}{'final $':>10}{'getiri %':>10}{'YILLIK ~%':>11}{'MAX DD %':>10}{'getiri/DD':>10}")
    for risk in RISKS:
        bal = BAL0; peak = bal; maxdd = 0.0
        for (_, R) in all_tr:
            bal += R * risk * bal
            if bal <= 0: bal = 0.01
            peak = max(peak, bal); maxdd = max(maxdd, (peak - bal) / peak)
        yrs = (all_tr[-1][0] - all_tr[0][0]).days / 365.25
        ret = (bal / BAL0 - 1) * 100
        cagr = ((bal / BAL0) ** (1 / yrs) - 1) * 100 if bal > 0 and yrs > 0 else -100
        r2dd = (ret / (maxdd * 100)) if maxdd > 0 else 9.99
        mk = "  ← MEVCUT" if abs(risk - 0.02) < 0.001 else ""
        print(f"  %{risk*100:<11.0f}${bal:>9.0f}{ret:>+9.0f}%{cagr:>+10.0f}%{maxdd*100:>9.0f}%{r2dd:>10.2f}{mk}", flush=True)
    print("\n  OKUMA: risk arttıkça getiri büyür AMA MAX DD de büyür. Bir yerden sonra")
    print("  final $ DÜŞMEYE başlar (Kelly aşımı — over-betting). getiri/DD en yüksek")
    print("  olan risk en 'verimli'. In-sample bunlar; forward'da DD daha derin olabilir.")
    print("  Küçük hesapta -%40 DD hem cebe hem PSİKOLOJİYE ağır — sistemi dipte bıraktırır.")


if __name__ == "__main__":
    main()
