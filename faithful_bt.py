"""
faithful_bt.py — ÜRETİM SINIFLARIYLA backtest = canlı botun BİREBİR yapacağı şey.

CANLI İLE BYTE-DENK olması için (main.py'den doğrulandı):
  • Aynı sınıflar: main.py `from strategies.squeeze import SqueezeStrategy`,
    `from strategies.donchian import DonchianStrategy` — burada da AYNILARI.
  • Aynı fonksiyonlar: main.py `from indicators import atr, adx` — burada da.
  • Aynı periyotlar: atr_period=14, adx_period=14 (config.py).
  • Aynı PENCERE: squeeze canlıda get_candles(120) → burada d1[i-119:i+1] (120 bar).
    donchian canlıda get_candles(260) → burada d4[i-259:i+1] (260 bar).
  • ATR/ADX PENCERE-YEREL hesaplanır (canlı: 120-bar df üstünde .iloc[-1]) —
    tam serili değil. ADX ~20.0 sınırında serinin uzunluğu değeri kaydırıp
    kapıyı ters çevirebildiği için bu ŞART (aksi halde canlı ile sapardı).
  • Aynı kapı: squeeze bo_allowed = regime!="ranging" = adx>20 (_get_regime,
    adx_ranging_threshold=20.0). Burada `if adxv<=20.0: continue`.
  • Aynı çıkış: squeeze/donchian BE/trailing DIŞINDA (main.py:1079 sadece
    orb/ifvg) → sabit SL/TP + max-hold. simtrades tam bunu yapar; SL girişteki
    pencere-yerel ATR ile ölçülür (canlı RiskManager ile aynı atr_val).

Sonuç: bu script'in ürettiği sinyaller ve trade'ler = canlı botun AYNISI.
Yavaş ama CANLIYLA BİREBİR. Kullanım: python faithful_bt.py [BTC]
"""
import sys, glob
import numpy as np, pandas as pd
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy
from indicators import atr as atr_fn, adx as adx_fn
import fast_bt

RISK=0.02; BAL=190.0; FEE=0.0001
coin = sys.argv[1] if len(sys.argv)>1 else "BTC"
# 2. arg: veri kaynağı. Varsayılan mexc_futures = CANLI-BİREBİR (borsa+enstrüman).
# 'binance_csv' = yerel BTC 1m CSV (hızlı ama Binance venue ≠ canlı MEXC vadeli).
source = sys.argv[2] if len(sys.argv)>2 else "mexc_futures"

def load(c):
    # Her coin CANLININ işlem gördüğü MEXC VADELİ veriden (COIN/USDT:USDT) yüklenir.
    # Eski hata: BTC yerel Binance CSV, SOL MEXC spot çekiliyordu → venue farkı.
    return fast_bt.load(c, source=source)

def simtrades(df, ents, sl_mult, rr, max_hold):
    """ents: (i, dir, atr_entry) — atr_entry canlının o barda kullandığı
    pencere-yerel ATR (RiskManager'ın build_trade_setup'a verdiği atr_val).
    SL/TP tam bu ATR ile ölçülür → canlı ile aynı seviyeler."""
    hi=df["high"].values; lo=df["low"].values; cl=df["close"].values; idx=df.index; n=len(cl)
    tr=[]; occ=-1
    for (i,d,av) in ents:
        if i<=occ or i>=n-1: continue
        if np.isnan(av) or av<=0: continue
        sld=sl_mult*av; e=cl[i]; sl=e-d*sld; tp=e+d*rr*sld; ep=None; j=i
        for j in range(i+1,min(i+1+max_hold,n)):
            if d==1:
                if lo[j]<=sl: ep=sl; break
                if hi[j]>=tp: ep=tp; break
            else:
                if hi[j]>=sl: ep=sl; break
                if lo[j]<=tp: ep=tp; break
        if ep is None: j=min(i+max_hold,n-1); ep=cl[j]
        tr.append({"r":d*(ep-e)/sld - 2*FEE*e/sld,"year":idx[i].year}); occ=j
    return tr

def prod_bb(m):
    # Canlı BB/mean_rev: 1h/120 pencere, trending blok (adx>=28), market-fallback →
    # close'da fill, SL 3xATR TP rr1.667 (=5xATR), max-hold 48. analyze(df) ATR'siz.
    try:
        from config import load_config
        from strategies.mean_reversion import MeanReversionStrategy
        s = MeanReversionStrategy(load_config().strategy)
    except Exception as e:
        print(f"  BB atlandı ({e})"); return []
    d1 = fast_bt.resample(m, "1h"); ents = []
    for i in range(260, len(d1)):
        sub = d1.iloc[max(0, i-119):i+1]
        av = atr_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if np.isnan(av) or av <= 0: continue
        adxr = adx_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if (float(adxr) if np.isfinite(adxr) else 20.0) >= 28.0: continue   # bb_allowed: trending blok
        sg = s.analyze(sub)
        if sg.direction != 0: ents.append((i, sg.direction, float(av)))
    return simtrades(d1, ents, 3.0, 1.667, 48)


def prod_donchian(m):
    # Canlı: df_4h=get_candles(260); atr_4h=atr(df_4h,14).iloc[-1]; analyze(df_4h,atr_4h)
    d4=fast_bt.resample(m,"4h"); s=DonchianStrategy(channel=40,rr=2.0,sl_atr=2.0,ema_trend=200)
    ents=[]
    for i in range(260,len(d4)):
        sub=d4.iloc[max(0,i-259):i+1]                                   # get_candles(260)
        av=atr_fn(sub["high"],sub["low"],sub["close"],14).iloc[-1]      # pencere-yerel atr_4h
        if np.isnan(av) or av<=0: continue
        sg=s.analyze(sub,float(av))
        if sg.direction!=0: ents.append((i,sg.direction,float(av)))
    return simtrades(d4,ents,2.0,2.0,30)

def prod_squeeze(m):
    # Canlı: df=get_candles(120); atr_val=atr(df,14).iloc[-1];
    #        adx=_adx_indicator(df,14).iloc[-1]; bo_allowed = adx>20; analyze(df,atr_val)
    d1=fast_bt.resample(m,"1h"); s=SqueezeStrategy(kc_mult=1.5,min_squeeze_bars=5,sl_atr=2.0,rr=2.5,mtf_filter=True)
    ents=[]
    for i in range(260,len(d1)):
        sub=d1.iloc[max(0,i-119):i+1]                                   # get_candles(120)
        av=atr_fn(sub["high"],sub["low"],sub["close"],14).iloc[-1]      # pencere-yerel atr_val
        if np.isnan(av) or av<=0: continue
        adxr=adx_fn(sub["high"],sub["low"],sub["close"],14).iloc[-1]    # pencere-yerel regime ADX
        adxv=float(adxr) if np.isfinite(adxr) else 20.0
        if adxv<=20.0: continue   # canlı bo_allowed=False (regime=="ranging", adx<=20)
        sg=s.analyze(sub,float(av))
        if sg.direction!=0: ents.append((i,sg.direction,float(av)))
    return simtrades(d1,ents,2.0,2.5,48)

def rep(name,tr):
    if not tr: print(f"  {name}: sinyal yok"); return
    df=pd.DataFrame(tr); r=df["r"].values
    gp=r[r>0].sum(); gl=-r[r<0].sum(); pf=gp/gl if gl>0 else 9.99
    print(f"  {name:10s} n={len(r):>3d} WR{(r>0).mean():>3.0%} PF{pf:4.2f} ${r.sum()*BAL*RISK:+7.2f}  [CANLI-BİREBİR]")
    for yr in sorted(df.year.unique()):
        ry=df[df.year==yr]["r"].values; g1=ry[ry>0].sum(); g2=-ry[ry<0].sum()
        print(f"      {yr} n={len(ry):>3d} WR{(ry>0).mean():>3.0%} PF{(g1/g2 if g2>0 else 9.99):4.2f} {ry.sum()*BAL*RISK:+7.2f}$")

if __name__ == "__main__":
    coins = [c.strip().upper() for c in coin.split(",")]   # çoklu coin destekli
    for c in coins:
        print(f"\n=== {c} — CANLI BOTUN BİREBİR YAPACAĞI (yıl-yıl) ===", flush=True)
        try:
            m = load(c)
        except Exception as e:
            print(f"  {c} veri hatası: {e}", flush=True); continue
        rep("donchian", prod_donchian(m))
        rep("squeeze", prod_squeeze(m))
        rep("BB/mean_rev", prod_bb(m))
