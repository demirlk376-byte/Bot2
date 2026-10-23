# Kâr çekme kuralı — ÖN KAYIT (2026-10-23, sonuçlardan ÖNCE)

Kullanıcı isteği: "haftalık/aylık kâr". 20+ strateji ailesinden düzenli aylık kâr veren çıkmadı (son: piyasa_notr_v1).
Botun kârı patlamalı geliyor ve iyi dönemden sonra geri verilebiliyor (canlıda 413 $ zirve → 253 $). Soru: strateji
değişmeden, hesaptan **düzenli para çekmek** kârı cebe koyup "geri verme"yi azaltır mı, bedeli ne?
Bu bir kenar testi değil, bir para yönetimi seçimi; ama kurallar ve karar ölçütü yine önceden sabit.
(aylik_hedef'ten farkı: orada iyi aydan sonra İŞLEM durduruluyordu; burada işlem hiç durmaz, yalnız para çekilir.)

## Veri
BASE = canlı düzen (bot gerçek maliyetli ikizi + trend %1.5), ortak sermaye motoru, momentum_v2'de hesaplanmış:
`scratchpad/mom2_portfoy/R_BASE_KESIF.pkl` (2023-04-07 → 2026-07-18, bot = `ikiz_gercek.db`) ve `R_BASE_BAGIMSIZ.pkl`
(2020-02-01 → 2023-04-07, bot = `ikiz_eski.db`). Aylık getiri = `mom2_portfoy/analiz.py` `aylik()` ile (ay sonu
değer, başa 10 000 eklenir, pct_change); ilk ve son kısmi aylar dahil (KEŞİF 40 ay, BAĞIMSIZ 39 ay).
Varsayım: bot ve trend boyutu özsermayeyle orantılı olduğundan çekimden sonra gelecek getiriler aynı oranda
ölçeklenir (ay sonunda açık pozisyonların küçülmemesi yaklaşık hata; ay sonu açık risk oranı ayrıca raporlanır).

## Kurallar (ay sonunda, o ayın getirisi uygulandıktan sonra; başlangıç S = 250 USDT)
- **BASE**: hiç çekim yok.
- **Z30**: zirve çizgisi Z (başta S). Bakiye E > Z ise W = 0.30 · (E − Z) çekilir; E ← E − W; Z ← E.
- **Z50**: aynı, oran 0.50.
- **M3**: her ay sonu (E > 0) W = 0.03 · E çekilir ("aylık maaş", zararlı ayda da).
Toplam servet TS_t = E_t + o ana kadar çekilenlerin toplamı (çekilen para güvende sayılır, faiz yok).

## Ölçümler
Tarihsel (iki dönem, gerçek ay sırası): son bakiye, çekilen toplam, TS, TS'nin en büyük düşüşü (ay sonu, başlangıç
dahil; "geri verme"), çekim yapılan ay sayısı, aylık ortalama çekim, yıl yıl çekim.
Bootstrap (senaryolar): her dönemin aylık getirilerinden dairesel blok bootstrap, blok 6 ay, 36 aylık yol,
10 000 yol, `numpy.random.default_rng(20261023)`, tüm kurallar AYNI yollarda. Her kural için TS'nin medyanı,
%10 ve %90 persentili, P(TS < S), TS düşüşünün medyanı.

## Karar (değiştirilmeyecek)
Bir kural **ÖNERİLİR** ⇔ HER İKİ dönemde de:
(a) bootstrap medyan TS ≥ BASE medyan TS'nin %50'si; (b) bootstrap %10 persentil TS ≥ BASE'inki;
(c) P(TS < S) ≤ BASE'inki; (d) tarihsel TS düşüşü BASE'inkinden en az 5 puan az.
Birden çok kural geçerse iki dönemin bootstrap medyan TS'lerinin geometrik ortalaması en yüksek olan seçilir.
Hiçbiri geçmezse "çekim kuralı önerilmez". Sınırlama: ikiz canlıdan iyimser olabilir (canlı şu an −%10); küçük
hesapta MEXC minimum emir büyüklüğü çekimle daha erken bağlayıcı olur (modellenmez).
Sonuç görüldükten sonra oranlar, blok boyu, yol uzunluğu, eşikler ve ölçüt değiştirilmez.

---
## SONUÇ (2026-10-23) — ÇEKİM KURALI ÖNERİLMEZ (ölçüt b her kuralda, iki dönemde de kaldı)
İki kör uygulama + denetçinin üçüncü motoru 128 sayının hepsinde aynı (göreli fark ≤ 2.6e-16). Düzeltme gerekmedi.
Başlangıç 250 USDT, ikiz (gerçek maliyetli) + trend %1.5. TS = cepteki + hesaptaki.

| dönem | kural | son bakiye | çekilen | TS | TS düşüşü | çekim ayı | boot. medyan TS | boot. %10 TS | P(TS<250) |
|---|---|---|---|---|---|---|---|---|---|
| keşif 2023–26 | BASE | 29 117 | 0 | 29 117 | %28.9 | 0/40 | 17 926 | 3 001 | %0.06 |
| | Z30 | 8 763 | 4 375 | 13 138 | %20.4 | 21/40 | 8 931 | 2 165 | %0.06 |
| | Z50 | 3 578 | 4 021 | 7 599 | %18.8 | 21/40 | 5 588 | 1 745 | %0.05 |
| | M3 | 8 610 | 5 695 | 14 305 | %22.6 | 40/40 | 8 367 | 1 664 | %0.07 |
| bağımsız 2020–23 | BASE | 10 540 | 0 | 10 540 | %58.7 | 0/39 | 7 934 | 1 084 | %1.14 |
| | Z30 | 3 227 | 3 240 | 6 467 | %41.5 | 20/39 | 4 801 | 1 005 | %0.70 |
| | Z50 | 1 356 | 3 030 | 4 386 | %37.2 | 20/39 | 3 366 | 948 | %0.49 |
| | M3 | 3 213 | 2 310 | 5 523 | %47.2 | 39/39 | 4 032 | 735 | %0.99 |

Çekim "geri verme"yi gerçekten azaltıyor (TS düşüşü 6–21 puan az; ölçüt d hepsinde geçti) ve bağımsız dönemde
başlangıcın altında bitme olasılığını yarıya indiriyor. Ama bileşik büyüme kaybı o kadar büyük ki kötü senaryoda
bile (%10 persentil) toplam servet çekimsizden düşük (ölçüt b kaldı); medyan TS %31–61'e iniyor (Z30 keşif 0.498,
eşiğin kıl payı altında). Sınırlama: sayılar ikizden; canlı hesap şu an −%10 ve ikizden kötü — mutlak tutarlar iyimser.
Ay sonu açık risk ortalaması %0.8–1.0 (yaklaşım hatası küçük).
