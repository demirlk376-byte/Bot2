# Pairs sermaye / kaldıraç mimarisi testi

**HÜKÜM: B — pairs edge'i düşük kaldıraçta TEST'te pozitif, ama ekonomik takas zayıf.**
- 12 hücreden hiçbiri USEFUL değil; sağlam bölge yok.
- Anlamlı bir DD düşüşü için fazla getiri feda ediliyor.
- Getiri üretecek kaldıraçta da izole bacaklar tasfiye oluyor.

Sinyal, execution ve maliyet `pairs_dual_twin` ile birebir aynı (modül içe aktarılıyor):
- 8 sabit çift; z 2.0/0.5/3.5; ZWIN 60; 20 gün; 1D.
- Dolum: D+1 01:00 1h açılışı.
- Maliyet: BASE 15.85bp/dolum + 1bp taker.

Değişen yalnız sermaye/kaldıraç mimarisi. Ana bot ikizi yeniden koşulmadı; doğrulanmış
saatlik hesap değeri kullanıldı.

Koşum: `python3 arastirma/pairs_capital_architecture/pairs_capital_architecture.py` (~4 dk, çevrimdışı).

**Çıktılar:**
- `scenario_table.csv`: 12 hücre, TRAIN + TEST, yoğunlaşma, negatif aylar
- `liquidation_events.csv`
- `sonuclar.json`

## 1. Önceden sabit mimari (sonuçtan önce yazıldı)

**Hücreler:** pairs payı {%10, %20, %30} × izole kaldıraç {1x, 3x, 5x, 10x}, toplam 12.

**Boyut:**
- Her çiftin ayrı izole slotu var. İşlem anında marjin = pairs hesap değeri / 8, bacak
  başına yarısı.
- nominal = marjin × kaldıraç; PnL = nominal × kaldıraçsız çift getirisi.
- Ücret ve kayma nominal üzerinden.
- Pairs hesabı kendi içinde bileşik büyür (ana bot gibi). Hesaplar arası para akışı yok.
- Serbest marjin yetmezse işlem reddedilir.

**Likidasyon** (muhafazakâr MEXC izole yaklaşımı, bakım oranı %1):

| bacak | tasfiye eşiği (ters hareket) |
|---|---|
| long | ≥ (1/L − 0.01)/(1 − 0.01) |
| short | ≥ (1/L − 0.01)/(1 + 0.01) |

| kaldıraç | eşik |
|---|---|
| 1x | ~%98 (short) |
| 3x | ~%32 |
| 5x | ~%19 |
| 10x | ~%9 |

- Kontrol saatlik high/low ile, dolum anından itibaren yapılıyor.
- Bir bacak eşiğe değerse o bacağın marjininin **tamamı kaybedilir**. Karşı bacak bir sonraki
  1h açılışta kayma + ücretle kapatılır; işlem z-çıkışına yaşatılmaz.
- Gerçek exchange likidasyon motoru değil; kasıtlı olarak muhafazakâr.

**Pencereler:**
- TRAIN: ana ikiz başı → 2025-01-01. TEST: 2025-01-01 → son.
- Her pencere, pencere başında sabit payla yapılmış **ayrı bir dağıtım**: açık pozisyon devri
  yok, pencere içinde yeniden dengeleme yok.

**USEFUL** (TEST, hepsi birlikte):
1. likidasyon = 0
2. pairs TEST getirisi > 0
3. birleşik maxDD ≤ baseline − 3 puan
4. birleşik getiri ≥ baseline'ın %90'ı (≥ +455.6%)
5. PGR ≤ baseline

**Hüküm kuralları:**
- **A:** Birbirine komşu en az iki hücre USEFUL **ve** bu hücrelerde TRAIN likidasyonu da 0.
  Likidasyon riski döneme özgü değil, yapısal kabul edildi. Komşu = aynı pay ve bitişik
  kaldıraç, ya da aynı kaldıraç ve bitişik pay.
- **C:** Her hücrede TEST likidasyonu > 0, **veya** likidasyonsuz her hücrede en iyi 3 işlem
  çıkarılınca pairs TEST getirisi ≤ 0.
- **B:** Diğer durumlar.
- **D:** Lookahead veya veri sorunu.

## 2. Baseline (ana bot %100, TEST)

- Getiri **+506.2%**, maxDD **%47.3**, PGR **0.759**.
- En kötü ay −26.7%, medyan ay +10.1%, pozitif ay %68.
- getiri/DD 10.71. maxDD dönemi sonunda toparlanma yok.

## 3. Senaryo tablosu (TEST)

Δ = hücre − baseline.

| pay | kaldıraç | TEST getiri | Δgetiri | maxDD | ΔmaxDD | PGR | TEST lik. | TRAIN lik. | pairs TEST | USEFUL |
|---|---|---|---|---|---|---|---|---|---|---|
| 10% | 1x | +456.3% | −49.9 pp | %46.8 | −0.50 | 0.758 | **0** | 2 | +6.7% | NO (DD) |
| 10% | 3x | +456.7% | −49.5 pp | %46.7 | −0.52 | 0.760 | 11 | 15 | +11.0% | NO |
| 10% | 5x | +456.0% | −50.2 pp | %46.8 | −0.49 | 0.760 | 46 | 61 | +4.3% | NO |
| 10% | 10x | +446.6% | −59.7 pp | %47.2 | −0.05 | 0.764 | 208 | 207 | **−90.4%** | NO |
| 20% | 1x | +406.3% | −99.9 pp | %46.1 | −1.10 | 0.758 | **0** | 2 | +6.7% | NO |
| 20% | 3x | +407.2% | −99.0 pp | %46.1 | −1.16 | 0.764 | 11 | 15 | +11.0% | NO |
| 20% | 5x | +405.8% | −100.4 pp | %46.2 | −1.09 | 0.767 | 46 | 61 | +4.3% | NO |
| 20% | 10x | +386.9% | −119.3 pp | %47.1 | −0.10 | 0.770 | 208 | 207 | −90.4% | NO |
| 30% | 1x | +356.4% | −149.9 pp | %45.4 | −1.86 | 0.758 | **0** | 2 | +6.7% | NO |
| 30% | 3x | +357.7% | −148.6 pp | %45.3 | −1.96 | 0.767 | 11 | 15 | +11.0% | NO |
| 30% | 5x | +355.6% | −150.6 pp | %45.4 | −1.84 | 0.777 | 46 | 61 | +4.3% | NO |
| 30% | 10x | +327.2% | −179.0 pp | %47.1 | −0.18 | 0.792 | 208 | 207 | −90.4% | NO |

- Likidasyon sayıları bacak olayıdır.
- Pairs TEST getirisi paydan bağımsızdır (oran).
- Marjin reddi: TEST'te 0, TRAIN'de 1-3.
- Lookahead ihlali 0.

**Ana botun negatif aylarında pairs katkısı (TEST, 19 ayın 6'sı negatif):**
- 1x ve 3x hücrelerde küçük pozitif: 6 negatif ayın 3'ünde pairs pozitif, toplam +$8 ile +$31.
- 5x ve 10x'te negatif: −$11 ile −$412.

**Ana botun en kötü 5 ayı (TEST):**
- Baseline ortalaması −15.1%.
- En iyi hücrede (30%×1x) −13.7%. Yani en iyi durumda ~1.4 puan yumuşama.

## 4. Neden hiçbir hücre USEFUL değil?

**Getiri kriteri ile DD kriteri aynı anda sağlanamıyor:**
- Pairs TEST getirisi en iyi +11% (3x), ana bot +506%.
- Bu yüzden getiri kriteri (%90'ı koru) pratikte yalnız %10 payla sağlanabiliyor. %10 payda
  da DD düşüşü yalnız 0.5 puan; eşik 3 puan.
- DD'yi 3 puan düşürmek için gereken pairs payı, getiriyi %90 eşiğinin çok altına çekiyor.
  Kazanan bir ara bölge yok.

**Kaldıraç ikilemi (yapısal):**
- Pairs'in kaldıraçsız çift getirisi küçük (işlem başı ~%0.66 net).
- Sermayeye anlamlı getiri için yüksek maruziyet gerekiyor. Eski boyut, bu şemada slot
  başına ~8x demek.
- 3x'te bile TEST'te 11, TRAIN'de 15 bacak tasfiyesi var. 5x'te 46/61. 10x'te pairs hesabı
  TEST'te **−90%**.
- 1x'te TEST temiz, ama TRAIN'de 2 tasfiye var: XLM short (2024-11-23, %99.9 ters hareket)
  ve ALGO short (2024-11-29, %103.5). **Kaldıraçsız short bile, iki katına çıkan bir coinde
  izole modda tasfiye olur.**

**Kaldıraçsız getiri yetersiz:** 1x'te pairs TEST getirisi +6.7% (yaklaşık 18.5 ayda). Ana
botun %10'luk payının yerine konunca portföyü değiştirecek büyüklükte değil.

## 5. Yoğunlaşma (TEST, pairs hesabı)

| kaldıraç | tümü | −1 en iyi | −3 en iyi | −5 en iyi |
|---|---|---|---|---|
| 1x | +6.7% | +3.5% | **+0.7%** | **−0.03%** |
| 3x | +11.0% | +2.8% | **−4.8%** | −7.5% |
| 5x | +4.3% | −2.5% | −10.0% | −13.0% |
| 10x | −90.4% | −92.9% | −93.7% | −94.2% |

TEST kârı birkaç işleme bağlı:
- 3x'te en iyi 3 işlem çıkarılınca negatif.
- 1x'te en iyi 5 işlem çıkarılınca sıfır.

Önceki `pairs_dual_twin` uyarısıyla tutarlı.

## 6. Güncel sermaye fizibilitesi (strateji ekonomisinden ayrı)

**UNCERTAIN.**
- ALGO, DOT ve ETC'nin `contractSize` ve min kontrat bilgisi repoda yok.
- MEXC public metadata bu ortamdan erişilemiyor (ağ politikası 403).
- Bilinenler (probe_hedge2): ETH 1 kontrat $19.09, BTC $6.45; diğerleri < $2.

Örnek: canlı $334'ün %10'u = $33.4 pairs hesabı. 1x'te slot başı marjin $4.2, bacak nominali
~$2.1. Bu, ETH ve BTC bacaklarının 1 kontrat minimumunun **altında** kalıyor. Yani mevcut
sermayede %10-30 pay ve 1x ile BTC/ETH ve ETC/ETH çiftleri açılamaz.

## 7. Hüküm gerekçesi

- **Neden A değil:** Hiçbir hücre USEFUL değil; sağlam bölge yok.
- **Neden C değil (kurala göre):**
  - 1x hücrelerinde TEST likidasyonu 0 (her hücrede > 0 koşulu sağlanmıyor).
  - 1x'te en iyi 3 işlem çıkarılınca pairs TEST getirisi hâlâ +0.7% (tüm temiz hücrelerde
    ≤ 0 koşulu sağlanmıyor).
- **Sonuç B.** Edge var ama ekonomik takas zayıf.
- **Ciddi uyarılar (B'nin içinde):**
  - ≥3x her hücrede TEST'te likidasyon var.
  - 1x'te bile TRAIN'de 2 short bacak tasfiyesi var.
  - TEST kârı 3-5 işleme bağlı.

**Sonraki adım yok:** A çıkmadığı için `pairs_paper_forward_v2` kurulmadı.
- Denenmeyen mimari sorular ayrı ve önceden kayıtlı test gerektirir: cross-marjin ve dönemsel
  yeniden dengeleme.
- Pair listesi, z parametreleri ve çıkış mantığı değiştirilmedi.
