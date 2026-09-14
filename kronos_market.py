"""
kronos_market.py — MARKET GİRİŞ kararı sonrası YENİ TABAN + funding kalibrasyonu.

DEĞİŞEN: DONCHIAN_MAKER_ENTRY=false → donchian artık sinyal barı kapanışında
ANINDA MARKET giriyor. Sonuçları:
  · 15.85bp kayma artık GERÇEKTEN ödeniyor → "kaymalı" sütun DOĞRU olan
  · ücret her iki tarafta taker %0.01 = 1bp → KRONOS'un fee=0.0001 varsayımı DOĞRU
  · maker doluş oranı diye bir bilinmeyen KALMADI

EKLENEN: funding maliyeti. Canlıda 8 saatte bir ödeniyor, ankorda HİÇ YOKTU.
R bedeli = Σrate/sl_pct (kaymayla aynı yapı, çünkü notional = eff*BAL0/sl_pct).
"""
import sys
import numpy as np, pandas as pd
import deployed_backtest as A
from kronos import Kronos, Ayar
from kronos.kollar import canli_kollar, funding_yukle

SRC = sys.argv[1] if len(sys.argv) > 1 else "local"
kollar = canli_kollar(SRC)
COINLER = A.DONCH + A.SQZ + A.BB_COINS
CANLI = dict(maxpos=7, riskf=0.028, cap=1.50, bal0=1000.0, ayni_bar_giris=True,
             ardisik_zarar_limiti=2, cooldown_dk=240, gunluk_zarar_pct=0.35,
             tek_pozisyon_per_coin=True)
fund = funding_yukle(COINLER)

def rap(isl, ad):
    R=np.array([t.R for t in isl]); eff=np.array([t.eff for t in isl]); pnl=np.array([t.pnl for t in isl])
    ex=pd.to_datetime([t.cikis_ts for t in isl]); yil=(ex.max()-ex.min()).days/365.25
    ay=pd.Series(pnl,index=ex.tz_localize(None).to_period("M")).groupby(level=0).sum()/1000*100
    bil=np.cumprod(1+R*eff); bb=np.concatenate([[1.0],bil])
    d=dict(n=len(isl),ortR=R.mean(),top=pnl.sum()/1000*100,aylik=ay.mean(),
           bdd=float(((np.maximum.accumulate(bb)-bb)/np.maximum.accumulate(bb)).max()*100),
           kotu=ay.min(),poz=(ay>0).mean()*100)
    print(f"  {ad:<44s} n={d['n']:>5d} ortR {d['ortR']:>+.4f} toplam %{d['top']:>+8.2f} "
          f"aylık %{d['aylik']:>+6.2f} bileşikDD %{d['bdd']:>6.2f} kötüay %{d['kotu']:>7.2f} pozAy %{d['poz']:.0f}")
    return d

print(f"\n{'='*118}\n=== MARKET GİRİŞ · YENİ TABAN ($1000, yüzde) ===")
a = rap(Kronos(kollar, Ayar(kayma_bp=0.0,   **CANLI)).kos(), "1) kaymasız, fundingsiz (eski iyimser)")
b = rap(Kronos(kollar, Ayar(kayma_bp=15.85, **CANLI)).kos(), "2) + 15.85bp kayma (MARKET gerçeği)")
c = rap(Kronos(kollar, Ayar(kayma_bp=15.85, funding=fund, **CANLI)).kos(), "3) + FUNDING = TAM GERÇEKÇİ TABAN")
print(f"\n  kayma bedeli   : ortR {b['ortR']-a['ortR']:+.4f}  ({(b['ortR']-a['ortR'])/a['ortR']*100:+.1f}%) · aylık {b['aylik']-a['aylik']:+.2f} puan")
print(f"  funding bedeli : ortR {c['ortR']-b['ortR']:+.4f}  ({(c['ortR']-b['ortR'])/b['ortR']*100:+.1f}%) · aylık {c['aylik']-b['aylik']:+.2f} puan")
print(f"  TOPLAM sürtünme: ortR {c['ortR']-a['ortR']:+.4f}  ({(c['ortR']-a['ortR'])/a['ortR']*100:+.1f}%)")
print(f"\n  → YENİ ÖN-KAYITLI TABAN: ort R {c['ortR']:+.4f} · aylık %{c['aylik']:+.2f} · "
      f"bileşik maxDD %{c['bdd']:.2f} · en kötü ay %{c['kotu']:.2f}")
print(f"{'='*118}\n")
