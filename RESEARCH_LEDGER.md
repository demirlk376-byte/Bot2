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
| ORB canlıdan çıkarma | 25 Temmuz'da BE'li örneklemde PF<0.5 kalırsa | ORB_ENABLED=false (paper'da izlemeye devam) |
| RISK_SCALE artırımı (1.25→1.5→2.0 kademeli) | Canlı PF ≥1.1-1.2, 30+ trade | .env değişikliği + izleme |

## 💡 HENÜZ TEST EDİLMEMİŞ ADAY HAVUZU (sprint 2 malzemesi)

- Hafta-içi/saat bazlı saatsellik (weekend etkisinin genellemesi)
- OI-divergence (fiyat yeni tepe + OI düşüyor → tükeniş)
- Vadeli-spot baz (basis) aşırılıkları
- Kullanıcıdan gelen her fikir → önce burada kaydedilir, sonra ön-kayıtlı harness

> Not: Mühür "fikir aptalcaydı" demek değil, "bu veri bu çıtayı geçemedi" demek.
> Canlıdaki 7 sleeve de aynı makineden sağ çıkanlardır — makine böyle çalışır.
