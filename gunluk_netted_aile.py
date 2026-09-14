"""
gunluk_netted_aile.py — NETTED çerçevede AİLE ALT-KÜMESİ.

gunluk_netted.py ön-kayıtlı ızgara-ortası hücresinde kolun marjinal katkısını
−171 puan ölçtü. Soru: bu TEK HÜCRE mi, yoksa ailenin tamamı mı? Tam 270
kombinasyon netted çerçevede koşulamaz (her hücre TAM motor koşusu ≈3 dk →
~13 saat). Bu yüzden ızgarayı SİSTEMATİK tarayan 9 hücrelik alt-küme:
ch ∈ {20,50,100} × mh ∈ {20,40,60} (ema200/sl2.0/rr3.0 sabit) — argmax yok,
ızgaranın iki ucu ve ortası.

S=1 (8 koltuk), tek_pozisyon_per_coin=True, kayma+funding. Ölçekleme YOK
(çıplak yüzde), kontrol = aynı 8 koltukta KOL YOK.

Kullanım: py gunluk_netted_aile.py local
"""
import sys, itertools
import numpy as np, pandas as pd
import deployed_backtest as DB
from kronos import Kronos, Ayar
from kronos.kollar import canli_kollar, funding_yukle
from gunluk_kol import gunluk_kollar, gunluk_veri

SRC = sys.argv[1] if len(sys.argv) > 1 else "local"
BAL0 = 1000.0
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")
COINS = DB.DONCH + DB.SQZ
fund = funding_yukle(DB.DONCH + DB.SQZ + DB.BB_COINS)
G = dict(riskf=0.028, cap=1.50, bal0=BAL0, ayni_bar_giris=True, ardisik_zarar_limiti=2,
         cooldown_dk=240, gunluk_zarar_pct=0.35, tek_pozisyon_per_coin=True,
         kayma_bp=15.85, funding=fund)
kk = canli_kollar(SRC)
ob = {c: gunluk_veri(c, SRC) for c in COINS}


def olc(isl):
    t = sorted(isl, key=lambda x: (x.cikis_ts.value, x.giris_ts.value, x.kol, x.coin))
    R = np.array([x.R for x in t]); e = np.array([x.eff for x in t])
    g = np.array([x.giris_ts.value for x in t]); p = R * e * BAL0
    b = np.concatenate([[1.0], np.cumprod(1 + R * e)]); pk = np.maximum.accumulate(b)
    return (float(p.sum()) / BAL0 * 100, float(p[g >= SPLIT.value].sum()) / BAL0 * 100,
            float(((pk - b) / pk).max() * 100), sum(1 for x in t if x.kol == "gunluk"),
            len(t) - sum(1 for x in t if x.kol == "gunluk"))


A = olc(Kronos(kk, Ayar(maxpos=7, **G)).kos())
B = olc(Kronos(kk, Ayar(maxpos=8, **G)).kos())
print(f"\n{'='*110}\n=== NETTED ÇERÇEVEDE AİLE ALT-KÜMESİ (S=1 → 8 koltuk, ölçekleme yok) ===")
print(f"  A  kitap 7 koltuk : top %{A[0]:+.2f} TEST %{A[1]:+.2f} DD %{A[2]:.2f} kitap {A[4]}")
print(f"  B  kitap 8 koltuk : top %{B[0]:+.2f} TEST %{B[1]:+.2f} DD %{B[2]:.2f} kitap {B[4]}  ← KONTROL")
print(f"\n  {'ch':>4}{'mh':>4}{'kol n':>7}{'kitap n':>9}{'top%':>9}{'Δ(C−B)':>9}{'TEST%':>9}"
      f"{'ΔTEST':>8}{'DD%':>7}")
d1, d2 = [], []
for ch, mh in itertools.product((20, 50, 100), (20, 40, 60)):
    kol = gunluk_kollar(COINS, SRC, None, ch, 200, 2.0, 3.0, mh, ob)
    C = olc(Kronos(kk + kol, Ayar(maxpos=8, **G)).kos())
    d1.append(C[0] - B[0]); d2.append(C[1] - B[1])
    print(f"  {ch:>4}{mh:>4}{C[3]:>7}{C[4]:>9}{C[0]:>9.2f}{C[0]-B[0]:>+9.2f}{C[1]:>9.2f}"
          f"{C[1]-B[1]:>+8.2f}{C[2]:>7.2f}", flush=True)
d1, d2 = np.array(d1), np.array(d2)
print(f"\n  9 hücre · Δ(C−B) medyan {np.median(d1):+.2f} · pozitif %{(d1>0).mean()*100:.0f} · "
      f"aralık [{d1.min():+.1f}, {d1.max():+.1f}]")
print(f"           ΔTEST      medyan {np.median(d2):+.2f} · pozitif %{(d2>0).mean()*100:.0f} · "
      f"aralık [{d2.min():+.1f}, {d2.max():+.1f}]")
print(f"{'='*110}\n")
