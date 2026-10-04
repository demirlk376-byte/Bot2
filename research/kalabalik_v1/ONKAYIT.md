# KALABALIK_V1 — kalabalığa karşı konumlanma, önceden kayıt (2026-10-04, veri inerken, sonuçlardan ÖNCE)

**Soru:** Perakende yatırımcılar (Binance "global account" long/short oranı) aşırı derecede tek tarafa
yığıldığında fiyat sonraki günlerde ters yöne gidiyor mu? Ya da büyük trader'lar ile perakende ters
konumlandığında büyüklerin tarafı mı kazanıyor?

## Veri
- **Kalabalık:** Binance USDⓈ-M `metrics` (5m) → 1h (saatin SON kaydı), `veri/kalabalik` dalı.
  - `count_long_short_ratio`: perakende hesap oranı.
  - `sum_toptrader_long_short_ratio`: büyük trader pozisyon oranı.
- **Fiyat ve funding:** Binance 4h mum + funding (`veri/trend4h`). MEXC metadatası.
- **Coinler:** seçim için botun 12 coini. Sınav için 24 coin (LINK … SUI).
  - Bu coinler başka stratejilerde incelendi; bu sinyal için HİÇ incelenmedi.
  - FIL/EOS MEXC metadatası yoksa dışlanır.

## Kurallar (2 varyant, sabit)
- **z-skoru:** son 720 saatin (30 gün) ortalaması ve standart sapması ile, karar anında bilinen değerlerle.
  Karar 4h kapanışında, o kapanıştan ÖNCEKİ son saatlik metrics değeriyle.
- **H1 — perakendeye karşı:**
  - perakende z ≥ +2 → SHORT;
  - perakende z ≤ −2 → LONG.
- **H2 — büyükler ile perakende ayrışması:**
  - büyük trader z ≤ −1 VE perakende z ≥ +1 → SHORT;
  - büyük trader z ≥ +1 VE perakende z ≤ −1 → LONG.
- **Giriş:** sinyalden sonraki 4h açılışında.
- **Çıkış:** 72 saat (18 adet 4h mum) sonra açılışta; ya da stopta (giriş ± 2×ATR20(4h), mum içinde stop
  fiyatından, açılışta boşlukta açılıştan). Hedef yok.
- **Pozisyon kuralı:** coin başına tek pozisyon; pozisyon açıkken o coinde yeni sinyal yok.

## Yürütme, maliyet, risk
- **Maliyet:** NORMAL (1bp komisyon, giriş 15.85bp, çıkış 0.24bp kayma) ve STRESS (kayma ×2); gerçek funding.
- **Risk:** işlem başı 25 USDT (C0 10.000'in %0.25'i, sabit, bileşiksiz). Açık risk tavanı 12 birim.

## Dönemler
- **Isınma:** 30 gün.
- **KEŞİF:** 2022-02-01 → 2024-06-14.
- **DOĞRULAMA:** 2024-06-14 → 2025-08-08.
- **FİNAL (2025-08-08 →) AÇILMAZ.**

## Karar (iki varyant için çoklu test düzeltmeli)
Bir varyant **TUTTU** sayılır, ancak hepsi birden sağlanırsa:
- (a) 12 coin DOĞRULAMA'da ortalama net R > 0 ve haftalık 4-haftalık blok bootstrap alt sınırı
  (yüzdelik 1.25, iki varyant için Bonferroni) > 0;
- (b) aynı koşullar 24 coinin KEŞİF + DOĞRULAMA dönemi toplamında da;
- (c) STRESS'te toplam net > 0.

Aksi halde ELENDİ. Örnek < 30 işlemse D (yetersiz). Sonuçtan sonra eşik, pencere, süre, stop değişmez.
