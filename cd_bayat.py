"""cd_bayat.py — D7 VERI BAYATLIGI. Ankor verisi 2026-07-19'da bitiyor, bugun
2026-09-14. data/*_uyum_1h.csv (2026-02-19 -> 2026-09-07, AYNI MEXC cekimi;
ortak pencerede fut ile BIREBIR ayni) kuyrugu eklenip YENI TABAN yeniden kosulur.

Uretim kodu DEGISTIRILMEZ: fast_bt.load calisma aninda sarmalanir (monkeypatch).
"""
import sys, os
import numpy as np, pandas as pd
import fast_bt
import deployed_backtest as DB

SRC = "local"
D = "/home/user/Bot2/data"

# ── 1) veri birlestirme dogrulamasi + monkeypatch ──
_orig = fast_bt.load
_bilgi = {}
def load_ek(coin, source="local"):
    m = _orig(coin, source="local")
    p = f"{D}/{coin}_uyum_1h.csv"
    if not os.path.exists(p):
        _bilgi[coin] = ("UYUM YOK", m.index[-1], m.index[-1], 0); return m
    u = pd.read_csv(p, index_col=0, parse_dates=True)
    ov = m.index.intersection(u.index)
    if len(ov) == 0: raise SystemExit(f"{coin}: ortak pencere YOK, birlestirme guvensiz")
    rel = ((m.loc[ov, "close"] - u.loc[ov, "close"]).abs() / u.loc[ov, "close"]).max()
    if rel > 1e-9: raise SystemExit(f"{coin}: ortak pencerede fut!=uyum (max rel {rel:.2e}) — DUR")
    ek = u[u.index > m.index[-1]]
    _bilgi[coin] = (f"ortak {len(ov)} bar, rel fark {rel:.1e}", m.index[-1], (ek.index[-1] if len(ek) else m.index[-1]), len(ek))
    return pd.concat([m, ek])
fast_bt.load = load_ek

from kronos import Kronos, Ayar
from kronos.kollar import canli_kollar, funding_yukle

BAL0 = 1000.0
CANLI = dict(maxpos=7, riskf=0.028, cap=1.50, bal0=BAL0, ayni_bar_giris=True,
             ardisik_zarar_limiti=2, cooldown_dk=240, gunluk_zarar_pct=0.35,
             tek_pozisyon_per_coin=True)
TUM = DB.DONCH + DB.SQZ + DB.BB_COINS
KES = pd.Timestamp("2026-07-19 12:00", tz="UTC")     # ankor verisinin bitisi (en gec coin)

def rap(isl, ad, yaz=True):
    if not isl:
        print(f"  {ad:<44s} n=0"); return dict(n=0)
    R=np.array([t.R for t in isl]); eff=np.array([t.eff for t in isl]); pnl=np.array([t.pnl for t in isl])
    ex=pd.to_datetime([t.cikis_ts for t in isl])
    ay=pd.Series(pnl,index=ex.tz_localize(None).to_period("M")).groupby(level=0).sum()/BAL0*100
    bil=np.cumprod(1+R*eff); bb=np.concatenate([[1.0],bil])
    d=dict(n=len(isl),ortR=float(R.mean()),top=float(pnl.sum())/BAL0*100,aylik=float(ay.mean()),
           bdd=float(((np.maximum.accumulate(bb)-bb)/np.maximum.accumulate(bb)).max()*100),
           kotu=float(ay.min()),poz=float((ay>0).mean()*100),
           sd=float(R.std(ddof=1)) if len(R)>1 else 0.0,
           se=float(R.std(ddof=1)/np.sqrt(len(R))) if len(R)>1 else 0.0,
           wr=float((R>0).mean()*100))
    if yaz:
        print(f"  {ad:<44s} n={d['n']:>5d} ortR {d['ortR']:>+.4f} (SE {d['se']:.4f}) kazanma %{d['wr']:4.1f} "
              f"toplam %{d['top']:>+8.2f} aylik %{d['aylik']:>+6.2f} bilesikDD %{d['bdd']:>6.2f} kotuay %{d['kotu']:>7.2f}")
    return d

def imza(isl):
    return [(t.kol,t.coin,t.giris_ts.value,t.cikis_ts.value,round(t.R,9)) for t in isl]

print(f"\n{'='*124}\n=== D7 · 0) VERI BIRLESTIRME ===")
fund = funding_yukle(TUM)
kollar = canli_kollar(SRC)
for c in TUM:
    b=_bilgi.get(c)
    if b: print(f"  {c:<5s} {b[0]:<34s} ankor son {str(b[1])[:16]} -> uzatilmis son {str(b[2])[:16]}  (+{b[3]} bar)")
fmax = max(s.index.max() for s in fund.values())
print(f"  funding verisi son: {fmax}  (uzatilmis pencereyi KAPSIYOR mu: {fmax >= pd.Timestamp('2026-09-07',tz='UTC')})")

print(f"\n{'='*124}\n=== D7 · 1) UZATILMIS VERI ILE YENI TABAN ===")
uz = Kronos(kollar, Ayar(kayma_bp=15.85, funding=fund, **CANLI)).kos()
r_uz = rap(uz, "UZATILMIS (2023-04 -> 2026-09-07)")

print(f"\n{'='*124}\n=== D7 · 2) ANKOR (kisa veri) ILE TABAN — nedensellik denetimi ===")
fast_bt.load = _orig
kollar_k = canli_kollar(SRC)
kisa = Kronos(kollar_k, Ayar(kayma_bp=15.85, funding=fund, **CANLI)).kos()
r_k = rap(kisa, "ANKOR (2023-04 -> 2026-07-19)  ON-KAYITLI TABAN")
uy = (r_k['n']==1712 and abs(r_k['ortR']-0.1451)<5e-4 and abs(r_k['top']-621.78)<0.5)
print(f"  on-kayitli n=1712 ortR +0.1451 toplam %+621.78 -> {'ESLESTI OK' if uy else 'ESLESMEDI DUR'}")
if not uy: sys.exit(1)

a_=[x for x in imza(uz)   if x[3] < KES.value]
b_=[x for x in imza(kisa) if x[3] < KES.value]
fark=(set(a_)-set(b_))|(set(b_)-set(a_))
print(f"  KES={KES} oncesi kapanan kararlar: uzatilmis {len(a_)} · ankor {len(b_)} · FARK {len(fark)}")
print(f"  -> {'gecmis kararlar BIREBIR AYNI (veri uzatmak gecmisi degistirmiyor)' if not fark else 'FARK VAR - incele'}")
for k in sorted(fark, key=lambda x:x[2])[:6]:
    nerede = "yalniz UZATILMIS" if k in set(a_) else "yalniz ANKOR"
    print(f"     {nerede}: {k[0]}/{k[1]} giris={pd.Timestamp(k[2])} cikis={pd.Timestamp(k[3])} R={k[4]:+.4f}")

print(f"\n{'='*124}\n=== D7 · 3) EKSIK PENCERE: ankorun GORMEDIGI donem ===")
yeni = [t for t in uz if t.cikis_ts >= KES]
r_y = rap(yeni, f"EKSIK PENCERE (cikis >= {str(KES)[:10]})")
girisyeni = [t for t in uz if t.giris_ts >= KES]
rap(girisyeni, f"  (alternatif: giris >= {str(KES)[:10]})")
if yeni:
    print(f"\n  eksik pencere suresi: {(pd.Timestamp('2026-09-07 18:00',tz='UTC')-KES).days} gun")
    print(f"  taban ort R {r_k['ortR']:+.4f} · eksik pencere ort R {r_y['ortR']:+.4f} · "
          f"fark {r_y['ortR']-r_k['ortR']:+.4f}R  (SE {r_y['se']:.4f}, z {(r_y['ortR']-r_k['ortR'])/max(r_y['se'],1e-9):+.2f})")
    ay_ = pd.Series([t.pnl for t in yeni],
                    index=pd.to_datetime([t.cikis_ts for t in yeni]).tz_localize(None).to_period("M")).groupby(level=0).sum()/BAL0*100
    print(f"  aylik getiri (eksik pencere):")
    for p_,v in ay_.items(): print(f"     {p_}  %{v:+.2f}")
    kol_ = pd.DataFrame([(t.kol,t.coin,t.R,t.pnl) for t in yeni], columns=["kol","coin","R","pnl"])
    print(f"  kol kirilimi:")
    for kk,g in kol_.groupby("kol"):
        print(f"     {kk:<9s} n={len(g):>3d} ortR {g.R.mean():+.4f} pnl %{g.pnl.sum()/BAL0*100:+.2f}")

print(f"\n{'='*124}\n=== D7 · 4) CANLI BOT DONEMI (2026-06-18 -> 2026-09-08) ===")
lo,hi = pd.Timestamp("2026-06-18",tz="UTC"), pd.Timestamp("2026-09-08",tz="UTC")
canli_d = [t for t in uz if lo <= t.cikis_ts < hi]
r_c = rap(canli_d, "KRONOS · canli donem (uzatilmis veri)")
print(f"  CANLI GERCEK (ledger, veri_bayat_olc.py): n=124 ortR +0.0837 kazanma %37.1 toplam +$58.76")
if canli_d:
    mL,sL,nL = 0.0837,1.347,124
    se = np.sqrt(r_c['sd']**2/r_c['n'] + sL**2/nL)
    print(f"  fark (canli - kronos): {mL-r_c['ortR']:+.4f}R · SE {se:.4f} · z {(mL-r_c['ortR'])/se:+.2f}")

print(f"\n{'='*124}\n=== D7 · 5) SON 12 AY / SON 6 AY (uzatilmis) ===")
for ay_g,lbl in ((365,"son 12 ay"),(180,"son 6 ay"),(90,"son 3 ay")):
    t0 = pd.Timestamp("2026-09-07 18:00",tz="UTC") - pd.Timedelta(days=ay_g)
    rap([t for t in uz if t.cikis_ts >= t0], f"{lbl} (cikis >= {str(t0)[:10]})")
print(f"{'='*124}\n")
