"""
aylik_beklenti.py — "aylık ne kadar kazanıyoruz / kazanacağız?"

İKİ AYRI SAYI VAR ve karıştırılırsa yanıltır:

 1) ANKORUN BEKLENTİSİ — 2023-2026 backtestinin aylık dağılımı. Bu bir TAVAN tahminidir:
    parametreler bu veriye bakılarak seçildi, dolayısıyla iyimser tarafa kaçar.
 2) CANLININ GERÇEKLEŞTİRDİĞİ — bugüne kadarki gerçek işlemler. n küçük ama bu sayı
    overfit EDİLEMEZ, çünkü hiçbir parametre ona bakılarak seçilmedi.

Ankor SABİT-ORAN modeli: her işlem hep aynı taban bakiyeye göre boyutlanır, bileşik
getiri YOKTUR. Gerçekte bot canlı bakiyeye göre boyutlandığı için hesap büyüdükçe
aynı yüzde daha çok dolar demektir. Bu yüzden "aylık $X" değil "aylık %X" doğru birimdir.

Kullanım:  py aylik_beklenti.py local [bakiye]
"""
import heapq
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A

CAP_YENI = 1.50


def pozisyonlar(source):
    tagged = []
    for c in A.DONCH:
        for t in A.gen("donchian", fast_bt.load(c, source=source)): tagged.append(t)
    for c in A.SQZ:
        for t in A.gen("squeeze", fast_bt.load(c, source=source)): tagged.append(t)
    for c in A.BB_COINS:
        for t in A.gen_bb(fast_bt.load(c, source=source)): tagged.append(t)
    ev = sorted(tagged, key=lambda t: t[0])
    openh = []; ctr = 0; out = []
    for entry_ns, exit_ts, R, slp in ev:
        while openh and openh[0][0].value <= entry_ns: heapq.heappop(openh)
        if len(openh) < A.MAXPOS:
            ctr += 1
            heapq.heappush(openh, (exit_ts, ctr, R))
            out.append((exit_ts, R, slp))
    return out


def aylik(poz, riskf, cap):
    r = np.array([p[1] for p in poz]); sp = np.array([p[2] for p in poz])
    eff = np.minimum(riskf, cap * sp)
    pnl_pct = r * eff * 100          # bakiyenin yüzdesi olarak
    ex = [pd.Timestamp(p[0]).tz_localize(None).to_period("M") for p in poz]
    return pd.Series(pnl_pct).groupby(ex).sum()


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    bal = float(sys.argv[2]) if len(sys.argv) > 2 else 203.0
    poz = pozisyonlar(source)
    print(f"\n{'=' * 92}")
    print("=== AYLIK BEKLENTİ ===")
    print(f"  DOĞRULAMA: {len(poz)} == 1579 → {'✓' if len(poz) == 1579 else '✗ SAPMA'}")
    if len(poz) != 1579:
        return

    for ad, riskf, cap in (("BUGÜNKÜ AYAR", A.RISKF, A.CAP),
                           ("PAKET SONRASI", A.RISKF, CAP_YENI)):
        m = aylik(poz, riskf, cap)
        print(f"\n  ── {ad} ──  ({len(m)} ay)")
        print(f"     ortalama ay   %{m.mean():+6.2f}   → ${m.mean()/100*bal:+7.2f}  (bakiye ${bal:.0f})")
        print(f"     MEDYAN ay     %{m.median():+6.2f}   → ${m.median()/100*bal:+7.2f}   ← tipik ay bu")
        print(f"     en iyi ay     %{m.max():+6.2f}   → ${m.max()/100*bal:+7.2f}")
        print(f"     en kötü ay    %{m.min():+6.2f}   → ${m.min()/100*bal:+7.2f}")
        print(f"     artı ay oranı %{(m > 0).mean()*100:.0f}  ·  "
              f"aylardan {(m < 0).sum()} tanesi ZARAR")
        q = m.quantile([0.10, 0.25, 0.75, 0.90])
        print(f"     ayların %80'i  %{q[0.10]:+.2f} ile %{q[0.90]:+.2f} arasında "
              f"(${q[0.10]/100*bal:+.0f} … ${q[0.90]/100*bal:+.0f})")

    m = aylik(poz, A.RISKF, CAP_YENI)
    print(f"\n{'=' * 92}\n=== BUNU NASIL OKUMALI ===")
    print(f"  · ORTALAMA yanıltıcıdır: birkaç büyük ay onu yukarı çeker. Tipik ayı MEDYAN anlatır")
    print(f"    (%{m.median():+.2f} → ${m.median()/100*bal:+.0f}), ortalama değil (%{m.mean():+.2f}).")
    print(f"  · Bu ankorun beklentisidir ve İYİMSERDİR: parametreler bu veriye bakılarak seçildi.")
    print(f"    Canlı gerçekleşen R, ankorun beklediğinin ALTINDA seyrediyor → gerçek aylık")
    print(f"    sayı bu tablonun altında olmalı. live_verify.py güncel farkı ölçer.")
    print(f"  · {(m < 0).sum()}/{len(m)} ay ZARARLA kapanıyor. Zararlı ay arıza değil, plan dâhilidir.")
    print(f"  · Sabit-oran modeli: bileşik getiri YOK. Gerçekte bakiye büyüdükçe aynı yüzde")
    print(f"    daha çok dolar eder — kâr, riski artırarak DEĞİL, bakiye büyüyerek artar.")


if __name__ == "__main__":
    main()
