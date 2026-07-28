"""
pf_killswitch.py — KÖR NOKTA: bot kendi performansını izlemiyor. Kill-switch işe yarar mı?

Bot PF soğumasını (1.53→1.43→1.45→1.35) GÖREMİYOR. Eğer edge gerçekten ölürse aylarca zarar eder.
Soru: kayan PF'e bakıp durmak/küçülmek TARİHSEL olarak yardım eder miydi?

FORMLAR (tek düğmenin ayarları değil, farklı mekanizmalar):
  halt_N_T   : son N kapanmış işlemin PF'i < T ise YENİ GİRİŞ YOK (PF toparlayınca devam)
  derisk_N_T : durmak yerine riski YARIYA indir (sinyal alınır, küçük)
  sleeve_N_T : sleeve BAZINDA (donchian ve squeeze ayrı ayrı değerlendirilir)

NEDENSELLİK ŞART: PF, o sinyalin giriş anından ÖNCE KAPANMIŞ işlemlerden hesaplanır (walk-forward).
Kapanmamış işlem bilgisi kullanılmaz — yoksa lookahead olur.

BİLİNEN TUZAK: aylık PnL ORTALAMAYA DÖNÜYOR (otokorelasyon −0.345). Kill-switch'ler tam dipte
kesip toparlanmayı kaçırma eğiliminde — cooldown testi bu yüzden elenmişti. Test bunu GİZLEMEYECEK
şekilde kuruldu: her formun yıl-yıl kırılımı ve kaçırılan toparlanma açıkça raporlanıyor.

Kullanım:  py pf_killswitch.py local
"""
import sys, heapq
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAL0=190.0; FEE=0.0001; RISKF=0.0225; CAP=1.0; MAXPOS=7
DONCH=["SOL","ETH","ADA","NEAR","BCH","ICP","BNB"]
SQZ=["XRP","DOGE","TRX","XLM"]
CFG={"donchian":("4h",259,2.0,2.5,30),"squeeze":("1h",119,2.0,2.5,48)}

def gen(sleeve, coin, m):
    tf,win,sl_a,rr,mh=CFG[sleeve]
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
        R=d_*(ep-e)/sld - 2*FEE*e/sld
        out.append({"entry":idx[i],"exit":idx[j],"R":R,"sl_pct":sld/e,"sleeve":sleeve}); occ=j
    return out

def simulate(trades, mode, N, T):
    """Walk-forward: PF sadece giriş anından ÖNCE KAPANMIŞ işlemlerden."""
    ev=sorted(trades, key=lambda t:t["entry"])
    openh=[]; taken=[]; ctr=0
    closed={"donchian":[], "squeeze":[], "all":[]}
    pend=sorted(range(len(ev)), key=lambda k: ev[k]["exit"])  # kapanış sırası
    pi=0
    for t in ev:
        # bu girişten ÖNCE kapanan tüm işlemleri closed'a aktar
        while pi<len(pend) and ev[pend[pi]]["exit"] <= t["entry"]:
            c=ev[pend[pi]]
            if c.get("_taken"):
                closed["all"].append(c["R"]); closed[c["sleeve"]].append(c["R"])
            pi+=1
        while openh and openh[0][0] <= t["entry"]: heapq.heappop(openh)
        if len(openh)>=MAXPOS: continue
        scale=1.0
        if mode!="baseline":
            hist = closed[t["sleeve"]] if mode=="sleeve" else closed["all"]
            if len(hist)>=N:
                w=np.array(hist[-N:]); gp=w[w>0].sum(); gl=-w[w<0].sum()
                pf = gp/gl if gl>0 else 9.99
                if pf < T:
                    if mode in ("halt","sleeve"): continue      # yeni giriş YOK
                    if mode=="derisk": scale=0.5                 # yarım boy
        ctr+=1; heapq.heappush(openh,(t["exit"],ctr))
        t["_taken"]=True; taken.append((t,scale))
    if not taken: return None
    r=np.array([t["R"] for t,_ in taken]); sc=np.array([s for _,s in taken])
    eff=np.minimum(RISKF, CAP*np.array([t["sl_pct"] for t,_ in taken]))*sc
    pnl=r*eff*BAL0
    gp=(r*sc)[r>0].sum(); gl=-(r*sc)[r<0].sum()
    allq=np.concatenate([[BAL0], BAL0+np.cumsum(pnl)])
    peak=np.maximum.accumulate(allq); mdd=((peak-allq)/peak).max()*100
    ex=[pd.Timestamp(t["exit"]) for t,_ in taken]; ya=np.array([x.year for x in ex])
    yrs={y: pnl[ya==y].sum() for y in sorted(set(ya))}
    mon=pd.Series(pnl, index=[x.to_period("M") for x in ex]).groupby(level=0).sum()
    return dict(n=len(r), pf=gp/max(gl,1e-9), tot=pnl.sum(), mdd=mdd, worst=mon.min(), yrs=yrs)

def main():
    src=sys.argv[1] if len(sys.argv)>1 else "mexc_futures"
    base=[]
    for c in DONCH: base += gen("donchian", c, fast_bt.load(c,source=src))
    for c in SQZ:   base += gen("squeeze",  c, fast_bt.load(c,source=src))
    import copy
    print(f"\n{'='*104}\n=== PF KILL-SWITCH (walk-forward, kayan PF sadece KAPANMIŞ işlemlerden) ===")
    print(f"  {'form':22s} {'n':>5s} {'PF':>5s} {'toplam$':>9s} {'maxDD%':>7s} {'enKötüAy':>9s}  yıl-yıl              bayrak")
    b=simulate(copy.deepcopy(base),"baseline",0,0)
    ys=" ".join(f"{y}:${v:+.0f}" for y,v in b["yrs"].items())
    print(f"  {'baseline':22s} {b['n']:>5d} {b['pf']:>5.2f} {b['tot']:>+9.0f} {b['mdd']:>7.1f} {b['worst']:>+9.1f}  {ys}")
    for mode in ("halt","derisk","sleeve"):
        for N in (30,50,100):
            for T in (1.0,1.1,1.2):
                m=simulate(copy.deepcopy(base),mode,N,T)
                if not m: continue
                hurt=[y for y in m["yrs"] if m["yrs"][y] < b["yrs"].get(y,0)-1e-6]
                flag="HER-YIL-OK ★" if not hurt else f"BOZDU:{len(hurt)}yıl"
                if m["tot"]<=b["tot"]: flag += " (para↓)"
                ys=" ".join(f"{y}:${v:+.0f}" for y,v in m["yrs"].items())
                print(f"  {f'{mode}_N{N}_T{T}':22s} {m['n']:>5d} {m['pf']:>5.2f} {m['tot']:>+9.0f} {m['mdd']:>7.1f} {m['worst']:>+9.1f}  {ys}  {flag}")
    print(f"\n  ARANAN: toplam$ VE her yıl baseline'ı geçen bir form → kill-switch gerçek koruma.")
    print(f"  Sadece maxDD düşüp para azalıyorsa → TAKAS (riski RISK_SCALE ile azaltmak daha temiz).")
    print("PFKDONE")

if __name__=="__main__": main()
