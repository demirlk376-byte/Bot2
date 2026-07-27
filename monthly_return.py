"""
monthly_return.py — Deploy portföyünün AYLIK getiri dağılımı (dürüst, fantezi-yok).

"Aylık potansiyel getiri" küçük hesapta yanıltıcıdır. Bu araç sabit-oran (compounding YOK,
her ay %2.25 sabit sermayeye göre) aylık getiri dağılımını çıkarır: ortalama + medyan +
EN KÖTÜ ay + pozitif-ay oranı. Compounding fantezisi ($190→$64k) DEĞİL — taşınabilir beklenti.

Deploy: donchian 7 (SOL,ETH,ADA,NEAR,BCH,ICP,BNB) + squeeze 4 (XRP,DOGE,TRX,XLM),
MAX_POSITIONS=7 koltuk, risk %2.25/işlem (RISK_SCALE 1.125).

Kullanım:  py monthly_return.py local
"""
import sys, heapq
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn, ema as ema_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAL0 = 190.0; FEE = 0.0001; RISKF = 0.0225   # %2.25/işlem
DONCH = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB"]
SQZ = ["XRP", "DOGE", "TRX", "XLM"]
MAXPOS = int(sys.argv[2]) if len(sys.argv) > 2 else 7   # py monthly_return.py local 10
CFG = {"donchian": ("4h", 259, 2.0, 2.5, 30), "squeeze": ("1h", 119, 2.0, 2.5, 48)}


def gen(sleeve, m):
    tf, win, sl_a, rr, mh = CFG[sleeve]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    # CANLI-BİREBİR MTF (lookahead YOK): canlı d1d=df_4h.resample("1D").close.last() +
    # ewm20 dahil-bugün; cebirsel olarak == kapanış > DÜNE kadar tamamlanmış EMA20.
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
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
        out.append((idx[i].value, idx[j], R)); occ = j   # (entry_ns, exit_ts, R) — occ=coin başına tek-pozisyon
    return out


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    trades = []
    for c in DONCH:
        try: trades += gen("donchian", fast_bt.load(c, source=source))
        except Exception as e: print(f"  d {c}: {e}")
    for c in SQZ:
        try: trades += gen("squeeze", fast_bt.load(c, source=source))
        except Exception as e: print(f"  s {c}: {e}")
    # koltuk-kısıtlı seçim (giriş sırası), realized PnL sabit-oran (compounding yok)
    ev = sorted(trades, key=lambda t: t[0]); openh = []; realized = []   # (exit_ts, pnl$)
    for entry_ns, exit_ts, R in ev:
        while openh and openh[0][0].value <= entry_ns:
            xts, Rr = heapq.heappop(openh)
            realized.append((xts, Rr * RISKF * BAL0))
        if len(openh) < MAXPOS:
            heapq.heappush(openh, (exit_ts, R))
    while openh:
        xts, Rr = heapq.heappop(openh); realized.append((xts, Rr * RISKF * BAL0))
    ser = pd.Series({xts: p for xts, p in realized}) if False else None
    df = pd.DataFrame(realized, columns=["exit", "pnl"]).set_index("exit")
    monthly = df["pnl"].resample("ME").sum()
    monthly_pct = monthly / BAL0 * 100   # sabit $190 tabana göre % (compounding yok)
    tot_years = (df.index.max() - df.index.min()).days / 365.25
    print(f"\n{'='*66}\n=== AYLIK GETİRİ (sabit-oran %2.25/işlem, compounding YOK, taban ${BAL0:.0f}) ===")
    print(f"  {len(df)} işlem, {len(monthly)} ay, ~{tot_years:.1f} yıl, MAX_POSITIONS={MAXPOS}")
    print(f"\n  Ortalama ay : {monthly_pct.mean():+6.1f}%   (${monthly.mean():+6.2f})")
    print(f"  Medyan ay   : {monthly_pct.median():+6.1f}%")
    print(f"  En İYİ ay   : {monthly_pct.max():+6.1f}%")
    print(f"  En KÖTÜ ay  : {monthly_pct.min():+6.1f}%")
    print(f"  Std (oynak) : {monthly_pct.std():6.1f}%")
    print(f"  Pozitif ay  : {(monthly_pct>0).mean()*100:.0f}%  ({(monthly_pct>0).sum()}/{len(monthly)})")
    print(f"\n  --- yıllık ortalama aylık % (yıl-yıl) ---")
    for y in sorted(set(monthly.index.year)):
        mm = monthly_pct[monthly_pct.index.year == y]
        print(f"    {y}: ort {mm.mean():+5.1f}%/ay  (en kötü {mm.min():+5.1f}%, poz {(mm>0).mean()*100:.0f}%)")
    print(f"\n  DÜRÜST: bu IN-SAMPLE, sabit-oran (fantezi compounding değil). İleriye:")
    print(f"  (1) edge zayıflar → gerçek daha DÜŞÜK; (2) oynaklık yüksek, tek ay {monthly_pct.min():+.0f}% mümkün;")
    print(f"  (3) küçük hesapta yüksek % kolay ama slippage/min-notional sürtünmesi ısırır.")


if __name__ == "__main__":
    main()
