"""Veri kusurlarinin ANKOR uzerindeki PARA etkisini olcer. Uretim kodu degismez."""
import sys, heapq
import numpy as np, pandas as pd
sys.path.insert(0,"/home/user/Bot2")
import deployed_backtest as A
import fast_bt

# --- coin etiketli ham sinyal uret ---
raw=[]
for c in A.DONCH:
    for t in A.gen("donchian", fast_bt.load(c, source="local")): raw.append((c,"donchian")+t)
for c in A.SQZ:
    for t in A.gen("squeeze", fast_bt.load(c, source="local")): raw.append((c,"squeeze")+t)
for c in A.BB_COINS:
    for t in A.gen_bb(fast_bt.load(c, source="local")): raw.append((c,"bb")+t)
print(f"ham sinyal {len(raw)}")

# --- koltuk secimi (deployed_backtest.seat_select ile ayni, etiket tasir) ---
ev=sorted(raw,key=lambda t:t[2]); openh=[]; taken=[]; ctr=0
for coin,sl,entry_ns,exit_ts,R,slp in ev:
    while openh and openh[0][0].value<=entry_ns: heapq.heappop(openh)
    if len(openh)<A.MAXPOS:
        ctr+=1; heapq.heappush(openh,(exit_ts,ctr,R))
        taken.append((coin,sl,pd.Timestamp(entry_ns,tz="UTC"),exit_ts,R,slp))
taken=sorted(taken,key=lambda t:t[3])
print(f"koltuk sonrasi {len(taken)}  (ankor 1579 bekleniyor)")

df=pd.DataFrame(taken,columns=["coin","kol","giris","cikis","R","slp"])
def para(d, riskf, cap):
    eff=np.minimum(riskf, cap*d.slp.values); return (d.R.values*eff*A.BAL0)
df["pnl_ankor"]=para(df,A.RISKF,A.CAP)
df["pnl_canli"]=para(df,A.CANLI_RISKF,A.CANLI_CAP)
print(f"toplam ankor ${df.pnl_ankor.sum():+.2f}   canli olcek ${df.pnl_canli.sum():+.2f}  ort R {df.R.mean():+.4f}")

# ============ 1) 2023-08-26 MEXC KESINTISI ============
k0=pd.Timestamp("2023-08-26 18:00",tz="UTC"); k1=pd.Timestamp("2023-08-26 23:00",tz="UTC")
m=((df.giris>=k0)&(df.giris<=k1)) | ((df.cikis>=k0)&(df.cikis<=k1))
kapsayan=(df.giris<=k0)&(df.cikis>=k1)
print(f"\n=== 1) 2023-08-26 KESINTISI (19:00-21:00 UTC, 10 duz bar + 13 eksik saat) ===")
print(f"  pencerede giris/cikis yapan islem: {m.sum()}   pnl ${df[m].pnl_ankor.sum():+.2f}")
print(f"  kesintiyi KAPSAYAN acik islem: {kapsayan.sum()}   pnl ${df[kapsayan].pnl_ankor.sum():+.2f} "
      f"({df[kapsayan].pnl_ankor.sum()/df.pnl_ankor.sum()*100:+.2f}% toplamin)")
if kapsayan.sum(): print(df[kapsayan][["coin","kol","giris","cikis","R","pnl_ankor"]].to_string(index=False))

# ============ 2) 2025-10-10 COKUS BARI ============
c0=pd.Timestamp("2025-10-10 20:00",tz="UTC"); c1=pd.Timestamp("2025-10-11 02:00",tz="UTC")
m2=((df.cikis>=c0)&(df.cikis<=c1))
kaps2=(df.giris<=c0)&(df.cikis>=c0)
print(f"\n=== 2) 2025-10-10 COKUS (21:00 bari: ADA %164 range, BCH %144, XRP %115) ===")
print(f"  o pencerede CIKAN islem: {m2.sum()}  pnl ${df[m2].pnl_ankor.sum():+.2f} "
      f"({df[m2].pnl_ankor.sum()/df.pnl_ankor.sum()*100:+.1f}% toplamin)")
print(f"  cokus barinda ACIK olan: {kaps2.sum()}  pnl ${df[kaps2].pnl_ankor.sum():+.2f}")
if m2.sum(): print(df[m2][["coin","kol","giris","cikis","R","pnl_ankor"]].to_string(index=False))
# 2025-10-10 gunu tamami
g=df[(df.cikis>=pd.Timestamp("2025-10-10",tz="UTC"))&(df.cikis<pd.Timestamp("2025-10-12",tz="UTC"))]
print(f"  10-11 Ekim 2025 iki gunu: n={len(g)} pnl ${g.pnl_ankor.sum():+.2f} ort R {g.R.mean() if len(g) else 0:+.3f}")

# ============ 3) VERI BAYATLIGI: canli donemle ortusme ============
print(f"\n=== 3) BAYATLIK ===")
son=df.cikis.max(); print(f"  ankor son cikis: {son}")
for et,lab in [(pd.Timestamp("2026-06-18",tz="UTC"),"canli baslangic")]:
    ovl=df[(df.cikis>=et)]
    print(f"  {lab} sonrasi ankorda kapanan islem: {len(ovl)}  pnl ${ovl.pnl_ankor.sum():+.2f} ort R {ovl.R.mean() if len(ovl) else 0:+.3f}")
# canli pencere 2026-06-18 -> 2026-09-11 = 85 gun; backtest verisi 2026-07-19/20'de bitiyor
import datetime
cb=datetime.date(2026,6,18); cs=datetime.date(2026,9,11); vs=datetime.date(2026,7,20)
print(f"  canli pencere {(cs-cb).days} gun; backtest verisi kapsiyor {(vs-cb).days} gun "
      f"= %{(vs-cb).days/(cs-cb).days*100:.0f}; KAPSANMAYAN {(cs-vs).days} gun (%{(cs-vs).days/(cs-cb).days*100:.0f})")

# ============ 4) VERI BASLANGIC FARKI: kolun ilk islemleri ============
print(f"\n=== 4) BASLANGIC/BITIS ASIMETRISI ===")
print(df.groupby("coin").agg(ilk_giris=("giris","min"),son_cikis=("cikis","max"),n=("R","size")).to_string())

# ============ 5) son 2 ay eksikligi: aylik dagilim ============
print(f"\n=== 5) AYLIK (son 8 ay) ===")
mm=df.copy(); mm["ay"]=[x.tz_localize(None).to_period("M") for x in mm.cikis]
s=mm.groupby("ay").agg(n=("R","size"),pnl=("pnl_ankor","sum"),R=("R","mean"))
print(s.tail(8).to_string())
df.to_csv("/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/ankor_trades.csv",index=False)
print("\nyazildi: ankor_trades.csv")
