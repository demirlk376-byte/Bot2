# Mum formasyonları (price action) — ÖN KAYIT (2026-10-18, sonuçlardan ÖNCE)

Kullanıcı isteği: mum analiziyle taktik. Klasik mum formasyonları bu projede sistematik olarak HİÇ test edilmedi
(yalnız NR-N/Crabel). 4h ve 1D'de (maliyetin stop mesafesine göre küçük olduğu yerde) klasik tanımlarla sınanır.

## Veri ve protokol
- `research_data/h4_kirilim_v6/veri/<COIN>_4h.csv` (open_time ms, OHLCV), 1D = 4h'ten UTC gün kapanışıyla.
- Dönem 2020-01-01 → 2025-08-08 (FİNAL kapalı, önceki çalışmalarla aynı).
- SEÇİM evreni: eski 12 (SOL ETH ADA NEAR BCH XRP DOGE TRX XLM LTC ICP BNB).
  SINAV evreni: yeni 26 (LINK AVAX DOT UNI ATOM FIL ETC AAVE ALGO XTZ SAND MANA AXS EGLD RUNE EOS THETA GRT CRV
  HBAR VET APT ARB OP INJ SUI).
- ATR14 (basit TR ortalaması) ve trend bağlamı (kapanış vs SMA50) yalnız formasyon mumunun kapanışına kadar.

## Formasyonlar (klasik tanımlar, klasik yön; G = gövde |C−O|, R = H−L, üst/alt fitil)
1. **Yutan (engulfing)**: önceki mum düşüş, bu mum yükseliş ve gövdesi öncekinin gövdesini tamamen kapsar →
   LONG (ayna: SHORT). Bağlam: LONG için kapanış < SMA50 (düşüş sonrası dönüş); SHORT için > SMA50.
2. **Çekiç / kayan yıldız (pin bar)**: alt fitil ≥ 2·G ve üst fitil ≤ 0.25·R ve G ≥ 0.05·R → LONG, bağlam kapanış
   < SMA50; ayna (üst fitil) → SHORT, bağlam > SMA50.
3. **İç mum kırılımı (inside bar)**: mum t, mum t−1'in aralığı içinde; sonraki mum t−1'in tepesinin üstünde
   kapanırsa LONG, dibinin altında kapanırsa SHORT (giriş kırılım mumundan sonra). Bağlam yok (devam formasyonu).
4. **Sabah / akşam yıldızı**: t−2 güçlü düşüş (G ≥ 0.6·R), t−1 küçük gövde (G ≤ 0.3·R), t yükseliş ve kapanış
   > t−2 gövdesinin ortası → LONG (bağlam < SMA50); ayna → SHORT.
5. **Üç beyaz asker / üç kara karga**: üç ardışık yükseliş mumu, her biri öncekinden yüksek kapanış, her gövde
   ≥ 0.5·R → LONG (devam; bağlam yok); ayna → SHORT.
6. **Marubozu**: G ≥ 0.9·R ve R ≥ 1.5·ATR14 → yön gövde yönü (devam; bağlam yok).

## İşlem
Giriş: formasyonun tamamlandığı mumdan SONRAKİ mumun açılışı. Stop: LONG için formasyon mum(lar)ının en düşüğü
− 0.1·ATR14 (SHORT ayna). Hedef: 2R. Süre: 10 mum sonra kapanışta çık. Mum içinde stop ve hedef birlikte
değerse STOP. Açılış stopun ötesindeyse açılıştan. Aynı coinde aynı formasyon×zaman diliminde tek pozisyon.
Maliyet NORMAL: 1 bp komisyon ×2 + giriş kayması 15.85 bp + çıkış 0.24 bp; STRESS: kayma ×2.
R = (çıkış − giriş)·yön / |giriş − stop| − maliyet/|giriş − stop|.

## Ölçüt (değiştirilmeyecek)
12 test (6 formasyon × {4h, 1D}). Haftalık blok bootstrap (10 000, seed 20261018), Bonferroni alt sınır =
%0.21 persentil.
Bir formasyon×TF **TUTTU** ⇔ (1) SEÇİM evreninde NORMAL ort R > 0, (2) SINAV evreninde NORMAL ort R > 0 ve
STRESS ort R > 0, (3) SINAV Bonferroni alt sınır > 0, (4) SINAV n ≥ 100.
TUTAN olursa ek (karar dışı) rapor: donchian ikiziyle haftalık korelasyon, olay kümelenmesi (aynı mumda kaç coin).
