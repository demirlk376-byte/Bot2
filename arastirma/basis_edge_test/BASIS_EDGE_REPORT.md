# MEXC perp–spot BASIS → Donchian kırılım kalitesi (önceden kayıt)

**Durum: VPS KOŞUSU BEKLİYOR.**
- MEXC spot verisi yerelde yok. Bu ortamdan borsaya erişim de kapalı (ağ politikası 403).
- Spot 4h mumları yalnız VPS'ten, public API ile indirilebilir.
- Aşağıdaki tanımlar ve kurallar **sonuç görülmeden** sabitlendi.

## 0. Kapsam ve eski eksenler

**Yeniden açılmayan, kapanmış eksenler:**
- OI 4h (hüküm C)
- funding
- OHLCV filtreleri
- ATH/genişlik (hüküm C)
- aynı-yön maruziyet
- YAPI
- trailing/BE

Bu test **yalnız** perp–spot basis içindir. Repoda basis aracı yoktu; bu klasörde sıfırdan
yazıldı.

## 1. Veri

- **Perp:** Repodaki `data/{COIN}_fut_1h.csv`. Bu, doğrulanmış canlı-birebir ikizin girdisi;
  git'te izleniyor, VPS'te de aynısı var.
  - `ts` = 1h bar **açılışı**.
  - 4h'e UTC 00/04/08/12/16/20 hizasıyla toplanır, yalnız 4 saati de olan barlar alınır.
  - `close` = son 1h close.
- **Spot:** MEXC **SPOT** `{COIN}USDT`, `GET https://api.mexc.com/api/v3/klines?interval=4h`.
  - Public; anahtar yok, emir yok.
  - `openTime` = bar **açılışı**.
  - Aynı venue ve aynı quote (USDT). Binance veya başka borsa kullanılmaz.
- **İşlemler:** `ikiz_k25_cap25_islemler.csv`, kol = donchian.
  - 412 işlem: TRAIN (giriş < 2025-01-01) 235, TEST 177.
  - `R` = ikizin kanonik R_net'i.

## 2. Zaman hizalaması (lookahead)

- **Giriş zamanı:** Donchian girişi sinyal 4h barının **kapanışında** olur. İkizde girişlerin
  %100'ü 4h sınırında.
- **Sinyal barı:** açılışı = `entry_time − 4h`.
- **Basis barı:** Aynı açılış zamanına sahip perp ve spot 4h barı. **ffill yok**; iki taraftan
  biri yoksa işlem geçersiz.
- **Bilgi zamanı:** `basis_information_time = bar kapanışı = entry_time`.
- **Assert:**
  - `basis_information_time ≤ signal_time ≤ entry_time`
  - önceki pencerenin son barı < sinyal barı (mevcut bar trailing istatistiğe girmez)
  - Tek bir ihlal bile olursa sonuç **TEST INVALID**.

## 3. Tek özellik (başka dönüşüm yok)

```
basis_bp            = (perp_close / spot_close − 1) × 1e4
önceki pencere      = sinyal barından ÖNCEKİ 180 adet 4h ızgara slotu (30 gün), mevcut bar HARİÇ
                      (≥ 162 slot dolu olmalı, yoksa geçersiz)
basis_z             = (basis_bp − median) / (1.4826 × MAD)     (1.4826×MAD < 0.5bp → geçersiz)
directional_basis_z = +basis_z (long) / −basis_z (short)
CROWDED             = directional_basis_z ≥ +1.0     (eşik sabit)
```

**Hipotez:** directional_basis_z arttıkça R_net düşer. Yani rho < 0 ve
delta_R = ort(CROWDED) − ort(NORMAL) < 0.

## 4. Kapılar ve Stage A (sabit)

**Veri kapısı:**
- TRAIN ve TEST kapsamı ayrı ayrı ≥ %70.
- Geçerli işlem TRAIN ≥ 100, TEST ≥ 80.
- Her Donchian coininde spot verisi olmalı.
- Sağlanmazsa **D — DATA INSUFFICIENT**. Eksik işlemler coin × neden × yıl olarak raporlanır,
  sessizce atılmaz.

**Veri kalitesi:**
- Coin başına raporlananlar: spot ilk/son bar, duplicate, ortak bar sayısı, basis
  medyan/p1/p99, >200bp sıçrama.
- **|basis| > 500bp** noktaları **silinmez**, ayrı listelenir.

**Stage A PASS için hepsi gerekli:**

| # | koşul |
|---|---|
| 1 | TRAIN Spearman rho < 0 |
| 2 | TEST rho < 0 |
| 3 | TEST hafta-kümeli bootstrap ortalama rho < 0 ("etki yönü negatif") |
| 4 | TRAIN delta_R < 0 |
| 5 | TEST delta_R < 0 |
| 6 | TEST CROWDED n ≥ 30 |
| 7 | TRAIN CROWDED n ≥ 30 |
| 8 | TRAIN **ve** TEST delta_R ≤ −0.15R |
| 9 | TEST delta_R hafta-kümeli %95 GA **tamamen < 0** |

- Bootstrap: ISO hafta kümesi, 5000 tekrar, tohum 20260928.
- Theil-Sen eğimi (R_net ~ z) betimsel olarak verilir.
- Yıl, coin ve yön kırılımları betimseldir; filtre üretilmez.

**FAIL → "BASIS EDGE YOK / KANIT YETERSİZ".** İkiz koşulmaz; eşik veya lookback kurcalanmaz.

## 5. Stage B (yalnız Stage A PASS olursa)

- **Tek varyant: `BASIS_CROWDING_HALF_RISK`.** Yalnız Donchian'da, giriş anında
  directional_basis_z ≥ +1.0 ise risk × 0.50, aksi halde × 1.00.
- **Replay:** Gerçek kronolojik ikiz. Çarpan boyutlama adımında uygulanır.
  `kar_geri_verme_risk_test` harness'iyle aynı yöntem kullanılır; production dosyaları
  kalıcı değişmez.
- **Başarı** (TEST, hepsi):
  1. maxDD ≥ 3 puan azalır
  2. getirinin ≥ %95'i korunur
  3. PGR iyileşir
  4. en kötü ay kötüleşmez
  5. TRAIN aynı yönde
  6. capture/marjin yan etkisi küçük
- **Sonuç:** Bunların hepsi sağlanırsa PROMISING HISTORICAL CANDIDATE, aksi halde REJECTED.
  Production'a uygulanmaz.
- **Uygulama notu:** Stage B için spot verisinin (`/tmp/basis_edge_test/spot_4h/`) bu
  araştırma ortamına getirilmesi gerekir. Replay ~20 dakika sürer ve canlı botun yanında
  VPS'te koşturulmaz.

## 6. Doğrulama (çevrimdışı, sentetik spot)

| senaryo | sonuç |
|---|---|
| etkisiz sentetik basis | Stage A **FAIL** |
| kaybeden işlemlere işlem yönünde +4σ basis yerleştirildi | **PASS** (rho −0.72, delta −2.7R, GA [−2.9, −2.5]) |
| spot verisi yok | **D** |

**Etkisiz senaryodaki şans farkı:** Etkisiz veride şans eseri TEST delta −0.34R çıktı, ama GA
sıfırı içeriyordu ([−0.85, +0.22]). Kriter 9 bunu doğru şekilde reddetti.

**Lookahead:** 412 işlemin hepsinde bilgi zamanı ≤ giriş ve sinyal barı + 4h = giriş. İhlal 0.

## 7. VPS komutları

```
cd /opt/bot2 && git pull
venv/bin/python arastirma/basis_edge_test/basis_edge_test.py --indir
venv/bin/python arastirma/basis_edge_test/basis_edge_test.py
```

## Sonuç

_(VPS çıktısı gelince eklenecek.)_
