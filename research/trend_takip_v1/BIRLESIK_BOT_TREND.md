# Canlı bot ikizi + trend paketi birleşik tahmin (teşhis, 2026-10-03)

- **Betik:** `birlesik_bot_trend.py` (`PYTHONPATH=. python3 ...`).
- **Girdi:** canlı-birebir ikiz işlemleri (`ikiz_y_taban_islemler.csv`, 936 işlem), trend paketi
  T1 + H4 + ETH200 + piramit.
- **Pencere:** 2023-04-07 → 2025-08-08 (29 ay). FİNAL dönemi kullanılmadı.
- **Yöntem:** işlem kapanışı sırasıyla bileşik, her işlem getirisi = R × risk.
  - Eşzamanlı pozisyonlar ve marjin modellenmedi.
  - Bot-tek sonucu bu yöntemle aylık %14.6 / DD %35. Resmi ikiz ölçümü aylık %10–13 / DD %37–46.
    Yani yöntem ~2–4 puan iyimser.

| bot riski | trend riski | trend evreni | aylık ort. | en kötü ay | maxDD (kapanış) |
|---|---|---|---|---|---|
| %3.5 | — | — | %14.6 | −15.2 | %35.0 |
| %3.5 | %1.0 | diğer 24 coin (dürüst) | %16.8 | −20.7 | %39.4 |
| %3.5 | %1.0 | botun 12 coini (seçim kümesi, iyimser) | %23.0 | −17.7 | %35.3 |
| %3.5 | %2.0 | diğer 24 coin | %18.6 | −30.0 | %46.3 |

Trend tek başına bu 29 ayda zayıf bir dönem geçirdi (2021 boğası pencerede yok): diğer 24 coinde
%0.25 riskle aylık %0.5.

## Düzeltme: giriş anı bakiyesiyle bileşik (`birlesik_aylik_giris_bazli.py`)

Yukarıdaki "kapanış sırasıyla bileşik" yöntemi, aynı anda açık işlemler birlikte kapandığında kârı
şişiriyordu: bir işlemin kârı, kendisinden sonra açılmamış ama ondan önce kapanmış işlemlerin
kârıyla büyümüş bakiyeye uygulanıyordu. Doğru yöntem: risk tutarı işlemin AÇILDIĞI andaki
gerçekleşmiş bakiyeden hesaplanır.

**Kalibrasyon:** bot tek başına bu yöntemle aylık %12.5, maxDD %45.1. Resmi ikiz ölçümü aylık
%10–13, DD %37–46. Yöntem resmi ölçümle uyumlu.

| | aylık geo | maxDD | 2023 (Nis–Ara) | 2024 | 2025 | 2026 (Oca–18 Tem) |
|---|---|---|---|---|---|---|
| bot %3.5 | %12.5 | %45.1 | +604% | +163% | +354% | +33% |
| bot %3.5 + trend %1 (botun 12 coini) | %16.0 | %45.1 | +674% | +641% | +404% | +33% |

Trend kısmı seçim kümesinde (iyimser). 2026'daki trend ayları eski 12 coinin FİNAL dönemine düşüyor
(bkz. FINAL_IHLAL_NOTU.md). İkiz verisi 2026-07-18'de bitiyor.

## ⚠ Netted kısıtı: önceki birleşik tahmin iyimserdi (2026-10-03)

RESEARCH_LEDGER (2026-09-14) ölçmüştü: MEXC'te bir sembol = bir net pozisyon (execution.py). Trend
kolu botun coinlerini haftalarca tutarsa botun o coindeki işlemleri engellenir. Ledger ölçümüne göre
botun işlemlerinin %12.5'i, getirisinin %19.6'sı. Yukarıdaki "botun 12 coini" satırları bunu
modellemiyor; gerçekte o kurulum net NEGATİF olabilir.

**Çakışmasız kurulum:** trend yalnız botun İŞLEM YAPMADIĞI 24 coinde. Coin başına tek pozisyon
(1D ve 4H modülleri arasında ilk açılan kazanır). Giriş-anı bileşik, 2023-04 → 2025-08-08,
FİNAL dışı (`birlesik_ayri_coin.py`):

| | aylık geo | maxDD | en kötü ay |
|---|---|---|---|
| bot %3.5 | %13.5 | %35.2 | −16.4 |
| + trend %1.0 (24 ayrı coin) | %14.5 | %40.2 | −21.4 |
| + trend %1.5 | %14.6 | %43.9 | −25.2 |
| + trend %2.0 | %14.6 | %47.5 | −30.8 |

**Sonuç:**
- Bu pencerede trend eklemek, riski artırmaya denk. Getiri/MDD oranı 0.38'den 0.36'ya iniyor.
- Pencerede 2021 tipi güçlü altcoin boğası yok; trendin asıl değeri orada olurdu. Ama botun ikizi
  2023-04'ten önceye gitmediği için o dönem birlikte ölçülemiyor.

## "Kısıtı kaldır": ayrı alt hesap senaryosu (2026-10-03)

Netted kısıtı borsa kuralı; kodla kapatılamaz. Tam kaldırmanın yolu, trendi ayrı bir MEXC alt
hesabında çalıştırmak. Ama o zaman sermaye bölünür ve trend kendi hesabının bakiyesine göre risk alır.
- **Pencere:** 2023-04 → 2025-08-08.
- **Trend:** 36 coin, coin başına tek pozisyon.
- **Betikler:** `birlesik_kisitsiz.py` (tek bakiye varsayımı, ulaşılamaz üst sınır) ve
  `birlesik_iki_hesap.py` (gerçekçi iki hesap).

| kurulum | aylık geo | maxDD |
|---|---|---|
| bot tek, %100 sermaye | %13.5 | %35.2 |
| tek bakiye + trend 36 coin %1 (üst sınır; aynı hesapta netted yüzünden ULAŞILAMAZ) | %17.6 | %40.5 |
| alt hesap %20 (hesap içi risk %5), dengelemesiz | %12.8 | %33.9 |
| alt hesap %30 (hesap içi risk %3.3), dengelemesiz | %12.5 | %32.9 |
| alt hesap %20, AYLIK dengeleme (elle transfer) | %15.2 | — |
| alt hesap %30, AYLIK dengeleme | %14.2 | — |

- Trend alt hesabının kendi düşüşü %69–85 (hesap içi risk %3.3–5).
- Dengelemesiz kurulum, bot tek başına kalmaktan KÖTÜ.

Aynı hesapta, botun kullanmadığı 24 coinde ayrı süreç (çakışmasız) en verimli kurulum:
aylık %13.5 → %14.5, maxDD +5 puan. Modellenmeyen ek maliyet: trend pozisyonlarının teminatı
botun teminat ön-kontrolünü (%95 serbest teminat) daraltıp bazı bot girişlerini engelleyebilir.

## Çakışma türleri ve çözüm tasarımlarının değeri (`birlesik_cakisma.py`, 2026-10-03)

Botun canlı kodunda ONE_PER_SYMBOL kuralı (execution.py) iki sebeple var:
- (a) MEXC'te pozisyon başına tek "ekli" stop olur; ikinci kolun girişi birincinin stopunu ezer.
- (b) Tek yönlü modda long ve short aynı anda tutulamaz.

Botta çoklu-kol stop yeniden kurma (`resync_symbol_stops`) ve hedge-farkında mutabakat
(`HEDGE_AWARE_RECON`, varsayılan kapalı) altyapısı zaten var.

**Çakışma sayımı:** 2023-04 → 2025-08-08, botun 684 işlemi. Trend (botun 12 coini) açıkken açılan
bot işlemi: aynı yön (long) 85, ters yön (short) 30.

Trend %1, giriş-anı bileşik:

| tasarım | bot işlem | trend işlem | aylık | maxDD |
|---|---|---|---|---|
| bot tek | 684 | — | %13.5 | %35.2 |
| D0 bugünkü kural (coin başına tek, ilk gelen) | 611 | 103 | %14.4 | %41.5 |
| D1 hedge modu (yalnız ters yön serbest) | 640 | 104 | %15.4 | %39.2 |
| D3 hedge + aynı bacakta ayrı stoplu çoklu kol | 684 | 140 | %17.7 | %35.5 |

D3, ilk testteki sonuç. Gerektirdikleri:
1. Hesabı hedge moduna almak.
2. Aynı bacaktaki kollar için miktara özel plan-emir stopları. Bunlar 24 saat/7 gün geçerli;
   yenileme gerekir.
3. Trendin geniş stopu için teminat düzeni (izole 10x tasfiye mesafesi ~%9.5 < trend stopu).
   Çapraz teminat ya da ek teminat.
4. Trend kollarını botun MAX_POSITIONS ve aynı-yön kapılarından muaf tutmak.

Trend kısmı bu coinlerde seçildiği için D3 rakamı iyimser.

## Canlı hesap bulguları (2026-10-03, `trend_hazirlik/mexc_hedge_kontrol.py` VPS çıktısı)

- **Pozisyon modu = 1 → HEDGE (çift yönlü).** MEXC belgesine göre 1 = hedge, 2 = tek yönlü. Mod değiştirmeye
  gerek yok. Hedge modda long ve short bacakların kaldıraçları birbirinden bağımsız.
- **Bot .env:** izole, 10x. O an açık pozisyon 0. USDT toplamı ≈ 309.
- **ccxt 4.5.84 notu:** `hedged=True` yolunda kapanış yön kodları ters eşleniyor
  (buy+reduceOnly → 4, oysa MEXC'te 4 = long kapat). Bot bu yolu kullanmıyor; açık yön kodlu varsayılan yol
  (1/2/3/4 doğru) hedge hesapta da çalışıyor. Trend kodu da `hedged=True` KULLANMAMALI.
- **Küçük hesapta minimum emir** (`kucuk_hesap_min_emir.py`): 309 USDT, trend riski %1. Bugünkü
  MEXC minimum emir tutarları, tipik trend notional'ının altında:
  - 1D modülü 36 coinin 35'inde, 4H modülü 36'sının 36'sında açılabilir; yalnız ETH 1D açılamaz.
  - 2021-01 → 2025-08 motor koşusunda botun 12 coininde getiri 10.000 USDT hesapla aynı
    (+%389 / +%381, basit, %1).
  - Diğer 24 coinde adım yuvarlaması getiriyi düşürüyor (+%174 / +%227).

**Adım 2 (minik gerçek emirle borsa davranışı denemesi)** yazılmadı. Gerçek emir gönderen betik yazmak
oturumun güvenlik denetimince engellendi; kullanıcının açık izni gerekiyor.

## Adım 2 sonucu: minik gerçek emirle MEXC davranışı (2026-10-03, VPS, DOT, `trend_hazirlik/mexc_hedge_deneme.py`)

- **A) Aynı coinde iki long giriş, her biri ekli stopla:** long bacağı 2 adım oldu. Ekli stoplar AYRI
  kaldı: 1.0549 (1 adım) ve 1.0788 (1 adım), aynı positionId. **İkinci giriş birincinin stopunu EZMEDİ.**
  Botun execution.py'deki ONE_PER_SYMBOL gerekçesinin (a) maddesi ("2. kolun girişi 1.'nin stopunu ezer")
  bu hesapta geçerli değil. Her girişin kendi miktarlı ekli stopu var.
- **B) Aynı coinde short:** long 2 ve short 1, ayrı bacaklar (farklı positionId), short'un kendi
  stopu 1.3425. **Hedge modu çalışıyor.**
- **C) Kısmi plan stop:** 1 adımlık, executeCycle=2 → borsada 168 (saat = 7 gün) olarak kabul edildi.
  Kimlikle iptal başarılı.
- **Temizlik:** TAMAM, coin boş.

**Sonuç: D3 (tam çözüm) teknik olarak mümkün.** Kalan iş:
- Kol bazında stop taşıma: botun `_get_attached_stop` fonksiyonu İLK stopu döndürüyor. Doğru stopu giriş
  emrinin kimliğiyle (stoporder.orderId) seçmek gerekir.
- Trend geniş stopunda izole 10x tasfiye mesafesi (~%9.5): bacak kaldıracı kollar arasında ortak.
- Mutabakatın bacak bazında yapılması (HEDGE_AWARE_RECON).
- Trend kolunun bot kapılarından (MAX_POSITIONS, aynı yön) muaf tutulması.

## Adım 3–4 sonuçları: teminat ve geniş stop (2026-10-03, VPS, DOT)

**Adım 3** (`mexc_teminat_deneme.py`):
- İzole 10x tasfiye fiyatı, fiyatın ~%90'ı.
- 0.10 USDT ek teminat (position/change_margin ADD) sonrası tasfiye fiyatın ~%7'sine indi.
- Açık pozisyonda kaldıracı 10x'ten 3x'e düşürmek (positionId ile) kabul edildi.
- Ekli stopu %25 aşağıya taşıma (change_plan_price, takeProfitPrice=0) reddedildi: 5003.

**Adım 4** (`mexc_stop_mesafe_deneme.py`):
- **takeProfitPrice=0 ile taşıma:** %15/%20/%25 reddedildi; stop yerinde kaldı.
- **Aynı taşıma, takeProfitPrice = fiyat×3 ile:** %25 KABUL. Stop 0.8985, TP 3.594.
- **change_price (giriş emri kimliğiyle) %25:** KABUL.
- **Girişte doğrudan %25 aşağıda ekli stop:** KABUL. İki giriş, iki ayrı stop.
- **Ayrı plan stop %25 aşağıda, 1 adım, 7 gün (168 saat):** KABUL.

**Sonuç:** Kısıt mesafe değil. Kâr al (TP) olmayan bir ekli stopu değiştirirken takeProfitPrice=0 göndermek
reddediliyor. Trend kolu için ekli stopa çok uzak bir TP konmalı (örn. fiyat×10) ve her stop taşımada aynı
TP geri gönderilmeli. Botun `_change_attached_sl` fonksiyonu mevcut TP'yi geri gönderiyor; bot kollarında
TP her zaman var, bu yüzden sorun görülmemişti.

**Tüm ön koşullar doğrulandı:**
- hesap hedge modunda,
- giriş başına ayrı ekli stop,
- long ve short bacakları ayrı,
- ek teminatla tasfiye stopun çok altına iniyor,
- geniş stop (girişte ya da TP'li taşımayla) kabul ediliyor,
- kısmi, 7 günlük plan stop kabul ediliyor.

## 2. aşama uçtan uca DOT denemesi (2026-10-04, VPS, `trend_hazirlik/mexc_trend_uctan_uca.py`)
Yeni canlı kod yolları (LiveExchange yöntemleri + trend_canli._teminat_ayarla) gerçek borsada:
1. Trend girişi kendi ekli stopuyla, kimlikle bulundu ✅
2. Ek teminat: tasfiye 0.5914'e indi ✅
3. Aynı bacağa bot girişi, iki ayrı stop ✅
4. Trend stopu kimlikle (TP yedekli) taşındı, bot stopu yerinde ✅
5. Bot stopu kimlikle taşındı, trend stopu yerinde ✅
6. Bot kolu kapatıldı:
   - **MEXC kapanan kolun stopunu KENDİSİ SİLMEDİ** ❗ (inceleme bulgusu #2 doğrulandı; düzeltme şart);
   - kimlikle iptal başarılı;
   - trend stopu ve miktarı kaldı ✅
7. Bot kolu kapandıktan sonra tasfiye fiyatı 0.5914'ten 0.8304'e YÜKSELDİ (izole teminat oransal serbest
   kaldı). Hâlâ trend stopunun (0.9487) altında ✅. Her 4 saatlik senkron teminat kontrolü bu yüzden gerekli.

Temizlik: TAMAM.
