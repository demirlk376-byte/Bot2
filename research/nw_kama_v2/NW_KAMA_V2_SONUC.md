# NW+KAMA V2 — sonuç (2026-10-02)

**KARAR: KANIT YETERSİZ** (`VALIDATION_UNCERTAIN`). Ama bu sefer **gerçek bir olumlu işaret var**:
günlük (1D) kombo iki ayrı dönemde de pozitif. Örneklem, önceden yazılmış eşikleri aşmaya
yetmedi. Final dönemi kurallar gereği AÇILMADI; sonucu bilinmiyor ve bakılmadı.

## Koşu
- **run_id:** `20261002T202722Z_9ef5ca4f_d40b2916` (commit `9ef5ca4`)
- **Kurallar:** `MANIFEST.md` (önceden kayıt `331facb`) + "Düzeltme 1".
- **Teknik düzeltme:** Dönem sonu giriş yasağı tutuş süresine eşitlendi. Sinyal, eşik ve
  parametrelerin hiçbiri değişmedi. İlk koşu INVALIDATED olarak saklandı.
- **Altyapı:** Sweep V1'in aynısı.
  - Veri: Binance USDⓈ-M 5m, 12 coin.
  - Maliyet: 15.85bp giriş kayması, 0.24bp çıkış kayması, 1bp/taraf komisyon; STRESS kaymalar ×2.
  - Risk: işlem başı 25 USDT.
  - İstatistik: 4 haftalık blok bootstrap.

## Keşif (2023-02-12 → 2025-04-18), 24 varyant
| grup | sonuç |
|---|---|
| 1h (6 varyant) | hepsi negatif: −0.07 ile −0.15R; çoğunun GA'sı sıfırın altında |
| 2h (6) | hepsi negatif ya da sıfır: −0.006 ile −0.09R |
| 4h (6) | −0.08 ile +0.01R; kenar yok |
| **1D (6)** | **5'i pozitif.** Örneklem eşiğini geçen ikisi doğrulamaya seçildi |

| varyant | işlem | ort. net R | %95 GA | PF | STRESS R |
|---|---|---|---|---|---|
| **1D_event_A** | 107 | **+0.178** | [−0.024, +0.379] | 1.46 | +0.159 |
| 1D_state_A | 173 | +0.052 | [−0.141, +0.260] | 1.13 | +0.036 |
| 1D_agree_A (örneklem az) | 48 | +0.264 | [−0.13, +0.67] | 1.71 | +0.240 |
| 1D_event_B (örneklem az) | 55 | +0.085 | [−0.21, +0.39] | 1.27 | +0.070 |
| 1D_state_B (örneklem az) | 95 | +0.034 | [−0.16, +0.22] | 1.12 | +0.020 |
| 1D_agree_B (örneklem az) | 26 | −0.109 | | 0.77 | −0.122 |

## Doğrulama (2025-04-18 → 2026-01-08)
| varyant | işlem | ort. net R | %95 GA | PF | durum |
|---|---|---|---|---|---|
| **1D_event_A** | 41 | **+0.252** | [−0.013, +0.501] | 2.05 | örneklem tabanı (50) altında, pozitif |
| 1D_state_A | 57 | +0.142 | [−0.166, +0.437] | 1.43 | LCB ≤ 0 |

## 1D_event_A teşhisi (seçime girmez)
- **Keşif:**
  - 12 coinin 8'inde pozitif; long +0.10R, short +0.22R.
  - Yıllar: 2023 +0.05, 2024 +0.24, 2025 +0.40.
  - En iyi 5 işlem çıkarılınca +457 → +210 USDT.
- **Doğrulama:**
  - 12 coinin 10'unda pozitif; long +0.28R, short +0.23R.
  - En iyi 5 çıkarılınca +254 → **+16 USDT**. Bu kırılgan.
- **Eski çalışmayla uyum:** 1D_event_A, `validate_nw_kama.py` GRID'inin ilk satırı ve
  `nw_kama_tracker.py`'nin ETH+AVAX için ileriye dönük izlediği config'in aynısı (3,15,1.5,5,lb1).
- **Kenarın nereden geldiği:** Günlük zaman diliminde stop mesafesi geniş (2×ATR günlük), bu
  yüzden 15.85bp kayma R'nin küçük bir kesri. Kısa zaman dilimlerinde aynı sinyal maliyet
  altında eziliyor.

## Sonraki adımlar (öneri; yeni deney sürümü gerektirir)
1. **İleriye dönük kanıt:** VPS'teki `nw_kama_tracker.py` (2026-07-14'ten beri ETH+AVAX, 1D event)
   sonucunu oku. Bu, hiç ayar yapılmamış gerçek gelecek veri.
2. **Bağımsız evrende ön-kayıtlı tekrar:** Aynı kurallar, bu 12 coinin DIŞINDAKİ likit coinlerde,
   aynı dönemlerde. Yeni coinler bu varyant için hiç görülmedi; örneklemi de büyütür.
3. **Final dönemi** ancak tek aday doğrulamayı geçtiğinde açılır; bu turda açılmadı.

## Denetim
İki şüpheci denetçi incelendi.
- **Tek YÜKSEK bulgu:** dönem sonu giriş yasağı. Düzeltme 1 ile giderildi.
  - Denetçinin kendi tekrar koşusu da aynı iki adayı seçti: 1D_event_A ve 1D_state_A.
- **Sinyal sadakati:** Sinyaller pandas ile bağımsız olarak yeniden uygulandı (eksik barlar
  enjekte edilerek). 24 varyantın hepsinde sinyal zamanı, yön, E ve ATR birebir eşleşti.
- **Geleceğe bakma:** Gelecek fiyatları bozan sarsma testinde, geçmiş sinyaller ve işlemler
  değişmedi.
- **Kalan 3 DÜŞÜK bulgu:** Bu veride etkisi sıfır.
  - Kaynak, evren ve dönem sınırlarının ön-kayıtla zorunlu karşılaştırılması → eklendi
    (koşu sonrası; sonucu değiştirmez).
  - Atılan sinyallerin sayılması.
- **Yan etki:** Motorun hash'i değiştiği için dondurulmuş sweep koşusunda `cli report` artık
  "hash değişti" diye reddeder. Sweep sonucu zaten raporlandı; kendi davranışı değişmedi
  (`max_hold_ms=None` → 12 saat).
