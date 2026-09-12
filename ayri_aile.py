"""
ayri_aile.py — AYRI HAVUZ bulgusu TEK HÜCRE mi, AİLE mi?

ayri_havuz.py ızgara-ortası hücresinde (ch50/sl2/rr3/mh40/ema200) S=2 ayrı
koltukla +$100.01 (TEST +$37.74) verdi. Tek hücre KANIT DEĞİL. Ledger'ın kendi
kuralı: "270 kombinasyon taranıyor → argmax neredeyse kesin gürültü içerir.
Bu yüzden karar argmax'a DEĞİL, tüm ailenin TEST medyanına bakılarak veriliyor."

Bu dosya tam onu yapar: 270 kombinasyonun HEPSİ ayrı havuzda (S taraması),
risk bileşik-maxDD ile eşitlenmiş, kâr sabit-kesir uzayında.

HÜKÜM KURALI (ön-kayıtlı, koşmadan önce):
  GEÇER  ancak ve ancak (a) ailenin TEST medyanı > 0 VE (b) TEST'te pozitif
  hücre oranı > %50 VE (c) tüm-dönem medyanı > 0. Yani etki AİLE GENELİNDE
  olmalı; birkaç parlak hücre reddedilir.
"""
import sys, heapq, numpy as np, pandas as pd, itertools
import fast_bt, deployed_backtest as DB, daily_trend_test as D
from ayri_havuz import koltuk, kar_sabit, dd_bilesik, olcek_bul, SPLIT


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "local"
    kitap = D.base_trades(src)
    A = koltuk(kitap, 7)
    if len(A) != 1579: sys.exit(f"⛔ taban {len(A)} — kıyas geçersiz.")
    dd_A = dd_bilesik(A); kar_A, ay_A = kar_sabit(A)
    kar_A_te, _ = kar_sabit([t for t in A if t[0] >= SPLIT.value])
    print(f"\n{'='*100}\n=== AYRI HAVUZ: AİLE TESTİ (270 kombinasyon) ===")
    print(f"  taban A: ${kar_A:+.2f} (TEST ${kar_A_te:+.2f}) · bileşik maxDD %{dd_A:.2f} · "
          f"en kötü ay %{ay_A.min():.2f}")

    dc = {c: D.daily_cache(c, src) for c in DB.DONCH + DB.SQZ}
    for S in (1, 2, 3):
        d_all, d_te, kotu = [], [], []
        for ch, esp, sl_a, rr, mh in itertools.product(
                D.CH_GRID, D.EMA_GRID, D.SL_GRID, D.RR_GRID, D.MH_GRID):
            kol = []
            for c in dc: kol += D.gen_daily(dc[c], ch, esp, sl_a, rr, mh, c)
            if not kol: continue
            C = A + koltuk(kol, S)
            o = olcek_bul(C, dd_A)
            k, ay = kar_sabit(C, o)
            kte, _ = kar_sabit([t for t in C if t[0] >= SPLIT.value], o)
            d_all.append(k - kar_A); d_te.append(kte - kar_A_te); kotu.append(ay.min())
        a, t, km = np.array(d_all), np.array(d_te), np.array(kotu)
        gec = np.median(t) > 0 and (t > 0).mean() > 0.5 and np.median(a) > 0
        print(f"\n  S={S} koltuk · {len(a)} kombinasyon")
        print(f"    TÜM DÖNEM  medyan Δ$ {np.median(a):+8.2f} · pozitif %{(a>0).mean()*100:5.1f} · "
              f"aralık [{a.min():+.0f}, {a.max():+.0f}]")
        print(f"    TEST       medyan Δ$ {np.median(t):+8.2f} · pozitif %{(t>0).mean()*100:5.1f} · "
              f"aralık [{t.min():+.0f}, {t.max():+.0f}]")
        print(f"    en kötü ay medyan %{np.median(km):+.2f} (taban %{ay_A.min():.2f}) · "
              f"kötüleşen %{(km<ay_A.min()).mean()*100:.0f}")
        print(f"    → {'✓ AİLE GEÇTİ' if gec else '✗ aile geçmedi'}")
    print(f"{'='*100}\n")


if __name__ == "__main__":
    main()
