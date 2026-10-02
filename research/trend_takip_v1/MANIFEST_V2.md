# TREND_TAKİP_V2 — önceden kayıt (2026-10-02, V2 sonuçlarından ÖNCE)

V1 (MANIFEST.md) motoru, verisi, maliyeti, riski ve dönemleri AYNEN kullanılır. Yalnız iki ek:

1. **Erken başarısızlık çıkışı (E10/E20):** Girişten sonra K gün (10 ya da 20) dolduğunda, girişten beri
   en iyi kapanış giriş fiyatından en az 1R (|E − S0|) lehe gitmemişse ertesi açılışta çık
   (EXIT_SIGNAL). Takip stopu aynen çalışmaya devam eder.
   Gerekçe (V1 teşhisi): kaybedenlerin çoğu tutmayan kırılımlar; kazananlar kısa sürede +1R'yi görüyor.
2. **Hibrit giriş (NWK):** giriş sinyali NW+KAMA 1D event_A (`validate_nw_kama.sigs`, kod aynen,
   parametreler 3/15/1.5/5/1), çıkış V1'in ATR takip stopu (hedef yok, azami tutuş yok).

## Varyantlar (6, sabit)
| id | taban | ek |
|---|---|---|
| T1 | N50_X5_L | E10 |
| T2 | N50_X5_L | E20 |
| T3 | N100_X5_LS | E10 |
| T4 | N100_X5_LS | E20 |
| H1 | NWK giriş, X5 takip, LS | — |
| H2 | NWK giriş, X3 takip, LS | — |

## Benimseme kuralı (sonuçtan önce sabit)
T-varyantı tabanına göre "iyileştirme" sayılır ancak ve ancak KEŞİF ve DOĞRULAMA'nın İKİSİNDE de
(NORMAL maliyet): ortalama R ≥ taban, toplam net USDT ≥ 0.9 × taban, MDD ≤ taban; ve STRESS'te toplam > 0.
H-varyantı, iki dönemde de NORMAL ve STRESS toplam net > 0 ise "çalışıyor" sayılır.
İstatistiksel hüküm ayrıca `liquidity_sweep_v1.selection` ile aynen verilir (örneklem tabanları ve LCB).
FİNAL dönemi bu V2 koşusunda AÇILMAZ.

## Teşhis (karar dışı)
Birleşik hesap: en iyi trend varyantı + NWK, aynı 10.000 USDT, günlük özsermaye değişimleri toplanarak
(%0.25 risk her biri) — % büyüme ve MDD.

Sonuç görüldükten sonra K, 1R eşiği, k, N ya da kural değiştirilmez.
