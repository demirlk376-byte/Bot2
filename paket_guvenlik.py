"""
paket_guvenlik.py — BUGÜN UYGULANAN PAKETİN ÖLÇÜLMEMİŞ YAN ETKİSİ: işlem kaybı.

Paket: MAX_RISK_PCT 0.08→0.02 (BB hizalama) + POSITION_CAP_FRACTION 1.25→1.5.
Ankor üzerinde +$68 ve en kötü ay −21.4→−20.5 gösterdi. AMA ankor bir şeyi
modellemiyor: CANLI MARJİN ÖN-KONTROLÜ.

execution.py:559 —
    if setup.margin_required > balance * 0.95:   # balance = SERBEST bakiye
        ... "Yetersiz bakiye" ... return  ← İŞLEM ATLANIR
CAP=1.5 ile dar stoplu işlemler DAHA BÜYÜK nominal alıyor, dolayısıyla daha çok
marjin istiyor. Eşzamanlı 7 koltuk varken bu, bazı işlemlerin canlıda AÇILAMAMASINA
yol açabilir. Backtest onları almış sayar → ölçülen +$68'in bir kısmı hayalî olur.

⚠️ TERS YÖNDE BİR ETKİ DE VAR ve hesaba katılıyor: BB hizalaması BB'nin nominalini
KÜÇÜLTÜYOR (CAP'e yapışıktı, artık %2.25 hedefiyle sınırlı). Yani paket bir yandan
trend kollarının marjinini artırırken diğer yandan BB'ninkini azaltıyor. Net etki
ölçülmeden bilinemez.

BU BETİK: her işlem için giriş anındaki SERBEST bakiyeyi olay-bazlı takip eder ve
canlı kuralı birebir uygular. Dört yapılandırma karşılaştırılır:
  1) ESKİ  BB %9    CAP 1.25   (dünkü canlı)
  2) YENİ  BB %2.25 CAP 1.50   (bugün uygulanan)
  3) ARA   BB %2.25 CAP 1.25   (yalnız hizalama)
  4) ESKİ+ BB %9    CAP 1.50   (yalnız CAP — uygulanmadı, karşılaştırma için)

SORU: (2) yapılandırmasında işlem kaybı VAR MI, ve varsa ölçülen +$68 hâlâ ayakta mı?

Kullanım:  py paket_guvenlik.py local [bakiye]
"""
import heapq
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A

LEV = 10.0
MAXR_ESKI = 0.08 * 1.125     # dünkü BB hedefi
ONK = 0.95                   # execution.py:559 tamponu


def havuz(source):
    """(kol, entry_ns, exit_ns, R, sl_pct) — kararlı sırada."""
    ham = []
    for c in A.DONCH:
        for t in A.gen("donchian", fast_bt.load(c, source=source)):
            ham.append(("trend", t[0], t[1].value, t[2], t[3]))
    for c in A.SQZ:
        for t in A.gen("squeeze", fast_bt.load(c, source=source)):
            ham.append(("trend", t[0], t[1].value, t[2], t[3]))
    for c in A.BB_COINS:
        for t in A.gen_bb(fast_bt.load(c, source=source)):
            ham.append(("bb", t[0], t[1].value, t[2], t[3]))
    return sorted(ham, key=lambda z: z[1])


def calistir(ham, cap, bb_hedef, bal, onkontrol=True):
    """Koltuk + CANLI MARJİN ÖN-KONTROLÜ. Dönüş: (alınan, koltuk_reddi, marjin_reddi, tepe)."""
    koltuk = []          # (exit_ns, ctr, marjin)
    ctr = 0; al = []
    k_red = m_red = 0
    kullanim = 0.0; tepe = 0.0
    for kol, e_ns, x_ns, R, slp in ham:
        while koltuk and koltuk[0][0] <= e_ns:
            _, _, mj = heapq.heappop(koltuk)
            kullanim -= mj
        if len(koltuk) >= A.MAXPOS:
            k_red += 1
            continue
        hedef = bb_hedef if kol == "bb" else A.RISKF
        nom = min(hedef * bal / slp, cap * bal)
        marjin = nom / LEV
        serbest = bal - kullanim
        if onkontrol and marjin > serbest * ONK:
            m_red += 1                      # canlıda bu işlem AÇILAMAZ
            continue
        ctr += 1
        heapq.heappush(koltuk, (x_ns, ctr, marjin))
        kullanim += marjin
        tepe = max(tepe, kullanim)
        al.append((x_ns, R, slp, hedef, kol))
    return al, k_red, m_red, tepe


def olc(al, cap, bal):
    if not al:
        return dict(n=0, tot=0.0, dd=0.0, worst=0.0, negay=0, ay=0)
    r = np.array([a[1] for a in al]); sp = np.array([a[2] for a in al])
    hd = np.array([a[3] for a in al])
    eff = np.minimum(hd, cap * sp)
    pnl = r * eff * bal
    eq = bal + np.cumsum(pnl)
    ex = [pd.Timestamp(a[0]) for a in al]
    mon = pd.Series(pnl).groupby([x.to_period("M") for x in ex]).sum() / bal * 100
    return dict(n=len(al), tot=float(pnl.sum()),
                dd=float(A.maxdd(np.concatenate([[bal], eq]))),
                worst=float(mon.min()), negay=int((mon < 0).sum()), ay=len(mon))


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    bal = float(sys.argv[2]) if len(sys.argv) > 2 else 203.0
    ham = havuz(source)

    # KONTROL: ön-kontrol KAPALI + eski ayar → ankor birebir çıkmalı
    al, _, _, _ = calistir(ham, A.CAP, A.RISKF, A.BAL0, onkontrol=False)
    kon = olc(al, A.CAP, A.BAL0)
    ok = kon["n"] == 1579 and abs(kon["tot"] - 1420.66) < 0.01
    print(f"\n{'=' * 114}")
    print("=== PAKET GÜVENLİK: canlı marjin ön-kontrolü işlem kaybettiriyor mu? ===")
    print(f"  KONTROL (ön-kontrol kapalı, eski ayar): {kon['n']} işlem / ${kon['tot']:+.2f} → "
          f"{'✓ BİREBİR' if ok else '✗ SAPMA'}")
    if not ok:
        return
    print(f"  bakiye ${bal:.0f} · kaldıraç {LEV:.0f}x · ön-kontrol: marjin > serbest×{ONK}")

    yap = [
        ("1) ESKİ   BB %9    CAP 1.25", 1.25, MAXR_ESKI),
        ("2) YENİ   BB %2.25 CAP 1.50", 1.50, A.RISKF),
        ("3) ARA    BB %2.25 CAP 1.25", 1.25, A.RISKF),
        ("4) yalnız CAP: BB %9 CAP 1.50", 1.50, MAXR_ESKI),
    ]
    print(f"\n  {'yapılandırma':<31s} {'işlem':>6s} {'marjin reddi':>13s} {'tepe marjin$':>13s} "
          f"{'tepe/bak':>9s} {'netPnL$':>9s} {'maxDD%':>7s} {'kötü ay%':>9s} {'neg/ay':>7s}")
    res = {}
    for ad, cap, bh in yap:
        al, kr, mr, tepe = calistir(ham, cap, bh, bal)
        v = olc(al, cap, bal); res[ad[0]] = (v, mr, tepe)
        uyari = "  ⚠ İŞLEM KAYBI" if mr > 0 else ""
        print(f"  {ad:<31s} {v['n']:>6d} {mr:>13d} {tepe:>13.1f} {tepe/bal:>8.0%} "
              f"{v['tot']:>+9.0f} {v['dd']:>7.1f} {v['worst']:>+9.1f} "
              f"{v['negay']:>3d}/{v['ay']:<3d}{uyari}")

    e, e_mr, e_tepe = res["1"]; y, y_mr, y_tepe = res["2"]
    print(f"\n{'=' * 114}\n=== HÜKÜM ===")
    print(f"\n  BUGÜN UYGULANAN (2) vs DÜNKÜ (1):")
    print(f"    işlem      {e['n']:>6d} → {y['n']:>6d}   ({y['n']-e['n']:+d})")
    print(f"    marjin reddi {e_mr:>4d} → {y_mr:>4d}")
    print(f"    net PnL    ${e['tot']:>+7.0f} → ${y['tot']:>+7.0f}   ({y['tot']-e['tot']:+.0f}$)")
    print(f"    en kötü ay {e['worst']:>+7.1f} → {y['worst']:>+7.1f}")
    print(f"    tepe marjin ${e_tepe:>6.1f} → ${y_tepe:>6.1f}  (bakiyenin "
          f"%{e_tepe/bal*100:.0f} → %{y_tepe/bal*100:.0f}'i)")
    if y_mr == 0:
        print(f"\n    ✓ MARJİN YÜZÜNDEN HİÇ İŞLEM KAYBEDİLMİYOR. Ölçülen kazanç ayakta.")
    elif y_mr <= e_mr:
        print(f"\n    ✓ Yeni ayar ESKİSİNDEN DAHA AZ işlem kaybediyor ({y_mr} vs {e_mr}).")
    else:
        print(f"\n    ⚠ Yeni ayar {y_mr-e_mr} işlem DAHA kaybediyor. Kazancın bir kısmı hayalî.")
    print(f"\n  NOT: BB hizalaması BB nominalini KÜÇÜLTÜR (CAP'e yapışıktı), CAP artışı ise")
    print(f"  trend kollarınınkini BÜYÜTÜR. (4) satırı yalnız CAP artışını gösteriyor —")
    print(f"  (2) ile farkı, hizalamanın marjin tarafında ne kadar yer açtığıdır.")


if __name__ == "__main__":
    main()
