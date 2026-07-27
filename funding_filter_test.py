"""
funding_filter_test.py — Sahte kırılımı POZİSYONLANMA ile ayırt edebilir miyiz? (funding filtresi)

NEDEN BU, DİĞERLERİNDEN FARKLI: bugüne kadar denenen TÜM özellikler (adx, atr, hacim, momentum,
kanal aşımı, mum yapısı, BTC hizası, saat, gün) aynı kaynaktan — o coinin OHLCV'si. Yani fiyatın
NE YAPTIĞINA bakıyorlar, KİMİN yaptığına değil. Sahte kırılımı ayırt eden asıl bilgi ikincisi.

En doğrudan ölçü OPEN INTEREST'ti ama: ccxt-MEXC desteklemiyor + hiçbir borsa çok-yıllık geçmiş OI
vermiyor → BACKTEST EDİLEMEZ (sadece ileriye toplanabilir). FUNDING onun elde edilebilir vekili.

NEDENSEL HİPOTEZ (kriptoya özgü, genel TA lore'u DEĞİL):
  yukarı kırılım + YÜKSEK POZİTİF funding = long'lar kalabalık ve ödüyor → kalabalığa girmek → SAHTE
  yukarı kırılım + NEGATİF funding      = short'lar ödüyor → squeeze yakıtı → GERÇEK
  (aşağı kırılımda simetrik)
NOT: ledger'da funding bir STRATEJİ olarak test edilip reddedilmişti; FİLTRE olarak hiç denenmedi.

VERİ: data/{COIN}_funding.csv (VPS'te fetch_funding.py ile üretilir). Yoksa uyarır ve çıkar.
FİLTRE ÜRETİMDE uygulanır (elenen sinyal slotu meşgul etmez) = canlı-doğru.

Kullanım:  py funding_filter_test.py local
"""
import sys, os
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAL0 = 190.0; FEE = 0.0001; RISKF = 0.0225; CAP = 1.0
DONCH = ["SOL","ETH","ADA","NEAR","BCH","ICP","BNB"]
SQZ = ["XRP","DOGE","TRX","XLM"]
CFG = {"donchian": ("4h",259,2.0,2.5,30), "squeeze": ("1h",119,2.0,2.5,48)}


def load_funding(coin):
    p = f"data/{coin}_funding.csv"
    if not os.path.exists(p): return None
    df = pd.read_csv(p, parse_dates=["dt"]).set_index("dt")
    return df["rate"]


def gen(sleeve, coin, m, fund, mode, thresh):
    tf, win, sl_a, rr, mh = CFG[sleeve]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    # funding'i bar indeksine hizala: SADECE GEÇMİŞ (son yayınlanan oran, ffill)
    fr = fund.reindex(d.index, method="ffill").values if fund is not None else np.full(len(d), np.nan)
    s = (DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve=="donchian" else
         SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    hi=d["high"].values; lo=d["low"].values; cl=d["close"].values; idx=d.index; n=len(cl)
    out=[]; occ=-1
    for i in range(260, n-1):
        a = atr_ser[i]
        if not np.isfinite(a) or a<=0 or i<=occ: continue
        if sleeve=="squeeze":
            xv = adx_ser[i] if np.isfinite(adx_ser[i]) else 20.0
            if xv <= 20.0: continue
        d_ = s.analyze(d.iloc[max(0,i-win):i+1], float(a)).direction
        if d_ == 0: continue
        # ── FUNDING FİLTRESİ (üretimde) ──
        f = fr[i]
        if mode != "baseline" and np.isfinite(f):
            crowded = (d_ == 1 and f > thresh) or (d_ == -1 and f < -thresh)
            fuel    = (d_ == 1 and f < -thresh) or (d_ == -1 and f > thresh)
            if mode == "skip_crowded" and crowded: continue
            if mode == "only_fuel" and not fuel: continue
        e=cl[i]; sld=sl_a*a; slp=e-d_*sld; tp=e+d_*rr*sld; ep=None; j=i
        for j in range(i+1, min(i+1+mh, n)):
            if d_==1:
                if lo[j]<=slp: ep=slp; break
                if hi[j]>=tp: ep=tp; break
            else:
                if hi[j]>=slp: ep=slp; break
                if lo[j]<=tp: ep=tp; break
        if ep is None: j=min(i+mh,n-1); ep=cl[j]
        R = d_*(ep-e)/sld - 2*FEE*e/sld
        out.append({"R":R,"sl_pct":sld/e,"year":idx[i].year}); occ=j
    return out


def summ(trs):
    r=np.array([t["R"] for t in trs]); eff=np.minimum(RISKF, CAP*np.array([t["sl_pct"] for t in trs]))
    pnl=r*eff*BAL0; gp=r[r>0].sum(); gl=-r[r<0].sum()
    ya=np.array([t["year"] for t in trs])
    return dict(n=len(r), pf=gp/max(gl,1e-9), wr=(r>0).mean()*100, tot=pnl.sum(),
                yrs={y: pnl[ya==y].sum() for y in sorted(set(ya))})


def main():
    source = sys.argv[1] if len(sys.argv)>1 else "mexc_futures"
    funds = {c: load_funding(c) for c in DONCH+SQZ}
    missing = [c for c,v in funds.items() if v is None]
    if missing:
        print(f"\n  UYARI: funding verisi YOK: {', '.join(missing)}")
        print(f"  Önce VPS'te:  cd /opt/bot2 && python3 fetch_funding.py && git add data/ && git commit -m 'funding' && git push")
        print(f"  Sonra PC'de:  git pull && py funding_filter_test.py local\n")
        return
    ms = {c: fast_bt.load(c, source=source) for c in DONCH+SQZ}
    print(f"\n{'='*100}\n=== FUNDING FİLTRESİ — pozisyonlanma sahte kırılımı ayırt ediyor mu? ===")
    print(f"  {'mod':16s} {'eşik':>7s} {'n':>5s} {'WR':>4s} {'PF':>5s} {'toplam$':>9s}  yıl-yıl                          bayrak")
    base=None
    for mode, thresh in [("baseline",0.0), ("skip_crowded",0.0001), ("skip_crowded",0.0003),
                         ("skip_crowded",0.0005), ("only_fuel",0.0001), ("only_fuel",0.0003)]:
        trs=[]
        for c in DONCH: trs += gen("donchian", c, ms[c], funds[c], mode, thresh)
        for c in SQZ:   trs += gen("squeeze",  c, ms[c], funds[c], mode, thresh)
        s=summ(trs)
        if mode=="baseline": base=s
        hurt=[y for y in s["yrs"] if base and s["yrs"][y] < base["yrs"].get(y,0)-1e-6]
        flag = "" if mode=="baseline" else ("HER-YIL-OK ★" if not hurt else f"BOZDU:{sorted(hurt)}")
        ys=" ".join(f"{y}:${v:+.0f}" for y,v in s["yrs"].items())
        print(f"  {mode:16s} {thresh:>7.4f} {s['n']:>5d} {s['wr']:>3.0f}% {s['pf']:>5.2f} {s['tot']:>+9.0f}  {ys}  {flag}")
    print(f"\n  ARANAN: toplam VE PF VE her yıl baseline'ı geçen bir eşik → pozisyonlanma sinyali GERÇEK.")
    print(f"  Hiçbiri geçmiyorsa → sahte kırılım, elimizdeki HİÇBİR veriyle öngörülemez (kesin kapanış).")


if __name__ == "__main__":
    main()
