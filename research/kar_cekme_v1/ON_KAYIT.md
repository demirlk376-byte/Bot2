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
