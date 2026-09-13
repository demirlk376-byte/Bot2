import glob,os,numpy as np,pandas as pd
ANKOR=set(["SOL","ETH","ADA","NEAR","BCH","ICP","BNB","XRP","DOGE","TRX","XLM","LTC"])
print("=== SIFIR HACIMLI BARLAR (tum dosyalar) ===")
for f in sorted(glob.glob("/home/user/Bot2/data/*_fut_1h.csv")):
    coin=os.path.basename(f).replace("_fut_1h.csv","")
    d=pd.read_csv(f,index_col=0,parse_dates=True)
    z=d[d.volume==0]
    if len(z)==0: continue
    tag="ANKOR" if coin in ANKOR else "     "
    for ts,r in z.iterrows():
        flat = (r.open==r.high==r.low==r.close)
        print(f"  {tag} {coin:9s} {ts}  O{r.open:.6g} H{r.high:.6g} L{r.low:.6g} C{r.close:.6g}  duz={flat}")
print("\n=== SIFIR/NEGATIF FIYAT ===")
for f in sorted(glob.glob("/home/user/Bot2/data/*_fut_1h.csv")):
    coin=os.path.basename(f).replace("_fut_1h.csv","")
    d=pd.read_csv(f,index_col=0,parse_dates=True)
    m=(d[["open","high","low","close"]]<=0).any(axis=1)
    if m.sum(): print(coin, d[m])
