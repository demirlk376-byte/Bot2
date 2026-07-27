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

## 🔬 TAM SLEEVE × COIN SWEEP (2026-07-18) — faithful_all, MEXC vadeli, 3.3 yıl

Test harness'ine güvendikten sonra (test==canlı, doğru veri kanıtlı) TÜM sleeve'ler
6 likit MEXC-vadeli coinde canlı-birebir koşuldu (faithful_all.py). Market-giriş
sleeve'leri byte-birebir; limit-giriş (orb/fvg/ifvg) modellendi (kesin değil, karara
katılmadı).

MARKET (byte-birebir) $ (BAL=190, risk_pct sleeve'e göre, 3.3 yıl):
| sleeve | BTC | ETH | SOL | BNB | XRP | DOGE |
|---|---|---|---|---|---|---|
| donchian | +60✅ | +126 | +135✅ | +79 | +79 | +72 |  (6/6 coin +, evrensel)
| squeeze  | +84 | +85 | +103✅ | +22 | +123 | +114✅ |
| sr_break | +18 | +48 | +10 | +13 | +89 | −48 |  (coin-seçici, güvenilmez)
| BB       | +52 | +56 | −53 | +17 | +29 | −17 |  (zayıf/kaybeden, elendi)
(✅ = her yıl pozitif)

BULGULAR: donchian = evrensel edge (6/6 coin +). squeeze = birkaç coinde çok güçlü
(XRP/DOGE/SOL). sr_break & BB güvenilmez → elendi. Limitler (orb $+271 SOL gibi)
MODEL, karara katılmadı.

## ✅ CANLI CONFIG v3 (2026-07-18) — 4 coin, dengeli, çakışmasız

Coin başına en iyi market sleeve, 2 donchian + 2 squeeze:
| coin | sleeve | $ 3.3y | PF |
|---|---|---|---|
| SOL | donchian | +135 | 1.46 |
| ETH | donchian | +126 | 1.40 |
| XRP | squeeze | +123 | 1.40 |
| DOGE | squeeze | +114 | 1.50 |
Toplam ~$498/3.3yıl (in-sample). Her coin tek sleeve → sıfır çakışma.

CANLI .env (/opt/bot2, btc-bot.service):
  SYMBOLS=SOL,ETH,XRP,DOGE (full :USDT form)
  DONCHIAN_ENABLED=true, DONCHIAN_SYMBOLS=SOL,ETH
  SQUEEZE_ENABLED=true,  SQUEEZE_SYMBOLS=XRP,DOGE
  MAX_POSITIONS=4, RISK_SCALE=1.0 (=%2/işlem, backtest birebir), FIXED_MARGIN_USDT=0
Kullanıcı 4-coin dengeli'yi seçti (6-coin ~$661 agresif, 3-coin ~$309 en sağlam
alternatifleri arasından). Forward tutarsa 6'ya çıkılabilir. sr_break/BB/orb/fvg/ifvg
kapalı (güvenilmez ya da model).

NOT: in-sample (2023-2026 = seçim dönemi). Çürüme-izleme önerildi (bir sleeve@coin
son N işlemde PF<1 olursa uyarı) — henüz eklenmedi.

## ⚠️ BB ÇAKIŞMA TUZAĞI (2026-07-18) — config v3 deploy sırasında yakalandı

BB'nin enable flag'i YOK, sadece bb_symbols allowlist'iyle geçitleniyor. Eskiden
BB'yi kapatmak için BB_SYMBOLS=XRP (o zaman işlem görmeyen coin) yapılmıştı. config
v3'te XRP işlem görmeye başlayınca BB tam XRP'de uyandı → [XRP] active sleeves:
BB, Squeeze = ÇAKIŞMA. Startup logu yakaladı ("active sleeves" satırları).
DÜZELTME: BB_SYMBOLS=NONE/USDT:USDT (hiç işlem görmeyen sahte sembol; _normalize_symbol
sadece formatlar, fetch edilmez). BB her yerde kapalı, ileride BTC/BNB eklense de
kapalı kalır. DERS: bir sleeve'i "işlem görmeyen coine sabitleyerek" kapatmak, o coin
sonradan traded olursa geri teper — kapatmayı fetch edilmeyen sahte sembolle yap.
Config değişince HER ZAMAN "active sleeves" startup logunu kontrol et (coin başına 1).

## ✅ CANLI CONFIG v4 (2026-07-19) — 7 coin, disiplinli genişleme

10 yeni likit MEXC-vadeli coin faithful_all ile tarandı. donchian EVRENSEL edge
çıktı (yeni 10 coinin 9'unda +): ADA+156, TRX+101, NEAR+100, BNB+79, AVAX+75,
DOT+62, BTC+60, LINK+28, ATOM+12 (sadece LTC−37). squeeze seçici (BTC+92, TRX+57,
ATOM+50 iyi; DOT−81, ADA−73 kötü).

Yıl-yıl robustluk (faithful_bt, byte-birebir) ile 3 sağlam yeni coin eklendi:
| coin | sleeve | 2023/24/25/26 | PF | 
|---|---|---|---|
| ADA | donchian | +50/+34/+62/+11 (4/4) | 1.53 |
| NEAR | donchian | +42/+18/+8/+31 (4/4) | 1.31 |
| TRX | squeeze | +10/+32/+11/+5 (4/4) | 1.45 |
KRİTİK: TRX'te donchian 2025 −$2 (3/4) ama squeeze 4/4 → squeeze seçildi.
Yıl-yıl bakmasak yanlış sleeve giderdi. BNB donchian 3/4 (2026 −$0.5 düz) →
şimdilik dışarıda (opsiyonel 8.).

CANLI (/opt/bot2, btc-bot.service):
  SYMBOLS=SOL,ETH,ADA,NEAR,XRP,DOGE,TRX (full :USDT)
  DONCHIAN_SYMBOLS=SOL,ETH,ADA,NEAR ; SQUEEZE_SYMBOLS=XRP,DOGE,TRX
  MAX_POSITIONS=7, RISK_SCALE=1.0, BB_SYMBOLS=NONE (kapalı)
Her coin tek sleeve → sıfır çakışma (startup "active sleeves" ile teyit).
In-sample katkı ~+$313/3.3yıl (mevcut +498 üstüne). Riski ARTIRMADAN,
kanıtlı edge'i çeşitlendirerek büyüme (matematiksel doğru yol).

ELENEN ARAŞTIRMALAR (hepsi doğru veride, PC'de, para kaybetmeden reddedildi):
NW-alone −$656 (0/12), KAMA-alone +$107 ama PF1.13 short-only (yetersiz),
NW+KAMA combo −$78, grid bot felaket (SOL maxDD $2095 = ~11x hesap yıkımı).
DERS: WR peşinde koşma (kâr değil, filtreler overfit+winner keser); risk kırma
(varyans+iflas, Kelly'yi geçme); çeşitlendirme = doğru büyüme düğmesi.

## ✅ GELİŞTİRME v1 (2026-07-21) — donchian rr 2.0→2.5 (doğrulanmış, deploy)

DEPLOY sonrası sistematik iyileştirme avı (paralel testler, PC'de, canlı-doğru):
- **donchian TP/RR: 2.0→2.5 → DEPLOY.** +$96 (+16%), PF 1.40→1.49, yıl-yıl 3/4 belirgin
  iyi + 2025 eşit (−$1.4 gürültü). Monotonik sweep (yüksek rr hep iyi) = yapısal, overfit
  değil (kazananları koştur). CANLI: DONCHIAN_RR=2.5 (/opt/bot2/.env, env — kod yok).
- **squeeze rr3.0: RED.** Aggregate +$33 ama per-year mixed (2023/24 kötü, 2025/26 iyi =
  kayma, robust değil). squeeze rr2.5 kalıyor. Disiplin: mixed per-year → güvenme.
- **donchian MTF (günlük EMA20 trend hizası): GERÇEK ama ertelendi.** +$42, PF 1.40→1.45,
  HER YIL ≥ baseline. Ama kod gerektiriyor (canlı donchian'a günlük-trend kontrolü); RR
  daha büyük + env-only olduğu için önce o. Sonra eklenebilir.
- **max-hold:** donchian 45 marjinal (+$22), squeeze 48 zaten en iyi → dokunma.
- **EMA200 / EMA50-200 golden / PxBoth / MTF+golden:** hepsi redundant/zarar → RED.

## 🔧 ÖZ-DENETİM: İKİ ARAÇ BUG'I YAKALANDI (kullanıcı ısrarı)
1. **post-hoc filtreleme YANLIŞ:** quality_test/ema_test filtreyi işlem üretildikten sonra
   uyguluyordu → occ/slot mantığını yeniden koşmuyor → SAHTE iyileştirme (BTC +EMA200
   post-hoc +$40 vs üretimde +$36). DÜZELTME: filter_test = filtre ÜRETİM SIRASINDA
   (elenen sinyal slotu meşgul etmez, canlı-doğru). baseline faithful_bt ile birebir.
2. **cur=rest[2]=sl_a (rr değil):** rr_test squeeze "mevcut"u yanlış (2.0) gösteriyordu →
   rest[3]. + tatlı-nokta seçimi (max'ın %97'sine ulaşan en küçük rr) = extreme'e overfit yok.
DERS: aracın kendisi denetlenmeden sonucuna güvenilmez. İki bug da bu sayede elendi.

## SL/EXECUTION DENETİMİ (sl_audit, öz-denetimli)
Canlı DB'de 27/30 SL/TP işlemi araç↔bot BİREBİR uyuştu (araç TP kararlarını da doğru
üretiyor = güvenilir + execution temiz). 3 uyuşmazlık: fvg (kapalı strateji) + 'neither'
= 1h çözünürlük/entry-mum-içi sınırı, execution bug DEĞİL (ters-sıra vaka yok). MFE:
%39 temiz kayıp, %11 whipsaw; SL'ler tasarım gereği, trailing/BE zaten test edilip elenmişti.

## 🔎 SL AVI (2026-07-22) — filtre sınıfları elendi (literatür + veri-güdümlü)

Amaç: SL'leri (sahte breakout) TP'leri bozmadan önleyen nedensel filtre bul.
İki bağımsız açı, ikisi de NEGATİF çıktı (dürüst, temiz sonuç):

**A) Literatür filtreleri (vol_filter_test, üretimde/canlı-doğru, yıl-yıl):**
hacim-onayı (breakout hacmi >1.5× 20-bar ort), ATR-genişlemesi, volatilite-tabanı.
- TOPLAM baseline PF1.48 $1115 → +Hacim PF1.58 ama SADECE $806 (−$309), +ATRexp $862,
  +VolFloor $1025 (squeeze'de PF 1.40'a DÜŞÜYOR — coil stratejisine ters), +Hacim+ATR $631.
- Hepsi PF'i sadece İŞLEM KESEREK yükseltiyor; total hep düşüyor, hiçbiri her-yıl korumuyor.
- NEDEN: sleeve'ler breakout'u zaten sıkı ön-filtreliyor (donchian EMA200+40-kanal;
  squeeze coil+ADX>20+MTF) → "düşük hacim=sahte" için artık marjinal edge yok. RED.

**B) Veri-güdümlü ayrışma (loser_analysis, TP-kazanan vs SL-kaybeden giriş özellikleri):**
- HİÇBİR özellik >0.4σ ayrışmıyor (adx/atr%/ema200-uzaklık/rejim/momentum hepsi ≤0.25σ).
  → SL'ler giriş anında ÖNGÖRÜLEMEZ (trend/breakout edge'inin doğası, tasarım gereği).
- TEK yapısal sinyal: donchian gün-içi — Pzt %61/Sal %65 SL vs Çar %41/Per %37.

**C) Gün-içi filtresi (dow_test, veri-taranmış lead → yıl-yıl sınandı):**
- -MonTue: PF 1.49→**1.67**, total $700→$700 (AYNI para, 168 az işlem) — aggregate HARİKA.
- AMA yıl-yıl: 2023 $174→$161 KÖTÜ, 2026 $118→$90 KÖTÜ (Pzt/Sal zayıflığı 2026'da TERSİNE
  döndü). Non-stationary → her-yıl testini geçmiyor, hele en güncel yılda. RED (overfit).
- -Mon/-MonTueSun/WedThuOnly: hepsi total kesiyor. RED.

**SONUÇ:** Ana literatür + veri-güdümlü filtre sınıfları elendi. Deploy edilen sleeve'lerin
SL'leri temiz filtrelenemiyor — edge zaten sıkı. Disiplin çalıştı: PF-başlığı güzel görünen
(-MonTue 1.67) aday, recency+per-year kontrolüyle doğru şekilde reddedildi.

**ARAÇ HIZLANDIRMA:** vol_filter/loser_analysis O(n·pencere)→O(n): ATR/ADX full-series bir
kez (i≥260'ta Wilder yakınsadığı için pencere-yerel ≈ full-series; donchian 1e-8), analyze
akışı filtreden bağımsız → coin başına bir kez. 10dk+timeout → 2m42s. baseline birebir
filter_test'i üretti (öz-denetim geçti). Adaylar yine window-yerel filter_test ile doğrulanır.

## 🌱 ÇEŞİTLENDİRME AVI (2026-07-22) — donchian coin genişlemesi (doğrulanmış aday)

Filtre yolu kapandı (SL kesilemiyor) → ledger'ın endorse ettiği büyüme düğmesi: çeşitlendirme.
coin_expand: 13 deploy-dışı coin × 2 sleeve, yıl-yıl, canlı-doğru (donchian rr2.5+MTF).

**İSTATİSTİK:** Her-yıl-pozitif testini şansla geçme ~ (0.5)^4=%6 → sleeve başı ~0.8 coin.
- **donchian 5 coin geçti (şansın ~6 katı) → trend edge coinler arası GENELLEŞİYOR.**
- squeeze 1 geçti (≈şans) → squeeze GENELLEŞMİYOR (kendi tuned coinlerine özel). Coin eklenmez.

**Robust donchian adaylar (window-yerel byte-doğrulandı, filter_test kod-yolundan bağımsız):**
  ICP PF1.57 $155 [7/73/35/40] | BNB PF1.33 $99 [10/58/22/8] | AVAX PF1.29 $87 [34/40/1/12] |
  DOT PF1.22 $70 [10/21/11/27] | VET PF1.21 $66 [7/21/27/11].  ICP iki sleeve'de robust → donchian'a.
  ICP+BNB en güçlü (temiz her-yıl, sağlam 2026). AVAX(2025 ince) / VET(2023 ince) marjinal.

**DEPLOY:** DONCHIAN_SYMBOLS env-var'a ekle (kod yok, geri alınabilir). MAX_POSITIONS tavanı
varsa risk tavanı sabit, sadece fırsat kümesi büyür (sınırlı-riskli net-yukarı).
**UYARILAR:** (1) hepsi kripto=korelasyonlu, mutlak $ artar ama DD $ kadar çeşitlenmez.
(2) in-sample seçim (2023-26), gerçek OOS ileriye. Deploy kararı kullanıcıda (canlı para).

## 📊 PORTFÖY SİM + BNB ÖZ-DENETİMİ (2026-07-22, coin genişleme v2)

coin_expand İZOLE test ediyordu; portfolio_sim koltuk-kısıtlı ORTAK portföyü simüle eder
(giriş sırası + MAX_POSITIONS koltuk mantığı = canlı-doğru). Donchian alt-portföyü:
  MP=3: baseline $692(DD30%) → +ICP+BNB $773(DD30%)  = +$81 aynı DD
  MP=4: $718(DD36%) → $855(DD33%)  = +$137 DAHA DÜŞÜK DD
  MP=5: $742(DD40%) → $949(DD38%)  = +$207 DAHA DÜŞÜK DD   ← tatlı nokta
  MP=8: $742(DD40%) → $996(DD49%)  = +$254 daha yüksek DD
  → MP≥3'te ICP+BNB para+risk-ayarlı İYİLEŞTİRİYOR (yüksek-PF coin koltuk kalitesini artırır).
  → +hepsi(10): marjinal para, PF düşer, DD şişer (MP=8 DD%73). DOT/AVAX/VET REDDEDİLDİ.
Canlı MAX_POSITIONS=7; squeeze(4 coin) de aynı koltukları yediği için efektif donchian
eşzamanı <7 → gerçek davranış tatlı-nokta (MP4-5) rejimine yakın (para↑, DD~sabit/↓).

**BNB ÖZ-DENETİMİ:** Eski ledger "BNB 2026 −$0.5, dışarıda" diyordu; coin_expand 4/4 +$8 buldu.
ÇÖZÜM: eski −$0.5 daha az 2026-verili anlık görüntüden; güncel (19Tem26) BNB 2026=+$7.90
(24 işlem, 11 kaz/46% WR) = pozitif ama BNB'nin EN ZAYIF yılı (ince). rr2.5 breakeven WR~%29
→ pozitif-EV, sahte değil ama küçük. ICP 2026=+$40 (54%WR) çok daha sağlam.
→ **ICP yüksek güven; BNB orta güven (gerçek ama ince 2026).**

**NET ÖNERİ:** DONCHIAN_SYMBOLS'a ICP ekle (kesin), BNB ekle (opsiyonel, ince-2026 kabulüyle).
  SOL,ETH,ADA,NEAR,BCH → +ICP(,BNB). Kod yok, geri alınabilir. filter_test byte-doğruladı.

## 💰 BÜYÜME-OPTIMAL RİSK (2026-07-22, growth_sim) — getiri kolu = risk-bütçesi kullanımı

Filtre+edge tükendi → kalan dürüst getiri kolu: mevcut edge'i risk-tavanına kadar dolu kullanmak
(yeni edge DEĞİL, kaldıraç). growth_sim: deploy portföyünü (7 donch+4 sqz, 1420 işlem ~3.2yıl)
BİLEŞİK simüle eder (canlı gibi, her işlem mevcut equity'nin f'i), MAX_POSITIONS=7 koltuk.

**terminal$ sütunu FANTEZİ** ($190→$64k @2%, $18M @8%): sıfır-sürtünme in-sample bileşik patlama,
gerçek değil (edge ileriye zayıflar, slippage/likidite/min-notional, R-dizisi tekrarlamaz).
Kullanıcıya asla "$64k yapacağız" denmez (hype = geçmişte azarlandı).

**TAŞINABİLİR sinyal = maxDD sütunu** (ölçek-değişmez, kayıp-kümelenmesinin gerçek özelliği):
  2.0%→DD42% (CANLI) | 2.25%→~46% | 2.5%→DD50% (tam tavan) | 3%→57% | 4%→68% | 8%→93%(Kelly tepesi).
Kullanıcı 2%'de, tarihsel DD %42, tolerans %50 → kullanılmamış risk-bütçesi var.

**KARAR: RISK_SCALE 1.0→1.125 (%2.25/işlem).** Tam tavan (2.5%) DEĞİL çünkü:
(1) tarihsel DD ~%46 → %50 tavanın altında tampon; (2) ileriye-dönük DD ~her zaman in-sample'dan
KÖTÜ (en kötü kümelenme henüz olmadı) → 2.5%'te tarihsel tam %50 zaten, ileride aşar. Getiri ~%12↑.
Kaldıraç (kayıpları da büyütür), geri alınabilir (env). Canlı DD izlenir, gerekirse geri çekilir.
Piramitleme (kazanana ekleme, turtle-native) = potansiyel GERÇEK edge kolu, ayrı test edilecek.

## 🔺 PİRAMİTLEME (2026-07-22, pyramid_test) — +EV ama RISK_SCALE domine ediyor → deploy YOK

Turtle-native "kazanana ekleme". Kesin test: add-unit tek-başına EV, birebir tarihsel yolla.
Donchian 7-coin, add tetik = +kATR lehe, kendi 2ATR stop'u, taban TP:
  TABAN PF1.51 $996 | add+0.5ATR PF1.42 $696 HER YIL+ | add+1.0 PF1.24 $367 | add+1.5 PF1.11
  (2025−5,2026−19 ÖLÜ).
**+0.5ATR add GERÇEKTEN +EV** (PF1.42 her yıl+) — trend edge geç-girişte sürüyor. Beklenti
düşüktü (trailing reddedilmişti) ama add-unit farklı: taze +EV pozisyon, stop-hilesi değil.

**AMA DEPLOY EDİLMEZ, 3 sebep:**
(1) add PF1.42 < taban PF1.51 → bir birim risk tabana uniform (RISK_SCALE) konursa daha verimli;
    piramitleme +EV ama RISK_SCALE tarafından DOMİNE EDİLİYOR.
(2) +0.5ATR tetiği seçici değil (846/997=%85 trade tetikliyor) → esasen "daha-verimsiz RISK_SCALE
    artışı", kalite-seçiciliği yok. Uzak tetikler (+1.5) kovalama = ölü.
(3) Netted mod = tek pozisyon/tek stop; iki ayrı-stop'lu ünite canlıda kurulamaz (ortalama-giriş
    olur) → KOD + execution riski (env değil), $188 hesapta değmez.
DERS: gerçek +EV desen bulundu ama basit kol (RISK_SCALE) domine → doğru yargı = deploy etme.
Temiz getiri kolları TÜKENDİ: çeşitlendirme(ICP+BNB) + risk-bütçesi(1.125) deploy edildi; filtre,
gün-içi, literatür-filtre, piramitleme = hepsi kanıtla elendi. Sistem sıkı, overfitsiz büyütüldü.

## 📉 BB DİVERSİFİER AVI + AYLIK GETİRİ (2026-07-22)

**BB mean-rev genişleme (bb_expand, faithful/byte-exact, hafta-sonu, 13 coin taranan):**
DD-düşürücü düşük-korelasyon kolu aranıyordu. SONUÇ: HİÇBİR coin her-yıl-pozitif değil.
En iyi ETH PF1.31 +$106 (2026−16), ATOM PF1.30 +$87 (2023−29), ICP PF1.15 (2025−6). Hepsinin
kaybeden yılı var → BB weekend mean-rev GENELLEŞMİYOR (squeeze gibi coin-özel kırılgan; deploy'daki
LTC o dönem şansı). Robust çakışmasız aday = YOK. DD-düşürücü diversifier bulunamadı. Dürüst negatif.

**AYLIK GETİRİ (monthly_return, deploy portföyü, %2.25 risk, MAX_POS=7, sabit-oran compounding-YOK):**
  1922 işlem/40ay/3.2yıl: ort +25.7%/ay, medyan +22%, en iyi +151%, EN KÖTÜ −35%, std ±40%, poz-ay %72.
  Yıl-yıl: 2023 +42% → 2024 +26% → 2025 +15% → 2026 +21% (EDGE DÜŞÜYOR, en eski yıl en yüksek).
  DÜRÜST çıpa: backtest ~%20-25 ama ileriye BEKLEME — edge zayıflar (2025-26 ~%15-21), varyans dev
  (tek ay −35% mümkün, %28 ay kayıp), küçük-hesap sürtünmesi ısırır. Gerçekçi: ileride ~%5-15/ay +
  arada −%30 aylar + kayıp dönemleri = iyi sonuç. compounding fantezisi ($190→$64k) DEĞİL.

**DURUM:** Temiz kollar bitti. KAZANANLAR (deploy): donchian coin genişleme (ICP+BNB) + risk-bütçesi
(RISK_SCALE 1.125). ELENENLER (kanıtla): SL-filtre, gün-içi, literatür-filtre, piramitleme (+EV ama
domine), BB-diversifier. Sistem sıkı, overfitsiz büyütüldü — pratik tavana ulaşıldı.

## 🐛 ÖZ-DENETİM BUG YAKALAMA (2026-07-22) — occ eksik + düzeltilmiş rakamlar

Kullanıcı "araçları denetle" disiplini → raw-havuz çapraz-kontrolü: monthly_return.gen 7 coin için
2541 donchian üretti, DÖRT temiz araç (cooldown/pyramid/false_breakout_ml/coin_expand) 997 dedi.
KÖK NEDEN: monthly_return.gen + worst_month.gen'de append sonrası **occ=j EKSİK** → coin-başına
tek-pozisyon guard'ı (i<=occ) hiç tetiklenmedi → örtüşen aynı-coin işlemler (SOL'da 261/399,
netted modda İMKANSIZ) → işlem sayısı ~2.5×, getiri+drawdown şişti. DÜZELTME: occ=j eklendi.
Grep audit: SADECE bu 2 raporlama aracı etkilendi; TÜM deploy-karar araçları (growth_sim→RISK_SCALE,
coin_expand→ICP/BNB, portfolio_sim→MAX_POS, cooldown, false_breakout_ml, filter_test) occ'lu = TEMİZ.
ICP/BNB + RISK_SCALE 1.125 kararları SAĞLAM. Düzeltme sonrası monthly==cooldown birebir (1401 işlem,
worst −16.4%) = çapraz-doğrulandı.

**DÜZELTİLMİŞ AYLIK (MP=7, %2.25, sabit-oran): ort +20.2%/ay, en kötü ay −16.4% (−35 DEĞİL),
std ±25%, poz-ay %70. MP=10 neredeyse aynı (+20.9%, worst −16.4%) → koltuk 7↔10 farkı ihmal
edilebilir (yavaş sleeve'ler nadiren >7 eşzamanlı). MAX_POSITIONS 10→7 değişikliği bug-kaynaklı
gerekçeydi ama zararsız; 7'de bırak.**

**DÜZELTİLMİŞ worst_month: niteliksel sonuç AYNEN duruyor** (büyüklük düzeldi): kötü aylar whipsaw
(WR %22-33), BTC-korelasyon +0.09 (çöküş DEĞİL; kötü aylarda BTC ort −0.2%, hatta 2026-04 −16%'da
BTC +12%), donchian-sürücülü (squeeze tamamlayıcı, çoğu kötü ay +), yön dağınık. cooldown (temiz
occ) worst'u düşürMÜYOR + her yıl bozuyor → RED geçerli. false_breakout ML OOS AUC 0.509 → geçerli.
DERS: raporlama araçları da deploy araçları kadar denetlenmeli; raw-havuz çapraz-kontrol = altın.

## ✅ DEPLOY SAĞLIK DENETİMİ + CANLI BYTE-KONTROL (2026-07-22)

**deployed_health (izole, occ-doğru, yıl-yıl):** 11 deploy coininin HEPSİ sağlam — hiçbirinin
2025+2026 toplamı negatif değil, ölü ağırlık YOK. En güçlü ADA(PF1.78), en zayıf BCH(1.30)/BNB(1.33)
ama hepsi son-2-yıl pozitif. PF soğuması (portföy 1.54→1.37) TEK coinden değil, TÜM coinlere yayılmış
= piyasa-geneli edge-decay (coin çıkararak düzeltilmez, kabul). Çıkarma adayı yok, dokunma.
SONUÇ: temiz backtest kolları bitti; sistem sağlıklı+doğrulanmış. Sonraki değer = CANLI doğrulama,
daha fazla in-sample tarama DEĞİL (overfit sızma noktası).

**deployed_backtest (canlı config, düzeltilmiş occ, MP=7, %2.25):** 1401 işlem/3.2yıl, PF1.48, WR%43,
işlem başı +0.256R. Sabit-oran: +$1535, GERÇEK max drawdown (tepe-dip) %19.9, aylık ort+%20/en kötü−%16.4,
her yıl+ (397/496/447/194). Bileşik $190→$275k = FANTEZİ (uyarılı, gerçek A'ya yakın).

**CANLI BYTE-KONTROL (kullanıcı screenshot):** ADA donchian LONG — TP0.1862/SL0.1655, geri-çözülen
giriş≈0.1714 → R:R=2.500 TAM, ima ATR%≈1.73 makul → backtest matematiğiyle nokta-nokta uyuştu = PASS.
NEAR donchian SHORT (SL1.937 fiyat üstünde) tutarlı; TP+giriş beklenerek ikinci onay. test=canlı doğru.

## 🎯 SL YERLEŞİMİ / LİKİDİTE KOLU (2026-07-22, sl_placement_test) — RED

Kullanıcı sezgisi (SMC/likidite): "SL'lerimiz likidite havuzlarında oturup süpürülüyor olabilir;
SL'i havuzun ötesine koyup TP'yi bozmadan SL'leri azaltabilir miyiz?" TP FİYATI SABİT (entry±5×ATR),
%2.25 risk, donchian 7 coin, canlı-doğru. Bilimsel kontrol: düz geniş ATR stop da aynı işi yapıyorsa
"likidite" çerçevesi bir şey katmıyor demektir.

  baseline2ATR SL%50 PF1.51 $+1121 | wide2.5ATR SL%42 PF1.44 $+833 | wide3ATR SL%34 PF1.43 $+693
  swing10 SL%25 PF1.31 $+410 | swing20 SL%16 PF1.31 $+323

**SEZGİ KISMEN DOĞRU:** yapısal SL gerçekten süpürülmeyi azaltıyor — SL oranı %50→%16, WR %44→%53.
**AMA PARA KAYBETTİRİYOR:** $1121→$323, HER YIL kötü (2025 $287→$30). Neden: aynı riskte geniş SL =
çok daha küçük pozisyon → kazançlar küçülüyor, takas net negatif.
**KONTROL BAŞARISIZ:** swing(PF1.31) < düz geniş ATR(PF1.43) → "likidite" çerçevesi ekstra edge
KATMIYOR, sadece stop-genişliği etkisi. SMC likidite fikri bu sistemde ölçülebilir edge vermiyor.
**SONUÇ: 2×ATR optimal, dokunma.** SL'ler "düzeltilebilir" değil — süpürülme dar stopun bedeli ve
dar stop daha çok kazandırıyor. (Sahte-breakout öngörülemezliği + cooldown reddi ile tutarlı.)

## 🩸 SL YERLEŞİMİ / LİKİDİTE KOLU (2026-07-22, sl_placement_test) — sezgi DOĞRU ama net NEGATİF

Kullanıcı sezgisi (SMC/likidite): SL'ler bariz likidite havuzlarında (swing-low altı) süpürülüyor →
SL'i yapısal seviyenin ÖTESİNE koy, TP FİYATINI SABİT tut (entry±5×ATR), %2.25 risk sabit.
Bilimsel kontrol: düz geniş ATR stop (2.5/3×ATR) aynı işi yapıyorsa "likidite" çerçevesi katkısız.

  baseline2ATR: SL%50 WR44% PF1.51 $+1121  ← EN İYİ
  wide2.5ATR  : SL%42 WR47% PF1.44 $ +833
  wide3ATR    : SL%34 WR50% PF1.43 $ +693
  swing10     : SL%25 WR52% PF1.31 $ +410
  swing20     : SL%16 WR53% PF1.31 $ +323   (SL oranı 50%→16%!)

**SEZGİ DOĞRULANDI:** geniş/yapısal stop SL-avını GERÇEKTEN azaltıyor (SL%50→16, WR%44→53).
**AMA NET NEGATİF:** toplam $1121→$323, PF 1.51→1.31, HER YIL daha kötü, MONOTONİK bozulma.
NEDEN (korunum yasası): sabit %2.25 riskte geniş stop = küçük pozisyon = kazançta daha az $/işlem.
Kaçınılan SL'ler bunu telafi etmiyor. "TP'yi bozmadan SL'i azalt" MÜMKÜN ama parayı azaltıyor.
LİKİDİTE ÇERÇEVESİ KATKISIZ: swing10/20, benzer SL-azaltmasında 3ATR'den DAHA KÖTÜ → etki sadece
stop-genişliği, "likidite havuzu" bilgisi ek değer katmıyor. RED (baseline 2ATR optimal kalıyor).

## 🔍 4h MUM UYUMU DOĞRULANDI (test=canlı)
Canlı `get_candles(confirm_tf=4h)` NATIVE MEXC 4h çekiyor; backtest 1h→4h resample ediyor.
Kontrol: resample sınırları [0,4,8,12,16,20] UTC = MEXC native 4h sınırlarıyla BİREBİR → aynı mumlar.
(Canlıda ayrıca 4h tazelik kontrolü + _poll_once var → kapanmamış bara göre işlem açılmıyor.)

## 🧾 DÜRÜST KAPANIŞ TABLOSU + DENETİMSİZ-ÇALIŞMA GÜVENLİĞİ (2026-07-25)

Denetim bulgularının adversaryal doğrulaması (5/12 tamamlandı, kalanı oturum limitine takıldı):
**3 GERÇEK KUSUR bulundu ve DÜZELTİLDİ:**
1. MTF LOOKAHEAD (araçlarda): günün TAM kapanışı ffill ile gün-içi barlara → gelecek bilgisi.
   14 araçta canlı-birebir forma çevrildi. Ölçüm: lookahead PF1.51/+$1121 vs gerçek PF1.45/+$1037.
   AYRICA: canlı MTF kapısı 1017 sinyalin **0**'ını blokluyor = TAMAMEN ETKİSİZ (40-bar kanal
   kırılımı + EMA200 zaten fiyatı 20-gün EMA üstüne çıkarıyor → kapı gereksiz).
   → Ledger'ın "MTF +$42, PF1.49→1.53" kredisi GERÇEKLEŞMİYOR. Deploy zararsız (no-op), inanç yanlıştı.
2. FAIL-OPEN SLEEVE DEFAULT'LARI: ORB/SR/FVG/IFVG config'de True → .env'den anahtar düşerse
   sessizce açılır (ölçülen felaket: maxDD %20→%103). config.py'de 8 default False yapıldı.
   Canlıda zaten kapalılar (loglar: her coin tek sleeve) → davranış değişmedi, tehlike kalktı.
3. NOTIONAL TAVANI MODELLENMEMİŞ: risk.py boyutu min(risk%, cap×SL%) ile sınırlıyor →
   dar-stop'lu işlemler (özellikle squeeze) hedeften küçük. deployed_backtest artık modelliyor.

**DÜRÜST NİHAİ RAKAMLAR (occ+lookahead+tavan hepsi düzeltilmiş, MP=7, cap=1.0):**
  1421 işlem/3.2yıl, PF **1.44**, WR %43. Canlı boyutla toplam **+$1224** (düz modelin %84'ü).
  Gerçek ort risk %2.06 (hedef %2.25), işlemlerin %25'i tavana takılı.
  **maxDD %18.2** | aylık ort +%16.1 | en kötü ay −%20.9 | poz-ay %60.
  Yıl-yıl: 2023 +$286 (PF1.53) | 2024 +$389 (1.43) | 2025 +$379 (1.45) | 2026 +$171 (1.35).
  PF YILDAN YILA DÜŞÜYOR (1.53→1.35) = piyasa-geneli edge decay, tek coin suçu değil (health temiz).
  ICP/BNB deploy kararı düzeltilmiş veriyle de AYAKTA (her yıl pozitif). 11 coin hepsi sağlam.

**DENETİMSİZ ÇALIŞMA GÜVENLİĞİ (koddan doğrulandı):**
  ✅ Birincil koruma = giriş emrine iliştirilmiş pozisyon-seviyesi SL/TP → MEXC'te YAPIŞKAN, süresi
     DOLMAZ (exchange.py: "sticky, survives cancel_stop_orders"). 24h executeCycle SADECE acil
     yedek plan-emirleri için → 5 günlük donchian tutuşunda korumasız kalma riski YOK.
  ✅ has_attached_protection MUHAFAZAKÂR: belirsizlikte False döner → stop koyar (asla korumasız varsaymaz).
  ✅ Reconciliation loop 2 dakikada bir: dış kapanışları yakalar, kardeş stop'ları yeniden koyar.
  ✅ Günlük zarar kill-switch: gün başlangıcının −%35'inde halt + emergency_close_all, 2 dk'da bir
     kontrol (sadece yeni sinyalde değil — eski açık bulunmuştu, kapatılmış).
  ✅ Isolated margin: bir pozisyonun kaybı diğerlerine sıçramaz.
  ⚠ VPS systemd Restart=always buradan doğrulanamıyor (service dosyası VPS'te) — kullanıcı teyit etmeli.
  ⚠ 7 denetim bulgusu (exit yolu, max-hold, likidasyon guard, cooldown) HÂLÂ DOĞRULANMAMIŞ (limit).

## 🔬 NEGATİF AYLAR NEDEN NEGATİF (2026-07-25) — kesin cevap, 2 bağımsız analiz

**MEKANİZMA: negatif aylar = CHOP (testere/yatay) AYLARI.** Gerçek, tanımlanabilir bir durum
(aynı-ay çapraz-coin ADX ayrımı AUC 0.68, p=0.003 — karıştırılmış işlemlere karşı; etiketleme
artefaktı DEĞİL). Kimliği: düşük ADX + 4h barların büyük kısmı önceki-40 kanalın İÇİNDE sıkışmış.

**NASIL kaybediyoruz (önemli):** kayıplar BÜYÜMÜYOR, kazançlar AZALIYOR.
  kötü ay (16/40) vs iyi ay (24/40): WR %34.2 vs %47.7 | ort kazanç +1.56R vs +1.91R |
  **ort kayıp −0.94R vs −0.95R (AYNI)** | 31.2 vs 38.4 işlem/ay.
  → Tüm fark isabet oranı + küçülen kazançlar. Stop'lar sorun değil; TP'ye ulaşamamak sorun.

**KÜMELENME DEĞİL:** kayıplar aya yayılmış (3-gün penceresinde max kayıp 6.25 gözlenen vs 6.25
rastgele-null = fark yok). Ay-üçtebirlerinin %82'sinde yüksek kayıp oranı. Coinler arası günlük
korelasyon kötü aylarda +0.075, iyi aylarda +0.089 (yani kötü ayda DAHA AZ senkron). Aynı-gün
çoklu-SL kümeleri var ama SİMETRİK (hep-kazanç günleri de var) → mekanizma bu değil.

**ÖNGÖRÜLEMEZ (kanıtlı):** rejim ANTI-PERSISTENT — ADX ay-ay otokorelasyon −0.379, aylık PnL
otokorelasyon −0.345. Önceki-ay göstergelerinin hiçbiri anlamlı değil (FWER p=0.41). OOS AUC
0.52-0.69, işaret isabeti 0.48 (hiçbir şey yapmamak 0.56). In-sample, HİNDSIGHT ile bile en iyi
eşik kuralı eğitim PnL'ini iyileştiremiyor ($611 vs $614) — her kesim iyi ayları kötülerden çok siliyor.

**EKONOMİK ÖLDÜRÜCÜ ARGÜMAN (korelasyon tahmini gerektirmez):** iyi aylar ort +%31.9 (toplam
+$1455), kötü aylar ort sadece −%7.6 (toplam −$231). İyi ay kötü ayın **4.2 katı**. MÜKEMMEL bir
kâhin tüm 16 kötü ayı atlasa kazanç sadece **+$231 / 3.2 yıl (~$6/ay)**. Simülasyon: bir ay-kapısının
başabaş olması için ~AUC 0.90 gerekir. → Denemeye DEĞMEZ, doğruluk ne olursa olsun.

**20 KALDIRAÇ TEST EDİLDİ, HİÇBİRİ +$1222'yi GEÇMEDİ.** Kill-switch'ler en kötü ayı DAHA KÖTÜ
yapıyor (−%23..−%29 vs −%20.9) çünkü aylık PnL ortalamaya dönüyor. MAXPOS=5 yazı-tura ($1239 vs
$1222 = gürültü). Aynı-yön cap K=4 dolar-negatif ve yıl-yıl kırılgan.

**BİLİNMESİ GEREKEN (aksiyon değil):** yılda ~2.5 kez, 5+ pozisyon aynı UTC gününde stop oluyor,
equity'nin %11-13'ü tek günde gidiyor. Yapısal, öngörülemez ve simetrik (hep-kazanç günleri de
aynı sıklıkta). Filtrelenmez, BOYUTLANDIRMAYLA yönetilir.

**SONUÇ: negatif aylar breakout edge'inin kaçınılmaz maliyeti.** Aksiyon: YOK. Doğru çerçeve
"chop'u önceden bil" değil, "chop'ta daha az kaybet" (giriş/çıkış tasarımı) — ama o kol da
(filtreler, cooldown, stop yerleşimi, piramitleme) daha önce kanıtla elendi.

## 🎯 KISMİ TP (scale-out) — İLK GERÇEK ADAY (2026-07-25, partial_tp_test) — DEPLOY EDİLMEDİ

DOĞRU MEKANİZMAYI hedefleyen ilk test. Ay analizi göstermişti: kötü aylarda ort KAYIP değişmiyor
(−0.94R vs −0.95R), KAZANÇ küçülüyor (1.56R vs 1.91R) → sorun SL değil, TP'ye ulaşamamak.
Kısmi TP = trailing/BE'den FARKLI (o stop oynatır, elenmişti; bu gerçek kâr realize eder).

**Sabit riskte (%2.25) RED ama risk-ayarlı İYİ:**
  baseline    %2.25 → $1224, maxDD %18.2, $/DD 67.3
  p50@1R      %2.25 → $1034 (−%16, 3 yıl bozuk) AMA maxDD %12.5, PF 1.44→1.48, poz-ay %60→%78
**RİSKLE TELAFİ (tavan modellenmiş):**
  p50@1R %3.00 → $1293, DD %13.9, $/DD 93.1 (en verimli) ama 3 yıl bozuk (2025'e yığılmış)
  p50@1R %3.50 → $1430, DD %16.4, 2023 bozuk
  **p50@1R %4.00 → $1557 (+%27), DD %18.4 (≈baseline 18.2), HER YIL İYİ ✓**
     2023 $301(vs286) 2024 $473(vs389) 2025 $577(vs379) 2026 $207(vs171)

**DEPLOY EDİLMEDİ — 5 sebep (kullanıcı 1 ay uzakta):**
1. Yeni edge DEĞİL: kısmi TP volatiliteyi düşürüyor, boşluğu kaldıraçla dolduruyoruz (verimli
   paketleme). Meşru ama "piyasadan daha çok koparmak" değil.
2. 2023 kıl payı geçiyor (+%5); ağırlık 2025'te (+%52) → "her yıl" testini geçiyor ama RAHAT değil.
3. %4 riskte işlemlerin **%53'ü** notional tavanına takılı → artış eşitsiz (donchian'a çok, squeeze
   donuk), portföy dengesi kayıyor.
4. Pozisyon boyutu +%78 → gap/flash-crash kuyruk riski DOĞRUSAL artar; maxDD bunu ÖLÇMEZ.
5. **Canlıda kısmi TP YOK** → env değil, EXECUTION KATMANI KODU (reduce-only yarım kapatma, kalan
   stop yönetimi, kısmi doluş, 2dk mutabakata yeni durum). Netted modda ciddi iş + denetimsiz bir ay.

**DÖNÜNCE SIRA:** (a) kısmi TP'yi kodla + paper modda doğrula, (b) canlı-doğru test, (c) riski
KADEMELİ artır — hepsi kullanıcı bakarken. Şimdilik sistem doğrulanmış haliyle kalıyor.

## ⚠️ KISMİ TP DÜZELTMESİ (2026-07-25, partial_by_sleeve) — "ilk gerçek aday" ZAYIFLADI

Kullanıcı gözlemi ("2023 sadece +%5, çok dengesiz") doğru çıktı ve iki şeyi ortaya çıkardı:

**1. "2023 trend yılıydı" HİPOTEZİ ÇÜRÜTÜLDÜ.** Yıl karakteri ölçüldü (7 donchian coini, 4h barların
önceki-40 kanal İÇİNDE kalma payı + ort ADX): 2023 chop%92.8/ADX28.3 | 2024 %93.8/27.2 |
2025 %93.7/26.2 | 2026 %93.8/27.8 → **DÖRT YIL DA BİREBİR AYNI.** Rejim farkı YOK.
→ 2023'ün zayıf kalması rejimden değil, AÇIKLANAMAYAN GÜRÜLTÜ = kullanıcının sezdiği kırılganlık.

**2. KISMİ TP SABİT RİSKTE HER YERDE ZARARLI (risk %2.25 sabit, kaldıraç izole):**
  baseline $1224 (DD18.2) | sadece-donchian $1047 (−$178, DD14.7) | sadece-squeeze $1211 (−$13,
  DD17.6) | ikisi $1034 (−$191, DD12.5).
  Hipotezin yarısı doğru: hasar DONCHIAN'da (trend takipçisinin kazananı kırpılıyor, her yıl −$4..−$78).
  AMA squeeze fayda da sağlamıyor (sadece nötr) → "kısmi TP'yi squeeze'e uygula" kazanç kapısı YOK.

**SONUÇ: önceki +%27 tamamen KALDIRAÇTAN geliyordu.** Kısmi TP edge'in %16'sını yok edip (1224→1034)
drawdown'ı %31 düşürüyor (18.2→12.5); boşluk %78 kaldıraçla dolduruluyor. Matematiksel olarak geçerli
bir takas (riskin %31'i karşılığında getirinin %16'sı) ama EDGE İYİLEŞTİRMESİ DEĞİL — volatilite
paketleyip kaldıraca çevirmek. Ve dengesiz yıl dağılımı rejimle açıklanamıyor → kırılgan.
→ ADAYLIK ZAYIFLADI. Deploy yok (zaten yoktu). Dönünce bakılacaksa "kaldıraç kararı" olarak bakılmalı,
"yeni edge" olarak değil.

**BONUS BULGU (kullanıcının "bot duruma göre davranmalı" sorusuna):** yıllar arasında adapte olunacak
DURUM FARKI YOK (chop %92.8-93.8, ADX 26-28 bandında sabit). Ay içinde chop durumu gerçek (p=0.003)
ama ay-ölçeğinde rejim ÖNGÖRÜLEMEZ (kanıtlı). Piyasa hep aynı karakterde; değişen sonuçların dağılımı.

## 🔚 SL SORUSU MEKANİK OLARAK KAPANDI (2026-07-25, mfe_anatomy) — 1440 işlem

İlk kez sorulan soru: "SL olan işlem, stop'a gitmeden ÖNCE ne kadar lehimize gitti?" (MFE).
Öncekiler hep "girişte öngörebilir miyiz" idi (HAYIR, OOS AUC 0.509). Bu MEKANİK cevap.

**ÇIKIŞ EKONOMİSİ:** tp 366 (%25) ort +2.49R +$3435 | sl 742 (%52) ort −1.01R −$2913 |
maxhold 332 (%23) ort **+0.56R +$748, %77 kârlı**, ort MFE 1.54R, ort 33.9 bar.

**SL MFE DAĞILIMI (742 işlem):**
  TEMİZ KAYIP <0.25R : 228 (%30.7) −$899   ← hiç lehimize gitmedi
  erken dönüş 0.25-1R: 340 (%45.8) −$1325
  WHIPSAW 1-2R       : 147 (%19.8) −$588
  KIL PAYI >2R       :  27 (%3.6)  −$101
  → **SL'lerin %76.5'i 1R'ye BİLE ULAŞMADI.** Ort MFE 0.64R, medyan 0.49R.
  → SL'e ort 11.4 bar vs TP'ye 14.4 bar: başarısız breakout HEMEN belli oluyor.

**DÖRT HİPOTEZ BİRDEN ÖLDÜ:**
1. "Stop dar" ❌ — kazananların sadece %10.7'si stop'a yaklaşmış (<−0.75R), ort MAE −0.37R,
   %40'ı −0.25R'yi bile görmemiş. Stop rahat yerde. (Geniş-stop testi zaten para kaybettirmişti.)
2. "TP uzak" ❌ — kıl payı sadece %3.6 = $101. Yok denecek kadar az.
3. "Whipsaw yakalanabilir" ⚠️ — %19.8 ($588) GERÇEK ama YAKALANAMIYOR: kısmi TP tam bunu
   hedefliyordu, net −$191. Aritmetik doğruluyor: 147 whipsaw'dan +73R vs 366 TP'den −274R.
4. "Max-hold zarar" ❌ — TERSİ: +$748, %77 kârlı, katkı sağlıyor. Süreyi kısaltmak zarar verir.
   (Eski "45 bar marjinal" sweep'inin NEDENİ bu.)

**SONUÇ:** kayıpların dörtte üçü, girişte ayırt edilemeyen ve hemen sönen sahte kırılımlar =
breakout edge'inin kelime anlamıyla maliyeti. SL ARAŞTIRMA KOLU KAPANDI (spekülasyonla değil,
mekanik kanıtla). %52 SL oranına RAĞMEN PF 1.44 — kazananların 2.49R'si taşıyor.

## 🆕 YENİ SİSTEM AİLESİ #1: KESİTSEL MOMENTUM (2026-07-25, xsec_momentum) — RED

Mevcut kitabın tamamı (donchian/squeeze/BB + elenen NW/KAMA/grid/funding/ORB/FVG/IFVG/SR/Asia)
TEK COİNE bakan zaman-serisi sinyalleri. Kesitsel momentum yapısal olarak FARKLI: "hangi coinler
BİRBİRİNE göre güçlü". 22 coin, günlük, L∈{7,14,30} K∈{2,3,4} R∈{7,14} = 18 konfigürasyon.

**AGGREGATE'TE HARİKA GÖRÜNÜYOR (tuzak):** en iyiler 14/4/14 PF **2.14** ve 14/3/14 PF **2.10** —
bizim donchian'ımız 1.44. Kullanıcının aylardır istediği "PF 2.0" tam burada. Aggregate'e baksak
"bulduk" derdik.

**AMA 18 KONFİGÜRASYONUN 18'İ DE 2026'DA NEGATİF.** İstisnasız, parametreye duyarsız →
gürültü DEĞİL, sistematik çöküş. 2023 + / 2024 + / 2025 çoğu + / 2026 HEPSİ −.
Kesitsel momentum 2023-25 çalışmış, 2026'da ÖLMÜŞ (literatürde de kripto XS momentum zayıflaması
belgeleniyor; penceremiz tam o döneme denk).

**LONG-ONLY KONTROLÜ DOĞRULADI:** L14K3R7 long-only = PF 1.44 **+$451** — long/short'un en iyisinden
(+$260) DAHA FAZLA. Yani "edge"in önemli kısmı kesitsel seçicilik değil, KRİPTO BETASI = zaten
sahip olduğumuz şey, çeşitlendirici değil.

**KARAR: RED** (PF>1.2 + HER YIL pozitif barajını hiçbiri geçemiyor; en güncel yıl hepsinde negatif).
DERS: bugün üçüncü kez aggregate-güzel/yıl-yıl-ölü tuzağı (önce -MonTue PF1.67, sonra kısmi TP +%27,
şimdi XS momentum PF2.14). Yıl-yıl kontrolü olmasa üçü de deploy edilir, üçünden de zarar edilirdi.
SIRADAKİ AİLE: spread/pairs (piyasa-nötr, gerçek düşük-korelasyon adayı).

## 🔀 YENİ SİSTEM AİLESİ #2: PAIRS SPREAD (2026-07-25) — EDGE GERÇEK, DEPLOY EDİLEBİLİR HALİ YOK

**TAM EVREN (günlük barlar) — bugüne kadar hem OOS hem her-yıl geçen TEK şey:**
  z2.0/0.5/3.5: PF1.63 $+532 TRAIN+321 TEST+211 | 2023+179 2024+141 2025+82 2026+129 HER-YIL+
  z2.0/0.0/3.0: PF1.67 $+610 TRAIN+383 TEST+227 | her yıl +
  z2.5/0.5/4.0: PF1.40 $+241 TRAIN+137 TEST+104 | her yıl +
  (4h barlar BAŞARISIZ: üçü de TRAIN+/TEST− = overfit imzası → sadece günlük çalışıyor.)
  Metodoloji korumaları: çiftler SADECE 2023-24'ten seçildi, z rolling pencereden, z-stop var.

**ÇEŞİTLENDİRME TEZİ DOĞRULANDI (seansın en iyi sonucu):**
  Kitapla korelasyon **−0.362** (Spearman −0.28). Kitabın 15 KAYIP ayında pairs **+$399**,
  15 ayın **12'sinde pozitif**. Birleştirme: $1224 → **$1756 (+%43)**, maxDD $59 → $60 (AYNI).
  Teori tuttu: chop breakout'u öldürürken mean-reversion'ı besliyor. BB'de bulamadığımız
  tamamlayıcı akış BU.

**AMA ÇAKIŞMA ÖLDÜRÜYOR (netted: coin başına tek pozisyon):**
  8 çiftin 6'sı deploy coini kullanıyor (ETC/ETH, BTC/ETH, ADA/DOT, XLM/XRP, ADA/ALGO, ADA/ATOM).
  Serbest olan 2 çiftle (ATOM/DOT, ALGO/DOT): PF1.09 **+$22** = değersiz.

**SERBEST EVREN DENEMESİ (10 deploy-dışı coin, 45 çift, 9 kombinasyon) — BARAJA TAKILDI:**
  En iyi 8-çift z2.5: PF1.45 $+302 TEST+185 ama **2025 −$1** ve kârın **%62'si 2026'dan**.
  z2.5 config'i 4/6/8 çiftte tutarlı (olumlu işaret) AMA: (a) her-yıl barajı geçilmiyor,
  (b) tek yıla yığılma — bugün aynı gerekçeyle kısmi TP ve -MonTue reddedildi, kural esnetilemez,
  (c) İLK DENEME BAŞARISIZ OLDUKTAN SONRA aynı veriye 9 yeni kombinasyonla bakıldı → araştırmacı
  serbestlik derecesi birikti = yanlış-pozitif üreten mekanizmanın ta kendisi. **RED (şimdilik).**

**DÖNÜNCE TEK YAPISAL HİPOTEZ (tarama değil):** ETH'yi donchian'dan çıkarıp pairs'e açmak.
ETH donchian'da zayıf halka (PF1.39, 2026 −$7) ama İKİ güçlü çiftte geçiyor (BTC/ETH, ETC/ETH).
Takas net pozitif mi? Tek ve yapısal soru — TAZE GÖZLE ve yıl-yıl doğrulanarak bakılmalı.
