# Tasfiye haritası (liquidation magnet) — ÖN KAYIT (2026-10-18, sonuçlardan ÖNCE)

Kullanıcı isteği: "likidite" ile aylık kâr. Kripto traderlarının "likidite haritası" (Coinglass liquidation heatmap)
fikri: birikmiş tasfiye seviyeleri fiyatı çeker. Bu projede hiç denenmedi (önceki "likidite" testleri stop avı /
emir defteri / hacim idi). Harita, kamu verisinden YAKLAŞIK modellenir; model varsayımları aşağıda sabittir.

## Veri
- Fiyat: `research_data/h4_kirilim_v6/veri/<COIN>_4h.csv`.
- OI ve taker oranı: `research_data/kalabalik/veri/<COIN>_metrics_1h.csv.gz` (t_kapanis ms = saat kapanışı,
  sum_open_interest [coin], sum_taker_long_short_vol_ratio = alıcı/satıcı taker hacim oranı). Saatin son kaydı.
- Dönem: girişler 2022-03-01 → 2025-08-08 (OI verisi 2022-01'de başlıyor; 2 ay ısınma). FİNAL kapalı.
- SEÇİM: eski 12; SINAV: yeni 26 (mum_formasyon_v1 ile aynı listeler; ICP/APT/ARB/SUI vb. verisi olduğu yerden).

## Harita modeli (her coin, her 4h mum sonunda güncellenir; yalnız o ana kadarki veri)
- Mum t'de ΔOI = OI(mum kapanışı) − OI(mum açılışı) (1h metrics'ten, mum sınırlarındaki saat kapanışları).
- ΔOI > 0: yeni pozisyon fiyatı P = (H+L+C)/3. Long payı = r/(1+r), r = mum içindeki 4 saatlik taker oranlarının
  ortalaması (r yoksa 1). Kaldıraç kademeleri ve ağırlıkları SABİT: 10x %40, 25x %40, 50x %20.
  Her kademe L için: long tasfiye seviyesi P·(1 − 1/L), short tasfiye seviyesi P·(1 + 1/L); kütle = ΔOI·P (USDT)
  × pay × ağırlık.
- ΔOI < 0: tüm açık kümeler kütleleriyle orantılı olarak |ΔOI·P| kadar azaltılır (kapanan pozisyonlar).
- Fiyat bir kümenin seviyesine değdiğinde (long kümesi: mum düşüğü ≤ seviye; short kümesi: mum yükseği ≥ seviye)
  küme silinir (tasfiye oldu). 30 günden eski kümeler silinir.

## Sinyal ve işlem
- Mum t kapanışında, kapanış fiyatı C'den uzaklığı %2–%10 arası olan kümeler: S_üst = yukarıdaki short tasfiye
  kütlesi, L_alt = aşağıdaki long tasfiye kütlesi. Dengesizlik I = (S_üst − L_alt)/(S_üst + L_alt).
- Toplam (S_üst + L_alt), o coinin son 90 günlük (yalnız geçmiş) dağılımında ≥ %80 persentil olmalı.
- I ≥ +0.5 → LONG (fiyat yukarıdaki short tasfiyelerine çekilir); I ≤ −0.5 → SHORT.
- Hedef: baskın taraftaki kümelerin kütle ağırlıklı ortalama seviyesi. Stop: giriş ∓ 1.5·ATR14(4h).
  Hedef/stop mesafe oranı < 1 ise işlem yok. Giriş sonraki mumun açılışı; mum içinde stop ve hedef birlikte →
  STOP; süre 18 mum (3 gün) sonra kapanışta çık. Aynı coinde tek pozisyon.
- Maliyet: NORMAL 1 bp ×2 + giriş kayması 15.85 bp + çıkış 0.24 bp; STRESS kayma ×2. R tanımı mum_formasyon_v1 ile aynı.

## Ölçüt (değiştirilmeyecek; tek test)
Haftalık blok bootstrap (10 000, seed 20261018).
**TUTTU** ⇔ (1) SEÇİM NORMAL ort R > 0, (2) SINAV NORMAL ve STRESS ort R > 0, (3) SINAV %2.5 persentil > 0,
(4) SINAV n ≥ 100. Rapor: kârlı ay oranı, aylık R toplamları, long/short, yıl yıl, coin coin; TUTARSA donchian
ikiziyle korelasyon.

---
## SONUÇ (2026-10-18) — TUTMADI
İki bağımsız uygulama (numpy / düz liste) işlem işlem aynı (502 işlem). Harita denetimi: eklenen kütle = ΔOI·P
birebir, gelecek veri yok (kesme testi 0 fark).

| evren | n | ort R NORMAL | ort R STRESS | %2.5 / %97.5 | kârlı ay |
|---|---|---|---|---|---|
| eski 12 (seçim) | 141 | −0.029 | −0.062 | −0.21 / +0.15 | 21/42 |
| yeni 26 (sınav) | 361 | −0.010 | −0.044 | −0.15 / +0.14 | 18/42 |

Sinyallerin %85'i short (taker oranı çoğunlukla > 1 → aşağıda daha çok long tasfiyesi) ve short taraf kaybediyor;
küçük long tarafı pozitif (eski12 +0.15, yeni26 +0.14, n=22/58) ama seçimde de istatistik gücü yok. Yıl yıl işaret
değişiyor. OI=0 veri deliklerini ham sayan duyarlılıkta da hüküm aynı. Tasfiye haritası mıknatısı bu modelle kenar
vermiyor.
