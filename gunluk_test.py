"""
gunluk_test.py — YENİ KOL (GunlukKol) için kronos_test.py'nin aynısı.

T0 DENKLİK      : kısıt gevşetilmiş modda (maxpos=∞, ayni_bar_giris=False) motor,
                  daily_trend_test.gen_daily'nin ham çıktısını BİREBİR üretmeli.
                  Tutmazsa yeni kol eski ölçümle kıyaslanamaz.
T2 NEDENSELLİK  : veri 3 tarihte kesilir, kol yeniden kurulur (göstergeler kesik
                  seriden yeniden doğar). Kesimden ÖNCE kapanmış kararlar birebir
                  aynı olmalı. Bir tanesi bile oynarsa lookahead var.
T3 BELİRLENİMCİ : aynı girdi iki koşuda birebir aynı çıktı.

Kullanım:  py gunluk_test.py local
"""
import sys
import numpy as np, pandas as pd
import fast_bt
import deployed_backtest as DB
import daily_trend_test as D
from kronos import Kronos, Ayar
from kronos.kollar import canli_kollar
from gunluk_kol import GunlukKol, gunluk_kollar, gunluk_veri

SRC = sys.argv[1] if len(sys.argv) > 1 else "local"
COINS = DB.DONCH + DB.SQZ
CH, ESP, SL_A, RR, MH = 50, 200, 2.0, 3.0, 40      # ızgara ortası (ön-kayıtlı)
HATA = []


def imza(isl):
    return [(t.kol, t.coin, t.giris_ts.value, t.cikis_ts.value, round(t.R, 9)) for t in isl]


# ══════════════ T0 — gen_daily DENKLİĞİ ══════════════
print(f"\n{'='*100}\n=== T0  gen_daily DENKLİĞİ (yeni kol eski ölçümün aynısını mı üretiyor?) ===")
mot = Kronos(gunluk_kollar(COINS, SRC, ch=CH, esp=ESP, sl_a=SL_A, rr=RR, mh=MH),
             Ayar(maxpos=10**9, ayni_bar_giris=False, fee=DB.FEE,
                  kayma_bp=0.0, funding={})).kos()
esk = []
for c in COINS:
    esk += D.gen_daily(D.daily_cache(c, SRC), CH, ESP, SL_A, RR, MH, c)
E = {("gunluk", t[5], t[0], pd.Timestamp(t[1]).value): round(float(t[2]), 9) for t in esk}
M = {(t[0], t[1], t[2], t[3]): t[4] for t in imza(mot)}
fa, fm = set(E) - set(M), set(M) - set(E)
fr = [k for k in set(E) & set(M) if abs(E[k] - M[k]) > 1e-6]
print(f"  gen_daily {len(E)} · KRONOS {len(M)} · ortak {len(set(E)&set(M))}")
print(f"  yalnız gen_daily {len(fa)} · yalnız KRONOS {len(fm)} · R farklı {len(fr)}")
for k in list(fa)[:3]: print(f"     yalnız gen_daily: {k[1]} {pd.Timestamp(k[2])}")
for k in list(fm)[:3]: print(f"     yalnız KRONOS   : {k[1]} {pd.Timestamp(k[2])}")
if fa or fm or fr: HATA.append("T0 DENKLİK")
print(f"  → {'✓ GEÇTİ' if not (fa or fm or fr) else '⛔ KALDI'}")


# ══════════════ T2 — NEDENSELLİK (yeni kol DAHİL) ══════════════
print(f"\n=== T2  NEDENSELLİK — veri kesilince geçmiş kararlar değişiyor mu? (kitap + GÜNLÜK kol) ===")
CANLI = dict(maxpos=7, riskf=0.028, cap=1.50, bal0=1000.0, ayni_bar_giris=True,
             ardisik_zarar_limiti=2, cooldown_dk=240, gunluk_zarar_pct=0.35,
             tek_pozisyon_per_coin=True)

def kur(kadar=None):
    return canli_kollar(SRC, kadar) + gunluk_kollar(COINS, SRC, kadar, CH, ESP, SL_A, RR, MH)

tam = Kronos(kur(), Ayar(kayma_bp=15.85, **CANLI)).kos()
itam = imza(tam)
for T in ("2024-06-01", "2025-03-15", "2025-11-01"):
    Tts = pd.Timestamp(T, tz="UTC")
    kes = Kronos(kur(Tts), Ayar(kayma_bp=15.85, **CANLI)).kos()
    a_ = [x for x in itam if x[3] < Tts.value]
    b_ = [x for x in imza(kes) if x[3] < Tts.value]
    sa, sb = set(a_), set(b_)
    fark = (sa - sb) | (sb - sa)
    ng = sum(1 for x in a_ if x[0] == "gunluk")
    print(f"  kesim {T}: tam {len(a_)} karar (gunluk {ng}) · kesik {len(b_)} · FARK {len(fark)}")
    if fark:
        HATA.append(f"T2 NEDENSELLİK ({T})")
        for k in sorted(fark, key=lambda x: x[2])[:5]:
            print(f"     ⚠ {'yalnız TAM' if k in sa else 'yalnız KESİK'}: {k[0]}/{k[1]} "
                  f"giriş={pd.Timestamp(k[2])} R={k[4]:+.4f}")
print(f"  → {'✓ GEÇTİ — yeni kol geleceği görmüyor' if not any(h.startswith('T2') for h in HATA) else '⛔ KALDI — SIZINTI'}")


# ══════════════ T3 — BELİRLENİMCİLİK ══════════════
print(f"\n=== T3  BELİRLENİMCİLİK ===")
iki = Kronos(kur(), Ayar(kayma_bp=15.85, **CANLI)).kos()
ayni = itam == imza(iki)
print(f"  iki koşu birebir aynı mı: {ayni}  ({len(tam)} vs {len(iki)} işlem)")
if not ayni: HATA.append("T3")
print(f"  → {'✓ GEÇTİ' if ayni else '⛔ KALDI'}")

print(f"\n{'='*100}")
if HATA:
    print(f"⛔ YENİ KOL GÜVENİLMEZ — kalan: {', '.join(HATA)}"); print(f"{'='*100}\n"); sys.exit(2)
print(f"✓ GÜNLÜK KOL DOĞRULANDI — gen_daily'ye denk, nedensel, belirlenimci.")
print(f"{'='*100}\n")
