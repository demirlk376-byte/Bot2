# Gün içi v1 — mekanizmalı üç hipotez — ÖN KAYIT (2026-10-17, sonuçlardan ÖNCE)

Önceki gün içi denemeler (ICT/SMC, FVG, ORB, Asya, sweep, VWAP) maliyet duvarına takıldı: brüt kenar ~0.
Bu tur yalnız MEKANİZMASI olan, hiç denenmemiş iki aile; önce BRÜT kenar, sonra gerçekçi maliyet.

## Veri
Binance USDⓈ-M 5m (`research_data/liquidity_sweep_v1/veri/binance_5m/<COIN>.npz`: open_time_ms, open, high,
low, close, volume) ve funding (`.../binance_funding/<COIN>.csv`: calc_time ms, last_funding_rate),
12 coin (SOL ETH ADA NEAR BCH XRP DOGE TRX XLM LTC ICP BNB), 2023-01-01 → 2026-09-30.
KEŞİF: 2023-01-01 → 2024-12-31. DOĞRULAMA: 2025-01-01 → 2026-09-30.
Settlement anı T = funding kaydının calc_time'ı 5 dk'ya yuvarlanmış hali (00/08/16 UTC).

## Hipotezler (eşikler sabit, optimizasyon yok)
- **F1 — ödeme öncesi baskı**: f_önceki = bir önceki settlement'ın oranı (T−8s'de tamamen bilinir).
  |f_önceki| ≥ 0.0003 ise: f>0 → T−60dk açılışında SHORT, T'de (T'de başlayan mumun açılışı) kapat; f<0 → LONG.
- **F2 — ödeme sonrası dönüş**: aynı koşul; f>0 → T'de LONG, T+60dk'da kapat; f<0 → SHORT.
- **C1 — 5m çöküş dönüşü**: ATR20(5m) ve hacim medyanı20 yalnız geçmiş mumlardan. Bir 5m mumun getirisi
  ≤ −3·ATR20/önceki kapanış VE hacmi ≥ 3·medyan20 → sonraki mum açılışında LONG; ayna: ≥ +3·ATR VE hacim
  → SHORT. Çıkış: 12 mum (60 dk) sonra açılışta, ya da giriş ∓ 2·ATR20 stop (mum içinde değerse stoptan;
  açılış stopun ötesindeyse açılıştan). Aynı coinde pozisyon açıkken yeni sinyal yok.

## Maliyet (gidiş-dönüş, getiriden düşülür)
NORMAL 10 bp (komisyon 2×2.5 + yarım spread/etki ~2×2.5; sabit zamanlı girişler momentum kovalamaz),
STRESS 21 bp (canlıda ölçülen kırılım giriş kayması 15.85 + 2×2.5 komisyon + 0.24 çıkış).

## İstatistik ve ölçüt (değiştirilmeyecek)
İşlem başı net getiri (bp). Güven aralığı: haftalık blok bootstrap (10 000, seed 20261017), 3 hipotez →
Bonferroni alt sınır = %0.83 persentil.
Bir hipotez **KAZANDI** ⇔ (1) keşif VE doğrulamada STRESS net ort > 0, (2) doğrulamada NORMAL net için
Bonferroni alt sınır > 0, (3) doğrulamada NORMAL net ort > 0 olan coin sayısı ≥ 8/12.
Aksi halde ELENDİ. Rapor: brüt ort bp, işlem sayısı, yıl yıl, coin coin, uzun/kısa ayrımı.
