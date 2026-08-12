"""
sim_katki.py — "her ay $100 koysam 1 yılda ne olur?"

⚠️ NEDEN BASİT ÇARPMA YANLIŞ: "medyan ay %15, 12 ay → 1.15^12 = 5.4 kat" hesabı
YANILTIR. Üç ayrı sebepten:
 1. OYNAKLIK SÜRÜKLEMESİ: +%50 sonra −%50 sıfır değil, −%25'tir. Ortalama getiri
    bileşiklendiğinde kaybolur; aylar oynak oldukça beklenen sonuç düşer.
 2. SIRA ÖNEMLİ: para EKLERKEN kötü ayın erken mi geç mi geldiği sonucu değiştirir.
    Erken gelen kötü ay küçük bakiyeyi vurur, geç gelen kötü ay büyük bakiyeyi.
 3. TEK BİR SAYI CEVAP DEĞİL: 40 ayın 8'i zararlı. Sonuç bir DAĞILIMDIR.

BU BETİK: ankorun GERÇEK 40 aylık getiri dağılımından örnekleyip binlerce yol simüle eder.

İKİ AYRI ÖRNEKLEME (ikisi de raporlanıyor, çünkü farklı şeyleri yakalarlar):
 · BAĞIMSIZ: aylar torbadan tek tek çekilir. Kötü ayların ARDIŞIK gelme eğilimini
   yok eder → kuyruk fazla iyimser çıkar.
 · BLOK: tarihten ARDIŞIK 12 aylık pencereler. Kötü dönemlerin kümelenmesini korur
   → gerçekçi kuyruk. Az sayıda pencere var, o yüzden ikisi birlikte okunmalı.

İKİ AYRI EDGE SENARYOSU:
 · ANKOR: backtestin tam gücü (ort R = 0.237). İYİMSER — parametreler bu veriye
   bakılarak seçildi.
 · CANLI: bugüne kadar gerçekleşen (ort R = 0.1096, aktif kollar). Her işlemin R'si
   sabit bir miktar AŞAĞI kaydırılarak elde edilir; dağılımın şekli/oynaklığı korunur.
   Gerçek muhtemelen bu ikisinin ARASINDA — güven aralığı ankoru dışlamıyor.

VARSAYIMLAR (hepsi sonucu İYİMSER yönde etkiler, bilerek yazıldı):
 · Katkı ayın BAŞINDA yatırılır ve tüm ay çalışır.
 · Çekim yok, ücret/vergi yok, kesinti yok.
 · Edge 12 ay boyunca AYNI kalır. Piyasa rejimi değişmez varsayılıyor.

Kullanım:  py sim_katki.py local [başlangıç] [aylık_katkı]
"""
import heapq
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A

CAP_YENI = 1.50
ANK_R = 0.237       # ankor ortalama R
CANLI_R = 0.1096    # live_verify: aktif kollar, bugüne kadar
YOL = 20000


def islemler(source):
    trades = []
    for c in A.DONCH: trades += A.gen("donchian", fast_bt.load(c, source=source))
    for c in A.SQZ:   trades += A.gen("squeeze", fast_bt.load(c, source=source))
    for c in A.BB_COINS: trades += A.gen_bb(fast_bt.load(c, source=source))
    return A.seat_select(trades)


def aylik_getiri(taken, kaydirma=0.0):
    """Aylık getiri YÜZDESİ (bakiyenin yüzdesi). kaydirma: her işlemin R'sine eklenir."""
    r = np.array([R for _, R, _ in taken]) + kaydirma
    sp = np.array([s for _, _, s in taken])
    eff = np.minimum(A.RISKF, CAP_YENI * sp)
    pnl = r * eff                                    # bakiyenin ORANI
    ay = [pd.Timestamp(x).tz_localize(None).to_period("M") for x, _, _ in taken]
    return pd.Series(pnl).groupby(ay).sum().values   # oran, yüzde değil


def bagimsiz(getiriler, bas, katki, ay=12, yol=YOL, rng=None):
    rng = rng or np.random.default_rng(20260812)
    idx = rng.integers(0, len(getiriler), size=(yol, ay))
    g = getiriler[idx]
    bak = np.full(yol, bas, dtype=float)
    for a in range(ay):
        bak = (bak + katki) * (1.0 + g[:, a])
        bak = np.maximum(bak, 0.0)                   # hesap sıfırın altına inmez
    return bak


def blok(getiriler, bas, katki, ay=12):
    """Tarihten ARDIŞIK 12 aylık pencereler — kötü dönem kümelenmesini korur."""
    son = []
    for s in range(len(getiriler) - ay + 1):
        bak = bas
        for a in range(ay):
            bak = max((bak + katki) * (1.0 + getiriler[s + a]), 0.0)
        son.append(bak)
    return np.array(son)


def yaz(ad, son, yatirilan):
    p = np.percentile(son, [10, 25, 50, 75, 90])
    print(f"  {ad:<34s} ${p[0]:>7.0f} ${p[1]:>7.0f} ${p[2]:>7.0f} ${p[3]:>7.0f} ${p[4]:>7.0f}"
          f"   %{(son < yatirilan).mean()*100:>4.0f}")


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    bas = float(sys.argv[2]) if len(sys.argv) > 2 else 203.0
    katki = float(sys.argv[3]) if len(sys.argv) > 3 else 100.0
    taken = islemler(source)
    ok = len(taken) == 1579
    print(f"\n{'=' * 100}")
    print("=== HER AY $%.0f KATKI — 1 YIL SONRA NE OLUR? ===" % katki)
    print(f"  DOĞRULAMA: {len(taken)} == 1579 → {'✓' if ok else '✗ SAPMA'}")
    if not ok:
        return
    r_ham = np.array([R for _, R, _ in taken])
    print(f"  ankor ort R = {r_ham.mean():.4f} (beklenen {ANK_R})")

    yatirilan = bas + katki * 12
    print(f"\n  başlangıç ${bas:.0f} + 12 × ${katki:.0f} = TOPLAM YATIRILAN ${yatirilan:.0f}")
    print(f"  (bot hiç kazanmasa da kaybetmese de elinde ${yatirilan:.0f} olurdu)")

    senaryolar = [
        ("ANKOR edge (R=%.3f)" % ANK_R, 0.0),
        ("CANLI edge (R=%.4f)" % CANLI_R, CANLI_R - r_ham.mean()),
    ]
    print(f"\n  {'senaryo / örnekleme':<34s} {'%10':>8s} {'%25':>8s} {'MEDYAN':>8s} "
          f"{'%75':>8s} {'%90':>8s}   {'zarar':>5s}")
    for ad, kay in senaryolar:
        g = aylik_getiri(taken, kay)
        yaz(f"{ad} · bağımsız", bagimsiz(g, bas, katki), yatirilan)
        yaz(f"{ad} · blok(gerçek dönem)", blok(g, bas, katki), yatirilan)

    print(f"\n{'=' * 100}\n=== NASIL OKUNUR ===")
    print(f"  · 'MEDYAN' = yolların yarısı bunun ÜSTÜNDE, yarısı ALTINDA biter. Beklenen sonuç budur.")
    print(f"  · '%10' = kötü senaryo (10 yoldan 1'i bundan da kötü). Buna hazırlıklı olunmalı.")
    print(f"  · 'zarar' = 12 ay sonunda elindeki paranın YATIRDIĞINDAN AZ olma olasılığı.")
    print(f"  · GERÇEK muhtemelen ANKOR ile CANLI satırlarının ARASINDA. Canlı örneklem hâlâ")
    print(f"    küçük; güven aralığı ankoru dışlamıyor, yani ikisi de mümkün.")
    print(f"  · 'blok' satırı gerçek tarihten ardışık 12 ay; kötü dönemlerin kümelenmesini")
    print(f"    koruduğu için kuyruk tarafında BAĞIMSIZ satırdan daha güvenilir.")
    print(f"  · Tüm varsayımlar iyimser yönde: ücret/çekim yok, edge 12 ay sabit, katkı ay")
    print(f"    başında tam çalışıyor. Gerçek sonuç bu tablonun ALTINA düşebilir.")


if __name__ == "__main__":
    main()
