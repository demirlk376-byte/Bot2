# NWK_FILTRE_V4 — önceden kayıt (2026-10-02, sonuçlardan ÖNCE)

V3 ile aynı motor, veri, maliyet, risk, dönemler ve çıkış (X3 takip, LS). Yalnız 1D. FİNAL açılmaz.

**Önemli uyarı:** Doğrulama dönemi V3'te zaten görüldü. Burada geçen bir filtre bile yalnız "aday" olur;
hükmü FİNAL dönemi ya da kâğıt-takip verir.

## Yeni filtreler (sinyal günü kapanışında bilinen bilgiyle)
| kod | kural | gerekçe |
|---|---|---|
| G1 funding kalabalığı | Son 3 günün funding settlement ortalaması long için ≤ 0.0001 (taban oran), short için ≥ 0 | Kalabalık tarafa girme |
| G2 hacim teyidi | Sinyal günü hacmi > önceki 20 günün medyanı | Gerçek katılım |
| G3 | G1 VE G2 | — |

Kimlik `NWK1D_G1..G3`; karşılaştırma tabanı `NWK1D_F0`. Eşikler (0.0001, 0, 3 gün, 20 gün) sabittir.

## Karar kuralı
V3 ile aynı. Gk, F0'a göre şu dört koşulu hem KEŞİF hem DOĞRULAMA'da sağlarsa iyileştirme sayılır:
- ortalama R > F0,
- MDD ≤ F0,
- toplam ≥ 0.75 × F0,
- STRESS > 0.

İstatistik `selection` ile aynen.
