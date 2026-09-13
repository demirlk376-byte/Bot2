"""
mum_ayristir.py — ankor ile canlı-doğru mum-mum arasındaki farkı BİLEŞENLERİNE ayırır.

Motor mum_dogrula.py ile ANKORA BİREBİR DENK doğrulandı (1603 ham işlem, 0 fark).
Dolayısıyla aşağıdaki farkların tamamı KOLTUK MANTIĞINDANDIR, kodlama hatasından değil.

İKİ AYRI SAPMA:
 (A) HAYALET BLOKAJ — ankor: gen() koltuktan habersiz üretir, `occ` HER sinyalde
     ilerler; koltuk yokluğundan elenen sinyal bile coini bloke eder. Canlı: koltuk
     yoksa sinyal düşer, coin SERBEST kalır.
 (B) AYNI BAR GİRİŞİ — ankor: `i <= occ` → çıkış barında giriş yasak. Canlı: bot bar
     kapanışında tarar, pozisyon o an zaten kapanmıştır → giriş serbest.
"""
import sys
import numpy as np, pandas as pd
import deployed_backtest as A, mum_mum as M

src = sys.argv[1] if len(sys.argv) > 1 else "local"
seri = M.yukle(src)
KY = 15.85 / 1e4

def rapor(ad, tk):
    m = M.olc(tk, A.CANLI_RISKF, A.CANLI_CAP, KY)
    print(f"  {ad:<44s} n={m['n']:>5d} ${m['kar']:>+9.2f} ortR {m['ortR']:>+.4f} "
          f"WR %{m['wr']:.1f} bileşikDD %{m['bdd']:.2f} kötüay %{m['kotu']:.2f}")
    return m

print(f"\n{'='*104}\n=== ANKOR → CANLI-DOĞRU: FARKIN AYRIŞTIRILMASI (hepsi canlı ölçek + 15.85bp kayma) ===")

# 0) ANKOR: ham 1603 → seat_select(7)
ham = M.kos(seri, maxpos=999, ayni_bar_giris=False)
ss = A.seat_select([(t[0], pd.Timestamp(t[1]), t[2], t[3]) for t in ham])
ank = [(0, x[0], x[1], x[2], "", "") for x in ss]
m0 = rapor("0) ANKOR (üret-sonra-filtrele)", ank)

# 1) yalnız (A) düzeltilmiş: koltuk O AN sorulur, elenen sinyal coini BLOKLAMAZ
m1 = rapor("1) +hayalet blokaj DÜZELTİLDİ", M.kos(seri, maxpos=7, ayni_bar_giris=False))

# 2) (A)+(B): tam canlı-doğru
tk2 = M.kos(seri, maxpos=7, ayni_bar_giris=True)
m2 = rapor("2) +aynı bar girişi DE açık = TAM CANLI-DOĞRU", tk2)

print(f"\n  {'ETKİ':<44s} {'Δn':>6s} {'Δ$':>10s} {'ΔortR':>9s} {'ΔbileşikDD':>11s} {'Δkötüay':>9s}")
print(f"  {'(A) hayalet blokaj':<44s} {m1['n']-m0['n']:>+6d} {m1['kar']-m0['kar']:>+10.2f} "
      f"{m1['ortR']-m0['ortR']:>+9.4f} {m1['bdd']-m0['bdd']:>+11.2f} {m1['kotu']-m0['kotu']:>+9.2f}")
print(f"  {'(B) aynı bar girişi':<44s} {m2['n']-m1['n']:>+6d} {m2['kar']-m1['kar']:>+10.2f} "
      f"{m2['ortR']-m1['ortR']:>+9.4f} {m2['bdd']-m1['bdd']:>+11.2f} {m2['kotu']-m1['kotu']:>+9.2f}")
print(f"  {'TOPLAM (ankor → canlı-doğru)':<44s} {m2['n']-m0['n']:>+6d} {m2['kar']-m0['kar']:>+10.2f} "
      f"{m2['ortR']-m0['ortR']:>+9.4f} {m2['bdd']-m0['bdd']:>+11.2f} {m2['kotu']-m0['kotu']:>+9.2f}")

# koltuk doluluğu: canlı-doğru modda kaç sinyal koltuk yokluğundan düştü
print(f"\n  ankor kâr ${m0['kar']:+.2f} → canlı-doğru ${m2['kar']:+.2f} = "
      f"%{(m2['kar']-m0['kar'])/abs(m0['kar'])*100:+.1f}")
print(f"  ankor ort R {m0['ortR']:+.4f} → canlı-doğru {m2['ortR']:+.4f} = "
      f"%{(m2['ortR']-m0['ortR'])/m0['ortR']*100:+.1f}")
print(f"{'='*104}\n")
