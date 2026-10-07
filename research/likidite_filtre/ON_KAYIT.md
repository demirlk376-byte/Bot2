# Likidite filtresi (donchian girişleri) — ÖN KAYIT (2026-10-07, sonuçlardan ÖNCE)

Soru (kullanıcı): "likidite" donchian'a filtre olarak kullanılabilir mi?

## Veri (değişmez)
- KEŞİF: gerçek maliyetli ikiz `ikiz_gercek.db` (giriş kayması 15.85bp, çıkış 0.24bp, komisyon 2.5bp,
  funding açık, maker dolum %66, squeeze kapalı), donchian işlemleri, girişler 2023-04-07 → 2026-07-18.
  Fiyat/hacim: `canli_wt/data/<COIN>_fut_1h.csv` (MEXC 1h; ts = mum AÇILIŞI, UTC).
- BAĞIMSIZ: aynı ayarlarla `ikiz_eski.db`, donchian girişleri < 2023-04-07 (2020-02 → 2023-04).
  Fiyat/hacim: `eski_kos/data/<COIN>_fut_1h.csv` (Binance 1h, aynı biçim).
- Emir defteri: `research_data/kalabalik/veri/<COIN>_bookdepth_5m.csv.gz` (t_kapanis ms, imb1 = ±%1
  bandında (alış−satış)/(alış+satış), 5 dk'nın son anlığı), 2023-01-01 → 2026-01-08.
- İşlem R = pnl_usdt / (|entry_price − sl0| × quantity) (sl0 strategy_scores içinde).
- Giriş anı E = entry_time (4h kapanışı). E'de bilinen 1h mumlar: ts + 1h ≤ E. GELECEK VERİ YASAK.

## Filtreler (yalnız atlama; atlanmayan işlemler aynen kalır)
- **L1 piyasa likiditesi**: günlük nakit hacim q_d = Σ(volume × close) UTC günü başına (yalnız tam
  günler, E'den önce biten). LQ = son 7 tam günün ort q_d / ondan önceki 90 tam günün medyan q_d
  (en az 60 gün veri; yoksa filtre uygulanmaz, işlem kalır).
  - **L1a**: LQ < 1.00 ise atla. **L1b**: LQ < 0.75 ise atla.
- **L2 emir defteri**: s = imb1 × yön (long +1, short −1), E'den önceki son kayıt (t_kapanis ≤ E, en
  fazla 15 dk eski; yoksa filtre uygulanmaz).
  - **L2a**: s < 0 ise atla. **L2b**: s < −0.10 ise atla.

## Ölçüt (değiştirilmeyecek)
Hesap: işlem başı %3.5 risk, çıkış sırasına göre bileşik; ay sonu değerlerinden en büyük düşüş (maxDD).
- **L1 (iki dönem)**: İYİ ⇔ HER İKİ dönemde de (i) ΣR filtreli > ΣR taban VE (ii) maxDD filtreli ≤
  maxDD taban + 1 puan.
- **L2 (yalnız keşif, 2023-04-07 → 2026-01-08 girişleri)**: İYİ ⇔ keşifin iki yarısında da
  (girişler < 2024-09-01 ve ≥ 2024-09-01) ΣR filtreli > ΣR taban VE tüm L2 penceresinde maxDD
  filtreli ≤ taban + 1 puan. Tek dönem olduğu için "İYİ" en fazla "zayıf kanıt" sayılır.
- Atlanan işlemlerin ort R'si ve haftalık blok bootstrap %95 aralığı raporlanır (karar dışı).
- Teşhis (karar dışı): LQ ve s beşte birlik dilimlerine göre ort R.

## Sınırlama
İkiz işlemlerinden sonradan süzme: atlanan işlemin boşalttığı koltuğa girebilecek başka sinyaller
modellenmez (koltuk tavanı 7; donchian nadiren takılıyor).
