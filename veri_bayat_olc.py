"""BAYATLIK OLCUMU: ankor verisinin bitmedigi 2026-07-20 -> 2026-09-07 penceresinde
ankor ne derdi? data/*_uyum_1h.csv (MEXC, 2026-09-09 cekimi) ile kosulur."""
import sys, heapq
import numpy as np, pandas as pd
sys.path.insert(0,"/home/user/Bot2")
import fast_bt, deployed_backtest as A

COINS=A.DONCH+A.SQZ+A.BB_COINS
V={c: pd.read_csv(f"/home/user/Bot2/data/{c}_uyum_1h.csv",index_col=0,parse_dates=True) for c in COINS}
print("taze veri:", V["ETH"].index[0], "->", V["ETH"].index[-1], len(V["ETH"]),"bar")
ISINMA = V["ETH"].index[0] + pd.Timedelta(hours=4)*260
print(f"donchian isinmasi biter: {ISINMA}  (bundan onceki sinyaller EKSIK sayilir)")

raw=[]
for c in A.DONCH:
    for t in A.gen("donchian", V[c]): raw.append((c,"donchian")+t)
for c in A.SQZ:
    for t in A.gen("squeeze", V[c]): raw.append((c,"squeeze")+t)
for c in A.BB_COINS:
    for t in A.gen_bb(V[c]): raw.append((c,"bb")+t)
print("ham sinyal (taze veri):", len(raw))

ev=sorted(raw,key=lambda t:t[2]); openh=[]; taken=[]; ctr=0
for coin,sl,ns,xt,R,slp in ev:
    while openh and openh[0][0].value<=ns: heapq.heappop(openh)
    if len(openh)<A.MAXPOS:
        ctr+=1; heapq.heappush(openh,(xt,ctr,R)); taken.append((coin,sl,pd.Timestamp(ns,tz="UTC"),xt,R,slp))
df=pd.DataFrame(sorted(taken,key=lambda t:t[3]),columns=["coin","kol","giris","cikis","R","slp"])
df=df[df.giris>=ISINMA]
eff=np.minimum(A.CANLI_RISKF, A.CANLI_CAP*df.slp.values); df["pnl_canli"]=df.R.values*eff*A.BAL0
print(f"\nisinma sonrasi toplam: n={len(df)} ortR {df.R.mean():+.4f} pnl(canli olcek) ${df.pnl_canli.sum():+.2f}")

for lo,hi,lbl in [("2026-06-18","2026-07-20","A) ANKORUN KAPSADIGI canli donem"),
                  ("2026-07-20","2026-09-08","B) ANKORUN KAPSAMADIGI canli donem"),
                  ("2026-06-18","2026-09-08","C) TUM canli donem")]:
    s=df[(df.cikis>=pd.Timestamp(lo,tz="UTC"))&(df.cikis<pd.Timestamp(hi,tz="UTC"))]
    c1=(0.001585/s.slp).mean() if len(s) else 0
    print(f"  {lbl:38s} n={len(s):3d} ortR {s.R.mean() if len(s) else 0:+.4f} "
          f"kaymali {s.R.mean()-c1 if len(s) else 0:+.4f} kazanma %{(s.R>0).mean()*100 if len(s) else 0:.1f} "
          f"pnl ${s.pnl_canli.sum():+.2f}")
print("\n  CANLI GERCEK (ledger): n=124 ortR +0.0837 kazanma %37.1 toplam +$58.76")

# --- istatistik ---
import math
s=df[(df.cikis>=pd.Timestamp("2026-06-18",tz="UTC"))&(df.cikis<pd.Timestamp("2026-09-08",tz="UTC"))]
c1=(0.001585/s.slp).mean()
mA, sA, nA = s.R.mean()-c1, s.R.std(), len(s)
mL, sL, nL = 0.0837, 1.347, 124
se=math.sqrt(sA**2/nA + sL**2/nL)
z=(mL-mA)/se
print(f"\n=== DONEM-ESLESMELI KIYAS ===")
print(f"  ankor (ayni pencere, taze veri, KAYMALI): {mA:+.4f}R  sigma {sA:.3f}  n {nA}")
print(f"  canli gercek                            : {mL:+.4f}R  sigma {sL:.3f}  n {nL}")
print(f"  fark {mL-mA:+.4f}R   SE {se:.4f}   z {z:+.2f}")
print(f"  LEDGER'IN KULLANDIGI tam-donem kaymali ankor: +0.1764R -> fark -0.0927R z -0.77")
