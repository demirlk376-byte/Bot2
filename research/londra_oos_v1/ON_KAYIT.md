# ChatGPT'nin "Londra kırılımı" planı — DIŞ-ÖRNEKLEM testi — ÖN KAYIT (2026-10-25, veri inmeden ve sonuçlardan ÖNCE)

Kaynak: kullanıcının paylaştığı ChatGPT çalışması (Ocak 2023 – Eylül 2026 Binance verisi). ChatGPT'nin kendi ifadesi:
"sonuçları gördükten sonra seçtiğim plan, doğrulanmış kazanan değildir"; 2025–2026'da 84 işlem, toplam +%0.075 hesap
getirisi, kayma artınca negatif. ChatGPT'nin HİÇ GÖRMEDİĞİ dönem: 2020–2022. Plan burada BİREBİR, o dönemde sınanır.

## Veri (`veri/londra` dalı, data.binance.vision)
`BTC_spot_1h.csv` (spot BTCUSDT 1h, taker_buy_volume dahil) · `BTC_fut_5m.csv.gz` (vadeli BTCUSDT 5m) ·
`scratchpad/btc_veri/veri/BTC_fut_1h.csv` (vadeli 1h) ve `BTC_funding.csv`.

## Kurallar (ChatGPT'nin 5 maddesi; belirsizlikleri bizim sabit çözümümüz [köşeli parantez])
1. Asya aralığı: Türkiye 03:00–09:00 = UTC 00:00–06:00 → vadeli 1h mumları açılışı 00:00…05:00 UTC; tepe = en yüksek,
   dip = en düşük.
2. Değerlendirme: Londra yerel saatiyle (Europe/London, yaz saati dahil) KAPANIŞI 08:00, 09:00, 10:00 ve 11:00 olan
   vadeli 1h mumlar. [Günde en fazla bir işlem: koşulları sağlayan İLK mum.]
3. LONG: kapanış > Asya tepesi VE hacim ≥ 1.5 × [aynı UTC saatinin önceki 20 gündeki vadeli hacim medyanı] VE kapanış >
   EMA168 (vadeli 1h kapanış) VE son 3 saatte spot agresif alış üstünlüğü [sinyal mumu ve önceki 2 mumda Σ spot
   taker_buy_volume / Σ spot volume > 0.5]. SHORT: kapanış < Asya dibi, aynı hacim, kapanış < EMA168, oran < 0.5.
4. Giriş: kapanıştan 5 dakika sonra [kapanış+5dk'da başlayan vadeli 5m mumun açılışı]. Stop: sinyal kapanışından
   1.5 × ATR24 [saatlik, TR'nin son 24 mumluk basit ortalaması, sinyal mumu dahil] uzaklıkta. Hedef: giriş ± 2 × |giriş −
   stop|. En fazla 12 saat [giriş+12s'deki 5m mumun açılışında çıkış]. 5m mumlarda tarama; aynı mumda stop ve hedef →
   STOP. [Giriş anında fiyat stopun ötesindeyse işlem yok, sayılır.]
5. Risk %0.5, tek pozisyon.
Maliyet: NORMAL 9 bp, STRESS 21 bp gidiş-dönüş (btc_hafta_v1 ile aynı); funding giriş < s ≤ çıkış, long öder.
R = (yön × (çıkış/giriş − 1) + funding − maliyet) / (|giriş − stop| / giriş).

## Dönemler
DIŞ-ÖRNEKLEM (karar): sinyal günü 2020-03-01 → 2022-12-31. İÇ-ÖRNEKLEM (yalnız yeniden üretim / karşılaştırma):
2023-01-01 → 2026-09-30 ve ayrıca 2025-01-01 → 2026-09-30 (ChatGPT: 84 işlem, +%0.075).

## Ölçüt (değiştirilmeyecek)
**TUTTU** ⇔ DIŞ-ÖRNEKLEMDE NORMAL ve STRESS ort R > 0 VE haftalık blok bootstrap (10 000, `default_rng(20261025)`)
%2.5 persentil > 0 VE n ≥ 100. Aksi halde ELENDİ. Kâğıt üzerinde izleme ancak TUTTU ise önerilir.
Ek (karar dışı): "olağandışı hacimden sonra 6 saatlik aralık %25–33 daha geniş, yön yok" bulgusu dış-örneklemde
betimsel olarak yeniden ölçülür (aralık oranı ve 6 saat sonra yukarıda olma oranı).
Sonuç görüldükten sonra kural çözümleri, dönem, maliyet ve ölçüt değiştirilmez.

---
## SONUÇ (2026-10-25) — ELENDİ
İki kör uygulama + denetçinin üçüncü motoru 472 işlemde birebir aynı; 6 işlem elle, kesme testi (gelecek veri yok),
DST, hacim medyanı, spot boşlukları doğru. Düzeltme gerekmedi.

| dönem | n | ort R NORMAL / STRESS | hesap (%0.5 risk) NORMAL / STRESS | alt sınır | hüküm |
|---|---|---|---|---|---|
| dış-örneklem 2020-03 → 2022-12 | 204 | +0.065 / −0.028 | +%6.6 / −%2.9 | −0.085 | ELENDİ |
| iç 2023-01 → 2026-09 | 268 | +0.035 / −0.099 | +%4.6 / −%13.2 | — | — |
| iç 2025-01 → 2026-09 | 133 | +0.013 / −0.128 | +%0.8 / −%8.5 | — | (ChatGPT: 84 işlem, +%0.075) |
Yıl yıl NORMAL ort R: 2020 +0.14 · 2021 −0.01 · 2022 +0.10 · 2023 −0.22 · 2024 +0.30 · 2025 +0.09 · 2026 −0.08.
Her dönemde normal maliyette sıfıra yakın artı, kayma biraz artınca eksi — ChatGPT'nin kendi bulgusuyla aynı tablo.
ChatGPT'nin işlem sayısı yazdığı kurallardan yeniden üretilemedi (133 vs 84; bilinmeyen ayrıntılar).
Hacim bulgusu dış-örneklemde DOĞRULANDI (karar dışı): yüksek hacimden sonra 6 saatlik aralık 1.49 kat geniş (iddia
1.25–1.33), yön yok (6 saat sonra yukarıda %51.7 vs %51.0; hacim mumunun yönünde devam %48.2).
