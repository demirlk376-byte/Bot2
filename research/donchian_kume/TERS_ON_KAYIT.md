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
