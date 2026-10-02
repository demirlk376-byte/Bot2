# TREND_TAKİP_V1 — önceden kayıt (2026-10-02, sonuçlardan ÖNCE)

## Soru
Kripto yılda birkaç büyük trend yapıyor; örneğin XLM +%521, XRP +%422, SOL +%269. Bu
trendlere kırılımla girip haftalarca TAŞIYAN bir günlük trend takipçisi, maliyetler sonrası
kâr ediyor mu? Mevcut bot ve NW+KAMA, bu trendlerin ilk birkaç gününden sonrasını kaçırıyor
(NW_KAMA_V2_SONUC.md teşhisi).

## Veri
- **Kaynak:** Binance USDⓈ-M 1d mumları ve fundingRate (`veri/trend1d` dalı), 2019-09 → 2026-09.
  MEXC'in derin geçmişi yok, bu yüzden venue vekili.
- **Evren:** botun 12 coini (SOL, ETH, ADA, NEAR, BCH, XRP, DOGE, TRX, XLM, LTC, ICP, BNB).
  Her coin, kendi listelenmesinden sonra 200 günlük ısınmayı tamamlayınca işlem görebilir.
- **Tick, kontrat, minimum emir:** MEXC güncel metadata (sweep verisindeki dosya).

## Kurallar (12 varyant = 2 giriş × 3 çıkış × 2 yön)
- **Giriş:** Günlük kapanış, önceki N günün en yüksek tepesinin ÜSTÜNDE → ertesi gün açılışında long.
  Short, yalnız LS varyantlarında ve aynanın tersiyle.
  - N ∈ {50, 100}.
- **Çıkış:**

  | kod | kural | ilk stop (R) |
  |---|---|---|
  | **X3** | Takip eden stop = girişten beri en yüksek kapanış − 3×ATR20. Yalnız yukarı taşınır. Gün içi dokunuşta stop emriyle çıkılır; açılış stopun ötesindeyse açılıştan. | giriş günü kapanışı − 3×ATR20 |
  | **X5** | Aynısı, 5×ATR20 ile. | giriş günü kapanışı − 5×ATR20 |
  | **XH** | Kapanış önceki N/2 günün en düşük dibinin altına inerse ertesi açılışta çıkış. | o N/2 dip |

- **Yön:** L (yalnız long) ya da LS (long + short).
- **Varyant kimliği:** `N{50|100}_{X3|X5|XH}_{L|LS}`.
- **Kurallar:**
  - Hedef yok, azami tutuş yok.
  - Sembol başına tek pozisyon.
  - Yeni giriş sinyali yalnız pozisyon yokken değerlendirilir.

## Yürütme ve maliyet
- **Dolum:**
  - Sinyal, günün kapanışında bilinir; dolum ertesi açılışta.
  - Kayma ve komisyon NORMAL profille: 15.85bp giriş kayması, 0.24bp çıkış kayması,
    1bp/taraf komisyon. STRESS profilde kaymalar ×2.
  - Tick yuvarlaması aleyhe yapılır.
- **Funding:**
  - Gerçek settlement oranları uygulanır.
  - Pozisyonun açık olduğu (giriş < τ ≤ çıkış) her settlement'a, o günün açılış fiyatıyla.
  - Gün içi çıkışta, o günün settlement'ları için çıkış gün sonunda varsayılır. Bu bir yaklaşımdır.
- **Risk:**
  - C0 10.000, işlem başı ilk-stop riski 25 USDT (%0.25).
  - Toplam ilk-stop riski tavanı 300 USDT (coin başına bir pozisyon).
  - Canlı kapılar: kaldıraç 10, notional ≤ 2.5×özsermaye, marjin ön-kontrolü.
- **Dönem sonu:** Açık pozisyon, dönemin son günü açılışında kapatılır (PARTITION_END). Sonraki
  dönemin fiyatı kullanılmaz.

## Dönemler, seçim, karar
- **Dönemler:** T0 = 2021-01-01, T1 = son tam UTC günü. [T0, T1) kronolojik %60 / %20 / %20.
- **Seçim ve karar:** `liquidity_sweep_v1.selection` aynen.
  - Örneklem tabanları 100/12/26, 50/8/13, 30/6/13.
  - Haftalık 4 haftalık blok bootstrap, 10.000 tekrar, seed 20261001.
  - Keşiften en fazla 3, doğrulamadan 1 aday.
  - LCB > 0 şartı doğrulama ve finalde.
  - Final previously_examined (2021–2026 bot geliştirmesinde kısmen görüldü), bu yüzden en iyi
    hüküm KANIT YETERSİZ olabilir.
- **Raporlanacak teşhis** (seçime girmez):
  - Büyük yükselişlerin yakalanma oranı.
  - Yıllık ve aylık % büyüme.
  - Maksimum düşüş.
  - %0.25 dışındaki risk seviyelerine ölçekleme.

Sonuç görüldükten sonra hiçbir eşik, N, k, çıkış ya da yön değiştirilmez.
