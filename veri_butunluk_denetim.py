"""VERI BUTUNLUGU DENETIMI - salt okuma. data/*_fut_1h.csv dosyalarini olcer."""
import glob, os, sys
import numpy as np, pandas as pd

FILES = sorted(glob.glob("/home/user/Bot2/data/*_fut_1h.csv"))
# ankorun kullandigi coinler
DONCH = ["SOL","ETH","ADA","NEAR","BCH","ICP","BNB"]
SQZ   = ["XRP","DOGE","TRX","XLM"]
BB    = ["LTC"]
ANKOR = set(DONCH+SQZ+BB)

rows=[]
detay={}
for f in FILES:
    coin = os.path.basename(f).replace("_fut_1h.csv","")
    d = pd.read_csv(f, index_col=0, parse_dates=True)
    idx = d.index
    n = len(d)
    # SIRA
    mono = bool(idx.is_monotonic_increasing)
    strict = bool(idx.is_monotonic_increasing and idx.is_unique)
    ndup = int(idx.duplicated().sum())
    geri = int((idx.to_series().diff().dt.total_seconds() < 0).sum())
    # BOSLUK
    diffs = idx.to_series().diff().dt.total_seconds()[1:]
    gapmask = diffs > 3600
    n_gap_ev = int(gapmask.sum())
    eksik_saat = int(((diffs[gapmask]/3600)-1).sum()) if n_gap_ev else 0
    maxgap = float(diffs.max()/3600) if n>1 else 0
    # beklenen bar
    span_h = int((idx[-1]-idx[0]).total_seconds()//3600)+1
    # MANTIK
    o,h,l,c,v = (d[x].values.astype(float) for x in ["open","high","low","close","volume"])
    v_hi = int((h < np.maximum(o,c) - 1e-12).sum())
    v_lo = int((l > np.minimum(o,c) + 1e-12).sum())
    v_hl = int((h < l).sum())
    # SIFIR / NaN
    nan_p = int(np.isnan(np.c_[o,h,l,c]).sum())
    nan_v = int(np.isnan(v).sum())
    zero_p = int(((np.c_[o,h,l,c] <= 0).sum()))
    zero_v = int((v == 0).sum())
    # UC DEGER: bar ici (high-low)/low ve bar-bar close degisimi
    rng = (h-l)/np.where(l>0,l,np.nan)
    ret = np.abs(np.diff(c)/c[:-1])
    n_rng50 = int((rng>0.5).sum()); n_ret50 = int((ret>0.5).sum())
    n_rng20 = int((rng>0.2).sum()); n_ret20 = int((ret>0.2).sum())
    rows.append(dict(coin=coin, n=n, bas=str(idx[0]), son=str(idx[-1]),
        mono=mono, strict=strict, dup=ndup, geri=geri,
        gap_ev=n_gap_ev, eksik_saat=eksik_saat, maxgap_h=round(maxgap,1),
        span_h=span_h, kapsam=round(n/span_h*100,2),
        ihl_hi=v_hi, ihl_lo=v_lo, ihl_hl=v_hl,
        nanp=nan_p, nanv=nan_v, zerop=zero_p, zerov=zero_v,
        rng50=n_rng50, ret50=n_ret50, rng20=n_rng20, ret20=n_ret20,
        ankor=(coin in ANKOR)))
    detay[coin]=(d, diffs, gapmask, rng, ret)

t = pd.DataFrame(rows)
pd.set_option("display.width",250); pd.set_option("display.max_columns",40)
print("=== TUM DOSYALAR ===")
print(t[["coin","n","bas","son","mono","strict","dup","geri","gap_ev","eksik_saat","maxgap_h","kapsam","ankor"]].to_string(index=False))
print()
print("=== MANTIK / SIFIR / UC DEGER ===")
print(t[["coin","ihl_hi","ihl_lo","ihl_hl","nanp","nanv","zerop","zerov","rng20","rng50","ret20","ret50","ankor"]].to_string(index=False))
print()
print("--- OZET (ankor 12 coin) ---")
a = t[t.ankor]
print(f"  ankor coin sayisi: {len(a)}  (beklenen 12)")
print(f"  toplam eksik saat: {a.eksik_saat.sum()}   toplam bosluk olayi: {a.gap_ev.sum()}")
print(f"  tekrar: {a.dup.sum()}  geri giden: {a.geri.sum()}  monoton olmayan: {(~a.mono).sum()}")
print(f"  OHLC ihlali: hi {a.ihl_hi.sum()} lo {a.ihl_lo.sum()} h<l {a.ihl_hl.sum()}")
print(f"  NaN fiyat {a.nanp.sum()} NaN hacim {a.nanv.sum()} sifir fiyat {a.zerop.sum()} sifir hacim {a.zerov.sum()}")
print(f"  bar sayisi benzersiz degerler: {sorted(a.n.unique())}")
print(f"  baslangic damgalari: {sorted(a.bas.unique())}")
print(f"  bitis damgalari: {sorted(a.son.unique())}")
print()
print("--- OZET (tum 31) ---")
print(f"  eksik saat toplam {t.eksik_saat.sum()} | dup {t.dup.sum()} | h<l {t.ihl_hl.sum()} | sifir hacim {t.zerov.sum()}")
print(f"  bar sayilari: {sorted(t.n.unique())}")
print(f"  baslangiclar: {sorted(t.bas.unique())}")
print(f"  bitisler: {sorted(t.son.unique())}")

# Bosluk yerleri (ankor coinler)
print("\n=== BOSLUK YERLERI (ankor coinler, ilk 15) ===")
for coin in sorted(ANKOR):
    if coin not in detay: print(f"  {coin}: DOSYA YOK"); continue
    d, diffs, gapmask, rng, ret = detay[coin]
    g = diffs[gapmask]
    if len(g)==0: print(f"  {coin}: bosluk YOK"); continue
    print(f"  {coin}: {len(g)} bosluk olayi, {int(((g/3600)-1).sum())} eksik saat")
    for ts, sec in list(g.items())[:15]:
        print(f"      {ts}  onceki bardan {sec/3600:.0f}h sonra (eksik {sec/3600-1:.0f} saat)")

# Uc degerler
print("\n=== UC DEGER DETAY (|bar-bar close| > %20, ankor coinler) ===")
for coin in sorted(ANKOR):
    if coin not in detay: continue
    d, diffs, gapmask, rng, ret = detay[coin]
    c = d["close"].values.astype(float)
    w = np.where(ret>0.2)[0]
    if len(w)==0: continue
    for i in w:
        print(f"  {coin} {d.index[i+1]}  {c[i]:.6g} -> {c[i+1]:.6g}  ({(c[i+1]/c[i]-1)*100:+.1f}%)  hacim {d['volume'].values[i+1]:.0f}")
print("\n=== BAR-ICI RANGE > %20 (ankor coinler) ===")
for coin in sorted(ANKOR):
    if coin not in detay: continue
    d, diffs, gapmask, rng, ret = detay[coin]
    w = np.where(rng>0.2)[0]
    for i in w:
        r=d.iloc[i]
        print(f"  {coin} {d.index[i]}  O{r.open:.6g} H{r.high:.6g} L{r.low:.6g} C{r.close:.6g} ({rng[i]*100:.0f}% range) V{r.volume:.0f}")
