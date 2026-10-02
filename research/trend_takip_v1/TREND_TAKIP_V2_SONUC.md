# TREND_TAKİP_V2 — sonuç (ön-kayıt: MANIFEST_V2.md, commit 5b300b1)

Koşu: `sonuclar_v2/20261002T214418Z_5b300b18_6e2d1b07/`. Keşif 2021-01→2024-06 (3.45 yıl), doğrulama 2024-06→2025-08 (1.15 yıl).
FİNAL açılmadı. Getiriler %0.25 işlem riskiyle, 10.000 USDT hesaba, NORMAL maliyet.

| varyant | keşif getiri | keşif MDD | doğr. getiri | doğr. MDD | benimseme |
|---|---|---|---|---|---|
| Taban N50_X5_L | +12.9% | 7.5% | +9.3% | 8.9% | — |
| T1 (E10) | +10.9% | **4.1%** | +7.4% | **5.4%** | HAYIR (getiri düştü) |
| T2 (E20) | +10.7% | 6.2% | +9.4% | 7.6% | HAYIR (keşifte toplam < %90) |
| Taban N100_X5_LS | +9.4% | 6.5% | +9.4% | 7.5% | — |
| T3 (E10) | +6.3% | 4.5% | +7.3% | 5.4% | HAYIR |
| T4 (E20) | +7.1% | 5.0% | +9.4% | 7.3% | HAYIR |
| H1 (NWK giriş + X5) | +0.7% | 2.4% | +7.5% | 3.0% | pozitif ama keşifte ~0 |
| H2 (NWK giriş + X3) | +3.4% | 2.9% | +4.0% | 1.7% | pozitif, zayıf |

Birleşik hesap (teşhis): N50_X5_L + H2 → keşif +16.4% (MDD 7.8%), doğrulama +13.4% (MDD 8.7%).

## Yorum
- Erken çıkış, düşüşü belirgin azaltıyor (MDD ~yarıya) ama toplam kârı da kesiyor. Ön-kayıtlı kural
  "kâr düşmeyecek" dediği için benimsenmedi. Getiri/MDD oranı iyileşti (T1 keşif 2.7 vs 1.7). Bu, sonradan
  bir risk-ölçekleme argümanı olur; ön-kayıtta yoktu, o yüzden kanıt sayılmaz.
- NWK girişi trend çıkışıyla birleşince tek başına zayıf. Trend takipçisiyle aynı hesapta, benzer
  düşüşle getiriyi +3..+4 puan artırıyor (çeşitlendirme).
- İstatistik: doğrulamada hiçbir varyant örneklem tabanı ve LCB > 0 şartını geçmedi.
  Hüküm KANIT YETERSİZ (V1 ile aynı).
