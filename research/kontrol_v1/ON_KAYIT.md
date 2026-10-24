# Test düzeneği kontrolü (pozitif / negatif kontrol) — ÖN KAYIT (2026-10-24, sonuçlardan ÖNCE)

Kullanıcı sorusu: "Uygun şekilde denememişizdir belki." SMC/ICT, mean reversion/range, formasyonlar ve gün içi
stratejiler elendi. Soru: elemeyi yapan test makineleri gerçek bir kenarı GÖREBİLİYOR mu (yanlış negatif), ve
kenar olmayan yerde sahte kenar ÜRETMİYOR mu (yanlış pozitif)? Bilinen cevaplı sinyaller makinelere verilir.

## Makineler (kodları değiştirilmez; kopyası scratchpad'de, yalnız sinyal YÖNÜ değiştirilir)
- **M1 SMC/ICT**: `research/liquidity_sweep_v1` (5m, 12 coin, sweep + MSS/FVG kurulumları).
- **M2 Formasyon / dönüş**: `research/mum_formasyon_v1/analiz.py` (pin bar, yutan, yıldız, iç mum, üç asker,
  marubozu; 4h/1D; eski12 seçim, yeni26 sınav).
- **M3 Gün içi / scalping**: `research/gun_ici_v1/analiz.py` (F1/F2 funding saati, C1 5m çöküş dönüşü).
Her makinenin kendi giriş zamanı, stop/hedef/süre kuralları, maliyeti (NORMAL), R/bp tanımı, bootstrap ve alt
sınır yöntemi AYNEN kullanılır (kendi ON_KAYIT'ındaki sınav/doğrulama kümesi ve istatistiği).

## Kontroller (her makinede, orijinal sinyallerin AYNI zaman ve coinlerinde)
- **NEG (negatif kontrol)**: her sinyalin yönü yazı-tura (`numpy.random.default_rng(20261024)`).
- **POS60 / POS55 (pozitif kontrol, bilerek geleceğe bakan)**: yön = sign(makinenin azami tutma süresinin sonundaki
  kapanış − giriş fiyatı); %60 (POS60) / %55 (POS55) olasılıkla bu yön, aksi halde ters (aynı seed). Eşitse yazı-tura.
- **INV (bilgi)**: orijinal yönün tersi.
Yön değişen işlemde stop ve hedef uzaklıkları giriş etrafında aynalanır (mesafeler aynı kalır).

## Ölçüt (değiştirilmeyecek)
Bir makine **SAĞLAM** ⇔ (1) NEG: maliyetsiz (brüt) ortalama 0'dan en fazla 3 standart hata uzakta VE NORMAL alt
sınır ≤ 0 (sahte kenar yok); (2) POS60: NORMAL ortalama > 0 VE makinenin kendi alt sınırı > 0 (gerçek kenarı
görüyor). POS55 ve INV karar dışı raporlanır (tespit gücü, simetri).
**DÜZENEK SAĞLAM** ⇔ üç makine de SAĞLAM. Bir makine sağlam değilse o makineyle elenen çalışmalar yeniden açılır.
Doğal pozitif kontrol (karar dışı, rapor): aynı tür ikiz/maliyet altyapısının donchian için verdiği +0.26R'nin
canlıda +0.25…+0.29R ölçülmesi.
Sonuç görüldükten sonra olasılıklar, seed, ölçüt ve makine listesi değiştirilmez.
