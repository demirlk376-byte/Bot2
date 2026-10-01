# BTC dominans filtresi — sonuç (2026-10-01)

**HÜKÜM: İKİ KURAL DA REDDEDİLDİ** (önceden kayıtlı kapılar: `MANIFEST.md`, commit `88b5d61` ve `21f146e`).

## Veri
- **Kaynak:** Binance `BTCDOMUSDT` 1h. GitHub Actions ile indirildi, `veri/btcdom` dalında duruyor.
- **Kapsam:** 2023-03-01 → 2026-09-29, 31.416 mum, boşluk 0.
- **İşlemler:** 936 referans ikiz işleminin %100'ü kapsamda.
- **Taban:** ortalama +0.185R, toplam +173.3R.

## Yaygın kural F1 (dominans yükselirken alt long yok, düşerken alt short yok)
| | n | ort net R | %95 GA |
|---|---|---|---|
| engellenen | 379 (%40) | +0.174 | [+0.027, +0.321] |
| kalan | 557 | +0.193 | |

- **Engellenen işlemler kârlı.** Filtre uygulansaydı toplam ≈ −65.9R kaybedilirdi.
- **Yarılar tutarsız:**
  - 2024-12 öncesi: engellenen +0.10R, kalan +0.29R.
  - Sonrası: engellenen +0.29R, kalan +0.09R.
- **Plasebo:** yüzdelik %44, rastgele kaydırmadan ayırt edilemiyor.
- **F2 (bant) ve F3 (72 sa):** engellenenler yine kârlı (+0.28R, +0.16R).

## Ters kural T1 (yalnız saklı dönem: 2025-03 öncesi + 2026-06 sonrası, 612 işlem)
| | n | ort net R | %95 GA |
|---|---|---|---|
| engellenen | 356 | +0.213 | [+0.038, +0.387] |
| kalan | 256 | +0.095 | |

- **Kuru denemedeki ilişki saklı dönemde TERSİNE döndü:** ters kuralın eleyeceği işlemler, tutacaklarından daha iyi.
- **Plasebo:** yüzdelik %79.5.

## Yorum
- Dominansın 7 günlük yönü bu botun işlem sonucunu öngörmüyor.
- Görülen etkiler dönemden döneme işaret değiştiriyor; tipik gürültü.
- Hiçbir kural Aşama 2'ye (ikiz portföy testi) geçemedi; o aşama koşulmadı.
- Bu sonuç, README'deki eski BTC-BB bulgusuyla da uyumlu: dominans bir kâr kaynağı değil.
