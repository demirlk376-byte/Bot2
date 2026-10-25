# Canlı botu iyileştirme: yön / maliyet / asimetri — 5 deney — ÖN KAYIT (2026-10-25, sonuçlardan ÖNCE)

Kaynak: anlama turu (scratchpad/anlama/: canli_kurallar.md, test_envanteri.md ~290 denenmiş filtre, maliyet_anatomisi.md).
Seçilenler daha önce DENENMEMİŞ olanlar. Canlı düzen = donchian (4h, 40 bar kırılım + EMA200, hacim ≥ 2.5×, SL 2×ATR,
TP 2.5R sabit, 120s süre, risk %3.5) + mean_rev (LTC hafta sonu) + trend kolu %1.5. Dönemler: BAĞIMSIZ (onay)
2020-02-01 → 2023-04-06 (`ikiz_eski.db`, girişler < 2023-04-07) · KEŞİF 2023-04-07 → 2026-07-18 (`ikiz_gercek.db`).
Portföy ölçümü (E2/E4/E5/E8): momentum_v2 BASE yöntemi — `trend_gelistirme/birlesik.py` MotorBirlesik, bot işlemleri
R × risk × özsermaye, trend B0 %1.5, MAL NORMAL; aylık seri → çarpan, maxDD, MAR = CAGR/maxDD, en kötü ay.
Hiçbir sonuç canlıya kendiliğinden geçmez: geçen deney önce gölge/kâğıt, sonra kullanıcı onayı.

## E1 — MALİYET: girişi 4h kapanışından 1–2 sn sonra ateşle (şu an medyan +24 sn)
Veri: `veri/maker2` — 2020–23 ikiz donchian sinyallerinin (`ikiz_eski.db`, T < 2023-04-07) [T−60 sn, T+300 sn]
Binance aggTrade'leri. P(t) = t anında veya önceki son aggTrade fiyatı (ma_fikir.py ile aynı). Sinyal başına
kazanç dR = yön × (P(T+24 sn) − P(T+2 sn)) / L / risk, risk = |L − sl0| / L (L = intended_entry).
**GEÇTİ** ⇔ ort dR > 0 VE haftalık blok bootstrap (10 000, `default_rng(20261025)`) %2.5 persentil > 0 VE
ort dR ≥ +0.006R. (Keşif içi ölçüm: +0.0134R [+0.0091, +0.0181], n=412 — bu dönemde bir daha seçim yapılmaz.)

## E2 — BOYUT/YÖN: hacim kapısı bağımsız dönemde gerçekten işe yarıyor mu?
İkiz yeniden koşusu, yalnız env farkı: A0 = canlı (mevcut DB'ler) · A1 = DONCHIAN_VOL_MULT=0 · A2 = VOL 0 ve donchian
riski × k, k = (A0 donchian işlem sayısı / A1 donchian işlem sayısı) KEŞİF'te; k dondurulur, BAĞIMSIZ'da aynen.
Ortam: gerçek maliyetli ikiz env'i (SQUEEZE_ENABLED=false, PAPER_SLIP_GIRIS_BP=15.85, PAPER_SLIP_CIKIS_BP=0.24,
PAPER_FUNDING=true, PAPER_MAKER_DOLUM=0.66, TAKER_FEE_RATE=0.00025). Önce A0 yeniden kurulup mevcut DB ile birebir
olduğu doğrulanır. Bir kol **BENİMSENİR** ⇔ İKİ dönemde de MAR > A0, çarpan ≥ A0, maxDD ≤ A0 + 3 puan. İkisi de geçerse
iki dönem MAR'larının geometrik ortalaması yüksek olan.

## E4 — YÖN: donchian'a ETH günlük SMA200 rejim kapısı (trend kolunun kuralı)
Long yalnız ETH son tamamlanmış günlük kapanışı > SMA200 (günlük kapanış) iken, short yalnız altındayken; rejim
bilinmiyorsa (veri < 200 gün) serbest. ETH günlük = `research_data/h4_kirilim_v6/veri/ETH_4h.csv` UTC günlüğe.
**GEÇTİ** ⇔ İKİ dönemde de (a) ort R(çelişen) − ort R(uyumlu) ≤ −0.15 VE (b) çelişenler çıkarılınca portföy MAR'ı
BASE'ten yüksek VE aynı sayıda rastgele işlem silmenin (2000 tekrar, `default_rng(20261025)`) %95 persentilinden yüksek.

## E5 — YÖN: "OI artıyorsa kırılım gerçek" (defterde 2026-09'da önceden yazılmış hipotez, L4182-4185)
dOI = OI(T'de veya önceki son kayıt) / OI(T−4s'de veya önceki son kayıt) − 1, Binance metrics sum_open_interest
(`research_data/kalabalik/veri/<COIN>_metrics_1h.csv.gz`, 2022-01 → 2026-01). Kural: dOI ≤ 0 olan donchian sinyali atlanır.
İşlemler: `ikiz_eski.db` 2022-01-01 → 2023-04-06 ve `ikiz_gercek.db` 2023-04-07 → OI verisinin sonu.
**GEÇTİ** ⇔ İKİ dönemde de ort R(artan) − ort R(artmayan) > 0 VE birleşik haftalık blok bootstrap %95 aralığı farkta
0'ı dışlıyor VE kurallı portföy MAR'ı iki dönemde de BASE'ten yüksek (dönemler OI verisiyle kısıtlı).

## E8 — ASİMETRİ: süre dolunca kârdaki işlemi kapatma, iz süren stopa devret
120 saatte açıklanmamış kâr ≥ +1.0R (sinyal kapanışı ve sl0'a göre) ise kapatma: TP 2.5R kalır, stop =
max(mevcut SL, girişten beri en yüksek 4h kapanış − 2×ATR14(4h)) (short ayna), her 4h kapanışta yalnız sıkılaşır;
en geç 240 saatte kapat. Diğer işlemler değişmez. 1h mumlarla yeniden simülasyon (2023–26 `canli_wt/data` MEXC,
2020–23 `eski_kos/data` Binance); aynı mumda SL ve TP → SL; çıkış kayması 0.24 bp.
**GEÇTİ** ⇔ İKİ dönemde de tüm donchian işlemleri üzerinde Σ dR > 0 (haftalık blok bootstrap tek yönlü p < 0.10) VE
portföy çarpanı ≥ BASE VE en kötü ay BASE'ten kötü değil.

Sonuç görüldükten sonra hiçbir kural, eşik, dönem, seed veya ölçüt değiştirilmez. Çoklu deney: her biri iki dönemde
birden geçmek zorunda; geçenler canlıya gitmeden önce gölge/kâğıt izlemeye alınır.
