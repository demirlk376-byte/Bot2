# TREND_TAKİP_V1 — sonuç (2026-10-02)

**KARAR (önceden yazılmış kurallarla): KANIT YETERSİZ** (`VALIDATION_UNCERTAIN`).
**Ancak şimdiye kadarki en güçlü ve en tutarlı olumlu sonuç bu.**
- Keşifte 12 varyantın **12'si de pozitif**.
- Doğrulamaya seçilen 3 adayın **3'ü de pozitif**.
- Kayma iki katına çıkınca sonuç neredeyse değişmiyor (geniş stoplar).

Final dönemi (2025-08 → 2026-10) kurallar gereği AÇILMADI.

- **Koşu:** `20261002T213122Z_5260611d_c079966c`. Kurallar: `MANIFEST.md` (commit `5260611`,
  veriden önce).
- **Teknik düzeltme:** Koşu sırasında yalnız eksik gün varken funding'in atlanması düzeltildi
  (ICP 26 gün, diğerleri ≤5 eksik gün). Kurallar değişmedi.
- **Veri:** Binance USDⓈ-M 1d, 2020 → 2026-10; MEXC venue vekili.

## Keşif (2021-01 → 2024-06, 3.45 yıl), işlem başı risk %0.25
| varyant | işlem | ort. net R | PF | hesap getirisi | maks düşüş | ort. tutuş |
|---|---|---|---|---|---|---|
| N50_X5_L | 105 | +0.49 | 2.16 | +%12.9 | %7.5 | 43 gün |
| N50_X3_L | 152 | +0.33 | 1.72 | +%12.4 | %7.3 | 16 gün |
| N100_X5_LS | 116 | +0.33 | 1.89 | +%9.4 | %6.5 | 52 gün |
| N50_XH_LS | 150 | +0.40 | 2.14 | +%14.9 | %15.6 | 68 gün |

Diğer 8 varyant da pozitif: tablo `sonuclar/.../selection_discovery.json`.

## Doğrulama (2024-06 → 2025-08, 1.15 yıl)
| varyant | işlem | ort. net R | PF | getiri | maks düşüş | durum |
|---|---|---|---|---|---|---|
| N50_X5_L | 40 | +0.94 | 3.52 | +%9.3 | %8.9 | 50 işlem tabanı altında |
| N100_X5_LS | 38 | +1.00 | 5.52 | +%9.4 | %7.5 | 50 işlem tabanı altında |
| N50_X5_LS | 67 | +0.43 | 2.12 | +%7.2 | %9.3 | LCB ≤ 0 |

## Büyük yükselişleri yakalıyor mu? (N50_X5_L, 2021-01 → 2025-08, coin başına en büyük 2)
- **24 büyük yükselişin 22'sine girdi.** Bu yükselişlerden toplam +105R aldı.
  Karşılaştırma: NW+KAMA 24'ün 9'u.
- Örnekler:

  | coin | yükseliş | alınan |
  |---|---|---|
  | BNB 2021 | +%656 | +15.2R |
  | XLM 2024 | +%521 | +13.9R |
  | TRX 2024 | +%177 | +11.4R |
  | XRP 2024 | +%422 | +9.3R |
  | ICP 2023 | +%258 | +9.1R |

## Dürüst uyarılar
- **Kâr birkaç dev işlemde yoğunlaşıyor; trend takibinin doğası bu.**
  - İşlemlerin yalnız %31–45'i kazanıyor.
  - En iyi 5 işlem çıkarılınca keşifte +1.291 → +108 USDT, doğrulamada +934 → −123 USDT.
  - Yani kazanç, yılda birkaç büyük trendi yakalamaya bağlı. O trendler gelmezse sistem küçük
    zararlarla bekler.
- **Örneklem az ve GA geniş:** Güven aralığı alt sınırları sıfırın hafif altında.
- **2021 boğa piyasası keşif döneminde.** Ama doğrulama (2024-06 → 2025-08) da pozitif.
- **Final dönemi** (2025-08 → 2026-10) açılmadı. İleriye dönük paper test gerekir.
- **Vekil veri:** Fiyatlar Binance; MEXC'te kayma ve funding farklı olabilir.

## Riske göre ölçekleme (kaba; bileşik değil, geçmiş veri)
| işlem başı risk | keşif (3.45 yıl) | yıllık ≈ | doğrulama (1.15 yıl) | olası maks düşüş |
|---|---|---|---|---|
| %0.25 (test) | +%13 | ~%4 | +%9 | ~%8–9 |
| %0.5 | +%26 | ~%7 | +%19 | ~%15–18 |
| %1 | +%52 | ~%13 | +%37 | ~%30–36 |
