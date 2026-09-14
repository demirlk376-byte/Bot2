"""
kronos_netted.py — CANLI NETTED KAPISI eklenince dört ek kol ne oluyor?

BULGU: execution.py:403 "One-position-per-symbol guard (LIVE/netted only)".
MEXC tek-yön modda bir sembol = bir net pozisyon. KRONOS bunu modellemiyordu,
(kol,coin) ciftlerini bagimsiz slot sayiyordu. Sonuc: motor dort ek kolu
gunde 11.3 islem kosturuyordu, canli 0.42 -> 27x fazla.

Ankorun 3 kolu AYRIK coinlerde (donchian 7 / squeeze 4 / bb 1, cakisma YOK)
oldugu icin bu kapi ankoru HIC etkilememeli — once onu dogrula, sonra ek
kollarla olc.
"""
import sys, numpy as np, pandas as pd
import deployed_backtest as A
from kronos import Kronos, Ayar
from kronos.kollar import canli_kollar
import kollar_ek

SRC = sys.argv[1] if len(sys.argv) > 1 else "local"
T = dict(maxpos=7, riskf=0.028, cap=1.50, bal0=A.BAL0, kayma_bp=15.85,
         ayni_bar_giris=True, ardisik_zarar_limiti=2, cooldown_dk=240,
         gunluk_zarar_pct=0.35)

def olc(isl, etiket, sayac=None):
    if not isl: print(f"  {etiket:<46s} (islem yok)"); return None
    R=np.array([t.R for t in isl]); pnl=np.array([t.pnl for t in isl])
    ex=pd.to_datetime([t.cikis_ts for t in isl])
    eq=np.concatenate([[A.BAL0],A.BAL0+np.cumsum(pnl)])
    bil=np.concatenate([[1.0],np.cumprod(1+R*np.array([t.eff for t in isl]))])
    ay=pd.Series(pnl,index=ex.tz_localize(None).to_period("M")).groupby(level=0).sum()/A.BAL0*100
    gun=(max(ex)-min(ex)).days or 1
    d=dict(n=len(isl),kar=pnl.sum(),ortR=R.mean(),gunluk=len(isl)/gun,
           bdd=float(((np.maximum.accumulate(bil)-bil)/np.maximum.accumulate(bil)).max()*100),
           kotu=ay.min())
    ek=f" · coin_engel {sayac['coin_engel']:>6d}" if sayac else ""
    print(f"  {etiket:<46s} n={d['n']:>6d} ${d['kar']:>+10.2f} ortR {d['ortR']:>+8.4f} "
          f"gun/islem {d['gunluk']:>5.2f} bDD %{d['bdd']:>6.2f} kötüay %{d['kotu']:>7.2f}{ek}")
    return d

print(f"\n{'='*118}\n=== NETTED KAPISI (tek pozisyon/coin) — canlı gerçeği ===")
ank = canli_kollar(SRC)
print("\n-- ankor tek başına: netted kapısı ankoru etkilemeli mi? (ayrık coinler → HAYIR beklenir)")
for ad, tk in (("ankor · netted KAPALI", False), ("ankor · netted AÇIK", True)):
    m = Kronos(ank, Ayar(**T, tek_pozisyon_per_coin=tk)); isl = m.kos()
    olc(isl, ad, m.sayac)

print("\n-- ankor + dört ek kol (limit dolum modeli = canlı niyet)")
ek = kollar_ek.limit_kollar(src=SRC) if hasattr(kollar_ek, "limit_kollar") else None
if ek is None:
    print("  ⚠ kollar_ek.limit_kollar yok — mevcut fabrikalar:",
          [x for x in dir(kollar_ek) if "kol" in x.lower()])
else:
    for ad, tk in (("ankor+4 · netted KAPALI", False), ("ankor+4 · netted AÇIK", True)):
        m = Kronos(ank + ek, Ayar(**T, tek_pozisyon_per_coin=tk)); isl = m.kos()
        d = olc(isl, ad, m.sayac)
        a_ = [t for t in isl if t.kol in ("donchian", "squeeze", "bb")]
        e_ = [t for t in isl if t.kol not in ("donchian", "squeeze", "bb")]
        olc(a_, f"   ↳ ankor kolları ({ad.split('·')[1].strip()})")
        olc(e_, f"   ↳ dört kol ({ad.split('·')[1].strip()})")
print(f"{'='*118}\n")
