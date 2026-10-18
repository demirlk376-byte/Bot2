# Devam formasyonları — FİNAL dönem tek seferlik doğrulama — ÖN KAYIT (2026-10-18, sonuçlardan ÖNCE)

Adaylar (mum_formasyon_v1'den, tanımlar ve işlem kuralları BİREBİR aynı, hiçbir parametre değişmez):
**U = üç beyaz asker / üç kara karga (4h)** ve **M = marubozu (4h)**. v1'de yeni 26 coinde her yıl pozitif,
ön kayıtlı Bonferroni eşiğini kıl payı kaçırdılar. FİNAL dönem (2025-08-08 sonrası) bu projede hiçbir seçimde
kullanılmadı; burada BİR KEZ kullanılır, sonucu ne olursa olsun tekrar kullanılmaz.

## Veri
`research_data/h4_kirilim_v6/veri/<COIN>_4h.csv`, 38 coinin tamamı (eski 12 + yeni 26). Girişler
2025-08-08 → 2026-09-20 (10 mumluk çıkış penceresi veri sonundan önce kapansın). Verisi bu dönemi kapsamayan
coin (ör. EOS 2025-05'te bitiyor) kendiliğinden düşer. Göstergeler dönem başından ÖNCEKİ veriyle ısınır.

## Ölçüt (değiştirilmeyecek; 2 test)
Haftalık blok bootstrap (10 000, seed 20261018).
- **DOĞRULANDI** ⇔ FİNAL'de NORMAL ort R > 0 VE STRESS ort R > 0 VE bootstrap %1.25 persentili (tek yönlü %97.5,
  2 test Bonferroni) > 0.
- **DESTEKLENDİ (zayıf)** ⇔ NORMAL ve STRESS ort R > 0 ama alt sınır ≤ 0.
- Aksi halde **ÇÜRÜDÜ**.

## Bota eklenebilirlik (yalnız DOĞRULANDI ya da DESTEKLENDİ çıkan için; karar dışı ölçümler)
1. Donchian ikiziyle (`ikiz_gercek.db`, 2023-04 → 2026-07) haftalık R korelasyonu ve örtüşme: formasyon
   işlemlerinin kaçı aynı coin + aynı yönde ±2 mum içinde bir donchian girişiyle çakışıyor.
2. Ortak sermaye etkisi: bot (gerçek maliyetli ikiz işlemleri) + formasyon kolu (işlem başı %1 risk, 12 bot
   coininde) birlikte, 2023-04 → 2026-07: çarpan ve aylık maxDD, yalnız bot ile karşılaştırma.
Eklemeye ancak (1) korelasyon < 0.5 ve (2) çarpan artarken maxDD en fazla 3 puan kötüleşirse aday denir;
canlıya alma ayrıca kullanıcı onayı ve ikiz testiyle yapılır.

---
## SONUÇ (2026-10-18) — İKİSİ DE ÇÜRÜDÜ (FİNAL bir kez kullanıldı)
İki bağımsız uygulama işlem işlem aynı (1849/1849); kod v1 referansını 5932 işlemde birebir üretiyor.

| formasyon | FİNAL n (37 coin) | ort R NORMAL | ort R STRESS | maliyetsiz brüt R | %1.25 alt |
|---|---|---|---|---|---|
| üç asker/karga 4h | 1113 | −0.037 | −0.069 | −0.001 | −0.177 |
| marubozu 4h | 736 | −0.119 | −0.158 | −0.076 | −0.298 |

2020–2025'teki +0.09 / +0.15R kenar yeni dönemde yok (maliyetten önce bile ~0 / negatif). Bot coinlerinde
donchian ile haftalık korelasyon +0.41 / +0.19 — örtüşen işlemler en iyileri (yani kenarın bir kısmı zaten donchian'da).
Hüküm: bota eklenmez.
