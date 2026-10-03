# Trend kolunu canlı bota ekleme — tasarım (2026-10-03)

Dayanak:
- Araştırma: T1 (1D N50 X5 E10) + H4 (N180 X5 E10), ETH200 anahtarı, 2 piramit, %1 risk.
  Çakışmasız tam çözüm (D3) ile bot %13.5 → %17.7 aylık (iyimser).
- MEXC denemeleri, adım 1–4, `BIRLESIK_BOT_TREND.md`.
- Bot kodu: `claude/btc-intraday-trading-engine-U2C8A`. Satır numaraları o dalın 8758fd8+ hâli.

## Bağlanma noktaları (bot kodunda bulunanlar)

| konu | yer | trend için gereken |
|---|---|---|
| Mum akışı | main.py:183 `on_candle_close` (1h). Donchian 4h bloğu main.py:775 (`hour%4==3`, 4h tamponu 260 bar, `_poll_once` ile tazelik). | 4H modülü aynı kalıpla `hour%4==3`'te. 1D modülü günlük kapanışta (`hour==23` 1h mumu). Günlük için ayrı `fetch_ohlcv('1d', 120)`. ETH SMA200 için günde bir kez ETH 1d 220 bar. |
| Giriş kapıları | execution.py:384–520 `_execute_signal_guarded`: durdurma, soğuma (strateji:sembol), MAX_POSITIONS (:422, TÜM pozisyonları sayar), korele grup sınırı (:431), portföy stopu soğuması, aynı yön sınırı (:469), ONE_PER_SYMBOL (:488, sembolde HERHANGİ pozisyon varsa engeller), slot dolu. | Trend kendi yolundan girer (`execute_trend`). Ayrıca botun MAX_POSITIONS, korele, aynı-yön ve ONE_PER_SYMBOL sayımları trend pozisyonlarını SAYMAMALI. Aksi halde trend botun yerini kapar; ledger'ın ilk ret sebebi buydu. |
| Boyut | execution.py:538+: özsermaye bazlı; strateji adına göre `risk_override` (donchian/squeeze/...); `build_trade_setup_from_levels`; serbest teminat %95 ön-kontrolü. | `trend_risk_pct=0.01` dalı. Risk mesafesi = giriş − stop (5×ATR, geniş). |
| Stop ekleme | execution.py:≈640: giriş emrine `stopLossPrice` + `takeProfitPrice` ekleniyor (deneme: her girişin KENDİ ekli stopu oluyor). | Trend: stop = 5×ATR. TP = fiyat×10 (uzak; TP=0 taşımaları 5003 ile reddediliyor). |
| Stop taşıma | exchange.py `move_stop_loss` → `_get_attached_stop` sembolün İLK stopunu döndürüyor. main.py:1350 `_update_trailing_stops` (yalnız orb/ifvg BE; canlıda STOP_MOVE_ENABLED ile). | **ZORUNLU DÜZELTME:** taşıma, pozisyonun KENDİ giriş emri kimliğiyle (stoporder.orderId) seçilmeli. Yoksa botun BE taşıması trendin stopunu, trendin taşıması botun stopunu oynatabilir. |
| Çoklu kol stop yeniden kurma | execution.py:984 `resync_symbol_stops`: sembolde tüm plan emirlerini iptal edip her kol için SL+TP plan emri kuruyor (executeCycle=1 → **24 saat**). Yeniden başlatmada ve mutabakatta çağrılıyor. | Trend haftalarca sürer. Plan emirlere dönerse 24 saatte biter; yenilenmeli ya da executeCycle=2 kullanılmalı. Ekli stoplarla plan emirlerin birlikte çalışması denetlenmeli. Koruma bekçisi (`_verify_protection`) "en az bir stop var mı" diye bakıyor; kol bazında bakmalı. |
| Mutabakat | main.py:1928: sembol başına borsa miktarı ile iç kolların TOPLAMI kıyaslanıyor. Aynı yön çoklu kol destekli. Ters yön için HEDGE_AWARE_RECON (varsayılan kapalı). | Trend açıkken HEDGE_AWARE_RECON=true gerekir (bot short + trend long aynı coinde). |
| Süre sınırı | main.py:1513 `_enforce_max_hold`: varsayılan 48 saat, pozisyon başına `strategy_scores['max_hold']`. | Trend pozisyonuna çok büyük max_hold yazılmalı. Yoksa 48 saatte kapanır. |
| Günlük zarar / acil kapatma | execution.py `emergency_close_all` her şeyi kapatır. | Kabul (trend de kapanır). Kullanıcı kararı olarak yazılacak. |
| Kalıcılık | Portföy pozisyonları DB'de, `strategy_scores` JSON alanıyla; `restore_state` main.py:1622. | Trend alanları (modül, E0, D0, en iyi kapanış, ek sayısı, giriş emri kimliği, MFE) `strategy_scores` içinde. |
| İkiz | ikiz/kos.py + PaperExchange (pozisyon başına SL). | TREND_MODE=kapalı ile 936 işlem BİREBİR. Trend açıkken trend işlemleri araştırma motoruyla uyuşmalı. |

## Bileşenler

1. **`trend_kolu.py` (saf mantık):** araştırma motorundan birebir taşınır.
   - Kırılım, ATR (aynı Wilder tanımı), iz süren stop, erken çıkış, piramit tetiği, ETH200.
   - Testleri araştırma motorunun işlem listesiyle kıyaslanır.
2. **Ayarlar** (hepsi varsayılan KAPALI):
   - `TREND_MODE=kapali|sinyal|canli`,
   - `TREND_RISK_PCT=0.01`,
   - `TREND_MAKS_ACIK_RISK=0.24`,
   - `TREND_COINS` (varsayılan SYMBOLS),
   - `TREND_TASFIYE_PAYI=1.5` (tasfiye fiyatı stop mesafesinin 1.5 katı uzakta olacak kadar ek teminat).
3. **Sinyal modu:** mum kapanışında karar verir ve Telegram'a yazar ("trend: SOL 1D kırılım, giriş ~X, stop Y,
   %1 risk = Z USDT"). Emir YOK. İlk canlı aşama budur.
4. **Canlı mod:** `executor.execute_trend`, botun giriş kapılarından ayrı bir yol:
   - market giriş + ekli SL + uzak TP,
   - ardından `change_margin ADD` ile tasfiye fiyatını stop × pay ötesine itmek.
   - Piramit ekleri ayrı alt pozisyon (`SYM:trend:ek1/ek2`). Her birinin kendi ekli stopu var; hepsi birlikte taşınır.
5. **Bot düzeltmeleri** (davranışı DEĞİŞTİRMEMELİ, ikizde 936 işlemle kanıtlanacak):
   - kapı sayımları trendi saymasın;
   - `move_stop_loss` giriş emri kimliğiyle seçsin;
   - koruma bekçisi kol bazında baksın.

## Riskler (gerçek para) ve önlemleri

| risk | önlem |
|---|---|
| Bot BE taşıması trendin stopunu oynatır (ya da tersi) | Stop seçimi giriş emri kimliğiyle. DOT'ta minik denemeyle doğrulanır. |
| Yeniden başlatmada `resync` stopları 24 saatlik plan emirlerine çevirir; trend stopu sessizce biter | Trend için resync'te ekli stop korunur ya da executeCycle=2 + günlük yenileme. Bekçi kol bazında. |
| Trend pozisyonu 48 saat sonra max_hold ile kapanır | `strategy_scores['max_hold']` büyük; birim testi. |
| Mutabakat ters bacakları karıştırıp açık kolu "kapandı" sayar | HEDGE_AWARE_RECON=true önkoşul; ikizde ve DOT denemesinde sınanır. |
| Ek teminat başarısız → tasfiye stoptan önce | Teminat eklenemezse pozisyon hemen kapatılır (güvenli taraf). |
| Kapı sayımı değişikliği botun kendi davranışını bozar | Trend kapalıyken ikiz 936 işlemi birebir üretmeli; yoksa birleştirilmez. |

## Aşamalar

1. **Çekirdek + sinyal modu + ikiz.** Emir kodu yok. Çıktılar:
   - `trend_kolu.py` + testler (araştırma motoruyla birebir);
   - sinyal modu Telegram mesajları;
   - kapı sayımı düzeltmesi;
   - ikizde 936 işlem birebir.
2. **Canlı emir yolu (kapalı bayrakla):**
   - `execute_trend`, kimlikle stop taşıma, ek teminat, piramit, resync/bekçi uyumu;
   - DOT'ta minik denemeyle uçtan uca doğrulama.
3. **Canlıya alma:** 1–2 hafta sinyal modu, sonra %0.25 → %1 risk.
