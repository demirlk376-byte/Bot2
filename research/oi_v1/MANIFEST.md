# OI_V1 — açık pozisyon (OI) tabanlı iki yeni kol — ÖN KAYIT (2026-10-04, sonuçlardan ÖNCE)

Envanter (RESEARCH_LEDGER, DURUM, research/*) taramasında HİÇ denenmemiş iki aile. İkisi de breakout
kollarına yapısal olarak ters/bağımsız: zorunlu pozisyon kapanmalarının (tasfiye, short sıkışması)
fiyatı aşırı ittiği ve sonra geri verdiği fikri.

## Veri ve protokol
- Fiyat: Binance USDⓈ-M 4h (`research_data/h4_kirilim_v6/veri`). OI: Binance metrics 1h
  `sum_open_interest` (`research_data/kalabalik/veri`, saatin SON kaydı, `t_kapanis` = saat kapanışı).
- Dönem: [2022-01-01, 2025-08-08) — FİNAL (2025-08-08 sonrası) kapalı, önceki çalışmalarla aynı.
- SEÇİM: eski 12 (SOL ETH ADA NEAR BCH XRP DOGE TRX XLM LTC ICP BNB).
  SINAV: yeni 26 (run_v5.COINS), seçilen TEK varyant dondurulmuş.
- Bir coinde aynı anda tek pozisyon; pozisyondayken gelen sinyal yok sayılır.
- Sinyal 4h kapanışında, giriş SONRAKİ mum açılışında.
- Stop = giriş ∓ 2 × ATR20(4h, sinyal mumunda). Mum içinde stop değerse stoptan çıkış (açılış stopun
  ötesindeyse açılıştan). Aksi halde H mum sonra kapanışta zaman çıkışı.
- R = (çıkış − giriş) × yön / (2 × ATR20) − maliyet/(2 × ATR20).
- Maliyet NORMAL: komisyon 1 bp her bacak; kayma giriş 15.85 bp, çıkış 0.24 bp (önceki çalışmalarla
  aynı). STRESS: kayma ×2.
- İstatistik: işlem başı ortalama R; haftalık toplam R serisi üzerinde 4 haftalık blok bootstrap,
  10 000 tekrar, seed 20261004. LCB = alt sınır. İki aile test edildiği için Bonferroni: LCB = %1.25
  persentil.

## Aile A — TASFİYE ÇAĞLAYANI SONRASI DÖNÜŞ (TC)
- r = mum getirisi (kapanış/önceki kapanış − 1), a = ATR20/önceki kapanış, ΔOI = OI(kapanış)/OI(açılış) − 1.
- LONG: r ≤ −k·a VE ΔOI ≤ −θ (longlar tasfiye edildi). SHORT (varyanta göre): r ≥ +k·a VE ΔOI ≤ −θ.
- Varyantlar: k ∈ {2, 3} × θ ∈ {0.03, 0.06} × H ∈ {3, 6} × yön ∈ {L, LS} = 16.

## Aile B — OI UYUMSUZLUĞU / TÜKENME (OD)
- Fiyat N mumluk yeni zirvede (kapanış > önceki N mumun en yüksek kapanışı) VE aynı N mumda OI
  değişimi ≤ −φ → SHORT (yükseliş yeni long değil short kapanışı). Ayna: yeni dip VE OI ≤ −φ → LONG.
- Varyantlar: N ∈ {20, 40} × φ ∈ {0.0, 0.05} × H ∈ {6, 12} × yön ∈ {S, LS} = 16
  (S = yalnız tepe-short; LS = ikisi).

## Seçim (eski 12, her aile ayrı)
NORMAL ort R > 0, STRESS ort R > 0 ve n ≥ 60 olanlar içinde en yüksek STRESS ort R. Hiçbiri yoksa aile
ELENDİ (sınava gidilmez).

## Sınav (yeni 26)
- **TUTTU:** NORMAL ort R > 0, STRESS ort R > 0, LCB(%1.25) > 0 ve n ≥ 60.
- Ek rapor (karar dışı): yıl yıl ort R, coin dağılımı, canlı donchian işlemleriyle (ikiz) haftalık
  korelasyon.

Sonuç görüldükten sonra k, θ, H, N, φ, stop, maliyet ya da ölçüt DEĞİŞTİRİLMEZ.
