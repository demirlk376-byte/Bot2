# BTC S1 (sade 4H kırılım) ayrı kol olarak bota eklenirse — portföy katkısı — ÖN KAYIT (2026-10-31, sonuçlardan ÖNCE)

btc_yeni_setup_v1'de S1 tek başına İYİ çıktı (2017–19 dış-örneklem CAGR %36, Sharpe 2.07, DD %6.9; 2020–26 %15, 1.07,
%10.7; botla aylık korelasyon 0.30). Canlıya almadan önceki ön kayıtlı adım: aynı hesapta, canlı düzenle (bot ikizi %3.5 +
trend %1.5) BİRLİKTE ne yapıyor?

## Kurulum (değişmez)
S1 işlemleri `scratchpad/by_A/trades_S1.csv` (dönem B, denetlenmiş; kurallar ve maliyet btc_yeni_setup_v1'deki gibi:
taker %0.05 + 3.5 bp/taraf, gerçek funding). Her S1 işlemi ortak sermaye motoruna (`scratchpad/portfoy/harness.py`,
MotorBirlesik, BASE ile aynı) ayrı bir kol olarak verilir: R = S1 işleminin R'si (pnl / başlangıç riski), risk = özsermayenin
**%1**'i (motorda R × 0.01/0.035), teminat_oran = notional/özsermaye × (0.01 / S1 risk payı) / 10 [10x teminat].
Bilgi amaçlı ikinci kol: risk %2. Pencereler: BAĞIMSIZ 2020-02-01 → 2023-04-07 (bot = ikiz_eski), KEŞİF 2023-04-07 →
2026-07-18 (bot = ikiz_gercek); girişler pencere içinde, çıkışlar pencere sonundan önce (BASE ile aynı kural).

## Ölçüt (değiştirilmeyecek)
**EKLENEBİLİR** ⇔ %1 kolu İKİ pencerede de: MAR > BASE, çarpan ≥ BASE, maxDD ≤ BASE + 3 puan, en kötü ay BASE'ten en
fazla 3 puan kötü. Rapor: aylık tablo, zararlı ay sayısı, eşzamanlı pozisyon, teminat atlamaları, yıl yıl katkı.
EKLENEBİLİR çıkarsa sonraki adım kâğıt (sinyal) modunda izleme + kullanıcı onayı; canlıya kendiliğinden geçmez.
Sonuç görüldükten sonra risk, pencereler ve ölçüt değiştirilmez.

---
## SONUÇ (2026-10-31) — EKLENEBİLİR (%1 kolu dört ölçütü iki pencerede de geçti)
Koşucu + bağımsız denetçi aynı sayılar; BASE birebir; S1 R/teminat ölçeklemesi doğrulandı; teminat atlaması yok.
| pencere | kol | çarpan | maxDD | MAR | en kötü ay | zararlı ay | S1 işlem |
|---|---|---|---|---|---|---|---|
| bağımsız 2020-02 → 2023-04 | BASE | x42.2 | %58.7 | 3.70 | −%38.1 | 16/39 | — |
| | +S1 %1 | **x65.4** | %56.2 | **4.68** | −%35.4 | 16/39 | 144 |
| | +S1 %2 (bilgi) | x95.8 | %53.7 | 5.73 | −%32.6 | 17/39 | 144 |
| keşif 2023-04 → 2026-07 | BASE | x116.5 | %28.9 | 10.94 | −%22.2 | 14/40 | — |
| | +S1 %1 | **x127.3** | %28.3 | **11.60** | −%24.1 | 15/40 | 163 |
| | +S1 %2 (bilgi) | x121.9 | %29.1 | 11.08 | −%26.9 | 17/40 | 162 |
En dar ölçüt: keşif en kötü ay −%24.1 (sınır −%25.2). %2 kolu keşifte en kötü ay testini geçmezdi. S1'in kendi kenarı
2025–26'da ince (+1.7R, +2.4R); keşifte botla aylık korelasyon 0.47, bağımsızda 0.04. Sınırlama: motor açık pozisyonları
piyasaya işaretlemiyor (BASE ile aynı). Sonraki adım: kâğıt/sinyal modunda izleme + kullanıcı onayı.
