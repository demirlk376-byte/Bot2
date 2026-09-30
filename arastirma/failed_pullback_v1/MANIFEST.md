# FAILED_PULLBACK_V1 — manifest (sonuçlardan ÖNCE yazıldı, 2026-09-30)

## Temel
| alan | değer |
|---|---|
| araştırma dalı | `research/failed-pullback-v1` |
| taban commit | `532da4e` (canlının izlediği `claude/btc-intraday-trading-engine-U2C8A` ucu, 2026-09-30) |
| üretim dosyaları | değişmedi; b78df07 → 532da4e arasında yalnız araştırma dosyaları farklı |
| ikiz | `ikiz/kos.py` `kur()` + `sur()` → gerçek `main.on_candle_close`, `ExecutionEngine`, `PaperExchange` |
| ayar | `ikiz/kos.py` `CANLI_ENV` (yerelde .env yok) + `ONE_PER_SYMBOL=true` |
| başlangıç sermayesi | 10.000 USDT (`PAPER_INITIAL_BALANCE` varsayılanı), tüm koşularda aynı |
| coin evreni | SOL, ETH, ADA, NEAR, BCH, XRP, DOGE, TRX, XLM, LTC, ICP, BNB |
| veri | `data/<COIN>_fut_1h.csv`, 2023-04-06 → 2026-07-19 (git'te izli; ikiz 4h'yi 1h'den üretir) |
| replay aralığı | başlangıç 2023-04-06, bitiş 2026-07-19 (936 referansıyla aynı) |
| maliyet (ana) | giriş kayması 15.85bp (piyasa), çıkış kayması 0.24bp (stop/zaman/acil; TP 0), komisyon 1bp/taraf taker, maker girişte 0 |
| maliyet (2x) | giriş 31.70bp, çıkış 0.48bp; komisyon aynı |
| funding | ana ikizde **YOK** (bilinen hatalar #1/#3 yüzünden `PAPER_FUNDING=true` iken fiilen 0; 936 referansı da böyle). Duyarlılık koşusu `FIX_FUNDING=1` ile: `data/*_funding_bnc.csv` (Binance, VEKİL) + MEXC dosyası (daha uzun olan seçilir) |
| A referansı | `arastirma/paylasim_paketi_2026-09-26/ikiz/ikiz_k25_cap25_islemler.csv` (936 işlem) |

## Koşular
| koşu | bot | aday | not |
|---|---|---|---|
| A | RISK_SCALE 1.75 (tüm kollar %3.5) | yok (yalnız gözlem) | 936 ile eşleşmeli |
| A75 | RISK_SCALE 1.3125 (%2.625) | yok | |
| B | A75 ile aynı | var, `risk_haritasi.json` (her sembol/yön %0.875 = 0.25 × %3.5; TRX hariç) | |
| S | bot kolları yürütülmez | tek başına, sabit risk birimi 100 USDT (10.000'in %1'i) | R cinsinden |
| *_2x | aynı | aynı | kayma iki kat |
| S_cikis | — | aday stop/zaman çıkış kayması 15.85bp | aday için ihtiyatlı çıkış stresi |
| *_f | aynı | aynı | funding duyarlılığı (Binance vekil) |

## Aday maliyet varsayımı
- Aday için ayrı bir canlı ölçüm YOK. Squeeze'in düşük ölçümü (1.49bp) KULLANILMADI.
- Ana koşu, ikizin piyasa girişi modelini kullanır (15.85bp; squeeze ölçümünün ~10 katı).
- Çıkış: botun ikiz modeli. Ayrıca aday çıkışlarına 15.85bp stres uygulanır (S_cikis).
- Spread ölçülen kaymanın içindedir (dolum − sinyal kapanışı); ikinci kez eklenmez.
- Miktar adımı: `risk.py` tabanı 0.001 birim (tüm kollarla aynı). MEXC kontrat büyüklüğüne
  yuvarlama ikizde hiçbir kol için modellenmiyor; aday işlemlerinin nominali yüzlerce/binlerce
  USDT olduğundan etkisi ihmal edilebilir. Fiyat adımı modellenmiyor.

## Giriş zamanı
- Sinyal q kapanışında bilinir. Aday, o damgada TÜM bot kolları çalıştıktan sonra denenir.
- Dolum, ikizin o anki fiyatıdır (= q kapanışı), üzerine kayma eklenir.
- 1h veride `open[q+1] == close[q]` oranı %99.98'dir (SOL/ETH/XRP/LTC ölçüldü), yani bu fiyat
  q+1 açılışıdır. q içindeki bir fiyattan geriye dönük dolum yazılmaz.
- Stop/hedef q kapanışında sabitlenir. Dolum farklı çıkarsa hedef 2R'ye yeniden taşınmaz.

## Önceden kayıtlı karar kuralları
Sonuçlar görülmeden yazıldı. Sonuçtan sonra DEĞİŞTİRİLMEZ.

**ELENDİ**, aşağıdakilerden biri olursa:
- S (ana maliyet) ortalama net R ≤ 0.
- B − A75 net USDT ≤ 0 (ana maliyet).

**İLERİ PAPER TEST ADAYI** için aşağıdakilerin **hepsi** gerekir:
1. S kapanan işlem ≥ 100.
2. S ortalama net R hafta-kümeli bootstrap %95 GA alt sınırı > 0 (5000 tekrar, seed 20260930).
3. S_2x ortalama net R > 0 ve S_cikis ortalama net R > 0.
4. Dönem tutarlılığı (S):
   - Kronolojik iki yarının (sınır 2024-12-01) ikisinde de ortalama net R > 0.
   - 2023–2026 takvim yıllarının en az 3'ünde ortalama net R > 0.
5. En iyi 5 işlem çıkarıldığında S toplam net R > 0.
6. Portföy katkısı:
   - B − A75 > 0 hem ana hem 2x maliyette.
   - B'nin maks. düşüşü A75'inkinin 1.10 katını aşmaz.

**KANIT YETERSİZ:** diğer tüm durumlar.

Olumlu sonuç canlıya alma onayı değildir. Bu verinin tamamı bot geliştirmesinde defalarca
incelendi; dokunulmamış test dönemi YOK. Sonuç ne olursa olsun ileriye dönük paper test gerekir.
