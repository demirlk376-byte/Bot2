# GELISIM_V8 — sonuç (ön-kayıt MANIFEST_V8.md, commit 60b506c)

Koşu: `sonuclar_v8/20261003T022206Z_60b506cc_15d8c86d/`. %0.25 risk, 2021-01 → 2025-08-08.
P0 sonucu V7-R1 ile birebir aynı.

| | eski 12 getiri | MDD | yeni 24 getiri | MDD | yeni 24'te 2022 |
|---|---|---|---|---|---|
| P0 (T1 + H4 + ETH200) | +73.4% | 8.3% | +49.0% | 11.2% | +0.8 |
| S ayıda short | +64.6% | 9.6% | +36.8% | 16.7% | +5.0 |
| **P piramit** | **+94.7%** | 10.5% | **+55.8%** | **11.1%** | +0.8 |
| SP | +85.5% | 12.9% | +43.5% | 16.6% | +4.3 |

## Hüküm (ön-kayıtlı)
- **P: BENİMSENDİ.** İki kümede de getiri > P0, getiri/MDD > P0 (9.03 > 8.84 ve 5.03 > 4.38),
  STRESS > 0.
- **S ve SP: reddedildi.**
  - 2022'yi kâra çeviriyor ama diğer yıllarda shortlar zarar ediyor.
  - Yeni kümede MDD 11% → 17%.

## İstatistik (teşhis)
- Piramitte işlem başı R, artan R0 yüzünden küçülür; bu yüzden R-tabanlı LCB yanıltıcıdır.
- Sabit 25 USDT birimiyle haftalık blok bootstrap (paket, NORMAL):
  - eski 12: P0 LCB +0.245, P +0.317;
  - **yeni 24: P0 +0.074, P +0.087** (ikisi de > 0).
- Paket bütün olarak görülmemiş coinlerde istatistiksel olarak pozitif.

## Paket (dondurulmuş aday)
- günlük N50_X5_L + E10;
- 4h N180_X5_L + E10;
- ETH200 long anahtarı;
- +2R/+4R'de en fazla 2 piramit eki.

Sonraki adım: FİNAL dönemi (2025-08 → 2026-10) tek seferlik sınav.
