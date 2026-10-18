# Funding toplama (delta-nötr) — MEXC güncel dönem — ÖN KAYIT (2026-10-18, sonuçlardan ÖNCE)

Amaç: kalabalığın kaldıraçlı long için ödediği funding'i, fiyat yönüne bahis girmeden toplamak (spot LONG +
vadeli SHORT, aynı miktar). Kural pro_v9 FC_T1'den DONDURULMUŞ olarak alınır (yeni parametre seçimi yok).

## Veri ve dönemler
- **A (gerçek MEXC oranları)**: `research_data/liquidity_sweep_v1/veri/mexc_funding/<COIN>.csv` (settleTime ms,
  fundingRate), 12 coin (SOL ETH ADA NEAR BCH XRP DOGE TRX XLM LTC ICP BNB), ilk ortak kayıttan 2026-09-30'a.
- **B (uzun vekil, Binance oranları)**: `research_data/h4_kirilim_v6/veri/<COIN>_funding.csv`, 38 coin,
  2023-01-01 → 2026-09-30 (MEXC−Binance farkı ortalama ~0.08 bp/8s, exchange.py notu).

## Kural (FC_T1, dondurulmuş)
- Her Pazartesi 00:00 UTC: son 7 günün settlement ortalaması ≥ 0.0001 (1 bp/8s) olan coinlerden (en az 3
  settlement) ortalaması en yüksek en fazla 6 coin seçilir. Seçili kalan pozisyon dokunulmadan tutulur;
  seçimden düşen kapatılır, yeni giren açılır.
- Pozisyon başına 1.000 USDT notional; sermaye = notional × 1.5 (spot tam + vadeli 2x teminat).
  Getiri, kullanılan değil AYRILAN tüm sermayeye (6 × 1.500 = 9.000) göre hesaplanır (boşta duran dahil).
- Kazanç: tutulan her settlement'ta short perp +oran × notional alır (negatif oranda öder).
- Baz (spot–perp fiyat farkı) MODELLENMEZ (sınırlama, raporlanır); fiyat bacakları birbirini götürür varsayılır.

## Maliyet (her açılış ve her kapanışta, iki bacak, notional üzerinden)
- NORMAL: spot komisyon 5 bp + perp komisyon 2.5 bp + bacak başı kayma 5 bp → işlem başı (açılış ya da kapanış)
  5 + 2.5 + 10 = 17.5 bp.
- STRESS: kayma bacak başı 15.85 bp → 5 + 2.5 + 31.7 = 39.2 bp.

## Ölçüt (değiştirilmeyecek)
Funding kolu **İŞE YARAR** ⇔ HER İKİ dönemde de (1) NORMAL yıllık net getiri (ayrılan sermayeye) ≥ %8
(USDT faiz getirisinin üstü), (2) STRESS yıllık net > 0, (3) kârlı ay oranı ≥ %75. Aksi halde DEĞMEZ.
Rapor: aylık getiri tablosu, en kötü ay, yıl yıl, ortalama kaç coin tutulduğu, işlem (rotasyon) sayısı,
donchian ikizinin aylık getirisiyle korelasyon (B, 2023-04→2026-07).
