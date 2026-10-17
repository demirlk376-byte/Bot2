# Aylık kâr hedefi durdurması — ÖN KAYIT (2026-10-17, sonuçlardan ÖNCE)

Kullanıcı fikri: hesap bir takvim ayında %10 (ya da %15) kâra ulaşınca o ayın kalanında YENİ işlem
açılmasın (açık pozisyonlar kendi stop/hedef/süre kurallarıyla kapanmaya devam eder).

## Veri
- KEŞİF: gerçek maliyetli ikiz `ikiz_gercek.db` (donchian + mean_rev, squeeze kapalı), 2023-04-07 → 2026-07-18.
- BAĞIMSIZ: aynı ayarlarla `ikiz_eski.db`, girişler < 2023-04-07 (2020-02 → 2023-04).
- R = pnl_usdt / (|entry_price − sl0| × quantity).
- Ek (yalnız keşif): bot + trend kolu (B0, %1 risk) ortak sermaye motoru (`research/trend_gelistirme/birlesik.py`
  mantığı), kural hem bot hem trend girişlerine uygulanır.

## Simülasyon (bot-yalnız, iki dönem)
Başlangıç 1.0; her işlemin riski = giriş anındaki hesap değeri × %3.5; sonuç çıkışta R × risk olarak
eklenir (açık pozisyonların gerçekleşmemiş kârı hesap değerine katılmaz — sınırlama). Ay başı değeri =
o ayın ilk anındaki gerçekleşmiş hesap değeri. Bir işlemin girişinde (ay içi gerçekleşmiş değer / ay başı
değeri − 1) ≥ eşik ise işlem ATLANIR.
- TABAN: kural yok. **H10**: eşik %10. **H15**: eşik %15.

## Ölçüt (değiştirilmeyecek)
Bir varyant İYİ ⇔ HER İKİ dönemde de (i) dönem sonu çarpanı TABAN'dan yüksek VE (ii) ay sonu değerlerinden
en büyük düşüş TABAN'dan en fazla 1 puan kötü. Aksi halde ELENDİ.
Rapor (karar dışı): kuralın tetiklendiği ay sayısı, atlanan işlem sayısı ve atlananların toplam R'si,
yıl yıl çarpan; bot+trend ek sonucu.
