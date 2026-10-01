# BTC DOMİNANS FİLTRESİ — önceden kayıt (2026-10-01, sonuçlardan ÖNCE)

## Soru
Bot yalnız altcoin işler: SOL, ETH, ADA, NEAR, BCH, ICP, BNB, XRP, DOGE, XLM, LTC.
Yaygın trader kuralı:
- BTC dominansı yükselirken altcoin LONG açma (paralar BTC'ye akıyor, altlar zayıf).
- Dominans düşerken altcoin SHORT açma (alt sezonu).

Bu kural, mevcut botun işlemlerinde kötü giden bir alt kümeyi ayırıp eleyebiliyor mu?

## Önceki çalışma ve farkı
`research_btcd_clean.py` (README "Does BTC Dominance help") eski botu, yani yalnız BTC üzerinde
1h BB-fade stratejisini, 13 ay veriyle test etti. Dominans çöküşünde açılan işlemler kötü
çıktı, ama filtre getiriyi artırmadı. Bugünkü bot (altcoinlerde donchian/squeeze/BB) bu filtreyle
hiç test edilmedi.

## Veri
- **Kaynak:** Binance USDⓈ-M `BTCDOMUSDT` 1h mumları (data.binance.vision aylık/günlük zip;
  yedek kaynak `fapi/v1/klines`). VPS'te indirilir, repodaki `data/` klasörüne yazılmaz.
- **Kullanılan değer:** kapanış fiyatı (dominans endeksi).
- **D(t):** kapanış zamanı ≤ t olan son 1h mumun kapanışı. t = ikizde girişin olduğu mum kapanışı.
  Canlı bot da aynı anda bu mumu çekebilir; gelecek bilgisi yok.
  Bulunan mum hedef zamandan 2 saatten eskiyse değer yok sayılır.
- **d7(t)** = ln(D(t) / D(t − 168 sa)): 7 günlük dominans değişimi.
- **d3(t)** = ln(D(t) / D(t − 72 sa)).

## Filtreler (yön: yaygın kural; sonuca göre ters çevrilmez)
| ad | rol | LONG engellenir | SHORT engellenir |
|---|---|---|---|
| **F1** | **BİRİNCİL — karar bununla** | d7 > 0 | d7 < 0 |
| F2 | sağlamlık (bant) | d7 > +%2 | d7 < −%2 |
| F3 | sağlamlık (72 sa) | d3 > 0 | d3 < 0 |

Dominans verisi yoksa işlem ENGELLENMEZ ve kapsam dışı sayılır.

## İşlemler
936 referans işlem: `arastirma/paylasim_paketi_2026-09-26/ikiz/ikiz_k25_cap25_islemler.csv`.
- Kaynağı: mevcut canlı ayarla ikiz, 2023-04 → 2026-07.
- Maliyet: 15.85bp giriş / 0.24bp çıkış kayması, 1bp komisyon.
- Bu liste 2026-09-30'da FAILED_PULLBACK_V1 A koşusuyla birebir yeniden üretildi.
- **net R** = pnl_usdt / (|giriş − sl0| × miktar).

## Aşama 1 — işlem ayrıştırması (ikiz koşusu yok)
Her işleme filtre etiketi verilir; alt kümelerin toplamı tabanı tam verir.

**Raporlananlar:**
- engellenen pay
- engellenen ve kalan işlemlerin ortalama net R'si, hafta-kümeli bootstrap %95 GA
  (5000 tekrar, seed 20261001)
- kol, yön ve kronolojik yarılara göre kırılım (sınır 2024-12-01)
- **plasebo:** d7 serisi işlemlere göre zaman içinde dairesel kaydırılır.
  - 200 eşit aralıklı kaydırma, 30 gün ile (süre − 30 gün) arası.
  - Gerçek F1 engellenen ortalama R, kaydırılmış versiyonların içinde kaçıncı yüzdelikte?
  - Rejimler aylarca sürdüğü için i.i.d. testlerin şişirdiği anlamlılığa karşı koruma sağlar.

**AŞAMA 1 GEÇER**, ancak aşağıdakilerin **hepsi** sağlanırsa:
- (a) İşlemlerin ≥ %95'inde d7 ve d3 hesaplanabiliyor.
- (b) F1'in engellediği işlemlerin ortalama net R'si < 0 **ve** GA üst sınırı < 0.
- (c) F1 engellenen ortalama net R, her iki kronolojik yarıda < 0.
- (d) F2 ve F3'ün engellediği işlemlerin ortalama net R'si de < 0 (yön tutarlılığı).
- (e) Plasebo: gerçek F1 engellenen ortalama R, kaydırılmış dağılımın en düşük %5'inde.

**Hüküm:**
- (a) sağlanmazsa → **KANIT YETERSİZ** (veri eksik).
- (a) sağlanıp (b)–(e)'den biri tutmazsa → **REDDEDİLDİ**.
  Engellenen işlemler zarar etmiyorsa, onları atmak beklenen getiriyi düşürür. Koltuk serbest
  bırakma etkisi küçüktür: 7 koltuk zamanın ~%3'ünde dolu (RESEARCH_LEDGER).
- Hepsi sağlanırsa → **Aşama 2**.

## Aşama 2 — portföy (yalnız Aşama 1 geçerse)
İkizde A (filtresiz) ve F1 (`execute_signal` öncesi engel) koşulur, ana ve 2x maliyetle.

**İLERİ PAPER İZLEME ADAYI** için hepsi gerekir:
- F1 − A net USDT > 0, hem 1x hem 2x maliyette.
- F1 maks. düşüş ≤ A maks. düşüş.
- Her iki kronolojik yarıda F1 − A ≥ 0.

Aksi hâlde **REDDEDİLDİ**. Olumlu sonuç bile canlıya alma onayı değildir: önce ileriye dönük
paper izleme gerekir.

## Notlar
- Bu veri (2023–2026) botun geliştirilmesinde defalarca kullanıldı; dokunulmamış test değildir.
- Kurallar ve eşikler sonuçlardan sonra değiştirilmez. Başka dominans tanımı ya da eşik taranmaz.

---

## Ek: TERS KURAL T1 (2026-10-01; kullanıcı isteği, saklı veri görülmeden yazıldı)

**Kaynağı — açıkça sonuçtan doğdu:**
- Kullanıcı, F1'in kuru denemede ters yönde çıkmasını görünce kuralın tersine çevrilmesini istedi.
  Kuru deneme: yerel 13 aylık 4h veri, 2025-03-01 → 2026-06-01; engellenen işlemler +0.44R,
  kalanlar +0.26R.
- Bu yüzden T1, **o dönemde test edilemez**. O dönem yalnız betimsel olarak raporlanır.

**Kural T1:** dominansla AYNI yönde gir.
- d7 < 0 iken LONG engellenir.
- d7 > 0 iken SHORT engellenir.
- d7 ≠ 0 iken F1'in tam tümleyenidir.

**Saklı test dönemi:** kuru denemede etiketlenmemiş tüm işlemler.
- 2025-03-01 öncesi (2023-04 → 2025-02).
- 2026-06-01 sonrası.
- Bu dönemlerin dominans verisi henüz hiç görülmedi; VPS indirmesiyle gelecek.

**SAKLI DÖNEMDE GEÇER**, ancak aşağıdakilerin hepsi sağlanırsa:
- (a) Saklı işlemlerin ≥ %95'i kapsamda.
- (b) T1'in engellediği saklı işlem sayısı ≥ 100.
- (c) T1'in engellediği işlemlerin ortalama net R'si < 0 **ve** hafta-kümeli %95 GA üst sınırı < 0.
- (d) Engellenen ortalama R iki parçanın ikisinde de < 0 (sınır 2024-03-01).
- (e) Plasebo: 200 dairesel kaydırma; gerçek değer en düşük %5'te.

**Hüküm:**
- Geçerse → Aşama 2. Tüm dönemde ikiz A ve T1 koşulur, 1x ve 2x maliyetle; ölçütler F1 için
  yazılanların aynısıdır.
- Aşama 2'yi de geçerse → ileriye dönük paper izleme. Doğrudan canlıya alınmaz.
- (a) sağlanmazsa → KANIT YETERSİZ.
- Diğer durumlarda → REDDEDİLDİ.

**F1 değerlendirmesi değişmez:** F1 kuralları, kapıları ve tam dönem testi aynen geçerlidir.
