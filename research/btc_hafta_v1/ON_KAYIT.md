# BTC'nin hafta içi davranışı: hangi koşulda hangi işlem yapılabilir hareket — ÖN KAYIT (2026-10-24, sonuçlardan ÖNCE)

Kullanıcı isteği: "BTC'nin hafta içinde hangi şartlar altında hangi trade edilebilir hareketleri yaptığını tespit et."
İki parça: (A) BETİMSEL HARİTA (karar dışı): haftanın gün/seanslarında ortalama getiri, isabet, hareket büyüklüğü;
(B) KEŞİF → DOĞRULAMA: koşullu gün/seans hareketlerinden maliyeti yenen ve yeni dönemde tekrar eden var mı?
Ayrıca ünlü "CME boşluğu dolar" inancı (G) ayrı, seçimsiz test edilir. kontrol_v1 dersi: kısa vadede maliyet duvarı
yüksek; burada BTC (en likit) ve maliyet BTC'ye göre, ama yine de net getiri esas.

## Veri
`scratchpad/btc_veri/veri/BTC_fut_1h.csv` (Binance BTCUSDT perp 1h, 2020-01-01 → 2026-10-03, boşluk yok),
`BTC_funding.csv` (gerçek oranlar). Saatler UTC. Bir parça [t1, t2): giriş t1 saat mumunun AÇILIŞI, çıkış t2 saat
mumunun açılışı. Funding: t1 < s ≤ t2 settlement'ları, long öder.
Maliyet (gidiş-dönüş, notional üzerinden): **NORMAL 9 bp** (2×2.5 bp komisyon + 2×2 bp kayma), **STRESS 21 bp**
(2×2.5 + 2×8). Dönemler: KEŞİF parça başlangıcı 2020-03-02 → 2023-12-31 (ısınma için ilk 2 ay atlanır);
DOĞRULAMA 2024-01-01 → 2026-09-30.

## (B) Tarama evreni (sonlu, sabit)
Parçalar (30): her takvim günü 00→24 (Pzt…Paz, 7); HAFTA SONU Cuma 21:00 → Pazar 22:00 (1); HAFTA İÇİ Pzt 00:00 →
Cuma 21:00 (1); HAFTA Pzt 00:00 → sonraki Pzt 00:00 (1); Pzt–Cuma her gün için seanslar ASYA 00–08, AVRUPA 08–13,
ABD 13–21, GEÇ 21–24 (20).
Koşullar (parça başlangıcından ÖNCEKİ veriyle; 14 hücre): HEPSİ · TREND (son kapanmış günlük kapanış > SMA50 günlük:
YUKARI/AŞAĞI) · ÖNCEKİ HAFTA (son tamamlanmış Pzt–Pzt getirisi > 0 / ≤ 0) · HAFTA SONU (son Cuma 21:00 → Pazar 22:00
getirisi > +%1 / < −%1 / arada; parça bu aralıktan sonra başlamıyorsa hücre boş) · OYNAKLIK (14 günlük gerçekleşen
oynaklık, önceki 365 günün medyanından yüksek/düşük) · FUNDING (son 7 gün ortalaması > %0.01/8s / ≤) · ÖNCEKİ GÜN
(son tamamlanmış takvim günü getirisi > 0 / ≤ 0).
Aday = (parça, hücre, yön long/short); yön net getirisi = yön × brüt − maliyet + funding.

## (B) Seçim ve doğrulama (değiştirilmeyecek)
KEŞİF'te n ≥ 40 olan adaylar arasında t = ort. net NORMAL / (std/√n) en yüksek, t ≥ 2.0 ve aynı (parça, hücre)
tekrarı olmayan en fazla **5 aday** seçilir. DOĞRULAMA'da bir aday **TUTTU** ⇔ aynı yönde NORMAL ve STRESS ort. net > 0
VE haftalık blok bootstrap (hafta blokları, 10 000, `default_rng(20261024)`) persentil 2.5/K > 0 (K = seçilen aday
sayısı, Bonferroni) VE n ≥ 30.

## (G) CME boşluğu (seçimsiz, tek test)
CME saatleri America/Chicago (yaz saati dahil): Cuma 16:00 CT kapanış P_F, Pazar 17:00 CT açılış P_S (o saatlerin
1h mumunun açılışı, BTC perp vekil). Boşluk g = P_S/P_F − 1; |g| ≥ %1 ise P_S'de boşluğu dolduracak yönde işlem
(g > 0 short, g < 0 long); hedef P_F; stop girişten |P_S − P_F| kadar ters yönde (1:1); süre sonraki Cuma 16:00 CT.
1h mumda stop ve hedef birlikte → STOP. R = (yön getirisi + funding − maliyet)/(|P_S − P_F|/P_S).
**TUTTU** ⇔ İKİ dönemde de NORMAL ve STRESS ort R > 0 VE DOĞRULAMA haftalık bootstrap %2.5 persentil > 0 VE
DOĞRULAMA n ≥ 30. Rapor: dolma oranı, dolma süresi, yukarı/aşağı boşluk ayrı.

## (A) Harita (karar dışı)
Haftanın 168 saati için: ort. getiri, |getiri| ortalaması, pozitif oran; gün ve seans tabloları; koşul hücrelerine
göre gün getirisi; iki dönem yan yana. Sonuçtan sonra parçalar, koşullar, eşikler, maliyet, seçim sayısı ve ölçüt
DEĞİŞTİRİLMEZ.
