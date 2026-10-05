# Donchian "ters küme" filtresi — ÖN KAYIT (2026-10-05, test sonuçlarından önce)

Hipotez (donchian_kume sonucundan TÜRETİLDİ — o veride sınanamaz): aynı 4h kapanışında ≥K coinde
donchian sinyali varsa o mumdaki HİÇBİR işleme girilmez; diğerleri aynen.

## Test verisi (bağımsız, hiç kullanılmamış dönem)
- Aynı 12 coin, aynı ikiz (canlı kodun birebir tekrarı), gerçek maliyet ayarları (giriş kayması
  15.85bp, çıkış 0.24bp, komisyon 2.5bp, funding açık — Binance funding 2020→, squeeze kapalı).
- Dönem: 2020-01 → 2023-04-06 girişleri (ikizin bugüne kadarki penceresinden ÖNCE). Fiyat: Binance
  USDⓈ-M 1h (canlı ikiz verisi MEXC; kaynak farkı raporlanır).

## Varyantlar
TABAN (tüm donchian) · ATLA3 (küme ≥3 atlanır) · ATLA4 (küme ≥4 atlanır). İkiz işlemlerinden süzülür.

## Ölçüt (değiştirilmeyecek)
Bir varyant İYİ ⇔ test döneminde (1) ΣR TABAN'dan yüksek, (2) %3.5 risk bileşik hesapta ay sonu en büyük
düşüş TABAN'dan kötü değil, (3) atlanan işlemlerin ort R'si < 0 ve haftalık blok bootstrap (10 000,
seed 20261005) %95 üst sınırı < +0.10R. Üçü birden yoksa ELENDİ.

---
## SONUÇ (ters_sonuc.txt; eski dönem ikizi 2020-02 → 2023-04, gerçek maliyet, 444 donchian işlemi)
- Küme 4+: 61 işlem, ort **−0.284R**; küme 3: +0.024R; küme 1: +0.224R; küme 2: +0.247R.
- ATLA3: ΣR 61.1 → 77.3, maxDD %48.5 → %38.7, ama atlananların üst sınırı +0.19R → **ELENDİ**.
- ATLA4: ΣR 61.1 → 78.4, maxDD %48.5 → %37.7, atlananlar −0.284R, üst sınır +0.0998R → ön kayıtlı
  kurala göre **İYİ (sınırda)**.
- Ancak 2023-04 → 2026-07 döneminde (keşif) ATLA4 TERS yönde: ΣR 91.1 → 87.0, maxDD %34.4 → %39.2
  (küme 4+ orada +0.071R).
- Birleşik 2020–2026: küme 4+ 118 işlem, ort ≈ −0.11R; ATLA4 ΣR 152.2 → 165.4 (+%9).
## Hüküm
Ön kayıtlı test geçti ama etki iki dönemde aynı yönde değil. Beklenen kazanç küçük (~+0.03R/işlem) ve
işareti dönemden döneme değişiyor. Canlıya ALINMAZ; kullanıcı isterse karar ona bırakılır.
