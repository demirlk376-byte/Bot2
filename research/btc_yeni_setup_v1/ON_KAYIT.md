# BTC için YENİ setup — 4 aday — ÖN KAYIT (2026-10-31, sonuçlardan ÖNCE)

Kullanıcı: "BTC'de yeni bir setup arıyoruz" (BTC'yi mevcut bota eklemek değil). Proje bulguları adayların şeklini
belirliyor: kısa vade maliyet duvarına takılıyor, BTC'nin gün/seans yönü tahmin edilemiyor, CME/Londra/SMC/formasyon
elendi; tutarlı kenar çok günlük trend + oynaklık yönetimi. Burada BTC'ye özgü, çok günlük 4 aday sınanır. 2017-08 →
2019-12 dönemi bu projede hiç kullanılmadı (gerçek dış-örneklem).

## Veri
`scratchpad/btc2017_veri/veri/BTC_spot_1h_2017.csv` ve `BTC_spot_1d_2017.csv` (Binance spot BTCUSDT, 2017-08-17 →
2026-10-28; 28 saatlik boşluk var — boşluklu 4H mum oluşturulmaz). Funding: `scratchpad/btc_veri/veri/BTC_funding.csv`
(2020-01 →; Binance perp 2019-09'da başladı, dosya 2020'den). Funding olmayan dönemde varsayım: taban oran %0.01/8s
(long öder, short alır). Fiyat vekili: spot (2017–2019'da Binance perp yok).
Dönemler: A = sinyal ısınmasından 2019-12-31'e (dış-örneklem); B = 2020-01-01 → 2026-10-28.

## Adaylar (parametreler önceden sabit, optimizasyon yok)
- **S1 — Sade 4H kırılım (rgb4h_v1'deki a′)**: 4H (00/04/…/20 UTC). Long: kapanış > önceki 20 barın en yükseği +
  0.25×ATR14(Wilder) VE kapanış > EMA200(4H); short simetrik. Giriş sonraki bar açılışı; başlangıç stopu giriş ∓ 2×ATR;
  çıkış önceki 10 barın karşı ucu (bar içi dokunuşta o seviyeden, boşlukta açılıştan); etkin stop long için
  max(başlangıç, DC10 alt). Risk %1 özsermaye, kaldıraç tavanı 3x. (Bu varyant rgb4h_v1 sonuçlarına bakılarak seçildi —
  B dönemi onun için bağımsız DEĞİL; karar A'da da tutmasını şart koşar.)
- **S2 — 200 gün ortalama + oynaklık hedefi**: günlük kapanış > SMA200 → long, değilse nakit. Pozisyon büyüklüğü =
  min(1, %40 / RV30) × özsermaye (RV30 = son 30 günün günlük log getiri std × √365). Sinyal değişince ertesi gün
  açılışında giriş/çıkış; pozisyon varken büyüklük her Pazartesi açılışında hedefe ayarlanır.
- **S3 — Haftalık zaman serisi momentumu**: Pazartesi açılışında, son 12 tamamlanmış haftanın getirisi > 0 → long, değilse
  nakit; büyüklük S2'deki gibi min(1, %40 / RV30), haftalık ayar.
- **S4 — Funding ısınması momentumu**: günlük ortalama funding'in son 365 günlük z-skoru (yalnız geçmiş) > 1.5 olduğu günün
  ertesi açılışında 30 gün long (büyüklük S2'deki gibi); pozisyon açıkken yeni sinyal süreyi uzatmaz. Veri yalnız
  2020 →; dönemler A4 = 2021-01-01 → 2023-06-30, B4 = 2023-07-01 → 2026-09-30 (ilk yıl ısınma).
Maliyet: taker %0.05/taraf + kayma 3.5 bp/taraf (her işlem gören notional'da, büyüklük ayarı dahil); funding tutulan her
settlement'ta. STRESS: maliyet 2 kat.

## Ölçüt (değiştirilmeyecek)
Bir aday **İYİ BTC SETUP** ⇔ HER İKİ dönemde de (1) yıllık bileşik getiri (CAGR) > 0, (2) Sharpe (günlük, √365) ≥ 0.5,
(3) MAR = CAGR / maxDD ≥ aynı dönemde BTC al-tut MAR'ı, (4) maxDD ≤ %35 — NORMAL maliyetle; VE STRESS'te iki dönem
CAGR > 0; VE toplam işlem (giriş) ≥ 20. Birden fazla İYİ çıkarsa hepsi raporlanır; canlıya alma ayrı test (bot ile birlikte
portföy katkısı) ve kullanıcı onayı gerektirir.
Rapor: yıl yıl getiri, kârlı ay oranı, en kötü ay, işlem sayısı, ortalama pozisyon büyüklüğü, al-tut kıyası, canlı bot
düzeniyle (BASE) aylık korelasyon (2020-02 → 2026-07).
Sonuç görüldükten sonra parametreler, dönemler, maliyet ve ölçüt değiştirilmez.

---
## SONUÇ (2026-10-31) — S1 İYİ BTC SETUP · S2, S3, S4 DEĞİL
İki kör uygulama aynı hükme vardı; denetçi uzlaştırmadan sonra 499 işlem ve tüm sayılar ~1e-14 aynı (farklar: S1 ısınma
başlangıcı, STRESS'te funding'in de 2 katlanması, gün sonu işaretleme, 2018-02 borsa kesintisinde birkaç saatlik
funding fiyatı — hiçbiri hükmü değiştirmedi). Bağımsız motorla 499 işlem, 20 kesme testi (gelecek veri yok), 3 elle hesap.

| aday | dönem | CAGR | Sharpe | maxDD | MAR (al-tut) | işlem | STRESS CAGR | hüküm |
|---|---|---|---|---|---|---|---|---|
| S1 sade 4H kırılım | A 2017-09 → 2019 | **+%36.1** | **2.07** | **%6.9** | 5.28 (0.37) | 101 | +%33.0 | İYİ |
| | B 2020 → 2026-10 | **+%15.3** | **1.07** | **%10.7** | 1.43 (0.56) | 325 | +%10.5 | |
| S2 200G + vol hedefi | A | +%8.0 | 0.42 | %34.0 | 0.24 (−0.32) | 4 | +%5.7 | DEĞİL |
| | B | +%20.4 | 0.74 | %46.8 | 0.44 (0.56) | 29 | +%11.0 | |
| S3 haftalık momentum | A | +%55.8 | 1.55 | %34.2 | 1.63 (0.12) | 7 | +%50.9 | DEĞİL |
| | B | +%13.1 | 0.54 | %40.7 | 0.32 (0.56) | 19 | +%4.7 | |
| S4 funding ısınması | A4 2021–23/06 | +%8.9 | 0.55 | %19.8 | 0.45 (0.03) | 6 | +%3.5 | DEĞİL |
| | B4 2023/07–26/09 | +%5.5 | 0.37 | %23.3 | 0.23 (0.69) | 8 | +%2.4 | |
S1 yıl yıl: 2017 +11.7 · 2018 +21.6 (al-tut −73) · 2019 +48.9 · 2020 +39.9 · 2021 +3.8 · 2022 +3.0 (al-tut −64) · 2023 +33.2 ·
2024 +18.8 · 2025 +1.1 · 2026 +10.4 — her yıl artı. Kârlı ay %71 (A) / %55 (B); en kötü ay −%2.3 / −%6.0. İşlem başı %1
risk, ortalama maruziyet özsermayenin ~%12–14'ü. Canlı bot düzeniyle aylık korelasyon 0.30 (çeşitlendirici).
Sınırlamalar: 2017–19 spot fiyat vekili ve varsayılan funding; B dönemi S1 için bağımsız değil (rgb4h_v1'den seçildi) —
asıl kanıt A. Canlıya alma: önce bot + S1 portföy katkısı (ayrı ön kayıt) ve kâğıt izleme, sonra kullanıcı onayı.
