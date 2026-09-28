# SQUEEZE_COST_AWARE_ALLOCATION: sonuç REJECTED

**Soru:** Yeni canlı squeeze maliyet ölçümü altında, Donchian'dan squeeze'e risk payı aktarmak
(Donchian ×0.75, squeeze ×1.50, BB ×1.00) toplam riski artırmadan net büyümeyi veya kâr geri
vermeyi iyileştiriyor mu?

**Hayır.**
- TEST'te B, A'ya göre büyümeyi artırmıyor (−%3.4 göreli) ve maxDD'yi yalnız 2.7 puan azaltıyor.
- TRAIN'de belirgin şekilde bozuluyor: CAGR −%31 göreli, maxDD +13 puan.
- 15.85bp stresinde de sonuç aynı.
- Önceden sabit kurallar gereği aday **REJECTED**. Eşik değiştirilerek kurtarılmaya çalışılmadı.

Bu, eski "kol ağırlığı" denemesinin (RESEARCH_LEDGER 2026-09-09, çürütüldü) tekrarı değil. Fark,
yeni squeeze maliyet verisi altında risk tahsisinin sınanması. Sonuç yine olumsuz.

## Yeniden çalıştırma

```
# tek koşu (repo kökünden; ~23 dk); örnek: B, squeeze 5.13bp, funding düzeltmeli
AD=B5 REPLAY_DB=/tmp/B5.db PAPER_SLIP_GIRIS_BP=15.85 PAPER_SLIP_CIKIS_BP=0.24 PAPER_FUNDING=true \
DONCHIAN_MAKER_ENTRY=false SQZ_SLIP_BP=5.13 FIX_FUNDING=1 DONCHIAN_RISK_PCT=0.015 SQUEEZE_RISK_PCT=0.03 \
  python3 arastirma/squeeze_cost_aware_allocation/sq_kos.py      # cwd = koşu klasörü
# analiz (koşu klasörleri SQCA_DIR altında)
SQCA_DIR=<koşu kökü> python3 arastirma/squeeze_cost_aware_allocation/analiz.py
# regresyon testleri
python3 -m pytest -q arastirma/squeeze_cost_aware_allocation/test_codex_bulgulari.py
```

**Koşular:**

| koşu | ayar |
|---|---|
| R0 | referans davranışı (funding yok) |
| A5 / B5 / C5 | squeeze 5.13bp |
| A15 / B15 / C15 | squeeze 15.85bp |
| C5, C15 | ek olarak `RISK_SCALE=1.713501` |

- Funding düzeltmesi (`FIX_FUNDING=1`) R0 dışındaki bütün koşularda **aynı**.
- `karsilastirma_tablosu.csv`, `sonuclar.json`: bütün metrikler.

## 1. Dayanak

- **Referans yeniden üretildi:** R0 **936/936 birebir** (strategy_scores dahil bütün alanlar).
- **Squeeze maliyeti:** `SQUEEZE_EXECUTION_AUDIT.md`'de canlı taker n=19, ort +1.49bp, %95 GA
  [−2.52, +5.13] (hüküm D, n<20).
  - Ana senaryo **5.13bp**. Bu, ortalamanın GA üst ucu; gelecekteki her dolum için güvenli üst
    sınır değildir.
  - Küçük örneklem kesin kalibrasyon sayılmadı.
- **Diğer maliyetler sabit:** Diğer girişler 15.85bp, çıkış kayması 0.24bp, taker 1bp, BB maker.
- **Aynı maliyet:** A, B ve C aynı maliyet modelini kullanıyor.

## 2. Codex bulguları ve yeni bulgu (regresyon testleri: `test_codex_bulgulari.py`, 4/4 geçiyor)

| # | bulgu | etki | araştırmada |
|---|---|---|---|
| 1 | `exchange._simdi_ts` içindeki yerel `from datetime import datetime`, ikizin sanal saat yamasını atlıyor | Paper funding penceresi duvar saatinden (~0 sn) → ikizde funding **sıfır** | sanal saatle değiştirildi (yalnız süreç belleğinde) |
| 2 | Canlı mutabakat (`main.py`) gerçek çıkış komisyonunu `_close_position_internal`'a aktarmıyor; içeride 1bp yeniden hesaplanıyor | yalnız **canlı** defter; paper ikiz bu yola girmiyor | belgelendi, düzeltilmedi (production) |
| 3 | **(yeni)** `exchange._funding_toplami` zaman damgasını `astype("int64")/1e9` ile çeviriyor; pandas 3'te seri `datetime64[us]`, değerler 1000 kat küçük | #1 düzeltilse bile funding **sıfır** | funding önbelleği doğru birimle dolduruldu |

**Funding kapsamı:**
- Bu çalışmadaki A/B/C koşularında funding **var**. Kaynak `data/{COIN}_funding_bnc.csv`
  (Binance oranları, MEXC vekili; `exchange.py` notu), yön duyarlı.
- Eski 936'lık referansta ve daha önceki bütün ikiz sonuçlarında funding **yok**.
- Etkisi: A15 ile R0 aynı ayarda. TEST CAGR %221.3 → %212.6, TEST funding maliyeti ≈ $27.8k.
- Eski referans sessizce değiştirilmedi; R0 ayrı tutuldu.

## 3. Risk eşleme (TEST'e bakmadan donduruldu)

- **TRAIN saatlik getiri std'si:** σ_A = 0.011271, σ_B = 0.011036.
- **B:** σ_B < σ_A → k_B = 1, küçültülmedi.
- **C:** k_C = σ_B/σ_A = **0.97914** → RISK_SCALE 1.75 → 1.713501, tek atış.
- **Kalan fark:** σ_C = 0.011087, σ_B'nin +%0.46 üstünde (tolerans raporlandı, iterasyon yok).
- **Gerçekleşen kol riski** (işlem riski / giriş anındaki hesap değeri, TEST):

| kol | A5 | B5 | C5 |
|---|---|---|---|
| Donchian | %3.52 | %2.64 | %3.44 |
| squeeze | %3.46 | **%4.70** | %3.39 |
| BB | %3.51 | %3.51 | %3.44 |

- **CAP squeeze'i kısıyor:** Squeeze hedefi 5.25% iken gerçekleşen 4.70% (TEST), 4.03%
  (TRAIN).
  - CAP bağlayıcı olan squeeze işlemleri: B5'te TRAIN 157/222, TEST 62/146.
  - A5'te: TRAIN 79/221, TEST 20/146.
  - CAP ve kaldıraç artırılmadı.

## 4. Karşılaştırma (saatlik hesap değeri; ekonomik çıkış işareti; komisyon bir kez)

**Ana maliyet (squeeze 5.13bp):**

| | pencere | CAGR | maxDD | en kötü ay | sualtı (g) | PGR | maliyet $ | işlem | marjin red. |
|---|---|---|---|---|---|---|---|---|---|
| **A5** | TRAIN | %467.9 | %39.4 | −20.7% | 617 | 0.733 | 45,445 | 538 | 3 (tüm) |
| **B5** | TRAIN | %321.0 | **%52.7** | −25.5% | 612 | 0.761 | 28,285 | 539 | 2 |
| **C5** | TRAIN | %454.2 | %38.5 | −20.2% | 617 | 0.732 | 43,303 | 540 | 1 |
| **A5** | TEST | %269.6 | %46.2 | −25.7% | 548 | 0.743 | 495,841 | 397 | |
| **B5** | TEST | %260.5 | %43.6 | −25.0% | 550 | 0.744 | 281,740 | 397 | |
| **C5** | TEST | %263.9 | %45.6 | −25.3% | 548 | 0.741 | 456,694 | 397 | |

**Stres (squeeze 15.85bp):**

| | pencere | CAGR | maxDD | en kötü ay | PGR |
|---|---|---|---|---|---|
| A15 | TRAIN | %327.1 | %42.6 | −22.7% | 0.735 |
| B15 | TRAIN | %208.2 | **%56.5** | −27.9% | 0.796 |
| C15 | TRAIN | %324.0 | %41.8 | −22.2% | 0.732 |
| A15 | TEST | %212.6 | %47.5 | −26.8% | 0.764 |
| B15 | TEST | %190.2 | %45.4 | −26.3% | 0.758 |
| C15 | TEST | %208.7 | %46.9 | −26.4% | 0.762 |

**Maliyet sütunları:**
- Maliyet = giriş+çıkış ücreti + giriş kayması + ödenen funding (tam liste CSV'de).
- $ tutarları hesap büyüklüğüyle ölçeklenir, doğrudan kıyaslanmamalı.

**İşlem sayıları:** A5 935, C5 937, referans 936. Bu fark, farklı bakiye yolunun marjin ve
koltuk kararlarını birkaç yerde değiştirmesinden (yol bağımlılığı).

**Uyarı (maliyet ile tahsis karışmasın):**
- A15 → A5 farkı (TEST CAGR %212.6 → %269.6) yalnız **maliyet varsayımı değişikliğidir**.
- Bu bir bot iyileştirmesi değil.
- Adayın katkısı yalnız aynı maliyet altında B − A farkıdır.

## 5. Önceden sabit karar (analiz.py docstring'inde, sonuçtan önce)

| koşul | ana (5.13bp) | stres (15.85bp) |
|---|---|---|
| K1a: CAGR_B ≥ 1.10·CAGR_A ve maxDD_B ≤ maxDD_A | ✗ (%260.5 < %296.6) | ✗ |
| K1b: maxDD_B ≤ maxDD_A − 5pp ve CAGR_B ≥ 0.95·CAGR_A | ✗ (−2.7pp; CAGR %96.6) | ✗ (−2.0pp; %89.5) |
| K2: B, risk-eşlenmiş C'yi TEST CAGR/maxDD'de geçer | ✓ (5.98 > 5.79, küçük) | ✗ |
| K3: TRAIN'de ters belirgin bozulma yok | ✗ (CAGR −%31, maxDD +13.3pp) | ✗ |

**Hafta blokları eşleştirilmiş bootstrap** (TEST, yıllık log büyüme farkı, 5000 tekrar):

| fark | ana | stres |
|---|---|---|
| B − A | [−0.43, +0.38] | [−0.48, +0.33] |
| B − C | [−0.40, +0.40] | [−0.46, +0.34] |

Hepsi sıfırı rahatça içeriyor.

**HÜKÜM: REJECTED.** Hem ana maliyette hem stres altında.

- **TEST'e dair uyarı:** Bu TEST dönemi (2025-01 →) önceki çalışmalarda defalarca kullanıldı.
  Temiz dış örneklem değil. Bu sonuç zaten olumsuz olduğu için bu uyarı yalnız kayıt amaçlı.

## 6. Okuma

- **TEST'teki küçük DD düşüşü (−2.7pp)** büyük ölçüde toplam riskin azalmasından geliyor:
  - TEST'te B'nin getirisi C'ye göre biraz daha düşük, maxDD'si ise 2 puan daha iyi; ikisi de
    GA içinde.
  - Bu, eski kol ağırlığı bulgusuyla aynı karakterde: kuyruk satın alınıyor, getiri kazanılmıyor.
- **TRAIN'deki bozulma:** Squeeze'in TRAIN performansı, taşınan riski karşılamıyor.
- **CAP'in etkisi:** CAP, squeeze'e aktarılan riskin önemli kısmını zaten kesiyor (TRAIN 157/222
  işlem). Bu yüzden B, niyet edilen dağılımı tam uygulayamıyor.
- **Maliyet sonucu değiştirmiyor:** Yeni maliyet ölçümü squeeze'i ucuzlatıyor, ama bu A'ya da aynı
  ölçüde yarıyor. Tahsis değişikliğinin kendi katkısı ne ana maliyette ne streste pozitif.

İleri paper-test planı yazılmadı, çünkü sonuç olumsuz. Canlıya bir şey uygulanmadı.
