"""
kronos_test_ek.py — YENİ DÖRT KOL (orb/asia_bo/fvg/sr_breakout) motor sınavı.

kronos_test.py'nin T2/T3'ünün AYNISI, ama kollar = ankor + dört yeni kol.
T1 (ankor denkliği) yeni kollar için tanımsızdır — onun yerine T0 konur:
  T0  ANKOR BOZULMADI: yeni kollar eklenince, KISITSIZ modda (maxpos=∞) ankor
      kollarının kararları BİREBİR aynı kalmalı. Değişirse yeni kol ankoru
      kirletiyordur (paylaşılan durum / sıralama sızıntısı).
  T2  NEDENSELLİK: veri T'de kesilir, motor sıfırdan koşulur, T'den önce
      KAPANMIŞ kararların HEPSİ birebir aynı olmalı. Yeni kol lookahead
      içeriyorsa (ön-hesap sırası, merkezli pencere, ileri resample) burada
      yakalanır.
  T3  BELİRLENİMCİLİK: iki koşu birebir aynı.

Kullanım:  py kronos_test_ek.py local
"""
import sys
import pandas as pd

from kronos import Kronos, Ayar
from kronos.kollar import canli_kollar
import deployed_backtest as A
import kollar_ek as EK

SRC = sys.argv[1] if len(sys.argv) > 1 else "local"
HATA = []
ANKOR_ADLAR = {"donchian", "squeeze", "bb"}


def imza(islemler):
    return [(t.kol, t.coin, t.giris_ts.value, t.cikis_ts.value, round(t.R, 9))
            for t in islemler]


def _kollar(kadar=None):
    return canli_kollar(SRC, kadar) + EK.ek_kollar(None, None, SRC, kadar)


# ══════════════════ T0 — ANKOR BOZULMADI ══════════════════
print(f"\n{'='*100}\n=== T0  ANKOR BOZULMADI (yeni kollar ankorun kararlarını değiştiriyor mu?) ===")
ay0 = dict(maxpos=10**9, ayni_bar_giris=False, riskf=A.RISKF, cap=A.CAP)
salt = Kronos(canli_kollar(SRC), Ayar(**ay0)).kos()
karisik = Kronos(_kollar(), Ayar(**ay0)).kos()
a_ = set(imza(salt))
b_ = set(x for x in imza(karisik) if x[0] in ANKOR_ADLAR)
fark = (a_ - b_) | (b_ - a_)
print(f"  salt ankor {len(a_)} karar · karışık koşudaki ankor kararları {len(b_)} · FARK {len(fark)}")
if fark:
    HATA.append("T0 ANKOR BOZULDU")
    for k in sorted(fark, key=lambda x: x[2])[:4]:
        print(f"     ⚠ {k[0]}/{k[1]} {pd.Timestamp(k[2])} R={k[4]:+.4f}")
ek_n = sum(1 for x in imza(karisik) if x[0] not in ANKOR_ADLAR)
print(f"  (kısıtsız modda yeni kolların ham işlem sayısı: {ek_n})")
print(f"  → {'✓ GEÇTİ' if not fark else '⛔ KALDI'}")


# ══════════════════ T2 — NEDENSELLİK ══════════════════
print(f"\n=== T2  NEDENSELLİK — veri kesilince geçmiş kararlar değişiyor mu? ===")
tam = Kronos(_kollar(), Ayar()).kos()
imza_tam = imza(tam)
print(f"  tam koşu: {len(imza_tam)} işlem")

for T in ("2024-06-01", "2025-03-15", "2025-11-01"):
    Tts = pd.Timestamp(T, tz="UTC")
    kes = Kronos(_kollar(kadar=Tts), Ayar()).kos()
    a_ = [x for x in imza_tam if x[3] < Tts.value]
    b_ = [x for x in imza(kes) if x[3] < Tts.value]
    sa, sb = set(a_), set(b_)
    fark = (sa - sb) | (sb - sa)
    ek_fark = [k for k in fark if k[0] not in ANKOR_ADLAR]
    print(f"  kesim {T}: tam {len(a_)} · kesik {len(b_)} · FARK {len(fark)} "
          f"(yeni kollarda {len(ek_fark)})")
    if fark:
        HATA.append(f"T2 NEDENSELLİK ({T})")
        for k in sorted(fark, key=lambda x: x[2])[:5]:
            nerede = "yalnız TAM" if k in sa else "yalnız KESİK"
            print(f"     ⚠ {nerede}: {k[0]}/{k[1]} giriş={pd.Timestamp(k[2])} R={k[4]:+.4f}")
print(f"  → {'✓ GEÇTİ — motor+yeni kollar geleceği görmüyor' if not any(h.startswith('T2') for h in HATA) else '⛔ KALDI — GELECEK BİLGİSİ SIZIYOR'}")


# ══════════════════ T3 — BELİRLENİMCİLİK ══════════════════
print(f"\n=== T3  BELİRLENİMCİLİK ===")
iki = Kronos(_kollar(), Ayar()).kos()
ayni = imza(tam) == imza(iki)
print(f"  iki koşu birebir aynı mı: {ayni}  ({len(tam)} vs {len(iki)} işlem)")
if not ayni:
    HATA.append("T3 BELİRLENİMCİLİK")
print(f"  → {'✓ GEÇTİ' if ayni else '⛔ KALDI'}")

print(f"\n{'='*100}")
if HATA:
    print(f"⛔ YENİ KOLLAR GÜVENİLMEZ — kalan testler: {', '.join(HATA)}")
    print(f"{'='*100}\n"); sys.exit(2)
print("✓ YENİ DÖRT KOL DOĞRULANDI — ankoru bozmuyor, nedensel, belirlenimci.")
print(f"{'='*100}\n")
