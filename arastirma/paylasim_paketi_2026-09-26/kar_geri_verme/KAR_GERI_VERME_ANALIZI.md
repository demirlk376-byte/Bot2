# Kazancı Geri Verme Analizi (2026-09-26)

Bu çalışma, düzeltilmiş ikizin mevcut 936 işleminin çevrimdışı olarak yeniden okunmasıdır.
Canlı kod, parametreler, süreçler ve emirler değiştirilmedi. Yeni filtre, strateji veya
optimizasyon koşulmadı. Eşikler (+0.5R, +1R, +1.5R) yalnız sayım için kullanıldı; çıkış
kuralı olarak test edilmedi.

**Yeniden çalıştırma** (repo kökünden, ~6 saniye, pandas + numpy):
```
python3 arastirma/kar_geri_verme/kar_geri_verme.py
```

**Girdiler:**
- `ikiz_k25_cap25_islemler.csv`: canlı ile birebir ikiz, 936 işlem, 2023-04-07 → 2026-07-19.
- `ikiz_k25_eski_islemler.csv`: yalnız §5 için.
- `data/{COIN}_fut_1h.csv`

**Çıktılar** (bu klasörde):

| dosya | içerik |
|---|---|
| `islem_mfe_mae.csv` | işlem başına MFE/MAE (kesin/üst sınır), çıkış nedeni, net sonuç, ekonomik çıkış işareti |
| `equity_saatlik.csv` | 28,759 saat işareti: bakiye, açık PnL, hesap değeri, pozisyon sayısı, long/short büyüklük, stoplara ek kayıp ve oranları |
| `giris_boyutlama.csv` | her girişte boyutlama tabanı, içindeki açık PnL, ima edilen taban, aynı/ters yönde açık pozisyon |
| `filtre_106.csv` | hacim filtresi karşılaştırmasındaki 126 + 20 işlemin sınıflandırması |
| `sonuclar.json` | rapordaki tüm sayılar |
| `kar_geri_verme.py` | analiz betiği |

**Etiketler:** **[H]** hesaplandı · **[B]** bar verisi belirsizliği · **[E]** eksik veri.

---

## 1. Analizin dayanağı

- **PnL yeniden kurulumu [H]:** Her işlem için

  ```
  pnl = yön × (çıkış − giriş) × miktar − giriş_ücreti − çıkış_ücreti
  giriş_ücreti = (0.0001 taker | 0 maker) × giriş × miktar
  çıkış_ücreti = 0.0001 × çıkış × miktar
  ```

  Sonuç `pnl_usdt` ile **936/936 uyuşuyor**. Tolerans 0.01$, uyuşmayan 0, en büyük fark
  3.4e-9$.
- **R tanımı:** `R_net = pnl_usdt / (miktar × |intended_entry − sl0|)`. Ortalama +0.1965,
  toplam +183.93R. CSV'deki `R` sütunu farklı tanımlı; hiçbir yerde kullanılmadı.
- **Funding:** İkiz PnL'inde **yok**. Burada da eklenmedi; başlangıç sonucu değiştirilmedi.
- **Zaman kuralları** (fiyat verisinde doğrulandı):
  - `ts` barın **açılış** saatidir.
  - Giriş, `entry_time` barının açılışında olur. Bu fiyat sinyal barının kapanışına,
    yani `intended_entry`'ye eşittir.
  - "T işareti", T anındaki durumu gösterir: fiyat olarak `ts = T−1h` barının **kapanışı**
    kullanılır.
- **Çıkış zamanı gecikmesi:**
  - Kayıtlı stop, hedef ve fiyat ile bar bar yürüyen simülasyon, çıkış tipini **936/936**
    eşledi (aynı mumda hem stop hem hedef değerse önce stop, ikizin kuralı).
  - Ekonomik çıkış, simülasyonun bulduğu barın içinde (SL/TP) ya da kapanışında (max-hold).
    Pozisyon o barın kapanış işaretinden itibaren **kapalı** sayıldı.
  - Kayıttaki `exit_time`, bu işaretten **906 işlemde 1 saat sonra**, **30 işlemde aynı
    saatte** yazılmış. 30'unda da tip ve bar eşleşiyor, yalnız kayıt damgası farklı.
  - Zaman çizelgesi her işlemde simüle edilen ekonomik çıkışı kullanıyor; kapanmış bir
    pozisyon fazladan bir saat açık sayılmıyor. Ham kayıtlar değiştirilmedi.
- **Başlangıç:** $10,000. Saatlik hesap değeri sonda csv toplamıyla aynı: **$791,666.20**.
  Veri sonunda açık pozisyon yok.

## 2. Saatlik hesap değeri ve açık pozisyon riski [H]

**Tanımlar:**
- Gerçekleşmiş bakiye = başlangıç + kapanmış işlemlerin `pnl_usdt`'si − açık pozisyonların
  (girişte ödenmiş) giriş ücreti.
- Açık PnL = Σ yön × (saat kapanış fiyatı − dolum fiyatı) × miktar.
- Hesap değeri = bakiye + açık PnL.
- Marjin zarar olarak düşülmedi. Ücretler ve gerçekleşmiş PnL bir kez sayıldı.
- Fiyat: her coinin **ortak saat kapanışı**; eksik barda son kapanış ileri taşındı.
  Farklı coinlerin saat içi high/low değerleri birleştirilmedi.

Açık pozisyon bulunan 19,517 saat işareti üzerinden:

| ölçü (hesap değerine oran) | %5 | medyan | %95 | %99 | uç |
|---|---|---|---|---|---|
| açık PnL | −%2.9 | +%0.8 | +%7.1 | +%11.6 | −%14.5 / +%21.6 |
| long toplam büyüklük | 0 | 0.55× | 3.02× | 4.90× | 9.04× |
| short toplam büyüklük | 0 | 0.73× | 3.78× | 5.49× | 9.64× |
| açıklar stoplarına giderse **ek** kayıp | −%19.3 | −%6.4 | −%1.8 | −%0.9 | **−%37.6** |

- **Aynı anda açık pozisyon sayısı** (tüm işaretler): 0: 9,242 · 1: 9,922 · 2: 5,675 ·
  3: 2,516 · 4: 814 · 5: 359 · 6: 151 · 7: 80.
- **En büyük düşüş:** Saatlik hesap değeriyle **%47.25**; yalnız gerçekleşmiş bakiyeyle
  %46.00. Bu değer saat kapanışlarından hesaplandı; tick düzeyindeki en büyük düşüş değildir **[B]**.
- **Stoplara ek kayıp** yalnız fiyat farkıdır. Çıkış ücreti, çıkış kayması ve stopu atlayan
  fiyat boşlukları dahil değil **[B]**.

## 3. İşlem içindeki kârın erimesi

**Nasıl ölçüldü:**
- Ölçü, dolum fiyatından itibaren 1h bar high/low değerleri; R payı `|intended_entry − sl0|`.
  Brüttür, maliyet içermez.
- Giriş barı tamamen girişten sonradır (giriş barın açılışında).
- Çıkıştan sonraki barlar dahil edilmedi.

**Çıkış barındaki belirsizlik [B]** (bu barda iki hareketin sırası bilinmiyor):
- **Stopla kapananlar:** Çıkış barındaki olumlu uç stoptan önce mi sonra mı bilinmiyor.
  MFE_kesin bu barı dışlar; MFE_üst onu da katar (hedefle sınırlı).
- **Hedefle kapananlar:** MAE için aynı mantık; MFE = hedef mesafesi.
- **Max-hold:** Çıkış kapanışta olduğu için bar tamamen işlemin içindedir.
- İki sınır, eşik sayımlarında en çok **1 işlem** farklı. Aynı mumda hem stop hem hedef
  1 işlemde oldu (XRP squeeze, ikiz önce stop saydı, MFE_üst 2.41R).

| kol (n; stopla biten) | ≥+0.5R gördü: zararla / kârla kapandı | ≥+1R gördü: zararla / kârla | ≥+1.5R gördü: zararla / kârla | stopla bitenlerden +0.5R / +1R / +1.5R'ye **hiç** ulaşmayan |
|---|---|---|---|---|
| donchian (412; 206) | 118 (%40.7) / 172 | 53 (%24.2) / 166 | 18 (%10.2) / 158 | 115 (%55.8) / 166 (%80.6) / 192 (%93.2) |
| squeeze (368; 201) | 107-108 (%41.8) / 149 | 58-59 (%28.7) / 144 | 19-20 (%12.6) / 132 | 107 (%53.2) / 152 (%75.6) / 187 (%93.0) |
| mean_rev (156; 69) | 35 (%31.5) / 76 | 12 (%14.5) / 71 | 4 (%6.3) / 59 | 44 (%63.8) / 63 (%91.3) / 68 (%98.6) |
| **hepsi (936; 476)** | **260-261 (%39.6)** / 397 | **123-124 (%24.4)** / 381 | **41-42 (%10.5)** / 349 | **266 (%55.9) / 381 (%80.0) / 447 (%93.9)** |

- "Zararla kapandı" = `R_net < 0`; stoplar ve zararlı max-hold çıkışları. Aralıklar
  kesin–üst sınırdır.
- **Okuma:**
  - +1R'ye ulaşan her 4 işlemden ~1'i zararla kapanıyor (123 işlem).
  - Stopla bitenlerin %80'i ise +1R'yi hiç görmedi.
  - Yani işlem düzeyinde kâr erimesi vardır ama stopların çoğu erimeden değil, hiç
    kâra geçmemekten geliyor.
- **Uyarı:** MFE, yakalanabilecek kâr değildir. Saatlik high değeri anlık bir uç olabilir;
  maliyet ve çıkışın uygulanabilirliği yok sayılmıştır.

## 4. En büyük üç düşüş (saatlik hesap değeri)

Ayrı ve örtüşmeyen düşüş dönemleri: tepeden, yeniden tepeye dönüşe kadar.

**Ayrıştırma kalemleri:**
- **A:** Tepede açık olan pozisyonların tepe → dip arasındaki **fiyat** PnL değişimi.
- **B:** Tepeden sonra açılanların dip anına kadarki **fiyat** PnL'i.
- **C:** Dönemde ödenen ücretler.
- Kayma, dolum fiyatının içinde; A/B'de sayıldı, C'de tekrar düşülmedi (yalnız bilgi olarak
  gösterildi).

| | 1 | 2 | 3 |
|---|---|---|---|
| tepe → dip | 2026-06-06 05:00 → 2026-07-18 17:00 | 2024-01-23 14:00 → 2024-04-13 07:00 | 2026-02-06 01:00 → 2026-05-04 05:00 |
| değer | $1,494,747 → $788,478 | $69,600 → $39,995 | $1,216,339 → $703,050 |
| düşüş | **−$706,269 (−%47.3)** · veri sonuna kadar toparlanmadı | **−$29,605 (−%42.5)** · 2024-08-04'te toparlandı | **−$513,290 (−%42.2)** · 2026-06-02'de toparlandı |
| A: tepede açık | −$81,007 (1 poz.) | **−$17,902 (7 poz.) = %60** | −$91,326 (2 poz.) |
| B: sonradan açılan | **−$617,696 (29 poz.) = %87** | −$10,835 (72 poz.) | **−$407,999 (56 poz.) = %79** |
| C: ücret | −$7,567 | −$869 | −$13,965 |
| açıklanamayan | −3.6e-9$ | −3.0e-10$ | −2.2e-9$ |
| bilgi: fiyat içindeki kayma | −$50,653 | −$6,014 | −$97,749 |
| B ort. R_net | −0.55 | +0.07 | −0.20 |
| **tepede:** açık / yön / büyüklük / açık PnL / stoplara ek | 1 / short / 0.35× / +%1.9 / −%5.4 | **7 / hepsi short / 6.19× / +%10.9 / −%34.4** | 2 / short / 0.77× / +%0.4 / −%7.5 |
| **dipte:** açık / büyüklük / açık PnL / stoplara ek | 2 / short 3.49× / −%6.7 / −%1.3 | 5 / short 2.48× / −%8.0 / −%11.3 | 1 / short 1.17× / +%1.2 / −%5.1 |

- **Kontrol:** A + B + C, üç dönemde de hesap değeri değişimine 1e-9$ içinde oturuyor.
- **Cevap: C (ikisi birlikte), portföy düzeyinde B baskın.**
  - En büyük iki düşüşün %79-87'si, tepeden **sonra açılan** işlemlerin zararından geliyor.
    Bunlar gerçekleşmiş stop serileri.
  - A yalnız 2024 dönemi için baskın (%60). O tepede 7 short pozisyon, hesap değerinin
    6.19 katı büyüklükle, +%10.9 açık kârla bekliyordu. Hepsi bu kârı geri verip ek zarar
    yazdı (açık kâr ≈ +$7,600 → A −$17,900).

### Hipotez: "Açık kâr boyutlama tabanını büyütüyor, sonra aynı yöndeki pozisyonlar birlikte kaybediyor"

**Dayanak [H]:**
- Boyutlamanın taban aldığı hesap değeri açık PnL'i **içeriyor** (`execution.py`'de
  `sizing_balance = equity`).
- Her girişte miktardan geri hesaplanan taban (`max(miktar × risk0 / 0.035,
  miktar × giriş / 2.5)`), yeniden kurulan saatlik hesap değerinin ortanca **1.000** katı
  (%5-95: 0.987–1.016). Aynı saatteki diğer girişler hariç tutuldu.

**Büyüklük:**
- Girişlerde açık PnL'in tabana oranı: medyan **0**, %75'lik dilim +%2.3, %95'lik dilim
  +%6.4, en fazla +%19.6.
- Düşüşlerde, B'deki zararlı işlemlerin "açık kâr yüzünden büyüyen" kısmı
  (zarar × girişteki açık kâr payı):
  - dönem 1: −$3,005 (B zararının %0.5'i)
  - dönem 2: −$1,444 (%13)
  - dönem 3: −$8,153 (%2)
  - Aynı mekanizma kazananlarda +$709 / +$1,580 / +$5,716 ekledi.

**Destekleyen örnekler:**
- Dönem 2 tepesi (yukarıda).
- 2023-09-11: BNB ve ETH donchian short'ları, taban içinde +%15.8 / +%14.5 açık kârla ve
  4-5 short zaten açıkken girildi; hepsi −1R.
- XRP squeeze short 2025-02-28 ve 2024-04-17: açık kâr payı %14, 3-5 aynı yönde açık; −1R.

**Zayıflatan örnekler:**
- Dönem 1 ve 3 tepelerinde 1-2 pozisyon ve ≤+%1.9 açık kâr vardı. Bu dönemlerdeki
  girişlerin medyan açık kâr payı **0**, medyan aynı yönde açık pozisyon sayısı **0**.
- En yüksek açık kâr payıyla girip kazananlar: BNB short 2024-08-04 (%19.6, +2.46R),
  ETH short 2023-08-17 (+2.41R), XLM short 2024-08-03 (+2.42R).

**Betimsel grup karşılaştırması:**

| girişteki durum | n | ort. R_net | kazanma |
|---|---|---|---|
| açık pozisyon yok | 375 | +0.178 | %43.7 |
| açık var, açık kâr ≤ 0 | 169 | +0.339 | %47.3 |
| açık kâr %0-3 | 197 | +0.205 | %42.1 |
| açık kâr > %3 | 195 | +0.099 | %38.5 |

- "> %3" eksi "açık yok" farkı: **−0.079R**, hafta-kümeli %95 aralık **[−0.37, +0.24]**.
  Anlamlı değil.
- "> %3" içinde aynı yönde açık pozisyon varken +0.056 (n=169), yokken +0.377 (n=26).
  Küçük örneklem, aralık hesaplanmadı. **Yalnız hipotez üretir.**
- **Sonuç:** Açık kârın tabanı büyütmesi gerçek ama küçük; en büyük düşüşlerin açıklaması
  değil. "Aynı yönde yoğun pozisyonların birlikte kaybetmesi" bir düşüşte (2024) belirgin,
  diğer ikisinde değil. Risk kuralı değiştirilmedi.

## 5. İki karşılaştırma notu

**Canlı–ikiz eşleştirmesi:** Bu çalışmada **canlı veri yok [E]**. Bu yüzden eşleştirme
yapılmadı ve hata oranı üretilmedi. Yapılacağında kurallar:
- Her dönem kendi gerçek ayarlarıyla karşılaştırılmalı. Örneğin Haziran–Temmuz'daki
  RR 2.0 / filtresiz canlı işlemler, bugünkü 2.5R / hacim filtreli ikizle doğrudan
  kıyaslanmamalı.
- Ayarı doğrulanamayan dönemler belirsiz işaretlenmeli.

**Hacim filtresi sayıları** (`filtre_106.csv`) **[H]:**
- Filtresiz koşudaki 1107 donchian işlemi (sembol, yön, giriş zamanı ile eşleştirildi):
  - **286** iki koşuda ortak
  - **801** hacim oranı < 2.5 (filtrenin elediği)
  - **20** oranı ≥ 2.5 ama filtreli koşuda yok ("yerinden edilen")
- 1107 − 801 = **306 = 286 + 20**.
- Filtreli koşu = **412 = 286 + 126**. 126 işlem yalnız filtreli koşuda var; hepsinin oranı
  ≥ 2.5.
- **412 − 306 = 106 = 126 − 20.**
- 126 işlemin kaynağı:
  - **118:** Filtresiz koşuda aynı coinin donchian yuvası, filtrenin elediği bir işlemle
    doluydu.
  - **2:** Filtresiz koşuda o coinde üst üste 2 zarar sonrası 240 dk bekleme vardı.
  - **6: açıklanamadı.** Eski koşunun risk (%2.8), CAP (1.5) ve TRX'li coin evreni farklı;
    marjin veya koltuk sınırı olabilir, kayıttan doğrulanamıyor.
- 20 yerinden edilen işlemin **20'si** de filtreli koşuda, yuvası yalnız filtreli koşuya
  özgü bir işlemle dolu olduğu için açılamadı.
- Bu yüzden 126 işlemin hepsi "filtrenin açtığı fırsat" değildir. 118'i yuva doluluğu
  zincirinin sonucu, 8'i kıyaslanan koşuların farklı ayarlarından. Bu turda rastgele eleme
  testi yapılmadı.

**$62.80 defter–borsa farkı:** Canlı veri bu çalışmaya verilmedi **[E]**. Repodaki son
kayıt (DURUM ~L1291-1320): fark kısmen izlendi (ücretler $22.80, funding $1.61, çıkış
fiyatları), tamamı açıklanmadı. **Farkın çözüldüğü varsayılmamalı.**

## 6. Ayrım

**Hesaplanan [H]:**
- PnL yeniden kurulumu (936/936).
- Çıkış eşleşmesi (936/936 tip; 906 kayıt +1 saat, 30 kayıt aynı saat).
- Saatlik seriler ve oranları.
- En büyük düşüş %47.25 (saat kapanışı) / %46.00 (gerçekleşmiş).
- MFE eşik sayımları.
- Üç düşüşün A/B/C ayrıştırması (kalan ~0).
- Boyutlama tabanının hesap değerine eşitliği.
- Filtre işlem eşleştirmesi.

**Bar verisi belirsizliği [B]:**
- Saat içi fiyat yolu bilinmiyor. Düşüş saat kapanışlarından; tick düzeyinde daha derin
  olabilir.
- Çıkış barındaki olumlu/olumsuz uç sırası belirsiz (kesin/üst sınır verildi; 1 işlem fark).
- Aynı mumda hem stop hem hedef: 1 işlem.
- Aynı saatteki girişlerin sırası bilinmiyor.
- Açık PnL ve stoplara ek kayıp, çıkış ücreti ve kaymasını içermiyor.

**Eksik [E]:**
- Canlı işlem veritabanı: canlıda A/B/C, canlı–ikiz eşleştirmesi, $62.80.
- Dakika veya tick verisi.
- İkizde funding.
