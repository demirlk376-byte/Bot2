"""
koltuk_kapasite.py — "boşta kalan parayı, HER ŞEYİ SABİT tutarak kullanabilir miyiz?"

KULLANICININ İSTEDİĞİ TAM OLARAK ŞU: TP/SL oranı sabit, kaldıraç sabit, işlem başına
risk sabit — sadece boşta duran para çalışsın.

ÖNCE NEDEN "MARJİNİ ARTIR" DİYE BİR KOL YOK:
    marjin = nominal / kaldıraç
Kaldıraç sabitse daha çok marjin ancak daha büyük NOMİNAL ile olur; stop mesafesi de
sabitse daha büyük nominal = işlem başına daha çok DOLAR RİSKİ. Yani marjin bağımsız
bir ayar değil, SONUÇTUR. "Her şey sabit ama marjin artsın" mümkün değildir.

AMA KULLANICININ TARİFİNE UYAN GERÇEK BİR KOL VAR: **MAX_POSITIONS**.
Aynı anda daha çok pozisyon tutmak her işlemi BİREBİR aynı bırakır (aynı TP/SL, aynı
kaldıraç, aynı risk) ve yalnız eşzamanlılığı artırır. Boşta para böyle kullanılır.

BU BETİK ONU ÖLÇER — ve asıl soruyu da cevaplar:
**PARA NEDEN BOŞTA?** İki ihtimal var ve ayırt edilmesi şart:
  (a) koltuk limiti doluyor, sinyal var ama alınamıyor  → MAX_POSITIONS işe yarar
  (b) yeterli SİNYAL yok, koltuklar zaten boş           → MAX_POSITIONS hiçbir şey yapmaz
Her MAX_POSITIONS için "koltuk yüzünden reddedilen sinyal" sayısı raporlanıyor.
Bu sayı zaten küçükse (b) doğrudur ve boşta para bir ayar sorunu DEĞİL, stratejinin
doğal işlem sıklığının sonucudur.

Ölçülen: eklenen işlem · ortalama/tepe marjin · netPnL · maxDD · en kötü ay.
⚠️ Canlı marjin ön-kontrolü (execution.py:559) BİREBİR uygulanıyor: marjin > serbest×0.95
   ise işlem atlanır. Daha çok pozisyon = daha çok marjin = bir noktada reddedilme.

Kullanım:  py koltuk_kapasite.py local [bakiye]
"""
import heapq
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A

ONK = 0.95
LEV = 10.0
CAP = 1.50


def havuz(source):
    ham = []
    for c in A.DONCH:
        for t in A.gen("donchian", fast_bt.load(c, source=source)):
            ham.append((t[0], t[1].value, t[2], t[3]))
    for c in A.SQZ:
        for t in A.gen("squeeze", fast_bt.load(c, source=source)):
            ham.append((t[0], t[1].value, t[2], t[3]))
    for c in A.BB_COINS:
        for t in A.gen_bb(fast_bt.load(c, source=source)):
            ham.append((t[0], t[1].value, t[2], t[3]))
    return sorted(ham, key=lambda z: z[0])


def calistir(ham, maxpos, bal, cap=CAP, onkontrol=True):
    koltuk = []; ctr = 0; al = []
    k_red = m_red = 0
    kullanim = 0.0; tepe = 0.0
    segs = []; prev = ham[0][0]
    for e, x, R, slp in ham:
        while koltuk and koltuk[0][0] <= e:
            _, _, mj = heapq.heappop(koltuk); kullanim -= mj
        if e > prev:
            segs.append((prev, e, kullanim, len(koltuk))); prev = e
        if len(koltuk) >= maxpos:
            k_red += 1
            continue
        nom = min(A.RISKF * bal / slp, cap * bal)
        marjin = nom / LEV
        if onkontrol and marjin > (bal - kullanim) * ONK:
            m_red += 1
            continue
        ctr += 1
        heapq.heappush(koltuk, (x, ctr, marjin))
        kullanim += marjin
        tepe = max(tepe, kullanim)
        al.append((x, R, slp))
    tot_t = sum(b - a for a, b, _, _ in segs) or 1
    ort_m = sum(m * (b - a) for a, b, m, _ in segs) / tot_t
    ort_p = sum(p * (b - a) for a, b, _, p in segs) / tot_t
    return al, k_red, m_red, tepe, ort_m, ort_p


def olc(al, bal, cap=CAP):
    r = np.array([a[1] for a in al]); sp = np.array([a[2] for a in al])
    pnl = r * np.minimum(A.RISKF, cap * sp) * bal
    eq = bal + np.cumsum(pnl)
    ex = [pd.Timestamp(a[0]) for a in al]
    mon = pd.Series(pnl).groupby([x.to_period("M") for x in ex]).sum() / bal * 100
    return dict(n=len(al), tot=float(pnl.sum()),
                dd=float(A.maxdd(np.concatenate([[bal], eq]))), worst=float(mon.min()))


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    bal = float(sys.argv[2]) if len(sys.argv) > 2 else 203.0
    ham = havuz(source)

    a0, _, _, _, _, _ = calistir(ham, A.MAXPOS, A.BAL0, cap=A.CAP, onkontrol=False)
    k0 = olc(a0, A.BAL0, cap=A.CAP)
    ok = k0["n"] == 1579 and abs(k0["tot"] - 1420.66) < 0.01
    print(f"\n{'=' * 116}")
    print("=== BOŞTA PARA: her şey sabit kalarak kullanılabilir mi? ===")
    print(f"  KONTROL: {k0['n']} işlem / ${k0['tot']:+.2f} → "
          f"{'✓ BİREBİR' if ok else '✗ SAPMA'}")
    if not ok:
        return
    print(f"  bakiye ${bal:.0f} · kaldıraç {LEV:.0f}x · CAP {CAP} · "
          f"TP/SL ve işlem başına risk DEĞİŞMİYOR")
    print(f"  Değişen TEK şey: aynı anda kaç pozisyon tutulabildiği.")
    print(f"\n  {len(ham)} aday sinyal (koltuk seçiminden ÖNCE)")

    print(f"\n  {'MAXPOS':>7s} {'işlem':>6s} {'Δişlem':>7s} {'koltuk reddi':>13s} "
          f"{'marjin reddi':>13s} {'ort açık poz':>13s} {'ort marjin':>11s} "
          f"{'TEPE marjin':>12s} {'tepe/bak':>9s} {'netPnL$':>9s} {'Δ$':>7s} {'kötü ay%':>9s}")
    taban = None
    for mp in (5, 7, 10, 15, 20, 30):
        al, kr, mr, tepe, ort_m, ort_p = calistir(ham, mp, bal)
        v = olc(al, bal)
        if mp == A.MAXPOS:
            taban = v
        d = f"{v['tot']-taban['tot']:+7.0f}" if taban else f"{'—':>7s}"
        dn = f"{v['n']-taban['n']:+7d}" if taban else f"{'—':>7s}"
        mark = "  ← ŞU AN" if mp == A.MAXPOS else ""
        uy = "  ⛔ marjin reddi VAR → kâr fantezi" if mr > 0 else ""
        print(f"  {mp:>7d} {v['n']:>6d} {dn} {kr:>13d} {mr:>13d} {ort_p:>13.2f} "
              f"{ort_m:>11.1f} {tepe:>12.1f} {tepe/bal:>8.0%} {v['tot']:>+9.0f} {d} "
              f"{v['worst']:>+9.1f}{mark}{uy}")

    # ── ASIL SORU: para neden boşta? ──
    al, kr, mr, tepe, ort_m, ort_p = calistir(ham, A.MAXPOS, bal)
    print(f"\n{'=' * 116}\n=== PARA NEDEN BOŞTA? ===")
    print(f"  Ortalama aynı anda AÇIK pozisyon: {ort_p:.2f} / {A.MAXPOS} koltuk "
          f"(doluluk %{ort_p/A.MAXPOS*100:.0f})")
    print(f"  Ortalama kullanılan marjin: ${ort_m:.1f} / ${bal:.0f} "
          f"(%{ort_m/bal*100:.0f})")
    print(f"  Koltuk yüzünden reddedilen sinyal: {kr} / {len(ham)} "
          f"(%{kr/len(ham)*100:.1f})")
    print(f"\n  HÜKÜM:")
    if kr / len(ham) < 0.05:
        print(f"    Koltuk limiti sinyallerin yalnız %{kr/len(ham)*100:.1f}'ini engelliyor.")
        print(f"    → Para boşta çünkü KOLTUK YETMİYOR DEĞİL, YETERLİ SİNYAL YOK.")
        print(f"    → MAX_POSITIONS artırmak hiçbir şey eklemez; boşluk bir AYAR sorunu")
        print(f"      değil, stratejinin doğal işlem sıklığının sonucudur.")
        print(f"    → Boşta parayı kullanmanın tek yolu DAHA ÇOK SİNYAL üretmektir")
        print(f"      (yeni coin / yeni strateji) — ki bu 'her şey sabit kalsın' DEĞİLDİR.")
    else:
        print(f"    Koltuk limiti sinyallerin %{kr/len(ham)*100:.1f}'ini engelliyor —")
        print(f"    MAX_POSITIONS artırmak gerçekten işlem ekleyebilir. Tabloya bakın.")


if __name__ == "__main__":
    main()
