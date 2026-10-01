# Eski sweep kurguları ↔ LIQUIDITY_SWEEP_V1

Taban: `research/liquidity-sweep-v1` dalı, canlının izlediği daldan ayrıldı (`e6c1376`).
Üretim dosyalarına dokunulmadı.

## Eski kurgular (depoda)

| dosya / kayıt | kurgu | hüküm (kayıtta) |
|---|---|---|
| `research_liquidity_sweep.py` | **Veri:** BTC 1h 2023-2026 + ETH 1h (8 ay).<br>**Seviye:** son N barın dibi/tepesi.<br>**Giriş:** sweep mumu kapanışında reclaim.<br>**Maliyet:** sabit `COST=0.0002` gidiş-dönüş.<br>**Test:** TR/TE bölmesi 2026-01-01. | Deploy edilmedi. TR/TE tutarsız. |
| `research_vwap_sweep.py` | Aynı sweep + VWAP/STDV filtreleri, 1h | Reddedildi |
| `strategies/donchian.py` `DONCHIAN_MOD=supurme` | 4h kanal fitili dışarı, kapanış içeride → ters gir | 1.789 işlem −0.125R (`RESEARCH_LEDGER.md`) |
| DURUM.md §4e (2026-08-14) `edge_lab.py` | **Veri:** Binance 5m, 13 coin, 1065 gün.<br>**Mimari:** 1H rejim / 15M setup / 5M teyit.<br>**Model:** Sweep+Reclaim. | 24.307 işlem, brüt −0.0103R |
| RESEARCH_LEDGER 2026-09-22 | SMC/ICT ailesi (Sweep+MSS, Sweep+FVG) | Hepsi reddedildi. "Süpürme şartı kurulumu kötüleştiriyor." |

## Bu deneyin farkları

- **Seviye aileleri:** Dört ayrı aile, önceden bilinen zamanla (`known_at`) ve ömürle (`expires_at`).
  - L1: önceki UTC gün.
  - L2: [00:00, 08:00) seansı.
  - L3: son onaylı 1H pivotu.
  - L4: birbirine yakın iki pivot.
  - Seviye ilk uygun ihlalde tüketilir.
  - Eski kod "son N bar dibi"ni her barda yeniden hesaplıyordu.
- **Teyit modelleri:** Dört model.
  - K1: aynı mumda reclaim.
  - K2: 3 bar içinde gecikmeli reclaim.
  - K3: 5m mikro pivot kırılımı + gövde ≥ 0.5 ATR.
  - K4: FVG geri testi.
  - Her modelin iptal öncelikleri, zaman pencereleri ve neden kodları sabit.
- **Trend:** F0/F1 (EMA200 1H + 3 bar eğim) dışında giriş filtresi yok. Rejim, hacim, MTF ve
  puan filtreleri miras alınmadı.
- **Yürütme:** Giriş, sinyalden sonraki ilk 5m AÇILIŞINDA.
  - Eski 1H ikiz, girişi sinyal mumunun kapanış fiyatından yazıyor. 1H veride bu q+1 açılışına
    eşitti; 5m'de ayrı tutuldu.
  - Açılış boşluğu stop/hedefi açılıştan kapatır.
  - Bar içi çift temasta stop önce varsayılır ve işaretlenir.
  - 12 saat zaman çıkışı açılışta yapılır.
- **TP:** Piyasa emri; aynı çıkış kayması uygulanır. Legacy `PaperExchange.KAYMASIZ_CIKISLAR=("tp_hit",)`
  muafiyeti bu araştırmada KULLANILMAZ. Canlı davranış değişmedi.
- **Muhasebe:**
  - Giriş ücreti dolum anında düşülür. `PaperExchange` ise kapanışta düşüyordu.
  - Funding gerçek settlement zamanlarında, işaret doğru (pozitif oranda long öder) ve tek kez sayılır.
  - Eski ikizde funding bilinen iki hata yüzünden fiilen 0'dı (#1 `_simdi_ts` saat yaması, #3 birim).
- **Risk:**
  - Sabit 25 USDT ilk-stop riski (C0 × %0.25); kârla büyümez.
  - Toplam açık ilk-stop riski ≤ 100 USDT.
  - Canlı LEVERAGE, MAX_POSITIONS, POSITION_CAP_FRACTION, DAILY_MAX_LOSS_PCT kapıları uygulanır.
  - Bot kollarının (donchian/squeeze/BB) sinyalleri karışmaz.
- **Dönemler:** Kronolojik 60/20/20 bölme. Keşifte 32 aday × 2 maliyet; doğrulamaya en fazla 3,
  finale en fazla 1 aday. Seçim fonksiyonu sabit.
- **İstatistik:** 4 haftalık blok bootstrap (10.000 tekrar, seed 20261001), oran tahmincisi ΣS/ΣN.

## Yeniden kullanılan bileşenler

| bileşen | nasıl |
|---|---|
| `ikiz/kos.py` `CANLI_ENV` | Evren sırası, LEVERAGE=10, MAX_POSITIONS=7, POSITION_CAP_FRACTION=2.5, DAILY_MAX_LOSS_PCT=0.35 |
| `exchange.PaperExchange` | Ücret oranı (FEE_RATE=0.0001), kayma profili (15.85 / 0.24bp). Mutabakat kapısı G2: her araştırma işlemi gerçek PaperExchange'e aynı dolumlarla verilip net PnL eşleştirilir. |
| `indicators.ema/atr` | Formüller aynı (ewm adjust=False, ilk değerle tohum). Adaptör yalnız eksik barı NaN tutup atlar. |
| `risk.build_trade_setup_from_levels` | Notional tavanı (bakiye × POSITION_CAP_FRACTION) ve miktarı AŞAĞI yuvarlama ilkesi. |
| `execution` ön-uçuş marjin kontrolü | `margin_required > free × 0.95` → miktar marjine sığacak şekilde azaltılır. |

## Yeni adaptörün değiştirdiği davranışlar

| eski ikiz davranışı | bu deneyde |
|---|---|
| ReplayFeed ham 1H; 5m yok | Gerçek 5m ızgara (Binance USDⓈ-M vekil veya MEXC). 15m/1H/gün tam alt bar kuralıyla türetilir. |
| `get_current_price` = son 1H kapanışı | Giriş/çıkış referansı yeni 5m barın AÇILIŞI |
| `fetch_ohlcv` oluşan mumu ekleyebiliyor | Strateji yalnız kapanmış barları görür. Sinyaller önceden hesaplanır ve motor bir sinyali ancak `signal_time == t` sınırında görür. |
| `check_sl_tp` high/low, stop önce, açılış boşluğu yok | Önce açılış boşluğu, sonra bar içi; çift temas işaretlenir |
| Giriş ücreti kapanışta | Dolum anında; açık pozisyon özsermayesinde doğru zamanda görünür |
| `_simdi_ts` yerel datetime → funding 0 | Funding motorun kendi sanal saatinde, gerçek settlement zamanlarında |
| Ortak `ikiz_trades.db` | Her varyant/aşama/maliyet koşusunun kendi CSV'leri; DB kullanılmaz |
