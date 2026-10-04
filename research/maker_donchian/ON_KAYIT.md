# Donchian maker giriş testi — ÖN KAYIT (sonuçlar görülmeden yazıldı, 2026-10-04)

## Soru
`DONCHIAN_MAKER_ENTRY=true` donchian girişlerini piyasa emrine göre UCUZLATIYOR mu?

## Canlı mekanizma (execution.py / exchange.py okundu)
- Limit fiyatı L = sinyal kapanışı (`intended_entry`), post-only, süre 45 sn, 3 sn yoklama.
- Post-only reddedilirse (limit piyasayı kesiyorsa) → hemen piyasa emri.
- 45 sn'de dolmazsa iptal → piyasa emri (yedek). Hiçbir işlem atlanmaz.
- SL/TP sinyal kapanışına ATR ile çapalı → işlem kümesi iki kolda AYNI; fark yalnız giriş fiyatı
  ve giriş ücreti. Bu yüzden ölçü = işlem başı giriş maliyeti farkı (seçim yanlılığı yok).

## Veri
Binance USDⓈ-M aggTrades (kamu arşivi), ikizin 413 donchian sinyali (`sinyaller.csv`, 7 coin,
2023-05 → 2026-07), her sinyal için [t−60 sn, t+300 sn] işlemleri. t = 4h mum kapanışı.

## Model (her sinyal, long için; short ayna)
- t0 = t + GECIKME (emrin borsaya ulaştığı an). P(x) = x anındaki son işlem fiyatı.
- PİYASA kolu: giriş = P(t0) × (1 + Y) , ücret 1 bp.  (Y = yarım-spread/etki)
- MAKER kolu:
  - P(t0) < L → post-only reddedilir → PİYASA kolu ile aynı.
  - aksi halde limit L'de bekler; [t0, t0+45+3 sn] içinde işlem fiyatı **< L** (kesin geçiş;
    L'ye dokunmak yetmez — kuyruk önceliği bilinmiyor) → giriş L, ücret 0.
  - dolmazsa giriş = P(t0+48 sn) × (1 + Y), ücret 1 bp.
- Fark Δ = PİYASA maliyeti − MAKER maliyeti (bp, L'ye göre). Δ > 0 → maker kazandırır.

## Senaryolar (önceden sabit)
- TABAN: GECIKME 75 sn, Y 1 bp.
- MUHAFAZAKÂR: GECIKME 120 sn, Y 0.5 bp (maker'ın avantajı küçülür), dolum için L'nin
  0.5 bp altından işlem gerekir.

## Karar kuralı (değiştirilmeyecek)
- İstatistik: işlem başı ortalama Δ; %95 aralık = haftalık blok bootstrap (10 000 tekrar).
- **AÇIK KALSIN**: TABAN'da ortalama Δ > 0 ve %95 alt sınır > 0, VE MUHAFAZAKÂR'da ortalama Δ > 0.
- **KAPAT**: TABAN'da ortalama Δ ≤ 0.
- Arada kalırsa: **KAPAT** (sadelik; kanıt yetersiz).
- Ek rapor (karar dışı): dolum oranı, coin kırılımı, yıl kırılımı, hesaba yıllık etki tahmini.

---
## SONUÇ (2026-10-04, veri: veri/maker1 dbe7dfb, 413/413 sinyal, 2.39M aggTrade) — `sonuc.txt`
- Akıl kontrolü: Binance kapanışı ile L farkı medyan 1.1 bp → sinyal fiyatları doğru eşleşiyor.
- TABAN: Δ ort **−0.98 bp** [%95 −3.00, +0.98]; limitte dolum yalnız **%17** (72/413), post-only reddi
  138, 45 sn yedek 203. Piyasa maliyeti ort +10.3 bp (canlı ölçülen +15.3 bp ile tutarlı).
- MUHAFAZAKÂR: Δ ort +0.63 bp [−1.35, +2.81], dolum %16.
- **ÖN KAYITLI KARAR: KAPAT.** Kırılımda fiyat limite nadiren geri dönüyor; dönmediğinde 45 sn bekleme
  kazancı geri yiyor. Net etki sıfır civarı (±2 bp ≈ ±0.005 R/işlem), işaret belirsiz.
