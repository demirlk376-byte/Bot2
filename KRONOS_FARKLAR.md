# KRONOS ile CANLI BOT — TAM FARK ENVANTERİ
*2026-09-14 · kod okunarak çıkarıldı, ezberden değil*

Bu belge KRONOS'a nereye kadar yaslanabileceğimizi tanımlar. Her madde kod
referanslı. "Bilinmiyor" yazan yerler gerçekten bilinmiyor — tahmin yok.

---

## A. AYNI OLAN — kanıtlanmış

| # | konu | canlı | KRONOS | kanıt |
|---|---|---|---|---|
| A1 | **Tetikleme** | `on_candle_close(candle)` — mum kapanışı olayı (main.py:180) | olay döngüsü, bar kapanışı | aynı mantık |
| A2 | **Donchian zamanlaması** | 1h mum kapanışında `hour % 4 == 3` ise 4h barı analiz et (main.py:681) + `donchian_last_4h` tekrar-koruması | 4h bar kapanışında bir kez | denk |
| A3 | **Donchian penceresi** | `get_candles(confirm_tf, 260)` (main.py:682) | `pencere(i, 260)` | **birebir 260 bar** |
| A4 | **Çıkış modeli (ankor kolları)** | donchian/squeeze/bb: **sabit SL/TP + max-hold**. Stop oynatma bu kollara UYGULANMIYOR (main.py:1105-1110) | sabit SL/TP + max-hold | birebir |
| A5 | **MTF formülü** | `close > EMA20(bugün dahil)` (main.py:1063) | `close > EMA20.shift(1)` | **cebirsel olarak AYNI**: c > αc+(1−α)E ⟺ c > E |
| A6 | **Koltuk sayısı** | `MAX_POSITIONS=7` | `maxpos=7` | .env'den doğrulandı |
| A7 | **Netted tek-pozisyon/coin** | "One-position-per-symbol guard (LIVE/netted only)" (execution.py:403) | `tek_pozisyon_per_coin` | eklendi; ankorda etkisi 0 (ayrık coinler) |
| A8 | **Cooldown** | 2 kayıp → 240dk, `{kol}:{coin}` anahtarı (execution.py:266-293) | aynı | etki: 11 işlem / −$9.79 |
| A9 | **Günlük fren** | gün başı equity'nin %35'i (risk.py:236) | aynı | etki: **sıfır** |
| A10 | **Nedensellik** | canlı geleceği göremez | veri 3 tarihte kesildi, önceki 616/1025/1344 karar **birebir aynı** | T2 |

---

## B. FARKLI — ölçüldü

| # | konu | canlı | KRONOS | ölçülen fark |
|---|---|---|---|---|
| B1 | **Aynı bar girişi** | pozisyon kapandıktan sonra aynı bar kapanışında yeni giriş serbest | modelleniyor (`ayni_bar_giris=True`) | ankora göre **+140 işlem, ort R %−13.3** |
| B2 | **Koltuk bilgisi** | koltuk O AN sorulur | aynı | ankorun "üret-sonra-filtrele"sine göre **+4 işlem, +$16** |

---

## C. FARKLI — ölçülmedi, büyüklüğü BİLİNMİYOR

| # | konu | canlı | KRONOS | neden önemli |
|---|---|---|---|---|
| **C1** | **Giriş emri tipi** | `MAKER_ENTRY=true` + `DONCHIAN_MAKER_ENTRY=true` → **maker limit** (execution.py:595-623, `force_market = not donchian_maker_entry`, main.py:744) | bar **kapanışından market** | maker girişte **kayma YOK**. KRONOS 15.85bp/stop_pct kesiyor ≈ **0.059R/işlem**. Bu, kaymasız/kaymalı iki sütun arasındaki farkın TAMAMI |
| **C2** | **Ücret** | maker dolum **%0**, taker **%0.01** (execution.py:718, 780, 817) | her iki tarafa da **sabit 1bp** | maker girişte KRONOS fazla kesiyor ≈ **0.0039R/işlem** |
| **C3** | **Maker dolmazsa** | limit bekler, dolmazsa market'e düşer (zaman aşımı) | her sinyal dolar varsayılıyor | doluş oranı **bilinmiyor** → 7-21 Ekim `kayma_denetim.py` kararı tam bu |
| **C4** | **Stop dolum fiyatı** | stop-market seviyenin **ötesinde** dolar (gap) | tam `sl_price`'tan dolar varsayılıyor | KRONOS stop çıkışlarını **iyimser** gösteriyor |
| **C5** | **Bar içi yol** | gerçek sıra | belirsizlikte **stop önce** (muhafazakâr) | belirsizlik bandı hiç hesaplanmadı |
| **C6** | **Boyutlandırma** | canlı equity'den (**bileşik**) | sabit taban (`bilesik_boyut=False`, hiç kullanılmadı) | kâr kıyasları için doğru, mutlak rakam için değil |

---

## D. KRONOS'ta HİÇ OLMAYAN

| # | ne | durum |
|---|---|---|
| **D1** | **Funding maliyeti** | `kronos/` içinde "funding" kelimesi **sıfır kez** geçiyor. Canlıda 8 saatte bir ödeniyor. Tutuş süresi ortalama ~2 gün → işlem başına ~6 funding ödemesi. **Hiç modellenmiyor.** |
| **D2** | **Dört ek kol** | orb / fvg / asia_bo / sr_breakout. Canlıda 125 işlemin **36'sı** (%28) bunlardan. Motor eksik bir kısıt yüzünden onları canlıdan **27× fazla** koşturuyor → ölçüm yapılamıyor |
| **D3** | **ORB tick-watcher** | ORB canlıda **bar içi** tetikleniyor (`orb_armed`, main.py:151) — KRONOS yalnız bar kapanışı |
| **D4** | **BE@+1R stop oynatma** | orb/ifvg için canlıda var (`STOP_MOVE_ENABLED` ise), KRONOS'ta yok. **Ankor kollarını etkilemez** |
| **D5** | **Minimum emir büyüklüğü** | MEXC kontrat minimumları. $190 tabanda işlem başına risk $5.32 → bazı işlemler gerçekte açılamayabilir. $1000 tabanda kısıt gevşer |
| **D6** | **Kısmi dolum** | canlıda mümkün, KRONOS'ta tam dolum varsayılıyor |
| **D7** | **Veri bayatlığı** | veri 2026-07-19'da bitiyor; bugün 2026-09-14 → **~2 ay eksik** |

---

## E. BİLİNMEYEN — .env'den doğrulanmalı

| # | ayar | neden kritik |
|---|---|---|
| **E1** | `DONCHIAN_MTF` | Kod varsayılanı **False** (config.py:290,469). KRONOS MTF kapısını **HER ZAMAN** uyguluyor. Canlıda kapalıysa KRONOS canlının almadığı işlemleri **eliyor** — donchian 1133 işlemi etkiler, **en büyük tek belirsizlik** |
| **E2** | `STOP_MOVE_ENABLED` | orb/ifvg BE@1R gerçekten uygulanıyor mu (ankoru etkilemez) |
| **E3** | `MAX_RISK_PCT` | 0.02 varsayıldı (×1.4 = 0.028). Farklıysa bütün boyutlandırma kayar |
| **E4** | `BB_SYMBOLS` / kol allowlist'leri | dört ek kolun hangi coinlerde açık olduğu — D2'nin çözümü burada olabilir |

---

## HÜKÜM

**Yaslan:** ankorun üç kolu içinde, aynı maliyet modeliyle **göreli** kıyaslar
(A1-A10 kanıtlı; B1-B2 ölçülü). "A fikri B'den iyi mi" sorusuna güvenilir cevap
verir, çünkü maliyet hatası iki tarafta da aynı olup sadeleşir.

**Yaslanma:** mutlak dolar/yüzde tahminleri. C1-C6 + D1 birlikte işlem başına
kabaca **0.06R'lik** bir belirsizlik yaratıyor ve edge **+0.15R** — yani
belirsizlik edge'in **%40'ı**. Yönü de bilinmiyor: C1/C2 KRONOS'u fazla
karamsar, C4/D1 fazla iyimser yapıyor.

**Önce çözülecek:** E1 (MTF kapısı). Tek bir `.env` satırı ve donchian'ın
1133 işlemini etkiliyor — maliyet kalibrasyonundan ÖNCE bilinmeli.
