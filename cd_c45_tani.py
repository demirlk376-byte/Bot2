"""cd_c45_tani.py — C4 (stop dolum gap) ve C5 (bar ici yol belirsizligi) TANI.
Uretim koduna DOKUNMAZ. Yeni tabani kosar, islemleri ve kol OHLC'sini alir,
her islemin CIKIS BARINI acip sayar. Sadece SAYIM — yeniden kosma yok."""
import sys, pickle, os
import numpy as np, pandas as pd
import deployed_backtest as DB
from kronos import Kronos, Ayar
from kronos.kollar import canli_kollar, funding_yukle

SRC = sys.argv[1] if len(sys.argv) > 1 else "local"
SCR = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad"
os.makedirs(SCR, exist_ok=True)
BAL0 = 1000.0
CANLI = dict(maxpos=7, riskf=0.028, cap=1.50, bal0=BAL0, ayni_bar_giris=True,
             ardisik_zarar_limiti=2, cooldown_dk=240, gunluk_zarar_pct=0.35,
             tek_pozisyon_per_coin=True)
TUM = DB.DONCH + DB.SQZ + DB.BB_COINS
fund = funding_yukle(TUM)

def rap(isl, ad):
    R=np.array([t.R for t in isl]); eff=np.array([t.eff for t in isl]); pnl=np.array([t.pnl for t in isl])
    ex=pd.to_datetime([t.cikis_ts for t in isl])
    ay=pd.Series(pnl,index=ex.tz_localize(None).to_period("M")).groupby(level=0).sum()/BAL0*100
    bil=np.cumprod(1+R*eff); bb=np.concatenate([[1.0],bil])
    d=dict(n=len(isl),ortR=float(R.mean()),top=float(pnl.sum())/BAL0*100,aylik=float(ay.mean()),
           bdd=float(((np.maximum.accumulate(bb)-bb)/np.maximum.accumulate(bb)).max()*100),
           kotu=float(ay.min()),poz=float((ay>0).mean()*100))
    print(f"  {ad:<42s} n={d['n']:>5d} ortR {d['ortR']:>+.4f} toplam %{d['top']:>+8.2f} "
          f"aylik %{d['aylik']:>+6.2f} bilesikDD %{d['bdd']:>6.2f} kotuay %{d['kotu']:>7.2f} pozAy %{d['poz']:.0f}")
    return d

print(f"\n{'='*110}\n=== 0) TABAN YENIDEN URETIMI ===")
kollar = canli_kollar(SRC)
kitap = Kronos(kollar, Ayar(kayma_bp=15.85, funding=fund, **CANLI)).kos()
rb = rap(kitap, "yeni on-kayitli taban (kayma+funding)")
uy = (rb['n']==1712 and abs(rb['ortR']-0.1451)<5e-4 and abs(rb['top']-621.78)<0.5
      and abs(rb['bdd']-51.58)<0.05 and abs(rb['kotu']+34.39)<0.05)
print(f"  on-kayitli: n=1712 ortR +0.1451 toplam %+621.78 aylik %+15.54 bilesikDD %51.58 kotuay %-34.39")
print(f"  -> {'ESLESTI OK' if uy else 'ESLESMEDI - DUR'}")
if not uy: sys.exit(1)

# kol OHLC haritasi
OH = {}
for k in kollar:
    d = k.besleme._d
    OH[(k.ad, k.coin)] = dict(o=d["open"].values, h=d["high"].values, l=d["low"].values,
                              c=d["close"].values, pos={t.value: i for i, t in enumerate(d.index)})
pickle.dump(kitap, open(f"{SCR}/taban_kitap.pkl","wb"))

print(f"\n{'='*110}\n=== C4  STOP DOLUM FIYATI: cikis barinin ACILISI stopun otesinde mi? ===")
rows=[]
for t in kitap:
    M = OH[(t.kol, t.coin)]
    i = M["pos"][t.cikis_ts.value]; i0 = M["pos"][t.giris_ts.value]
    o, h, l, c = M["o"][i], M["h"][i], M["l"][i], M["c"][i]
    pc = M["c"][i-1] if i>0 else np.nan          # onceki barin kapanisi
    slp = t.giris - t.yon*t.sld
    otede = (o < slp) if t.yon==1 else (o > slp)
    # gercekci dolum: gap varsa acilis, yoksa tam slp
    dolum = o if (t.neden=="sl" and otede) else t.cikis
    dR = t.yon*(dolum - t.cikis)/t.sld            # R farki (negatif = daha kotu)
    rows.append((t.kol,t.coin,t.neden,t.yon,t.giris,t.cikis,slp,o,pc,l,h,t.sld,t.sl_pct,t.R,dR,t.eff,
                 bool(otede), int(i-i0), t.giris_ts, t.cikis_ts))
D = pd.DataFrame(rows, columns=["kol","coin","neden","yon","giris","cikis","slp","acilis","onceki_kapanis",
                                "lo","hi","sld","sl_pct","R","dR","eff","acilis_otede","bar","gts","xts"])
sl = D[D.neden=="sl"]
print(f"  toplam islem {len(D)} · stop cikisi {len(sl)} (%{len(sl)/len(D)*100:.1f}) · "
      f"tp {int((D.neden=='tp').sum())} · sure {int((D.neden=='sure').sum())} · veri_sonu {int((D.neden=='veri_sonu').sum())}")
g = sl[sl.acilis_otede]
print(f"  STOP cikislarinda cikis barinin ACILISI stopun OTESINDE: {len(g)} / {len(sl)} (%{len(g)/max(len(sl),1)*100:.2f})")
if len(g):
    print(f"    o islemlerde ortalama ek kayip: {g.dR.mean():+.4f}R  (medyan {g.dR.median():+.4f}R, en kotu {g.dR.min():+.4f}R)")
print(f"  TUM kitapta toplam R etkisi: {D.dR.sum():+.4f}R  -> islem basina {D.dR.mean():+.6f}R")
# bar suregelisligi: open[i] != close[i-1] ne siklikta?
print(f"\n  --- bar sureklilik denetimi (acilis = onceki kapanis mi?) ---")
for (ad,coin),M in sorted(OH.items()):
    o=M["o"][1:]; pc=M["c"][:-1]
    fark = np.abs(o-pc)/np.maximum(pc,1e-12)
    print(f"    {ad:<9s}{coin:<5s} n={len(o):>6d}  acilis!=onceki_kapanis: {int((fark>1e-12).sum()):>5d} "
          f"(%{ (fark>1e-12).mean()*100:5.2f})  ort |gap| {fark.mean()*1e4:>7.3f}bp  max {fark.max()*1e4:>9.1f}bp")

print(f"\n{'='*110}\n=== C5  BAR ICI YOL: cikis barinda HEM stop HEM hedef gorundu mu? ===")
amb=[]
for t in kitap:
    M = OH[(t.kol, t.coin)]
    i = M["pos"][t.cikis_ts.value]
    h,l = M["h"][i], M["l"][i]
    slp = t.giris - t.yon*t.sld
    tp  = t.giris + t.yon*(abs(t.cikis-t.giris)/t.sld if False else 0)
    amb.append((h,l,slp))
# tp'yi kol parametresinden hesapla
RRS = {"donchian":2.5, "squeeze":2.5, "bb":1.667}
cift=0; cift_l=[]
for t in kitap:
    M = OH[(t.kol, t.coin)]
    i = M["pos"][t.cikis_ts.value]
    h,l = M["h"][i], M["l"][i]
    slp = t.giris - t.yon*t.sld
    tp  = t.giris + t.yon*RRS[t.kol]*t.sld
    if t.yon==1: ikisi = (l<=slp) and (h>=tp)
    else:        ikisi = (h>=slp) and (l<=tp)
    if ikisi: cift+=1; cift_l.append((t.kol,t.coin,str(t.giris_ts)[:16],str(t.cikis_ts)[:16],t.neden,t.R,t.eff))
print(f"  cikis barinda HEM stop HEM hedef dokunulan islem: {cift} / {len(kitap)} (%{cift/len(kitap)*100:.2f})")
for r in cift_l[:25]: print(f"    {r[0]:<9s}{r[1]:<5s} {r[2]} -> {r[3]} neden={r[4]:<5s} R={r[5]:+.3f} eff={r[6]:.4f}")
# ayrica: TP cikisi olan islemlerde ayni barda stop da gorundu mu (ters yon)
print(f"\n  NOT: bu sayim yalniz KRONOS'un fiilen cikis yaptigi bari kontrol eder. Belirsizlik")
print(f"  bandi icin motorun iyimser varsayimla YENIDEN KOSULMASI gerekir (cd_yol.py).")
D.to_pickle(f"{SCR}/c45_tani.pkl")
print(f"\n{'='*110}\n")
