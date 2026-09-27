# Canlı max_hold market çıkışlarının execution maliyeti (önceden kayıt)

**Durum: VPS KOŞUSU BEKLİYOR.** Kurallar sonuç görülmeden sabitlendi.

## 1. Doğrulanan kod yolu

Beklenen akış (süre dolar → market kapanış → gerçek dolum kaydı) doğru, ama **referans
fiyat bir mum kapanışı değil**:

| adım | yer | davranış |
|---|---|---|
| tetik | `main.py:219-222` | Her **1h mum kapanışı** işleyicisinde `_enforce_max_hold(symbol, current_price)` çağrılır |
| referans | `main.py:193` | `current_price = ctx.data_mgr.get_current_price()`. Bu **anlık ticker** fiyatı; **DB'ye kaydedilmez** |
| koşul | `main.py:1513-1534` | `max_candles = strategy_scores["max_hold"]`, yoksa `MAX_HOLD_CANDLES` (48) |
| koşul (devamı) | | `max_age = max_candles × 3600` (PRIMARY_TF=1h); tetik: `now − entry_time ≥ max_age` |
| kapanış | `execution.py` `close_position` → `exchange.py` `close_position` | Reduce-only **MARKET**. `exit_price = order.filled_price`; `current_price` yalnız order None ise kullanılır |
| dolum yedeği | `exchange.py` | average = 0 → `fetch_order` / `dealAvgPrice` → son çare **MARK fiyatı**. Bu durumda yalnız WARNING loglanır ("Close fill price unavailable"); **DB'de işaret yok** |
| ücret | `execution.py` `_close_position_internal` | Çıkış ücreti **sabit** `exit × 0.0001` (taker 1bp); `exit_time = now` (dolumdan sonra) |
| max_hold değerleri | `execution.py:932-941` | donchian 120 (`DONCHIAN_MAX_HOLD`), squeeze varsayılan 48, gün-içi 6 / 24 |

## 2. Referans fiyat: vekil (birebir kurulamaz)

Karar anındaki ticker fiyatı kaydedilmiyor. Bu yüzden **vekil** kullanılıyor: karar
işleyicisini tetikleyen 1h mumun **kapanışı**.

- ccxt/MEXC OHLCV zaman damgası mumun **açılışıdır**.
- Karar mumu kapanışı `C = floor_hour(exit_time)`. Referans mum `[C−1h, C)`, referans
  fiyat o mumun `close` değeri.
- Referans mum karar anından **önce** kapanmış olur. Lookahead üç koşulla otomatik
  denetlenir:
  1. `decision_time ≤ exit_time`
  2. mum kapanışı `≤ exit_time`
  3. mum kapanışı `≤ decision_time`
- **Vekil hatası:** Mum kapanışı ile işleyicinin ticker'ı okuduğu an arasında birkaç
  saniyelik fiyat oynaması var. Bu sıfır ortalamalıdır; ortalamayı değil yalnız dağılımı
  büyütür.
- Önceki ölçümde bar kapanışından 1 dk sonraki sürüklenme ~0.1bp çıkmıştı
  (`kayma_denetim.py` notu).

### Zamanlama tutarlılığı (işlem başına, önceden sabit)

- `0 ≤ exit_time − C ≤ 300 sn`
- `yaş = exit_time − entry_time ≥ max_age`
- `yaş − max_age < 3600 + 300 sn`. İlk uygun mum kapanışında tetiklenmiş olmalı; geç
  tetik restart veya kesinti demektir.

Tutarsız işlem elenir. **Adayların < %80'i tutarlıysa RECONSTRUCTION FAIL → D.**

### Örneklem

- `is_paper = 0` ve `exit_reason = "max_hold"` (kodda kullanılan tek değer).
- manual / external / SL / TP / emergency / `no_stop_safety` karışmaz.
- Elenenler:
  - `strategy_scores.exit_price_estimated` işaretli işlemler
  - Journal'da çıkıştan 0-30 sn önce "Close fill price unavailable" uyarısı olan
    işlemler (mark fiyatıyla yazılmış, gerçek dolum değil). Journal okunamazsa bu
    uyarı basılır.

## 3. Tanımlar

- **Kayma** (+ = aleyhe):
  - LONG `(ref − dolum)/ref·1e4`
  - SHORT `(dolum − ref)/ref·1e4`
- **R:**
  - `initial_stop_pct = |entry − sl0|/entry`, `exit_slippage_R = (bp/1e4)/initial_stop_pct`.
  - `sl0` yoksa: yalnız donchian/squeeze için `|niyet − sl_price| = 2.0×ATR (±%2)` ise
    `sl_price` kullanılır (stop hiç taşınmamış demektir). Aksi halde R hesaplanmaz,
    bp kalır.
- **Ücret:** market çıkış ücreti 1.00bp (taker; kodda sabit), maker 0. Kaymaya
  karışmaz. `toplam çıkış maliyeti = kayma + 1bp`.
- **PERFECT_FILL_SAVING_UPPER_BOUND:** Σ (kayma_bp + 1bp − 0bp)/1e4 × çıkış nominali.
  - Her çıkışın referansta, maker olarak dolduğu **kusursuz** varsayım.
  - Kayma işaretli kullanılır; lehimize dolumlar üst sınırı düşürür.
  - **Gerçek limit getirisi değildir.** Dolmama ve ters seçilim ölçülmez.
  - Ayrıca verilenler: R/işlem, yıllık $ (canlı dönem uzunluğuna göre) ve canlı net
    PnL'nin yüzdesi (tüm kapanmış canlı işlemler).

## 4. Veri kapıları ve hüküm (önceden sabit)

**Veri kapıları:**

| koşul | sonuç |
|---|---|
| lookahead ihlali (tek bir tane bile) | **TEST INVALID** |
| RECONSTRUCTION FAIL veya geçerli n < 15 | **D** |
| 15 ≤ n < 30 | yalnız keşif, **D** |

**n ≥ 30 ise:**

| hüküm | koşul |
|---|---|
| **A**: kayda değer execution adayı | ort kayma %95 bootstrap GA tamamen > 0 **ve** üst sınır **kayda değer** |
| **C**: kullanışlı execution edge yok | üst sınır **anlamsız küçük** **ve** (ort kayma ≤ 0 veya GA sıfırı içeriyor) |
| **B**: maliyet var ama belirsiz/küçük | diğer durumlar |

- **Kayda değer:** üst sınır ≥ canlı net PnL'nin **%2**'si. Net PnL ≤ 0 ise
  R/işlem ≥ **0.02R**.
- **Anlamsız küçük:** üst sınır < net PnL'nin **%0.5**'i. Net PnL ≤ 0 ise
  R/işlem < **0.005R**.

A çıksa bile production'a LIMIT çıkış **eklenmez**. Market kayma ölçümü limit dolum
oranını ve ters seçilimi ölçmez.

**Alt gruplar:**
- Kol bazında n<10 betimsel, 10-19 zayıf, ≥20 yorumlanabilir. Alt gruptan kural
  üretilmez.
- Nominal ilişkisi: n ≥ 20 ise Spearman (5000 permütasyon) ve Q1-Q4; aksi halde
  INSUFFICIENT.

## 5. A çıkarsa sonraki deney (BU GÖREVDE YAPILMADI)

Gerçek davranışı değiştirmeden bir **gölge limit** simülasyonu gerekir.
- Her max_hold kararında, canlı market çıkışı aynen yapılırken varsayımsal bir maker
  limit fiyatı kaydedilir (örneğin karar anındaki ticker).
- Sonraki fiyat akışında ölçülür:
  - limit dolar mıydı,
  - ne kadar sürede dolardı,
  - dolmasaydı fiyat ne kadar kaçtı (ters seçilim).
- Ancak bu ölçüm dolum oranı × kazanç − kaçırma maliyeti olarak pozitif çıkarsa limit
  çıkış ayrı bir karar konusu olur.

## 6. Doğrulama (çevrimdışı)

**Sentetik defter, yerel `data/*_fut_1h.csv` mumları:**
- 36 işleme bilinen kayma enjekte edildi. Ölçülen ile enjekte edilen arasındaki en büyük
  fark **1.8e-12bp** (birebir).
- Elenenler doğru sayıldı:
  - geç tetik (restart benzeri) → zamanlama tutarsız
  - `exit_price_estimated` işaretli işlem
- `sl_hit` ve `is_paper=1` işlemleri aday bile olmadı.
- Lookahead ihlali 0.
- Stop kaynağı: `sl0` 12, ATR ile doğrulanmış `sl_price` 24.
- Boş veritabanında hüküm **D** çıktı.

## 7. VPS'te çalıştırma (salt okur)

```
cd /opt/bot2 && git pull && venv/bin/python arastirma/max_hold_execution_audit/max_hold_execution_audit.py
```

- Mumlar MEXC **halka açık** OHLCV'den okunur (emir/hesap erişimi yok).
- `journalctl -u btc-bot` yalnız okunur.
- `.env` okunmaz, bota dokunulmaz, DB `mode=ro`.
- CSV `/tmp/max_hold_execution_audit/max_hold_trades.csv` dosyasına yazılır.

## Sonuç

_(VPS çıktısı gelince eklenecek.)_
