# Pairs alt-hesap ikizi + ana bot ikizi (kronolojik, ayrı hesap)

**HÜKÜM: B — pairs edge'i gerçekçi execution'da ayakta, ama çift-hesap birleşimi önceden
sabit kriterlerin ikisini geçemiyor. Birincisi 10x izole marjinde yapısal likidasyon
sorunu (kriter 10), ikincisi TEST'te getiri/DD bozuluyor (kriter 8). Production'a geçilmez.**

Koşum: `python3 arastirma/pairs_dual_twin/pairs_dual_twin.py` (repo kökünden, çevrimdışı, ~50 sn).

**Çıktılar:**
- `pairs_trades.csv`: BASE, her işlem iki bacak, audit alanları
- `combined_monthly.csv`
- `drawdown_episodes.csv`
- `sonuclar.json`

## 0. Dondurulmuş aday ve eski semantik (değiştirilmedi)

**Çiftler:** ETC/ETH · ATOM/DOT · BTC/ETH · ADA/DOT · XLM/XRP · ALGO/DOT · ADA/ALGO · ADA/ATOM

**Sinyal:**
- Veri: 1D, spread `log(A/B)`.
- z: rolling 60 gün, gün D dahil, yalnız geçmiş.
- Giriş |z| ≥ 2.0. z > 0 → A short / B long; z < 0 → A long / B short.
- Çıkış: |z| < 0.5, |z| > 3.5 ya da 20 gün.
- Çıkıştan sonra yeni sinyal ertesi günden itibaren.

**Eski sizing** (`pairs_spread.py` / `pairs_verify.py` / `pairs_margin.py`):
- Her çift işlemi **toplam nominal = BAL0** ($190), bacak başına yarısı. Bileşik **yok**.
- `$ = ret × BAL0`, `ret = (r_A + r_B)/2 − 4 × 0.0001`.
- **Normalize eşdeğer:** B hesabının başlangıç değeri `B0`; her işlemin nominali `B0`,
  sabit, bileşik yok.

**Eski execution (artık yasak):**
- Giriş ve çıkış, sinyal gününün **kapanış fiyatından**.
- Eski kod `fast_bt.resample(..., "1d")` günlük kapanışlarını kullanıyordu.

**Eski sonucun yeniden üretilmesi (`ESKI_AYNI_KAPANIS_4bp` modu):**

| | n | PF | toplam | yıllar |
|---|---|---|---|---|
| Ledger (2026-08-02) | 260 | 1.63 | $+532 | +179 / +141 / +82 / +129 |
| Bu harness | 258 | 1.65 | %284.6 × $190 = $+541 | $+178 / +143 / +95 / +125 |

Harness eski bulguyu yeniden üretiyor.

## 1. Execution ve nedensellik

**Zamanlama:**
- Günlük bar D = UTC [D 00:00, D+1 00:00), MEXC **vadeli** 1h barlarından
  (`data/{COIN}_fut_1h.csv`; ts = bar açılışı).
- D kapanışı = D 23:00 barının close'u; **bilgi zamanı = D+1 00:00**.

**Dolum:**
- Bilgi zamanından **sonra başlayan** ilk 1h barın açılışı, yani **D+1 01:00 open**.
- 00:00 barının açılışı bilgi anına **eşit** olduğu için kullanılmadı (assert `>`).
- Çıkış için de aynı kural geçerli.

**Lookahead:** Tüm maliyet senaryolarında ihlal **0**. Ayrıca `entry_time > signal_time`
yazılı olarak assert edildi.

**İki bacak:**
- İkisi aynı barın açılışından dolar.
- 1h veride bacak gecikmesi modellenemez. Bu bir **modelleme sınırıdır**; paper-forward'da
  ayrıca ölçülmesi gerekir.
- Test geçse bile "production-ready" denemez.

**Maliyet:**
- Her dolumda (4 dolum/işlem) ters kayma: LOW 10bp, BASE 15.85bp, STRESS 25bp.
- Taker ücreti 1bp/dolum (`execution.py` `_close_position_internal` ve `entry_fee_rate` = 0.0001).

## 2. Pairs tek başına

Getiriler B hesabının başlangıç değerine göre; bileşik yok.

| senaryo | n | PF | WR | toplam | TRAIN | TEST | 2023 | 2024 | 2025 | 2026 | maxDD | en kötü ay | poz. ay |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| eski aynı-kapanış 4bp | 258 | 1.65 | %59 | +284.6% | +168.6% | +116.0% | +93.6 | +75.1 | +50.1 | +65.9 | %30.4 | −17.4% | %60 |
| yeni sonraki-bar 4bp | 258 | 1.57 | %61 | +254.5% | +156.3% | +98.2% | +85.4 | +70.9 | +29.7 | +68.5 | %31.9 | −18.8% | %60 |
| LOW 10bp | 258 | 1.43 | %59 | +202.1% | +127.9% | +74.2% | +74.5 | +53.4 | +14.8 | +59.4 | %36.1 | −22.5% | %52 |
| **BASE 15.85bp** | **258** | **1.36** | %59 | **+171.4%** | **+111.2%** | **+60.1%** | **+68.1** | **+43.2** | **+6.1** | **+54.1** | **%39.5** | −24.9% | %52 |
| STRESS 25bp | 258 | 1.25 | %58 | +123.4% | +85.2% | +38.2% | +58.0 | +27.2 | **−7.6** | +45.7 | %45.7 | −29.3% | %50 |

- **Yıl sütunları:** Sinyal yılına göre, %.
- **Ortalama net işlem getirisi:** BASE +0.664%, STRESS +0.478% (nominal üzerinden).
- **BASE çıkışları:** z_out 109, max_hold 92, z_stop 57.
- **Sonraki-bar etkisi:** Execution'ın tek başına etkisi küçük (PF 1.65 → 1.57). Edge'i asıl
  eriten gerçekçi maliyet: 4bp → 15.85bp ile PF 1.36'ya iniyor.
- **2025 zayıf:** BASE'te +6.1%, STRESS'te −7.6%.

## 3. Çift bazında (BASE; betimsel, seçim yapılmadı)

| çift | n | toplam | PF | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|
| XLM/XRP | 33 | +59.8% | 1.83 | +27.6 | +4.0 | −9.4 | +37.5 |
| ADA/DOT | 34 | +52.7% | 2.00 | +11.8 | +6.7 | +24.9 | +9.3 |
| ADA/ATOM | 36 | +42.1% | 1.62 | +4.1 | −5.2 | +46.8 | −3.6 |
| ADA/ALGO | 30 | +31.7% | 1.66 | +17.8 | +6.0 | +1.7 | +6.2 |
| ETC/ETH | 30 | +29.6% | 1.77 | +15.8 | +15.9 | −13.7 | +11.7 |
| ATOM/DOT | 29 | +3.2% | 1.06 | −1.0 | +16.1 | −1.9 | −10.0 |
| BTC/ETH | 31 | −19.7% | 0.64 | −1.5 | +15.4 | −29.1 | −4.5 |
| ALGO/DOT | 35 | −28.0% | 0.70 | −6.6 | −15.7 | −13.1 | +7.4 |

**CONCENTRATION RISK:** Kârın büyük kısmı 3-4 çiftte (XLM/XRP, ADA/DOT, ADA/ATOM). İki çift
net negatif. 8 çift sabit; hiçbiri çıkarılmadı.

## 4. En iyi işlemleri çıkarma (BASE)

| çıkarılan | toplam | TEST | pozitif yıl |
|---|---|---|---|
| 0 | +171.4% | +60.1% | 4/4 |
| 1 | +136.4% | +60.1% | 4/4 |
| 3 | +72.9% | **−3.4%** | 3/4 |
| 5 | +34.7% | −3.4% | 2/4 |
| 10 | **−32.3%** | −42.4% | 2/4 |

**Kâr birkaç şanslı işleme bağlı.**
- En iyi 3 işlem çıkarılınca TEST negatife dönüyor.
- En iyi 10 işlem çıkarılınca toplam negatif.
- Bu, eski "en iyi 10 işlem kârın %77'si" uyarısının gerçekçi maliyetle daha ağır hali.

## 5. Marjin ve likidasyon (BASE, 10x izole)

**Marjin:**
- Marjin reddi **0**. En çok 8 çift aynı anda açık.
- En yüksek brüt nominal 8.0 × B0, en yüksek kullanılan marjin 0.80 × B0.

**Likidasyon (gerçek exchange likidasyonu simüle edilmedi, PnL buna göre düzeltilmedi):**
- Bacak başına saatlik high/low ile en büyük ters hareket (MAE) ölçüldü.
- 10x izole bir bacağın likidasyon eşiği yaklaşık %9.5 (1/10 − ~%0.5 bakım).

| kaldıraç (izole) | eşik | eşiği aşan işlem (258'den) |
|---|---|---|
| **10x** | %9.5 | **185** |
| 5x | %19.5 | 83 |
| 3x | %32.5 | 26 |
| 2x | %49.5 | 7 |

- Medyan en büyük bacak MAE %14.5. En büyüğü %114.6: ALGO/DOT, ALGO short, Kasım 2024
  (ALGO ve XLM rallisi gerçek).
- **Yapısal sonuç:** İzole marjinle pairs, backtest'teki gibi yaşayamaz. Bacaklar tek tek
  tasfiye olur. Tasfiye olmamak için gereken kaldıraç ~0.9x, yani izole modda imkânsız.
- **Cross marjin:** Hesap düzeyinde en büyük düşüş %39.5 olduğu için tarihte hesap
  tasfiyesi görünmüyor. Ama bu ayrı bir tasarım kararı ve bu testin kapsamında değil.
- **Kriter 10 → FAIL.**

## 6. Ana botla çeşitlendirme

- **Aylık korelasyon (40 ay):** Pearson **−0.161**, Spearman **−0.154**.
- **Ana botun negatif ayları: 12.** Pairs bunların 7'sinde pozitif. Toplam pairs katkısı
  +69.0% (B hesabı getirisi toplamı), dual tahsisle $+7,463.

**Ana botun en kötü 5 ayı:**

| ay | ana | pairs | dual |
|---|---|---|---|
| 2026-07 | −26.7% | +4.7% | −24.6% |
| 2024-04 | −22.5% | +5.1% | −8.4% |
| 2026-04 | −19.9% | −2.7% | −18.7% |
| 2023-04 | −15.2% | 0.0% | −3.8% |
| 2025-08 | −14.7% | −2.9% | −12.4% |

**TRAIN'den dondurulmuş ağırlıklar** (2023-2024 aylık std, ters-oynaklık):
- Aylık std: ana 32.8%, pairs 11.0%.
- Buna göre **w_main 0.252, w_pairs 0.748**. TEST boyunca sabit.

## 7. Birleşik portföy

Toplam sermaye $10,000; iki senaryoda aynı. Hesaplar arasında para akışı yok.

| | dönem | getiri | CAGR | maxDD | maxDD $ | en kötü ay | medyan ay | poz. ay | getiri/DD | PGR | sualtı |
|---|---|---|---|---|---|---|---|---|---|---|---|
| BASELINE | TÜM | +7843% | +279.5% | %47.3 | $708,652 | −26.7% | +10.4% | %70 | 166.0 | 0.727 | 1171g |
| DUAL | TÜM | +2102% | +156.6% | %44.7 | $177,207 | −24.6% | +6.4% | %72 | 47.0 | 0.710 | 1175g |
| BASELINE | TRAIN | +1211% | +340.2% | %42.5 | $56,443 | −22.5% | +14.1% | %71 | 28.5 | 0.730 | 621g |
| DUAL | TRAIN | +388% | +149.2% | **%25.0** | $15,434 | −8.4% | +6.4% | %76 | 15.5 | **0.675** | 619g |
| BASELINE | TEST | +506.2% | +221.2% | **%47.3** | $708,652 | −26.7% | +10.1% | %68 | **10.71** | **0.759** | 548g |
| DUAL | TEST | +351.2% | +165.3% | **%44.7** | $177,207 | −24.6% | +6.3% | %68 | **7.86** | **0.769** | 555g |

**Büyük düşüş epizodları** (baseline; `drawdown_episodes.csv`):

| tepe → dip | baseline DD | dual DD | toparlanma baseline → dual |
|---|---|---|---|
| 2023-07 → 08 | %38.0 | **%7.6** | 35g → 0.2g |
| 2024-01 → 04 | %42.5 | **%18.0** | 194g → 111g |
| 2024-12 → 2025-03 | %34.4 | **%18.4** | 125g → ~0g |
| 2026-02 → 05 | %42.2 | %39.7 | 117g → 117g |
| 2026-06 → 07 | %47.3 | %44.7 | dönmedi → dönmedi |

**Neden TEST'te etki kayboluyor?** Bu, testin önemli bir yapısal bulgusu:
- Ana hesap **bileşik** büyüyor (risk % ile boyutlanıyor). Pairs hesabı eski semantik
  gereği **sabit nominal**, bileşik yok. Hesaplar arasında para akışı da yasak.
- Bu yüzden 2026'ya gelindiğinde ana hesap birleşik değerin çok büyük kısmı; pairs'in
  dolar etkisi sulanmış durumda.
- 2023-2024 düşüşlerinde pairs düşüşü yarıya indiriyor. 2026 düşüşlerinde neredeyse
  hiçbir şey yapmıyor.
- Yani çeşitlendirme gerçek, ama bu sermaye yapısında zamanla sönüyor.
- Periyodik yeniden dengeleme hesaplar arası para aktarımı gerektirir; bu testte yasaktı
  ve denenmedi.

## 8. Önceden sabit kriterler (BASE)

| # | kriter | sonuç |
|---|---|---|
| 1 | pairs TRAIN > 0 | ✓ +111.2% |
| 2 | pairs TEST > 0 | ✓ +60.1% |
| 3 | 4/4 yıl + | ✓ (2025 yalnız +6.1%) |
| 4 | PF ≥ 1.20 | ✓ 1.36 |
| 5 | aylık korelasyon ≤ +0.20 | ✓ −0.161 |
| 6 | ana negatif aylarda pairs toplamı > 0 | ✓ +69.0% (7/12 pozitif) |
| 7 | dual TEST maxDD < baseline TEST maxDD | ✓ %44.7 < %47.3 (küçük fark) |
| 8 | dual TEST getirisi bozulmuyor (**getiri/maxDD ≥ baseline**; önceden tanım) | ✗ 7.86 < 10.71 |
| 9 | STRESS ortalama işlem getirisi ≥ 0 | ✓ +0.478% (ama 2025 −7.6%) |
| 10 | margin/likidasyon yapısal hatası yok | ✗ **10x izolede 185/258 işlemde bacak likidasyon eşiği aşılıyor** |

- 1-4 geçti → edge gerçekçi execution'da ayakta.
- 8 ve 10 başarısız → **B**.
- Kriter 8 tanımı: "bozulmuyor" veri görülmeden **getiri/maxDD ≥ baseline** olarak sabitlendi.
- Profit giveback TEST'te de kötüleşiyor: 0.759 → 0.769.

## 9. Güncel sermaye fizibilitesi (strateji ekonomisinden AYRI)

**Tahsis:** Canlı bakiye $334 ve TRAIN ağırlığı kullanılırsa pairs alt-hesabı yaklaşık **$250**
(bacak başına ~$125), ana hesap yaklaşık **$84** olur.

**Pairs tarafında min kontrat** (probe_hedge2, 1 kontrat):

| coin | min kontrat | kontrat adedi (~$125 bacak) | yuvarlama hatası |
|---|---|---|---|
| ETH | $19.09 | 6.5 | ~%8 |
| BTC | $6.45 | 19 | ~%2 |
| ADA / ATOM / XLM / XRP | ihmal edilebilir | — | ihmal edilebilir |

ALGO, DOT ve ETC'nin kontrat boyutu repoda yok.

**Sorunlar:**
- Ana hesabın $84'e düşmesi ana botun kendi min-notional ve CAP sınırları için ayrı bir sorun.
- İzole likidasyon sorunu (bölüm 5) bu sermayede de geçerli.

**CURRENT-CAPITAL FEASIBILITY: UNCERTAIN.** Bu "strateji kötü" demek değil, "henüz deploy
edilebilir yapı yok" demek.

## 10. Eski iddia vs yeni sonuç

| | ESKİ (aynı kapanış, 4bp, tek hesap) | YENİ (sonraki bar, BASE 15.85bp+1bp, ayrı hesap) |
|---|---|---|
| işlem | 260 | 258 |
| PF | 1.63 | 1.36 |
| TEST | +$211 (≈ +111%) | +60.1% |
| 4/4 yıl | ✓ (+179/+141/+82/+129 $) | ✓ ama 2025 +6.1% (STRESS'te −7.6%) |
| korelasyon | −0.362 (eski kitapla) | −0.161 (canlı-birebir ikizle) |
| birleşik DD | "kötü aylarda denge" | TRAIN'de güçlü (%42.5 → %25.0), TEST'te zayıf (%47.3 → %44.7) |

**Özet:**
- Edge'in çoğu gerçekçi maliyette korunuyor. Execution artefaktı değil; aynı-kapanış dolumu
  PF'i yalnız ~0.08 şişiriyordu.
- Ama edge, eski bulgunun gösterdiğinden daha ince ve birkaç işleme yoğunlaşmış.
- 10x izole marjinde yapısal olarak uygulanamaz.

## 11. B sonrası (bu turda yapılmadı)

- Parametre, çift, z eşiği, stop, OLS beta değiştirilmedi; hiçbir çift çıkarılmadı.
- A çıkmadığı için paper-forward kurulmadı.

Olası ayrı, önceden kayıtlı sorular (yalnız not):
- Cross-marjin alt-hesap tasarımı
- Hesaplar arası dönemsel yeniden dengeleme
