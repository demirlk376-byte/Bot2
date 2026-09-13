"""
mum_dogrula.py — mum_mum.py motorunu ANKORA karşı doğrular.

DENKLİK TESTİ: koltuk sınırı KALDIRILINCA (maxpos=999) koltuk rekabeti kalmaz;
tek kısıt "coin başına tek açık pozisyon" olur — bu da ankorun `occ` mantığının
TAM KARŞILIĞIDIR. Dolayısıyla motorun çıktısı A.gen()/A.gen_bb() çıktısıyla
BİREBİR aynı olmalı. Değilse hata MOTORDA, ankorda değil.

Tutarsa: 1579 ile mum-mum farkının tamamı KOLTUK MANTIĞINDAN gelir ve ölçüm geçerli.
"""
import sys
import numpy as np, pandas as pd
import fast_bt, deployed_backtest as A, mum_mum as M

src = sys.argv[1] if len(sys.argv) > 1 else "local"
seri = M.yukle(src)

# ── ankor tarafı: gen() ham çıktısı (seat_select ÖNCESİ), kol+coin etiketli
ank = []
for c in A.DONCH: ank += [(t[0], t[1], t[2], t[3], "donchian", c) for t in A.gen("donchian", fast_bt.load(c, source=src))]
for c in A.SQZ:   ank += [(t[0], t[1], t[2], t[3], "squeeze",  c) for t in A.gen("squeeze",  fast_bt.load(c, source=src))]
for c in A.BB_COINS: ank += [(t[0], t[1], t[2], t[3], "bb", c) for t in A.gen_bb(fast_bt.load(c, source=src))]

mot = M.kos(seri, maxpos=999, ayni_bar_giris=False)

def anahtarla(lst):
    return {(t[4], t[5], t[0], pd.Timestamp(t[1]).value): round(float(t[2]), 9) for t in lst}

A_, M_ = anahtarla(ank), anahtarla(mot)
print(f"\n{'='*100}\n=== DENKLİK TESTİ: motor(maxpos=999) vs ankor gen() ham ===")
print(f"  ankor ham işlem : {len(ank)}")
print(f"  motor ham işlem : {len(mot)}")
sadece_a = set(A_) - set(M_); sadece_m = set(M_) - set(A_); ortak = set(A_) & set(M_)
print(f"  ortak (giriş+çıkış+kol+coin aynı): {len(ortak)}")
print(f"  yalnız ankorda: {len(sadece_a)} · yalnız motorda: {len(sadece_m)}")
farkli_R = [k for k in ortak if abs(A_[k] - M_[k]) > 1e-6]
print(f"  ortaklardan R'si FARKLI olan: {len(farkli_R)}")
if farkli_R[:3]:
    for k in farkli_R[:3]: print(f"     {k[0]}/{k[1]} giriş={pd.Timestamp(k[2])} ankorR={A_[k]:+.6f} motorR={M_[k]:+.6f}")
for ad, s in (("yalnız ANKORDA", sadece_a), ("yalnız MOTORDA", sadece_m)):
    if s:
        print(f"  ── {ad} ilk 5:")
        for k in sorted(s, key=lambda x: x[2])[:5]:
            print(f"     {k[0]:<9s} {k[1]:<5s} giriş={pd.Timestamp(k[2])} çıkış={pd.Timestamp(k[3])}")
tam = (len(sadece_a) == 0 and len(sadece_m) == 0 and len(farkli_R) == 0)
print(f"\n  → {'✓ BİREBİR DENK — motor doğrulandı, fark yalnız koltuk mantığından' if tam else '⛔ DENK DEĞİL — motorda hata var, mum-mum sonucu HENÜZ GEÇERSİZ'}")
print(f"{'='*100}\n")
