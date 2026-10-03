# PRO_V9 — önceden kayıt (2026-10-03, sonuçlardan ÖNCE)

İki profesyonel strateji: coinler arası momentum (XS) ve funding toplama (FC).
Protokol öncekilerle aynı:
- eski 12 coinde varyant seçimi, yeni 24 coinde dondurulmuş sınav;
- dönem [2021-01-01, 2025-08-08);
- FİNAL kapalı;
- veri: Binance günlük + funding; dışlanan coinler V5 ile aynı.

## Ortak
- **Yeniden dengeleme:** haftalık, her Pazartesi 00:00 UTC açılışında, o anda bilinen bilgiyle.
- **Birim:** 25 USDT (C0 = 10.000'in %0.25'i). Getiriler basit (bileşiksiz), C0'a göre %.
- **İstatistik:** haftalık net PnL (birim cinsinden), 4 haftalık blok bootstrap, 10.000 tekrar,
  seed 20261001. LCB = haftalık ortalamanın %2.5 alt sınırı.

## XS — coinler arası momentum
- **Uygun coin:** listelenmeden 200 gün geçmiş, sinyal ve işlem günü verisi olan.
- **Sinyal:** dengeleme gününden önceki son kapanışa kadar L günlük getiri.
- **Pozisyonlar:** en iyi ⌊%25 × uygun sayısı⌋ (en az 1) coin long. LS modunda en kötü aynı sayıda coin short.
- **Boyut:** volatilite paritesi. Notional = 25 / (2 × ATR20%), ATR20% = ATR20 / önceki kapanış.
  Pozisyon miktarı (coin adedi) dengeleme açılışında sabitlenir.
- **Maliyet:** değişen notional üzerinden 1bp komisyon. Kayma, mutlak pozisyon artarken 15.85bp,
  azalırken 0.24bp. STRESS'te kayma ×2.
- **Funding:** gerçek oran, long öder ve short alır. Günün açılış fiyatıyla.
- **Varyantlar:** `XS_L{28|56}_{LS|L}` (4 adet).
- **Seçim (eski 12):** NORMAL ve STRESS > 0 olanlar içinde en yüksek getiri/MDD.

## FC — funding toplama (delta-nötr: spot long + perp short, aynı miktar)
- **Sinyal:** son 7 günün funding settlement ortalaması ≥ θ (en az 3 settlement). En yüksek 6 coine kadar.
- **Pozisyon:**
  - 1.000 USDT notional;
  - perp kısa bacak 2x kaldıraç (500 USDT marjin), yani pozisyon başı 1.500 USDT sermaye;
  - 6 × 1.500 = 9.000 ≤ C0.
  - Seçilmeye devam eden pozisyon tutulur, işlem yapılmaz.
- **Kazanç:** short perp funding'i alır (+oran × notional; negatif oranda öder). Fiyat bacakları
  birbirini götürür. Baz (spot–perp farkı) MODELLENMEDİ (varsayım, raporlanır).
- **Maliyet (giriş ve çıkış, iki bacak):**
  - perp: 1bp komisyon + kayma;
  - spot: 10bp komisyon + kayma;
  - kayma: giriş 15.85bp, çıkış 0.24bp. STRESS'te kayma ×2.
- **Varyantlar:** `FC_T{1|2|3}` → θ = 0.0001 / 0.0002 / 0.0003 (8 saatlik oran).
- **Seçim (eski 12):** STRESS > 0 olanlar içinde en yüksek NORMAL getiri.

## Sınav (yeni 24, seçilen tek varyant, her strateji ayrı)
- **TUTTU:** NORMAL > 0, STRESS > 0 ve LCB > 0.
- **Sepete katkı:** trend paketi P (V8) + strateji birleşik hesabında getiri/MDD, P tek başına
  oranından yüksek. Teşhis olarak üçünün birlikte sonucu da raporlanır.

Sonuç görüldükten sonra L, oran, θ, maliyet ya da ölçüt değiştirilmez.
