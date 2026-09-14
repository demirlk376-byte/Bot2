"""
kronos_test_ek2.py — LİMİT-DOLUM varyantlarının motor sınavı (T0/T2/T3).

limit_varyant() sentetik bir KAPANIŞ sütunu kurar (yalnız dolum barlarında
close:=seviye) ve sinyali i+1'e taşır. İki yeni nedensellik riski doğar:
  · dolum kararı i+1 barının aralığına bakar → i+1'de biliniyor mu?
  · sentetik seri, göstergeleri/kararları geriye doğru kirletiyor mu?
T2 kesme testi ikisini de yakalar.

Kullanım: py kronos_test_ek2.py local
"""
import sys
import pandas as pd
from kronos import Kronos, Ayar
from kronos.kollar import canli_kollar
import deployed_backtest as A
import kollar_ek as EK

SRC = sys.argv[1] if len(sys.argv) > 1 else "local"
HATA = []
ANKOR = {"donchian", "squeeze", "bb"}


def imza(ts):
    return [(t.kol, t.coin, t.giris_ts.value, t.cikis_ts.value, round(t.R, 9)) for t in ts]


def _kollar(kadar=None):
    return canli_kollar(SRC, kadar) + EK.limit_kollar(None, None, SRC, kadar)


print(f"\n{'='*100}\n=== T0  ANKOR BOZULMADI (limit kolları) ===")
ay0 = dict(maxpos=10**9, ayni_bar_giris=False, riskf=A.RISKF, cap=A.CAP)
salt = set(imza(Kronos(canli_kollar(SRC), Ayar(**ay0)).kos()))
kar = imza(Kronos(_kollar(), Ayar(**ay0)).kos())
b_ = set(x for x in kar if x[0] in ANKOR)
fark = (salt - b_) | (b_ - salt)
print(f"  salt ankor {len(salt)} · karışıkta ankor {len(b_)} · FARK {len(fark)}")
print(f"  (limit kollarının kısıtsız ham işlemi: {sum(1 for x in kar if x[0] not in ANKOR)})")
if fark: HATA.append("T0")
print(f"  → {'✓ GEÇTİ' if not fark else '⛔ KALDI'}")

print(f"\n=== T2  NEDENSELLİK ===")
tam = Kronos(_kollar(), Ayar()).kos()
it = imza(tam)
print(f"  tam koşu {len(it)} işlem")
for T in ("2024-06-01", "2025-03-15", "2025-11-01"):
    Tts = pd.Timestamp(T, tz="UTC")
    kes = Kronos(_kollar(kadar=Tts), Ayar()).kos()
    a_ = set(x for x in it if x[3] < Tts.value)
    b2 = set(x for x in imza(kes) if x[3] < Tts.value)
    f = (a_ - b2) | (b2 - a_)
    print(f"  kesim {T}: tam {len(a_)} · kesik {len(b2)} · FARK {len(f)} "
          f"(limit kollarında {sum(1 for k in f if k[0].endswith('_L'))})")
    if f:
        HATA.append(f"T2 {T}")
        for k in sorted(f, key=lambda x: x[2])[:5]:
            print(f"     ⚠ {'yalnız TAM' if k in a_ else 'yalnız KESİK'}: {k[0]}/{k[1]} "
                  f"giriş={pd.Timestamp(k[2])} R={k[4]:+.4f}")
print(f"  → {'✓ GEÇTİ' if not any(h.startswith('T2') for h in HATA) else '⛔ KALDI — SIZINTI'}")

print(f"\n=== T3  BELİRLENİMCİLİK ===")
iki = Kronos(_kollar(), Ayar()).kos()
ayni = imza(tam) == imza(iki)
print(f"  iki koşu aynı mı: {ayni} ({len(tam)} vs {len(iki)})")
if not ayni: HATA.append("T3")
print(f"  → {'✓ GEÇTİ' if ayni else '⛔ KALDI'}")

print(f"\n{'='*100}")
if HATA:
    print(f"⛔ LİMİT KOLLARI GÜVENİLMEZ: {', '.join(HATA)}"); print(f"{'='*100}\n"); sys.exit(2)
print("✓ LİMİT KOLLARI DOĞRULANDI — ankoru bozmuyor, nedensel, belirlenimci.")
print(f"{'='*100}\n")
