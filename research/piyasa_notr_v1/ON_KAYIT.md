# Piyasa-nötr düzenli kâr — ÖN KAYIT (2026-10-20, sonuçlardan ÖNCE)

Kullanıcı isteği: "haftalık ya da aylık kâr veren strateji". Yönlü stratejilerin (donchian, trend, momentum) kârı
boğa aylarında patlamalı geliyor; aylık düzenlilik yapısal olarak ancak **piyasa-nötr** (aynı anda long ve short,
piyasa yönü birbirini götürür) stratejilerden beklenebilir. Daha önce denenen piyasa-nötrler: spot–perp funding
toplama (pro_v9 FC, funding_toplama_mexc → yıllık ~%0–2, değmez), coinler arası momentum L/S (pro_v9 XS → ~0).
Bu projede HİÇ denenmemiş üç piyasa-nötr aile burada, parametreler önceden sabit, optimizasyon yok.

## Veri
`veri/listeleme` (Binance USDⓈ-M, delist edilenler dahil 895 USDT perp): `veri/1d/<SYM>.csv` (open_time ms,
OHLCV, quote_volume), `veri/funding/<SYM>.csv` (calc_time ms, last_funding_rate). BTCUSDT hedge bacağı.
Hariç: taban varlığı (sembol − "USDT") sabit coin olanlar {USDC, BUSD, TUSD, FDUSD, DAI, USDP, USDE, PYUSD} ve
endeks perpleri {BTCDOM, DEFI, BLUEBIRD, FOOTBALL}; BTCUSDT yalnız hedge olarak kullanılır (evrende değil).
Hayalet satırlar: hacmi 0 olan gün "işlem yok" sayılır.

## Uygunluk (her karar anı t için, yalnız t'den ÖNCEKİ günlerle)
- t'den önce ≥ 60 günlük mum; son 30 günün medyan quote_volume ≥ 20 000 000 USDT; son 7 günde hacmi 0 gün yok.
- F7 = [t − 7 gün, t) aralığında settlement'ı olan funding oranlarının TOPLAMI (aralıktan bağımsız; ≥ 7 settlement
  şartı).
- Bir karar anında uygun sembol < 30 ise o dönem pozisyon yok (nakit).

## Stratejiler
**C — coinler arası funding carry (L/S, dolar-nötr), haftalık.** Pazartesi 00:00 UTC (günlük mum açılışı) karar
ve işlem. Uygunlar F7'ye göre sıralanır: en yüksek 10 → SHORT, en düşük 10 → LONG. Her pozisyon notional'ı
G/20, G = haftabaşı özsermaye × 1.0 (brüt). Bir sonraki Pazartesi açılışında yeniden dengelenir.

**CH — kalabalık long'ları short'la, BTC ile beta-hedge, haftalık.** Aynı takvim/uygunluk. En yüksek F7'li 10 →
SHORT, her biri G/20. Hedge: BTCUSDT LONG, notional = Σ βᵢ · G/20; βᵢ = son 90 günün günlük log getirilerinde
(kapanış–kapanış, en az 60 gözlem) coinin BTC'ye OLS eğimi, [0.5, 2.0] aralığına kırpılır.

**P — BTC'ye göre artık getiri dönüşü (çift ticaret), günlük.** Her gün 00:00 UTC karar (dünün kapanışına kadar
veri), işlem o günün açılışında. Uygunluk aynı kurallarla günlük. βᵢ yukarıdaki gibi; günlük artık
eᵢ = rᵢ − βᵢ·r_BTC (log, kapanış–kapanış); σᵢ = son 90 günün eᵢ standart sapması; z = (son 3 günün eᵢ toplamı)/(σᵢ√3).
z ≥ +2.5 → coin SHORT + BTC LONG (βᵢ × coin notional); z ≤ −2.5 → coin LONG + BTC SHORT. Coin notional'ı
özsermayenin %2.5'i. Günde en fazla 5 yeni giriş (|z| büyükten küçüğe), en fazla 20 eşzamanlı, coin başına tek
pozisyon. Çıkış: girişten 3 gün sonra o günün açılışında. Stop yok.

## Getiri, funding, maliyet (üçü için ortak)
- Bacak getirisi: long P_çıkış/P_giriş − 1, short tersi. Funding: tutulan her settlement'ta (giriş < s ≤ çıkış)
  long −oran × notional_s öder/alır, short +oran × notional_s; notional_s = ilk notional × (settlement gününün
  açılışı / giriş fiyatı).
- Maliyet işlem gören notional üzerinden (yeniden dengelemede yalnız fark işlem görür; yön değişimi ya da
  çıkış/giriş tamamı): NORMAL 2.5 bp komisyon + 15.85 bp kayma = **18.35 bp**, STRESS 2.5 + 31.7 = **34.2 bp**.
  P'de her işlem coin ve BTC bacağını açılışta ve kapanışta ayrı ayrı öder.
- Veri hafta/tutma içinde biterse (delist ya da hacim 0) pozisyon son hacimli günün kapanışından kapanır; kalan
  süre nakit. Karar gününün mumu yoksa o sembol o dönem işlem görmez.
- Dönem getirisi = dönem PnL / dönem başı özsermaye; aylık getiri = ay içindeki dönemlerin bileşik çarpımı
  (dönem başlangıç tarihinin ayına göre; P'de gün gün).

## Dönemler
KEŞİF: 2021-01-04 → 2023-12-31 başlangıçlı dönemler. DOĞRULAMA: 2024-01-01 → 2026-09-21 (son tam hafta;
P için girişler ≤ 2026-09-26).

## Ölçüt (değiştirilmeyecek; 3 strateji)
Bir strateji **DÜZENLİ** ⇔ hepsi:
1. HER İKİ dönemde NORMAL ve STRESS toplam (bileşik) getiri > 0.
2. DOĞRULAMA'da aylık NORMAL getirilerin ortalaması için ay bootstrap'ı (10 000, seed 20261020) %0.83 persentili
   (tek yönlü %2.5, 3 test Bonferroni) > 0.
3. HER İKİ dönemde NORMAL kârlı ay oranı ≥ %60.
**EKLENİR** ⇔ DÜZENLİ VE 4:
4. Portföy: BASE = canlı düzen (bot ikizi + trend %1.5; `momentum_v2` BASE serileri, ortak sermaye motoru) aylık
   getirisi r_B; birleşik r = r_B + r_X (X yukarıdaki boyutla toplam özsermayeye göre). İki pencerede —
   2023-04 → 2026-06 (bot = `ikiz_gercek.db`) ve 2021-01 → 2023-03 (bot = `ikiz_eski.db`), tam aylar — (a) zararlı ay
   sayısı BASE'den az, (b) son çarpan ≥ BASE, (c) aylık maxDD ≤ BASE + 3 puan.
Aksi halde ELENDİ. DÜZENLİ ama 4'ü geçmeyen "ayrı düzenli, bota eklenmez" diye raporlanır.

Rapor: aylık tablo, kârlı hafta/ay oranı, yıl yıl, en kötü ay, funding ve fiyat katkısı ayrı, ortalama haftalık
devir, BASE ile aylık korelasyon, uygun sembol sayısı. Sınırlamalar: Binance vekil veri (MEXC'de sembol/funding
farklı olabilir); ~250 USDT hesapta 20 bacak MEXC minimum emir büyüklüğüne takılabilir — ayrıca belirtilir.
Sonuç görüldükten sonra hiçbir eşik, sayı, süre, maliyet ya da ölçüt değiştirilmez.

---
## SONUÇ (2026-10-20) — ÜÇÜ DE ELENDİ (piyasa-nötr aileden düzenli aylık kâr çıkmadı)
İki kör uygulama (vektörel / olay döngüsü) aynı hükmü verdi. Farklar yalnız spec'te tanımsız noktalardan: F7
eşitliğinde (çok coin taban oranda, F7 = 0.0021) sıralama, P çıkış maliyetinin hangi güne yazıldığı. Uzlaştırmada B'nin
hayalet gün (hacim 0) getirilerini beta/z'ye katması düzeltildi. A'nın kurallarıyla iki motor her dönemde birebir
aynı (fark < 2e-15). Denetçi 47 kesme testi (gelecek veri yok), elle funding/maliyet/işlem yeniden hesabı yaptı.
Rastgele eşitlik sıralaması (60 tohum), veri delikleri ve delist doldurma duyarlılıklarında da hiçbir hüküm değişmiyor.

| strateji | dönem | toplam NORMAL / STRESS | kârlı ay | aylık ort. | boot. alt (%0.83) |
|---|---|---|---|---|---|
| C funding carry L/S | keşif 2021–23 | +%129 / +%72 | %64 | +%2.6 | — |
| C | doğrulama 2024–26 | −%53 / −%63 | %42 | −%1.4 | −%6.8 |
| CH kalabalık short + BTC | keşif | +%20 / −%0.1 | %53 | +%0.9 | — |
| CH | doğrulama | +%13 / −%1.2 | %52 | +%1.2 | −%4.1 |
| P artık dönüşü | keşif | −%31 / −%44 | %39 | −%1.0 | — |
| P | doğrulama | −%9 / −%28 | %52 | −%0.2 | −%1.9 |

Yıl yıl NORMAL (kârlı ay): C 2021 +96 (9/12) · 2022 −9 · 2023 +28 · 2024 +9 (5/12) · 2025 **−51** (4/12) · 2026 −12.
CH 2021 −24 · 2022 −2 · 2023 +62 · 2024 +58 · 2025 −26 · 2026 −4. P her yıl ~negatif (2024 hariç).
C'nin çöküşü: doğrulamada long bacak (en düşük funding) +%126 funding topladı ama fiyatta −%148 kaybetti; yüksek
funding'li short'lar sıkıştı (ör. MYX 2025-09, ~3 kat). 2021–23'te çalışan carry 2025'te tersine döndü.
Portföy (bilgi amaçlı, ölçüt 4): +C 2023–26 x139 → x70.5 (DD %29 → %46); +CH x139 → x164 ama DD %29 → %50; +P zararlı ay
sayısını azaltmıyor. Hiçbiri 4'ü de geçmiyor. Hüküm: üçü de ELENDİ; bota eklenmez.
