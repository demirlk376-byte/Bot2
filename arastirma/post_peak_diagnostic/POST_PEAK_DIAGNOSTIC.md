# Post-peak teşhisi (2026-09-27)

**Soru:** Bot güçlü trend dönemlerinde kazanıp sonra geri veriyor. Girişten **önce**
gözlenebilen hangi durumda bunu fark edemiyor?

Çevrimdışı teşhis çalışması. Production dosyaları, `.env`, canlı süreç ve emirler
değiştirilmedi; commit yapılmadı. Filtre veya threshold optimizasyonu yok: sürekli
değişkenler yalnız sabit Q1-Q5 dilimleriyle betimlendi, hipotez tanımları sonuçlar
görülmeden kodda sabitlendi.

**Yeniden çalıştırma** (repo kökünden, ~30 sn):
```
python3 arastirma/post_peak_diagnostic/post_peak_diagnostic.py
```

**Çıktılar:**

| dosya | içerik |
|---|---|
| `entry_state.csv` | 936 işlem × giriş anı özellikleri + R_net + dönem etiketi |
| `ozellik_tablosu.csv` | her özellik ve grup için n, ort R, WR, TRAIN/TEST |
| `hipotezler.json` | etki büyüklükleri, hafta-kümeli bootstrap %95 aralıkları (2000 tekrar), H1-H4, sağlamlık kontrolleri |

## 0. Dayanak doğrulaması

- `ikiz_k25_cap25_islemler.csv` = **936 işlem**. Kaynak: `kar_geri_verme` çalışması,
  commit `e7574fa`.
- İkiz motor dosyaları (`ikiz/`, `main.py`, `execution.py`, `risk.py`, `strategies/`,
  `config.py` vb.), canlı-birebir ikizin sabitlendiği commit'ten (`56914fb`) bu yana
  **değişmedi** (`git diff` boş).
- O tarihte yeni CANLI_ENV ile koşulan taban, bu listeyle işlem-işlem aynıydı
  (938 satır, özet `8e3fa541ec60`).
- Bu tur ikiz aynı ayarla bir kez daha çevrimdışı koşuldu: sonuç §6'da.

**Baseline:** 936 işlem, ort R_net **+0.1965**.

**Bölme:** Burada TRAIN/TEST **giriş zamanına** göre yapıldı; önceki çalışmalar çıkış
zamanını kullanıyordu, 1 işlem farklı.

| bölüm | n | ort R_net |
|---|---|---|
| TRAIN (giriş < 2025-01-01) | 539 | +0.201 |
| TEST | 397 | +0.190 |

**Lookahead kuralları:**
- 1h bar zaman damgası = açılış. T girişinde bilinen son 1h kapanış, ts = T−1h barıdır.
- 4h barlar UTC 0/4/8 başlangıçlı. Yalnız T anında kapanmış 4h barlar kullanıldı.
- EMA200, en az 200 kapanmış 4h bardan önce **boş** bırakıldı; ilk ~33 gün tahmin edilmedi.
- Portföy durumu: T'den önce açılmış ve ekonomik çıkışı T'den sonra olan pozisyonlar.
  Aynı saatte açılanlar hariç.
- Strateji geçmişi: yalnız ekonomik çıkışı ≤ T olan (kapanmış) Donchian işlemleri.
  Ekonomik çıkış zamanı `kar_geri_verme` analizindeki `cikis_isaret`'ten alındı; kayıttaki
  geç `exit_time` kullanılmadı.

## 1. Özellik tablosu (etki = üst grup − alt grup, R_net; hafta-kümeli %95 aralık)

`*` işareti aralığın sıfırı dışladığını gösterir. Tüm gruplar için: `ozellik_tablosu.csv`.

**Tüm işlemler (936)**

| özellik | karşılaştırma | HEPSİ | TRAIN | TEST | yön tutarlı? |
|---|---|---|---|---|---|
| BTC 24h getiri | Q5−Q1 | +0.19 [−0.14, +0.50] | +0.35 | −0.02 | hayır |
| BTC 48h getiri | Q5−Q1 | +0.15 [−0.24, +0.54] | +0.34 | −0.11 | hayır |
| BTC 48h, işlem yönünde | Q5−Q1 | −0.16 [−0.50, +0.18] | −0.24 | −0.02 | evet |
| BTC EMA200 uzaklığı (ATR) | Q5−Q1 | +0.24 [−0.12, +0.58] | +0.42 | −0.12 | hayır |
| BTC ATR/fiyat | Q5−Q1 | −0.27 [−0.64, +0.14] | −0.13 | −0.40 | evet |
| BTC ardışık 4h mum, işlem yönünde | ≥4 − 1 | +0.11 [−0.28, +0.49] | +0.05 | +0.22 | evet |
| BTC 24h işlemle hizalı | evet − hayır | −0.12 [−0.35, +0.13] | −0.19 | −0.02 | evet |
| EMA200 üstü coin oranı | Q5−Q1 | +0.21 [−0.14, +0.55] | +0.25 | +0.16 | evet |
| açık PnL / equity | Q5−Q1 | −0.20 [−0.54, +0.13] | −0.25 | −0.12 | evet |
| **ATH'den düşüş** | Q5−Q1 | **+0.52 [+0.18, +0.87]\*** | +0.68\* | +0.35 | evet |
| önceki 5 Donchian R | Q5−Q1 | −0.39 [−0.80, +0.02] | −0.29 | −0.64\* | evet |
| önceki 10 Donchian R | Q5−Q1 | −0.40 [−0.81, +0.01] | −0.66\* | −0.14 | evet |
| aynı yönde açık | 3+ − 0 | −0.23 [−0.72, +0.31] | −0.24 | −0.23 | evet |
| son 72h Donchian girişi | 3+ − 0 | −0.18 [−0.56, +0.25] | −0.09 | −0.36 | evet |
| Donchian ardışık kayıp | 3+ − 0 | +0.18 [−0.09, +0.47] | +0.19 | +0.17 | evet |

**Yalnız Donchian (412)**

| özellik | karşılaştırma | HEPSİ | TRAIN | TEST |
|---|---|---|---|---|
| ATH'den düşüş | Q5−Q1 | +0.83 [+0.20, +1.34]\* | +1.13\* | +0.51 |
| önceki 10 Donchian R | Q5−Q1 | −0.82 [−1.40, −0.26]\* | −1.51\* | −0.43 |
| önceki 5 Donchian R | Q5−Q1 | −0.76 [−1.30, −0.20]\* | −0.63 | −1.07\* |
| aynı yönde açık | 3+ − 0 | −0.91 [−1.36, −0.29]\* | −1.00\* | −0.86\* (**n=20; TEST n=6**) |
| gross notional/equity | Q5−Q1 | −0.62 [−1.09, −0.09]\* | −0.73\* | (TEST'te Q1 boş) |
| BTC EMA200 uzaklığı | Q5−Q1 | +0.33 [−0.21, +0.83] | +0.54\* | +0.18 |

**Çoklu karşılaştırma uyarısı:**
- ~27 özellik × 2 alt küme × 3 dilim ≈ 160 aralık hesaplandı.
- %5 düzeyinde yalnız şansla ~8 "yıldız" beklenir.
- Tek dilimde görülen yıldızlar kanıt sayılmamalı.

## 2. Hipotezler (tanımlar önceden sabit, `hipotezler.json`)

| | tanım | HEPSİ fark [%95] | TRAIN | TEST | hüküm |
|---|---|---|---|---|---|
| **H1** | \|BTC 48h\| Q5 VE son 4h mum 48h yönüne ters | −0.23 [−0.86, +0.46], n=19 | +0.06 | −0.73 (n=7) | **desteklenmiyor** |
| H1b | \|BTC 48h\| Q5 VE son 4h mum aynı yönde (koşu sürüyor) | −0.26 [−0.55, +0.03], n=168 | −0.30 | −0.21 | zayıf, anlamsız |
| **H2** | 7/7 coin işlem yönünde VE BTC zayıflıyor | −0.19 [−0.61, +0.23], n=59 | −0.01 | −0.35 | **desteklenmiyor** |
| H2b | 7/7 coin 24h'te işlem yönünde | **−0.245 [−0.47, −0.02]\***, n=398 | −0.24 [−0.53, +0.03] | −0.26 [−0.64, +0.10] | **kısmen:** iki yarı aynı yön, tek başına anlamsız |
| **H3** | son 72h ≥3 Donchian girişi vs 0 | −0.18 [−0.57, +0.23], n=91 | −0.09 | −0.36 | **desteklenmiyor** |
| H3b | aynı yönde ≥2 açık vs 0 | +0.04 [−0.27, +0.35] | −0.15 | +0.37 | desteklenmiyor (yön değişiyor) |
| **H4** | önceki 10 Donchian R Q5 vs Q1-Q4 | −0.08 [−0.39, +0.23] | −0.22 | +0.13 | **desteklenmiyor** |
| H4c | hesap ATH'nin %2 içinde vs değil | **−0.45 [−0.74, −0.14]\***, n=124 | **−0.52 [−0.84, −0.16]\*** | −0.34 [−0.88, +0.23] | **kısmen:** TRAIN anlamlı, TEST aynı yön |

**H5** — "para bas → geri ver", pozitif beklentili ama yüksek varyanslı sistemin normal
stop kümeleriyle açıklanabilir mi? **Büyük ölçüde evet.**
- Önceki çalışmalar: kayıp serileri ve düşüşler iki null modelde de şans içinde; gözlenen
  yol karıştırılmış yollardan bile yumuşak (ledger 2026-09-26).
- Bu çalışma: BTC rejimi bir işaret vermiyor; yön TRAIN ile TEST arasında değişiyor.
- Kalan iki zayıf bağımlılık (H2b, H4c) toplamda küçük. ATH yakını 124 işlem × −0.19R
  ≈ −24R; toplam +184R'nin yanında.
- Yani davranışın çoğu varyans. Buna **zayıf bir negatif seri bağımlılık** eşlik ediyor
  (bkz. aday 1).

### Kullanıcı gözlemi: "BTC'de art arda güçlü yönlü mumlar"

Veri bunu desteklemiyor:
- BTC'nin işlem yönünde ≥4 ardışık 4h mumla koştuğu anda açılan işlemler **biraz daha iyi**
  (+0.11R; TRAIN +0.05, TEST +0.22; anlamsız).
- Koşu sonrası BTC zayıflaması (H1) seyrek (19 işlem) ve iki yarıda ters yönlü.
- BTC getiri ve EMA özellikleri TRAIN'de pozitif, TEST'te negatif. Sabit bir BTC rejim
  etkisi yok. Bu, ledger'daki BTC/çapraz-varlık ekseninin null sonucuyla tutarlı.

## 3. Dönem etiketleri (döngüsel, kanıt değil)

| dönem | n | ort R_net |
|---|---|---|
| normal | 769 | +0.278 |
| equity tepesinde açık | 10 | −0.722 |
| tepeden sonra açılan | 157 | −0.144 |

Bu dönemler, zaten bu işlemlerin zararlarıyla tanımlandığı için fark döngüseldir. Mekanizma
kanıtı olarak kullanılmadı; bunun yerine girişte bilinen "ATH'den düşüş" değişkenine bakıldı.

## 4. Sonuç: **MEKANİZMA ADAYI VAR** (iki zayıf aday, ikisi de TEST'te tek başına kanıtlanmadı)

### Aday 1 — Başarı sonrası zayıflık / strateji düzeyinde negatif seri bağımlılık

Hesap ATH'ye yakınken açılan işlemler daha kötü, derin düşüşteyken açılanlar daha iyi.

**Kanıt:**
- H4c: −0.45R [−0.74, −0.14]. TRAIN −0.52\*, TEST −0.34 (aynı yön).
- Donchian'da ATH'den düşüş Q1: −0.19R; Q5: +0.64R. İki yarıda da Q5 > Q1.
- Sağlamlık (`hipotezler.json` → `saglamlik`):
  - Üç büyük düşüş penceresi dışarıda bırakılınca da sürüyor: −0.49 [−0.78, −0.17];
    TEST −0.46 (anlamsız).
  - Kırılım kollarında aynı işaret: donchian −0.57\*, squeeze −0.69\*.
  - mean_rev'de ters: +0.30 (n=14). Kontra-trend kol olduğu için beklenebilir.
- Aynı olgunun ayna görüntüsü: önceki 10 Donchian işleminin en kötü dilimi (Q1) sonrasında
  Donchian işlemleri +0.97R (TRAIN +1.60, n=27; TEST +0.65, n=53).
- Ledger'daki bağımsız bulgularla tutarlı: haftalık R lag-1 −0.13; kötü seri sonrası
  daha iyi; DD'de durmak 36/36 zarar.

**Karşı kanıt ve riskler:**
- TEST aralığı sıfırı içeriyor.
- Q2-Q5 dilimleri düzgün sıralanmıyor.
- 2% sınırı sabit ama tek bir seçim.
- Ledger'daki "portföy kâr kilidi" (başarı sonrası risk azaltma) maliyetsiz ankorda
  13/13 başarısızdı. O test eski tabandaydı, ama uyarı değeri var.

### Aday 2 — Piyasa genişliği tamamen tek yönlüyken açılan kırılımlar zayıf

Donchian evrenindeki 7 coinin 7'si de son 24h'te işlem yönünde hareket etmişken açılan
işlemler daha kötü.

**Kanıt:**
- H2b: −0.245R [−0.47, −0.02], n=398 (TRAIN −0.24, TEST −0.26; ikisi de tek başına anlamsız).
- Donchian'da daha güçlü: +0.05 vs +0.55, fark −0.50 [−0.89, −0.11]; TRAIN −0.60\*,
  TEST −0.33.
- Büyük düşüş pencereleri dışarıda da sürüyor: −0.245.

**Örtüşme:** Aday 1 ile kısmen bağımsız.

| durum | n | ort R |
|---|---|---|
| ikisi birden | 75 | −0.34 |
| yalnız 7/7 genişlik | 323 | +0.15 |
| yalnız ATH yakını | 49 | +0.04 |
| hiçbiri | 489 | +0.33 |

**Risk:** İşlemlerin %43'ü bu durumda. Donchian kırılımı doğası gereği hareketle birlikte
geldiği için bu koşul "piyasa geneli hareket"in bir vekili olabilir. Ledger'daki
eşzamanlılık bulgusuyla (kalabalık aylar iyi aylar) gerilim içinde.

### Tek önerilen sonraki deney (uygulanmadı)

**Önceden kayıtlı dış-örneklem ölçümü; strateji değişikliği yok.**

1. İki tanımı **aynen** dondur: `port_dd_ath ≤ 0.02` ve `gen_islem_yonunde == 1.0`
   (7/7 coin). Başka varyant koşma.
2. Bu çalışmada kullanılmamış bir dönemde, **2023-04 öncesi** (ör. 2021-01 → 2023-03),
   canlı-birebir ikizi aynen koş. Önce bu döneme ait 1h MEXC futures verisinin
   bulunabildiği doğrulanmalı. Veri yoksa ileriye dönük canlı + ikiz birikimini bekle.
3. Tek ölçüm: iki koşulun işlem R'sine etkisi. Hafta-kümeli %95 aralık ve aynı yön şartı.
4. Yalnız ikisi de o dönemde aynı yönde ve aralığı sıfırı dışlarsa bir sonraki adım
   düşünülür. O adım da filtre değil, **tek bir önceden kayıtlı boyut varyantı** olur
   (ör. koşul altında riskin yarısı), portföy düzeyinde iki yarı kuralıyla.

## 5. Claude'un dikkatini çeken beklenmedik bulgular

1. **Kötü seriden sonraki işlemler belirgin biçimde iyi.** Önceki 10 Donchian işleminin
   en kötü beşte-birinden sonra gelen Donchian işlemleri +0.97R: TRAIN +1.60 (n=27),
   TEST +0.65 (n=53). Q2-Q5 arası +0.15 ile −0.13 arasında. Bu, "düşüşte küçült/dur"
   kurallarının neden sürekli zarar ettirdiğinin doğrudan bir açıklaması. Ama Q1 dışında
   monoton değil; tek dilim olduğu için edge sayılmamalı.
2. **Aynı yönde 3+ açık pozisyonla açılan Donchian işlemleri −0.60R** (n=20; TRAIN −0.55
   n=14, TEST −0.72 n=6). İki yarıda da negatif, ama örneklem çok küçük.
   `MAX_SAME_DIRECTION=3` portföy testi 2026-09-26'da doğru ikizde TRAIN −1.48 / TEST
   +1.48 çıkmıştı. İşlem düzeyindeki bu zayıflık portföy kuralına çevrilince fayda
   vermiyor. Tekrar test edilmemeli.
3. **Özellik dağılımları TRAIN ile TEST arasında kayıyor.** Örneğin gross notional/equity'nin
   en düşük beşte-birinde TEST'ten hiç işlem yok (CAP ve hesap büyüklüğü dönemle değişti).
   Tüm örneklem üzerinden kurulan quantile dilimleri bu yüzden iki yarıda aynı anlama
   gelmiyor. Bu tür özellikler yarı içi quantile ile yeniden okunmalı (yapılmadı).
4. **BTC özelliklerinin işareti iki yarıda tersine dönüyor** (24h/48h getiri, EMA200
   uzaklığı). Kullanıcının BTC-mum gözlemi için olumsuz bir kanıt ve TRAIN'e bakıp BTC
   kuralı kurmanın neden tehlikeli olduğunun örneği.
5. **mean_rev, kırılım kollarının tersine davranıyor:** ATH yakınında +0.30 (n=14).
   Küçük örneklem, ama portföy düzeyinde bir koşula tüm kolları aynı anda bağlamanın yanlış
   olacağını düşündürüyor.

## 6. İkiz yeniden koşum doğrulaması

2026-09-27'de, değişmemiş motorla ve canlı ayarlarla (CANLI_ENV + gerçek maliyet: giriş
15.85bp, çıkış 0.24bp) `ikiz_tam.py` çevrimdışı yeniden koşuldu. Çıktı repo dışına taşındı;
repoya dosya eklenmedi.

| ölçü | değer |
|---|---|
| yeniden koşumdaki kapanmış işlem | **936** |
| referansla eşleşen (sembol, yön, giriş zamanı) | **936** |
| çıkış zamanı ve pnl_usdt birebir aynı (±1e-6$) | **936** |
| eksik / fazla işlem | yok / yok |
| toplam R_net (referans → yeniden) | 183.929697 → 183.929697 (fark 0.0) |
| ortalama R_net farkı | 0.0 |
| **sonuç** | **PASS** |

Not: Koşu sonu hesap değeri $801,516. Bu, veri sonunda hâlâ açık pozisyonların
gerçekleşmemiş PnL'ini (+$9,850) içeriyor. Kapanmış işlem listesi ve toplamı referansla
aynı ($791,666).

## 7. Next experiment readiness (yalnız not)

Tanımlar, raporda kullanılan kesin formüllerle (`post_peak_diagnostic.py`); eşikler
değiştirilmedi.

**1. `port_dd_ath <= 0.02`**

```
T              = entry_time (giriş barının açılışı)
close_c(T)     = coin c'nin ts ≤ T−1h olan son 1h kapanışı
açık(T)        = {i : giris_i < T  ve  cikis_isaret_i > T}   # aynı saatte açılanlar hariç
kapalı(T)      = {i : cikis_isaret_i ≤ T}
V(T)           = 10000 + Σ_{kapalı} pnl_usdt_i − Σ_{açık} ucret_giris_i
                 + Σ_{açık} yon_i × (close_{c_i}(T) − entry_price_i) × quantity_i
ATH(T)         = max( max{ hesap_degeri(z) : z < T },  V(T) )   # equity_saatlik.csv
port_dd_ath    = 1 − V(T) / ATH(T)
```

- `ucret_giris = entry_fee_rate × entry_price × quantity`.
- `cikis_isaret` = `kar_geri_verme` analizindeki ekonomik çıkış işareti.

**2. `gen_islem_yonunde == 1.0`**

```
Evren          = {SOL, ETH, ADA, NEAR, BCH, ICP, BNB}  (7 Donchian coini)
r_c(T)         = close_c(T) / close_c(T−24h) − 1
                 # close_c(T−24h) = ts ≤ T−25h olan son 1h kapanış
gen_islem_yonunde = ortalama_c [ sign(r_c(T)) == yon ]   # yon: long +1, short −1
```

- 7 coinden biri eksikse değer boş (NaN).
- `== 1.0`: 7 coinin 7'sinin de 24h getirisi işlem yönünde.

**Dış-örneklem verisi (2021-01 → 2023-03): UNAVAILABLE**

- Repodaki `data/{COIN}_fut_1h.csv` dosyalarının 13'ü de (SOL, ETH, ADA, NEAR, BCH, ICP,
  BNB, XRP, DOGE, XLM, LTC, BTC, TRX) **2023-04-06/07'de başlıyor**. İstenen 27 ayın
  hiçbiri yok.
- Mevcut veri kaynağı (`fast_bt.load`, `source="mexc_futures"`) yalnız **"şimdi − 1200 gün"**
  penceresini çekiyor (`fast_bt.py:95`). Bugün bu pencere ~2023-06'dan başlıyor; o
  dönem bu kaynakla da gelmez.
- MEXC API'nin daha eski 1h futures geçmişi sunup sunmadığı kontrol **edilmedi**: ağ
  isteği veri indirmek sayılırdı.
- Repodaki diğer veriler (Binance BTC/ETH 1m, BTCDOM 4h) de 2025-2026 dönemine ait ve
  MEXC futures değil.
