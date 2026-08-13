"""
risk_kademe.py — "belli bir işlem sayısından sonra riski artırırsak ne olur?"

İKİ AYRI SORU, İKİSİ DE CEVAPLANIYOR:

[A] TETİK ULAŞILABİLİR Mİ? DURUM.md'ye şu ön-kayıtlı kural yazıldı:
      "en az 200 kapanmış işlem VE canlı ortalama R'nin alt güven sınırı 0.15'in üstünde"
    Bu iki şartın BİRLİKTE sağlanabilir olup olmadığı HİÇ HESAPLANMADI.
    Gerekli n: ort_R − 1.96·(σ_R/√n) > 0.15  →  n > (1.96·σ_R / (ort_R − 0.15))²
    σ_R ankordan ÖLÇÜLÜYOR (varsayılmıyor). Cevap 200'den çok büyükse kural
    ULAŞILAMAZ demektir ve düzeltilmesi gerekir.

[B] KADEMELİ RİSK — kademe gerçekten olursa projeksiyon nasıl değişir?
    Simülasyon: RISK_SCALE 1.125 ile başla, tetik ayında X'e çık.
    Karşılaştırılan: sabit 1.125 (taban) · kademe 1.25 · kademe 1.50
    Ölçülen: 12/24 ay bakiye dağılımı, aylık kâr, EN KÖTÜ AY, zarar olasılığı.

⚠️ KADEME KÂRI DA RİSKİ DE BÜYÜTÜR. pw_risk_scale.py ölçmüştü: RISK_SCALE 2x
   kârı %56 artırıyor ama en kötü ayı %86 kötüleştiriyor. Kademeli uygulama bunu
   DEĞİŞTİRMEZ — yalnız GEÇ başlatır. Bu betik "geç başlatmak ne kazandırıyor"u ölçer.

⚠️ Aylık getiri serisi her ölçek için AYRI hesaplanıyor (doğrusal ölçekleme YOK):
   eff = min(RISKF·ölçek, CAP·sl%) — CAP bağladığında ilişki doğrusal değildir.

Kullanım:  py risk_kademe.py local
"""
import sys

import numpy as np
import pandas as pd

import deployed_backtest as A
import sim_katki as S

BAS, KATKI = 203.0, 100.0
CAP = 1.50
CANLI_R = 0.1096
AYLIK_ISLEM = 31.0          # canlı hız: ankorun 40/ay × 0.77 (hiz_analiz ölçümü)
YOL = 20000


def aylik(taken, kaydirma, olcek):
    """Aylık getiri ORANI, verilen risk ölçeğinde. Doğrusal ölçekleme YOK.

    ⚠️ DÜZELTİLDİ: ilk sürüm `A.RISKF * olcek` yazıyordu. Ama A.RISKF = 0.02 × 1.125
    yani RISK_SCALE'i ZATEN İÇERİYOR → 1.125 İKİ KEZ uygulanıyordu ve "sabit 1.125
    (bugün)" satırı aslında 1.266'yı simüle ediyordu. Doğrusu ham tabandan çarpmak."""
    r = np.array([R for _, R, _ in taken]) + kaydirma
    sp = np.array([s for _, _, s in taken])
    eff = np.minimum(0.02 * olcek, CAP * sp)          # 0.02 = RISK_SCALE'siz taban
    pnl = r * eff
    ay = [pd.Timestamp(x).tz_localize(None).to_period("M") for x, _, _ in taken]
    return pd.Series(pnl).groupby(ay).sum().values


def sim(g1, g2, gecis_ay, ay, yol=YOL, tohum=20260812):
    """g1 serisiyle başla, gecis_ay'dan itibaren g2'ye geç."""
    rng = np.random.default_rng(tohum)
    i1 = rng.integers(0, len(g1), size=(yol, ay))
    i2 = rng.integers(0, len(g2), size=(yol, ay))
    bak = np.full(yol, BAS, dtype=float)
    enk = np.zeros(yol)
    for a in range(ay):
        g = g2[i2[:, a]] if a >= gecis_ay else g1[i1[:, a]]
        bak = np.maximum((bak + KATKI) * (1.0 + g), 0.0)
        enk = np.minimum(enk, g)
    return bak, enk


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    taken = S.islemler(source)
    ok = len(taken) == 1579
    print(f"\n{'=' * 100}")
    print("=== KADEMELİ RİSK: belli bir işlem sayısından sonra artırsak? ===")
    print(f"  KONTROL: {len(taken)} işlem → {'✓' if ok else '✗ SAPMA'}")
    if not ok:
        return

    r_ham = np.array([R for _, R, _ in taken])
    sigma = float(r_ham.std(ddof=1))
    print(f"  ankor ort R {r_ham.mean():.4f} · σ_R {sigma:.4f} (ÖLÇÜLDÜ, varsayılmadı)")

    # ── [A] TETİK ULAŞILABİLİR Mİ ──
    print(f"\n[A] ÖN-KAYITLI TETİK ULAŞILABİLİR Mİ?")
    print(f"    kural: alt güven sınırı (ort_R − 1.96·σ/√n) > 0.15")
    print(f"\n    {'varsayılan gerçek ort R':<26s} {'gerekli n':>10s} {'canlı hızla süre':>18s}")
    for gercek in (0.237, 0.20, 0.18, 0.16, CANLI_R):
        if gercek <= 0.15:
            print(f"    {gercek:<26.4f} {'ASLA':>10s} {'—':>18s}"
                  f"   ← ort R zaten 0.15'in altında")
            continue
        n = (1.96 * sigma / (gercek - 0.15)) ** 2
        ay_ = n / AYLIK_ISLEM
        print(f"    {gercek:<26.4f} {n:>10.0f} {ay_:>15.1f} ay")
    n200_lo = 0.237 - 1.96 * sigma / np.sqrt(200)
    print(f"\n    n=200'de, gerçek ort R ankor kadar (0.237) olsa bile:")
    print(f"      alt sınır = 0.237 − 1.96·{sigma:.3f}/√200 = {n200_lo:+.4f}")
    print(f"      → 0.15'in {'ÜSTÜNDE' if n200_lo > 0.15 else 'ALTINDA'}. "
          f"{'Kural tutarlı.' if n200_lo > 0.15 else 'KURAL ULAŞILAMAZ — düzeltilmeli.'}")

    # ── [B] KADEMELİ RİSK PROJEKSİYONU ──
    kay = CANLI_R - r_ham.mean()          # canlı edge senaryosu
    g_taban = aylik(taken, kay, 1.125)
    seri = {1.125: g_taban, 1.25: aylik(taken, kay, 1.25), 1.50: aylik(taken, kay, 1.50)}
    print(f"\n[B] KADEMELİ RİSK — canlı edge senaryosu, ayda ${KATKI:.0f} katkı")
    print(f"    {'ölçek':>7s} {'ort eff':>9s} {'CAP bağlı%':>11s} {'ay ORT%':>9s} "
          f"{'ay MEDYAN%':>11s}")
    for k_, v in seri.items():
        e_ = np.minimum(0.02 * k_, CAP * np.array([s for _, _, s in taken]))
        print(f"    {k_:>7.3f} {e_.mean():>9.5f} "
              f"{(e_ < 0.02*k_-1e-12).mean()*100:>10.0f}% {v.mean()*100:>8.2f}% "
              f"{np.median(v)*100:>10.2f}%")
    # MEKANİZMA: ölçek artınca ORTALAMA yükselirken MEDYAN düşüyor. Sebep CAP.
    r_ = np.array([R for _, R, _ in taken]); sp_ = np.array([s for _, _, s in taken])
    for k_ in (1.125, 1.50):
        bagli = (CAP * sp_) < (0.02 * k_)
        if bagli.any() and (~bagli).any():
            print(f"    ölçek {k_}: CAP'e takılanların ort R {r_[bagli].mean():+.4f} · "
                  f"takılmayanların {r_[~bagli].mean():+.4f} "
                  f"(takılan {bagli.sum()} işlem)")
    print(f"    → Ölçek artınca CAP daha çok işlemi kesiyor; kesilenler farklı kalitede")
    print(f"      ise bileşim değişiyor ve MEDYAN ay ORTALAMA ile aynı yönde gitmiyor.")

    for ay in (12, 24):
        yat = BAS + KATKI * ay
        print(f"\n  ── {ay} AY (yatırılan ${yat:.0f}) ──")
        print(f"    {'yapılandırma':<28s} {'%10':>8s} {'MEDYAN':>9s} {'%90':>9s} "
              f"{'ay kârı(med)':>12s} {'en kötü ay':>11s} {'zarar':>6s}")
        for ad, olcek, gec in (("sabit 1.125 (bugün)", 1.125, 0),
                               ("6. aydan sonra 1.25", 1.25, 6),
                               ("6. aydan sonra 1.50", 1.50, 6),
                               ("12. aydan sonra 1.25", 1.25, 12),
                               ("12. aydan sonra 1.50", 1.50, 12)):
            if gec >= ay and gec > 0:
                continue
            bak, enk = sim(g_taban, seri[olcek], gec, ay)
            p = np.percentile(bak, [10, 50, 90])
            med_ay = float(np.median(seri[olcek] if gec < ay else g_taban))
            print(f"    {ad:<28s} {p[0]:>8.0f} {p[1]:>9.0f} {p[2]:>9.0f} "
                  f"{p[1]*med_ay:>12.0f} {np.median(enk)*100:>10.1f}% "
                  f"{(bak < yat).mean()*100:>5.0f}%")

    print(f"\n{'=' * 100}\n=== NASIL OKUNUR ===")
    print("  · 'en kötü ay' = o yolda görülen en kötü ayın MEDYANI. Kademe bunu büyütür.")
    print("  · Kademe kârı da riski de büyütür; GEÇ başlatmak yalnız küçük bakiyede")
    print("    korunmayı sağlar, takası değiştirmez (pw_risk_scale: 2x kâr +%56, kuyruk +%86).")
    print("  · [A] tetiği ulaşılamaz çıkarsa kademe zaten HİÇ tetiklenmez — o zaman")
    print("    [B]'deki satırlar 'kural değişirse ne olur' senaryosudur, plan değil.")


if __name__ == "__main__":
    main()
