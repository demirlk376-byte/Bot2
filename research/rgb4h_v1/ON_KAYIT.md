# RGB-4H (Regime-Gated Breakout) — dış rapordaki setup'ın ATLAMADAN testi — ÖN KAYIT (2026-10-28, sonuçlardan ÖNCE)

Kaynak: kullanıcının paylaştığı "BTC Setup Raporu (28 Ekim 2026): Rejim Kapılı Sıkışma Kırılımı (RGB-4H)". Rapordaki
kurallar, ablasyon, walk-forward, maliyet, Monte Carlo, DSR, kabul ve red kriterleri AYNEN uygulanır. Raporun belirsiz
bıraktığı yerler aşağıda [köşeli parantez] içinde sabit çözümlerle kapatıldı. Not: rapor "mevcut sistem = Donchian 20/10
+ EMA200 4H" varsayıyor; bizim canlı donchian'ımız farklı (40 bar, TP 2.5R, hacim ≥ 2.5×). Burada raporun tanımladığı
sistem test edilir; bizim sistemle karşılaştırma yalnız bilgi olarak raporlanır.

## Veri
Binance USDⓈ-M BTCUSDT ve ETHUSDT 1h (`scratchpad/btc_veri/veri/{BTC,ETH}_fut_1h.csv`, 2020-01-01 → 2026-10-03) →
4H mumlar (00/04/…/20 UTC hizalı) ve günlük mumlar (UTC). Funding: `btc_veri/veri/BTC_funding.csv`,
`research_data/h4_kirilim_v6/veri/ETH_funding.csv` (8 saatlik gerçek oranlar). Sinyaller ısınmadan sonra (günlük EMA200
için 200 kapanmış gün) başlar.

## Kurallar
- Göstergeler (4H, yalnız kapanmış barlarla): DC20 üst/alt = önceki 20 barın en yüksek/en düşük değeri (sinyal barı
  hariç); DC10 aynı şekilde 10 bar; ATR(14) [Wilder]; EMA200 4H kapanış; BB(20,2) BandWidth = (üst−alt)/orta; BBW
  yüzdeliği = sinyal barı dahil son 180 barın içindeki sırası; ER(30) = |C_t − C_{t−30}| / Σ|ΔC| (30 bar).
  Günlük EMA200: yalnız TAMAMLANMIŞ günlük kapanışlarla, sinyal barının kapanışından önce biten son gün.
- **Varyant a (raporun "mevcut sistemi")**: long ⇔ 4H kapanış > DC20 üst VE kapanış > EMA200(4H); short simetrik.
  Giriş bir sonraki bar açılışında. Başlangıç stopu giriş ∓ 2×ATR(14). Çıkış: DC10 karşı taraf (long: önceki 10 barın en
  düşüğü; bar içinde dokunursa o seviyeden, açılış zaten ötesindeyse açılıştan). Etkin stop = long için max(başlangıç
  stopu, DC10 alt), short için ayna. Risk %1, kaldıraç tavanı 3x, toplam açık risk ≤ %1.5 [ikinci pozisyon tavana
  sığacak kadar küçültülür; sığmazsa atlanır].
- **b = a + Gate 1**: long yalnız günlük kapanış > günlük EMA200, short yalnız altında; 4H EMA200 filtresi korunur; tetik
  RGB tetiği: 4H kapanış > DC20 üst + 0.25×ATR(14) (short simetrik). [Tetik tamponu b'den itibaren uygulanır;
  a + tampon "a′" bilgi amaçlı ayrıca raporlanır.]
- **c = b + Gate 2**: giriş barında (i) son 12 bar içinde (sinyal barı dahil) BBW yüzdeliği ≤ 20 olmuş, VEYA (ii) ER(30) ≥ 0.30.
- **d = c + başarısız kırılım çıkışı + boyut/risk kuralları + operasyonel filtreler**: girişten sonraki 6 bar içinde bir 4H
  kapanış kırılan DC20 seviyesinin (sinyal anındaki) gerisine dönerse bir sonraki bar açılışında çık. Risk = %1 ×
  min(1, %40 / RV30) [RV30 = son 30 tamamlanmış günün günlük log getirisi std × √365]; strateji özsermayesi zirvesinden
  %15'ten fazla düşükse risk yarıya iner; kaldıraç tavanı 3x, toplam risk ≤ %1.5. Funding son oranı > %0.05/8s ise yeni
  long yok. Event filtresi: FOMC açıklamasından (14:00 ET) önceki 2 saat içinde yeni giriş yok; sinyal açıklamayı içeren
  bardaysa o sinyal atlanır, sonraki bar kapanışı normal değerlendirilir; event barındaki giriş/çıkışta kayma 2 kat.
  [CPI tarih takvimi çevrimdışı güvenilir şekilde bulunamadığı için event filtresi YALNIZ FOMC'dir — sınırlama.]
- Test varyantı (bilgi): d'de trailing yerine 3×ATR Chandelier (girişten beri en yüksek − 3×ATR).
- Varlıklar: BTC ve ETH, aynı donmuş parametrelerle, ortak özsermayede.

## Maliyet
Taker %0.05 giriş + %0.05 çıkış; kayma 3.5 bp/taraf [rapordaki 2–5 bp'nin ortası], event barında 2 kat; gerçek funding
(tutulan her settlement'ta long öder). STRESS: tüm maliyetler 2 kat.

## Doğrulama (raporun planı)
1. Ablasyon: a, b, c, d tüm dönemde; Sharpe (günlük getiri, yıllık √365), maxDD, işlem sayısı, PF, toplam getiri, "range
   aylarındaki kayıp". [Range ayı = BTC'nin o takvim ayındaki günlük kapanışlarıyla ER < 0.30 olan ay; range kaybı = o
   aylarda stratejinin aylık getirilerinin toplamı.]
2. Walk-forward: 24 ay IS / 6 ay OOS, 6 ay kaydırmalı. Donchian/ATR donuk. IS'te 27'lik ızgara (BBW yüzdeliği 10/20/30 ×
   ER 0.25/0.30/0.35 × başarısız kırılım barı 4/6/8) üzerinde d varyantı; seçim = IS Sharpe en yüksek; OOS'ta o
   parametreyle. Plato: ızgaradaki IS Sharpe'ların dağılımı ve OOS'un tüm ızgarada raporu; tek tepe (en iyi noktanın
   komşularının IS Sharpe'ı en iyinin %50'sinin altındaysa) → RED.
3. Monte Carlo: işlem sırası karıştırma (10 000) ve 1 aylık blok bootstrap (10 000), `default_rng(20261028)`; %95'lik
   maxDD ≤ %25.
4. Deflated Sharpe Ratio (Bailey & López de Prado 2014): OOS günlük Sharpe için, deneme sayısı N = 150 [raporun "150+
   varyant" ifadesi], Sharpe varyansı = 27'lik ızgaranın IS Sharpe varyansı, çarpıklık/basıklık OOS getirilerinden.

## Kabul (hepsi): maliyet sonrası OOS PF ≥ 1.3 · OOS Sharpe ≥ IS Sharpe'ın %70'i · c/d range kaybı a'dan en az %30 düşük ·
c/d toplam getirisi a'nın en az %80'i · DSR > 0.95 · OOS'ta BTC+ETH ≥ 100 işlem ve her OOS katında ≥ 15 · MC %95 maxDD ≤ %25.
## Red (biri yeter): Gate 2 iyileşmesi (c − b) tek yıldan (en iyi yıl çıkarılınca ≤ 0) veya tek varlıktan geliyor · ETH'de
ters sonuç (ETH'de d − a < 0 iken BTC'de > 0, ya da tersi) · toplam işlem < 50.
**KABUL** ⇔ tüm kabul kriterleri sağlanır VE hiçbir red kriteri tetiklenmez. Aksi halde RED.
Ek (karar dışı): bizim canlı donchian'ın BTC'deki sonucu (btc_setup_v1) ve KABUL çıkarsa portföy katkısı ayrı ön kayıtla.
Sonuç görüldükten sonra hiçbir kural, eşik, ızgara, maliyet, tanım veya ölçüt değiştirilmez.

---
## SONUÇ (2026-10-29) — RED (raporun kendi kriterleriyle)
İki kör uygulama + denetçi: tek fark A'nın başlangıç stopunu kaymalı dolum fiyatına bağlamasıydı (spec: ham açılış);
düzeltildi, 18 işlem kümesi, walk-forward ızgarası, katlar, günlük eğriler, DSR ve MC float hassasiyetinde aynı.
Kesme testi (gelecek veri yok), IS-yalnız seçim, 7 işlem elle, DD yarılama, FOMC filtresi doğrulandı.

Ablasyon (BTC+ETH, 2020-07-19 → 2026-10-04, %1 risk, taker %0.05 + 3.5 bp kayma, gerçek funding):
| varyant | işlem | toplam getiri | Sharpe | maxDD | PF | range kaybı |
|---|---|---|---|---|---|---|
| a Donchian 20/10 + EMA200 | 686 | +%192 | 0.98 | %16.7 | 1.39 | %31.5 |
| a′ a + 0.25×ATR tampon (bilgi) | 571 | +%237 | 1.15 | %15.7 | 1.54 | %20.7 |
| b + günlük EMA200 | 396 | +%75 | 0.73 | %12.9 | 1.32 | %22.8 |
| c + Gate 2 | 326 | +%61 | 0.65 | %17.1 | 1.31 | %19.5 |
| d RGB-4H tam | 322 | +%77 | 0.88 | %11.6 | 1.54 | %5.9 |
| d Chandelier (bilgi) | 316 | +%80 | 1.00 | %10.6 | 1.63 | −%5.9 |
STRESS: a +%94 / d +%47. Walk-forward (9 kat, OOS 2022-07 → 2026-10, 205 işlem): PF 1.308, OOS Sharpe 0.522 (gereken
≥ 0.650 = %70 × IS 0.929), DSR 0.735, MC %95 maxDD %16.0 (karıştırma) / %24.1 (blok). Plato var (tek tepe yok).
Kalan: K2 (OOS Sharpe), K4c/K4d (c %61, d %77 vs gereken %154), K5 (DSR), K6b (son kısa katta 13 işlem). Red tetikleri:
R1a/R1b — Gate 2 (c − b) iyileştirmiyor, kötüleştiriyor: toplamda −13.7 puan / −0.08 Sharpe, BTC'de ve ETH'de ayrı ayrı
negatif. Kabul edilenler: K1 (PF 1.31), K3 (range kaybı azalıyor), K6a, K7, R2, R3, plato.
Hüküm: RED. Kapılar düşüşü ve range kaybını azaltıyor ama kazancın çoğunu kesiyor. Not (karar dışı, sonuç sonrası
gözlem): en iyi varyant filtresiz a′; bu gözlem ancak ayrı ön kayıtla, bota katkı ölçütüyle sınanabilir.
