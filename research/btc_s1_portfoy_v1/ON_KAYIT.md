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
