# TREND_GELİŞTİRME B0–B3 — önceden kayıt (2026-10-04, sonuçlardan ÖNCE)

**Kaynak:** kullanıcı görevi (B0 düzeltilmiş taban; B1 4H→günlük devir; B2 ETH filtresi piramitte;
B3 başarısız kırılımdan erken çıkış). Yalnız dört varyant; kombinasyon, eşik taraması ve yeni filtre YOK.
Canlı bot, .env, süreçler ve emirler değiştirilmez.

## Sabitler (sonuçlardan önce)

**Evren**
- Botun canlı coinleri: SOL ETH ADA NEAR BCH XRP DOGE TRX XLM LTC ICP BNB.
- **Bu coinler ÖNCEDEN İNCELENMİŞTİR.** Trend parametreleri bu coinlerde seçildi; "görülmemiş" sayılmaz.
- İkincil kontrol: 24 coin (LINK … SUI). Bunlar da V5/V6'da incelendi; "görülmemiş" sayılmaz.

**Veri ve dönemler**
- Veri: Binance USDⓈ-M 4h mum + fundingRate (`veri/trend4h` dalı, sha256 koşu manifestinde).
  Günlük mumlar 4h'den UTC günü olarak kurulur (tam 6 mum). MEXC güncel sözleşme metadatası.
- Isınma: veri başından itibaren göstergeler hesaplanır. Coin, ilk mumundan 200 gün sonra işlem görebilir.
- Dönemler: KEŞİF 2021-01-01 → 2024-06-14, DOĞRULAMA 2024-06-14 → 2025-08-08.
- Tek sürekli koşu 2021-01-01 → 2025-08-08; dönem sonuçları ortak zamanlı hesap değerinden ölçülür.
- **FİNAL (2025-08-08 →) AÇILMAZ.** Not: eski 12 coinin final yılı bir korelasyon ölçümünde yıl düzeyinde
  görülmüştü (FINAL_IHLAL_NOTU.md); yine de burada kullanılmaz.

**Sermaye ve risk**
- Sermaye C0 = 10.000 USDT.
- Risk: işlem başı (ilk giriş ve her ek) son kapanıştaki hesap değerinin %1'i, giriş/ek anındaki stopa göre.
- Açık trend riski tavanı %24.
- Pozisyon başına notional ≤ 2.5 × hesap değeri.
- Sözleşme adımına aşağı yuvarlama; MEXC minimum emri.

**Teminat**
- İzole; lot teminatı = notional × max(1/10, 1.5 × stop% + 0.005). Tasfiye fiyatı stopun 0.5 stop mesafesi
  altında olacak kadar ek teminat; canlı trend_canli.py kuralının karşılığı.
- Toplam teminat ≤ 0.95 × hesap değeri. Aşarsa giriş/ek atlanır ve kaydedilir.

**Maliyet**
- NORMAL: komisyon 1bp/taraf; giriş kayması 15.85bp; çıkış kayması 0.24bp; fiyat aleyhe tick'e yuvarlanır.
- STRESS: kaymalar ×2.
- Funding: gerçek Binance oranları, pozisyon açıkken (t, t+4h] settlement'larına mum açılış fiyatıyla.

**Yürütme**
- Sinyal kapanışta bilinir; dolum aynı coinin bir sonraki 4h mum açılışında.
- Mum içi stop: açılış stopun altındaysa açılıştan, değilse dokunuşta stop fiyatından.
- Çıkış kârı, aynı mumun açılışındaki boyutlamada kullanılmaz. Boyutlama önceki kapanıştaki hesap değeriyle.

**Ortak saat ve sıra:** Her 4h adımında sırasıyla:
1. Açılış: boşluk stopu → bekleyen çıkış → bekleyen ek → bekleyen giriş (coin adına göre sıralı).
2. Mum içi stop.
3. Funding.
4. Kapanış: 4H pozisyon yönetimi.
5. Gün sonunda (kapanış 00:00 UTC): 1D pozisyon yönetimi ve B1 devri.
6. Yeni sinyaller (önce 1D, sonra 4H).
7. Hesap değeri kesiti.

Coin başına tek trend pozisyonu: iki modül çakışmaz. Bekleyen giriş varken diğer modül sinyal üretmez.
ETH rejimi (son tamamlanmış UTC günü ETH kapanışı > SMA200) bilinmiyorsa yeni giriş YOK.

## Hüküm sınıfları (B0'a karşı, DOĞRULAMA döneminde)
- **A)** Getiri ve getiri/MDD ikisi de iyileşiyor (NORMAL ve STRESS).
- **B)** MDD azalıyor, getiri düşüyor.
- **C)** Getiri ve getiri/MDD ikisi de kötüleşiyor, ya da MDD artıyor ve getiri düşüyor.
- **D)** Etkilenen işlem < 10 ya da sonuç keşif ile doğrulama arasında ters yönde.

Sonuçtan sonra eşik, kural ya da dönem değiştirilmez.
