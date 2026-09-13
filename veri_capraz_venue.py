"""CAPRAZ-VENUE: MEXC vadeli BTC 1h (data/BTC_fut_1h.csv) vs Binance BTCUSDT 1m -> 1h."""
import glob, numpy as np, pandas as pd
fr=[]
for f in sorted(glob.glob("/home/user/Bot2/BTCUSDT-1m-*.csv")):
    d=pd.read_csv(f)
    d=d.iloc[:,:6]; d.columns=["ts","open","high","low","close","volume"]
    fr.append(d.astype(float))
b=pd.concat(fr).drop_duplicates("ts").sort_values("ts")
b.index=pd.to_datetime(b["ts"],unit="ms",utc=True)
b=b.drop(columns=["ts"])
B=b.resample("1h").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
M=pd.read_csv("/home/user/Bot2/data/BTC_fut_1h.csv",index_col=0,parse_dates=True)
print(f"Binance 1m->1h: {len(B)} bar  {B.index[0]} -> {B.index[-1]}")
print(f"MEXC vadeli 1h: {len(M)} bar  {M.index[0]} -> {M.index[-1]}")
ix=B.index.intersection(M.index); print(f"ortak bar: {len(ix)}")
A=M.loc[ix]; Bb=B.loc[ix]
for col in ["open","high","low","close"]:
    d=(A[col].values-Bb[col].values)/Bb[col].values*1e4
    print(f"  {col:6s} fark bp: ort {d.mean():+7.2f}  medyan {np.median(d):+7.2f}  std {d.std():7.2f}  "
          f"p99 {np.percentile(np.abs(d),99):7.1f}  max|.| {np.abs(d).max():8.1f}")
r1=np.diff(np.log(A.close.values)); r2=np.diff(np.log(Bb.close.values))
print(f"  saatlik getiri korelasyonu: {np.corrcoef(r1,r2)[0,1]:.6f}")
# bar-ici range karsilastirmasi (fitil abartisi testi)
rA=(A.high-A.low)/A.close; rB=(Bb.high-Bb.low)/Bb.close
print(f"  bar-ici range: MEXC ort %{rA.mean()*100:.4f} vs Binance %{rB.mean()*100:.4f}  oran {rA.mean()/rB.mean():.4f}")
print(f"                 MEXC p99  %{np.percentile(rA,99)*100:.3f} vs Binance %{np.percentile(rB,99)*100:.3f}")
# 2025-10-10 cokus penceresi
print("\n=== 2025-10-10 COKUS (BTC, 18:00-02:00) ===")
w=pd.date_range("2025-10-10 18:00","2025-10-11 02:00",freq="1h",tz="UTC")
for t in w:
    if t in A.index and t in Bb.index:
        a=A.loc[t]; c=Bb.loc[t]
        print(f"  {t}  MEXC H{a.high:9.1f} L{a.low:9.1f} C{a.close:9.1f} | BNC H{c.high:9.1f} L{c.low:9.1f} C{c.close:9.1f} "
              f"| lowfark {(a.low/c.low-1)*100:+6.2f}%")
# en buyuk sapmalar
d=np.abs((A.close.values-Bb.close.values)/Bb.close.values*1e4)
k=np.argsort(d)[-8:][::-1]
print("\n=== EN BUYUK 8 CLOSE SAPMASI ===")
for i in k:
    print(f"  {ix[i]}  MEXC {A.close.values[i]:.2f} vs BNC {Bb.close.values[i]:.2f}  = {d[i]:.1f}bp")
