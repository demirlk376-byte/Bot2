"""
yil_projeksiyon.py — "her ay $150 eklesem 1 yıl sonra ne olur?"

BU BİR TAHMİN DEĞİL, BİR DAĞILIMDIR. Tek sayı vermek yalan olur: aynı edge ile
12 ay, çok farklı sonuçlara çıkabilir. Bu yüzden Monte Carlo koşuluyor ve
medyan + %10/%90 dilimleri raporlanıyor.

ÜÇ SENARYO — hangisinin doğru olduğunu BİLMİYORUZ, aralık bu yüzden var:

  A) ÇIPA AYNEN — backtestin aylık dağılımı, canlı ayarlarla (cap 1.50, risk %2.80).
     Bu bir TAVAN'dır: parametreler bu veriye BAKILARAK seçildi.

  B) ÇIPA − KAYMA — üstüne ölçülen giriş kaymasını (15.85bp) düşer.
     Ankor bu maliyeti modellemiyor; gerçek para onu ödüyor. ÇIKIŞ kayması
     ayrıca var ve burada YOK, yani B bile hafif iyimser.

  C) B'nin YARISI — coin evreni geçmiş performansa bakılarak seçilmişti
     (donchian coinleri 21 coin içinde ort. sıra 4.6, rastgele 11.0). coin_expand
     yürüyen-pencere testi bu seçimin İLERİYE TAŞINMADIĞINI gösterdi. Ama 21
     coinin 18'i pozitif → edge geniş ve gerçek, seçim onu BÜYÜTTÜ, YARATMADI.
     İleri beklenti ankorun %50-100'ü. C o aralığın ALT ucu.

KATKI: her ayın BAŞINDA eklenir, o ayın getirisini de alır.
BİLEŞİK: bot canlı bakiyeye göre boyutlanıyor, yani yüzdeler bileşiklenir.

⚠ ÖLÇÜLMEMİŞ BÖLGE: kayma ölçümü $59-513 nominal aralığını kapsıyor. Bakiye
$2000'i geçince nominal o aralığın ÜSTÜNE çıkar ve orada VERİMİZ YOK. Büyük
emrin piyasayı daha çok itmesi beklenir; etkisi ölçülene kadar bilinmiyor.

Kullanım:  py yil_projeksiyon.py local [baslangic_bakiye] [aylik_katki]
"""
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A

AY = 12
YOL = 20000
KAYMA_BP = 15.85        # kayma_denetim.py · 2026-09-09 · n=54 · [%95: 8.34, 23.37]
TOHUM = 20260909        # sabit tohum: aynı girdi → aynı çıktı, sonuç cherry-pick edilemez


def cipa_islemler(source):
    ham = []
    for c in A.DONCH: ham += A.gen("donchian", fast_bt.load(c, source=source))
    for c in A.SQZ:   ham += A.gen("squeeze",  fast_bt.load(c, source=source))
    for c in A.BB_COINS: ham += A.gen_bb(fast_bt.load(c, source=source))
    taken = A.seat_select(ham)
    if len(taken) != 1579:
        print(f"✗ ÇIPA BOZUK: {len(taken)} işlem, 1579 bekleniyordu. Rakam BASMIYORUM.")
        sys.exit(2)
    return taken


def aylik_yuzde(taken, r_carp=1.0, kayma_bp=0.0):
    """Aylık getiri yüzdesi serisi — CANLI ayarlarla (CANLI_RISKF, CANLI_CAP)."""
    r = np.array([R for _, R, _ in taken], dtype=float)
    slp = np.array([sp for _, _, sp in taken], dtype=float)
    exits = pd.to_datetime([x for x, _, _ in taken])

    # Kayma R cinsinden: fiyatın kayma_bp'si, stop mesafesine bölünür.
    # Dar stopta ısırığı BÜYÜK — bu yüzden işlem başına ayrı ayrı hesaplanıyor,
    # ortalama üzerinden değil.
    if kayma_bp:
        r = r - (kayma_bp / 1e4) / slp

    # Edge zayıflaması: ORTALAMAYI düşür, dağılımı koru. Her R'yi çarpmak
    # oynaklığı da küçültürdü ve riski OLDUĞUNDAN AZ gösterirdi.
    if r_carp != 1.0:
        r = r - r.mean() * (1.0 - r_carp)

    eff = np.minimum(A.CANLI_RISKF, A.CANLI_CAP * slp)
    pnl_pct = r * eff * 100
    ay = exits.tz_localize(None).to_period("M").values
    return pd.Series(pnl_pct).groupby(ay).sum()


def pencere_yuru(aylar, bakiye, katki):
    """GERÇEK ardışık 12 aylık pencereler — örnekleme YOK, sıra KORUNUR.

    Bootstrap ayları bağımsız çekiyor; oysa gerçek hayatta aylar art arda gelir
    ve kötü aylar KÜMELENİR. Bir boğa ayını bir ayı ayının ardına rastgele
    dizmek riski OLDUĞUNDAN AZ gösterir. Bu fonksiyon o hileyi yapmıyor:
    geçmişte GERÇEKTEN olmuş her 12 aylık dilimi tek tek yürütüyor.
    """
    v = np.asarray(aylar, dtype=float) / 100.0
    sonuc = []
    for i in range(len(v) - AY + 1):
        eq = float(bakiye)
        for a in range(AY):
            eq = max(0.0, (eq + katki) * (1.0 + v[i + a]))
        sonuc.append(eq)
    return np.array(sonuc)


def simule(aylar, bakiye, katki, rng):
    """YOL adet 12-aylık yol. Aylar YERİNE KOYARAK örnekleniyor."""
    ornek = rng.choice(aylar, size=(YOL, AY), replace=True) / 100.0
    eq = np.full(YOL, float(bakiye))
    for a in range(AY):
        eq = (eq + katki) * (1.0 + ornek[:, a])
        eq = np.maximum(eq, 0.0)          # hesap sıfırın altına inemez
    return eq


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    bakiye = float(sys.argv[2]) if len(sys.argv) > 2 else 306.0
    katki = float(sys.argv[3]) if len(sys.argv) > 3 else 150.0
    taken = cipa_islemler(source)
    rng = np.random.default_rng(TOHUM)
    yatan = bakiye + katki * AY

    print(f"\n{'=' * 88}")
    print(f"=== 1 YIL PROJEKSİYONU — başlangıç ${bakiye:.0f}, her ay +${katki:.0f} ===")
    print(f"  1579 işlem doğrulandı ✓   ·   canlı ayar: cap {A.CANLI_CAP}, "
          f"risk %{A.CANLI_RISKF*100:.2f}   ·   {YOL:,} yol")
    print(f"  BOT OLMASA: ${yatan:,.0f} (sadece yatırdığın para). Her sayı buna kıyaslanmalı.\n")

    senaryolar = [
        ("A) ÇIPA AYNEN        (tavan, iyimser)", 1.0, 0.0),
        ("B) ÇIPA − KAYMA      (en gerçekçi)",    1.0, KAYMA_BP),
        ("C) B'nin YARISI      (taban, kötümser)", 0.5, KAYMA_BP),
    ]
    print(f"  {'senaryo':<38s} {'aylık ort':>10s} {'MEDYAN yıl':>12s} "
          f"{'%10 dilim':>11s} {'%90 dilim':>11s} {'zarar riski':>12s}")
    for ad, carp, kayma in senaryolar:
        aylar = aylik_yuzde(taken, carp, kayma)
        son = simule(aylar, bakiye, katki, rng)
        p10, p50, p90 = np.percentile(son, [10, 50, 90])
        kayip = (son < yatan).mean() * 100
        print(f"  {ad:<38s} {aylar.mean():>9.2f}% ${p50:>10,.0f} "
              f"${p10:>10,.0f} ${p90:>10,.0f} {kayip:>11.0f}%")

    # En gerçekçi senaryoyu aç
    aylar = aylik_yuzde(taken, 1.0, KAYMA_BP)
    son = simule(aylar, bakiye, katki, rng)
    p10, p50, p90 = np.percentile(son, [10, 50, 90])
    print(f"\n  {'—' * 84}")
    print(f"  B) ÇIPA − KAYMA açılımı  ({len(aylar)} aylık geçmişten örneklendi)")
    print(f"    aylık: ort %{aylar.mean():+.2f} · MEDYAN %{np.median(aylar):+.2f} · "
          f"en kötü %{aylar.min():+.2f} · artı ay %{(aylar > 0).mean()*100:.0f}")
    print(f"    yıl sonu MEDYAN ${p50:,.0f}  →  yatırdığının ${p50 - yatan:+,.0f} "
          f"üstü (%{(p50/yatan - 1)*100:+.1f})")
    print(f"    yolların %80'i ${p10:,.0f} ile ${p90:,.0f} arasında")
    print(f"    ${yatan:,.0f}'ın ALTINDA bitme olasılığı: %{(son < yatan).mean()*100:.0f}")
    print(f"    yarıya (${yatan/2:,.0f}) inme olasılığı:  %{(son < yatan/2).mean()*100:.0f}")

    # ── GERÇEK PENCERELER — asıl bakılması gereken yer ──
    ser = aylik_yuzde(taken, 1.0, KAYMA_BP)
    pen = pencere_yuru(ser.values, bakiye, katki)
    idx = ser.index
    en_kotu_i = int(np.argmin(pen)); en_iyi_i = int(np.argmax(pen))
    print(f"\n  {'—' * 84}")
    print(f"  GERÇEK 12 AYLIK PENCERELER (B senaryosu, sıra KORUNDU — {len(pen)} pencere)")
    print(f"  Bootstrap ayları bağımsız çekiyor; gerçekte kötü aylar KÜMELENİR.")
    print(f"  Asıl bakılması gereken yer burası.\n")
    print(f"    {'pencere':<22s} {'yıl sonu':>12s}  {'yatırdığına göre':>18s}")
    for ad, i in (("EN KÖTÜ", en_kotu_i), ("MEDYAN", int(np.argsort(pen)[len(pen)//2])),
                  ("EN İYİ", en_iyi_i)):
        bas, bit = idx[i], idx[i + AY - 1]
        print(f"    {ad:<8s} {str(bas):>6s}→{str(bit):<7s} ${pen[i]:>11,.0f}  "
              f"${pen[i] - yatan:>+16,.0f}")
    kayb = (pen < yatan).mean() * 100
    print(f"\n    {len(pen)} pencerenin %{kayb:.0f}'ı ${yatan:,.0f}'ın ALTINDA bitti.")
    print(f"    ⚠ Bu pencerelerin çoğu BOĞA piyasasında geçti (2023-2024). Ayı/yatay")
    print(f"      rejimde bot döküldüğünü sen de gözlemledin. EN KÖTÜ satırı taban DEĞİL,")
    print(f"      sadece geçmişte GÖRDÜĞÜMÜZ en kötü. Daha kötüsü mümkün.")

    print(f"\n  {'—' * 84}\n  BUNU NASIL OKUMALI")
    print(f"    · ⚠⚠ BİLEŞİK RAKAMLAR FANTEZİYE KAÇAR. deployed_backtest.py'nin kendi")
    print(f"      uyarısı: 'bileşik görünüm küçük hesapta patlar = fantezi'. Çıpanın")
    print(f"      aylık %20'si SABİT $190 tabanında ölçüldü. Onu 12 ay bileşiklemek,")
    print(f"      aynı oranın HER hesap boyutunda geçerli olduğunu VARSAYAR — ve bu")
    print(f"      varsayım TEST EDİLMEDİ. Yukarıdaki büyük sayılara PLAN YAPMA.")
    print(f"    · Aylık ORTALAMA yanıltıcıdır; birkaç büyük ay onu çeker. Tipik ay MEDYAN.")
    print(f"    · Kâr esas olarak BİLEŞİKTEN değil, EKLEDİĞİN PARADAN geliyor: ${katki*AY:,.0f}")
    print(f"      katkı vs ${p50 - yatan:+,.0f} bot katkısı. Bot parayı çoğaltıyor, yaratmıyor.")
    print(f"    · Üç senaryonun HANGİSİNİN doğru olduğunu bilmiyoruz. Edge'i sıfırdan")
    print(f"      ayırmak ~312 işlem istiyor (bugün 67, ~8 ay). O güne kadar aralık bu.")
    print(f"    · ⚠ Kayma ölçümü $59-513 nominali kapsıyor. Bakiye $2000'i geçince")
    print(f"      nominal o aralığın ÜSTÜNE çıkar; orada VERİMİZ YOK.")
    print(f"{'=' * 88}\n")


if __name__ == "__main__":
    main()
