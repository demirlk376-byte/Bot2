# İyi bir BTC setup'ı: BTC'yi çalışan trend/kırılım sistemine eklemek — ÖN KAYIT (2026-10-28, sonuçlardan ÖNCE)

Kullanıcı: "Amacımız güzel bir BTC setup bulmak." Bu projede elde edilen bulgular iyi bir setup'ın şeklini belirliyor:
kısa vadede (dakika–saat) maliyet duvarı kenarı yiyor ve BTC'nin gün/seans yönü tahmin edilemiyor (btc_hafta_v1,
londra_oos_v1, kontrol_v1); maliyeti yenen tek tutarlı kenar çok günlük trend/kırılım (donchian, trend kolu), hacim
onaylı, kayıpları stopla kesip kazananı taşıyan yapı. Canlı sistem BTC'yi hiç işlemiyor (SYMBOLS'ta yok; Temmuz 2026'da
donchian@BTC canlıdaydı, sonra evrenden çıktı). Defter: coin seçimi bilgi taşımıyor (L5984-6021) ve coin eklemek
2025–26'da koltuk rekabeti yüzünden kötüleştirmişti (L1617-1638) — bu yüzden karar PORTFÖY katkısıyla verilir.

## Setup'lar (kurallar canlıdakiyle BİREBİR, yeni parametre yok)
- **B1 — BTC donchian'a**: DONCHIAN_SYMBOLS ve SYMBOLS'a BTC eklenir; diğer her şey canlı env (4h 40 bar kırılım +
  EMA200, hacim ≥ 2.5×, günlük EMA20 MTF, SL 2×ATR14, TP 2.5R, 120 s, risk %3.5, MAX_POSITIONS 7, BTC/ETH/SOL aynı yön ≤ 2).
  Gerçek maliyetli ikiz yeniden koşusu (SQUEEZE_ENABLED=false PAPER_SLIP_GIRIS_BP=15.85 PAPER_SLIP_CIKIS_BP=0.24
  PAPER_FUNDING=true PAPER_MAKER_DOLUM=0.66 TAKER_FEE_RATE=0.00025), iki dönem.
- **B2 — BTC trend koluna**: trend B0 kuralları aynen (1D 50 gün / 4h 180 bar kırılımı, ETH SMA200 rejimi, 5×ATR iz süren
  stop, 2 piramit, risk %1.5, açık risk tavanı %24), evren BOT12 + BTC.
- **B3 — B1 + B2 birlikte.**
Veri: KEŞİF 2023-04-07 → 2026-07-18 (MEXC 1h, `canli_wt/data`, BTC dahil); BAĞIMSIZ 2020-02-01 → 2023-04-06 (Binance 1h
vekil; BTC için `scratchpad/btc_veri/veri/BTC_fut_1h.csv` + `BTC_funding.csv`). Portföy: momentum_v2/bot_iyilestirme_v1
düzeneği (`scratchpad/portfoy/harness.py`, ortak sermaye motoru, bot %3.5 + trend %1.5); BASE = canlı düzen
(KEŞİF x116.467 / maxDD %28.94 / MAR 10.937; BAĞIMSIZ x42.160 / %58.67 / 3.696).

## Ölçüt (değiştirilmeyecek)
Bir setup **İYİ** ⇔ HER İKİ dönemde de (1) portföy MAR > BASE, (2) çarpan ≥ BASE, (3) maxDD ≤ BASE + 3 puan, VE
(4) BTC işlemlerinin kendi ort R'si > 0 (kazanç başka coinlerin işlemlerini kovmaktan gelmesin). Birden fazla İYİ ise
iki dönem MAR'larının geometrik ortalaması yüksek olan. Hiçbiri İYİ değilse BTC eklenmez.
Rapor: BTC işlem sayısı / ort R / yıl yıl, kovulan işlemler (koltuk ve BTC/ETH/SOL korelasyon kapısı), aylık tablo.
İYİ çıkan setup canlıya kendiliğinden geçmez: kullanıcı onayı (ayrı onay cümlesi) gerekir.
Sonuç görüldükten sonra kurallar, dönemler, maliyet ve ölçüt değiştirilmez.
