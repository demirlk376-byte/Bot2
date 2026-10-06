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
