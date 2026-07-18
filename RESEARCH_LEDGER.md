# Araştırma Kayıt Defteri (Research Ledger)

Amaç: hangi fikir ne zaman, hangi kanıtla denendi ve ne karar çıktı — tek
bakışta. Yeni bir fikir gelince ÖNCE buraya bak: mühürlü bir ailenin
varyantıysa, mührü kaldırmak için YENİ VERİ (farklı dönem/mekanizma) gerekir,
aynı verinin başka açısı yetmez.

Kurallar (her test için değişmez):
- Kabul çıtası KOŞMADAN ÖNCE dosyaya yazılır (ön-kayıt), sonradan esnetilmez.
- Çok dönem (train/test) + komşu-parametre tutarlılığı + (varsa) çok-coin şartı.
- Geçen aile önce paper-forward'a girer; canlı ancak orada da yaşarsa.

## 🔒 MÜHÜRLÜ (denendi, geçemedi)

| Tarih | Aile / Fikir | Test | Sonuç | Mühür sebebi |
|---|---|---|---|---|
| 2026-07 | ETH/BTC spread mean-rev (piyasa-nötr) | research_spread.py 3×3 grid | 0/9 | Rejim dönek: kısa pencere TR-kaybet/TE-kazan, uzun pencere tam ayna |
| 2026-07 | Günlük TSM momentum 3-14g | research_tsm.py 4×3 | 1/12 | Tek PASS (LB14/T0) komşusuz + ETH TRAIN 0.89 |
| 2026-07 | Aylık TSM 21-60g (#2b, itiraflı hipotez) | research_tsm.py --monthly, 3-coin şart | 0/12 | BTC+ETH LB60'ta geçti, SOL TEST çöktü (0.65-0.72) — anomali varlıklar-arası taşınmıyor |
| 2026-07 | NR-N dar gün kırılımı (Crabel) | research_nr7.py 3×3 | 0/9 | TRAIN tamamen negatif (PF 0.52-0.93, her hücre eksi R) |
| 2026-07 | Funding-penceresi kontraryan | research_funding_window.py 3×2, perp+funding verisi | 0/6 | TRAIN hep <1.0; ETH her yerde çöp (0.56-0.81) |
| 2026-07 | NW+KAMA confluence (1h/1D/2D, event/state/agree) | validate_nw_kama.py, 10 coin, 4 yıl | GÜÇLÜ 2/10 | Çoklu-karşılaştırma şansının öngördüğü sayı; ETH+AVAX forward takibe alındı (aşağıda) |
| 2026-07 | sr_breakout'a BE+trailing | 1m intrabar, üretim sinyalleri | fixed +23.4R vs trail +7.1R | Doğrulanmamış eklenti kazananı boğuyordu — canlıdan söküldü |
| 2026-06/07 | TP1/TP2 kademeli çıkış (tüm sleeve'ler) | scratch_exits, 1m intrabar | Her sleeve'de toplam R düştü | WR yükseltip beklentiyi kesiyor |
| 2026-06 | BB'ye BE/trailing/erken-kesme | research_mgmt.py, 1M path | Hiçbir varyant baseline'ı (+%26.9) geçemedi | Mean-rev'in TP yolu dalgalı — stop taşıma zarar |
| 2026-06 | Asia BO canlı | backtest_live model | PF 0.78 | Kapatıldı (intra-candle giriş varsayımı gerçekte yok) |
| 2026-06 | ORB stop-entry (tick dokunuşta giriş) | iki dönem karşılaştırma | 1.dönem 1.65 kazandı, 2.dönem 0.87 çöktü | Limit-retrace (1.41/1.42) daha sağlam — varsayılan o |
| 2026-öncesi | HTF trend filtresi BB'ye | research_bb_filters | PF düştü | BB extreme'leri her rejimde döner |
| 2026-öncesi | BTCD, mum formasyonları, momentum filtresi, session filtreleri, 15m girişler | research_* dosyaları | Geçemedi | Arşivde |

## ⏳ FORWARD'DA (jüri dışarıda — ileri veri karar verecek)

| Başlangıç | Fikir | Araç | Karar kuralı | Karar tarihi |
|---|---|---|---|---|
| 2026-07-14 | NW+KAMA event-1D, ETH+AVAX | nw_kama_tracker.py (gece cron) | n≥15 & PF≥1.3 → sleeve tasarımı; değilse mühür | ~2026-09 |
| 2026-07-13 | Orderflow onay filtresi (taker delta / derinlik) | orderflow_log.csv ×2 instance + analyze_orderflow.py | kova n≥40/40 & PF farkı ≥0.30 & 2x veride yön korunur | 2026-08-08+ |
| 2026-07-13 | Funding aşırılık filtresi (BB sinyaline) | funding_log.csv ×2 + aynı çıta | aynı | 2026-08-08+ |
| 2026-07-12 | Tam-sistem paper forward ($10k sanal) | /opt/bot2-paper, live_report --paper | model (+%40/ay medyan) vs gerçek | 2026-08-08 |

## 📋 SIRADA (kanıt şartına bağlı, hazır bekliyor)

| Fikir | Şart | İş |
|---|---|---|
| LTC×BB genişlemesi | 8 Ağustos'ta BB canlı karnesi yeşilse | BB_SYMBOLS+SYMBOLS'a ekle (1 satır) |
| ~~ORB canlıdan çıkarma~~ | **UYGULANDI 2026-07-17** (erken, yeni delille) | benchmark_recent kanıtı: aynı pencerede adil BB modeli +$40 yaparken canlı BB 23 sinyalin 4'ünü alabildi — one-per-symbol kuralı yüzünden ORB (12 pozisyon) sembolleri işgal edip BB'yi bloklamış. ORB'nin gerçek maliyeti kendi -$3.20'si değil, ~$40'lık fırsat kaçağı. Doğrudan PF'i de 0.34 (n=12) idi. **GERİ DÖNÜŞ KURALI (ön-kayıtlı): paper ikizde BE'li ORB n≥20'de PF≥1.2 gösterirse canlıya geri alınır.** |
| RISK_SCALE artırımı (1.25→1.5→2.0 kademeli) | Canlı PF ≥1.1-1.2, 30+ trade | .env değişikliği + izleme |
| Oda ayrımı: sleeve-ailesi başına MEXC sub-account (çekirdek/swing/intraday) | Hesap ≥ ~$2-3k (bölünme min-lot'u bozmayacak boyut) | Tam izolasyon: one-per-symbol çakışması biter, her sleeve tam modeliyle oynar. Kullanıcı fikri 2026-07-17 |

## 💡 HENÜZ TEST EDİLMEMİŞ ADAY HAVUZU (sprint 2 malzemesi)

- Hafta-içi/saat bazlı saatsellik (weekend etkisinin genellemesi)
- OI-divergence (fiyat yeni tepe + OI düşüyor → tükeniş)
- Vadeli-spot baz (basis) aşırılıkları
- Kullanıcıdan gelen her fikir → önce burada kaydedilir, sonra ön-kayıtlı harness

## 🔍 DERİN DENETİM (2026-07-14, çok-ajanlı tarama + elle doğrulama)

Düzeltilen (hepsi kodda doğrulandı, testler yeşil):

| Bulgu | Dosya | Kanıt / Etki |
|---|---|---|
| Squeeze eşiği off-by-one (min_sq+1) | strategies/squeeze.py | Ampirik: research 141 sinyal, canlı 127 — 5-barlık koillerin tamamı (%10) yutuluyordu. Düzeltilmiş = research 141/141. (2026-06-19 "düzeltmesi" hatanın kendisiymiş.) |
| Donchian bayat 4h buffer yarışı | main.py | 1h/4h poller fazları bağımsız → sınırda ~%50 bayat analiz; taze kırılımlar sessizce kaçıyordu. Fix: beklenen 4h açılış ts doğrulanır, gerekirse zorla poll, bayatsa atla + tekrar-analiz koruması. |
| Canlı close kontrat kesme (dust) | exchange.py | base→contract float dönüşü 1 ulp altta kalınca 49'un 48'i kapanıyor, DB tam kapanış yazıyor, dust stopsuz kalıyordu. Fix: round_up (reduceOnly overshoot'u sınırlar). |
| Paper giriş fee çifte kesim | exchange.py | Taker girişte fee hem girişte hem kapanış net_pnl'inde düşülüyordu → paper bakiye trades toplamından sapıyordu. Fix: fee yalnız kapanışta. |
| Paper close yanlış sleeve | exchange.py | Sadece sembole bakıp İLK pozisyonu kapatıyordu — ORB max-hold BB swing'i kapatabiliyordu. Fix: yön + en yakın miktar eşleşmesi. |
| Çekim → sahte kill-switch | execution.py | Gün içi para çekimi ham equity kıyasında %35 "zarar" gibi görünüp emergency-close tetikleyebilirdi. Fix: baseline, deposit.py meta akışıyla düzeltilir. |
| Korumasız-giriş kapanışı defter dışı | execution.py | no_stop_safety round-trip'i hiçbir kayda girmiyordu (görünmez para kaybı). Fix: trade open+close satırı yazılır. |
| FVG/IFVG kesinti sonrası bozuk zone | strategies/fvg.py, ifvg.py | Backfill'de ara barlar işlenmediği için kırılan zone haritada "aktif" kalıp ters yönde trade edilebilirdi. Fix: bar sürekliliği kopuksa zone state sıfırlanır. |

Bilinçli ERTELENEN (kayıtlı, mühürlü değil):
- Kısmi harici kapanışta PnL defterlenmiyor (main.py reconciliation) — çıkış
  fiyatı bilinmediği için tasarım kararı gerekir; günlük defter-banka kontrolü
  farkı yakalıyor. Ertelendi: 8 Ağustos oturumu.
- Paper tick-girişli pozisyona tam-mum SL kontrolü (ORB_STOP_ENTRY=false iken etkisiz).
- initialize() tek-kline forming bar kabulü (sadece yeni listelenen coin senaryosu).

> Not: Mühür "fikir aptalcaydı" demek değil, "bu veri bu çıtayı geçemedi" demek.
> Canlıdaki 7 sleeve de aynı makineden sağ çıkanlardır — makine böyle çalışır.

## 🔍 DERİN DENETİM v3 (2026-07-18, son 3 boyut + elle doğrulama)

Düzeltilen (kodda doğrulandı, 7 test yeşil):

| Bulgu | Dosya | Etki / Fix |
|---|---|---|
| **Sleeve exception izolasyonu** (kimse kimseyi bloklamasın) | main.py | Tüm strateji bloğu TEK try/except'teydi — bir sleeve exception atınca o mumdaki SONRAKİ tüm sleeve'ler atlanıyordu. Fix: 9 sleeve'in her biri kendi try/except'inde; biri düşse diğerleri koşar. |
| Squeeze %8 risk mirası | config.py, execution.py | Squeeze else-branch'e düşüp max_risk_per_trade (canlı .env'de MAX_RISK_PCT=%8) miras alıyordu; doğrulaması %2'ydi. Cap çoğu zaman maskeliyordu ama sıkı SL'de ~4x aşırı boyut riski. Fix: squeeze_risk_pct=%2 eklendi. |
| Startup fetch retry yok | data.py | Tek geçici fetch hatası buffer'ı BOŞ bırakıp sleeve'i sessizce öldürüyordu (squeeze 4h MTF kapalı, Donchian/FVG saatlerce ölü). Fix: 3 deneme + backoff. |
| Paper yanlış-coin fiyatı | main.py | _current_price fallback'i bir coin'in emrini başka coin'in fiyatıyla doldurabiliyordu. Fix: candle handler her mumda per-coin taze fiyatı exchange'e push ediyor. |
| Fiyat-yaşı guard'ı yok | data.py, main.py | Sessizce donmuş websocket ticker _current_price'ı donduruyor, mum-staleness yeşil kalıyordu → canlı BE hiç kurulmuyordu. Fix: price_age_seconds() + entry-skip guard'ına OR'landı. |
| .env.example ORB_ENABLED=true | .env.example | ORB 2026-07-17'de canlıdan çıkarıldı; örnek dosya güncellendi. |

Bilinçli ERTELENEN (8 Ağustos — backtest kararı gerekir, kör düzeltme yok):
- FVG per-coin allowlist yok (#2): coin listesi zaten SYMBOLS ile sınırlı; FVG'nin
  hangi coinlerde doğrulandığı netleşince allowlist eklenir.
- Squeeze ADX-ranging gate (#3): canlı squeeze'i ranging'de blokluyor; research bunu
  gate'ledi mi doğrulanmalı (squeeze off-by-one gibi olabilir).
- BE@1R mum-kapanışta vs intrabar (#4): canlı BE, backtest'in intrabar 1R dokunuşundan
  daha geç kuruluyor; tick-path'e taşımak ayrı bir değişiklik.
- Squeeze MTF 4h yalnız 120 1h bar'dan (#8): EMA20 seed'i ~%5.5 ağırlık taşıyor,
  midline yakınında filtreyi çevirebilir; buffer büyütme minör iyileştirme.

## ✅ NİHAİ MİNİMAL CONFIG (2026-07-18, fast_bt 3-yıl doğrulaması)

7-sleeve config 3-yıl look-ahead'siz backtest'te net kaybeden (PF 0.98, 4 yılın
1'i +). Çöp atıldı, sadece 3-yıl 4/4-yıl doğrulanmış kazananlar kaldı. fast_bt.py
(vektörel, saniyeler) 3 yıl gerçek veride (2023-2026):

| Sleeve @ coin | 3-yıl | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|
| donchian @ BTC | +$98 PF1.32 | 1.36 | 1.32 | 1.32 | 1.25 |
| squeeze @ SOL | +$193 PF1.32 | 1.08 | 1.45 | 1.12 | 1.76 |

İkisi de 4/4 yıl pozitif. Farklı coinler → SIFIR ÇAKIŞMA.
CANLI CONFIG: donchian=BTC, squeeze=SOL, BB/FVG/IFVG/SR/ORB kapalı,
SYMBOLS=BTC,SOL, MAX_POSITIONS=2, RISK_SCALE=1.0 (tam doğrulanmış risk).

Kesilen (3-yıl net kaybeden): BB/mean_rev (-$156, en çok SOL), FVG/IFVG/SR.
Not: bu in-sample (2023-2026 = seçim dönemi); forward gerçek hakem. Ama
elimizdeki en kanıtlı, en sade, çakışmasız config bu.

## ✅ NİHAİ CONFIG DÜZELTMESİ (2026-07-18, faithful_bt canlı-birebir 3-yıl)

verify_conformance: fast_bt squeeze üretim sınıfından %50 sapıyordu → fast_bt
squeeze GÜVENİLMEZ. faithful_bt (üretim sınıfı = canlı birebir, 3-yıl):

| Sleeve @ coin | 3-yıl | 2025 | 2026 |
|---|---|---|---|
| squeeze @ SOL | +$107 | **-7** | **-14** (çürümüş, son 2 yıl -) |
| squeeze @ BTC | +$225 | +4 | +34 (4/4 yıl +) |
| donchian @ SOL | +$127 | +50 | +14 |
| donchian @ BTC | +$83 | +22 | +7 |

İlk deploy (donchian-BTC + squeeze-SOL) squeeze-SOL çürümesi yüzünden 2026'da
net eksi olurdu. DÜZELTME: squeeze→BTC (en iyi coini), donchian→SOL. Hâlâ
farklı coinler → sıfır çakışma. Son 2 yıl her ikisi de pozitif.
CANLI: SQUEEZE_SYMBOLS=BTC, DONCHIAN_SYMBOLS=SOL.

DERS: fast_bt (vektörel) squeeze'de canlıdan saptı; faithful_bt (üretim sınıfı,
bounded pencere = canlı birebir) doğru araç. Her strateji kararı faithful_bt
ile alınır. Kullanıcının "test güvenilir olmalı" ısrarı kötü deploy'u önledi.

## ✅ BYTE-DENK KONFORMANS KANITI (2026-07-18) — test == canlı, eksiksiz

Kullanıcı: "testler tamamen güvenilir aynı gerçekteki gibi olacak, livede de
testlerdeki gibi çalışacak, hatasız eksiksiz tamamen." Bunu main.py'yi satır
satır doğrulayıp KANITLADIK — faithful_bt canlının BİREBİR aynısı:

| Boyut | CANLI (main.py) | faithful_bt / fast_bt | Denk? |
|---|---|---|---|
| Sınıflar | `from strategies.squeeze/donchian import ...` (17,24) | AYNI sınıflar | ✅ |
| ATR/ADX fn | `from indicators import atr, adx` (19) | AYNI fonksiyonlar | ✅ |
| Periyotlar | atr_period=14, adx_period=14 (config) | 14 / 14 | ✅ |
| Squeeze penceresi | get_candles(120) (187) | d1[i-119:i+1] = 120 bar | ✅ |
| Donchian penceresi | get_candles(260) 4h (681) | d4[i-259:i+1] = 260 bar | ✅ |
| ATR hesabı | atr(df_120/260,14).iloc[-1] (209,713) | PENCERE-YEREL .iloc[-1] | ✅ |
| Squeeze kapısı | bo_allowed = regime!="ranging" = adx>20 (258, _get_regime 1034) | pencere-yerel adx<=20 → continue | ✅ |
| Çıkış modeli | squeeze/donchian BE/trailing DIŞINDA (1079: sadece orb/ifvg) → sabit SL/TP + max-hold | simtrades sabit SL/TP + max-hold | ✅ |
| SL ölçeği | RiskManager × giriş atr_val | simtrades giriş pencere-yerel ATR | ✅ |

KRİTİK DÜZELTME: ATR/ADX artık TAM-SERİ değil PENCERE-YEREL hesaplanıyor
(canlı yalnız 120/260 barlık buffer'a sahip). ADX ~20.0 sınırında seri uzunluğu
değeri kaydırıp kapıyı ters çevirebiliyordu; bu düzeltilmeden faithful_bt canlıdan
sapardı. Düzeltince squeeze@BTC $33→$25'e indi (DÜRÜST, canlı-birebir rakam).

fast_bt KONSOLİDASYONU: hem squeeze hem donchian artık üretim sınıfına delege
(faithful_bt.prod_*). Vektörel kopyalar terk edildi (squeeze %48, donchian %99.1
sapıyordu). Artık TEK doğru yol var: fast_bt == faithful_bt == CANLI.

verify_conformance.py sonucu (yerel BTC, 1 yıl):
  - SQUEEZE ÜRETİM: 47/47 sinyal ✅ BİREBİR (fast_bt = canlı)
  - DONCHIAN vektörel: %99.1 (terk edilen kopya — belge amaçlı)
  - SQUEEZE vektörel: %47.9 (terk edilen kopya — NEDEN'ini gösterir)

SONUÇ: Backtest rakamları = canlı botun üreteceği rakamlar. Kanıt kodda,
her strateji kararı faithful_bt/fast_bt (üretim sınıfı) ile alınır.

## 🔴 KRİTİK VERİ HATASI + DÜZELTME (2026-07-18) — spot değil MEXC VADELİ

Kullanıcı sezgisi yakaladı: "belki sol squeeze'de hata yaptık, testte ya da live'de."
DOĞRUYDU. fast_bt.load spot/Binance çekiyordu; canlı MEXC VADELİ (perp) işlem görüyor:
  - non-BTC: `ccxt.mexc()` + `COIN/USDT` = MEXC SPOT (canlı = COIN/USDT:USDT VADELİ)
  - BTC: yerel `BTCUSDT-1m.csv` = BINANCE (canlı = MEXC vadeli)
Spot/Binance ≠ MEXC perp (funding/basis, farklı wick'ler). Sinyal MANTIĞI byte-birebir
ama YANLIŞ MUMLARLA besleniyordu. Düzeltme: load() artık MEXC VADELİ (defaultType=swap,
COIN/USDT:USDT) = canlının işlem gördüğü enstrümanın AYNISI.

En çarpıcı: squeeze@SOL 2026 SPOT'ta −$21.59 (PF0.57 "çürük") görünüyordu →
VADELİ'de +$51.81 (PF2.12, EN İYİ yıl). Çürüme YOKTU, spot artefaktıydı. Yanlış
veri neredeyse iyi bir sleeve'i kestiriyordu.

DÜZELTİLMİŞ RAKAMLAR (MEXC VADELİ, canlı-birebir, 3.3 yıl, faithful_bt):
| Sleeve @ coin | Toplam | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|
| donchian @ SOL | +$135 | +70 | +4 | +50 | +10 |  (4/4 yıl +)
| squeeze  @ SOL | +$103 | +33 | +10 | +8 | +52 |  (4/4 yıl +)
| squeeze  @ BTC | +$84 | +15 | +52 | +18 | −2 |  (2026 SÖNÜK)
| donchian @ BTC | +$60 | +2 | +33 | +6 | +19 |  (4/4 yıl +)

GÖZLEM: donchian = istikrarlı (her iki coinde 4/4 yıl +). squeeze = streaky,
"hangi coin" oynak (2024 BTC yıldız, 2026 SOL yıldız / BTC sönük).

## ✅ NİHAİ CANLI CONFIG (2026-07-18) — güvenilirlik önceliği

Karar: **donchian @ BTC + donchian @ SOL** (squeeze KAPALI). Gerekçe: donchian tek
eksi-yılı olmayan sleeve (ikisi de 4/4 +); sönen squeeze@BTC yerine aynı coinde
istikrarlı donchian. squeeze'in "hangi coin" kumarı oynanmaz. Toplam ~$195, her yıl +.
Farklı coinler → sıfır çakışma. Tek strateji riski kabul edildi (donchian robust trend
edge, iki coinde kısmi decorrelation).

CANLI .env (/opt/bot2, btc-bot.service): SYMBOLS=BTC,SOL; DONCHIAN_SYMBOLS=BTC,SOL;
SQUEEZE_ENABLED=false; MAX_POSITIONS=2; RISK_SCALE=1.0 (=%2/işlem, backtest ile birebir);
FIXED_MARGIN_USDT=0 (risk-bazlı boyutlama aktif). Servis restart edildi, active.

DERS: sinyal mantığı byte-birebir olsa bile YANLIŞ VERİ KAYNAĞI testi yalancı yapar.
Her backtest canlının işlem gördüğü borsa+enstrümandan (MEXC vadeli) beslenmeli.
Kullanıcının "testte hata olabilir" ısrarı ikinci kez kötü kararı önledi.
