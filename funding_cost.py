"""
funding_cost.py — ÇOK-GÜNLÜK TUTUŞLARDA FUNDING MALİYETİ (hiç ölçülmedi).

KÖR NOKTA: backtest sadece 2×1bp komisyon alıyor. Ama donchian 30 bar × 4h = 5 GÜNE kadar tutuyor
ve funding 8 SAATTE BİR ödeniyor → tek işlemde ~15 funding bacağı. Squeeze 48 bar × 1h = 2 gün → ~6.
Bot bunu görmüyor, backtest modellemiyor.

MATEMATİK: R_funding = −yön × Σ(rate) / sl_pct
  (PnL_funding = −yön × Σrate × nominal; risk = nominal × sl_pct → bölünce nominal sadeleşiyor)
  funding pozitif → LONG öder, SHORT alır.

VERİ: data/<COIN>_funding.csv, 2025-08-28 → 2026-07-27 (MEXC son 1000 kayıt). Bu pencerede
gerçekleşen işlemler üzerinde ölçülür; öncesi NaN → dokunulmaz.

Kullanım:  py funding_cost.py local
"""
import sys, os
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAL0=190.0; FEE=0.0001; RISKF=0.0225; CAP=1.0
DONCH=["SOL","ETH","ADA","NEAR","BCH","ICP","BNB"]
SQZ=["XRP","DOGE","TRX","XLM"]
CFG={"donchian":("4h",259,2.0,2.5,30),"squeeze":("1h",119,2.0,2.5,48)}

def load_funding(coin):
    p=f"data/{coin}_funding.csv"
    if not os.path.exists(p): return None
    df=pd.read_csv(p, parse_dates=["dt"]).set_index("dt").sort_index()
    return df["rate"]

def gen(sleeve, coin, m, fund):
    tf,win,sl_a,rr,mh = CFG[sleeve]
    d=fast_bt.resample(m,tf)
    atr=atr_fn(d["high"],d["low"],d["close"],14).values
    adx=adx_fn(d["high"],d["low"],d["close"],14).values
    s=(DonchianStrategy(channel=40,rr=2.0,sl_atr=2.0,ema_trend=200,buffer_atr=0.0) if sleeve=="donchian"
       else SqueezeStrategy(kc_mult=1.5,min_squeeze_bars=5,sl_atr=2.0,rr=2.5,mtf_filter=True))
    hi=d["high"].values; lo=d["low"].values; cl=d["close"].values; idx=d.index; n=len(cl)
    out=[]; occ=-1
    for i in range(260,n-1):
        a=atr[i]
        if not np.isfinite(a) or a<=0 or i<=occ: continue
        if sleeve=="squeeze":
            xv=adx[i] if np.isfinite(adx[i]) else 20.0
            if xv<=20.0: continue
        d_=s.analyze(d.iloc[max(0,i-win):i+1], float(a)).direction
        if d_==0: continue
        e=cl[i]; sld=sl_a*a; slp=e-d_*sld; tp=e+d_*rr*sld; ep=None; j=i
        for j in range(i+1, min(i+1+mh,n)):
            if d_==1:
                if lo[j]<=slp: ep=slp; break
                if hi[j]>=tp: ep=tp; break
            else:
                if hi[j]>=slp: ep=slp; break
                if lo[j]<=tp: ep=tp; break
        if ep is None: j=min(i+mh,n-1); ep=cl[j]
        R = d_*(ep-e)/sld - 2*FEE*e/sld
        # ── FUNDING: tutuş süresince ödenen/alınan ──
        t0, t1 = idx[i], idx[j]
        fr = np.nan; nlegs = 0
        if fund is not None:
            seg = fund[(fund.index > t0) & (fund.index <= t1)]
            if len(seg) > 0 or (fund.index.min() <= t0 <= fund.index.max()):
                fr = float(seg.sum()); nlegs = len(seg)
        R_fund = (-d_ * fr / (sld/e)) if np.isfinite(fr) else np.nan
        out.append({"R":R,"R_fund":R_fund,"legs":nlegs,"sl_pct":sld/e,
                    "hours":(t1-t0).total_seconds()/3600,"sleeve":sleeve,
                    "year":idx[i].year,"dir":d_}); occ=j
    return out

def main():
    src=sys.argv[1] if len(sys.argv)>1 else "mexc_futures"
    trs=[]
    for c in DONCH: trs += gen("donchian", c, fast_bt.load(c,source=src), load_funding(c))
    for c in SQZ:   trs += gen("squeeze",  c, fast_bt.load(c,source=src), load_funding(c))
    cov=[t for t in trs if np.isfinite(t["R_fund"])]
    print(f"\n{'='*92}\n=== FUNDING MALİYETİ (çok-günlük tutuşlar) ===")
    print(f"  toplam {len(trs)} işlem, funding verisi olan pencere: {len(cov)} işlem (%{len(cov)/len(trs)*100:.0f})")
    if not cov: print("  funding verisi yok"); return
    for sl in ("donchian","squeeze"):
        g=[t for t in cov if t["sleeve"]==sl]
        if not g: continue
        print(f"\n  --- {sl} ({len(g)} işlem) ---")
        print(f"    ort tutuş {np.mean([t['hours'] for t in g]):.0f} saat | ort funding bacağı {np.mean([t['legs'] for t in g]):.1f}")
        rf=np.array([t["R_fund"] for t in g])
        print(f"    funding R etkisi: ort {rf.mean():+.4f}R | medyan {np.median(rf):+.4f}R | toplam {rf.sum():+.2f}R")
        for dd,lbl in ((1,"LONG"),(-1,"SHORT")):
            gg=[t for t in g if t["dir"]==dd]
            if gg:
                r2=np.array([t["R_fund"] for t in gg])
                print(f"      {lbl:5s} n={len(gg):>3d} ort {r2.mean():+.4f}R toplam {r2.sum():+.2f}R")
    # dolar etkisi
    eff=lambda ts,key: sum(t[key]*min(RISKF,CAP*t["sl_pct"])*BAL0 for t in ts)
    base=eff(cov,"R"); fnd=eff(cov,"R_fund")
    r=np.array([t["R"] for t in cov]); rn=np.array([t["R"]+t["R_fund"] for t in cov])
    pf=lambda x: x[x>0].sum()/max(-x[x<0].sum(),1e-9)
    print(f"\n  === PENCERE İÇİ ETKİ ({len(cov)} işlem, 2025-08→2026-07) ===")
    print(f"    funding ÖNCESİ : ${base:+.2f}  PF {pf(r):.3f}")
    print(f"    funding SONRASI: ${base+fnd:+.2f}  PF {pf(rn):.3f}")
    print(f"    FUNDING ETKİSİ : ${fnd:+.2f}  ({fnd/abs(base)*100:+.1f}% of window PnL)")
    ya=np.array([t["year"] for t in cov])
    for y in sorted(set(ya)):
        g=[t for t in cov if t["year"]==y]
        print(f"      {y}: funding ${eff(g,'R_fund'):+.2f}  (PnL ${eff(g,'R'):+.0f})")
    print("FUNDDONE")

if __name__=="__main__": main()
