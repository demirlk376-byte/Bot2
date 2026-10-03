# REJIM_V7 — önceden kayıt (2026-10-03, sonuçlardan ÖNCE)

## Soru
Paket (günlük T1 + 4h H4_N180_X5_E10, ikisi de dondurulmuş), "kötü piyasada" yeni long açmayı
kendiliğinden durdurursa düşüş azalır ve kâr korunur mu?

## Rejim anahtarları
Ders kitabı eşikleri, ayarlanmaz. Her mum kapanışında SON TAMAMLANMIŞ günün değeri kullanılır.
Anahtar kapalıyken yalnız YENİ long girişi engellenir; açık pozisyonlar kendi stopuyla yönetilir.

| kod | kural |
|---|---|
| R0 | anahtar yok (taban) |
| R1 | ETH günlük kapanışı > ETH SMA200 |
| R2 | genişlik: kümedeki coinlerin (SMA200 hesaplanabilenler) en az %50'si kendi SMA200 üstünde |

## Veri ve dönem
- **Kümeler:**
  - eski 12 coin: günlük `research_data/trend_takip_v1/veri`, 4h `veri/trend4h`;
  - yeni 24 coin: günlük `yeni_coin_v5`, 4h `veri/trend4h`.
- **Referanslar:** ETH her iki küme için eski kümenin günlük ETH verisi. R2 genişliği her kümenin
  kendi günlük verisinden hesaplanır.
- **Dönem:** [2021-01-01, 2025-08-08). FİNAL kapalı.
- **Maliyet ve risk:** V5/V6 ile aynı.

## Karar kuralı
Rk "benimsenir", ancak İKİ kümede de (eski ve yeni) paket için şu üçü birden sağlanırsa:
- MDD < R0 MDD,
- toplam getiri ≥ 0.85 × R0,
- 2022 yılı net kârı ≥ R0'ın 2022 net kârı.

Yeni küme bu sorunun temiz sınavıdır. Eski kümede ETH200 özelliği V1 kaybeden analizinde bakılmıştı.
Modül bazında sonuçlar teşhis olarak raporlanır. Sonuçtan sonra eşik ya da kural değiştirilmez.
