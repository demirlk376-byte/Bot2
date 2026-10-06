# Geliştirme turu 1 — ÖN KAYIT (2026-10-06, sonuçlardan önce)

Gerçek maliyetli ikiz (giriş kayması 15.85bp, çıkış 0.24bp, komisyon 2.5bp, funding açık, maker dolum
%66) iki dönemde: KEŞİF 2023-04 → 2026-07 ve BAĞIMSIZ 2020-02 → 2023-04.

## S1 — Squeeze gerçek maliyette kârlı mı?
İkiz SQUEEZE_ENABLED=true (canlıdaki XRP/DOGE/XLM) ile iki dönemde koşulur.
- Squeeze işlemlerinin ort R'si iki dönemde de > 0 VE bot (squeeze dahil) bileşik çarpanı ile en büyük
  düşüşün oranı (çarpan / maxDD) iki dönemde de squeeze kapalıdan yüksek → **AÇILABİLİR**.
- Aksi halde KAPALI KALIR.

## S2 — Trend riski
Bot (squeeze kapalı, gerçek maliyet) + trend B0 ortak sermaye (birlesik mantığı), trend riski
%1 / %1.5 / %2. Ölçüt: aylık hesap değerinden "yıllık bileşik getiri / en büyük düşüş" oranı.
- Bir risk seviyesi %1'den İYİ ⇔ bu oran iki yarıda da (2023-04→2024-12, 2025-01→2026-07) yüksek VE
  en büyük düşüş %1'e göre en fazla 5 puan kötü.
(Bağımsız dönemde trend motoru verisi var ama bot ikizi ile birleşim yalnız keşif penceresinde
kurulu — sınırlama olarak raporlanır.)

---
## SONUÇ
### S1 squeeze (gerçek maliyet)
| dönem | squeeze ort R | bot çarpan kapalı → açık | maxDD kapalı → açık | oran kapalı → açık |
|---|---|---|---|---|
| keşif 2023-04→2026-07 | +0.120 (368) | 21.9 → 51.2 | %30.5 → %26.7 | 0.72 → 1.92 |
| bağımsız 2020-02→2023-04 | +0.062 (415) | 9.4 → 12.9 | %55.5 → **%70.8** | 0.170 → 0.182 |
Ön kayıtlı kurala göre **AÇILABİLİR**. AMA kural (çarpan/maxDD) bağımsız dönemde maxDD'nin %55'ten %71'e
çıkmasını yakalamadı — kuralın tasarım zaafı, açıkça belirtilir. Canlı 21 işlem −0.47R [%95 −0.99,
+0.15]: aralık ikizin +0.12'sini dışlamıyor (şanssızlıkla tutarlı). Öneri: mevcut riskte AÇMA; yarım
riskte ayrı ön kayıtla sına.
### S2 trend riski (keşif penceresi, gerçek maliyetli bot + trend)
| risk | çarpan | CAGR | maxDD | oran | 1.yarı oran/DD | 2.yarı oran/DD |
|---|---|---|---|---|---|---|
| %1 | 79.1 | %271 | %28.9 | 9.37 | 33.35 / %17.8 | 2.93 / %28.9 |
| %1.5 | 116.5 | %316 | %28.9 | 10.94 | 35.79 / %21.3 | 2.97 / %28.9 |
| %2 | 159.3 | %357 | %29.0 | 12.33 | 37.36 / %24.8 | 2.98 / %29.0 |
%1.5 **İYİ** (iki yarıda oran yüksek, DD +3.5 puan). %2 ELENDİ (1. yarı DD +7.0 puan > 5).
Kazancın neredeyse tamamı 2023–2024 boğasından; 2025–2026'da fark yok denecek kadar küçük.
