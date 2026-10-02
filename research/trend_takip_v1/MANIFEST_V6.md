# H4_KIRILIM_V6 — önceden kayıt (2026-10-02, 4h verisi inerken, sonuçlardan ÖNCE)

## Soru
Aynı kırılım + takip stopu mantığı 4 saatlik mumda, günlük T1'den daha iyi ya da onun yanında
ek modül olarak değerli mi?

## Veri ve dönem
- **Kaynak:** Binance USDⓈ-M 4h mum ve funding (`veri/trend4h` dalı), MEXC güncel metadata (aynı dal).
  - Metadatası olmayan coin dışlanır.
- **Seçim kümesi:** eski 12 coin (SOL ETH ADA NEAR BCH XRP DOGE TRX XLM LTC ICP BNB).
- **Sınav kümesi:** yeni 26 coin listesi (V5 ile aynı). Bu coinlerin 4h verisine hiç bakılmadı.
- **Dönem:** [2021-01-01, 2025-08-08). FİNAL kapalı.
- **Isınma:** coin listelenmesinden sonra 200 gün.

## Kurallar
Motor aynen (`engine.simulate`, `bar_ms` = 4 saat).
- **Giriş:** 4h kapanış, önceki N mumun tepesinin üstünde → sonraki 4h mumun açılışında long.
- **Stop:** ATR20 (4h mum) × k takip stopu, yalnız lehe taşınır. Mum içinde dokunursa stop fiyatından,
  açılış stopun ötesindeyse açılıştan çıkılır.
- **Erken çıkış:** E10 = 10 GÜN içinde en iyi kapanış +1R görmezse sonraki açılışta çık.
- **Funding:** her 4h mumdaki settlement'lar, o mumun açılış fiyatıyla.
- **Maliyet ve risk:** maliyet NORMAL/STRESS; risk %0.25/işlem; toplam risk tavanı 300 USDT;
  canlı kapılar aynen.

## Varyantlar (8, yalnız long)
`H4_N{60|180}_{X3|X5}_{E0|E10}`
- **N:** 60 mum (10 gün) ya da 180 mum (30 gün).
- **k:** 3 ya da 5.
- **Erken çıkış:** E0 yok, E10 var.

## Seçim (eski 12 coinde)
NORMAL ve STRESS toplam net > 0 ve ortalama R > 0 olan varyantlar arasından en yüksek
getiri / MDD (NORMAL) oranlı TEK varyant seçilir. Hiçbiri yoksa ELENDİ.

## Sınav (yeni coinlerde, seçilen tek varyant)
- **TUTTU:** dört koşulun dördü de sağlanmalı (V5 ile aynı):
  - NORMAL > 0,
  - STRESS > 0,
  - ortalama R > 0,
  - LCB > 0.
- **T1'den iyi:** yeni coinlerde getiri ≥ T1 getirisi VE MDD ≤ T1 MDD.
  T1 = günlük N50_X5_L + E10: +19.09%, MDD 7.07% (V5).
- **Ek modül değerli:** T1 + H4 birleşik hesabın getiri/MDD oranı, T1 tek başına oranından yüksek.

## Teşhis (karar dışı)
Tüm varyantların yeni coin sonuçları, yıllara göre getiri, en iyi 5 işlem çıkarılınca getiri.

Sonuç görüldükten sonra N, k, E, coin listesi, dönem ya da ölçüt değiştirilmez.
