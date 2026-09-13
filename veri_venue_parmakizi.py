"""Venue parmak izi: 2023-08-26 MEXC kesintisi tum dosyalarda ayni mi? + listeleme rampasi"""
import glob,os,numpy as np,pandas as pd
ANKOR=["SOL","ETH","ADA","NEAR","BCH","ICP","BNB","XRP","DOGE","TRX","XLM","LTC"]
print("=== 2023-08-26 18:00-22:00 UTC PENCERESI (MEXC kesinti parmak izi) ===")
for f in sorted(glob.glob("/home/user/Bot2/data/*_fut_1h.csv")):
    coin=os.path.basename(f).replace("_fut_1h.csv","")
    d=pd.read_csv(f,index_col=0,parse_dates=True)
    w=d.loc["2023-08-26 18:00":"2023-08-26 22:00"]
    saatler=[t.hour for t in w.index]
    sifir=[t.hour for t in w.index if d.loc[t,"volume"]==0]
    print(f"  {coin:9s} barlar={saatler} sifir_hacim={sifir}")
print("\n=== LISTELEME RAMPASI: ilk 168 saat hacim / medyan hacim ===")
print(f"{'coin':9s} {'ilk_bar':26s} {'ilk7g_ort_hacim':>16s} {'tum_medyan':>14s} {'oran':>7s} {'ilk24s_min_hacim':>17s}")
for f in sorted(glob.glob("/home/user/Bot2/data/*_fut_1h.csv")):
    coin=os.path.basename(f).replace("_fut_1h.csv","")
    d=pd.read_csv(f,index_col=0,parse_dates=True)
    v=d.volume.values
    tag="*" if coin in ANKOR else " "
    print(f"{tag}{coin:8s} {str(d.index[0]):26s} {v[:168].mean():16.0f} {np.median(v):14.0f} "
          f"{v[:168].mean()/np.median(v):7.2f} {v[:24].min():17.0f}")
print("\n=== SON BARLAR: delist/donma belirtisi (son 168 saat hacim orani) ===")
for f in sorted(glob.glob("/home/user/Bot2/data/*_fut_1h.csv")):
    coin=os.path.basename(f).replace("_fut_1h.csv","")
    d=pd.read_csv(f,index_col=0,parse_dates=True)
    v=d.volume.values
    tag="*" if coin in ANKOR else " "
    print(f"{tag}{coin:8s} son_bar={d.index[-1]}  son7g/medyan={v[-168:].mean()/np.median(v):5.2f}  son7g_sifir_bar={int((v[-168:]==0).sum())}")
