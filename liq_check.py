"""
liq_check.py — Stop, likidasyon bandının ÖTESİNDE kalan işlemler + GERÇEK maliyeti.

Denetimde çıkmış ama doğrulanmamış bulgu: donchian işlemlerinin bir kısmında SL (2×ATR),
10x izole likidasyon bandının (~%9.5 ters hareket) ÖTESİNDE → borsa stop'tan ÖNCE kapatır.
Bot bunu HİÇ kontrol etmiyor (SL'i ATR'ye koyar, likidasyona bakmaz).

MATEMATİK: izole marjda marj = nominal/kaldıraç; risk-tabanlı boyutta geniş stop = küçük nominal
= küçük marj → likidasyon kaybı (%1.9) hedeflenen kayıptan (%2.25) DAHA AZ. Yani sorun kayıp
büyüklüğü DEĞİL.
ASIL SORUN: TOPARLANMA İHTİMALİNİ ÖLDÜRÜR. −%9.5'e inip sonra dönüp TP'ye giden işlem, likidasyonla
orada kesilir. Backtest bunu modellemiyor (orada işlem yaşamaya devam eder).

ÖLÇÜLEN: (a) kaç işlemde sl_pct > likidasyon bandı, (b) O İŞLEMLERİN GERÇEKTE NE OLDUĞU —
likidasyon seviyesine değip sonra TP'ye giden var mı, (c) dolar etkisi.
"""
import sys
import numpy as np
import fast_bt
from indicators import atr as atr_fn
from strategies.donchian import DonchianStrategy

BAL0=190.0; FEE=0.0001; RISKF=0.0225; CAP=1.0
DONCH=["SOL","ETH","ADA","NEAR","BCH","ICP","BNB"]
SL_A, RR, MH = 2.0, 2.5, 30
LIQ_BANDS = [0.090, 0.095, 0.100]     # 10x izole: 1/lev − bakım marjı

def gen(m):
    d = fast_bt.resample(m,"4h")
    atr = atr_fn(d["high"],d["low"],d["close"],14).values
    ch_hi = d["high"].rolling(40).max().shift(1).values
    ch_lo = d["low"].rolling(40).min().shift(1).values
    from indicators import ema as ema_fn
    ema200 = ema_fn(d["close"],200).values
    hi=d["high"].values; lo=d["low"].values; cl=d["close"].values; idx=d.index; n=len(cl)
    out=[]; occ=-1
    for i in range(260,n-1):
        a=atr[i]
        if not np.isfinite(a) or a<=0 or i<=occ: continue
        if not (np.isfinite(ch_hi[i]) and np.isfinite(ch_lo[i]) and np.isfinite(ema200[i])): continue
        c=cl[i]
        if c>ch_hi[i] and c>ema200[i]: d_=1
        elif c<ch_lo[i] and c<ema200[i]: d_=-1
        else: continue
        e=c; sld=SL_A*a; slp=e-d_*sld; tp=e+d_*RR*sld
        ep=None; j=i; reason="hold"; worst=0.0   # worst = en kötü ters hareket (oran)
        for j in range(i+1, min(i+1+MH,n)):
            adv = (lo[j]-e)/e*d_ if d_==1 else (hi[j]-e)/e*d_   # negatif = aleyhte
            worst = min(worst, adv)
            if d_==1:
                if lo[j]<=slp: ep=slp; reason="sl"; break
                if hi[j]>=tp: ep=tp; reason="tp"; break
            else:
                if hi[j]>=slp: ep=slp; reason="sl"; break
                if lo[j]<=tp: ep=tp; reason="tp"; break
        if ep is None: j=min(i+MH,n-1); ep=cl[j]
        R = d_*(ep-e)/sld - 2*FEE*e/sld
        out.append({"R":R,"sl_pct":sld/e,"reason":reason,"worst":-worst})  # worst>0 = aleyhte %
    return out

def main():
    src = sys.argv[1] if len(sys.argv)>1 else "mexc_futures"
    trs=[]
    for c in DONCH: trs += gen(fast_bt.load(c, source=src))
    n=len(trs)
    print(f"\n{'='*88}\n=== LİKİDASYON BANDI KONTROLÜ — {n} donchian işlemi (10x izole) ===")
    for band in LIQ_BANDS:
        beyond=[t for t in trs if t["sl_pct"]>band]
        print(f"\n  --- likidasyon bandı %{band*100:.1f} ---")
        print(f"  SL bandın ÖTESİNDE: {len(beyond)} işlem (%{len(beyond)/n*100:.1f})")
        if not beyond: continue
        # bu işlemlerden kaçı likidasyon seviyesine DEĞDİ?
        touched=[t for t in beyond if t["worst"]>=band]
        print(f"    bunlardan likidasyon seviyesine DEĞEN: {len(touched)} (%{len(touched)/max(len(beyond),1)*100:.0f})")
        if touched:
            saved=[t for t in touched if t["R"]>0]     # değip sonra KAZANMIŞ = likidasyon öldürürdü
            lost =[t for t in touched if t["R"]<=0]
            eff=lambda ts: sum(t["R"]*min(RISKF,CAP*t["sl_pct"])*BAL0 for t in ts)
            print(f"    → değip SONRA KAZANAN (likidasyon bunları ÖLDÜRÜRDÜ): {len(saved)} işlem, ${eff(saved):+.0f}")
            print(f"    → değip zaten kaybeden (fark yok): {len(lost)} işlem, ${eff(lost):+.0f}")
            # likidasyon senaryosu: bu işlemler bandda kapansaydı
            liq_loss = -sum(min(RISKF,CAP*t["sl_pct"])*BAL0*(band/t["sl_pct"]) for t in touched)
            actual   = eff(touched)
            print(f"    LİKİDASYON SENARYOSU: ${liq_loss:+.0f}  vs  GERÇEK ${actual:+.0f}  → fark ${liq_loss-actual:+.0f}")
    tot = sum(t["R"]*min(RISKF,CAP*t["sl_pct"])*BAL0 for t in trs)
    print(f"\n  (karşılaştırma: donchian toplam ${tot:+.0f})")
    print("LIQDONE")

if __name__=="__main__": main()
