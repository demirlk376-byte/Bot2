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

**LONG-ONLY KONTROLÜ — İKİ AYRI SEBEPLE RED (yıl-yıl kırılımı ŞART, toplam yanıltıcı):**
  L14K3R7 long-only: PF1.44 +$451 maxDD**24.8%** | 2023+250 2024+292 2025**+33** 2026**−124**
  L30K3R7 long-only: PF1.13 +$141 maxDD**48.6%** | 2023+195 2024+208 2025**−58** 2026**−204**
(1) Toplam long/short'un en iyisini (+$260) geçiyor → "edge"in çoğu kesitsel seçicilik değil,
    KRİPTO BETASI = zaten sahip olduğumuz şey, çeşitlendirici değil.
(2) DAHA ÖNEMLİSİ: long-only DA 2026'da ölüyor (−$124/−$204), 2025 zaten sönük (+$33/−$58) →
    desen long/short ile BİREBİR AYNI. Ailenin TAMAMI (l/s + long-only) mevcut rejimde ölü;
    tek varyantın şanssızlığı değil, SİSTEMATİK. Ayrıca maxDD %24.8-48.6 vs bizim kitap %18.2 —
    iyi yıllarında bile daha riskli.
UYARI: bu satır ÖNCE sadece "PF1.44 +$451" olarak kaydedilmişti; bağlamdan kopunca çekici görünüp
yeniden açılmaya davetiye çıkarıyordu. DERS: ledger'a toplam yazılacaksa YIL-YIL da yazılacak.

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

## 🏛️ PROFESYONEL STANDART #1: ÇOKLU HORİZON (2026-07-25, horizon_sweep) — ENSEMBLE RED, AMA SİSTEM DOĞRULANDI

Web araştırması: çoklu-lookback ensemble managed-futures ENDÜSTRİ STANDARDI ("hiçbir tek horizon
tüm ortamları yakalayamaz; hız çeşitliliği zamanlama riskini dağıtır"; CFA Institute, TSMOM
literatürü). Biz TEK horizonda (kanal=40) çalışıyoruz → hem standart test hem ÖZ-DENETİM.

**ÖZ-DENETİM GEÇTİ:** vektörize donchian, kanal=40'ta **1017 işlem** = bilinen sonuçla BİREBİR.

**BULGU 1 — SİSTEM PARAMETRE-KIRILGAN DEĞİL (deploy için çok iyi haber):**
  ch20 PF1.30 $+919 DD13.3 | ch30 1.32 $+855 DD11.0 | **ch40 1.44 $+1003 DD8.6 (DEPLOY)** |
  ch60 1.30 $+610 DD16.2 | ch80 1.32 $+567 DD17.0 | ch120 1.39 $+546 DD14.8
  **ALTI HORİZONUN ALTISI DA HER YIL POZİTİF** → edge YAPISAL, parametre şansı değil.
  40 üç metrikte de en iyi AMA komşuları makul (30:1.32, 60:1.30) = eğri PÜRÜZSÜZ.
  Overfit spike olsaydı 30/60 çökerdi. Bu, "40 şanslı seçim mi?" sorusunun en iyi cevabı.

**BULGU 2 — ENSEMBLE FAYDASIZ (red):** horizonlar arası aylık korelasyon **0.76-0.96**
(komşular 0.90-0.96) → aynı şeyin kopyaları, literatürün vaat ettiği düşük-korelasyon YOK.
Tüm kombinasyonlar 40'ın altında: (20,40,80) $829 | (20,40,60,80) $775 | (30,60,120) $670 |
hepsi $750 — vs 40 tek başına **$1003**. En iyiyi zayıf+korele horizonlarla seyreltmek zarar.
NEDEN literatürle çelişiyor: CTA'lar 1-12 AY horizonu kullanıyor; bizim 20-120 bar (4h) = 3-20 GÜN,
hepsi literatürün "hızlı" ucunda → benzeşiyorlar. Gerçek çeşitlilik haftalık/aylık sinyal ister,
3.3 yıllık veride o örneklem yok.
NOT: tablodaki ensemble DD'si $ , tek-horizon DD'si % — farklı birim, karar toplam$ + yıl-yıl'dan.

**VOLATİLİTE HEDEFLEME (2. standart):** kısmen ZATEN VAR — boyut = risk/(giriş×SL%) ve SL ∝ ATR,
yani pozisyon volatiliteyle ters orantılı. Eksik tarafı bugün ölçülmüştü: notional tavanı
işlemlerin %25'inde bunu bozuyor (squeeze'de %72).

## ⛔ ETH TAKASI + ÇAKIŞMA ENGELİ (2026-07-25, eth_swap_test) — PAIRS YOLU KAPANDI

**SORU:** ETH'yi donchian'dan çıkarıp BTC/ETH + ETC/ETH çiftlerini açmak net pozitif mi?
RİSK-NÖTR kuruldu (pairs ham haliyle sermayenin ~tamamını nominal kullanıyor, kitap %2.25 risk →
pairs, çıkarılan ETH-donchian'ın aylık std'sine eşitlendi; ölçek ×1.018).

  baseline (d7+sqz) $+1224 en kötü ay −$40 maxDD $59 | 2023+286 2024+389 2025+379 2026+171
  VARIANT (d6+pairs) $+1173 en kötü ay −$69 maxDD $69 | 2023+314 2024+407 2025**+252** 2026+200
  **fark −$52, 2025 BOZULDU → RED. ETH donchian'da kalıyor.**

**ASIL BULGU — pairs edge'i ETH çiftlerinde DEĞİL:** BTC/ETH+ETC/ETH tek başına sadece **+$36**
(2025 **−$68**), oysa 8-çiftlik tam set +$532/her-yıl+. Kalan ~$496 çakışan DİĞER çiftlerde:
ADA/DOT, XLM/XRP, ADA/ALGO, ADA/ATOM. Ve **ADA bizim EN İYİ donchian coinimiz** (PF1.78 +$226,
ETH'nin ~2 katı), XLM/XRP sağlam squeeze coinleri (+$138/+$138).
→ **Pairs edge'i tam da vazgeçemeyeceğimiz coinlerde yaşıyor.**

**KOLTUK DİNAMİĞİ (öngörüldü, doğrulandı):** ETH'yi çıkarmak katkısını silmiyor, boşalan koltuklar
diğer coinlere gidiyor → donchian6 ≈ $1136, yani ETH'nin maliyeti $129 değil **$88**. 2026'da
d6 daha İYİ (+$185 vs +$171) ama 2025 çöküyor.

**ÇAKIŞMA ENGELİ KALDIRILABİLİR Mİ?** ccxt mexc `setPositionMode` DESTEKLİYOR (hedge mode mümkün).
AMA: (a) sorunu ancak YARI çözer — hedge long+short'u ayırır, aynı yöndeki iki sleeve yine tek
pozisyona netlenir, pairs bacakları ~yarı zaman donchian ile aynı yönde; (b) asıl bedel GÜVENLİK:
tek güvenilir korumamız pozisyona iliştirilmiş yapışkan SL/TP ve o pozisyon başına TEK tane —
ikinci sleeve birincinin stop'unu EZER (execution.py:388 gerekçesi). Hedge mode = stop yerleştirme
+ 2dk mutabakat + kısmi kapatma mantığını baştan yazmak, sistemin en güvenlik-kritik parçası.

**SONUÇ: pairs deploy yolu hedge mode olmadan KAPALI.** Üç seçenek de elendi: (1) serbest-evren
çiftleri zayıf/2026'ya yığılmış, (2) ETH takası −$52, (3) ADA/XLM/XRP feda etmek ETH'den çok daha
pahalı (test gereksiz). Pairs'in çeşitlendirme değeri GERÇEK (korr −0.36) ama erişilemiyor.

## 🔄 BREAKOUT FADE (2026-07-25, fade_test) — MEKANİZMA GERÇEK, KÂR YOK → RED

Hipotez kendi bulgularımızdan: breakout'ların %76.5'i 1R'ye ulaşmadan sönüyor + kötü aylar chop.
→ "kanal kırıldı AMA ADX düşük" durumunda FADE et. 10 SERBEST coin (çakışma yok, hedge mode YOK,
tek bacak = mevcut altyapıyla uyumlu → deploy edilebilirliği en yüksek aday).

**MONOTONLUK TESTİ GEÇTİ (mekanizma gerçek):** ADX<15 → PF1.00-1.13 (+$6..+$60) | ADX<20 →
PF0.89-0.95 (−$67..−$145) | ADX<25 → PF0.92-0.98 (−$61..−$191). Eşik genişledikçe (trendli
kırılımlar karışınca) fade KÖTÜLEŞİYOR = "trendsiz rejimde ortalamaya dönüş" mekanizması DOĞRU.

**TERS KORELASYON DA GERÇEK:** kitapla korr **−0.22 .. −0.50**. ADX<25 rr2.5 kitabın kayıp
aylarında **+$416** (15 ayın 10'unda pozitif).

**AMA KÂR YOK → RED:** hiçbir konfigürasyon HER-YIL testini geçmiyor (en iyi ADX<15 rr2.5 bile
2023 −$10, 2025 −$12), en iyi toplam 3.3 yılda +$60, birleştirme kazancı en iyi durumda
+$59/3.3yıl ≈ **yılda $18**. Çoğu varyant zaten zararda.

## 🧭 ÇEŞİTLENDİRİCİ ARAMASI KAPANDI — SINIR TESPİTİ
İki ters-korelasyonlu akış bulundu, ikisi de kullanılamıyor ama FARKLI sebeplerden:
  pairs spread : korr −0.36 | KÂRLI (+$532, her yıl+) | ERİŞİLEMEZ (çakışma: ADA/XLM/XRP)
  breakout fade: korr −0.22..−0.50 | KÂRSIZ | ERİŞİLEBİLİR (serbest coinler)
Kârlı olan erişilemiyor, erişilebilir olan kârlı değil. TESADÜF DEĞİL, ekonomik olarak anlamlı:
kripto TREND-AĞIRLIKLI bir varlık sınıfı → ters yönde kazanmak ya piyasa-nötr yapı ister (pairs,
altyapı/hedge mode) ya da yönlü fade (kripto trendli olduğu için kaybettirir).
SONUÇ: bu 22-coin evreninde, bu veri penceresinde, mevcut kitaba ERİŞİLEBİLİR çeşitlendirici YOK.
Bu bir başarısızlık değil, SINIR TESPİTİ — olmayan şeyi aramaya devam etmekten iyidir.

## 🔬 PAIRS, DOĞRU METODOLOJİYLE (2026-07-25, pairs_coint) — SERBEST EVREN KESİN RED

Kullanıcı "sorunu yarı değil TAMAMEN çöz" dedi → iki metodolojik hatamı düzeltip yeniden test:
 1) Çift seçimi KORELASYONLA yapılmıştı → KOİNTEGRASYON olmalı (korele çiftler kalıcı ayrışır,
    kointegre çiftler yapısı gereği döner).
 2) log(A/B) = 1:1 hedge oranı VARSAYIMI → OLS β ile spread = log(A) − β·log(B) olmalı.
scipy yok → Engle-Granger elle: OLS β + AR(1) half-life (2-30 gün bandı) + kalıntı stabilitesi,
SEÇİM SADECE 2023-24'ten.

**SONUÇ: 6 konfigürasyonun 6'sında da 2026 NEGATİF, TRAIN+$151..302 / TEST +$0..−$61.**
  4 çift: z2.0/0.5/3.5 PF1.49 TEST+0 | z2.0/0.0/3.0 PF1.48 TEST−61 | z2.5/0.5/4.0 PF1.72 TEST+11
  5 çift: PF1.20-1.36, TEST −2..−35, hepsi 2026 negatif
Seçilen 5 çiftin 4'ünde ETC var = tek coine bağımlılık, kendi başına red sebebi.
→ Sorun METODOLOJİDE DEĞİLDİ; serbest evrende edge GERÇEKTEN YOK. Bu, önceki bulguyu GÜÇLENDİRİR:
tam evren pairs'i (ADA/XLM/XRP/ETH dahil) her yıl+ idi → edge O SPESİFİK COİNLERDE, artefakt değil.

## ✅ TAM ÇÖZÜM TESPİT EDİLDİ: ALT-HESAP (sermaye meselesi, kod meselesi değil)
Çakışma "yarı" değil TAMAMEN çözülebilir: pairs'i AYRI MEXC ALT-HESABINDA ayrı API anahtarıyla
çalıştır → ayrı pozisyon defteri → ana hesap ADA'da donchian long tutarken alt-hesap ADA'da pairs
short tutabilir, İKİSİ DE kendi yapışkan SL/TP'sini korur, ezme YOK.
**KRİTİK: bu, zayıf serbest-evren versiyonunu değil GERÇEK olanı açar** — 8 çiftlik tam set
(+$532, HER YIL+, kitapla korr −0.36, kitabın 15 kayıp ayının 12'sinde pozitif).
**Hedge mode'dan ÇOK DAHA GÜVENLİ:** mevcut botun execution koduna SIFIR dokunuş — stop yerleştirme,
2dk mutabakat, kısmi kapatma hiç değişmiyor. Sadece ikinci bot örneği + ayrı anahtar.
**TEK ENGEL SERMAYE:** pairs 2 bacaklı (işlem başına 2 emir); alt-hesabın min-notional üstünde
çalışması için ~$300-400 gerekir. $188 + ayda $150 → **2-3 ay sonra eşik geçilir.**
→ "Çözemeyiz" DEĞİL: çözüm net, güvenli, bilinen — sadece henüz sermayesi yok. Sermaye gelince
sıra: (a) alt-hesap aç, (b) pairs botunu paper modda doğrula, (c) küçük sermayeyle canlıya al.

## 🔭 SAHTE KIRILIM — SON TEST EDİLMEMİŞ AÇI: POZİSYONLANMA (2026-07-25)

**KÖR NOKTA TESPİTİ:** bugüne kadar sahte kırılım için denenen TÜM özellikler (adx, atr%, hacim,
ATR-genişleme, momentum, kanal-aşımı, mum-içi kapanış, ters fitil, BTC hizası, saat, gün, ema
mesafeleri — 13 özellikli çok-değişkenli model dahil, OOS AUC 0.509) AYNI KAYNAKTAN: o coinin
OHLCV'si. Yani fiyatın NE YAPTIĞINA bakıyorlar, KİMİN yaptığına DEĞİL. Profesyonellerin kırılım
doğrulaması için kullandığı asıl bilgi ikincisi (emir defteri/akış) — bizde yok, geçmişe dönük alınamaz.

**OPEN INTEREST = en doğrudan elde edilebilir vekil AMA BACKTEST EDİLEMEZ:**
  ccxt-MEXC `fetchOpenInterest: False`, `fetchOpenInterestHistory: False` (doğrulandı).
  Ayrıca HİÇBİR borsa çok-yıllık geçmiş OI vermiyor (Binance 30 gün, MEXC yok).
  → OI ancak İLERİYE DÖNÜK toplanabilir. Mekanizma: kırılım+artan OI = yeni para = gerçek;
    kırılım+düşen OI = pozisyon kapanışı (squeeze/stop avı) = sahte.

**FUNDING = OI'nın test edilebilir vekili (fetchFundingRateHistory: True):**
  Hipotez (kriptoya özgü, genel TA lore'u DEĞİL): yukarı kırılım + YÜKSEK POZİTİF funding =
  long'lar kalabalık ve ödüyor → kalabalığa girmek → SAHTE. Negatif funding + yukarı kırılım =
  short'lar ödüyor → squeeze yakıtı → GERÇEK. Aşağı kırılımda simetrik.
  NOT: funding bir STRATEJİ olarak test edilip reddedilmişti (funding_bt); FİLTRE olarak HİÇ denenmedi.
  ARAÇLAR HAZIR: fetch_funding.py (VPS'te çalışır, geçmişi CSV'ye) + funding_filter_test.py
  (filtre ÜRETİMDE = canlı-doğru, 6 mod/eşik, yıl-yıl). Veri yoksa uyarıp çıkıyor.
  Container MEXC'e erişemiyor → veri VPS'ten gelmeli (OHLCV cache'iyle aynı iş akışı).

**BU SON TEST EDİLEBİLİR FİKİR.** Geçerse: pozisyonlanma sinyali gerçek. Geçmezse: sahte kırılım,
ELİMİZDEKİ HİÇBİR VERİYLE öngörülemez — kesin kapanış (ve tek kalan yol ileriye dönük OI toplamak).

---
# 📌 DÖNÜŞ NOTU (2026-07-25 sonu) — bir aylık aradan sonra buradan devam

## CANLI DURUM (dokunma, çalışıyor)
donchian 7 (SOL,ETH,ADA,NEAR,BCH,ICP,BNB) + squeeze 4 (XRP,DOGE,TRX,XLM) + BB(LTC hafta sonu)
RISK_SCALE=1.125 (%2.25/işlem) | MAX_POSITIONS=7 | 10x isolated | DONCHIAN_RR=2.5 | DONCHIAN_MTF=true
systemd: Restart=always + enabled (doğrulandı). Koruma: pozisyona iliştirilmiş YAPIŞKAN SL/TP
(süresi dolmaz; 24h plan emirleri sadece acil yedek). Günlük −%35 kill-switch, 2dk'da bir kontrol.

## DÜRÜST BEKLENTİ (tüm düzeltmeler sonrası)
PF 1.44, WR %43, 1421 işlem/3.2yıl. Canlı boyutla +$1224, GERÇEK maxDD %18.2, en kötü ay −%20.9.
Yıl-yıl hep pozitif AMA PF düşüyor (1.53→1.35 = piyasa geneli edge decay, coin suçu değil).
İleriye: backtest'in ALTI bekle. Gerçekçi ~%5-10/ay, arada −%15-20 aylar. $188'de bu ~$10-20/ay.
NOT: DONCHIAN_MTF canlıda ETKİSİZ (1017 sinyalin 0'ını blokluyor) — zararsız ama "+$42" kredisi SAHTE.

## SIRADAKİ 3 İŞ (öncelik sırasıyla)
1. **CANLI DOĞRULAMA (en değerli):** ~30-40 işlem birikti. `sl_audit` ile DB'den çek, backtest
   beklentisiyle karşılaştır. WR/PF tutuyor mu? Slippage var mı? Bu tek veri, buradaki 14 testin
   toplamından fazlasını söyler — overfit edilemeyen TEK şey o.
2. **FUNDING FİLTRESİ (son test edilebilir fikir):** VPS'te
   `cd /opt/bot2 && python3 fetch_funding.py && git add data/*_funding.csv && git commit -m funding && git push`
   sonra `git pull && py funding_filter_test.py local`. Geçerse ilk kez OHLCV dışına çıkarız;
   geçmezse sahte kırılım kesin olarak öngörülemez (ve tek yol ileriye dönük OI toplamak).
3. **PAIRS ALT-HESAP (sermaye ~$400-500'e ulaşınca):** çakışmayı TAMAMEN çözer, GERÇEK 8-çiftlik
   seti açar (+$532, her yıl+, korr −0.36). Mevcut bota SIFIR dokunuş. Sıra: alt-hesap aç →
   paper doğrula → küçük sermayeyle canlı.

## DOKUNMA (kanıtla elenmiş, tekrar açma)
SL filtreleri · gün-içi · literatür filtreleri (hacim/ATR/vol-taban) · cooldown · stop yerleşimi
(geniş+yapısal/likidite) · piramitleme · kısmi TP · rejim tahmini · BB genişleme · kesitsel momentum
(l/s VE long-only) · horizon ensemble · pairs serbest-evren (korelasyon VE kointegrasyon ile) ·
breakout fade · ETH takası. Hepsi yıl-yıl kontrolünde öldü; detaylar yukarıda.

## KURAL (bugün 4 yanlış pozitif yakalattı)
Aggregate metrik YANILTIR. -MonTue PF1.67, kısmi TP +%27, XS momentum PF2.14, long-only +$451 —
dördü de toplamda harika, dördü de yıl-yıl ölü. **HER YIL pozitif + TEST penceresi pozitif** barajı
olmadan hiçbir şey deploy edilmez. Ve ledger'a toplam yazılıyorsa YIL-YIL da yazılır.

## 🔒 FUNDING FİLTRESİ TEST EDİLDİ (2026-07-27, VPS'te koşturuldu) — RED, SAHTE KIRILIM KOLU KESİN KAPANDI

VERİ SINIRI: MEXC funding endpoint'i `since`'i yok sayıp SON 1000 kaydı döndürüyor →
sadece **2025-08-28 → 2026-07-27 (~11 ay)**. 2023-24 satırları tüm varyantlarda BİREBİR aynı
(+287/+394) çünkü o dönemde funding NaN → filtre devreye girmiyor. Gerçek test sadece 2025-08 sonrası.

**SONUÇ — 6 varyantın 6'sı da baseline'ın ALTINDA:**
  baseline           PF1.45 **+$1270** | 2025+392 2026+197
  skip_crowded 1e-4  PF1.45  +$1219  | 2025+402 2026**+136**  (2026 bozuldu)
  skip_crowded 3e-4  PF1.45  +$1246  | 2025+391 2026+173      (ikisi de bozuldu)
  skip_crowded 5e-4  PF1.45  +$1268  | 2025+390 2026+197      (neredeyse hiç filtrelemiyor)
  only_fuel    1e-4  PF1.43  +$895   | 2025+208 2026**+6**    (yıkım)
  only_fuel    3e-4  PF1.44  +$889   | 2025+212 2026**−4**    (yıkım)
En sıkı eşik 2025'i +10 iyileştirip 2026'yı −61 bozdu → sinyal DEĞİL, gürültü.

## ⛔ SAHTE KIRILIM: ERİŞİLEBİLİR TÜM VERİ KAYNAKLARI TÜKENDİ
  OHLCV özellikleri (13, çok-değişkenli, dürüst OOS) → AUC **0.509** (yazı tura)
  hacim / ATR-genişleme / volatilite-tabanı        → hepsi toplamı düşürdü
  zaman-takvim (gün, saat)                          → 2026'da tersine döndü
  yapı (kanal aşımı, ters fitil, mum-içi kapanış)   → ayrışma yok (<0.4σ)
  **pozisyonlanma (funding)**                       → **hiçbir eşikte işe yaramadı**
Geriye SADECE open interest kalıyor → BACKTEST EDİLEMEZ (hiçbir borsa çok-yıllık geçmiş OI vermiyor;
ccxt-MEXC hiç desteklemiyor). Tek yol: bot bugünden itibaren OI kaydetsin, 6-12 ay sonra test edilsin.

**NİHAİ CEVAP:** sahte kırılım, elimizdeki HİÇBİR veriyle giriş anında öngörülemez. Bu bir eksiklik
değil, edge'in ÖN KOŞULU: ayırt edilebilseydi herkes filtreler, edge kalmazdı. %52 SL oranı,
2.49R'lik kazananların bedeli — ayrı bir sorun değil, aynı madalyonun diğer yüzü.

## ✅ RETLERİN YENİDEN DOĞRULANMASI (2026-07-27) — "gerçekten mi elendi?" (kullanıcı denetimi)

SORUN: MTF lookahead 14 araçta düzeltildi AMA bazı retler düzeltmeden ÖNCE, kirli araçlarla
verilmişti. Mantık yürütmek yerine (bugün mantık yürütmek yerine ölçtüğümüz için 2 bug yakalandı)
dördü de düzeltilmiş araçlarla YENİDEN koşuldu:

  COOLDOWN      : baseline +$1451 | 6 varyant $1060-$1302, hepsi çoklu yıl bozuyor → RET GEÇERLİ
  PİRAMİTLEME   : taban PF1.45 | add+0.5ATR PF**1.38** (eski 1.42), +1.0 PF1.24, +1.5 PF1.10
                  (2025−5, 2026−21) → add PF < taban PF, RET GEÇERLİ (marj GENİŞLEDİ)
  STOP YERLEŞİMİ: baseline2ATR PF1.45 +$1037 | wide2.5 $760, wide3 $650, swing10 $356, swing20 $280
                  monotonik bozulma aynı, her yılda baseline üstün → RET GEÇERLİ
  SAHTE-BREAKOUT ML: OOS AUC **0.502** (eski 0.509), in-sample 0.563 → klasik overfit imzası,
                  13 özelliğin hepsi ≤0.10σ → RET GEÇERLİ (DAHA KESİN)

**HİÇBİRİ YÖN DEĞİŞTİRMEDİ.** Sebep: lookahead hem baseline'a hem varyanta EŞİT uygulanıyordu =
ortak-mod hata → mutlak rakamları şişiriyordu, göreli sıralamayı bozmuyordu. İkisinde marj GENİŞLEDİ.
YAN DOĞRULAMA: ML çıktısında mtf_aligned artık kazanan/kaybeden ikisinde de 1.000 → MTF'nin canlıda
etkisiz olduğu BAĞIMSIZ bir yoldan teyit edildi.

## 🌍 FARKLI VARLIK SINIFLARI — doğru yön, şu an ERİŞİLEMEZ
Profesyonel CTA'lar (AQR/Man AHL/Winton) 80-150 piyasada çalışıyor ve kazanma oranları %38-48 —
BİZİMKİ %43, yani AYNI. Sahte kırılımı bizden iyi ayırt etmiyorlar; ilişkisiz bahis sayısıyla
sönümlüyorlar. Ama bize bugün uygulanabilir DEĞİL: (1) veri yok (sadece 22 coin kripto cache),
(2) MEXC kripto-only → petrol/tahvil için FARKLI BROKER + execution katmanı yeniden yazımı,
(3) vadeli kontrat nominal değerleri $188 hesabın çok üstünde. Sıralama: pairs alt-hesabı
(~$400-500, 2-3 ay) → daha çok kripto coini (yapıldı) → varlık sınıfı çeşitlendirmesi (uzak gelecek).

## 📅 KAYAN 12-AYLIK PENCERELER (2026-07-27, rolling_year) — "kötü yıl ne kadar kötü?"

Takvim yılı sorusu ölçülemez (4 yılın 4'ü de pozitif, 2026 kısmi) → 29 KAYAN 12-aylık pencere.

**29 PENCERENİN HİÇBİRİ NEGATİF DEĞİL.** en kötü **+$316** (2024-09→2025-08) | en iyi +$535 |
medyan +$392 | ortalama +$400 (taban $190).

**EN KÖTÜ YILIN İÇİ (asıl öğretici):** +43 −8 +97 +22 −27 +131 −31 +51 −1 −18 +80 −22
  → 12 ayın **6'sı negatif** AMA pozitif toplam **+$425** vs negatif **−$109**.
  Dayanıklılık isabet oranından DEĞİL, ASİMETRİDEN: kayıp aylar küçük (ort −$18), kazanç ayları
  büyük (ort +$71). Yarısı kayıp olan bir yıl bile rahat pozitif kapanıyor.

**ÖZ-ELEŞTİRİ:** bu veri, benim kullanıcıya verdiğim "−$645 kötü yıl" senaryosundan ÇOK daha
iyimser. Backtest'in EN KÖTÜ yılı bile +%166 (taban), benim tahminim %36-60/yıl = verinin ~1/4'ü.
Kesinti gerekçeleri GERÇEK: (a) parametreler bu veriden seçildi (rr2.5 sweep, coinler "her yıl+"
filtresi, ICP/BNB aynı) = seçim yanlılığı, (b) PF ölçülebilir soğuma 1.53→1.35, (c) slippage/
funding/küçük-hesap sürtünmesi modellenmemiş, (d) 29 pencere ÖRTÜŞÜYOR → bağımsız gözlem sayısı
~3, 29 değil. AMA %75 kesinti agresif olabilir; dürüst aralık: backtest medyanı +%206/yıl,
tahminim +%36-60/yıl, gerçek muhtemelen ARADA (bana daha yakın). Tutucu duruş bilinçli tercih:
hayal kırıklığı sürpriz kazançtan pahalı. Kullanıcıya her iki çıpa da açıkça verildi.

## ✅ LİKİDASYON BANDI DOĞRULANDI (2026-07-27, liq_check) — mekanizma gerçek, ETKİ SIFIR

Denetimin doğrulanmamış bulgusu: "3.6% of donchian trades place the stop beyond the 10x-isolated
liquidation band". 2571 donchian işleminde ölçüldü:
  %10 bandı: 93 işlem (%3.6) SL bandın ÖTESİNDE → **iddia TAM DOĞRU**
  bunların 68'i (%73) likidasyon seviyesine DEĞMİŞ
  o 68'den SADECE **1 tanesi** sonra kazanmış (+$1); 67'si zaten kaybediyordu (−$277)
  likidasyon senaryosu −$249 vs gerçek −$276 → **+$27 DAHA İYİ**
(%9 bandı: 168 işlem/%6.5, +$40 daha iyi | %9.5: 119/%4.6, +$34 daha iyi)

NEDEN ZARARSIZ: (a) izole marjda geniş stop = küçük nominal = küçük marj → likidasyon kaybı
(%~1.9) hedeflenenden (%2.25) AZ; (b) 2×ATR sistemde %10 aleyhine giden işlem zaten ölmüş,
68'de 1 toparlanıyor. Bot bu kontrolü yapmıyor ama YAPMASINA GEREK YOK.
DERS: denetim mekanizmayı doğru tespit etmişti, ETKİ ANALİZİNİ atlamıştı. "Kod X yapıyor" ile
"X şu kadara mal oluyor" ayrı sorular — ikincisi ölçülmeden severity verilemez.

## 👁 BOTUN GÖREMEDİĞİ 3 ŞEY (kullanıcı sorusu: "senin görüp botun göremediği")
1. **YÖN YOĞUNLAŞMASI:** şu an iki canlı pozisyon da SHORT + ikisi de alt-coin (ADA, NEAR).
   Bot her sinyali BAĞIMSIZ değerlendiriyor, portföy yön dengesini hiç görmüyor. Ölçülen risk:
   yılda ~2.5 kez 5+ pozisyon aynı gün stop = equity'nin %11-13'ü. Hata değil, yapısal.
2. **KENDİ SLIPPAGE'INI GÖREMİYOR:** SL/TP çıkışları DB'ye TEORİK seviyeden yazılıyor (gerçek
   doluştan değil) → botun defteri backtest'le TANIM GEREĞİ uyuşur, gerçek doluşlar kötü olsa bile.
   Bir ay sonra "canlı backtest'i tutuyor mu" bakarken YANILTICI. Çözüm: sl_audit'i MEXC gerçek
   emir geçmişiyle karşılaştırmak (döndüğünde).
3. **PF SOĞUMASINI GÖREMİYOR:** 1.53→1.43→1.45→1.35. Bot kendi geçmiş performansını izlemiyor.
   İZLENECEK TEK ŞEY BU: canlı PF 1.2'nin altına inip orada kalırsa "kötü dönem" değil EDGE ÖLÜMÜ.

## ⛔ PF KILL-SWITCH (2026-07-27, pf_killswitch) — 27 FORMUN 27'Sİ RED + TASARIM KUSURU BULUNDU

Kör nokta: bot kendi PF soğumasını (1.53→1.43→1.45→1.35) göremiyor. 3 farklı MEKANİZMA ×
3 pencere (30/50/100 kapanmış işlem) × 3 eşik (1.0/1.1/1.2). Walk-forward: kayan PF SADECE
giriş anından ÖNCE KAPANMIŞ işlemlerden (lookahead yok).

**SONUÇ: 27 formun 27'si de baseline'ın ($1224) ALTINDA.** En iyi derisk_N100_T1.0 = $1126 (−$98).

**YENİ BULGU — `halt` FORMLARI KİLİTLENİYOR (yapısal kusur):** halt_N30_T1.0 sadece 98 işlem,
yıl-yıl kırılımında SADECE 2023 var → 2023'te durmuş, BİR DAHA AÇILMAMIŞ. Sebep: durunca yeni işlem
KAPANMIYOR → kayan PF DONUYOR → eşiğin altında kalıyor → sonsuza kadar kapalı = TEK YÖNLÜ KAPI.
Ayar sorunu değil, mekanizmanın kendi kusuru. Gerçek bir botta SESSİZCE olurdu.
`derisk` kilitlenmiyor (yarım boyla devam → PF güncellenir, 1421 işlem korunur) ama yine kaybettiriyor,
3-4 yıl bozuyor — bilinen tuzak DOĞRULANDI: aylık PnL ortalamaya döner (−0.345), kill-switch tam
dipte küçültür, toparlanmayı küçük pozisyonla karşılar.

**ARAÇ KUSURU (dürüstlük):** bu tablodaki maxDD/enKötüAy sütunları güvenilmez — baseline −39.7%
gösteriyor ama deployed_backtest AYNI işlem setinde −20.9% veriyor; fark çözülmedi. Toplam ($1224)
ve yıl-yıl BİREBİR tutuyor ve karar onlara dayanıyor, ama sütunlar raporlanırken belirtildi.

**SONUÇ: PF izleme OTOMATİKLEŞTİRİLEMEZ.** Kill-switch koruma aracı değil. Doğru kullanım: PF'i
RAPORLA, kararı İNSAN versin. Bot geçici çukurla gerçek edge-ölümünü ayırt edemiyor; "PF 1.2 altına
indi ve 3 ay orada kaldı" bir insan kararıdır, bot refleksi değil.

## 💸 FUNDING MALİYETİ ÖLÇÜLDÜ (2026-07-27, funding_cost, VPS'te) — GERÇEK ama KÜÇÜK

Kör nokta: backtest sadece 2×1bp komisyon alıyor; donchian 5 GÜNE kadar tutuyor, funding 8 saatte
bir ödeniyor. Hiç ölçülmemişti. Pencere: 380 işlem (%26), 2025-08→2026-07 (funding verisi kadar).

  donchian 290 işlem: ort tutuş **68 saat**, ort **8.4 funding bacağı**, R etkisi ort −0.0058R
    LONG n=115 ort −0.0044R | SHORT n=175 ort −0.0067R
  squeeze  90 işlem: ort tutuş 20 saat, 2.6 bacak, ort −0.0084R
  **PENCERE ETKİSİ: −$9.02 = PnL'in −%2.2'si** ($408.31→$399.29, PF 1.535→1.520)
  2025 −$1.18 | 2026 −$7.84

**HEM LONG HEM SHORT KAYBEDİYOR** — tesadüf değil: breakout takipçisi kalabalığın ZATEN ittiği yöne
giriyor → her seferinde kalabalık tarafa katılıp funding ÖDÜYOR. Mekanik olarak tutarlı.
→ Backtest bu eksende ~%2 FAZLA İYİMSER. Küçük ama gerçek ve HEP ALEYHTE. Düzeltilemez (davranış
değişikliği değil, MUHASEBE körlüğü) — sadece beklentiden %2 düşülür.

## 🧠 İLKE: "KÖR NOKTAYI DÜZELTMEK" NEDEN GENELDE PARA KAYBETTİRİR (kullanıcı sorusu)
1. "Bot görmüyor" ≠ "görse daha iyi olurdu". Bilginin değeri kararı KÂRLI değiştirmesine bağlı.
   5 pozisyonun da short olması hata değil, SİNYALİN KENDİSİ (5 coin birden kırılıyorsa kripto
   düşüyordur). Limit = edge'in en güçlü anında işlem reddetmek.
2. PF'e tepki TERSİNE çalışıyor: aylık PnL ortalamaya döner (−0.345) → "PF düştü" zayıf bir ALIŞ
   sinyali, satış değil. Küçülmek = dipte küçülüp toparlanmayı kaçırmak.
3. ENTEGRASYON SORUNU DEĞİL — özellikle test edildi: PF için 3 mekanizma×3 pencere×3 eşik=27 form,
   yön için 4 limit. Entegrasyon sorunu olsaydı EN AZ BİR form çalışırdı. 27/27 başarısızlık
   fikrin yanlış olduğunu söyler, kodun değil.
4. EN DERİN SEBEP: her filtre kazananı da siler. Kâr için ORANTISIZ çok kaybeden elemeli; ama
   kazanan/kaybeden girişte ayrılamıyor (OOS AUC 0.502) → filtre ikisini ORANTILI eler → elde aynı
   sistemin KÜÇÜLMÜŞ KOPYASI kalır.
5. AMA MEKANİK HATALAR DÜZELTİLİR (ve düzeltildi): occ eksikliği (imkânsız işlemler), MTF lookahead
   (gelecek bilgisi), fail-open sleeve'ler (hesabı sıfırlayabilirdi), halt kilitlenmesi (bot sessizce
   durup açılmazdı — deploy edilmeden yakalandı).
**AYRIM: mekanik hata → düzelt. Karar körlüğü → genelde düzeltme (bot zaten elindeki bilgiyle
optimuma yakın). Muhasebe körlüğü (funding) → düzeltilemez, beklentiden düş.**

---

## 🔒 2026-07-28 — BİR AY GÖZETİMSİZ ÇALIŞMA DENETİMİ (getiri değil, DAYANIKLILIK)

Getiri tarafı kapandı (~20 fikir reddedildi, tavana yakınız). Bir ay başında kimse yokken kalan
gerçek risk OPERASYONEL: 30 gün kendi başına dönerken kırılabilecek kod yolları. Denetimdeki
36 bulgudan doğrulanmamış kalan 6'sı kapatıldı.

### ✅ BULUNAN VE DÜZELTİLEN KÖR NOKTA: koruma orta ömürde kaybolursa kimse fark etmiyordu
Borsa tarafı SL/TP SADECE iki noktada doğrulanıyordu:
  1. Girişte (`execution.py:672` — has_sltp_orders, 3 deneme, teyitsizse pozisyonu kapat)
  2. Yeniden başlatmada (`main.py:1752` — restore edilen pozisyonlar için resync)
**Girişte korumalı açılıp SONRADAN stop'u kaybolan pozisyonu hiçbir şey tekrar kontrol etmiyordu.**
`position_reconciliation_loop` yalnız pozisyon KAPANDIĞINDA (exch_qty < internal_qty) resync
çağırıyor; hâlâ açık olan pozisyonda `continue` ile geçiyordu. Gözetimsiz bir ayda bu, hesabın
büyük kısmını götürebilecek TEK arıza biçimi — pozisyon aşağı sınırı olmadan koşar.

**DÜZELTME** (`main._verify_protection` + `PROTECTION_CHECK_EVERY=10`): mutabakat döngüsünde
~20 dakikada bir, açık pozisyonun koruması SALT-OKUMA doğrulanır. Yalnız TEYİTLİ korumasızda
(iki ardışık okuma da `False`; `None`=belirsiz sayılmaz) alarm + mevcut denetimli resync yolu
devreye girer — o yol da stop'u kuramazsa pozisyonu kapatır (fail-safe = flat).
Sağlıklı yolda HİÇBİR mutasyon yok → çalışan korumaya dokunulmaz, hız limiti yenmez.
Test: `tests/test_protection_watchdog.py` — 8 senaryo (True/None/False→True/False→None/
False→False/istisna×2/API yok).

### ✅ DOĞRULANAN (sorun yok)
- **max-hold duvar-saati**: donchian `scores["max_hold"]=120` (30×4h=120s, primary_tf=1h
  biriminde) — `execution.py:769`. squeeze varsayılan 48 = 48s. Backtest bar sayımıyla birebir.
- **Stop taşıma**: `main.py:1103` — BE/trailing YALNIZ orb/ifvg'ye uygulanıyor, ikisi de KAPALI.
  Yani donchian/squeeze/BB'nin girişte takılan SL/TP'si ömrü boyunca HİÇ dokunulmuyor
  → "taşıma yarıda kalır, stop kaybolur" riski deploy'daki sleeve'ler için YOK.
- **Kontrat adımı kırpması**: `exchange.py:679` adım altı boyutu temiz hatayla reddediyor;
  portföy `order.quantity` (kırpma SONRASI) kullanıyor (`execution.py:781`) → hayalet boyut yok.
- **Plan-order 24h geçerliliği**: konu dışı kalıyor — birincil koruma giriş-bağlı position-level
  SL/TP (sticky, süresiz). Plan order sadece acil yedek; restart + yeni nöbetçi kapsıyor.
- **Çıkış muhasebesi**: mutabakat dış kapanışı doğru ücretle kaydediyor (giriş `entry_fee_rate`,
  çıkış taker 1bp) ve `_close_position_internal` tek yetkili → çift sayım yok.
- **Sleeve/coin çakışması**: donchian(7) ∩ squeeze(4) ∩ BB(LTC) = ∅ → netleşme çakışması yok.

### 📏 CANLI GİRİŞ KAPILARI vs BACKTEST (`live_gates.py` — YENİ)
Backtest "canlı config" diyordu ama `execution.py:334-412`'deki kapıların hepsini modellemiyordu.
Envanter çıkarıldı ve ölçüldü:

| kapı | backtest'te | etki |
|---|---|---|
| MAX_POSITIONS=7 | ✓ koltuk seçimi | modelli |
| tek-pozisyon/sembol + slot | ✓ occ | modelli |
| **COOLDOWN** (2 ardışık kayıp → 240dk) | **✗ YOKTU** | **1421 işlemde 1 sinyal, +$4** |
| korelasyon tavanı (grup {BTC,ETH,SOL}, tavan 2) | ✗ | **ASLA tetiklenemez**: BTC deploy'da yok
  → grubun 2 üyesi var → same_dir hiçbir zaman 2'yi aşamaz. Etki sıfır. |

**COOLDOWN PRATİKTE ATIL.** Sebep yapısal: anahtar (sleeve:coin) bazlı ve 240dk = donchian'da 1
bar / squeeze'de 4 bar. Stop olduktan sonra aynı coinde 1-4 bar içinde YENİ sinyal doğması
(40-bar kanalı tekrar kırmak / 5-barlık coil'in yeniden kurulması) neredeyse imkânsız.
3.2 yılda tek bir sinyal engelledi, o da kaybeden bir işlemdi (+$4 katkı).
→ **İlan ettiğimiz backtest rakamı modellenmemiş kapılar yüzünden ŞİŞİK DEĞİL.** Kapatmaya gerek yok.

### 🔧 DÜZELTİLEN ESKİMİŞ SABİT: POSITION_CAP_FRACTION
`deployed_backtest.py` CAP=1.0 kullanıyordu; canlı `.env` **1.25** (canlı işlem boyutlarından da
teyitli). Etki: **+$1224 → +$1286 (+%5)**, tavana takılan işlem %26→%17, maxDD %18.2→%19.5.
Yani ANKOR RAKAM daha önce ~%5 DÜŞÜK ilan edilmişti (muhafazakâr yönde hata).

**GÜNCEL ANKOR (3.2 yıl, sabit-oran, $190 taban, cap=1.25):**
`1421 işlem | PF 1.44 | WR %43 | +$1286 | maxDD %19.5 | en kötü ay −%20 | poz-ay %62`
`2023:$+307  2024:$+403  2025:$+398  2026:$+178` (her yıl pozitif)

NOT: diğer araştırma araçları (fade/horizon/mfe/partial/pf_kill/funding/liq) CAP=1.0 kullanmaya
devam ediyor. Bu, VERDİKLERİ KARARI değiştirmez (her iki kol da aynı yönde kayar), yalnız mutlak
$ rakamları ~%5 düşük çıkar. Bilerek dokunulmadı — bir ay gözetimsizken gereksiz kod hareketi
kendi başına bir risk.

### 📐 KAÇ İŞLEM GEREKİR (`sample_size.py` — bootstrap, 20.000 tekrar, gerçek 1440-işlem R dağılımı)
"Bir ay bakıp çalışıyorsa riski artırırız" sorusunun sayısal cevabı:

| N işlem | ÇALIŞAN sistem zararda görünür | PF %5-95 aralığı | PF<1 olasılığı |
|---|---|---|---|
| 20 | %24.1 | 0.56 – 3.13 | %24.8 |
| **30 (≈1 ay)** | **%18.9** | **0.72 – 2.82** | **%19.2** |
| 50 | %12.5 | 0.84 – 2.35 | %12.8 |
| 100 | %4.8 | 1.01 – 2.05 | %4.3 |
| 200 | %0.8 | 1.13 – 1.87 | %0.7 |

→ Bir ay (≈30 işlem) KANIT DEĞİL: çalışan sistem 5 ayın 1'inde zararda görünür ve ölçülen PF
0.72–2.82 arasında herhangi bir yere düşebilir. PF aralığı ancak **N≈100'de** (3-4 ay) 1.0'ı geçer.
Aylık PnL'in mean-reversion'ı (−0.345) ile birleşince "iyi aydan sonra riski artır" kuralı
istatistiksel olarak TERS yönde çalışır. **Risk seviyesi P&L'e değil drawdown tahammülüne bağlanır.**

### 🧪 TEST DURUMU: 8/8 GEÇİYOR
`test_multicoin.py` fail-safe varsayılan değişikliğinden (SR_BREAKOUT_ENABLED artık False)
sonra kırık kalmıştı — düzeltildi ve fail-safe davranışı ARTIK TEST EDİLİYOR (env yokken emekli
sleeve kapalı gelmeli, boş allowlist bunu maskelememeli). Yeni: `test_protection_watchdog.py`.

---

## 📉 2026-07-28 — CANLI DENETİM: ölçülen sürtünme + geri alınan iki alarm

Canlı DB (59 işlem, 55 kapanmış, bakiye $188.22) `live_report.py` ile denetlendi.

### DURUM: PF 0.83 / WR %33 — ama bu ARTIK VAR OLMAYAN bir konfigürasyon
Sleeve zaman çizelgesi (ilk→son işlem, PnL):

| sleeve | durum | n | PnL |
|---|---|---|---|
| asia_bo | KAPALI | 4 | −1.61 |
| sr_breakout | KAPALI | 1 | −1.89 |
| fvg | KAPALI | 10 | −0.45 |
| orb | KAPALI | 21 | −4.00 |
| **squeeze** | DEPLOY | 5 | −7.53 |
| **mean_rev** | DEPLOY | 10 | **+11.88** |
| **donchian** | DEPLOY | 8 | −3.52 |

**Kapalı sleeve'ler: −$7.95. Deploy'daki üçü: +$0.83 (net POZİTİF).** Toplam −$7.12.
ÖNCE/SONRA (kesim 2026-07-16, kapalı sleeve'lerin son işlemi):
  ÖNCE n=50 −$8.24 WR%32 PF 0.75 | SONRA n=5 +$1.12 WR%40 PF 1.11
→ "PF 0.83" ile "deploy'daki sistem çalışmıyor" AYNI ŞEY DEĞİL. Temiz dönem n=5 = gürültü.
Bootstrap'a göre N=50'de çalışan sistem bile %12.8 ihtimalle PF<1 gösterir; 0.83 alt %5'te.

### ✅ ÖLÇÜLEN GERÇEK SÜRTÜNME: donchian giriş kayması +13.4 bp
`intended_entry` (execution.py:758) vs gerçek dolum, 36 işlem:

| sleeve | n | ort bp | medyan bp | en kötü |
|---|---|---|---|---|
| **donchian** | 8 | **+13.4** | **+11.3** | +40.6 |
| squeeze | 4 | +1.7 | +0.3 | +6.4 |
| mean_rev | 5 | −0.9 | 0.0 | 0.0 |
| fvg / orb / sr_breakout | 19 | 0.0 | 0.0 | 0.0 |

Medyan ≈ ortalama → tek aykırıdan değil, HER İŞLEMDE oluyor. Sadece donchian'da.
**MEKANİZMA:** ORB/FVG/SR önceden belli SEVİYEYE limit ile girer → dolum = niyet. Donchian
kırılım mumunun KAPANIŞINDA piyasa emriyle girer; mum kapanışı → 120 mum çekme → ATR/ADX →
sleeve döngüsü → emrin borsaya varması arasında fiyat kırılım yönünde koşmaya devam eder.
Momentum stratejisinde bu gecikme yapısal olarak HEP ALEYHTE. Taker spread'i de üstüne biner.

**DÜZELTİLEMEZ (araştırıldı, hipotez ÇÜRÜTÜLDÜ):** "MAKER_ENTRY açık, 45sn maker beklemesi
kaymaya sebep oluyor, kapatalım" diye düşündüm — YANLIŞ. execution.py:592-595: donchian
`force_market=True` ile gelir ve limit yoluna HİÇ GİRMEZ (2026-07-16 denetiminde bilerek).
Zaten anında piyasa emri veriyor. Kalan kayma = spread + gecikme + momentum → yapılandırma
hatası değil, giriş biçiminin doğal maliyeti.

**BEDELİ:** R:R 2.5 → ~2.37 (kazanan başına %5.2 az). Donchian işlemlerin ~%70'i →
brütte ~%3.6 → **net kârın ~%12'si (~$152/$1286)**. Funding'in −%2.2'siyle toplam **~%14**
ölçülmüş sürtünme. İleriye dönük %75'lik ıskontonun İÇİNDE kalıyor — ama artık varsayım değil ÖLÇÜM.
DOĞRULAMA: model 13.4bp ile R:R 2.37 öngörüyor; açık 4 pozisyonun ortalaması 2.385. Tutuyor.
(Kapanmış 8 işlemdeki 2.187, en kötü durumların çektiği sapma. İlk tahminim ~35bp fazlaydı.)

### ↩️ GERİ ALINAN İKİ ALARM (ikisi de doğrulanınca çürüdü)
1. **"entry=0 PnL'i bozmuş olabilir"** — HAYIR. İki kayıt da entry=0 **ve** exit=0 **ve** pnl=0;
   toplam katkı **$0.00**. Botun ilk dakikasından (06-18 00:01) kalma hayalet satırlar, pozisyon
   hiç açılmamış. Kod yolu (exchange.py:715-733, tüm fallback'ler başarısız → filled_price=0)
   teorik olarak hâlâ riskli ama gerçekleşmemiş.
2. **"nominal tavanı delinmiş ($464.62 BNB)"** — ARTIK DEĞİL. Üç aşırı nominalin (BNB $464,
   BTC $374, SOL $303) ÜÇÜ DE **2026-06-23**. 07-12'den sonraki her şey ≤$229, tavan 1.25×188=$235.
   Tavan tam dayattığı yerde. risk.py:189-191'deki yorum hatayı anlatıyor: tavan `float(leverage)`
   varsayılanına düşerse levels-sleeve'leri 10× nominal alabiliyordu (10×~$93=$930 ⊃ $464).
   Hata GERÇEKTİ, OLDU, ZATEN DÜZELTİLMİŞ. `FIXED_MARGIN_USDT=0` → o dal hiç çalışmıyor
   (fixed-margin hipotezim de yanlıştı).

**Canlı .env teyidi:** LEVERAGE=10 · MAX_RISK_PCT=0.08 · RISK_SCALE=1.125 ·
FIXED_MARGIN_USDT=0 · POSITION_CAP_FRACTION=1.25 · MAX_POSITIONS=7

### 🧭 İLKE (funding'deki ayrımın tekrarı)
Mekanik hata → düzelt (occ, MTF lookahead, fail-open sleeve, nominal tavanı — hepsi düzeltildi).
Muhasebe körlüğü → düzeltilmez, beklentiden DÜŞÜLÜR (funding −%2.2, donchian kayması −%12).
Karar körlüğü → genelde dokunma (~20 fikir reddedildi).

---

## 🚪 2026-07-29 — SAHTE KIRILIM: ÇIKIŞ TARAFI DA KAPANDI + OI RETİ YENİDEN AÇILDI

Giriş tarafı zaten kapalıydı (AUC 0.502). Bu tur iki YENİ soru sordu.

### ❌ ERKEN ÇIKIŞ (`early_exit_test.py`) — 13/13 KAYBETTİRDİ
Soru farklıydı: "sahte kırılıma GİRME" (öngörü gerektirir, imkânsız) değil, "sahte kırılımın
TAM BEDELİNİ ÖDEME" (girişten SONRAKİ bilgiyi kullanır, öngörü gerektirmez).
Gerekçe: mfe_anatomy → SL'lerin %76.5'i 1R'ye bile ulaşmıyor = çoğu kaybeden kendini erken ele veriyor.
Kural: giriş+k barında kapanış R'si eşiğin altındaysa piyasadan çık. k∈{2,3,4,6,8,12} × eşik∈{−0.25,0,+0.25}.

| kural | n | WR | PF | toplam$ | Δ | maxDD% |
|---|---|---|---|---|---|---|
| TABAN | 1421 | %43 | 1.44 | +1286 | — | 21.5 |
| k=4 eşik−0.25R | 1589 | %28 | 1.40 | +1018 | **−267** | 15.7 |
| k=8 eşik 0.00R | 1568 | %26 | 1.42 | +1012 | −274 | 15.3 |
| k=2 eşik 0.00R | 1821 | **%16** | 1.36 | +707 | **−579** | 16.9 |

**MEKANİZMA = WR ÇÖKÜŞÜ (%43 → %16-30).** Kural, sonunda kazanacak işlemleri küçük zarara çeviriyor.
→ **YENİ BULGU: ayırt edilemezlik giriş anıyla sınırlı değil, girişten sonraki 2-12 BAR boyunca sürüyor.**
AUC 0.502'nin zaman eksenindeki uzantısı. Kazananlar da ilk barlarını rutin olarak girişin altında geçiriyor.
İşlem sayısı ARTTI (1421→1887): erken çıkış koltuğu boşaltıyor, başka sinyaller giriyor. O ikinci
mertebeden fayda GERÇEKTEN oluştu ve yine de yetmedi.

**RİSKE GÖRE DÜZELTİLMİŞ KARŞI ARGÜMAN — kontrol edildi, geçmedi:** maxDD ciddi düzeliyor
(21.5→15.7). Getiri/DD: k=4/−0.25R **64.8** vs taban **59.8** → oran olarak DAHA İYİ. Peki riski
1.37× artırıp boşalan DD alanını doldursak? 2024: 283×1.37=**388 < 403**. 2026: 96×1.37=**132 < 178**.
Yıl-yıl kuralı riske-göre-ölçeklenmiş halini de öldürüyor. (Bu argümanı kontrol etmeden reddetmek
özensizlik olurdu — en güçlü karşı argümandı.)

### ❌ HACİM ve SEANS (`vol_session_test.py`) — GÜNCEL tabanda yeniden, 11/11 RET
Eski ret ESKİ konfigürasyondaydı (rr2.0, taban $1115) ve lookahead sonrası yeniden doğrulanan
DÖRT retin arasında DEĞİLDİ. rr 2.0→2.5 ortak-mod değil (kazananın ödemesini büyütür) → verdict
flip edebilirdi. Etmedi:

| varyant | n | WR | PF | toplam$ | Δ$ |
|---|---|---|---|---|---|
| taban | 1421 | %43 | 1.44 | +1286 | — |
| hacim>1.00x | 1195 | %43 | 1.47 | +1167 | −118 |
| hacim>1.50x | 931 | %44 | 1.52 | +1014 | −272 |
| hacim>2.00x | 673 | %43 | 1.45 | +643 | −643 |
| sadece asya | 655 | %41 | 1.36 | +514 | −772 |
| asya HARİÇ | 1175 | %43 | 1.45 | +1085 | −201 |
| abd HARİÇ | 1103 | %42 | 1.38 | +857 | −429 |

**HACİMDE WR HİÇ DEĞİŞMİYOR (%43→%43→%44→%43).** 1591 sinyal elenmesine rağmen kalan kümenin
kazanma oranı aynı → hacim de kazananı kaybedenden ayıramıyor, sadece sistemi KÜÇÜLTÜYOR.
PF'in yükselmesi (1.44→1.52) bundan: kalan işlemler daha iyi değil, daha AZ. **PF oran, biz dolar kazanıyoruz.**

**SEANS — tutarlılık kapanı işledi:** "sadece asya" −$772 VE "asya HARİÇ" −$201 → İKİSİ DE kaybettiriyor.
Asya gerçekten kötü olsa dışlamak KAZANDIRMALIYDI. İkisinin de kaybetmesi = seans etkisi YOK,
sadece işlem sayısı düşüşünün maliyeti. (Bu kapan kasten kuruldu; olmasaydı "Asya'yı atla" makul görünürdü.)

### 🔓 OI RETİ YENİDEN AÇILDI — eski gerekçe EKSİKTİ
Ledger OI'yı "ccxt-MEXC `fetchOpenInterest: False`" diye kapatmıştı. Bu ret **ccxt'nin yetenek
bayrağına** dayanıyor, MEXC'in yeteneğine değil. Bu gece ccxt'nin `load_markets()` timeout verdiği
yerde HAM contract API'ye geçip veri aldık (fetch_universe.py) → **ccxt'nin sınırı MEXC'in sınırı DEĞİL.**
→ `oi_collect.py` yazıldı: ham API'yi PROBE eder, OI alanı varsa data/oi_log.csv'ye kaydeder,
yoksa gelen alan adlarını basar (tahminle kapatmak yerine ölçerek).

**NEDEN SADECE BU KALDI:** denenen her özellik fiyatın NE YAPTIĞINA bakıyordu. OI POZİSYONUN KİMDE
olduğuna bakar. Kırılım+artan OI = yeni para = gerçek; kırılım+düşen OI = pozisyon kapanışı =
stop avı = sahte. Bu ayrım OHLCV'de GÖRÜNMEZ — aynı mum, aynı hacim, TERS anlam.
**Geçmiş OI yok** (hiçbir borsa çok-yıllık vermiyor) → tek yol ileriye dönük toplamak. Bugün
başlanırsa 6-12 ay sonra test edilebilir. Maliyeti sıfır, bota dokunmuyor, BUGÜNE bir şey kazandırmaz —
bir OPSİYON yaratır. Cevap yine HAYIR çıkabilir, ama o zaman ölçüye dayanarak kapatılır.

### 📌 ÖZET: sahte kırılım artık İKİ TARAFTAN da kapalı
giriş anında öngörülemiyor (AUC 0.502, 13 özellik, yapı, takvim, hacim, funding) ·
çıkışta ucuzlatılamıyor (13 varyant, hepsi kaybettirdi, riske-göre bile) ·
kalan tek kapı OI ve o da ancak ileriye dönük toplanarak açılabilir.

---

## 🧾 2026-07-29/30 — GENİŞLİK KAPANDI · OI AÇILDI (probe BAŞARILI)

### ❌ GENİŞLİK (`breadth_expand.py`, VPS'te 9 yeni coin + 10 mevcut aday) — RET
Seçim TRAIN(2023-24)'den, karar TEST(2025-26)'den:

| K | n | toplam$ | Δtoplam | **ΔTEST** | dolu% | ort poz | yıl-yıl Δ |
|---|---|---|---|---|---|---|---|
| 3 | 1755 | +1454 | +169 | **−109** | 7.1% | 2.97 | 2023:+142 2024:+136 2025:−68 2026:−41 |
| 5 | 1936 | +1622 | +337 | **−59** | 10.7% | 3.38 | 2023:+112 2024:+284 2025:+20 2026:−79 |
| 8 | 2129 | +1809 | +523 | **−55** | 13.8% | 3.60 | 2023:+182 2024:+396 2025:+72 2026:−127 |
| 12 | 2358 | +1849 | +563 | **−131** | 17.3% | 3.85 | 2023:+287 2024:+407 2025:+60 2026:−191 |
| 16 | 2487 | +1762 | +477 | **−198** | 21.1% | 4.04 | 2023:+313 2024:+361 2025:+17 2026:−214 |

**HER sepette toplam ARTIYOR (+169…+563) ama ΔTEST HEPSİNDE NEGATİF.** Kazanç tamamen seçim
yapılan yıllarda (2023-24), dokunulmayan yıllarda (2025-26) bozuluyor = seçim yanlılığının
ders kitabı imzası. Train/test ayrımı tam bu yüzden konmuştu.
Koltuk doluluğu %7.1→%21.1, ort eşzamanlı 2.97→4.04 → K=16 < K=12 çünkü eklenen coinler artık
taban coinlerin işlemlerini KOVUYOR (breadth_test'in öngördüğü tavan).

**YAPILMAYAN VE NEDEN:** listede hem train hem test'te pozitif duran coinler var
(ZEC +86/+89, INJ +88/+35, DOT +39/+31, VET +32/+38, UNI +15/+53). "Sadece bunları al" demek
TEST VERİSİNE BAKARAK SEÇMEK olurdu = elimizdeki tek dürüst hakemi yakmak. Sonucu doğrulayacak
hiçbir şey kalmazdı. **Genişlik kolu kapandı.**

### 🔓 OI PROBE BAŞARILI — ledger'ın eski reti YANLIŞTI
`oi_collect.py --probe` (ham MEXC contract ticker, BTC_USDT):
```
holdVol = 821787711     ← OPEN INTEREST, VAR
fundingRate = 7.8e-05 · bid1/ask1 (spread) · fairPrice · indexPrice · amount24 · volume24
```
Eski ret "ccxt-MEXC fetchOpenInterest: False" idi → **ccxt'nin yeteneği, MEXC'in değil.**
Ham API veriyor. Ret eksik gerekçeye dayanıyordu, düzeltildi.
Bonus: bid1/ask1 → spread de kaydedilebilir (donchian'ın ölçülen 13.4bp kaymasının bileşeni).

**KURULDU:** `install_oi.sh` → `btc-bot-oi.timer`, 15 dk'da bir, `data/oi_log.csv`.
15 dk çözünürlük seçimi keyfi değil: donchian 4h barlarda çalışıyor → bir kırılım barının
İÇİNDE 16 örnek. Büyüme ~420k satır/yıl (~25 MB), disk sorunu değil. Bota/borsaya dokunmuyor.

**BUGÜNE KAZANCI SIFIR — bir OPSİYON yaratıyor.** 6-12 ay sonra test edilecek soru:
"kırılım barındaki OI DEĞİŞİMİ kazananı kaybedenden ayırıyor mu?" Cevap yine HAYIR olabilir;
ama o zaman ÖLÇÜYLE kapatılır, varsayımla değil. (Bu oturumda iki kez ölçüm, kurduğum mantığın
yanlış olduğunu gösterdi: fixed-margin hipotezi ve maker-bekleme hipotezi.)

---

## 🧊 2026-07-30 — KÖTÜ AYLAR: "KAZANMA" KOLU DA KAPANDI (3 açı + adversarial faz-2)

Kaçınma kolunun tavanı zaten +$231'di (mükemmel kâhinle). Bu tur soruyu tersine çevirdi:
**kötü aylarda kaçınmak yerine KAZANMAK.** Üç açı paralel test edildi, biri faz-2'ye geçti, o da düştü.

### ❌ A) CHOP AYLARINDA MEAN-REVERSION — ana hipotez ÇÜRÜDÜ
"Kırılımın sönmesi = ortalamaya dönüş" tezi YANLIŞ çıktı. Üretim `MeanReversionStrategy` ile
11 coin, tüm günler: **n=4645, PF 0.97, toplam −$248**.
  KÖTÜ aylarda −$220 (PF 0.92) | İYİ aylarda −$29 (PF 0.99)
→ mean-rev kötü aylarda iyi aylardan **DAHA KÖTÜ**. Breakout ile korelasyon −0.074 (≈sıfır).
Kâhinle sadece kötü aylarda açılsa bile −$216 = NEGATİF. TAM RED.

### ⚠️ FAZ-2'YE GEÇEN ADAY: hafta-sonu BB'nin 11 coine açılması — **REDDEDİLDİ**
Faz-1 umut vericiydi: tek başına +$275, korr −0.368, kötü-ay PnL'i **4/4 yıl pozitif**.
Faz-2 tam üretim testi bunu yıktı ve **en önemli ders taban hatasıydı**:

**TABAN HATASI (2.23× şişme):** Faz-1 salt-breakout'a ($1285.55) göre ölçtü. Ama CANLI config
zaten **BB(LTC) hafta-sonunu içeriyor** (ledger 913/1145). Doğru taban T1 = **$1420.66**.
LTC kolunun kendi katkısı $135.10 ve **4/4 yıl pozitif** — Faz-1 adaya "LTC'nin yokluğunu" da
kredi yazıyordu. Düzeltince delta **+$244.80 → +$109.69**.
→ **KURAL: bundan sonraki HER aday salt-breakout'a değil, CANLI konfigürasyona (BB-LTC dahil)
göre ölçülecek.** Bu tek başına bir sonucu yarıya indirdi.

Diğer red gerekçeleri (hepsi ölçüldü):
- **0/45 parametre varyantı** doğru tabanda her-yıl barını geçiyor (T0'da 3/45 "geçiyor", T1'de 0).
- **Takvime asılı, mekanizması yok:** hafta sonu +$110 | sadece Cmt +$13 | sadece Paz −$44 |
  Cuma+hafta sonu −$188 | hafta içi −$454. Komşu takvim tanımlarının hiçbirinde yaşamıyor
  → ledger'daki "seans filtresi = gürültü" imzasının aynısı.
- **Kazancın %163'ü 3 ayda.** O 3 ay çıkınca kol −$69, 3/4 yıl negatif.
- **Likidite testi TERSİNE çıktı:** en likit 3 coin −$4.57 | 5 −$7.85 | 7 −$8.84 | 9 +$76 | 11 +$99.
  Edge **sadece illikit kuyrukta** yaşıyor (XLM/DOGE/TRX ~$0.02M/saat) — slippage ve min-notional'ın
  en çok ısırdığı yerde, ve backtest ikisini de modellemiyor.
- **RİSK (Faz-1'in hiç ölçmediği şey): maxDD %24.4 → %46.0**, neredeyse iki kat.
  Getiri/DD oranı 58.2 → 33.2 (**%43 kötüleşme**). $190 hesapta %46 DD kabul edilemez.
- **Gizli yapısal yan etki:** mevcut deploy'da donchian ∩ squeeze ∩ BB = ∅ (ledger'da GÜVENLİK
  özelliği olarak kayıtlı). 11 coine açılınca 1736 hafta-sonu BB işleminin **579'u (%33)** aynı
  coinde bir breakout pozisyonuyla zaman çakışıyor. Koltuk modeli koltuğu sayıyor ama aynı sembolde
  **çift notional**'ın korelasyon/marjin riskini fiyatlamıyor → gerçek risk %46'dan da yüksek.
- **Bootstrap:** gözlenen aylık dağılımın kendisiyle bile 4/4-yıl barını geçme olasılığı **%14.2**.
  11 coinden sadece XRP'nin 4/4 geçmesi = şansın öngördüğü sayı (beklenen 1.6). Kanıt değil.

### ❌ B) KESİTSEL DAĞILIM — ilk PERSISTENT gösterge bulundu ama PnL ile bağı SIFIR
**POZİTİF BULGU (projede bir ilk):** kesitsel eş-hareket ölçüleri gerçekten öngörülebilir.
Aylık ACF(1): avgcorr **+0.411**, pc1 +0.417, disp_ratio +0.457 (60-gün pencerede +0.72…+0.78).
Karşılaştır: ADX ay-ay ACF **−0.379**. Yani "rejim ölçülemez" önermesi bu ölçü için YANLIŞ.

**AMA PnL ile korelasyon sıfır:** önceki-ay-sonu → o ayın PnL'i, en iyi |r| = 0.268 (xsdisp),
o da volatilite vekili — vol kontrol edilince kısmi korelasyon **−0.116**. Saf ayrışma **−0.086 ≈ 0**.
Pencere 10/20/40/60 taransa değişmiyor. İşlem bazlı (n=1421) r = −0.025…+0.031, hepsi p>0.15.
**Hipotezin işareti TERS:** "iyi" dediği rejimde (düşük korelasyon) işlem $+1097 < taban $+1286.
30 filtre varyantı (eşikler in-sample seçilmiş = iyimser): **0/30** tabanı geçti.

### 🧠 EN DEĞERLİ YAPISAL BULGU — bir FİKİR AİLESİNİ kapatıyor
Aylık PnL ACF(1) = **−0.277** (bilinen −0.345 ile tutarlı). Yani:
> **PERSISTENT bir gösterge ile ANTI-PERSISTENT bir hedefi kovalamak yapısal olarak çelişkilidir.**
ACF(gösterge)=+0.41 ve ACF(hedef)=−0.277 iken teorik üst sınır |r| ≤ 0.72 ve o da artığın ACF'inin
−1 olmasını gerektirir (gerçekleşmez); ölçülen her değer ≤0.27.
→ Sorun "rejim ölçülemiyor" DEĞİL — bu rejim mükemmel ölçülüyor. Sorun **HEDEFİN kendisinin
ay-ay ortalamaya dönmesi.** "Persistent rejim göstergesi bul, onunla aylık PnL'i zamanla"
programı bu yüzden yapısal olarak sakat. **Bu kola bir daha girilmemeli.**

### ❌ C) PORTFÖY VOL-HEDEFLEME — 36 varyant, "kazananların" tamamı gizli KALDIRAÇ
Ham bakışta 12/36 varyant toplam+her-yıl geçiyor. Ama **12'sinin de tamamı üst-sınır>1 kolundan**;
ortalama ölçek 1.04-1.08 → dağıtılan risk %3-6 daha fazla. Kazanç zamanlama değil, **kaldıraç**.
- **Muhafazakâr kol (sadece-küçült, üst=1.0): 12/12 KAYBETTİRDİ** ($+1142…$+1282 < taban $+1286).
- **maxDD DÜŞMÜYOR** (%19.4-26.9 vs taban %19.5) → "DD düşüyorsa kaldıraçlayalım" argümanının
  yakıtı yok. DD tabana eşitlenerek ölçeklendiğinde **36/36 elendi**.
- **En kötü ay KÖTÜLEŞİYOR** (−$38 → −$47…−$73). Sebep yine anti-persistence: düşük vol'den sonra
  vol büyüyor, sistem tam kötü döneme kaldıraçlı giriyor. Mekanizma yanlış yöne çalışıyor.
- **Permütasyon testi (2000 tur):** yıl-yıl geçen 6 varyantın p = 0.062-0.112 (anlamsız, üstelik
  36 test yapıldı). p<0.05 olan 8 varyantın **hepsi** 2025'te yıl-yıl barını düşürüyor.
  **İkisini birden sağlayan: 0/36.**
- Normalizasyon tutarsızlığı (gürültü imzası): ham 12 aday, DD-eşitlenmiş 0, eşit-risk 6 →
  **üçünün kesişimi 0**. Hangi normalizasyon seçildiğine göre aday kümesi tamamen değişiyor.
- Kâhin (lookahead'li) tavanı bile 3.2 yılda +$90 ve çoğu kaldıraç.

### 📌 KAPANIŞ
| kol | tavan | durum |
|---|---|---|
| kötü aydan KAÇINMA (mükemmel kâhin) | +$231 | kapalı (20 varyant) |
| chop'ta KAZANMA (mean-rev, doğru taban) | +$110, risk-ayarlı NEGATİF | **kapalı** |
| kesitsel dağılım rejimi | $0 (r≈0) | **kapalı** |
| portföy vol-hedefleme | ~$0 (kâhinle +$90, çoğu kaldıraç) | **kapalı** |

**Kötü aylar sorusu artık her iki taraftan da kapalı.** İyi aylar kötü ayların 4.2 katı; kötü aylar
bir kusur değil, iyi aylarda masada olmanın bedeli.

---

## 📐 2026-07-30 — ANKOR DÜZELTİLDİ: BB/LTC kolu artık DAHİL

`deployed_backtest.py` ta baştan beri BB/mean_rev(LTC, hafta sonu) kolunu **dışarıda** bırakıyordu
("~%3-5 ek" notuyla, ölçülmeden). Faz-2 ajanı ölçtü: kol **+$135.10 ve 4/4 YIL POZİTİF**
(2023 +13.97 / 2024 +54.02 / 2025 +49.40 / 2026 +17.72). Kol canlıda AÇIK.

İki ayrı zarar veriyordu:
1. Ankor rakamı ~%10 DÜŞÜK ilan ediliyordu.
2. Daha kötüsü: yeni adaylar YANLIŞ tabana kıyaslanıyordu. Hafta-sonu BB genişlemesi adayı bu
   yüzden **2.23x şişik** ölçüldü (+$245 sanılan delta gerçekte +$110'du) — çünkü aday, zaten
   sahip olduğumuz LTC kolunun kaldırılmasından doğan $135'i de kredi olarak alıyordu.

**GÜNCEL ANKOR (canlının TAMAMI, 3.2 yıl, sabit-oran, $190 taban, CAP=1.25, MP=7):**
`1579 işlem | PF 1.45 | WR %44 | +$1421 | maxDD %24.4 | en kötü ay −%21.0 | poz-ay %80`
`2023:$+321  2024:$+457  2025:$+447  2026:$+195`  (her yıl pozitif)
Ham sinyal: breakout 1440 + BB/hafta-sonu 163 = 1603 → koltuk sonrası 1579.
ÇAPRAZ DOĞRULAMA: bağımsız faz-2 ajanı aynı tabanı $1420.66 ölçtü. Birebir tutuyor.

**ESKİ (salt breakout) → YENİ (tam canlı) farkları:**
| metrik | eski | yeni | not |
|---|---|---|---|
| toplam | +$1286 | **+$1421** | +%10.5 |
| **pozitif ay oranı** | %62 | **%80** | BB kolu (korr −0.368) eğriyi DÜZLEŞTİRİYOR |
| PF | 1.44 | 1.45 | ~aynı |
| maxDD | %19.5 | **%24.4** | KÖTÜLEŞTİ — ek kol eşzamanlılığı artırıyor |
| en kötü ay | −%20.0 | −%21.0 | ~aynı |

**DÜRÜST OKUMA:** BB kolu parayı ve tutarlılığı artırıyor (poz-ay %62→%80, bu büyük bir fark)
AMA drawdown'ı da artırıyor (%19.5→%24.4). Sebep koltuk seçimi değil, EŞZAMANLILIK: aynı anda
daha çok pozisyon açık olması salınımı büyütüyor. Bu bir tercih değil, canlıda ZATEN böyle —
sadece artık doğru ölçüyoruz.

**KURAL (ledger'a kalıcı):** bundan sonraki HER aday `deployed_backtest.py`'nin ÜRETTİĞİ tabana
kıyaslanacak. Salt-breakout tabanı artık YANLIŞ taban.

---

## 🔍 2026-07-31 — "Hangi kol bizi bitiriyor?" (`sleeve_audit.py`) — CEVAP: HİÇBİRİ

Kullanıcı sorusu. Doğru soru "bu kol tek başına ne kazandı" DEĞİL (koltuklar paylaşılıyor;
bir kolu çıkarınca koltukları boşalır ve başka sinyaller girer), **"bu kolu ÇIKARSAK kitap ne
yapar"** — canlıda alınacak kararla (env'den kapatmak) birebir aynı soru.

Taban: tam canlı config, n=1579, PF 1.45, WR %44, **$+1421**.

### B) LEAVE-ONE-OUT (karar verdiren ölçü)
| çıkarılan | kalan n | toplam$ | Δ | yıl-yıl Δ | karar |
|---|---|---|---|---|---|
| donchian | 586 | +418 | **−$1003** | −202/−376/−267/−158 | KATKI SAĞLIYOR |
| squeeze | 1177 | +1154 | **−$267** | −99/−26/−135/−7 | KATKI SAĞLIYOR |
| bb | 1421 | +1286 | **−$135** | −14/−54/−49/−18 | KATKI SAĞLIYOR |

**Üç kolun da çıkarılması HER YIL zarar veriyor.** Kapatılacak kol yok.

### C) COIN BAZINDA — 12 coinin 11'i katkı sağlıyor
Tek pozitif delta: **TRX +$8** (çıkarınca kitap $8 iyileşir) ama 2026 −$7 → yıl-yıl barını
geçmiyor ve 3.2 yılda $8 zaten gürültü. Diğer 11 coin çıkarılınca kitap kötüleşiyor:
ADA −206 | SOL −166 | NEAR −150 | LTC −135 | ICP −126 | DOGE −113 | ETH −105 | XRP −84 |
BNB −74 | XLM −69 | BCH −64.

### 🧠 METODOLOJİK NOT: tek-başına ≠ portföy katkısı
| kol | tek başına | leave-one-out |
|---|---|---|
| donchian | +$1027 | −$1003 |
| squeeze | +$304 | −$267 |
| **bb** | **+$114** | **−$135** |
BB portföyde tek başına olduğundan **DAHA DEĞERLİ** (+$135 vs +$114). Sebep: hafta-sonu
zamanlaması koltuk için neredeyse hiç rekabet etmiyor, aksi halde BOŞ duran kapasiteyi
dolduruyor (breadth_test bulgusu: koltuklar zamanın %14.8'inde tamamen boş).
→ Bir kolu tek-başına rakamıyla yargılamak yanlış; koltuk etkileşimi işareti bile değiştirebilir.

### CANLI TABLOYLA İLİŞKİSİ
Canlıda squeeze −$7.53 görünüyor ama **n=6**. Backtest aynı kolu 3.2 yılda +$267 değerinde
ölçüyor. n=6'da PF 0.11 ile PF 3.0 arasında istatistiksel fark yok.
**Bizi gerçekten bitiren kollar zaten kapatılmıştı** (orb/fvg/asia_bo/sr_breakout = −$7.95,
canlı raporda "[kapalı]" satırı). O karar 2026-07-16'da verildi ve rakam o tarihten beri DONMUŞ.

---

## ⚖️ 2026-07-31 — "İYİ GİDEN KOLA DAHA ÇOK RİSK" (`sleeve_risk_test.py`) — HEPSİ RET

Kullanıcı sorusu: "BB canlıda iyi görünüyor, riskini artıralım mı?"
Canlı gerekçe zaten geçersiz (n=10, sonradan-seçim, aylık PnL −0.345 ile ortalamaya döner).
Ama BACKTEST gerekçesi meşru olabilirdi (BB korr −0.368) → ölçüldü.

### 🐛 ÖNCE: TESTİN KENDİ HATASI — 2 SAHTE "★ KABUL" ÜRETTİ
İlk sürümde `budget_neutral()` yalnız "diğer" kolları kısıyordu ve alt sınırı 0.05'ti. Donchian
işlemlerin %63'ü olduğu için 2x/3x'te diğerlerini sıfıra yaklaştırmak bile yetmedi; ikili arama
hedefe ULAŞAMADAN durdu ama fonksiyon yine de sonuç döndürdü → **ort risk %2.73 / %3.47
(taban %2.13) olduğu halde "bütçe-nötr" etiketiyle raporlandı** ve donchian 2x/3x satırları
"★ KABUL" aldı. **Test, yakalamak için yazıldığı KALDIRAÇ tuzağına kendisi düştü.**
DÜZELTME: global bir `g` ile TÜM vektör ölçeklenir (g serbestçe küçülebildiği için kısıt her
zaman sağlanır); sağlanamazsa `None` döner ve satır GEÇERSİZ basılır — sessizce yanlış etiket yok.
Düzeltilmiş koşuda **kabul edilen varyant sayısı: 0**.

### SONUÇLAR (bütçe-nötr = ort risk %2.13, tabanla AYNI)
| hedef | çarpan | A) ham Δ | risk× | **B) bütçe-nötr Δ** | karar |
|---|---|---|---|---|---|
| **bb** | 1.25 | +$22 | 1.016 | **+$2** (2024 −8) | yıl bozuk |
| **bb** | 1.50 | +$29 | 1.026 | **−$2** | RET |
| **bb** | 2.00 | +$20 | 1.038 | **−$24** | RET |
| **bb** | 3.00 | −$9 | 1.050 | **−$69** | RET |
| squeeze | 1.25→3.0 | +$2…−$14 | ~1.03-1.07 | **−$31…−$111** | RET (hepsi) |
| donchian | 1.25 | +$247 | 1.163 | **+$35** (2025 −2) | yıl bozuk |
| donchian | 1.50 | +$478 | 1.318 | **+$54** (2025 −3) | yıl bozuk |
| donchian | 2.00 | +$861 | 1.592 | **+$73** (2025 −8) | yıl bozuk |
| donchian | 3.00 | +$1383 | 1.940 | **+$94** (2025 −11) | yıl bozuk |

### 📌 EN ÇARPICI SAYI — KALDIRAÇ vs TAHSİS
**donchian 3x: ham +$1383 → bütçe-nötr +$94.** Görünen kazancın **%93'ü kaldıraçtı**, sadece
%7'si gerçek tahsis iyileşmesi. Bu, oturumdaki kaldıraç tuzağının en net örneği.
(Aynı imza vol-hedeflemede de vardı: 12 "kazanan" varyantın hepsi A'da iyi, B'de yok.)

### CEVAP: BB'nin riski ARTIRILMAMALI
İki gerekçeyle: (1) canlı kanıt yok (n=10), (2) backtest'te de bütçe-nötr olarak NEGATİF
(1.5x'ten itibaren −$2…−$69). BB zaten hak ettiği payı alıyor; değeri korelasyonunda
(−0.368) ve boş koltuk doldurmasında, büyüklüğünde değil.

### YAN BULGU (deploy EDİLMEDİ): donchian yoğunlaştırma
Tek sinyal barındıran yön. Bütçe-nötr 3x: **+$94 VE maxDD %26.2→%24.0** (hem daha çok para hem
daha az drawdown). AMA dört varyantın DÖRDÜNDE de 2025 negatif (−2/−3/−8/−11) → yıl-yıl barı
geçmiyor. Ayrıca donchian zaten işlemlerin %63'ü; daha da yoğunlaştırmak çeşitlendirmeyi
azaltır ve 2025 kırılması tam bu semptom. **+$94 = kitabın %6.6'sı** — bu kadar küçük bir
kazanç için beş sahte pozitifi öldüren kuralı esnetmek mantıksız.

---

## 🎯 2026-07-31 — ÇERÇEVEYE DOKUNAN 3 KOL (`param_rederive` / `daily_trend_test` / `trail_exit_test`)

Bugüne kadar her test mevcut çerçevenin ÜSTÜNE bir şey ekliyordu. Bu tur çerçevenin KENDİSİNE
dokundu: çekirdek parametreler, zaman ölçeği, çıkış mekaniği. Üçü de reddedildi — ama ikisi
"edge yok" değil, **"edge var, kullanamıyoruz"** dedi.

### ❌ A) ÇEKİRDEK PARAMETRELER BAYAT DEĞİL (427 kombinasyon)
Şüphe meşruydu: kanal40/SL2.0/mh30 occ hatası ve MTF lookahead DÜZELTİLMEDEN seçilmişti.
Temiz motorla yeniden türetildi → **aynı yere düşüyor.** Taban 400'lük ızgarada TRAIN sıra
**20/400**, TOPLAM **18/400**. kanal=40 hem TRAIN hem TEST marjinalinde açık ara en iyi.
TAM barı (TEST>taban VE 4/4 yıl) geçen kombinasyon: **0/400**.

**ASIL BULGU — parametre seçimi bu veride BİLGİ TAŞIMIYOR:**
  TRAIN↔TEST sıra korelasyonu: donchian **+0.27**, squeeze **−0.14**.
  TRAIN'de tabanı geçen 19 donchian noktasının yalnız 4'ü (**%21**) TEST'te de geçiyor —
  **saf şanstan (%50) DAHA KÖTÜ.** TRAIN ilk-10'un TEST ortalaması (+537) taban TEST'inin (+643) ALTINDA.
  Şans büyüklüğü: TRAIN-en-iyi z=+2.98; 400 çekilişin beklenen maksimumu z≈2.84 → **tepe, saf
  gürültünün üreteceğiyle neredeyse birebir aynı.**
→ Bu ızgarada parametre optimizasyonu yapmak yapısal olarak beyhude. Kol kapandı.

**🐛 ARAÇ HATASI (kayda değer):** ajan kendi kodunda pandas 3 tuzağı buldu — index dtype
`datetime64[us]`, `.values.astype(int64)` MİKRO-saniye veriyor ama `idx[i].value` NANO-saniye.
Karışık birim koltuk seçimini bozuyor (n=1584/$1399 vs doğru n=1579/$1421, ~%2 sapma).
**pandas 3'te bu depodaki her aracın zaman-damgası aritmetiği kontrol edilmeli.**

### ❌ B) GÜNLÜK YAVAŞ TREND — EDGE GERÇEK, KOLTUK-GÜNÜ ÖLDÜRÜYOR (270 kombinasyon)
**Bu oturumda görülen EN TEMİZ OOS davranışı:** TRAIN'de **270/270** kombinasyon pozitif,
TEST'te **259/270 (%96)** pozitif. Argmax değil, AİLE genelinde edge.
  En iyi (ch30/EMA100/SL2.0/rr4.0/mh60g): TEST n=104 PF 1.37 **$+104**; tüm dönem $+430
  bootstrap GA [$+183,$+683], P>0=%100.
  Kitapla aylık korelasyon **+0.193** (TEST döneminde **−0.211**) → hedef <+0.30 GEÇTİ.
  Tutuş 23.6 gün (taban 2.03). En iyi %10 işlem +84.0R / toplam +100.5R → **klasik CTA imzası
  doğrulandı: kâr az sayıda büyük trendden geliyor.**

**AMA BİRLEŞİK PORTFÖYDE ÖLÜYOR:** $+1421 → $+1206 (**Δ−214**), 2024/2025/2026 tabanın altında.
**SEBEP ÖLÇÜLDÜ — kıt kaynak KOLTUK değil, KOLTUK-GÜNÜ:**
  taban **$0.44/koltuk-günü** (squeeze 0.74 · bb 0.69 · donchian 0.39) vs günlük kol **$0.08**
  = tabanın **0.19x**'i. 23.6 gün koltuk tutan bir işlem yerine ~15 taban işlemi girebiliyordu.
  258 günlük sinyalin 157'si koltuk buluyor ve **453 taban işlemini dışarı itiyor** (1579→1126).
SEÇİM ARTEFAKTI DEĞİL: 270 kombinasyonun **261'i** TEST'te kitabı bozuyor. Parametreden bağımsız.
9 koltuğa çıkarma da çözmüyor (bütçe-nötr Δ−248; kaldıraçlı formda bile 2025 447→283).
→ **Tek meşru yol: AYRI SERMAYE / AYRI KOLTUK HAVUZU.** Kitaba ekleyerek değil.

### ❌ C) SABİT TP'Yİ KALDIR — MEKANİZMA DOĞRU, VERİ KARAR VERDİRMİYOR (69 kombinasyon)
**Tez mekanik olarak DOĞRULANDI:** TP'ye değen donchian işlemleri TP'den sonra ort **+2.17R**
daha gidiyor (medyan +1.12R, p90 +4.95R, maks +30.5R); %33'ü 2R'den fazla. Saf "TP yok" kontrolü:
ort işlem **+0.237R → +0.321R (+%35)**, maks R 2.5→**24.6**, R>5 işlem sayısı **0→24**.
Yani sabit TP büyük trendleri GERÇEKTEN kesiyordu.

**AMA:** TRAIN'de 10/66 tabanı geçti, **TEST'te 10/10 kaldı.** 11 varyantın 11'inde 2023 pozitif,
2025 negatif.
**KARARI VEREN ÖLÇÜM — KUYRUK YOĞUNLAŞMASI:** kolun kârının **%73'ü 24 işlemden** (%2.6) geliyor.
Yıl dağılımı 2023:11 · 2024:7 · 2025:2 · 2026:4 → **TRAIN'de 18, TEST'te 6.**
En iyi 10 işlem olmasa kol tabanın ALTINDA. Taban ise dağınık (en iyi 10 = kârın %8'i).
→ Soru 1476 işlemle değil, **efektif olarak ~24 gözlemle** cevaplanıyor. Bu örneklemde TRAIN/TEST
ayrımı sorunu ÇÖZEMEZ. Dürüst okuma: "trailing kötü" DEĞİL, **"bu veriyle karar verilemez"** →
kabul barı bunu RED olarak sonuçlandırır ve doğrusu budur.

**🧠 EN ÖNEMLİ METODOLOJİK DERS:** TRAIN'de geniş, monotonik, mekanik olarak anlamlı bir PLATO
vardı (dontr 5/10/15/20/30 = +641/+877/+1039/+1060/+1057; chand gevşedikçe monoton iyileşiyor)
ve **TEST'e hiç taşınmadı.**
> **PLATO, PARAMETRE gürültüsüne karşı korur; ÖRNEKLEM gürültüsüne karşı KORUMAZ.**
Belirsizlik parametrede değil, kârı taşıyan 24 işlemlik kuyruktaydı. Plato şartını bundan sonra
tek başına yeterli sayma.

**ÖZ-DENETİM:** ajan kendi varyantında bulaşma buldu — donchian-trail kaybedenleri de erken
kesiyor (ort kaybeden −0.855R vs taban −0.928R), yani kısmen reddedilmiş "erken çıkış" sınıfına
giriyor. Saf kontrol (notp: TP yok, stop SABİT) eklendi; sonuç değişmedi.

### 📌 BU TURUN GERÇEK SONUCU: DARBOĞAZ FİKİR DEĞİL, SERMAYE
İki bağımsız kol aynı yere çıktı:
| kol | edge gerçek mi | neden kullanılamıyor |
|---|---|---|
| **pairs** (ledger 2026-07-25) | evet, korr −0.362 | alt-hesap min-notional → ~$300-400 gerek |
| **günlük trend** (bugün) | evet, 259/270 TEST+, korr +0.19 | koltuk-günü maliyeti → ayrı havuz gerek |
Her ikisi de "daha zeki olamadık" değil, **"ikinci bir sermaye havuzu yok"** diyor.
Mevcut 7 koltuk 12 coin ve 3 sleeve arasında zaten paylaşılıyor; dördüncü bir kol ancak
başkasının yerini alarak girebiliyor ve koltuk-günü verimi tabanın 1/5'i.

---

## 🔬 2026-08-02 — 186 HİPOTEZ, 0 ADAY — ve NEDENİNİN MEKANİK AÇIKLAMASI

Kullanıcı sorusu: "başka indikatör ya da filtre deneyebilir miyiz?" Ledger'daki 13 özellik
listesinde RSI/MACD/StochRSI/Aroon/SuperTrend ve chop'a özel kanonik göstergeler YOKTU → meşru boşluk.
Üç aile paralel tarandı, **toplam 186 hipotez**, permütasyon + çoklu-test düzeltmesi zorunlu.

### ❌ A) TREND-KALİTESİ (68 hipotez) — Kaufman ER · Choppiness · VHF · Hurst
Chop'u ölçmek için ÖZEL tasarlanmış kanonik göstergeler. ADX yönlü-hareket tabanlıydı, bunlar
**yol-verimliliği** tabanlı = yapısal olarak farklı bilgi. Hepsi başarısız.
  TRAIN'i geçen 9/68 — **hepsi sinyalin %85-100'ünü TUTAN** ("neredeyse filtresiz") ayarlar.
  Anlamlı filtreleyen HER ayar para kaybetti: CHOP14<38.2 (−$146) · ER20>0.4 (−$78) ·
  VHF28>0.4 (−$141) · HURST50>0.55 (−$166) · ER40>0.5 (−$539).
  TEST'i geçen 2, HER YIL geçen **0/68**. Permütasyon (seçim döneminde) p=0.159 / 0.233.
  Plato YOK: VHF14 eşiği 0.3→−$13, **0.35→+$33**, 0.4→−$11 = tek-eşik sivrilmesi.
  Δ'nın %50'si **2-3 işlemden**.

**🔑 KRİTİK GÖZLEM — permütasyon dağılımının ORTALAMASI NEGATİF (−$9…−$46):**
sinyallerin %4-7'sini RASTGELE atmak bile ortalamada para kaybettiriyor. Yani "az filtreleyen"
ayarların minik pozitif deltası, negatif bir taban üstündeki gürültüden ibaret.
→ **Bu sistemde işlem ELEMEK, elenen ne olursa olsun, beklenen değeri DÜŞÜRÜR.**

Post-hoc (seçimde KULLANILMADI): HURST50 sinyal-düzeyinde TEST rho **+0.185 p<0.001** — istatistiksel
olarak gerçek. Ama PARASALLAŞMIYOR: PF 1.45→1.59 yükselirken işlem 1579→995 düşüyor, toplam $ HER
YILDA tabanın altında. Kırmızı bayrak: HURST50 ile ER40 korelasyonu **−0.002** (ikisi de aynı şeyi
ölçmeliydi; ER40-VHF28 +0.540). Basit R/S paydası yüzünden Hurst kısmen VOLATİLİTE-aykırılığı
ölçüyor = zaten reddedilmiş ATR% ailesi.

### ❌ B) KLASİK OSİLATÖRLER (50 hipotez) — **KÖK NEDEN BULUNDU: TOTOLOJİ**
Bu turun en değerli bulgusu. Osilatörler, donchian girişinin **tanımı gereği zaten sağladığı**
şeyleri soruyor. Sinyal anındaki dağılım (2570 donchian adayı):

| gösterge | LONG sinyallerinde | sonuç |
|---|---|---|
| **RSI(14)** | min **57.7**, medyan **73.0** | "RSI>50 momentum onayı" **0 sinyal eliyor** |
| **AroonUp(25)** | min **100.0**, medyan 100.0 | **MATEMATİKSEL TOTOLOJİ** (kırılım mumu zaten 25-bar zirvesi) |
| SuperTrend(10,3) | sinyalle **%99.8** uyumlu | eleme ~0 |
| MACD çizgi işareti | **%99.6** uyumlu | eleme ~0 |
| MACD histogram | **%96.8** uyumlu | eleme ~%3 |

→ "Uyum" filtreleri %0-4 eliyor, sonuç tabanla **özdeş**. "Fade" yönü sleeve'i yok ediyor
(donchian RSI-fade %100 eliyor → −$578).
**Bağımsız bilgi taşıyan tek ikisi para kaybettiriyor:** RSI>70 (%34 eliyor, TRAIN −$85 TEST −$164,
**ama PF 1.48→1.52 YÜKSELİYOR** — klasik tuzak) · StochK>80 (%32 eliyor, −$92/−$51).
**40-barlık bir kanal kırılımı, yüksek-RSI + Aroon-100 + pozitif-MACD + SuperTrend-uyumlu bir
olayın TA KENDİSİDİR.** Bu göstergeleri "eklemek" yeni bilgi değil, aynı şeyi ikinci kez sormak.

### ❌ C) HACİM TÜREVLERİ (68 hipotez) — ham hacimle AYNI patoloji
  **WR 68 hipotezin hepsinde %41.5-44.9 bandında; |ΔWR| > 2 puan olan: 0/68** (taban %43.5).
  Hacmin YÖNÜ ve BİRİKİMİ de kazananı kaybedenden ayırmıyor.
  **VWAP24 donchian'da DEJENERE:** yön-işaretli mesafenin MİNİMUMU **+%0.89**, %100'ü >%1.
  40-bar kırılımı tanımı gereği 24-bar VWAP'in çok üstünde kapanıyor → **sıfır bağımsız bilgi.**
  (mean_rev'de çalışmasının sebebi de bu: orada giriş kuralının doğal parçası değil.)
  **Seviye-likiditesine normalize kırılım gücü, ham hacimden ZAYIF** (rho +0.038 vs +0.075) →
  normalize etmek bilgi eklemiyor, **gürültü ekliyor**.
  A/D20 eğimi: TRAIN +0.263 (p=0.023) → TEST **−0.077** = ders kitabı işaret dönmesi.
  TRAIN'i geçen tek filtre ([sqz] OBV10>0) TEST'te −$5, komşu eşiklerin hepsi negatif.

### 🧠 BİRLEŞTİRİCİ AÇIKLAMA (bu eksenin KAPANIŞI)
Üç ailenin üçü de aynı yere çıkıyor:
> **Donchian giriş koşulu, bu göstergelerin ölçtüğü şeyi ZATEN İÇERİYOR.**
> EMA200 üstünde 40-bar kanal kırılımı = yüksek RSI + Aroon 100 + pozitif MACD + VWAP üstü +
> yüksek yol-verimliliği. Bunları filtre olarak eklemek ya hiçbir şey elemiyor (totoloji) ya da
> bağımsız oldukları yerde kazananı da kaybedeni de ORANTILI eliyor (WR kıpırdamıyor).
Buna permütasyon bulgusu ekleniyor: **rastgele eleme bile negatif beklenen değerli.**
→ **Giriş-filtresi ekseni artık sadece "denendi, olmadı" değil, MEKANİK OLARAK kapalı.**

### 📋 METODOLOJİ NOTLARI (ajanların kendi öz-denetimleri)
- **Koltuk sırası tuzağı:** `seat_select` sort'u STABİL; sleeve'leri farklı sırada eklemek aynı
  entry_ns'li işlemlerde koltuk sırasını değiştirip $1421→$1418 yapıyor. `DB.main`'in sırası
  (DONCH→SQZ→BB) korunmalı. pandas 3 nano/mikro tuzağının kardeşi.
- Bir ajan kendi eşik ızgarasını TEST çeyreklerini gördükten SONRA genişlettiğini fark edip o
  aileyi "KİRLİ" işaretledi (geçmediği için sonuca etkisi yok). Doğru davranış.

---

## 🧮 2026-08-02 — BOYUTLANDIRMA (filtre değil BOYUT): RED — ve manşet rakamın KİRLİ olduğunun itirafı

Kullanıcı sorusu: "unuttuğumuz bir gösterge olabilir mi, ve bunları doğru test ediyor musun?"
İkinci soru bu oturumda ÜÇÜNCÜ kez gerçek bir kusur ortaya çıkardı.

### 🔍 BULUNAN BOŞLUK: ~230 hipotezin HEPSİ aç/kapa kapısıydı
Permütasyon bulgusu şunu göstermişti: sinyallerin %4-7'sini RASTGELE atmak bile ortalamada para
kaybettiriyor → **işlem SİLMEK her koşulda beklenen değeri düşürüyor.** Ama bazı göstergeler
sinyal düzeyinde GERÇEK bilgi taşıyor (HURST TEST rho +0.185 p<0.001).
→ **BOYUTLANDIRMA işlem silmez.** Filtrelemenin yok ettiği bilgiyi çıkarabilecek tek mekanizma.
Hiç denenmemişti. Meşru boşluktu.

### ⚠️ İLK DENEME KİRLİYDİ — kendi itirafım
"Hurst50 tier k=0.6 → ΔTEST +$150" çıktı ve bunu örneklem-dışı sonuç olarak sunmaya yaklaştım.
**Değildi.** Seçim zinciri TEST'e ÜÇ noktada dokunmuştu:
  1. HURST, önceki bir ajanın POST-HOC analizinde **TEST** rho +0.185 bulduğu için seçildi
  2. N=50 penceresi o post-hoc bulgudan MİRAS alındı (TRAIN'den türetilmedi)
  3. k=0.6/tier, benim taramamda en büyük **ΔTEST**'i verdiği için öne çıktı
Pencere sağlamlık testi bunu bağımsız olarak ele verdi: ΔTEST N30:+16 N50:**+150** N80:+80
N100:−11 → **plato YOK**, ve TRAIN'in en iyisi (N=80) TEST'in en iyisi (N=50) DEĞİL.

### ❌ TEMİZ TEST (tüm parametreler TRAIN'den, TEST bir kez açıldı)
Izgara: 17 gösterge-pencere × 2 mod × 3 k = **102 kombinasyon**.
**TRAIN argmax: hurst80/tier/k=0.6** (ΔTRAIN +$161) — kirli denemenin hurst50'si DEĞİL, tahmin edildiği gibi.

| kriter | sonuç |
|---|---|
| (b) ΔTEST > 0 | ✓ **+$80** |
| (c) HER YIL > 0 | ✓ 2023:+126 2024:+38 2025:+72 2026:+6 |
| (d) BÜYÜKLÜK > %2 taban | ✓ (eşik $13) |
| (e) DOZ-TEPKİ monoton | ✓ +27 → +56 → +80 |
| **(f) PERMÜTASYON** | ✗ **ham p=0.1044** · Šidák(102) p=1.0000 |

**DÜZELTMESİZ HALDE BİLE ANLAMSIZ (p=0.10).** +$80, rastgele boyutlandırmanın ürettiği aralığın
içinde. Šidák tartışmasına bile gerek kalmadı. **SONUÇ: RED.**

Not: önceden-kayıtlı seçim (+$80), kirli manşetin (+$150) yarısından biraz fazla — beklendiği gibi.

### 🧠 ÜÇÜNCÜ KEZ AYNI YAPISAL BULGU: TRAIN SIRALAMASI TEST'İ ÖNGÖRMÜYOR
Şeffaflık satırı: TEST'in en iyisi (hurst50/tier/k0.6, ΔTEST +$150) **TRAIN sıralamasında 28/102.**
Bu, aynı olgunun üçüncü bağımsız ölçümü:
| ölçüm | bulgu |
|---|---|
| parametre taraması (427 komb.) | TRAIN'de tabanı geçenlerin %21'i TEST'te de geçiyor (**şans %50**) |
| günlük trend (270 komb.) | TRAIN↔TEST sıra korelasyonu Spearman **+0.247** |
| boyutlandırma (102 komb.) | TEST'in en iyisi TRAIN'de **28/102** |
→ **Bu veride "TRAIN'den seç" işleminin KENDİSİ bilgi taşımıyor.** Filtre, parametre, boyut —
üçünde de aynı. Arama ekseni yapısal olarak kapalı; sorun aday fikir eksikliği DEĞİL,
3.2 yıllık verinin seçim yapmaya yetmemesi.

### 🔧 KABUL BARI DÜZELTİLDİ (eski bar büyüklük körüydü)
Eski bar **$4'lük ADX gürültüsünü KABUL**, **$150'lik Hurst etkisini RED** etmişti (2025 deltası
+$0.4 yuvarlanınca pozitif göründüğü için). Eklenen üç şart:
  (d) **BÜYÜKLÜK**: Δ tabanın en az %2'si — $4 buna takılır
  (e) **DOZ-TEPKİ**: parametre arttıkça etki monoton artmalı — gürültü doz-tepki üretmez,
      plato şartından daha güçlü ayırıcı
  (f) **Šidák düzeltilmiş permütasyon**, ızgara boyutuna göre
Ayrıca **şeffaflık satırı**: TEST'in en iyisi TRAIN'de kaçıncı — seçimin bilgi taşıyıp taşımadığı.

### 📋 BİLİNEN KUSUR (dürüstlük için kayda geçiyor)
Yıl-yıl barının yanlış-negatif oranı YÜKSEK: gözlenen dağılımın kendisiyle bile 4/4 barını geçme
olasılığı **%14.2** (trailing testinden). Yani bu bar, gerçek ama küçük edge'lerin ~%86'sını
reddediyor. Beş sahte pozitifi öldürdü; bedeli bu. $181'lik gözetimsiz bir hesapta doğru takas —
ama takas olduğu bilinerek kullanılmalı.
