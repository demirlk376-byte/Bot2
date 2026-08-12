"""
pw_cap_margin.py — CAP BULGUSUNUN ÖLÜM TESTİ: marjin gerçekten yetiyor mu?

pw_cap bugünün İLK geçen sonucunu verdi: CAP 1.25 → 1.5/2/3 arasında kâr monoton artıyor
(+$55 … +$162), maxDD neredeyse sabit (24.4 → 25.3), en kötü ay İYİLEŞİYOR (−21.0 → −20.3),
dört yıl da iyileşiyor. Doz-yanıt temiz, zikzak yok.

VE MEKANİZMA ANLAŞILIR: CAP bizim SEÇTİĞİMİZ bir risk kontrolü değil, hedeflediğimiz riski
(%2.25) alamamıza engel olan bir ARTEFAKT. Ortalama gerçekleşen risk CAP ile birlikte
2.13% → 2.25%'e çıkıyor — yani tavanı gevşetmek riski hedefin ÜSTÜNE çıkarmıyor, sadece
kırpılmayı durduruyor. Bu, bugün reddettiğim "daha çok maruziyet" değişikliklerinden
YAPISAL OLARAK farklı.

⚠️ AMA BACKTEST BİR ŞEYİ MODELLEMİYOR: MARJİN.
CAP = azami nominal / bakiye. CAP=5 demek tek bir pozisyonun 5×bakiye nominal alabilmesi
demek — 10x kaldıraçla bakiyenin YARISI kadar marjin. Yedi koltuk varken bu fiziksel olarak
imkânsız olabilir ve o işlemler CANLIDA REDDEDİLİR. Backtest onları almış sayar → FANTEZİ.

BU BETİK: her CAP değeri için EŞZAMANLI marjin talebini olay-bazlı hesaplar ve bakiyeyi
aşan anları sayar. Aşıyorsa o CAP değeri UYGULANAMAZ — kâr rakamı gerçek değildir.

AYRICA: MEXC'in tek-pozisyon marjin tavanı da var (kaldıraç kademesi). $190'lık bir hesapta
bu muhtemelen bağlamaz ama nominal/bakiye oranı raporlanıyor ki gözden kaçmasın.

Kullanım:  py pw_cap_margin.py local
"""
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A

LEV = 10.0
BAL = 190.0          # ankor tabanı (sabit-oran modeli)


def pozisyonlar(source):
    """Ankorun ALDIĞI işlemler + giriş/çıkış zamanı + sl_pct.
    A.seat_select yalnız (exit_ts, R, sl_pct) döndürüyor; marjin için GİRİŞ zamanı da
    gerekiyor, o yüzden seat mantığı burada sembol/zaman koruyarak tekrarlanıyor."""
    import heapq
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
            out.append((entry_ns, exit_ts.value, R, slp))
    return out


def marjin_profili(poz, cap):
    """Olay-bazlı eşzamanlı marjin. Dönüş: (segmentler, tepe, süre-ağırlıklı ortalama)."""
    ev = []
    for s, e, R, slp in poz:
        # nominal = min(risk$/sl%, CAP×bakiye)
        nom = min(A.RISKF * BAL / slp, cap * BAL)
        ev.append((s, +nom / LEV)); ev.append((e, -nom / LEV))
    ev.sort()
    cur = 0.0; segs = []; prev = ev[0][0]
    for ts, d in ev:
        if ts > prev: segs.append((prev, ts, cur))
        cur += d; prev = ts
    tot_t = sum(e - s for s, e, _ in segs) or 1
    ort = sum(m * (e - s) for s, e, m in segs) / tot_t
    tepe = max(m for _, _, m in segs)
    return segs, tepe, ort


def asilan_oran(segs, esik):
    tot = sum(e - s for s, e, _ in segs) or 1
    return sum(e - s for s, e, m in segs if m > esik) / tot * 100


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    poz = pozisyonlar(source)
    print(f"\n{'=' * 100}")
    print("=== CAP ÖLÜM TESTİ: marjin yetiyor mu? (backtest bunu modellemiyor) ===")
    print(f"  {len(poz)} pozisyon · bakiye ${BAL:.0f} · kaldıraç {LEV:.0f}x")
    print(f"  DOĞRULAMA: {len(poz)} == 1579 → {'✓' if len(poz)==1579 else '✗ SAPMA'}")
    if len(poz) != 1579:
        return

    print(f"\n  {'CAP':>5s} {'tek poz. azami':>15s} {'ort marjin$':>12s} {'TEPE marjin$':>13s} "
          f"{'>bakiye %zaman':>15s} {'>%80 %zaman':>13s}")
    for cap in (1.00, 1.25, 1.50, 2.00, 3.00, 5.00):
        segs, tepe, ort = marjin_profili(poz, cap)
        tek = cap * BAL / LEV
        a100 = asilan_oran(segs, BAL)
        a80 = asilan_oran(segs, BAL * 0.8)
        mark = "  ← CANLI" if abs(cap - A.CAP) < 1e-9 else ""
        uyari = "  ⛔ UYGULANAMAZ" if a100 > 0.5 else ("  ⚠ sınırda" if a80 > 5 else "")
        print(f"  {cap:>5.2f} ${tek:>14.2f} ${ort:>11.1f} ${tepe:>12.1f} "
              f"{a100:>14.1f}% {a80:>12.1f}%{mark}{uyari}")

    print(f"\n  OKUMA:")
    print(f"   · 'tek poz. azami' = CAP×bakiye/kaldıraç — TEK bir pozisyonun marjini")
    print(f"   · '>bakiye %zaman' = eşzamanlı marjin talebinin bakiyeyi AŞTIĞI zaman oranı")
    print(f"     Bu >0 ise o CAP'te bazı işlemler canlıda AÇILAMAZ; backtest kârı fantezidir.")
    print(f"   · %80 eşiği tampon içindir (fonlama, ücret, uPnL dalgalanması, likidasyon payı)")

    # ── kaç işlem gerçekten büyür ──
    print(f"\n  --- CAP artınca KAÇ işlem büyüyor ve NE KADAR ---")
    slp = np.array([p[3] for p in poz])
    print(f"  {'CAP':>5s} {'büyüyen işlem':>14s} {'ort büyüme':>11s} {'en büyük nominal$':>18s}")
    base_nom = np.minimum(A.RISKF * BAL / slp, A.CAP * BAL)
    for cap in (1.50, 2.00, 3.00, 5.00):
        nom = np.minimum(A.RISKF * BAL / slp, cap * BAL)
        buyuyen = nom > base_nom + 1e-9
        oran = (nom[buyuyen] / base_nom[buyuyen]).mean() if buyuyen.any() else 1.0
        print(f"  {cap:>5.2f} {buyuyen.sum():>10d} (%{buyuyen.mean()*100:.0f}) "
              f"{oran:>10.2f}x ${nom.max():>17.2f}")


if __name__ == "__main__":
    main()
