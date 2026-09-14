"""cd_cikis_kayma.py — C4'un GENEL HALI: KRONOS cikis tarafinda HIC kayma
kesmiyor. Giris 15.85bp odenip cikis bedava varsayiliyor.

Cikis tipi -> gercek emir tipi:
  sl   (stop-market)  -> MARKET, kayma ODENIR
  sure (max-hold)     -> MARKET, kayma ODENIR
  tp   (limit)        -> MAKER, kayma YOK (limit fiyattan dolar)
Bu dosya birinci-mertebe (post-hoc) bedeli hesaplar. Yol bagimliligini
olcmek icin cd_yol.py'nin stop_ek_bp taramasiyla KARSILASTIRILIR."""
import pickle, numpy as np, pandas as pd
SCR="/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad"
kitap=pickle.load(open(f"{SCR}/taban_kitap.pkl","rb"))
BAL0=1000.0
R=np.array([t.R for t in kitap]); eff=np.array([t.eff for t in kitap])
sp=np.array([t.sl_pct for t in kitap]); nd=np.array([t.neden for t in kitap])
ex=pd.to_datetime([t.cikis_ts for t in kitap])

def olc(mask,bp,ad):
    d=np.where(mask,(bp/1e4)/sp,0.0)
    R2=R-d
    pnl=R2*eff*BAL0
    ay=pd.Series(pnl,index=ex.tz_localize(None).to_period("M")).groupby(level=0).sum()/BAL0*100
    bil=np.concatenate([[1.0],np.cumprod(1+R2*eff)])
    dd=float(((np.maximum.accumulate(bil)-bil)/np.maximum.accumulate(bil)).max()*100)
    print(f"  {ad:<46s} ortR {R2.mean():+.4f} ({R2.mean()-R.mean():+.4f}) toplam %{pnl.sum()/BAL0*100:+8.2f} "
          f"aylik %{ay.mean():+6.2f} bilesikDD %{dd:6.2f} kotuay %{ay.min():+7.2f}")
    return R2.mean()

print(f"\n{'='*118}\n=== CIKIS KAYMASI — C4'un genel hali (birinci mertebe, yol etkisi HARIC) ===")
print(f"  cikis tipi dagilimi: " + " · ".join(f"{k} {int((nd==k).sum())}" for k in ("sl","tp","sure","veri_sonu")))
print(f"  ort 1/sl_pct = {np.mean(1/sp):.2f}  -> 1bp cikis kaymasi ~ {1e-4*np.mean(1/sp):.5f}R")
print(f"\n  TABAN: ortR {R.mean():+.4f} toplam %{(R*eff*BAL0).sum()/BAL0*100:+.2f}")
for bp in (5,10,15.85,25):
    olc(nd=="sl", bp, f"A) yalniz STOP cikisina {bp}bp")
print()
for bp in (5,10,15.85,25):
    olc((nd=="sl")|(nd=="sure"), bp, f"B) STOP + SURE (market cikislar) {bp}bp")
print()
for bp in (15.85,):
    olc(np.ones(len(R),bool), bp, f"C) TUM cikislara {bp}bp (en karamsar)")
print(f"\n  ON-KAYITLI TESPIT TABANI: SE 0.0354 · 2sigma = 0.0708 · gecme bari delta >= +0.0694")
print(f"{'='*118}\n")
