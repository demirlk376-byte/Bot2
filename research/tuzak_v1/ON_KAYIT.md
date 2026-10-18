# Tuzak (başarısız kalabalık formasyonu) — ÖN KAYIT (2026-10-18, sonuçlardan ÖNCE)

Gerekçe: mum_formasyon_v1'de kalabalığın en çok kullandığı DÖNÜŞ formasyonları (pin bar, yutan) zarar etti
(4h pin bar −0.15R, yutan −0.10R; 16.6k / 15.2k işlem). Hipotez: formasyon başarısız olup kalabalığın doğal stop
seviyesi (formasyonun ucu) kırıldığında, tetiklenen stoplar hareketi hızlandırır → kırılım yönünde işlem.
Formasyon tanımları mum_formasyon_v1/ON_KAYIT.md ile BİREBİR aynı (yutan, pin bar; bağlam koşulları dahil).

## Veri ve protokol
`research_data/h4_kirilim_v6/veri/<COIN>_4h.csv`, 1D = UTC gün (6 mum tam). Dönem: girişler 2020-01-01 →
2025-08-08. SEÇİM: eski 12; SINAV: yeni 26 (mum_formasyon_v1 ile aynı listeler).

## Kural
- Boğa formasyonu (yükseliş yutan / çekiç, kalabalık LONG) tamamlanır. Sonraki 3 mum içinde fiyat formasyonun EN
  DÜŞÜĞÜNÜN 0.1·ATR14 altına inerse (bekleyen satış-stop emri) → SHORT, giriş fiyatı = o seviye (mum o seviyenin
  altında açılırsa açılış). Stop: formasyonun EN YÜKSEĞİ + 0.1·ATR14. Hedef 2R. Süre: girişten itibaren 10 mum
  (giriş mumu 1. mum), sonra kapanışta çık. Giriş mumunda stop ve hedef de kontrol edilir: giriş mumunda hem
  stop hem hedef seviyesi görülmüşse STOP sayılır.
- Ayı formasyonu (düşüş yutan / kayan yıldız, kalabalık SHORT) → aynası: formasyon EN YÜKSEĞİ + 0.1·ATR üstünde
  LONG, stop formasyon EN DÜŞÜĞÜ − 0.1·ATR.
- 3 mum içinde tetiklenmezse sinyal iptal. Aynı coinde aynı test için tek pozisyon.
- ATR14 (basit TR ortalaması) formasyon tamamlanma mumuna kadar.
Maliyet NORMAL: 1 bp ×2 komisyon + giriş kayması 15.85 bp + çıkış 0.24 bp; STRESS: kayma ×2. R tanımı v1 ile aynı.

## Testler ve ölçüt (değiştirilmeyecek)
4 test: {yutan-tuzak, pinbar-tuzak} × {4h, 1D}. Haftalık blok bootstrap (10 000, seed 20261018),
Bonferroni alt sınır = %0.625 persentil.
Bir test **TUTTU** ⇔ (1) SEÇİM NORMAL ort R > 0, (2) SINAV NORMAL ve STRESS ort R > 0, (3) SINAV Bonferroni
alt > 0, (4) SINAV n ≥ 100. Rapor: long/short, yıl yıl, çıkış dağılımı, tetiklenme oranı; TUTAN olursa donchian
ikiziyle haftalık korelasyon.

---
## SONUÇ (2026-10-18) — 4/4 TUTMADI
| test | TF | SEÇİM ort R | SINAV ort R (NORMAL / STRESS) | SINAV n | yıl yıl (SINAV) |
|---|---|---|---|---|---|
| yutan tuzağı | 4h | −0.17 | −0.18 / −0.23 | ~6000 | her yıl negatif |
| yutan tuzağı | 1D | −0.11 | −0.06 / −0.08 | ~900 | karışık |
| pin bar tuzağı | 4h | −0.27 | −0.28 / −0.34 | ~8100 | her yıl negatif |
| pin bar tuzağı | 1D | −0.18 | −0.22 / −0.24 | ~1160 | her yıl negatif |
Maliyetten önce bile negatif. Hem formasyon hem tuzağı kaybediyor: formasyon uçları etrafındaki hareket kısa vadeli
gürültü; dar stoplu her iki yön de stoplanıyor. Kalabalığın formasyonunu tersine çevirmek kenar yaratmıyor.
