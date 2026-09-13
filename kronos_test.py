"""
kronos_test.py — KRONOS motorunun kendisini sınar. Strateji değil, MOTOR.

Üç test. Üçü de geçmeden motorun hiçbir çıktısına güvenilmez.

T1 ANKOR DENKLİĞİ
   Kısıt gevşetilmiş modda (maxpos=∞, ayni_bar_giris=False) motor,
   deployed_backtest.gen()/gen_bb() ham çıktısını BİREBİR üretmeli.
   Tutmazsa motorun mekaniği ankordan farklıdır → tüm kıyaslar geçersiz.

T2 NEDENSELLİK (asıl test)
   Veri rastgele bir T anında KESİLİR ve motor yeniden koşulur. T'den önce
   ALINAN KARARLAR birebir aynı olmalı. Bir tanesi bile değişirse motor
   geleceği görüyor demektir. Göstergeler Besleme'nin serisinden hesaplandığı
   için bu test sinyal mantığını DA gösterge nedenselliğini DE sınar.
   (Merkezli rolling, ileri-bakan resample, ffill-with-future burada yakalanır.)

T3 BELİRLENİMCİLİK
   Aynı girdi iki kez koşulunca birebir aynı çıktı. Sözlük sırası, kararsız
   sıralama, rastgele tohum kaynaklı oynama olmamalı.

Kullanım:  py kronos_test.py local
"""
import sys
import numpy as np, pandas as pd
import fast_bt, deployed_backtest as A
from kronos import Kronos, Ayar
from kronos.kollar import canli_kollar

SRC = sys.argv[1] if len(sys.argv) > 1 else "local"
HATA = []


def imza(islemler):
    """Karar imzası: hangi kol/coin, ne zaman girdi, ne zaman çıktı, hangi R."""
    return [(t.kol, t.coin, t.giris_ts.value, t.cikis_ts.value, round(t.R, 9))
            for t in islemler]


# ══════════════════ T1 — ANKOR DENKLİĞİ ══════════════════
print(f"\n{'='*100}\n=== T1  ANKOR DENKLİĞİ ===")
kollar = canli_kollar(SRC)
mot = Kronos(kollar, Ayar(maxpos=10**9, ayni_bar_giris=False, riskf=A.RISKF, cap=A.CAP)).kos()

ank = []
for c in A.DONCH: ank += [("donchian", c) + t for t in A.gen("donchian", fast_bt.load(c, source=SRC))]
for c in A.SQZ:   ank += [("squeeze",  c) + t for t in A.gen("squeeze",  fast_bt.load(c, source=SRC))]
for c in A.BB_COINS: ank += [("bb", c) + t for t in A.gen_bb(fast_bt.load(c, source=SRC))]
Aset = {(k, c, g, pd.Timestamp(x).value): round(float(r), 9) for k, c, g, x, r, _s in ank}
Mset = {(t[0], t[1], t[2], t[3]): t[4] for t in imza(mot)}

fa, fm = set(Aset) - set(Mset), set(Mset) - set(Aset)
fr = [k for k in set(Aset) & set(Mset) if abs(Aset[k] - Mset[k]) > 1e-6]
print(f"  ankor {len(Aset)} · kronos {len(Mset)} · ortak {len(set(Aset)&set(Mset))}")
print(f"  yalnız ankorda {len(fa)} · yalnız kronosta {len(fm)} · R farklı {len(fr)}")
if fa or fm or fr:
    HATA.append("T1 ANKOR DENKLİĞİ")
    for k in list(fa)[:3]: print(f"     yalnız ankor: {k[0]}/{k[1]} {pd.Timestamp(k[2])}")
    for k in list(fm)[:3]: print(f"     yalnız kronos: {k[0]}/{k[1]} {pd.Timestamp(k[2])}")
print(f"  → {'✓ GEÇTİ' if not (fa or fm or fr) else '⛔ KALDI'}")


# ══════════════════ T2 — NEDENSELLİK (kesme testi) ══════════════════
print(f"\n=== T2  NEDENSELLİK — veri kesilince geçmiş kararlar değişiyor mu? ===")
tam = Kronos(canli_kollar(SRC), Ayar()).kos()
imza_tam = imza(tam)

for T in ("2024-06-01", "2025-03-15", "2025-11-01"):
    Tts = pd.Timestamp(T, tz="UTC")
    kes = Kronos(canli_kollar(SRC, kadar=Tts), Ayar()).kos()
    # kıyas kümesi: T'den ÖNCE KAPANMIŞ işlemler (kesik koşuda yarım kalanlar hariç)
    a_ = [x for x in imza_tam if x[3] < Tts.value]
    b_ = [x for x in imza(kes) if x[3] < Tts.value]
    sa, sb = set(a_), set(b_)
    fark = (sa - sb) | (sb - sa)
    print(f"  kesim {T}: tam koşu {len(a_)} karar · kesik koşu {len(b_)} karar · FARK {len(fark)}")
    if fark:
        HATA.append(f"T2 NEDENSELLİK ({T})")
        for k in sorted(fark, key=lambda x: x[2])[:4]:
            nerede = "yalnız TAM" if k in sa else "yalnız KESİK"
            print(f"     ⚠ {nerede}: {k[0]}/{k[1]} giriş={pd.Timestamp(k[2])} R={k[4]:+.4f}")
print(f"  → {'✓ GEÇTİ — motor geleceği görmüyor' if not any(h.startswith('T2') for h in HATA) else '⛔ KALDI — GELECEK BİLGİSİ SIZIYOR'}")


# ══════════════════ T3 — BELİRLENİMCİLİK ══════════════════
print(f"\n=== T3  BELİRLENİMCİLİK ===")
iki = Kronos(canli_kollar(SRC), Ayar()).kos()
ayni = imza(tam) == imza(iki)
print(f"  iki koşu birebir aynı mı: {ayni}  ({len(tam)} vs {len(iki)} işlem)")
if not ayni: HATA.append("T3 BELİRLENİMCİLİK")
print(f"  → {'✓ GEÇTİ' if ayni else '⛔ KALDI'}")


print(f"\n{'='*100}")
if HATA:
    print(f"⛔ MOTOR GÜVENİLMEZ — kalan testler: {', '.join(HATA)}")
    print(f"{'='*100}\n"); sys.exit(2)
print(f"✓ KRONOS DOĞRULANDI — ankora denk, nedensel, belirlenimci.")
print(f"{'='*100}\n")
