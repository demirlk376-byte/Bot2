# Momentum v2 — haftalık TSMOM ve 52 hafta zirvesi — ÖN KAYIT (2026-10-19, sonuçlardan ÖNCE)

Daha önce elenen momentumlar: günlük TSM 3–14g, aylık 21–60g, kesitsel momentum, devam formasyonları, trend 36 coin.
Bu turda hiç denenmemiş iki klasik fon yöntemi; KARAR ölçütü yalnız "tek başına kârlı mı" değil, "mevcut botu
(donchian + mean_rev + trend %1.5) birlikte iyileştiriyor mu".

## Veri
Fiyat `research_data/h4_kirilim_v6/veri/<COIN>_4h.csv` → haftalık mum (Pazartesi 00:00 UTC – Pazar sonu), funding
`<COIN>_funding.csv` (gerçek oranlar, long öder). Evrenler: ESKİ12 (bot coinleri) ve YENİ (yeni 26'dan MEXC
sözleşme bilgisi olan 24; EOS ve FIL hariç).

## Stratejiler (yalnız LONG; haftalık, Pazartesi açılışında karar ve işlem)
- **W (haftalık zaman serisi momentumu)**: son 12 tamamlanmış haftanın getirisi > 0 ise long aç / tut; ≤ 0 ise kapat.
  Koruyucu stop: giriş − 3·ATR(haftalık, 10). Stop olursa sinyal yeniden pozitif olduğu bir sonraki Pazartesiye kadar
  yeniden girilmez.
- **H (52 hafta zirvesine yakınlık)**: son kapanış ≥ 0.95 × son 52 tamamlanmış haftanın en yüksek kapanışı ise long aç;
  4 hafta tut (4. Pazartesi açılışında kapat), stop giriş − 3·ATR(haftalık, 10). Pozisyon açıkken yeni sinyal yok sayılır.
- Isınma: W için 12, H için 52 tamamlanmış hafta.
- Maliyet: NORMAL 1 bp ×2 komisyon + giriş kayması 15.85 bp + çıkış 0.24 bp; STRESS kayma ×2. Funding: tutulan her
  settlement'ta long −oran × notional. R = [(çıkış−giriş)/giriş + funding − maliyet] / (3·ATR/giriş).

## Ölçüt (değiştirilmeyecek; 2 strateji)
1. **Tek başına (kenar kanıtı)**: YENİ evrende, girişler 2020-01-01 → 2025-08-08: NORMAL ve STRESS ort R > 0 ve
   aylık blok bootstrap (10 000, seed 20261019) %1.25 persentil (2 test Bonferroni) > 0; ESKİ12'de de NORMAL ort R > 0.
2. **Portföy katkısı**: strateji ESKİ12'de, işlem başı %1 risk, mevcut düzenle (bot ikiz işlemleri %3.5 + trend B0 %1.5,
   ortak sermaye motoru `trend_gelistirme/birlesik.py`) BİRLİKTE; iki dönemde (2020-02-01 → 2023-04-06 bot=`ikiz_eski.db`;
   2023-04-07 → 2026-07-18 bot=`ikiz_gercek.db`): aylık CAGR/maxDD oranı ve çarpan mevcut düzenden yüksek, maxDD en fazla
   3 puan kötü.
Bir strateji **EKLENİR** ⇔ 1 VE 2. Rapor: donchian ve trend ile haftalık korelasyon, eşzamanlı pozisyon, yıl yıl.

---
## SONUÇ (2026-10-20) — İKİSİ DE EKLENMEZ
Kenar: iki bağımsız uygulama aynı hükmü verdi (W GEÇTİ, H GEÇMEDİ). Büyüklük farkı yalnız funding kuralından
(B: her settlement'ta güncel notional; A: giriş notionalı) — B daha gerçekçi, ikisinde de W > 0. Denetçi ajanı oturum
sınırı nedeniyle tamamlanamadı; hükümler bu farktan etkilenmiyor.

| | yeni 24 ort R (A / B) | %1.25 alt (A / B) | not |
|---|---|---|---|
| W haftalık TSMOM | +0.50 / +0.37 | +0.12 / +0.08 | medyan R negatif; 2020 girişleri baskın (DOGE +200R) |
| H 52 hafta zirvesi | +0.12 / +0.11 | −0.17 / −0.18 | anlamlı değil |

Portföy (bot + trend %1.5, işlem başı %1 risk, 12 bot coini):
| dönem | BASE | +W | +H |
|---|---|---|---|
| bağımsız 2020–23 | x42.2, DD %58.7 | x60.6, DD %59.1 | x44.0, DD %58.7 |
| keşif 2023–26 | x116.5, DD %28.9 | x114.0, DD %29.3 | x130.3, DD %29.7 |
W: kenarı var ama keşifte hesabı kötüleştiriyor; bağımsızdaki kazanç tek bir DOGE işleminden (çıkarınca x44.3). 2025–26'da
W girişleri negatif. H: hesabı iki dönemde de biraz iyileştiriyor ama kendi kenarı istatistik olarak sıfırdan ayırt
edilemiyor. Kural 1 VE 2 → ikisi de eklenmez. H en yakın aday; istenirse kâğıt üzerinde izlenebilir.
