# Yeni listelenen coinleri short'lama — ÖN KAYIT (2026-10-19, sonuçlardan ÖNCE)

Mekanizma (zorunlu akış): yeni listelenen coinlerde erken yatırımcı/airdrop satışı ve kilit açılımları ilk
haftalarda sürekli arz baskısı yaratır. Grafik deseni değil, yapısal akış hipotezi. Bu projede hiç denenmedi.

## Veri
`veri/listeleme` dalı (Binance USDⓈ-M, delist edilenler dahil 895 USDT perp): `veri/1d/<SYM>.csv`
(open_time ms, OHLCV, quote_volume), `veri/funding/<SYM>.csv` (calc_time ms, last_funding_rate).
Listeleme günü L = sembolün ilk günlük mumu. Hariç: adında USDC/BUSD/TUSD/FDUSD/DAI/USDP geçen sabitler, BTC ve
ETH çeşitlemeleri (BTCDOM, ETHBTC vb. — sembolde "BTC"/"ETH" ile başlayan ve ilk mumu 2020 öncesi olanlar),
1000x önekli yeniden listelemeler (1000SHIB gibi) DAHİL (ayrı coin sayılır).

## Kural
- Giriş: L + 3. günün AÇILIŞINDA short (ilk 3 günün kaosu atlanır). L + 3 verisi yoksa işlem yok.
- Varyant **S30**: 30 gün tut, stop girişin %40 üstü. Varyant **S14**: 14 gün tut, stop %25 üstü.
- Stop: günlük yüksek ≥ stop ise stoptan (açılış zaten üstündeyse açılıştan) kapanır. Süre dolunca o günün
  kapanışında kapanır. Veri erken biterse (delist) son kapanıştan kapanır (delist çoğunlukla düşüşle olur —
  bu bir avantaj değil, gerçekçi sonuçtur; ayrıca raporlanır).
- Funding: tutulan her settlement'ta short +oran × notional alır (negatifse öder). Gerçek kayıtlardan.
- Maliyet (notional üzerinden): NORMAL 2×2.5 bp komisyon + giriş 30 bp + çıkış 30 bp = 65 bp; STRESS kayma ×2 → 125 bp.
- R = [ (giriş − çıkış)/giriş + funding_toplamı − maliyet ] / stop_mesafesi (0.40 ya da 0.25).
- Beta düzeltmesi (karar kriteri 4): aynı giriş/çıkış günlerinde BTCUSDT short getirisi (funding'siz, maliyetsiz)
  çıkarılarak "fazla getiri" R'si.

## Dönemler
KEŞİF: L ∈ [2021-01-01, 2023-12-31]. DOĞRULAMA: L ∈ [2024-01-01, 2026-08-15] (çıkış 2026-09-30'a kadar).

## Ölçüt (değiştirilmeyecek; 2 varyant)
Bootstrap: giriş AYI blokları (10 000, seed 20261019), ratio-of-sums; Bonferroni alt = %1.25 persentil.
Bir varyant **KAZANDI** ⇔ HER İKİ dönemde de (1) NORMAL ort R > 0 ve STRESS ort R > 0, (2) DOĞRULAMA'da NORMAL
Bonferroni alt > 0, (3) beta düzeltmeli ort R > 0, (4) n ≥ 50. Aksi halde ELENDİ.
Rapor: kârlı ay oranı, yıl yıl, delist edilenlerin payı ve katkısı, en kötü 10 işlem (short sıkışmaları),
eşzamanlı açık pozisyon sayısı.

---
## SONUÇ (2026-10-19) — S30 ve S14 ELENDİ (S30 zayıf pozitif)
İki bağımsız uygulama + denetçi motoru 1514 işlemde aynı. Denetçinin bulduğu delist sonrası "hayalet satır" sorunu
(hacim 0, düz fiyat) düzeltildi; yalnız 1 işlem değişti, hüküm aynı.

| varyant | dönem | n | ort R NORMAL / STRESS | piyasadan arındırılmış R | Bonf. alt |
|---|---|---|---|---|---|
| S30 (30 gün, %40 stop) | keşif 2021–23 | 182 | +0.048 / +0.033 | +0.136 | −0.130 |
| S30 | doğrulama 2024–26 | 575 | +0.043 / +0.028 | +0.087 | −0.106 |
| S14 (14 gün, %25 stop) | keşif | 182 | −0.073 / −0.097 | −0.019 | −0.233 |
| S14 | doğrulama | 575 | +0.039 / +0.015 | +0.063 | −0.102 |

S30 her iki dönemde pozitif ama kenar küçük ve istatistik olarak sıfırdan ayırt edilemiyor (en iyi 5 işlem çıkınca
keşif +0.002). Eşzamanlı açık pozisyon doğrulamada ortalama 14, en fazla 67 (2026'da tokenize hisse/ETF/emtia
perpleri listelemelerin büyük kısmı). Funding etkisi küçük; işlemlerin ~%32'si net funding ödüyor. Canlıya alınmaz;
istenirse yalnız sinyal (kâğıt) modunda ileriye dönük izlenebilir.
