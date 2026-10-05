# BTC "sağlam boy" öncesi ortak noktalar — ÖN KAYIT (2026-10-05, veri gelmeden ve sonuçlardan önce)

Kullanıcı sorusu: BTC'nin sağlam yükseldiği zamanları belirle, hemen öncesindeki ortak noktaları bul;
BTCDOM'a da bak.

## Tuzak ve önlem
Yalnız yükselişlerin öncesine bakmak, her zaman var olan durumları "ortak nokta" gösterir (temel oran
yanılgısı) ve geçmişe bakarak hikâye kurdurur. Bu yüzden:
1. Her özellik için yükseliş-öncesi sıklığı **tüm günlerin sıklığıyla** karşılaştırılır (lift).
2. Özellikler **keşif** döneminde bulunur, **doğrulama** döneminde dondurulmuş haliyle sınanır.

## Olay tanımı (günlük, Binance spot BTCUSDT kapanışları)
- Etiket: gün t "boy günü" ⇔ max(kapanış[t+1 … t+14]) / kapanış[t] − 1 ≥ **+%15**.
- Olay başlangıcı (liste ve örnekler için): boy günlerinden önceki 14 günde boy günü olmayan ilk gün.
- İstatistikler TÜM günler üzerinden (etiketli/etiketsiz); örtüşme nedeniyle CI ay blok bootstrap ile.

## Özellikler (yalnız t kapanışında bilinen bilgi)
F1 30g getiri · F2 7g getiri · F3 365g zirveden uzaklık · F4 kapanış/SMA200 − 1 ·
F5 14g gerçekleşen oynaklığın önceki 365g içindeki yüzdeliği (sıkışma) · F6 7g/90g hacim oranı ·
F7 RSI14 · F8 7g ortalama funding (2019-09→) · F9 7g OI değişimi (2021-12→) ·
F10 top-trader L/S (hesap sayısı) 7g ort., 90g z-skoru · F11 perakende L/S 7g ort. z ·
F12 taker al/sat hacim oranı 7g ort. · F13 BTCDOM 14g değişim (2021-06→) · F14 BTCDOM/SMA50(gün) − 1 ·
F15 ETH/BTC 14g değişim.

## Dönemler
- Keşif: veri başı → 2023-12-31. Doğrulama: 2024-01-01 → son veri − 14 gün.
- (Türev özellikleri F9–F14 2021-12/2021-06 sonrası; keşifleri daha kısa — raporda belirtilir.)

## Yöntem
- Her özellik keşif döneminin beşte birlik dilimlerine (quintile) bölünür; dilim sınırları keşiften
  dondurulur. Lift = P(boy | dilim) / P(boy) (o dönemin temel oranı).
- Keşifte, en az 60 gün ve en az 15 boy günü içeren dilimler arasında lift'i en yüksek **3 özellik-dilimi**
  doğrulamaya taşınır (en düşük lift'li 3 dilim de "kaçınılacak" olarak taşınır).
- **DOĞRULANDI:** doğrulamada aynı dilimin lift'i, ay blok bootstrap (10 000, seed 20261005) ile
  %95 Bonferroni (6 test → %0.83 alt persentil) alt sınırında > 1 (kaçınılacaklar için üst sınır < 1).
- Ek (karar dışı): olay listesi ve her olayın öncesindeki özellik görüntüsü; BTCDOM yön tablosu.

Sonuç görüldükten sonra eşik (+%15/14g), özellik tanımları, dönemler ve ölçüt DEĞİŞTİRİLMEZ.
