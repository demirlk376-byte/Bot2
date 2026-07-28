"""
sample_size.py — "Bir ay bakıp çalışıyorsa riski artırırız" — kaç işlem GERÇEKTEN gerekir?

Gerçek backtest R dağılımından (1421 işlem) bootstrap ile örnekler çekip sorar:
  (a) ÇALIŞAN bir sistem N işlemde ne sıklıkla ZARARDA görünür? (yanlış alarm)
  (b) N işlemde ölçülen PF ne kadar oynak? (güven aralığı)
  (c) Kaç işlem sonra "çalışıyor/çalışmıyor" ayrımı anlamlı olur?
"""
import numpy as np, fast_bt
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

FEE=0.0001; RISKF=0.0225; CAP=1.25
DONCH=["SOL","ETH","ADA","NEAR","BCH","ICP","BNB"]; SQZ=["XRP","DOGE","TRX","XLM"]
CFG={"donchian":("4h",259,2.0,2.5,30),"squeeze":("1h",119,2.0,2.5,48)}

def gen(sleeve,m):
    tf,win,sl_a,rr,mh=CFG[sleeve]; d=fast_bt.resample(m,tf)
    atr=atr_fn(d["high"],d["low"],d["close"],14).values; adx=adx_fn(d["high"],d["low"],d["close"],14).values
    s=(DonchianStrategy(channel=40,rr=2.0,sl_atr=2.0,ema_trend=200,buffer_atr=0.0) if sleeve=="donchian"
       else SqueezeStrategy(kc_mult=1.5,min_squeeze_bars=5,sl_atr=2.0,rr=2.5,mtf_filter=True))
    hi=d["high"].values; lo=d["low"].values; cl=d["close"].values; n=len(cl); out=[]; occ=-1
    for i in range(260,n-1):
        a=atr[i]
        if not np.isfinite(a) or a<=0 or i<=occ: continue
        if sleeve=="squeeze":
            xv=adx[i] if np.isfinite(adx[i]) else 20.0
            if xv<=20.0: continue
        d_=s.analyze(d.iloc[max(0,i-win):i+1],float(a)).direction
        if d_==0: continue
        e=cl[i]; sld=sl_a*a; slp=e-d_*sld; tp=e+d_*rr*sld; ep=None; j=i
        for j in range(i+1,min(i+1+mh,n)):
            if d_==1:
                if lo[j]<=slp: ep=slp; break
                if hi[j]>=tp: ep=tp; break
            else:
                if hi[j]>=slp: ep=slp; break
                if lo[j]<=tp: ep=tp; break
        if ep is None: j=min(i+mh,n-1); ep=cl[j]
        out.append(d_*(ep-e)/sld - 2*FEE*e/sld); occ=j
    return out

R=[]
for c in DONCH: R+=gen("donchian",fast_bt.load(c,source="local"))
for c in SQZ:   R+=gen("squeeze",fast_bt.load(c,source="local"))
R=np.array(R)
gp=R[R>0].sum(); gl=-R[R<0].sum()
print(f"\n{'='*80}\n=== GERÇEK DAĞILIM ({len(R)} işlem) ===")
print(f"  ort {R.mean():+.3f}R | std {R.std():.3f}R | PF {gp/gl:.3f} | WR %{(R>0).mean()*100:.0f}")
rng=np.random.default_rng(7)
print(f"\n  {'N işlem':>8s} {'zararda görünme':>16s} {'PF 5-95% aralığı':>22s} {'PF<1 olasılığı':>15s}")
for N in (20,30,50,100,200,400):
    sims=rng.choice(R,size=(20000,N),replace=True)
    tot=sims.sum(axis=1)
    pfs=[]
    for s_ in sims[:4000]:
        g=s_[s_>0].sum(); l=-s_[s_<0].sum()
        pfs.append(g/l if l>0 else 9.99)
    pfs=np.array(pfs)
    print(f"  {N:>8d} {np.mean(tot<0)*100:>15.1f}% "
          f"{np.percentile(pfs,5):>10.2f} – {np.percentile(pfs,95):<9.2f} {np.mean(pfs<1)*100:>14.1f}%")
print(f"\n  → ÇALIŞAN sistem bile N=30'da sık sık zararda görünür. 'Bir ay iyiydi' KANIT DEĞİL.")
print(f"  → Aynı şekilde 'bir ay kötüydü' de sistemin bozulduğunu göstermez.")
print("SSDONE")
