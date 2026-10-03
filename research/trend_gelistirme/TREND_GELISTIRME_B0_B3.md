# TREND_GELİŞTİRME B0–B3 — sonuç raporu (2026-10-04)

## En önemli bulgu

Üç değişiklikten hiçbiri düzeltilmiş tabanı (B0) iyileştirmedi.
- **B1 (4H→günlük devir):** büyük kazananları daha uzun taşımak için tasarlandı ama ters çalıştı.
  Devredilen 134 işlemin 91'i kötüleşti; botun coinlerinde hem kâr hem düşüş kötüleşti.
  - Doğrulama: getiri +%184 → +%151, MDD %23 → %35.
  - Diğer 24 coinde keşifte çok iyi, doğrulamada çok kötü (ters yön). Sonuç dönem şansına bağlı.
- **B3 (başarısız kırılımdan çıkış):** MDD'yi biraz düşürdü (doğrulama %23.2 → %22.3).
  Bedeli: B0'da sonradan kazanan 41 işlemi erken kesmesi; kaçan kâr +34.9k, kurtarılan kayıp 26.0k.
  Getiri ve getiri/MDD ikisi de düştü.
- **B2 (ETH filtresi piramitte):** HİÇ etki yok. B0'daki 234 piramit ekinin (12 + 24 coin) hepsi ETH rejimi
  açıkken doldu. Bu dönemde test edilebilir örnek yok.

Hepsi önceden incelenmiş coin ve dönemlerde ölçüldü; korunmuş final dönemi açılmadı.
Öneri: B0'ı (düzeltilmiş taban) olduğu gibi kullanmak. B0'ın düzeltmeleri canlı koda da taşınmalı (aşağıda).

## 1. B0 — düzeltilmiş taban ve doğrulaması

**Motor** (`motor.py`):
- Ortak 4h portföy saati. Sıra: açılış (boşluk stopu → bekleyen çıkış → ek → giriş) → mum içi stop →
  funding → 4H yönetimi → gün sonunda 1D yönetimi → yeni sinyaller (önce 1D sonra 4H) → hesap değeri.
- Coin başına tek trend pozisyonu.
- ETH rejimi bilinmiyorsa giriş yok.
- Boyutlama önceki kapanışın hesap değeriyle; aynı mumdaki çıkış kârı kullanılmıyor.

**Durum testleri** (`tests/test_durum.py`, 6/6 geçti):
- **Toplu = mum mum = kaydet/yükle:** dört varyantta işlem listesi, hesap serisi, açık pozisyonlar ve
  bekleyenler birebir.
- **Veri kesilince geçmiş aynı:** gelecek sızıntısı yok.
- **Çakışma yok:** aynı coinde çakışan iki trend pozisyonu yok.
- **Rejim bilinmiyorsa giriş yok:** ETH rejimi tamamen silinince hiç işlem açılmıyor.

**Canlı koddaki karşılıkları:** 1. aşamada gönderilen `trend_kolu.py` / `trend_canli.py` şunları yapıyor:
- (a) İlk kurulumda önce tüm 1D, sonra tüm 4H geçmişini yürütüyor.
- (b) Rejim bilinmezse girişe izin veriyor (`rv is None` → serbest).
- (c) Yalnız 215 günlük ETH geçmişi çekiyor; en eski sinyallerin SMA200'üne yetmeyebilir.

Bu üç sorun B0 motorunda düzeltildi; canlı koda henüz taşınmadı. Sinyal modunda yalnız mesajları etkiler
(emir yok). Canlı moddan önce düzeltilmeli.

**Koşu kaydı:**
- **Commit:** 9f48a95 (ön-kayıt).
- **Veri:** `veri/trend4h` 4h + funding; sha256 `sonuclar/*/ozet.json → manifest.veri_hash`.
- **Coinler:** botun 12 coini (birincil). İkincil: 24 coin.
- **Dönemler:** KEŞİF 2021-01-01 → 2024-06-14, DOĞRULAMA 2024-06-14 → 2025-08-08. Final kapalı.
- **Sermaye ve risk:** C0 10.000; risk %1/giriş ve ek, bileşik; açık risk tavanı %24; notional ≤ 2.5× hesap.
- **Teminat:** izole, notional × max(0.1, 1.5 × stop% + 0.005); toplam ≤ 0.95 × hesap.
- **Maliyet:** NORMAL = 1bp komisyon, 15.85bp giriş / 0.24bp çıkış kayması; STRESS = kaymalar ×2;
  gerçek funding.

## 2. Karşılaştırma — botun 12 coini (birincil; önceden incelenmiş)

| | keşif getiri | keşif MDD | doğr. getiri | doğr. MDD | doğr. getiri/MDD | doğr. işlem | doğr. STRESS getiri |
|---|---|---|---|---|---|---|---|
| **B0** | +%290.8 | %35.9 | **+%184.2** | **%23.2** | **7.94** | 53 | +%179.4 |
| B1 | +%151.0 | %44.4 | +%151.2 | %34.6 | 4.38 | 47 | +%145.4 |
| B2 | = B0 | = B0 | = B0 | = B0 | = B0 | 53 | = B0 |
| B3 | +%161.2 | %30.8 | +%169.6 | %22.3 | 7.61 | 77 | +%162.7 |

Getiriler bileşik, ortak zamanlı hesap değerinden. MDD açık pozisyon PnL'i dahil, ortak 4h kapanışlarıyla.

**Yıllık (NORMAL):**

| yıl | B0 | B1 | B3 |
|---|---|---|---|
| 2021 | +%198 | +%97 | +%156 |
| 2022 | −%2 | −%2 | −%2 |
| 2023 | +%29 | +%67 | +%6 |
| 2024 | +%160 | +%62 | +%136 |
| 2025 (8 ay) | +%13 | +%21 | +%13 |

**Parasal katkı ve geri verilen kâr** (tüm dönem, USDT; piramitte R paydası yerine para):

| | ilk giriş | 1. ek | 2. ek | net | açık kârdan geri verilen |
|---|---|---|---|---|---|
| B0 | 69.026 | 21.262 | 10.020 | 100.308 | 202.377 |
| B1 | 26.066 | 6.563 | 5.330 | 37.960 | 161.449 |
| B3 | 41.264 | 13.562 | 4.774 | 59.600 | 139.995 |

Doğrulama döneminde B0: ilk 48.854 / ek1 15.254 / ek2 7.116, geri verilen 92.559.

**En büyük kazananlar:** B0'ın en büyük 10 işlemi toplam 92.586 USDT.
- B1'de bunların 6'sı aynı girişle var, toplam 35.553. Devir yolu sonraki girişleri değiştiriyor.
- B3'te 10'u da var, toplam 53.297. Bileşik boyut farkı ve B3'ün bazılarını erken kesmesi.

## 3. Varyant ayrıntıları ve hüküm

### B1 — 4H işlemini günlük yönetime devret → **C (kötüleştiriyor)**

**Botun 12 coini:**
- 134 devir. Devredilen işlemler B1'de 47.855, B0'daki karşılıkları 91.988 → fark −44.133.
- 43 iyileşti, 91 kötüleşti. Ortalama tutuş 10.7 → 22.6 gün.
- Eşleşen işlem farkının %95 önyükleme aralığı [−116.858, −19.019]: sıfırın altında.

**Diğer 24 coin:**
- Keşifte +%36 → +%295, ama MDD %48 → %73.
- Doğrulamada +%107 → +%39, MDD %33 → %65. Ters yönde.
- Fark aralığı [−45.999, +104.328].

**Yorum:** Günlük 5×ATR stopu, 4H stopundan çok daha geniş. Pozisyon daha uzun taşınıyor ama zirveden çok
daha fazla kâr geri veriliyor. Uzun tutuş, aynı coinde yeni ve daha iyi girişleri de engelliyor.
Büyük kazananlar korunmuyor, aksine azalıyor.

### B2 — ETH filtresi piramit eklerinde → **D (etkilenen örnek yok)**
- **Botun 12 coini:** 98 ek dolumu, 24 coinde 136. Hepsi ETH rejimi açıkken (doğrulandı).
- 2021–2025/08'de ETH rejimi günlerin %58'inde açık; kapanmaya geçiş yalnız 13 kez.
- Engellenen ek 0. B0'daki katkı ve kaçırılan büyük kazanan da 0. Bu veriyle hiçbir şey söylenemez.

### B3 — başarısız kırılımdan erken çıkış → **C**
Ön-kayıttaki B ve C tanımları burada örtüşüyor: MDD biraz düşüyor ama getiri ve getiri/MDD ikisi de
düşüyor. Getiri/MDD düştüğü için C sayıldı.

**Botun 12 coini:**
- 217 B3 çıkışı (tüm dönem); B3'te toplam −17.416, B0'daki karşılıkları +8.834.
- Erken kapatılanlardan B0'da kazanan biten 41 işlem (+34.867), kaybeden biten 104 işlem (−26.033).
- Kaybedenlerden kurtarılan, kazananlardan kaçandan az.
- Fark aralığı [−78.222, −10.140].

**Diğer 24 coin:**
- 454 çıkış; B0'da 76 kazanan (+26.686), 238 kaybeden (−24.214).
- Fark aralığı [−29.813, +6.962]. Burada belirsiz, eğilim yine negatif.

## 4. Mevcut botla aynı hesapta (ortak sermaye ve teminat)

`birlesik.py`, pencere 2023-04-07 → 2025-08-08, botun ikiz işlem listesi (683 işlem bu pencerede).
- **Bot:** risk %3.5; teminat ikizdeki notional oranından.
- **Ortak teminat:** sınırı aşılırsa işlem atlanır.

| | aylık (geo) | toplam | MDD | doğrulama getiri | doğrulama MDD | atlanan bot işlemi (teminat) |
|---|---|---|---|---|---|---|
| yalnız bot | %16.7 | 88× | %35.2 | +%540 | %28.2 | 4 |
| bot + B0 | **%21.6** | 288× | %42.6 | +%1.639 | %42.6 | 5 |
| bot + B1 | %20.9 | 245× | %52.1 | +%1.398 | %52.1 | 6 |
| bot + B2 | = B0 | | | | | 5 |
| bot + B3 | %21.1 | 256× | %42.1 | +%1.546 | %42.1 | 4 |

- **Teminat yarışı neredeyse yok:** trend yalnız 1 ek bot işlemini teminat yüzünden engelledi.
- **Trend kolu birleşik hesapta da en iyi B0 ile:** ayda +~5 puan, buna karşılık MDD +~7 puan.
- **Sınırlama:** İkizde bot pozisyonlarının açık PnL'i yok. Hesap değeri kesitinde bot kısmı yalnız
  kapanışta görünüyor, bu yüzden bot kaynaklı düşüş eksik ölçülüyor; birleşik MDD gerçekte daha yüksek
  olabilir. Bileşik çarpanlar likidite ve kayma büyümesini içermez; gerçekçi değildir.

## 5. Sınırlamalar ve belirsizlik
- **Önceden incelenmiş veri:** Coinler ve dönemler trend parametrelerinin seçildiği veriyle örtüşüyor.
  Hiçbir sonuç bağımsız sınav değildir.
- **Mum içi belirsizlik:** Hesap değeri 4h kapanışlarıyla ölçülüyor; gün içi daha derin düşüşler görünmez.
  Stop dolumu stop fiyatı (çıkış kayması dahil) ya da boşlukta açılış. Aynı mumda tepe/dip sırası
  bilinmiyor; muhafazakâr kabul edildi (girişten sonraki ilk mumda da stop kontrolü).
- **Varyant etkisi:** B1 ve B3 sonuçları büyük ölçüde birkaç büyük trendin yolunun değişmesinden geliyor.
  İşlem bazlı fark aralıkları raporlandı.
- **Kapsam:** Eşik taraması ve kombinasyon yapılmadı (ön-kayıt gereği). Sonuçlar kötü çıktı diye yeniden
  denenmeyecek.

## 6. Dosyalar ve yeniden çalıştırma
- `ONKAYIT.md`: sonuçlardan önce sabitlenen kurallar (commit 9f48a95).
- `motor.py`, `veri.py`, `kos.py`, `birlesik.py`, `tests/test_durum.py`.
- `sonuclar/<koşu>/`:
  - `ozet.json`: karşılaştırma tablosu, manifest, varyant teşhisleri;
  - `islemler_<V>_<MALIYET>.csv`: varyant işlem kayıtları;
  - `hesap_degeri_<V>_<MALIYET>.csv.gz`: ortak zamanlı hesap değeri, 4h.
- **Komutlar** (repo kökünde):
  ```
  PYTHONPATH=. python3 -m pytest -q research/trend_gelistirme/tests/test_durum.py
  PYTHONPATH=. python3 -m research.trend_gelistirme.kos --evren bot12
  PYTHONPATH=. python3 -m research.trend_gelistirme.kos --evren diger24
  PYTHONPATH=. python3 -m research.trend_gelistirme.birlesik --ikiz-db <ikiz_trades.db>
  ```
  `ikiz_trades.db`: canlı-birebir ikizin `ikiz_tam.py` çıktısı (937 işlem).
