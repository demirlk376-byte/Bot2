# Trend kolunu 38 coine yaymak — ÖN KAYIT (2026-10-19, sonuçlardan ÖNCE)

Gerekçe: trend kolu (B0: 1D N50 + 4h N180, ETH SMA200 rejimi, 5×ATR iz süren stop, 2 piramit, açık risk tavanı
%24) geliştirilirken hiç görmediği yeni coinlerde de kâr etti (trend_takip_v1 V5/V8, pro_v9 sepeti). Canlıda yalnız
botun 12 coininde çalışıyor. Soru: aynı kurallarla 38 coinde çalışması toplam hesabı iyileştirir mi?

## Kurulum (değişmez)
Ortak sermaye motoru `research/trend_gelistirme/birlesik.py` (MotorBirlesik): bot işlemleri gerçek maliyetli
ikizden (donchian + mean_rev, squeeze kapalı; işlem başı %3.5), trend B0 NORMAL maliyet profiliyle.
- **T12 (taban, canlı düzen)**: trend 12 bot coininde, risk %1.5, tavan %24.
- **T38**: trend 38 coinde (`research_data/h4_kirilim_v6/veri` içindeki tüm coinler), risk %1.5, tavan %24.
- **T38_R1**: trend 38 coinde, risk %1.0, tavan %24.
Dönemler: KEŞİF 2023-04-07 → 2026-07-18 (bot = `ikiz_gercek.db`), BAĞIMSIZ 2020-02-01 → 2023-04-06
(bot = `ikiz_eski.db`, girişler < 2023-04-07). Coinler listelendikleri tarihten itibaren katılır.

## Ölçüt (değiştirilmeyecek)
Aylık hesap değerinden: çarpan, yıllık bileşik getiri (CAGR), en büyük düşüş (maxDD), oran = CAGR/maxDD.
Bir varyant **İYİ** ⇔ HER İKİ dönemde de (1) oran T12'den yüksek, (2) çarpan T12'den yüksek, (3) maxDD T12'den
en fazla 3 puan kötü. İkisi de İYİ ise oranı yüksek olan seçilir. Aksi halde canlı düzen (T12) kalır.
Rapor: aylık tablo, ortalama/en fazla eşzamanlı trend pozisyonu, tavana takılan giriş sayısı, coin bazında trend PnL.
Sınırlama: küçük hesapta MEXC minimum emir büyüklüğü ve teminat sınırları modellenmez.

---
## SONUÇ (2026-10-19) — İYİ VARYANT YOK, canlı düzen (T12) kalır
Uygulama + bağımsız yeniden hesap 6 satırda birebir aynı. Not: EOS ve FIL'in MEXC sözleşme bilgisi yok → "T38" fiilen 36 coin.

| varyant | dönem | çarpan | maxDD | CAGR/maxDD |
|---|---|---|---|---|
| T12 (12 coin, %1.5) | keşif | 116.5 | %28.9 | 10.94 |
| T38 (36 coin, %1.5) | keşif | 68.9 | %38.8 | 6.59 |
| T38_R1 (36 coin, %1) | keşif | 69.2 | %29.7 | 8.62 |
| T12 | bağımsız | 42.2 | %58.7 | 3.70 |
| T38 | bağımsız | 76.5 | %62.8 | 4.47 |
| T38_R1 | bağımsız | 45.0 | %59.5 | 3.76 |

Daha çok coin 2021 boğasında daha çok kazandırıyor (bağımsız), ama 2023–2024'te eşzamanlı pozisyonlar artınca
(ortalama 1.3 → 3.8, en fazla 12 → 33–36) sert geri çekilmeler büyüyor ve risk tavanı piramitleri kesiyor; sonuç
keşifte belirgin şekilde kötü. Ön kayıtlı kural: iki dönemde de iyi değil → eklenmez.
