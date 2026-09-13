import glob,os,numpy as np,pandas as pd
ANK=set("SOL ETH ADA NEAR BCH ICP BNB XRP DOGE TRX XLM LTC".split())
print(f"{'coin':9s} {'ayni_ardisik_OHLCV':>19s} {'neg_hacim':>10s} {'donuk_bar(O=H=L=C)':>19s} {'tekrar_OHLCV_blok':>18s} {'1200g?':>8s}")
for f in sorted(glob.glob("/home/user/Bot2/data/*_fut_1h.csv")):
    coin=os.path.basename(f).replace("_fut_1h.csv","")
    d=pd.read_csv(f,index_col=0,parse_dates=True)
    ohlcv=d[["open","high","low","close","volume"]]
    ardisik=int((ohlcv.shift(1)==ohlcv).all(axis=1).sum())
    neg=int((d.volume<0).sum())
    donuk=int(((d.open==d.high)&(d.high==d.low)&(d.low==d.close)).sum())
    tekrar=int(ohlcv.duplicated().sum())
    gun=(d.index[-1]-d.index[0]).total_seconds()/86400
    tag="*" if coin in ANK else " "
    print(f"{tag}{coin:8s} {ardisik:19d} {neg:10d} {donuk:19d} {tekrar:18d} {gun:8.1f}")
print("\n=== FIYAT SIRALAMA MANTIGI (tam) ===")
tot={"h<o":0,"h<c":0,"l>o":0,"l>c":0,"h<l":0,"n":0}
for f in sorted(glob.glob("/home/user/Bot2/data/*_fut_1h.csv")):
    d=pd.read_csv(f,index_col=0,parse_dates=True)
    tot["n"]+=len(d)
    tot["h<o"]+=int((d.high<d.open).sum()); tot["h<c"]+=int((d.high<d.close).sum())
    tot["l>o"]+=int((d.low>d.open).sum());  tot["l>c"]+=int((d.low>d.close).sum())
    tot["h<l"]+=int((d.high<d.low).sum())
print(" ",tot)
