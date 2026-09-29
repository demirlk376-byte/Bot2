# Lider traderların stratejileri ve bota eklenebilirlik

**Durum: 1. VPS koşusu (2026-09-29) yapıldı → ENTEGRASYON HÜKMÜ D (veri yetersiz). 2. koşu (geniş evren + sayfalı mum) bekleniyor.** Bu ortamdan Hyperliquid, Binance ve MEXC API'lerine erişim engelli
(ağ politikası). Araç VPS'te çalışacak.

## 1. Şimdiye kadar bulunan dış kanıt (web aramasıyla)

- **Hyperliquid'de 43.618 adresin analizi** ([TechFlow](https://www.techflowpost.com/en-US/article/33650),
  [KuCoin özeti](https://www.kucoin.com/news/flash/analysis-of-43-618-hyperliquid-addresses-reveals-12-top-accounts-and-their-trading-strategies)):
  - Pozitif getiri, hacim ve tutarlılık filtresinden 1.681 hesap geçmiş; bunların içinden en iyi
    12 hesap incelenmiş.
  - 12 hesabın dağılımı:
    - **8'i** yüksek frekanslı, iki taraflı işlem yapan hesaplar (piyasa yapıcılığı).
    - **3'ü** aktif gün içi traderlar.
    - Yalnız **1'i** tek yönlü, büyük pozisyonlu trend takipçisi.
  - Sonuç: başarı "küçük, tekrarlanabilir execution avantajından" geliyor; popüler altcoinler ya
    da yüksek hacim değil.
- **Copy trading üzerine akademik bulgu** ([Apesteguia vd., Management Science 2020](https://repository.essex.ac.uk/25396/)):
  - Başkalarının başarısını görmek ve kopyalayabilmek risk almayı belirgin artırıyor.
  - Makalenin sonucu: copy trading ex-ante refahı düşürüyor.
- **Balina pozisyonunun gelecekteki getiriyi öngördüğüne dair** yayımlanmış bir çalışma bulunamadı.
  Takip araçları var ([Hypertracker](https://hypertracker.io/),
  [Whaleportal](https://whaleportal.com/blog/hyperliquid-whale-tracker-explained/)), ama
  öngörü gücü ölçülmemiş.

**Çıkarım:** "Top 1" hesapların çoğunun stratejisi piyasa yapıcılığı. Bu, milisaniye düzeyinde
emir defteri avantajı ve düşük maker ücreti gerektirir; 4 saatlik bir kırılım botuna taşınamaz.
Yön alan (gün içi / trend) lider traderlar azınlıkta ve onlar için ölçülmüş bir öngörü kanıtı yok.

## 2. Kendi ölçümümüz — araç

`top_trader_analizi.py`: salt okur; yalnız Hyperliquid'in halka açık info API'sini kullanır.

**İndirilenler:**
- Lider tablosu.
- Aylık PnL'ye göre ilk 40 hesabın gerçek dolumları. Seçim koşulları: hesap değeri ≥ $100k,
  aylık ve tüm zamanlar PnL > 0. API hesap başına son ~10k dolumu verir.
- Bizim 11 coinimizin 4h mumları.

**Analiz (kurallar sonuçtan önce sabit):**
1. **Tip.** Dolumlardan ölçülür:
   - HFT/piyasa yapıcı: günde > 150 dolum, ya da maker payı ≥ %60 ve medyan tutuş < 1 sa.
   - gün içi: medyan tutuş < 24 sa.
   - swing/trend: diğerleri.
2. **Hangi durumda hangi işlem.** Yön alan traderların bizim coinlerdeki her tur işlemi için,
   giriş anından önce kapanmış 4h mumdan bağlam çıkarılır:
   - trend (EMA200'e göre)
   - Donchian-40 kırılımı
   - 24 saatlik momentum yönü
   - RSI14 bölgesi

   Her bağlamda işlem sayısı, kazanma oranı, ortalama net PnL ve tutuş raporlanır.
3. **Bota eklenebilir mi (zaman bölmeli, seçim yanlılığına karşı).**
   - Her trader'ın geçmişi zamanda ikiye bölünür.
   - Trader'lar ilk yarıdaki PnL'ye göre seçilir.
   - Sinyal yalnız ikinci yarıda ölçülür: seçilmiş traderların açtığı pozisyonların yönünde,
     sonraki 24 saatin getirisi, bizim maliyetimiz (33.7bp) düşülerek.
   - Hüküm:

| olay sayısı / sonuç | hüküm |
|---|---|
| < 50 olay | **D** |
| hafta-kümeli %95 GA > 0 | **A** (ikiz testine aday) |
| ortalama > 0 ama GA 0'ı içeriyor | **B** |
| ortalama ≤ 0 | **C** |

**Sentetik sınama:**
- Üç tip (piyasa yapıcı, gün içi, swing) doğru sınıflandı.
- Bağlam tablosu trend takipçisini "trend yönünde" olarak doğru gösterdi.
- 30 olayla hüküm D çıktı.

## 3. VPS'te çalıştırma

```
cd /opt/bot2 && git pull
venv/bin/python arastirma/top_trader_analizi/top_trader_analizi.py --indir
venv/bin/python arastirma/top_trader_analizi/top_trader_analizi.py
```

- Çıktılar `/tmp/top_trader/` altına yazılır:
  - `trader_profilleri.csv`
  - `yon_alan_islemler.csv`
  - `entegrasyon_olaylari.csv`
- Emir yok, API anahtarı yok, bota dokunulmaz.

## Sınırlar

- **Seçim yanlılığı:** Lider tablosu bugünkü PnL'ye göre seçilir ve kaybedenler görünmez.
  Bu yüzden entegrasyon testi zaman bölmeli.
- **Veri penceresi:** API yalnız son ~10k dolumu verir. Piyasa yapıcılar için bu birkaç gün,
  swing traderlar için aylar demek.
- **Borsa farkı:** Hyperliquid fiyatı MEXC'ten biraz farklıdır; bağlam için Hyperliquid mumları
  kullanılır.

## Sonuç

### 1. VPS koşusu (ilk 40 → dolum verisi olan 29 hesap)

**Trader tipleri:**

| tip | hesap |
|---|---|
| HFT / piyasa yapıcı | **23** |
| swing/trend | 4 |
| gün içi | 2 |

- HFT hesaplarının çoğunda günde 180 ile 28.000 arasında dolum var.
- Maker payı hesaba göre %0 ile %100 arasında değişiyor. Yani yalnız klasik piyasa yapıcılar
  değil, yüksek frekanslı taker botları da var.
- Dış analizle (12 hesabın 8'i iki taraflı yüksek frekans) tutarlı.

**Yön alan traderların bizim 11 coinimizde tur işlemi:** yalnız **19**. Bunların yalnız 2'sinde
giriş bağlamı hesaplanabildi.
- **Sebep:** Mumlar tek istekle çekiliyordu ve yetersiz geliyordu.
- **Düzeltme:** Sayfalı indirme.

**Entegrasyon testi:** 11 olay (< 50) → **D**.

**Çıkarım:**
- Lider tablosunun tepesi ağırlıkla yüksek frekanslı işlem.
- Bu strateji 4h kırılım botumuza **taşınamaz**. Bizim işlem başı maliyetimiz ~17bp; onların
  avantajı bunun altında ve milisaniye düzeyinde.
- Yön alan azınlık için test ancak daha geniş evrenle mümkün.

### 2. koşu (bekleniyor; kurallar aynı)

**Değişenler:** Yalnız evren genişliği (`--n-top 300`) ve sayfalı mum indirme.
- Tip eşikleri, bağlam tanımları, zaman bölmeli seçim, maliyet ve hüküm kuralları değişmedi.
- Hüküm D "veri yetersiz" demektir, "başarısız" değil. Bu yüzden evreni büyütmek eşik
  oynaması değildir.
