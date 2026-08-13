"""
marjin_kapasite.py — "hesabın çoğu boşta, daha çok MARJİN kullanamaz mıyız?"

ÖNCE KAVRAM DÜZELTMESİ — marjin bir getiri kaynağı DEĞİLDİR:
    marjin = nominal / kaldıraç
    getiri = nominal × fiyat hareketi
Marjin, o pozisyon için kilitlenen teminattır. Aynı nominal için daha çok teminat
kilitlemek (kaldıracı DÜŞÜRMEK) hiçbir şey kazandırmaz, yalnız parayı bağlar.
Dolayısıyla "daha çok marjin kullanalım" ancak "daha büyük NOMİNAL açalım" demekse
anlamlıdır — ve onun kolu POSITION_CAP_FRACTION'dır.

ÖLÇÜLEN DURUM (pw_bb_margin + paket_guvenlik, bugün):
  CAP=1.5, LEV=10 → ortalama marjin bakiyenin ~%17'si, TEPE %82, marjin reddi 0.
Yani hesap çoğu zaman boşta ama tepe noktada zaten dolu.

BU BETİK İKİ ŞEYİ ÖLÇER:

[1] CAP KAPASİTESİ — CAP'i 1.5'in üstüne çıkarmak canlıda UYGULANABİLİR mi?
    Canlı ön-kontrol (execution.py:559) `marjin > serbest × 0.95` ise işlemi ATLAR.
    Her CAP için olay-bazlı serbest bakiye takip edilip bu kural BİREBİR uygulanıyor.
    Reddedilen işlem varsa backtest kârı FANTEZİDİR.
    (pw_cap_margin CAP=3'ü zaten böyle öldürmüştü: tepe $203.6 > $190 bakiye.)

[2] KALDIRAÇ — LİKİDASYON GÜVENLİĞİ. Kaldıracı yükseltmek marjini serbest bırakır
    AMA likidasyon fiyatını girişe YAKLAŞTIRIR:
        likidasyon hareketi ≈ 1/kaldıraç − bakım_marjini
    Stop mesafesi bu hareketten BÜYÜKSE stop çalışmadan likide olursun — felaket.
    Her kaldıraç için "stopu likidasyonun ÖTESİNDE kalan işlem" oranı raporlanıyor.
    ⚠️ Bu, kâr sorusundan ÖNCE gelen bir GÜVENLİK sorusudur.

Kullanım:  py marjin_kapasite.py local [bakiye]
"""
import heapq
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A

ONK = 0.95          # execution.py:559 tamponu
BAKIM = 0.005       # MEXC bakım marjini (yaklaşık, muhafazakâr)


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


def calistir(ham, cap, lev, bal, onkontrol=True):
    """Koltuk + CANLI marjin ön-kontrolü. Dönüş: (alınan, marjin_reddi, tepe, ort)."""
    koltuk = []; ctr = 0; al = []; red = 0
    kullanim = 0.0; tepe = 0.0
    segs = []; prev = ham[0][0]
    for e, x, R, slp in ham:
        while koltuk and koltuk[0][0] <= e:
            _, _, mj = heapq.heappop(koltuk); kullanim -= mj
        if e > prev:
            segs.append((prev, e, kullanim)); prev = e
        if len(koltuk) >= A.MAXPOS:
            continue
        nom = min(A.RISKF * bal / slp, cap * bal)
        marjin = nom / lev
        if onkontrol and marjin > (bal - kullanim) * ONK:
            red += 1
            continue
        ctr += 1
        heapq.heappush(koltuk, (x, ctr, marjin))
        kullanim += marjin
        tepe = max(tepe, kullanim)
        al.append((x, R, slp))
    tot_t = sum(b - a for a, b, _ in segs) or 1
    ort = sum(m * (b - a) for a, b, m in segs) / tot_t
    return al, red, tepe, ort


def olc(al, cap, bal):
    if not al:
        return dict(n=0, tot=0.0, dd=0.0, worst=0.0)
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

    al, _, _, _ = calistir(ham, A.CAP, 10.0, A.BAL0, onkontrol=False)
    kon = olc(al, A.CAP, A.BAL0)
    ok = kon["n"] == 1579 and abs(kon["tot"] - 1420.66) < 0.01
    print(f"\n{'=' * 112}")
    print("=== MARJİN KAPASİTESİ: daha büyük pozisyon açabilir miyiz? ===")
    print(f"  KONTROL: {kon['n']} işlem / ${kon['tot']:+.2f} → "
          f"{'✓ BİREBİR' if ok else '✗ SAPMA'}")
    if not ok:
        return
    print(f"  bakiye ${bal:.0f} · ön-kontrol: marjin > serbest×{ONK} ise işlem ATLANIR")
    print(f"\n  ⚠ MARJİN GETİRİ ÜRETMEZ. Getiriyi NOMİNAL üretir; marjin sadece kilitlenen")
    print(f"    teminattır. Kaldıracı düşürüp daha çok marjin bağlamak HİÇBİR ŞEY kazandırmaz.")

    # ── [1] CAP KAPASİTESİ (LEV=10 sabit) ──
    print(f"\n[1] CAP KAPASİTESİ — kaldıraç 10x sabit")
    print(f"  {'CAP':>5s} {'işlem':>6s} {'marjin reddi':>13s} {'ort marjin':>11s} "
          f"{'TEPE marjin':>12s} {'tepe/bak':>9s} {'netPnL$':>9s} {'Δ$':>7s} "
          f"{'maxDD%':>7s} {'kötü ay%':>9s}")
    taban = None
    for cap in (1.25, 1.50, 1.75, 2.00, 2.50, 3.00):
        a2, red, tepe, ort = calistir(ham, cap, 10.0, bal)
        v = olc(a2, cap, bal)
        if cap == 1.50:
            taban = v
        d = f"{v['tot']-taban['tot']:+7.0f}" if taban else f"{'—':>7s}"
        uy = ""
        if red > 0:
            uy = f"  ⛔ {red} işlem AÇILAMAZ → kâr FANTEZİ"
        elif tepe > bal * 0.90:
            uy = "  ⚠ tampon yok"
        mark = "  ← ŞU AN" if abs(cap - 1.5) < 1e-9 else ""
        print(f"  {cap:>5.2f} {v['n']:>6d} {red:>13d} {ort:>11.1f} {tepe:>12.1f} "
              f"{tepe/bal:>8.0%} {v['tot']:>+9.0f} {d} {v['dd']:>7.1f} "
              f"{v['worst']:>+9.1f}{mark}{uy}")

    # ── [2] KALDIRAÇ GÜVENLİĞİ ──
    print(f"\n[2] KALDIRAÇ — likidasyon güvenliği (KÂRDAN ÖNCE GELEN SORU)")
    sp = np.array([h[3] for h in ham])
    print(f"    stop mesafesi: medyan %{np.median(sp)*100:.2f} · "
          f"%90'ı %{np.percentile(sp, 90)*100:.2f}'in altında · "
          f"en geniş %{sp.max()*100:.2f}")
    print(f"\n  {'kaldıraç':>9s} {'likidasyon hareketi':>20s} {'stopu ÖTEDE kalan':>19s} "
          f"{'tepe marjin (CAP=1.5)':>22s}")
    for lev in (5, 10, 15, 20, 25):
        lik = 1.0 / lev - BAKIM
        tehlike = float((sp >= lik).mean() * 100)
        _, _, tepe, _ = calistir(ham, 1.50, float(lev), bal)
        bay = ""
        if tehlike > 1.0:
            bay = f"  ⛔ işlemlerin %{tehlike:.1f}'i STOP ÇALIŞMADAN LİKİDE OLUR"
        elif tehlike > 0:
            bay = f"  ⚠ %{tehlike:.2f}"
        mark = "  ← ŞU AN" if lev == 10 else ""
        print(f"  {lev:>8d}x {lik*100:>19.2f}% {tehlike:>18.2f}% "
              f"{tepe:>21.1f}{mark}{bay}")

    print(f"\n{'=' * 112}\n=== NASIL OKUNUR ===")
    print("  · [1] 'marjin reddi' > 0 olan satır UYGULANAMAZ: o işlemler canlıda")
    print("    açılamaz, backtest onları almış sayar, kâr rakamı gerçek değildir.")
    print("  · [2] 'stopu ÖTEDE kalan' = stop mesafesi likidasyon hareketinden BÜYÜK olan")
    print("    işlem oranı. Bu işlemlerde stop çalışmadan likide olursun — tam kayıp,")
    print("    üstelik ankorun modellediği −1R DEĞİL. Sıfırdan büyükse o kaldıraç KULLANILMAZ.")
    print("  · Kaldıracı YÜKSELTMEK marjin serbest bırakır ama likidasyonu yaklaştırır;")
    print("    marjin zaten bağlamıyorsa (reddi 0) bu takas SAF ZARARDIR.")


if __name__ == "__main__":
    main()
