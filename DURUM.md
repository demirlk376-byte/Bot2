# Sistem Durumu

*Son güncelleme: 2026-08-14*

Bu dosya tek doğruluk kaynağı. "Ne yapıyorduk, neyi kanıtladık, ne zaman ne
değiştireceğiz" sorularının cevabı burada. Yeni bir şey yapmadan önce buraya bak.

---

## 1. Şu anki yapılandırma

```
LEVERAGE=10                RISK_SCALE=1.4                 ← 2026-09-09'da 1.125'ten
MAX_RISK_PCT=0.02          POSITION_CAP_FRACTION=1.5      ← 2026-08-12'de değişti
MAX_POSITIONS=7            CONSECUTIVE_LOSS_LIMIT=2
COOLDOWN_MINUTES=240       DAILY_MAX_LOSS_PCT=0.35
FIXED_MARGIN_USDT=0        MAKER_ENTRY=true
MARGIN_MODE=isolated       DONCHIAN_MAKER_ENTRY=true      ← 2026-09-09'da açıldı
```

Gerçekleşen risk/işlem = MAX_RISK_PCT × RISK_SCALE = **%2.80** (çıpa %2.25).
Bu satır bayatlarsa `ayar_dogrula.py` yakalar — ama ancak `deployed_backtest.py`
içindeki `CANLI_*` sabitleri de güncellenirse. İkisi birlikte güncellenir.

Üç kol çalışıyor:

| kol | coinler | zaman | risk/işlem |
|---|---|---|---|
| donchian | SOL ETH ADA NEAR BCH ICP BNB | 4h | %2.25 |
| squeeze | XRP DOGE TRX XLM | 1h | %2.25 |
| bb (mean_rev) | LTC, **yalnız hafta sonu** | 1h | %2.25 |

Doğrulama: `python3 ayar_dogrula.py` → `✓ AYARLAR DOĞRU` demeli.

---

## 2. Beklenti

Bakiye ~$203. Ankor (2023-2026 backtest) tipik ayı **%+15.3**, en kötü ayı **−%20.5**,
40 ayın 8'i negatif.

**Ama ankor iyimserdir** — parametreler o veriye bakılarak seçildi. Canlıda gerçekleşen
R şu an ankorun altında (n=41, güven aralığı hem ankoru hem sıfırı içeriyor).

Gerçekçi tipik ay: **$9 – $31**.
(⚠ DÜZELTİLDİ: önce "$15–31" yazıyordu. O sayı ankorun %15.3'ünü R oranıyla
DOĞRUSAL ölçekleyerek tahmin edilmişti. Simülasyon R'yi gerçek şekilde kaydırınca
medyan ay %4.3 çıkıyor, %7 değil: edge düşüşü ayda ~39 işlemin HEPSİNE uygulanıyor,
yani aylık getiriden sabit ~11 puan iniyor. 15.3 − 11.0 = 4.3.)

**PROJEKSİYON — ayda $100 katkıyla** (canlı edge senaryosu, sim_katki.py):

| | 12 ay (yatırılan $1403) | 24 ay (yatırılan $2603) |
|---|---|---|
| kötü (%10) | $1,142 → ay ~$49 | $2,477 → ay ~$106 |
| **medyan** | **$2,266 → ay ~$97** | **$6,420 → ay ~$276** |
| iyi (%90) | $4,728 → ay ~$203 | $18,781 → ay ~$807 |
| yatırdığından az çıkma | %19 | %11 |

**Kullanılacak aralık: 1 yıl ~$100/ay · 2 yıl $150–400/ay (merkez $275).**

⚠ ANKOR senaryosu 24 ayda medyan $38,474 / ayda $5,897 veriyor — SAÇMA, kullanma.
%15.3'ü 24 ay bileşiklendirmek 30 kat demek; hiçbir strateji iki yıl aynı verimde kalmaz.

⚠ ÜST UÇ AYRICA KIRPILMALI, üç modellenmemiş etki: (a) edge 24 ay sabit varsayılıyor,
(b) ölçek — %90 senaryoda tek pozisyon $28,000 nominal, ICP/NEAR/XLM gibi ince
defterlerde ölçülen 13.4bp kayma büyür, (c) simülasyonda ücret/çekim yok, katkı ayın
başında tam çalışıyor, kötü dönemler kümelenmiyor.

Kâr, riski artırarak değil **bakiye büyüyerek** artar. $203 → $400 olduğunda aynı
%2.25 riskle aylık kâr ikiye katlanır.

---

## 2b. ANKOR DENETİMİ (2026-08-12) — TABAN %20 ŞİŞKİNMİŞ

Bütün gün araçlar ankoru YENİDEN ÜRETTİ ama ankorun DOĞRU olduğu hiç denetlenmedi.
Denetlendi:

| kademe | işlem | toplam$ | Δ% | PF | ort R | maxDD |
|---|---|---|---|---|---|---|
| A0 ANKOR (eski taban) | 1579 | +1476 | +0% | 1.43 | +0.237 | 26.4 |
| A1 +giriş kayması 13.4bp | 1581 | +1225 | −17% | 1.35 | +0.192 | 28.9 |
| A2 **sonraki barın açılışı** | 1580 | +1462 | **−1%** | 1.42 | +0.236 | 21.6 |
| A3 A2+kayma+fonlama | 1582 | **+1177** | **−20%** | 1.33 | **+0.190** | 29.8 |

**A2 GEÇTİ — ankorun temeli SAĞLAM.** Giriş bir sonraki barın açılışına (canlıda
gerçekten olan yere) kaydırılınca kayıp yalnız %1. Ankorun kârı "kapanış fiyatına
erişebilmekten" GELMİYOR; edge zamana duyarlı değil.

**AMA %20 ŞİŞKİN:** ankor giriş kaymasını (13.4bp) ve fonlamayı (%2.2/yıl) hiç
düşmüyor. **Dürüst ankor $1177 ve ort R +0.190** — $1476 / +0.237 değil.
→ Bugün verilen TÜM projeksiyonlarda 0.237 kullanıldı; doğrusu 0.190'dı.
→ Hatırlanan "aylık %15" gerçekte **~%12** olmalıydı.
→ A3'ün +0.190'ı canlıda ölçülen +0.0555'in güven aralığının ([−0.357, +0.468])
  İÇİNDE — dürüst ankor ile canlı arası uçurum sanılandan DAR.

**BUNDAN DOĞAN TEK UYGULANABİLİR FİKİR (bugünün en iyisi):**
Kayma tek başına **$251** yiyor (3.6 yılda, ~$70/yıl) — bugün bulunan hiçbir filtre
buna yaklaşamadı. A2 gösterdi ki **edge bir tam bar gecikmeye dayanıyor (−%1)**.
Şu an donchian/squeeze `force_market` ile giriyor (koddaki gerekçe: "araştırmaları
kapanışta garanti taker dolum varsayıyor") — ama A2 o varsayımın GEREKLİ OLMADIĞINI
gösterdi. Maker limit girişi hem kaymayı hem taker ücretini kurtarabilir.
Risk: limit dolmazsa işlem kaçar. ÖLÇÜLMEDİ — sıradaki iş bu.

---

## 2c. MAKER GİRİŞ (2026-08-13) — KARARSIZ, ve kararı canlı defter verecek

`maker_giris.py` · `gecikme_olc.py` · `kayma_denetim.py`

**Önce fikrin düzeltilmesi:** 2b'de "limit dolmazsa işlem kaçar" yazmışım. Kodu
okuyunca ortaya çıktı ki bu **zaten denenmiş ve 2026-07-16'da geri alınmış**
(main.py:640-647): *"the former limit+no-fallback path adversely selected: runaway
releases never retraced and were skipped."* Geri alınan şey "maker giriş" değil,
**YEDEKSİZ** maker girişti. `exchange.place_limit_order` piyasa yedeğiyle geliyor ve
BB/MR kolu canlıda ZATEN bu yolu kullanıyor. Yedekli sürümde **hiçbir işlem kaçmaz**;
değişen tek şey ödenen fiyattır. Ayrım execution.py:611'de `sl_price > 0` bakışında —
donchian/squeeze sl_price DOLDURUYOR ama SL'i yapıya değil KAPANIŞA çapalıyor, yani
bayrak yanlış kolu yakalıyor.

**Gecikme elendi (gecikme_olc.py).** data.py:88 `REST_POLL_INTERVAL=30` ve bar sınırına
hizalı değil — "kayma aslında geç fark etmedir, hizalama bedava kazanç" hipotezi
makuldü. ÖLÇÜLDÜ (BTC+ETH 1dk, n=133 donchian sinyali): bar kapanışından **1dk sonra
aleyhe sürüklenme +0.12bp** (squeeze +1.35bp), medyan NEGATİF, %95 aralık 0'ı içeriyor.
→ **Anket hizalaması boşa iş.** 13.4bp gecikmeden gelmiyor; geriye spread/etki kalıyor.
(Yan bulgu: 1dk'da fiyatın kaçmaması maker girişi GÜÇLENDİRİR — beklemenin bedeli ~0.)

**Dolum oranı ölçüldü ve KURALA ÇOK DUYARLI çıktı.** İlk kuralım (`low <= L → doldu`)
%98.4 verdi; o sayı gerçek değil, kural neredeyse totolojiydi (1dk barının açılışı ≈ L).
Fiziksel gerçek: limitimiz kuyruğun arkasında, fiyatın seviyeyi GEÇMESİ gerekir. Tek
sayı yerine bant üretildi (W=1dk, ön-kayıtlı):

| dolum kuralı | dolum% | başabaş p* | portföy Δ$ | ters-seçim modellenince Δ$ |
|---|---|---|---|---|
| seviyeyi geçsin (0bp) | 89% | 47% | **+179** | **+192** |
| 2bp geçsin | 68% | 42% | **+103** | **+66** |
| 5bp geçsin | 41% | 32% | +22 | −3 |
| 10bp geçsin (tam spread) | 21% | 26% | −30 | **−74** |

**Ters-seçim GERÇEK ve ölçüldü:** en katı kuralda limit KAZANAN işlemlerde %9,
KAYBEDENlerde %27 doluyor — fiyat kazananlarda kaçtığı için. Yedek olduğundan işlem
kaçmıyor, ama indirim ağırlıkla kaybedenlere düşüyor. Modellenince her satır
kötüleşiyor (düz ortalama model İYİMSERMİŞ). Karar bu satırlardan verilmeli.

**HÜKÜM: KARARSIZ.** İşaret 2bp ile 5bp arasında dönüyor, yani soru tek bir şeye
iniyor: *~$285'lik emrimiz, fiyat seviyeyi 2-5bp geçtiğinde dolar mı?* Bunu 1 dakikalık
BAR verisi bilemez — emir defteri sorusudur. Ön-kayıtlı bar en kötümser satırdan
verildiği için **bugün üretime ALINMAZ.**

**AMA cevap bedava ve hazır:** BB/MR kolu canlıda ZATEN maker yolunda, donchian/squeeze
market. Defterde hazır doğal deney var. `kayma_denetim.py` (self-test'li) her işlemin
sinyal barı kapanışını bulup gerçekleşen girişle farkını ölçüyor, kol bazında ayırıyor.

**AYRICA — 13.4bp'nin KENDİSİ DENETLENMEMİŞ.** live_verify.py:44'te
`ANK_SLIP_BP = 13.4  # ölçülen` yazıyor ama **ölçüm kodu hiçbir dosyada yok**. Bu sabit
2b'nin $251'ini, "dürüst ankor $1177"i ve buradaki tüm $ rakamlarını belirliyor.
Ankorda yaptığımız hatanın aynısı: herkesin güvendiği, kimsenin denetlemediği sayı.
`kayma_denetim.py` onu da defterden yeniden ölçüyor.

## 2d. ÜCRET ÖLÇÜLDÜ (2026-08-13) — ve defter dolum oranını ELE VERDİ

`ucret_olc.py` nihayet çalıştırıldı (aylardır bekliyordu). Ankor taraf başına 1.00bp
varsayıyor; **gerçek 0.751bp**. Ankor bu kalemde $10.51 AZ gösteriyor (%0.74) —
kayda değer ama aksiyon gerektirmiyor. Asıl değer kol bazındaki dağılımda:

| kol | yürütme yolu | ölçülen bp/taraf | teorik beklenti |
|---|---|---|---|
| `?` (kapalı kollar) | limit, **YEDEKSİZ** → dolmazsa işlem atlanır, kitaba giren her işlemin girişi ZORUNLU maker | **0.508** | 0.500 |
| donchian | `force_market` → iki bacak da taker | **0.985** | 1.000 |
| squeeze | `force_market` | **0.945** | 1.000 |
| bb/mean_rev | **maker limit + 45sn piyasa yedeği** | **0.668** | ? |

**İki uç da teoriyi TAM tutturdu** (0.508 ≈ 0.500 · 0.985/0.945 ≈ 1.000). Bu, "MEXC
vadelide maker %0, taker 1bp" modelinin doğrulanmasıdır — ve o model doğruysa
aradaki BB satırı **dolum oranını doğrudan verir**: 0.668 = (2−p)/2 → **p ≈ %66**.

Yani `maker_giris.py`'nin 1dk bar verisiyle cevaplayamadığı soruyu **canlı defter
cevaplıyor**: donchian için önerilen kurgunun (maker limit + 45sn yedek) gerçek dolum
oranı, o kurguyu zaten kullanan kolda **~%66**. Başabaş ~%42 (2bp kuralı). Bandımızda
%68 satırı **+$103** (ters-seçim modellenince +$66) veriyordu — bar geçiyor.

**AMA ÜST SINIR, TAHMİN DEĞİL — iki sebeple:**
1. **n=11.** %95 aralık kabaca %38–%94; alt uç başabaşın altında.
2. **BB ortalamaya dönüş kolu.** Limitini fiyatın GERİ GELDİĞİ yere koyuyor → dolum
   lehine yanlı. donchian/squeeze momentum; fiyat limitten KAÇAR. 2026-07-16
   denetiminin tespit ettiği mekanizma tam bu. `maker_giris.py` de aynı yönde ölçtü:
   limit kazanan işlemlerde %9, kaybedenlerde %27 doluyor.

→ **Hâlâ üretime alınmıyor.** Ama artık eksen "ölçülemez" değil, "n yetersiz".
`kayma_denetim.py` [4] bölümü bu çıkarımı her koşuda işlem-başına sınıflandırmayla
(gerçek Bernoulli + güven aralığı) ve iki-uç kalibrasyon kontrolüyle yeniden yapıyor.
**BB işlem sayısı büyüdükçe aralık daralacak — bu ekseni ay sonunda tekrar bak.**

### Yan bulgu (düzeltilmeli)
`live_verify.py` `TAKER_FEE` varsayılanı **0.0002**, ölçülen ise **~0.0001**. İki kat
şişkin; beklenen-vs-gerçekleşen PnL karşılaştırmasını kaydırıyor.

---

## 2e. Bugün aracın kendi guard'ının yakaladığı hata

`kayma_denetim.py` ilk koşuda **hüküm vermeyi reddetti**: "işlemlerin %44'ü sinyal
barına eşleşmedi". Guard doğru çalıştı, hatalı olan benim paydamdı: 79 işlemin 33'ü
kapalı kollardan (`?`) ve onların timeframe'i `TF` sözlüğünde yok — hiçbir zaman
eşleşemezlerdi. Kapsam dışına alınınca eşleşme 44/46 (%96). *Bu, regime_teshis'in
sessiz tz hatasının tersi: orada araç yanlış hükmü SESSİZCE basmıştı, burada guard
doğru hükmü basmayı ENGELLEDİ. İkincisi doğru davranış.*

---

## 2f. KAYMA DENETİMİ ÇALIŞTI (2026-08-13) — sabit doğrulandı, maker CANLI KANIT aldı

`kayma_denetim.py`, canlı defter, n=44, **%100 bar eşleşmesi**.

### [1] 13.4bp DENETLENDİ ve GEÇTİ
donchian ölçülen giriş kayması **+15.32bp** [%95: +0.26, +30.38] · n=21.
**13.4 aralığın içinde → sabit DOĞRULANDI.** Ankor denetiminin A1/A3 satırları
($251 düzeltme, "dürüst taban $1177") **geçerli**. Aralık geniş, sabit değiştirilmedi.

### [2] DOĞAL DENEY — maker kol vs taker kollar

| kol | yürütme yolu | giriş kayması | aleyhe% | n |
|---|---|---|---|---|
| **bb/mean_rev** | **maker limit + 45sn yedek** | **−2.95bp** [−6.37, +0.47] | 18% | 11 |
| donchian | `force_market` | **+15.32bp** [+0.26, +30.38] | 67% | 21 |
| squeeze | `force_market` | +4.18bp [+0.45, +7.91] | 67% | 12 |

**FARK +14.22bp [%95: +3.87, +24.57] — sıfırı DIŞLIYOR.** Maker kolu sinyal
fiyatından **daha İYİ** giriyor (negatif kayma), taker kollar aleyhe.

### [3] GECİKME — hipotez kesin olarak elendi
medyan **24sn**, %90 42sn (ort 123sn'yi 3638sn'lik tek outlier şişiriyor —
muhtemelen restart). `gecikme_olc.py` 1dk'da ~0bp sürüklenme ölçmüştü.
→ **24sn'de sürüklenmeden gelen kayma ihmal edilebilir. Kayma spread/etki.**
Ve spread/etki maker girişin tam olarak kurtardığı şey.

### [4] DOLUM ORANI — iki uç kalibrasyonu TUTTU

| kol | bp/taraf | maker giriş | oran | beklenen |
|---|---|---|---|---|
| `?` (kapalı, yedeksiz limit) | 0.547 | 30/33 | %91 | ~%100 |
| **bb [maker+yedek]** | 0.638 | **8/11** | **%73** [%46–%99] | ? |
| donchian (force_market) | 0.975 | 1/19 | %5 | ~%0 |
| squeeze (force_market) | 0.872 | 3/12 | %25 | ~%0 |

İki uç teoriyi tutturdu (0.547≈0.500 · 0.935≈1.000) → "maker %0 / taker 1bp"
modeli doğrulandı → **BB'nin %73'ü gerçek bir ölçüm.** Başabaş ~%42;
**güven aralığının ALT UCU (%46) bile başabaşın üstünde.**

*(Not: squeeze'in 3/12'si ve `?`'nin 30/33'ü teoriden sapıyor. Sebep sistematik:
nominal'i yalnız GİRİŞ fiyatından hesaplıyorum, ücret ise giriş+çıkış nominali
üzerinden → ~+%5 yukarı kayma. Sınıflandırma eşiğini etkiliyor ama BB'nin 0.638'i
eşiğe uzak, o okuma sağlam.)*

### HÜKÜM: eksen "kararsız"dan "GÜÇLÜ ADAY"a geçti — ama hâlâ ÜST SINIR
Çekince değişmedi: **BB ortalamaya dönüş** (limit lehine yanlı), donchian
**momentum** (fiyat limitten kaçar). BB'nin %73'ü donchian için **üst sınır**.

---

## 2g. UYGULAMA — deney olarak kodlandı, VARSAYILAN KAPALI

Kod hazır ve testli, **ama canlı davranış DEĞİŞMEDİ.**

`DONCHIAN_MAKER_ENTRY=false` (varsayılan) → `git pull` tek başına hiçbir şeyi
değiştirmez. Bu bilinçli: bulgu güçlü ama BB üst sınır olduğu için açmak bir KARAR.

**Neden tek satır yetmiyordu:** `execution.py:611` yolu `sl_price > 0` ile seçiyordu.
donchian sl_price'ı DOLDURUYOR ama SL'i seviyeye değil GİRİŞ FİYATINA ATR ile
çapalıyor → çıkarım onu "yapı-tabanlı" sayıp **piyasa yedeğini kapatıyordu**.
Sadece `force_market=False` yapmak, 2026-07-16'da geri alınan **yedeksiz** yola
düşürürdü. Açık bayrak eklendi: `CombinedSignal.anchor_is_level`
(`None` = eski çıkarım → mevcut kolların hiçbiri etkilenmez).

`tests/test_maker_routing.py` (suite'e eklendi, 4/4 dosya geçiyor) altı şeyi kanıtlıyor;
en önemlisi **bayrak kapalıyken yolun `market` kaldığı**.

### DENEY TASARIMI — squeeze KONTROL GRUBU olarak kalır
Sadece donchian açılır. squeeze `force_market` kalır. İkisi de **momentum** kolu,
aynı dönem, aynı piyasa → BB'nin ortalamaya-dönüş yanlılığı ortadan kalkar.
Kazanç potansiyeli de donchian'da (+15.32bp vs squeeze +4.18bp).

**Açmak için** (`.env`, sonra `systemctl restart btc-bot`):
```
DONCHIAN_MAKER_ENTRY=true
```
**4–6 hafta sonra** `python3 kayma_denetim.py` → donchian'ın kayması ve dolum oranı
squeeze'inkiyle karşılaştırılır.
**GERİ ALMA ÖLÇÜTÜ (ön-kayıtlı):** donchian dolum oranı **%42'nin altına** düşerse
veya kayması squeeze'e göre iyileşmezse → bayrak kapatılır.

### Modellenmemiş tek risk
**KISMİ DOLUM.** `place_limit_order` kısmi dolumu booklar ve üstüne piyasa yedeği
ATMAZ (bilinçli — çift maruziyeti önlüyor). Pozisyon hedeflenenden küçük kalır;
küçük emirlerde nadir ama backtest'te modellenmedi.

### Yan bulgu (ayrı iş)
`live_verify.py` `TAKER_FEE` varsayılanı **0.0002**, ölçülen **~0.0001**. İki kat
şişkin; beklenen-vs-gerçekleşen PnL kıyasını kaydırıyor.

---

## 3. Kanıtlanmış olan

**Kötü aylar rejim değil, şans.** 10.000 permütasyon: gerçek 8 negatif ay
(karışık medyan 7, p=0.32), gerçek en kötü ay −20.5 (karışık medyan −21.1, p=0.53).
Kayıplar zamanda kümelenmiyor.

Bu yüzden **hiçbir rejim filtresi çalışamaz** — filtrelenecek bilgi yok. Bu bir
deneme sonucu değil, matematiksel sonuç.

**Kapsam sınırı:** bu, "alınan işlemleri girişte bilinen bir kuralla elemek" için
geçerli. Yapısal olarak farklı yeni bir strateji/enstrüman eklemek hakkında bir şey
söylemez.

---

## 4. Kapanan eksenler (23+)

Tekrar denenmemeli. Her birinin sebebi var, "denedik olmadı" değil.

**Çıkış/maruziyet ekseni fiyatlı.** Kuyruk riskini satmak puan başına en fazla
$23.6 kazandırıyor, satın almak en az $80'e mal oluyor. Trailing, breakeven, kısmi
çıkış, rr genişletme, maruziyet tavanı, koltuk azaltma — hepsi bu duvara çarptı.

**Rejim filtreleri.** Kapı (squeeze/bb oynaklık), günlük zarar freni, korelasyon
koşullu koltuk. Üçü de çöktü; sebebi bölüm 3'te.

**Neden çöktüklerinin mekanizması:** en kötü dilimin ortalama R'si hâlâ POZİTİF
(squeeze en yüksek ATR dilimi +0.058R). Filtre zarar edeni değil AZ KAZANANI kesiyor.
"Edge zayıflıyor" ile "edge negatife dönüyor" farklı şeyler.

**Cooldown.** 1603 sinyalin yalnız 6'sını engelliyor. Etkisi +$14 / 3.6 yıl = gürültü.

**Günlük zarar freni.** Kâğıtta ucuz göründü ama `execution.py` tetiklendiğinde
`emergency_close_all` çağırıyor — bütün pozisyonları piyasa emriyle kapatıyor.
Modellemediğim için ölçüm geçersizdi. **DAILY_MAX_LOSS_PCT değiştirilmez.**

**Pairs.** 5 işlem kârın %67'si; koruyucu stop edge'i öldürüyor; aynı hesapta
çakışma %89. Tolere edilebilir riskte yılda ~$27. Bakiye ≥$1000 olursa yeniden bakılır.

**XAU.** MEXC'te uygun enstrüman yok.

**KISA VADELİ DÖNÜŞ / FADE (2026-08-12).** Bugünün TEK "ekleyen" denemesi (diğer 13'ü
mevcut işlemleri buduyordu). Hipotez kendi ölçümlerimizden çıkmıştı: en iyi rejim
`range/düşük vol` (+0.391R) ve tek mean-reversion kolumuz (bb) yalnız LTC+hafta sonu.
| k (aşırılık) | kendi n | kendi ortR | kayma sonrası | portföy Δ$ |
|---|---|---|---|---|
| 1.0 | 13006 | −0.0159 | −0.0529 | −130 |
| 1.5 | 7052 | −0.0481 | −0.0851 | −708 |
| 2.0 | 3162 | −0.0553 | −0.0923 | −463 |
| 2.5 | 1385 | −0.0279 | −0.0649 | −194 |
| 3.0 | 649 | −0.0182 | −0.0552 | −97 |

**BEŞ EŞİĞİN BEŞİ DE KAYMA ÖNCESİNDE BİLE NEGATİF.** Yani "arbitrajlanmış, sıfıra
inmiş" değil — AKTİF OLARAK ZARAR ETTİRİYOR.

**MEKANİZMA — sistemi açıklıyor:** aşırı hareketi ters oynamak para kaybettiriyorsa
o hareket DEVAM ediyor demektir. Bu tam olarak donchian'ın sömürdüğü şey. Bu piyasa
bu zaman ölçeğinde MOMENTUM piyasası; fade etmek donchian'ın kâr ettiği etkiye karşı
bahis oynamaktır.
→ bb kolunun neden yalnız HAFTA SONU ve TEK coinde olduğu da anlaşıldı: hafta sonu
hacim düşük, momentum zayıf — ortalamaya dönüşün çalıştığı tek yer orası.
Kısıtlaması keyfi değil, DOĞRU YERDE.

**KAPALI KOLLAR (2026-08-12).** Kodda .env ile açılan 5 kol (SR/FVG/IFVG/ASIA/ORB)
ölçüldü — hepsi REDDEDİLDİ. Taban: +$1476, maxDD 26.4, en kötü ay −20.5.
| kol | kendi n | kendi ortR | kendi PF | portföy Δ$ | maxDD% | en kötü ay |
|---|---|---|---|---|---|---|
| sr | 1967 | +0.0489 | 1.08 | +32 | **86.5** | −51.9 |
| fvg | 7672 | +0.0091 | 1.02 | −245 | **125.4** | −120.2 |
| ifvg | 1866 | +0.0231 | 1.00 | +127 | 25.8 | −48.2 |
| asia | 12376 | **−0.0206** | 0.94 | **−1438** | **142.1** | −77.9 |

**KESİN ÖLDÜREN ARGÜMAN — yürütme maliyeti:** ölçülmüş giriş kayması 13.4bp ≈ **0.037R**
(donchian sl% 3.57 üzerinden). Donchian 0.243 − 0.037 = 0.206R sorunsuz. Ama
sr 0.049 − 0.037 = 0.012R (sıfıra yakın), ifvg 0.023 − 0.037 = **NEGATİF**.
Bu kollar backtest'te bile zar zor kâr ederken gerçek yürütme maliyetini ödeyemiyor.

**MEKANİZMA — bugünü tamamlıyor:** bu kollar binlerce sinyal üretiyor (asia 12.376) ve
koltukları sürekli dolduruyor — ama +0.24R'lik işlemler yerine +0.05R'liklerle.
`asia` tek başına portföyü +$1476'dan **+$38**'e düşürüyor.
→ **BOŞ KOLTUK, DOLDURULMAYI BEKLEYEN KAPASİTE DEĞİLDİR.** İyi sinyal nadir olduğu için
boş. Vasat sinyalle doldurmak para eklemez, İYİLERİ KOVAR.
Bu, "boşta para = rezerv" ve "coin ekleme kuyruğu patlatıyor" bulgularının üçüncü ayağı:
kapasiteyi doldurmanın ÜÇ yolu da (coin, kol, koltuk) ölçüldü ve üçü de zarar veriyor.

**COIN EVRENİ GENİŞLETME (2026-08-12).** Eksen yeniden açıldı ve KESİN kapandı.
Gerekçe sağlamdı: para boşta çünkü SİNYAL yok (1.75/7 koltuk); coin eklemek sinyal ekler;
yeni parametre uydurulmuyor, aynı kural daha çok yere uygulanıyor; deploy .env.

**T1 — SEÇİMSİZ (10 adayın hepsi, sıfır seçim yanlılığı):**
| küme | işlem | toplam$ | PF | maxDD% | en kötü ay |
|---|---|---|---|---|---|
| taban (7 coin) | 1579 | +1421 | 1.45 | 24.4 | −21.0 |
| +hepsi (15 coin) | 2331 | **+1361** | 1.27 | 28.1 | **−58.8** |
İşlem %48 arttı, kâr AZALDI, en kötü ay neredeyse ÜÇ KATINA çıktı.

**T2 — TRAIN'de seç (2023-24), TEST'te ölç (2025-26):**
Kural önceden sabit (her TRAIN yılı pozitif VE PF>1.10) → 8 coin seçildi.
```
TRAIN 2023-24:  taban +$778 → seçim +$1283   (+$505)
TEST  2025-26:  taban +$643 → seçim  +$388   (−$254)
```
**Seçim prosedürü TRAIN'de muhteşem, TEST'te para kaybediyor.** Başarısız olan
herhangi bir coin değil, "geçmişte iyi gideni seç" PROSEDÜRÜNÜN KENDİSİ.
→ "Hangi coinleri ekleyelim" sorusunun cevabı YOK; soru yanlış.

**T3 — doz-yanıt:** K=1 (+TRX) kârı +$87 artırırken en kötü ayı −21.0 → **−32.2**
taşıyor. Daha İLK adımda ön-kayıtlı bar düşüyor.

**DÜZELTİLEN AKIL YÜRÜTME — bugünün en değerli mekanizması:**
Bu testi açarken "eski ret gerekçesi koltuk çekişmesiydi ama koltuklar %3.25 dolu,
o mekanizma bizde yok" demiştim. **YANLIŞTI.** Koltuklar ORTALAMADA boş ama korele
bir çöküşte hepsi birden doluyor — ve 15 coinle hepsi birbirinin aynı kaybeden
pozisyonuyla doluyor. En kötü ayın −21'den −58.8'e fırlaması tam olarak budur.
Eski gerekçe doğruymuş; ben yanlış yerde (ortalamada) ölçmüşüm. Önemli olan
KUYRUKTAKİ doluluk. Bu, "boşta duran para israf değil REZERV" tespitinin bağımsız
teyidi.

**"Boşta parayı kullanalım" (marjin / kaldıraç / koltuk).** Üç kol da ölçüldü, üçü de
reddedildi. ÖNCE KAVRAM: `marjin = nominal / kaldıraç`. Kaldıraç sabitken daha çok
marjin ancak daha büyük nominal ile olur; stop sabitken bu doğrudan işlem başına daha
çok DOLAR RİSKİ demektir. Marjin bağımsız bir ayar DEĞİL, sonuçtur.
| kol | ölçüm | hüküm |
|---|---|---|
| CAP 1.5→2.0 | +$60/3.6yıl, tepe marjin %82→%97 | tampon %3'e iner; bakiye düşünce kötü dönemde işlem reddi başlar |
| kaldıraç 10x→20x | kazanç YOK (marjin zaten hiçbir işlemi engellemiyor, red=0) | işlemlerin %35'inin stopu likidasyonun ötesine geçer |
| MAX_POSITIONS 7→10 | +$28/3.6yıl ($8/yıl) | en kötü ay −20.5 → −22.7; barı geçmiyor |

**ASIL BULGU — para neden boşta:** ortalama aynı anda açık pozisyon **1.75 / 7 koltuk**
(doluluk %25), ortalama marjin bakiyenin **%10'u**, tepe **%82**. 1603 sinyalin yalnız
24'ü (%1.5) koltuk yüzünden engelleniyor. MAX_POSITIONS 10'un üstünde HİÇBİR ŞEY
değişmiyor (1603 toplam sinyal arzı).
→ Para boşta çünkü koltuk yetmiyor değil, **YETERLİ SİNYAL YOK**.
→ Ortalama %10 ile tepe %82 arasındaki fark İSRAF DEĞİL, sinyal kümelenmesi için
  tutulan REZERV. Ortalamayı doldurmaya kalkmak, tepe anında (sinyallerin bol olduğu,
  yani en kazançlı dönemde) işlem reddine yol açar.
→ Boşta parayı kullanmanın tek yolu daha çok sinyal üretmektir (yeni coin / strateji)
  — ki bu "her şey sabit kalsın" değildir.

**Sahte kırılım (Breakout Quality Filter).** Kullanıcının 7 kriteri tek tek ölçüldü.
Beşi zaten sistemde vardı ya da ayrım gücü yoktu (kapanis_yeri z=−0.00 — tam sıfır).
Kalite skoru (6 özellik, eşit ağırlık) GERÇEKTEN ayırdı (Q1 +0.092R vs Q5 +0.314R,
WR %38.7→%47.3) ama negatif dilim üretmedi → kapı %10/%20/%30'da −$21/−$106/−$211.
DİKKAT: PF ve WR yükselirken net PnL düştü — kalite metriği tuzağı.
Kırılım sonrası teyit gerçek ve çok güçlü çıktı (yukarıdaki inceltilmiş kurala bakın)
ama üç uygulama yolu da kaybettirdi.

**ARAŞTIRMA KURALI (2026-08-12'de deneyle doğrulandı):**
Bir filtre ancak kestiği alt kümenin ortalama R'si **NEGATİF** ise para kazandırır.
Sinyalin ne kadar güçlü ya da tutarlı olduğu önemli değil.

Kanıt — aynı koşuda iki kapı:
| kapı | sinyal | negatif alt küme | walk-forward |
|---|---|---|---|
| donchian atr_orani | z=+2.15, iki dönem tutarlı | **yok** (en kötü +0.072) | **−$41** |
| squeeze govde | z=−2.10, daha zayıf | **var** (Q5 = −0.243) | **+$21**, 3/3 yıl artı |

Güçlü sinyal + negatif küme yok = para kaybı. Zayıf sinyal + negatif küme var = kazanç.

**AYNI GÜN İNCELTİLDİ — negatif küme GEREKLİ ama YETERLİ DEĞİL:**
Sahte kırılım testi bunu gösterdi. Sinyal muazzam (z=+6.39, TRAIN/TEST birebir),
negatif alt küme net (−0.2488R, 234 işlem). Kuralın istediği her şey vardı.
Yine de üç uygulama yolunun üçü de kaybettirdi:
| yol | mantık | sonuç | neden |
|---|---|---|---|
| teyit bekle | kötüyü hiç alma | −$335 | 783 iyi işleme 1 bar geç giriliyor |
| retest şartı | daha seçici | −$878 | aynı, daha ağır |
| erken çık | girişi koru | −$120 | −0.2488 → −0.3925: toparlananlar ölüyor |

**Tam kural:** kesilecek grubun R'si negatif OLMALI **ve** o gruptan çıkmanın
bedeli grubun zararından KÜÇÜK olmalı. İkinci şart genelde tutmuyor: bilgiyi almak
için ya giriş fiyatı feda ediliyor ya toparlanma ihtimali.

Yeni bir filtre fikrinde İKİ soruyu birden sor:
 1. Kesilecek grubun ortalama R'si negatif mi?
 2. O gruptan çıkmanın bedeli (geç giriş / erken çıkış / kaçan toparlanma) zarardan az mı?

---

## 4c. KÖK NEDEN ANALİZİ — "bot hangi koşulda kaybediyor?" (2026-08-12)

**CEVAP: hiçbirinde sistematik olarak kaybetmiyor.** Ölçülen HER koşulun beklentisi
pozitif. Dört şartı (ort R negatif · n≥30 · TRAIN ve TEST'te ikisinde de negatif ·
Bonferroni |z|) birden geçen tek bir hücre YOK.

**Negatif ayların kol dağılımı** (8 ay, toplam −$181.8):
donchian −$192 (%106) · squeeze **+$50** (−%27) · bb −$40 (%22)
→ squeeze kötü aylarda POZİTİF; zararın kaynağı değil YASTIĞI (8 ayın 5'inde kârlı).
→ bb payı oransız: zararın %22'si, kârın %9'u. n=161, aksiyon için yetersiz.

**En önemli tek gözlem:** sekiz negatif ayın hepsinde "en büyük kayıp" AYNI: −$4.3
(= 1R tam stop). Kötü aylar birkaç büyük kayıptan değil, çok sayıda KÜÇÜK kayıptan
oluşuyor. Kesilecek aykırı grup yok — filtrelerin neden çöktüğünün somut açıklaması.

**Rejim — yaygın varsayımın TERSİ:** dokuz hücrenin hepsi pozitif ve en iyisi
**range/düşük vol +0.391R** (z=3.23, iki dönem de artı). "Yatay ve sakin piyasada
sahte kırılım üretiyor" varsayımı ÖLÇÜMLE YANLIŞ. En zayıfı ara/orta vol +0.166R.

**Yön:** donchian long +0.290 / short +0.190, squeeze long +0.221 / short +0.251.
Shortlar da kazanıyor → sadece kripto betası değil, gerçek edge.

**Saat:** donchian'ın 6 saatinin hepsi pozitif. squeeze 02:00 dikkat çekti
(n=17, ort R −0.916, z=−9.50) AMA TEST'te yalnız 2 işlem var → pratikte TRAIN-only.
Ön-kayıtlı n≥30 barı tam bunun için vardı. Canlıda squeeze birikince yeniden bakılacak.

**Ardışık kayıplar:** 1./2-3./4+ kayıp ve kazanç-sonrası gruplarının rejim
ortalamaları birebir aynı (vol20 0.0355-0.0374, adx 23.4-25.9). En uzun seri 14 işlem
— %56.5 kayıp oranıyla 1579 işlemde beklenen. Özel bir koşulun ürünü DEĞİL.

→ **YENİ FİLTRE EKLENMEZ.** Bu, karıştırma testinin (p=0.32) bağımsız üçüncü teyidi.

---

## 4d. KOMBİNASYON TARAMASI — ikili/üçlü birleşimler (2026-08-12)

Tek tek özellikler kapanmıştı; **birleşimler** hiç taranmamıştı. 1276 tekli/ikili/üçlü
hücre, sınırlar yalnız TRAIN üçlük diliminden, aday şartı n≥30 ve TRAIN z<−2.

```
ŞANSLA beklenen: ~1.0   ·   GERÇEKTE geçen: 2
```
**Şans düzeyinde.** Birleşimlerde de desen YOK.

Tek hayatta kalan: `adx:yüksek + yon:short + saat:00-05`
TRAIN n=30 R=−0.553 z=−2.86 → **TEST n=28 R=−0.003 (SIFIR, negatif değil)**.
Filtrenin öncülü örneklem dışında çürüdü. Walk-forward +$60 gösteriyor ama yılda ~16
işlem × σ_R 1.465 → üç yılda gürültünün σ'sı ~$46; **+$60 = 1.3σ**, yani gürültü.
1276 hücreden örneklem dışında doğrulanmayan birini seçmek overfitting'in tanımıdır.
REDDEDİLDİ.

**İKİ ARAÇ HATASI BULUNDU — ikisi de "bulgu yok" derken:**
1. `geri_donus` (kırılım sonrası kanala dönüş) taramaya sokulmuştu; o bilgi GİRİŞ
   ANINDA YOK, sonraki barın kapanışından geliyor → LOOKAHEAD. İlk taramanın 15
   adayının 8'i bu özelliği içeriyordu; çıkarılınca 2'ye düştü. Çıkarıldı.
2. "Şansla beklenen" sayısı hücrelerin gerçek ortalamasını SIFIR varsayarak
   hesaplanmıştı (~29). Doğru null "hücre popülasyondan farksız" (ort=+0.237) →
   beklenen ~1. Yanlış null, gerçek bir sinyali "gürültü" diye eleyecekti.

**DERS:** bugün bulunan araç hatalarının çoğu "bulgu var" değil **"bulgu yok"**
derken çıktı (tz uyuşmazlığı, yanlış null, çifte ölçek). Bir araç "yok" dediğinde de
gerçekten aradı mı diye bakmak gerekiyor.

**SORUNUN CEVABI:** giriş anında bilinebilen hiçbir koşul birleşiminde sistem negatif
beklenti üretmiyor. Gerçek zamanda tespit edilebilen tek aday (`gd:döndü`) giriş anında
bilinmiyor; bilgiyi almak bir bar beklemeyi gerektiriyor ve o üç yoldan da kaybettiriyor.

---

## 4b. Rafta bekleyen tek bulgu: sq_govde

**Ne:** squeeze kolunda, giriş mumunun gövde oranı `|close-open|/(high-low)` en üst
%20'deyse işlemi atla. Mekanizma: squeeze sıkışmadan çıkıştır; dev gövdeli mumda
girmek hareketin ZATEN olduğu anlamına gelir — tükenişe giriliyor.

**Ölçüm:** tam dönem +$76 · out-of-sample +$18 · walk-forward +$21 (3/3 yıl artı).
maxDD 26.4→24.7, en kötü ay hiçbir dilimde kötüleşmiyor.

**Neden uygulanmadı:** yılda ~$7 (kârın %1.8'i) ve `.env` değil KOD değişikliği
gerektiriyor. $203'lük hesapta bu takas kötü.

**Yeniden bakma koşulu:** bakiye $1000'i geçerse (aynı oran ~$37/yıl) ya da canlıda
yeterli squeeze işlemi birikip desen teyit edilirse.

---

## 4e. YENİ STRATEJİ ARAŞTIRMASI (2026-08-14) — ÜÇÜ DE REDDEDİLDİ

Kullanıcının detaylı brief'i: Liquidity Sweep+Reclaim · VWAP Mean Reversion ·
BB/Keltner Volatility Expansion. 1H rejim / 15M setup / 5M teyit / 1M timing,
walk-forward + OOS zorunlu, filtre A/B zorunlu.

### Önce VERİ (repoda yoktu)
Canlı coinler için yalnız 1 SAATLİK veri vardı; 15M/5M hiç yok. MEXC 5dk'yı derin
geçmişe TUTMUYOR (`veri_cek.py --probe`). Çözüm: Binance aylık dökümleri
(`veri_binance.py`) — 13 coin × 306.719 bar × 1065 gün, boşluk %0.
**Venue hipotezi SINANDI:** SOL Binance-vs-MEXC kapanış farkı |ort| 0.83bp,
%95 2.60bp, saatlik getiri korelasyonu **0.99976** → keşif için aynı seri.
Dosya adına venue gömüldü: `_bnc_` (Binance/keşif) vs `_fut_` (MEXC/karar).

### Sonuçlar (filtresiz baseline, ön-kayıtlı parametreler)
| strateji | n | ort R | **brüt edge** | maliyet/R | stop% |
|---|---|---|---|---|---|
| Sweep+Reclaim | 24.307 | −0.3283 | **−0.0103** | 0.318 | %0.81 |
| VWAP Reversion | 29.991 | −0.3920 | **−0.0105** | 0.381 | %0.64 |
| BB/Keltner | 9.824 | −0.5207 | **−0.0026** | 0.518 | %0.56 |

TRAIN/TEST/OOS üçünde de tutarlı · 13 coin ve 4 yıl homojen negatif.
**ÜÇÜNÜN DE BRÜT EDGE'İ SIFIR** (aralıklar sıfırı içeriyor). Maliyet iyi
stratejileri öldürmedi — edge yoktu. Sweep'te maker dolumu (kayma 0) varsayılsa
bile net −0.072R. Opsiyonel filtrelere GEÇİLMEDİ: popülasyon homojen sıfır,
kesilecek negatif alt grup yok (bugünkü kuralın gerek şartı sağlanmıyor).

### MOTOR DOĞRULANDI — bu olmadan yukarıdaki hükümler geçersizdi
Üç farklı strateji de tam sıfır verince asıl soru: "edge yok" mu, "motor kör" mü?
`edge_oracle.py`: KÂHİN kolu ileri barlara DOĞRUDAN bakıp TP'ye mi SL'e mi önce
değeceğini bilerek yön seçiyor. Sonuç **+1.3447R / WR %100**; kontrol grubu
(kör kâhin) **−0.7761R**. → Hat gerçek edge'i GÖRÜYOR, sıfırlar ölçüm hatası değil.

### YAPISAL BULGU — MALİYET DUVARI
15dk/5dk ölçekte yapısal stoplar %0.56-0.81 çıkıyor. 20.3bp gidiş-dönüş maliyet
bunun **0.32-0.52R**'si. Gerçek +0.2R'lik bir brüt edge bile NET NEGATİF olurdu.
Squeeze'in vol rejimi ayrımı mekanik kanıt:
| rejim | n | ort R | maliyet/R |
|---|---|---|---|
| çok DÜŞÜK vol | 466 | −1.1841 | **1.379** ← maliyet TEK BAŞINA risk biriminden büyük |
| normal vol | 9.358 | −0.4876 | 0.475 |
→ **Üretimdeki 1h/4h sistem kısmen bu yüzden çalışıyor: stopları %2-3,
maliyeti 0.10R.** Aynı fikirler alt dilime inince duvara çarpıyor.
→ Brief'in "regime-based switching" aşamasına GEÇİLMEDİ: kanıtlanmamış üç şeyi
birleştirmek dördüncü bir kanıtlanmamış şey üretir.

### Bugün araçlarda yakalanan üç hata (hepsi ÜRETİME ÇIKMADAN)
1. **Sentetik veri üreticim bozuktu** — bar `high=c+w, low=c-w, close=c` idi,
   yani kapanış HER ZAMAN barın tam ortasında (konum std=0). Mum ŞEKLİNE bakan
   her filtre böyle veride %100 elenir. edge_vwap "0 sinyal" verdi ve sebep
   stratejide sanıldı. Düzeltildi (`EL.sentetik`, konum std 0.296).
2. **rr_min kapısı SESSİZCE eliyordu** — edge_squeeze 217 adayı sessizce atıyordu.
   Sayaç eklendi; sebep aritmetik çıktı (yapısal SL aralığın karşı ucundaysa
   RR≈1.0, rr_min=1.5'i asla geçemez).
3. **İlk look-ahead testim GEÇERSİZDİ** — `swing_k=0` fractal penceresini tek
   elemana indiriyor, seviye "son 40 barın en düşüğü"ne dönüşüyor: GELECEĞE HİÇ
   BAKMIYOR. Hile sandığım şey hile değildi. Doğrusu `edge_oracle.py`.

---

## 4f. ANKOR VERİSİ SESSİZCE EZİLDİ (2026-08-14) — yapısal olarak kapatıldı

`ic_bar.py` kontrol testi ankoru üretemedi (1564/$1365.35 vs 1579/$1420.66).
Guard durdurdu; sebep ARAÇLARDA çıktı:

`fast_bt.load(source="mexc_futures")` penceresi **KAYAN**: `since = now − 1200 gün`.
Ve çektiğini `_save_cache` ile `data/{COIN}_fut_1h.csv`'ye **SESSİZCE YAZIYORDU**.
`kayma_denetim.py` MEXC verisi gerektirdiği için çalıştırılınca ankorun bütün veri
dosyalarını ezdi:
```
repodaki : 2023-04-06 → 2026-07-19
diskteki : 2023-05-02 → 2026-08-14      ≈1 ay kaymış
```
**Bar SAYISI ikisinde de ~28.799** olduğu için fark görünmedi. "Bar sayıları
eşleşiyor, veri aynı" çıkarımı YANLIŞTI — sayıya değil TARİH ARALIĞINA bakılmalı.
`data/*_fut_1h.csv` git'te TAKİPLİ, yani ankorun tanımı diskte değişmişti.

**DÜZELTMELER:**
1. `fast_bt._save_cache` artık mevcut dosyanın üzerine YAZMIYOR.
   Bilerek tazelemek için `VERI_TAZELE=1`. (Test edildi: koruma + tazeleme.)
2. `ic_bar.py` sapmada çıplak "SAPMA" demiyor; tarih aralığını ankorun
   beklediğiyle yan yana basıyor, `git status data/` gösteriyor, çözümü veriyor.

**Geri alma:** `git checkout -- data/`

⚠ Bugün ankor üzerine kurulan diğer sonuçlar ETKİLENMEDİ — hepsi ezmeden ÖNCE
koştu ve kontrol testini geçti (maker_giris, ankor_denetim, kombinasyon...).
Etkilenen tek koşu ic_bar'dı, o da guard sayesinde sonuç basmadan durdu.

---

## 4g. BAR İÇİ 5dk TEŞHİSİ (2026-08-14) — EKSEN KAPANDI

Kullanıcının fikri: 5dk veriyi yeni strateji değil, MEVCUT donchian'a FİLTRE olarak
kullan. `fake_kirilim` negatif alt grubu (−0.2488R) bulmuştu ama karar anında
tanıyamıyordu; 4 saatlik bar kapanırken içindeki 48 adet 5dk barı ZATEN kapanmış
olduğu için bar içi yapı karar anında BİLİNİR. Look-ahead yok, gerçekten yeni bilgi.

**n=943 donchian sinyali · 5dk kapsama %93 · bu sinyallerin ort R'si +0.2367**

| özellik | Q1 | Q2 | Q3 | Q4 | Q5 | z(uç) | negatif dilim |
|---|---|---|---|---|---|---|---|
| tepe_konum | +0.3615 | +0.1680 | +0.2245 | +0.2273 | +0.2018 | −1.05 | YOK |
| kirilim_ani | +0.2758 | +0.2198 | +0.2605 | +0.1778 | +0.2492 | −0.18 | YOK |
| ustunde | +0.1700 | +0.2676 | +0.4304 | +0.1895 | +0.1259 | −0.30 | YOK |
| geri_cekilme | +0.2055 | +0.1450 | +0.2585 | +0.3038 | +0.2706 | +0.44 | YOK |
| hacim_sonra | +0.2064 | +0.2186 | +0.0531 | +0.4107 | +0.2955 | +0.59 | YOK |
| son_ceyrek | +0.1818 | +0.2171 | +0.3890 | +0.1632 | +0.2319 | +0.34 | YOK |

**HÜKÜM: 30 hücrenin 30'u da POZİTİF. Tek bir negatif dilim yok, hiçbir z 1.05'i
geçmiyor.** Bar içi 5dk yapısı donchian sinyalinin kalitesini AYRIŞTIRMIYOR.
Bugünkü kurala göre (negatif alt grup = gerek şart) bu eksende filtre para
kazandıramaz. Bonferroni'ye bile gerek kalmadı — kesilecek aday yok.

**ASIL OKUMA — bu bir başarısızlık raporu değil:** kesilecek kötü grup YOK çünkü
KÖTÜ GRUP YOK. Donchian sinyalleri her dilimde pozitif; edge sinyalin KENDİSİNDE,
sinyaller arasında ayrım yapmakta değil. Bu, edge'in homojen ve sağlam olduğunun
kanıtı. Filtreyle iyileştirilememesinin sebebi de bu.

---

## 4h. 5dk ÇIKIŞ TESTİ (2026-08-14) — kapandı, ama İKİ KALICI BULGUYLA

`cikis_5dk.py` — ic_bar girişte filtrelemeyi kapatınca kalan varyant: 5dk'yı
ÇIKIŞTA kullan. n=946 donchian işlemi, ankor kontrolü birebir geçti.

### BULGU 1 — ANKOR ÇÖZÜNÜRLÜKTEN DE İYİMSER (kalıcı, çıkış testinden bağımsız)
| | n | ort R |
|---|---|---|
| ankor (4 SAATLİK barlarla) | 946 | +0.2360 |
| **aynı işlemler 5dk yolunda** | 946 | **+0.2117** |
| **fark** | | **−0.0243R/işlem** |

4 saatlik bar, bar-içi fitilleri göremiyor; 5dk çözünürlükte stoplar daha gerçekçi
tetikleniyor. Bu, ankorun 2b'de ölçülen şişkinliğinin ÜSTÜNE gelen ayrı bir kalem.
→ **Dürüst ankor tahmini: +0.190R (A3) − 0.024 ≈ +0.166R.**

### BULGU 2 — GEREK ŞART SAĞLANDI, YETER ŞART DÜŞTÜ
İlk kez gerçek zamanlı tanınabilen NEGATİF bir alt grup bulundu:
| grup | n | ort R | PF | WR |
|---|---|---|---|---|
| seviyeyi KAYBEDEN | 721 | **−0.1422** [−0.2309,−0.0535] | 0.77 | %33.0 |
| seviyeyi KORUYAN | 225 | **+1.3456** [+1.2052,+1.4859] | 11.42 | %84.0 |
| ayrışma | | **z = +17.56** | | |

Ama kuralı UYGULAYINCA her tamponda ZARAR:
| tampon | kesilen | toplam ort R | Δ vs taban |
|---|---|---|---|
| 0.00 | 721 | +0.1171 | **−0.0946** |
| 0.25 | 645 | +0.1307 | −0.0810 |
| 0.50 | 563 | +0.1637 | −0.0480 |

Monoton: kural ne kadar az keserse o kadar az zarar → tamponsuz limitte Δ→0.
Yani kuralın KENDİSİ zararlı, eşiği değil.

**NEDEN — ve bu bugünün en önemli dersi:** z=17.56'lık ayrışma bir ÖNGÖRÜ değil,
**DURUM TESPİTİ**. "Seviyeyi kaybetti" = "şu an ~0.44 ATR aleyhte" demek. Bir
işlemin ŞU AN zararda olduğunu bilmek, SONUNDA zarar edeceğini bilmek değildir.
Kaybeden grubun içinde seviyeyi kaybedip GERİ DÖNEN büyük kazananlar var; onları
kayıp anında kesmek 946 işlemde toplam −89.5R'ye mal oluyor.
KORUYAN grubun +1.3456 / WR %84'ü de bunu ele veriyor: "hiç aleyhe gitmemiş
işlem" zaten kazanan işlemdir — ölçüm büyük ölçüde totolojiyi ölçüyor.

**Tetik mesafesi 0.44±0.37 ATR** (ankor stopu 2.00 ATR) → bu kural sabit stoptan
farklı, gerçekten daha dar ve yapısal bir stop. Ve zararlı. sl_sweep.py'nin dar
stopları elemesiyle tutarlı.

→ Bugünkü iki parçalı kural en temiz kanıtını burada buldu: **negatif alt grup
GEREK ama YETER DEĞİL — o gruptan çıkmanın maliyeti grubun kaybından az olmalı.**
Burada grup −0.1422R kaybediyor, çıkmak −0.0946R/işlem (tüm portföye) mal oluyor.

---

## 4i. ⭐ CANLI OLAY KAYDI (2026-08-17) — +%100 koşu ve −%27 geri veriş

**KULLANICININ ANLATTIĞI (2 hafta sonra buradan devam edilecek):**
BTC 4h grafiğinde 62.239 → 79.539 (~%28) uzun yeşil mum serisi. Diğer coinler de
eşlik etti. Donchian bir haftada bakiyeyi ~2 katına çıkardı. Sonra tek sert kırmızı
mumda **açık 6 pozisyonun 6'sı birden stop oldu**; bakiye $380 → $278.

### ÖLÇÜ — bu bir ARIZA DEĞİL
| | |
|---|---|
| tepe → şimdi | $380 → $278.08 = **−%26.8** |
| ankorun öngördüğü maxDD | **−%26.4** |
| fark | **0.4 puan** |

Sistem tam olarak modelin söylediğini yaptı. Büyük hareket → büyük kazanç.
Dönüş → öngörülen büyüklükte drawdown. Panik gerektiren bir sapma YOK.

### KAYBIN İKİ PARÇASI — ve asıl soru
```
6 pozisyon TAM stop (−1R): 6 × %2.25 × $380 = $51.30   ← tasarlanmış, kaçınılmaz
gözlenen kayıp                              = $101.92
                                              ────────
geri verilen AÇIK KÂR                       = $50.62   ← ASIL SORU
```
Kaybın YARISI gerçek risk, YARISI hiç kilitlenmemiş açık kârdı. Pozisyonlar
yükselirken stoplar GİRİŞTE kaldı.

### KODDA NE VAR, NE KAPALI
`main.py:1071 _update_trailing_stops` MEVCUT ve `check_mexc_stopmove.py` probe'u
hazır. Ama:
1. `STOP_MOVE_ENABLED=false` (config.py:90) — probe hiç koşulmadı
2. **Daha önemlisi:** kod stop taşımayı YALNIZ `orb`/`ifvg` kollarına uyguluyor
   — ikisi de 2026-07-16'da EMEKLİ EDİLDİ. Yani aktif kollarda (donchian/squeeze/
   bb) bayrak açılsa BİLE hiçbir şey değişmezdi.

### ÖNCEKİ KANITLAR — trailing trend takipçisini ÖLDÜRÜYOR
main.py:1077-1088'deki denetim notları:
* `sr_breakout` (2026-07-13 denetimi): sabit PF **1.80** / +23.4R · trailing'li
  PF **1.39** / +7.1R, DD de kötü. *"Fixed stops let the 3R winner run."*
* BB mean-rev ve FVG'de BE **ölçülebilir şekilde zarar** veriyor.
* Kısmi TP (TP1/TP2): **her kolda DAHA KÖTÜ** — WR yükseliyor, toplam düşüyor.
* BE@1R yalnız ORB/IFVG'de işe yaradı (+5.5R/+3.0R).

→ Donchian'ın gerçekleşen R:R'si **2.36**. Parayı kazananları KOŞTURARAK
kazanıyor. Trailing/BE tam o mekanizmayı keser. **Önsel BU FİKRE KARŞI.**

### AMA KODUN KENDİ NOTU BİR EKSİK İŞ BIRAKMIŞ
main.py:1089: *"single-regime sample — re-verify on longer data when 2023/24 1m
is around."* Çıkış modeli kanıtı YALNIZ BTC 1dk 2025-05..2026-04 üzerinde.
**O veri ARTIK VAR**: 13 coin × 3 yıl × 5dk (veri_binance.py). Kodun istediği
doğrulama artık yapılabilir — ve bu "son kaybı düzeltmek" değil, kodun kendi
bıraktığı ödevi bitirmek.

### DÖNÜNCE DEĞERLENDİRİLECEK ADAYLAR (öncelik sırasıyla)

**1. PORTFÖY SEVİYESİNDE KÂR KİLİDİ — yeni, hiç test edilmedi**
İşlem-başına kısmi TP test edilip reddedildi ("her kolda daha kötü"). Ama bu
olayın sorunu İŞLEM seviyesinde değildi: 6 pozisyonun HEPSİNDE aynı anda büyük
açık kâr vardı ve hepsi birlikte buharlaştı. Kural şöyle olurdu:
*"toplam açık kâr bakiyenin %X'ini geçerse tüm pozisyonlarda stopu sıkılaştır /
bir kısmını al."* PORTFÖY durumuna koşullu — işlem durumuna değil. Bu ayrım
onu daha önce reddedilen testten FARKLI kılıyor. Ankor verisiyle ölçülebilir
(giriş/çıkış zamanları ve R elimizde).

**2. YÖNSEL KAPI — `yon_kapi.py` yazıldı, KOŞULMADI**
6 long'un 4'ü korelasyon grubunun dışındaydı (grup yalnız {BTC,ETH,SOL}).
Grubu genişletmek bu olayda 2-4 pozisyonu engellerdi: yükselişte daha az kazanç,
düşüşte daha az kayıp. Ölçüt zaten doğru seçilmişti: **drawdown-normalize kâr**.
Tek komut: `python3 yon_kapi.py local`

**3. DONCHIAN İÇİN BE/TRAILING — önsel KÖTÜ ama veri artık var**
sr_breakout kanıtı güçlü şekilde aleyhte. Yine de kodun istediği uzun-veri
doğrulaması yapılmalı ki eksen KAPANSIN. Düşük beklentiyle.

**4. HİÇBİR ŞEY — dürüst seçenek**
−%27, +%100'ün bedeli. İkisi AYNI mekanizma: kazananları koşturmak. Trailing
koyarsan iki tarafı birden kısarsın.

### ⚠ HÂLÂ AÇIK: MUHASEBE
Bu anlatı bile boşluğu KAPATMIYOR. İki rapor arası: defter PnL **+$8.37**,
bakiye **−$48.96**. Açık uPnL'in ($25.03) gerçekleşmesi hesaba katılsa bile
~**$32** açıkta kalıyor. Ve "ne ile başladık" sorusu üç farklı cevap veriyor
(defter $242.91 · MEXC transfer $209.05 · kullanıcı hafızası $178).
**Açık pozisyon 0 iken `python3 gercek_pnl.py` çalıştırılmalı** — uPnL
belirsizliği olmadan ölçüm yapılabilecek tek an buydu/bu.

---

## 4j. SESSİZLİK (2026-08-27) — "bot iki üç gündür işlem açmıyor"

**Loglar HALT hipotezini ELEDİ.** journalctl'de yalnızca `BB skipped:
regime=... is_weekend=False` var. `halt` yok, `cooldown` yok, `Correlation cap`
yok, `Max positions` yok. BB zaten hafta-sonu-only, o satırlar beklenen gürültü.

**Log'un kör noktası:** donchian `direction == 0` verince kod HİÇBİR ŞEY
yazmıyor. Yani grep boş dönmesi "sinyal yok" ile "sinyal engellendi" ayrımını
YAPAMIYOR. Bu yüzden `neden_sessiz.py` yazıldı — canlı veriden coin başına
kanal genişliği / kırılıma uzaklık / MTF kapısı yönü basıyor.

**Hipotez:** BTC 62.239→79.539 hareketinden sonra 40 barlık kanal
(40×4s ≈ **6.7 GÜN**) o hareketin TAMAMINI içine aldı. Kanal çok geniş, fiyat
ortasında, tetikleyecek bir şey yok. Zirve barları pencereden çıktıkça (~6-7
gün) kanal daralır ve sinyaller KENDİLİĞİNDEN döner.

Doğrulaması: `python3 neden_sessiz.py` → `kanal %` sütunu >%15 ve fiyat
ortadaysa bot bozuk değil, sadece ateşleyecek bir şey yok.

**⛔ BU HİPOTEZ ÖLÇÜLDÜ VE ÇÜRÜDÜ — bkz. 4k.** Sert hareketle sonraki sessizlik
arasında ilişki YOK (ρ=−0.0018, p=0.94); hatta en sert kuşakta boşluk en KISA.
Backlog kapandı: dağılım artık `sessizlik.py` ile ölçülü.

---

## 4k. SESSİZLİK ÖLÇÜLDÜ (2026-08-27) — `sessizlik.py`, İKİ HİPOTEZ ÇÜRÜDÜ

Sonunda "bot kaç gün sessiz kalır?" sorusunun SAYISI var. Ankorun 1579 işleminin
giriş zamanlarından ardışık boşluk dağılımı (3.24 yıl):

| kapsam | medyan | p90 | p95 | **max** | ≥4 gün | ≥5 gün | ≥7 gün |
|---|---|---|---|---|---|---|---|
| tüm kollar | 0.42g | 2.04g | 2.67g | **6.12g** | yılda 6.8 | yılda 1.5 | **hiç** |
| BB'siz (hafta içi) | 0.38g | 2.29g | 3.01g | **8.21g** | yılda 11.4 | yılda 3.7 | yılda 1.2 |
| yalnız donchian | 0.50g | 3.17g | 4.67g | **15.50g** | yılda 23 | yılda 13 | yılda 4.6 |

**Hafta içi doğru taban ORTADAKİ satır** (BB yalnız hafta sonu çalışır). 4-5 günlük
sessizlik ≈ 97.4-99.2 yüzdelik: **seyrek ama yılda ~11 kez oluyor. NORMAL.**

### ÇÜRÜYEN HİPOTEZ 1: "sert hareket kanalı genişletir, bot susar"
Benim hipotezimdi. **YANLIŞ.** Girişten önceki 7 günlük |BTC getirisi| ile sonraki
sessizlik arasında Spearman **ρ = −0.0018 (p = 0.94, n=1578)**. Kuşak tablosu TERS
yönü gösteriyor: en sert kuşak (|BTC 7g| %12.4) medyan boşluk **0.33g**, en sakin
kuşak (%0.6) **0.46g**. Sert hareket botu susturmuyor, hızlandırıyor.

### ÇÜRÜYEN HİPOTEZ 2: "sessizlik kötüye işarettir"
Boşluk ≥4 gün olduktan SONRAKİ işlem ort **+0.497R**, diğerleri +0.234R (z=+0.80).
Anlamlı değil ama işaret POZİTİF — sessizliği uyarı saymak için sebep yok.

### CANLI LOGUN AÇIKLAMASI
`Donchian skipped: SOL already holds a position` **arıza değil**. Donchian coinleri
zamanın **%32.2**'sinde açık pozisyonla kilitli (ort tutma 2.4-2.8 gün, max_hold
120 saat). Rastgele bir donchian sinyalinin ~1/3'ü bu yüzden elenir. MAX_POSITIONS=7
ise zamanın yalnız **%3.3**'ünde dolu (3.24 yılda 24 sinyal kaybı, %1.5).

### max_hold DENETLENDİ — HATA YOK
`_enforce_max_hold` primary_tf=1h sayıyor ama execution.py:839 donchian'a açıkça
`max_hold = 120` (saat) yazıyor = backtest'in 30×4s'i. squeeze/BB varsayılan 48 =
backtest 48. **Üçü de birebir.** Cooldown per-(sleeve:coin) 4 saat — tüm botu
susturamaz.

---

## 4l. YÖNSEL KAPI REDDEDİLDİ (2026-08-27) — `yon_kapi.py` çalıştırıldı

"Aynı rüzgâr ters eserse" sorusu. Araç kendini ankora karşı doğruladı (kapısız =
1579 / $+1420.66 ✓ birebir).

**ÖNCE BİR TESPİT: mevcut korelasyon kapısı BİR HİÇ.** `_CORRELATED_GROUPS` yalnız
{BTC, ETH, SOL} ve BTC işlem görmüyor → 2 üyeli kümede "en fazla 2" ASLA bağlamaz.
Ölçüldü: cap 2/3/4/5'te **kesilen işlem 0**. Ağustos'ta 6 pozisyonun birlikte
stoplanmasını engelleyecek hiçbir şey yoktu, çünkü kapı kapsam dışıydı.

**Grubu tüm coinlere genişletmek ölçüldü ve REDDEDİLDİ.** Ölçüt drawdown-normalize
kâr (kâr × maxDD_taban/maxDD_aday) = "aynı acıya katlanarak ne kazanırdık":

| kapsam | cap | işlem | kesilen | kâr | maxDD | en kötü ay | normalize | Δ |
|---|---|---|---|---|---|---|---|---|
| TABAN | — | 1579 | — | +1421 | 26.2 | −21.0 | 1421 | — |
| TÜM coinler | 2 | 917 | 686 | +706 | 22.6 | −16.3 | 816 | **−604** |
| TÜM coinler | 3 | 1161 | 442 | +1043 | 22.0 | −16.4 | 1239 | −182 |
| TÜM coinler | 4 | 1333 | 270 | +1213 | 24.0 | −20.0 | 1323 | −98 |
| TÜM coinler | 5 | 1454 | 149 | +1371 | 26.2 | −21.6 | 1371 | −50 |

**MONOTON.** Kapı ne kadar gevşetilirse o kadar az zarar veriyor; hiçbir ayarda kâra
dönmüyor. maxDD gerçekten düşüyor (26.2→22.0) ama kâr daha hızlı düşüyor.
**Mekanizma:** yönsel yığılma TRENDLİ dönemlerde oluşuyor — sistemin para kazandığı
dönem. Yığılmayı kesmek kârın kaynağını kesiyor. ic_bar'ın "30 dilimin 30'u da
pozitif" bulgusuyla aynı yere çıkıyor: donchian'ın kesilecek kötü alt kümesi yok.

**KARAR: genişletme YAPILMAYACAK.** "Altı long birlikte stoplanır" riski gerçek ama
fiyatı faydasından büyük. Kapanan eksen sayısı 23+ → **25+**.


---

## 4m. SAĞLIK KANITI (2026-08-27) — `saglik_kaniti.py`

4k istatistikti: "4-5 gün sessizlik dağılıma UYUYOR". Bu **'sorun yok' demek
değil** — sadece sessizliğin tek başına kanıt olmadığı demek. Bu araç farklı bir
soru soruyor ve cevabı SAYIM:

    SON N GÜNDE KAÇ SİNYAL OLUŞMALIYDI, KAÇ TANESİ AÇILDI?

**Loga güvenmiyor.** Canlı kod `direction == 0` iken hiçbir şey yazmıyor; boş log
"sinyal yok" ile "sinyal yutuldu"yu ayırt etmiyor. O yüzden sinyaller ÜRETİM
SINIFLARIYLA (DonchianStrategy / SqueezeStrategy + canlı MTF kapısı) sıfırdan
yeniden hesaplanıyor, sonra trades.db'deki GERÇEK girişlerle eşleştiriliyor.

Dört bağımsız kontrol: **A)** canlı .env ankorla aynı mı · **B)** borsa mumları
taze mi (bayat veri = sessizce kör bot) · **C)** sinyal yeniden hesabı ·
**D)** gerçek girişlerle eşleştirme + açık pozisyon yaşı vs max_hold.

Eşleşmeyen her sinyal için sırayla eleniyor: coin kilidi (one-per-symbol),
MAX_POSITIONS koltuğu, (sleeve:coin) cooldown. Hâlâ açıklanamayan varsa araç
"⛔ AÇIKLANAMADI" diyor ve o bar için hazır `journalctl` komutunu basıyor —
"arıza var" diye İDDİA ETMİYOR, elenen ve elenmeyen ihtimalleri sayıyor.

### ÖZ-TEST ZORUNLU — `python3 saglik_kaniti.py --dogrula`
Araç ancak replay'i ankorla örtüşüyorsa değerli. Öz-test ankorun ürettiği HER
girişin replay'in aday listesinde olmasını şart koşuyor; bir tanesi eksikse
`SystemExit` ile duruyor. **Çalıştırıldı: 11 coin, 84 ankor girişi, eksik 0. ✓**
(Aday sayısı daha büyük — occ uygulanmıyor, bu beklenen.)

### SMOKE-TEST GERÇEK BİR HATA YAKALADI
İlk sürüm ccxt yokken C bölümünde **"hiç sinyal yok — sessizliğin sebebi BU"**
diye YALANCI HÜKÜM basıyordu. defter_gercek/gercek_pnl ile aynı hata sınıfı.
Artık sert guard var: veri eksikse ya da trades.db yoksa `SystemExit(2)`, hüküm
YOK. "Bakamadık" ile "yok" bir daha karışmayacak.

### YAN BULGU: `DONCHIAN_MTF` varsayılanı `False`
`config.py:469` `_getbool("DONCHIAN_MTF", False)` ve `.env.example`'da hiç geçmiyor.
Canlı .env'de set edilmemişse **donchian MTF kapısı olmadan çalışıyor**, ankor ise
onu HEP uyguluyor. Sessizliğin sebebi değil (kapı yoksa DAHA ÇOK sinyal olur) ama
canlı ≠ ankor demek. Araç A bölümünde bunu yüzüne söylüyor — VPS'te bakılacak.

### ANKOR VERİSİNE DOKUNMAZ
ccxt'yi doğrudan, pencereli (220 gün) çağırır; `fast_bt.load`/`_save_cache` yoluna
hiç girmez, `data/` altına hiçbir şey yazmaz. 4f'deki kaza tekrarlanamaz.


---

## 4n. PARA EKLEME (2026-08-27) — `para_ekle.py`, ve KAYIT BİR FRENDİR

Kod okundu, mekanik net:

**Boyut EQUITY'den okunur, her girişte, canlı.** `execution.py:472`
`sizing_balance = equity` ve equity `fetch_balance({"type":"swap"})` ile MEXC'ten.
Yani **restart GEREKMEZ**; para vadeli cüzdana düşer düşmez sonraki giriş büyür.
Açık pozisyonlar etkilenmez (boyut girişte sabitlenir).

**⚠ Para VADELİ cüzdanda olmalı.** Bot yalnız swap cüzdanını okur. Spotta kalırsa
bot parayı GÖRMEZ.

### RİSK 1 — kaydetmezsen GÜNLÜK ZARAR FRENİ GEVŞER
`execution.py:238` ve `:473` günlük zarar tabanını
`_daily_starting_balance + _deposit_flow_since_baseline()` diye kuruyor. Akış
`deposit.py`'nin yazdığı `total_deposits` meta'sından okunuyor. **Kaydetmezsen**
taban eski kalır ama equity yükselir:

> taban $278, limit %35 → fren $180.7'de. $200 ekleyip kaydetmezsen equity $478
> olur, fren HÂLÂ $180.7'de → yeni sermayeye göre **−%62**'ye kadar iner.

Yani `deposit.py` süs muhasebe değil, **frenin parçası**.

### RİSK 2 — SABİT MARJ açıksa para hiçbir şey değiştirmez
`risk.py:57` `FIXED_MARGIN_USDT > 0` iken boyut `min(bakiye, sabit)`. Varsayılan
0.0 ve canlıda RISK_SCALE=1.125 kullanıldığına göre muhtemelen kapalı
(`config.py:522` ikisi birlikteyken uyarı basıyor) ama **VPS'te teyit edilmeli** —
araç A bölümünde söylüyor.

### RİSK 3 — oran aynı, DOLAR büyür
Ankor maxDD %26.2, en kötü ay %21.0. Bunlar ORAN; para eklemek değiştirmez.
$278'de −%26.2 = $73; $478'de = $125. Ağustos'taki −%26.8 $478'de $128 olurdu.

### `para_ekle.py` — iki adımlı, doğrulamalı
```
venv/bin/python para_ekle.py 200 --once     # durum + ne değişecek + uyarılar
#  ... MEXC'te SPOT → VADELİ transfer ...
venv/bin/python para_ekle.py 200 --sonra    # borsayı DOĞRULAR, sonra deftere yazar
```
`--sonra` equity artışını beklenenle karşılaştırır; tutmuyorsa **deftere hiçbir şey
yazmaz** ve sebepleri sayar (para spotta kaldı / transfer oturmadı / tutar yanlış).
Guard'lar: paper modu, `--once`/`--sonra` tutar uyuşmazlığı, ve **çift kayıt** —
arada `deposit.py` elle çalıştırıldıysa `total_deposits` değişmiş olur ve araç
durur. Bu sonuncusu tam da "ne ile başladık" sorusunun üç farklı cevap vermesine
yol açan hata sınıfını engelliyor (bkz. 4i ⚠ HÂLÂ AÇIK: MUHASEBE).

### YAN FAYDA
Daha büyük sermaye = min-notional yüzünden reddedilen sinyal azalır → canlı
işlem sayısı ankora YAKLAŞIR. Bu, canlı-ankor sapmasını küçültür.


---

## 4o. TELEGRAM RAPORU YANLIŞ SAYI GÖSTERİYORDU (2026-08-28) — DÜZELTİLDİ

Kullanıcı para ekledi, rapor bunun TAMAMINI "Gerçek kâr" diye gösterdi:
11:27 kâr $+82.64 → 19:10 kâr $+152.40. Artış **$69.76**; bakiye artışı da
**tam $69.76**. Yani bakiyeye giren her kuruş kâra yazıldı.

Aynı gün **üç farklı sayı "bakiye" etiketiyle** görünüyordu, arada tek işlem yok:

| saat | mesaj | sayı | ASLINDA NE |
|---|---|---|---|
| 03:00 | Daily Summary "Balance" | $283.29 | **yeni günün BAŞLANGIÇ equity'si** |
| 03:20 | heartbeat "bakiye" | $266.42 | **SERBEST bakiye** (kilitli marj hariç) |
| 11:27 | /status "Bakiye" | $280.51 | equity |

### DÖRT DÜZELTME (hepsi testli)

**1. heartbeat SERBEST bakiye okuyordu** — `main.py:1401` `get_balance()`.
Pozisyon açıkken kilitli marjı hariç tutuyor, yani /status'tan hep DÜŞÜK.
Artık `executor.current_equity()`; okunamazsa yanlış sayı basmak yerine
"⚠ equity OKUNAMADI" diyor. Ayrıca yatırılan sermaye + kâr da basılıyor.

**2. /status equity'i YENİDEN KURUYORDU** — `free + locked + uPnL`, kilitli marjı
`entry_price/leverage` ile YAKLAŞIKLAYARAK. Borsanın kendi equity'sinden sapabilir
ve günlük zarar freninin ölçüsünden farklı bir sayı gösterir. Artık önce
`get_equity()` (borsa gerçeği), okunamazsa yeniden kurulum yedek.

**3. Yatırılan sermaye GÖRÜNMÜYORDU.** /status artık `Yatırılan sermaye` satırını
da basıyor — eksik kayıt anında gözle yakalanır. Etiketler `Bakiye` → `Equity`.

**4. Günlük özetin "Balance"ı yanlış etiketti** — main.py oraya `start_equity`
gönderiyor. Artık `Yeni günün başlangıç equity'si` (telegram + ntfy).

### ASIL PANZEHİR: `_tutarlilik()` — İKİ BAĞIMSIZ KAYNAK
/status ve /balance artık iki kaynağı karşılaştırıyor:
```
iddia  = equity − yatırılan sermaye          (borsa + meta)
defter = Σ kapanan işlem PnL + açık uPnL     (trades tablosu)
```
Fark eşiği (max($5, sermayenin %2'si)) aşarsa rapor **kendi kendini suçluyor**:
"⚠ Defter uyuşmuyor — en olası sebep KAYDEDİLMEMİŞ para GİRİŞ/ÇIKIŞ". DB
okunamazsa SESSİZ kalır (yanlış alarm, sessizlikten kötü).

### `para_ekle.py --tespit` / `--kaydet`
Geçmişte kaydedilmemiş transfer için: `--tespit` MEXC transfer geçmişini
tarihli döker, deftere göre eksiği hesaplar. **Otomatik kayıt YAPMAZ** — köken
bakiyesinden ÖNCEKİ transferler `inception_balance`'ın İÇİNDE, ayrıca eklemek
sermayeyi çift sayar (4i'deki üç-farklı-cevap sorununun aynısı). Tutarı sen
seçip `--kaydet` ile işliyorsun.

### TEST: `tests/test_rapor_tutarlilik.py` — 8 iddia, run_tests.py'ye eklendi
equity borsadan mı okunuyor · get_equity yokken yedek yol · kaydedilmemiş $70
yakalanıyor mu · doğru kayıtta yanlış alarm yok · $2 sapma alarm üretmiyor ·
DB patlarsa sessiz · heartbeat artık `get_balance()` çağırmıyor · günlük özet
etiketi düzeldi. **7 dosya geçiyor.**


---

## 4p. KALDIRAÇ KADEMESİ ÇALIŞTIRILDI (2026-08-29) — **DAYANIKLILIKTA DÜŞTÜ**

Ön-kayıtlı barajı geçen TEK aday buydu. Tarama tamamlandı ve **reddedildi**.

**Ana tablo (taban: CAP1.5 · 10x sabit → 1579 işlem, $+1476, maxDD 26.4):**

| yapılandırma | Δ$ | maxDD | en kötü ay | tepe marjin | BAR |
|---|---|---|---|---|---|
| CAP1.5 · 10/15x | +0 | 26.4 | −20.5 | 82→**57** | ✗ Δ$ yetersiz |
| CAP2.0 · 10/15x | +56 | 26.3 | −20.3 | 67 | ✓ |
| CAP2.5 · 10/15x | +88 | 26.3 | −20.3 | 70 | ✓ |
| **CAP3.0 · 10/15x** | **+107** | **26.1** | −20.3 | 73 | ✓ |

4/4 yıl iyileşti, maxDD düştü, en kötü ay düzeldi, RED=0. Baraj geçildi.

### AMA: DAYANIKLILIK TARAMASI ÖLDÜRDÜ

| ek kayma | Δ$ | hüküm |
|---|---|---|
| 0bp | +107 | ✓ |
| 5bp | +66 | ✓ |
| **10bp** | **+25** | **✗ baraj altı** |
| 15bp | −15 | ✗ |
| 30bp | −138 | ✗ |

**Kazancın tamamı, kendi mekanizmasının belirsizliğinin İÇİNDE.** Kazanç
pozisyonları BÜYÜTMEKTEN geliyor (CAP 1.5→3.0 = ~2× nominal). Ölçülen 15.3bp
kayma ~$267 nominalde ölçüldü. ICP/NEAR/BCH gibi ince defterlerde nominali iki
katına çıkarmak 10bp ek kayma getirir mi? **Büyük ihtimalle evet** — ve o an iş
biter. Kazancı üreten şey, kazancı öldüren maliyeti de üretiyor.

**KARAR: CANLIYA ALINMIYOR.** Kapanan eksen 25+ → **26+**.
(Şart değişirse yeniden bakılır: canlı defterde büyük-nominal kayma ÖLÇÜLÜRSE
ve +10bp'nin altında kaldığı gösterilirse aday geri gelir.)

### ⚠ AYRI VE CANLI BİR BULGU: **İHL = 36, TABANDA**
Taban yapılandırmada 36 işlemin (%2.3) 2×ATR stopu likidasyon mesafesini
(10x'te ~%9.5) AŞIYOR. O işlemlerde **stop çalışmadan likide olunur**. Bu
adayın getirdiği bir şey değil — **bugün canlıda var**. Adaylar bunu artırmıyor
ama kimse azaltmıyor da.

Yönü ilginç: kaldıraç KADEMESİ tepe marjini %82→%57 düşürüyor (CAP1.5·10/15x,
Δ$=0 yani kâra dokunmuyor). İHL için gereken ise TERSİ — geniş stoplu işlemlerde
kaldıracı DÜŞÜRMEK. Ölçülmedi. **Backlog: "geniş stoplu %2.3'te kaldıracı 5x'e
indirmek ne kaybettirir?"** — kâr etkisi muhtemelen küçük, kuyruk riski gerçek.


---

## 4r. GENİŞ STOPLU %2.3 ÖLÇÜLDÜ (2026-08-29) — `genis_stop.py`, MALİYET ~SIFIR

4p'de "İHL=36 tabanda var, bugün canlıda" diye bayrak kaldırılmıştı. Ölçüldü.
Araç önce likidasyon KAPALIYKEN ankora karşı kendini doğruluyor
(1579 / $+1420.66 ✓ birebir), tutmazsa hüküm basmadan duruyor.

### CEVAP: 3.24 yılda **$+1.14** — yani sıfır, hatta LEHİMİZE

| | işlem | toplam$ | maxDD | en kötü ay |
|---|---|---|---|---|
| ANKOR (likidasyona hiç bakmıyor) | 1579 | +1421 | 26.2 | −21.0 |
| GERÇEK (likidasyon uygulanmış) | 1579 | **+1422** | 26.1 | −21.0 |

36 işlemin **25'i** gerçekten likidasyon seviyesine değdi. Ve likide olmak,
stopun çalışmasından **daha ucuz** çıktı.

### MEKANİZMA — risk tabanlı boyutlandırma sorunu ZATEN çözmüş
`nom = min(RISKF×bakiye/slp, CAP×bakiye)`. Stop %11 olunca nominal
$0.0225×190/0.11 = **$38.9**, 10x'te marjin **$3.89**.
- likidasyon (%9.5'te): marjin gider → **−$3.89**
- stop (%11'de) çalışsaydı: −1R = 0.0225×190 = **−$4.28**

Likidasyon zararı stoptan ÖNCE kapatıyor. Geniş stop → küçük pozisyon → küçük
marjin. Tehlike kulağa büyük geliyordu, dolar cinsinden yok.

| çözüm | LİK | Δ$ | maxDD | RED |
|---|---|---|---|---|
| taban (10x sabit) | 25 | — | 26.1 | 0 |
| (a) stop≥%9.5 ise alma | 0 | +24 | 24.8 | 0 |
| (b) kaldıraç kademesi (her varyant) | **0** | **−1** | 26.2 | **0** |

(a) barajın altında (+24 < +28) ama maxDD'yi 1.3 puan düşürüyor.
(b) likidasyonu tamamen bitiriyor ve **$1'e mal oluyor**, hiç RED üretmeden.

### KARAR: DEĞİŞİKLİK YAPILMIYOR
$1'lik fayda için işlem-bazında kaldıraç anahtarlama eklemek, MEXC'in açık
pozisyonda `set_leverage`'ı reddetme riskini karşılamıyor. **4p'deki bayrak
YANLIŞ ALARMDI** — kayda geçti, bir daha kovalanmayacak.

### ⚠ AMA BU ZARARSIZLIK BİR AYARA BAĞLI — KORUNMALI
Zararsızlığın tek sebebi boyutun RİSK tabanlı olması. `FIXED_MARGIN_USDT > 0`
yapılırsa (risk.py:57) boyut `min(bakiye, sabit) × kaldıraç` olur — stop
mesafesinden BAĞIMSIZ. O zaman geniş stoplu işlem TAM BOY açılır ve likidasyon
sabit marjinin tamamını götürür. **Değişmez kural: FIXED_MARGIN_USDT = 0.**
Ayrıca `MARGIN_MODE=isolated` olmalı; cross'ta likidasyon hesabın tamamını
tehdit eder (bu ölçüm isolated varsayar).

### ARAÇ İKİ KEZ KENDİNİ ELE VERDİ
1. İlk sürüm `mae >= likidasyon` diyordu ve **84 sahte likidasyon** ile
   **−$179.63'lük uydurma "gizli maliyet"** üretti. Çıktının kendisi ele verdi:
   stopu **%1.9** olan bir satır "likide oldu" yazıyordu — imkânsız, çünkü stop
   borsada duran bir emir, fiyat %1.9'a değince orada dolar. MAE stopun
   tetiklendiği BARIN TAMAMINI kapsadığı için o barın dibi likidasyonu geçiyor
   ve sahte sayılıyordu. Doğru kural İKİ ŞART: `slp >= lik` VE `mae >= lik`.
2. Tip hatası (giriş int ns, çıkış Timestamp) ve f-string tırnak hatası —
   ikisi de gürültülü çöktü, sessiz yanlış sonuç vermedi.


---

## 4s. SERMAYE DENKLEMİ KAPANDI (2026-08-29) — ve araç ÜST ÜSTE İKİ KEZ YANILDI

Borsanın transfer kaydı okundu. Sonuç:

| | |
|---|---|
| Borsa equity | **$341.36** |
| Vadeliye giren toplam (SPOT→FUTURES) | **$280.37** |
| **GERÇEK kâr** | **$+60.99 (+%21.8)** |
| Defterin iddiası | $+143.49 (+%72.5) |
| Aradaki fark | **$82.51 — kaydedilmemiş sermaye** |

Transferler: 06-09 $9.98 · 06-09 $1.00 · 06-15 $48.43 · 06-17 $45.24 (bunlar
botun ilk işleminden ÖNCE, toplam $104.65) · 07-12 $104.40 · 08-28 $71.32.

**`inception_balance` GÜVENİLMEZ.** Bot başlamadan $104.65 vadeliye geçmiş ama
inception $48.47 yazıyor (fark $56.18). Sebep muhtemelen main.py'nin "bogus
startup value" yolu: inception <$1 görülünce O ANKİ bakiyeyle EZİLİYOR.
Bu, 4i'deki "ne ile başladık — üç farklı cevap" sorusunun kaynağı.

**DÜZELTME: `total_deposits` $149.39 → $231.90** (`para_ekle.py 82.51 --kaydet`).
Ondan sonra defter borsayla aynı kâr rakamını verecek.

### ARAÇ İKİ KEZ YANLIŞ RAKAM VERDİ — ikisi de satır içi aritmetikten
1. **"$26.32 kayıt eksiği"** — YANLIŞ TABAN. inception'ın köken öncesi
   transferleri karşıladığını varsaydı; karşılamıyordu.
2. **"$456.09 sermaye / −$114.72 kâr"** — ÇİFT SAYMA. deposits + transfers +
   withdrawals toplandı. Ama aynı para İKİ KEZ görünüyor:
   `07-12 00:32 +104.40 deposits` (dışarıdan MEXC'e) ve
   `07-12 00:37 +104.40 transfers` (spot→vadeli). İki bacak, tek para.
   Çıktının kendisi ele verdi: aynı tutar, 5 dakika arayla, iki satırda.

**DOĞRU KURAL: sermaye YALNIZ `transfers` ile ölçülür.** Bota para ancak VADELİ
cüzdana geçince girer; spotta duran deposit'i bot görmez. deposits/withdrawals
artık yalnız BAĞLAM olarak listeleniyor ve eşleşen çiftler açıkça yazılıyor.

### YAPISAL ÖNLEM
Aritmetik `sermaye_denklemi()` saf fonksiyonuna çıkarıldı ve
**`tests/test_sermaye.py` onu GERÇEK MEXC verisiyle kilitliyor** (6 iddia:
çift sayma yok · köken ayrımı · inception çelişkisi yakalanıyor · gerçek kâr
$60.99 · düzeltme $82.51 değil $258.22 · transfer yoksa hüküm yok).
Araç artık satır içi hesap YAPMIYOR. **9 test dosyası geçiyor.**

### HÂLÂ AÇIK
`fetch_withdrawals` 0 kayıt döndü (7 günlük dilimlemeden sonra okunabildi) —
yani dışarı para çıkışı yok. Ama FUTURES→SPOT ters transfer olup olmadığı
kesin değil: MEXC `fromAccountType` parametresini yok sayıyor, yön kaydın
kendi alanında. 6 kaydın hepsi pozitif göründü. 89 günlük pencere botun ömrünü
(ilk işlem 06-18, en eski transfer 06-09) kapsıyor.


---

## 4t. SIRADAKİ EN BÜYÜK RAKAM (2026-08-29) — defter borsadan $62.80 FAZLA yazıyor

4s sermaye denklemini kapattı ve **daha büyük bir soru açtı**:

| | |
|---|---|
| Borsa: equity $341.44 − yatırılan $280.38 | **GERÇEK kâr $+61.06** |
| Defter: kapanan işlem PnL'i | **$+123.86** |
| **AÇIK** | **$62.80** |

Defter 2.5 ayda gerçek kârın **kendisinden fazla** sapmış. Yıllığa vurulursa
**~$300** — ankorun bu ölçekteki beklentisinin yarısı kadar. Bu artık bir
muhasebe detayı değil, **edge'in yarısı büyüklüğünde bir sızıntı**.

`kar_farki.py` farkı kalem kalem kapatmaya çalışır, hepsi BORSA kaydından:
1. **ÜCRET** — defter nominal×1bp yazıyor; gerçek dolumların ücreti (DURUM 2d
   ~2.5bp/yön ölçmüştü, ama tüm defter üzerinden hiç toplanmadı)
2. **FONLAMA** — defterde HİÇ kalemi yok
3. **ÇIKIŞ KAYMASI** — mutabakat yolu çıkışı SEVİYE fiyatından yazıyordu
   (bugün düzeltildi). Araç "seviyeye TAM eşit çıkış" oranını sayıyor: oran
   yüksekse defter gerçek dolumu değil seviyeyi yazmış demektir.
4. **KALAN**

**Hüküm kuralları** (önceki araçların dersleri kodda): okunamayan kaynak SIFIR
sayılmaz, dolum kapsaması %80 altındaysa hüküm verilmez, aynı para iki kez
sayılmaz. Açık pozisyon varsa uyarı basıp "pozisyon yokken tekrar çalıştır" der.

**Not:** `gercek_pnl.py` bu iş için ÇALIŞTIRILMAMALI — sermaye denklemini
`daily_stats.starting_balance` üzerinden kuruyor, o taban 4s'den sonra geçersiz
ve rakip bir YANLIŞ rakam üretir.


---

## 4u. BETA ÖLÇÜLDÜ (2026-09-06) — YÖN DEĞİL, **HAREKET ŞİDDETİ**

"Kaybettiğimiz dönemlerde neden kaybediyoruz, o dönemleri eleyebilir miyiz?"
sorusunun DÖNEM seviyesindeki cevabı. `beta_analiz.py` çalıştırıldı (ankora
karşı kendini doğruladı: 1579 / $+1420.66 ✓). 40 eşleşen ay.

### YÖN NEREDEYSE HİÇBİR ŞEY AÇIKLAMIYOR
| | |
|---|---|
| beta (piyasaya bağımlılık) | **+0.222** [%95: −0.093, +0.536] |
| R² (piyasanın açıkladığı) | **%4.8** |
| piyasa YUKARI aylar | +19.81% ort · %83 pozitif |
| piyasa AŞAĞI aylar | **+17.19%** ort · %76 pozitif |
| ayrışma | z = **+0.31** (yok) |
| LONG / SHORT | +0.2585R / +0.2176R — güven aralıkları iç içe |

Bot uzun-beta DEĞİL. Piyasa düşerken de kazanıyor.

### HAREKET ŞİDDETİ 2.3 KAT DAHA ÇOK AÇIKLIYOR
| | eğim | R² |
|---|---|---|
| işaretli getiri (yön) | +0.431 | %4.8 |
| **|getiri| (şiddet)** | **+0.431** | **%11.2** |

| hareket | ay | sistem ort | poz ay | toplam |
|---|---|---|---|---|
| BÜYÜK (\|ret\|>%12.5) | 20 | **+27.56%** | %85 | +551.3% |
| KÜÇÜK (\|ret\|≤%12.5) | 20 | **+9.82%** | %75 | +196.5% |

**2×2 tablo kesin:** büyük/küçük farkı HER İKİ satırda da büyük
(yukarı 29.15 vs 11.24 · aşağı 25.62 vs 7.70), yukarı/aşağı farkı her iki
sütunda da küçük. Yani belirleyici **şiddet**, yön değil.

**Yalnız donchian daha da keskin:** BÜYÜK aylarda **+24.21%**, KÜÇÜK aylarda
**+3.04%** — sekiz kat.

### SL'LER NEDEN SL OLUYOR — MEKANİZMA
Donchian bir kırılım takipçisi. Yatay/çırpıntılı piyasada fiyat kanalı kırar,
koşacak yer bulamaz, döner ve stopa gelir. Kaybettiğimiz dönem = piyasanın
**hareket etmediği** dönem. Yön hiç fark etmiyor.

### ⛔ AMA "O DÖNEMLERİ ELEYELİM" ÇALIŞMAZ
Araştırma kuralı 1: bir filtre ancak kestiği alt kümenin ortalama R'si
NEGATİF ise para kazandırır. Küçük-hareket ayları **+%9.82** (donchian tek
başına +%3.04) — yani **pozitif**. Kesecek zarar YOK; kesersek toplamın
%26'sını (+196.5%) hiçbir şey kazanmadan atmış oluruz.

### AÇIK KALAN TEK YOL: ELEMEK DEĞİL, **BOYUTLANDIRMAK**
Küçük-hareket dönemlerinde işlemi kesmek yerine RİSKİ KÜÇÜLTMEK yapısal olarak
farklı bir fikir ve HİÇ TEST EDİLMEDİ. Şartı var: şiddet **önceden** ölçülebilir
olmalı. Yukarıdaki ölçüm AYNI ayın |getirisi|ni kullanıyor — bu eşzamanlı,
öngörücü değil. Oynaklık kümelenmesi (volatility clustering) finansın en
sağlam olgularından biri olduğu için geçmiş oynaklık gelecek şiddeti tahmin
edebilir; ama bu VARSAYIM, ölçülmeden kullanılamaz.

⚠ `regime_sans.py` kötü AYLARIN önceden tahmin edilemediğini 10.000
permütasyonla göstermişti. Beta AÇIKLAYICI, ÖNGÖRÜCÜ DEĞİL.


---

## 4v. OYNAKLIK EKSENİ KAPANDI (2026-09-06) — ve 4u'nun tersini gösterdi

4u "belirleyici olan hareket ŞİDDETİ" dedi ve tek açık yol olarak "elemek
değil BOYUTLANDIRMAK"ı bıraktı. `oynaklik_kapisi.py` onu test etti (ankora
karşı 1579 / $+1420.66 ✓ birebir).

### [1] ŞİDDET ÖNCEDEN BİLİNEMİYOR
Girişten ÖNCEKİ 30 günlük pencerede ölçülen piyasa oynaklığı (rolling +
`shift(1)`, lookahead kilitli) ile işlemin R'si arasında:
**Spearman ρ = +0.0342, p = 0.1765, n = 1566 → İLİŞKİ YOK.**

### [2] VE DİLİM TABLOSU 4u'NUN TERSİNİ SÖYLÜYOR
| dilim | n | oynaklık | ort R | alt güven |
|---|---|---|---|---|
| Q1 (en sakin) | 311 | %1.83 | +0.2323 | +0.0634 |
| Q2 | 315 | %2.41 | +0.3264 | +0.1637 |
| **Q3 (orta)** | 313 | %2.83 | **+0.4029** | +0.2363 |
| Q4 | 312 | %3.36 | +0.1834 | +0.0237 |
| **Q5 (en oynak)** | 315 | %4.31 | **+0.0559** | −0.0966 |

**En iyi dilim ORTA, en kötü dilim EN OYNAK olan.** Aylık analiz "büyük
hareket iyi" diyordu; işlem seviyesinde tam tersi çıkıyor.

**Çelişki değil, açıklaması var:** aylık |getiri| EŞZAMANLI ölçülüyordu —
sistem hareketi yakaladığı için o ay büyük görünüyor; bu SONUÇ, öngörü değil.
İşlem öncesi yüksek oynaklık ise hareketin ÇOKTAN OLDUĞU anlamına geliyor;
oraya girmek GEÇ kalmak demek. 4u açıklayıcıydı, 4v öngörücü — ikisi farklı
soru ve cevapları da farklı.

Hiçbir dilim negatif değil → **eleme kural 1'e göre kesin ölü.**

### [3] BOYUTLANDIRMA DA ÇALIŞMIYOR — beşinin beşi düştü
| kural | kâr$ | Δ$ | maxDD | en kötü ay | NORM | Δnorm |
|---|---|---|---|---|---|---|
| TABAN | +1421 | — | 24.4 | −21.0 | 1421 | — |
| düşük vol'de 0.5× | +962 | −458 | **27.5** | −14.2 | 853 | −567 |
| düşük vol'de 0.75× | +1192 | −229 | 25.9 | −17.4 | 1124 | −296 |
| yüksek vol'de 1.25× | +1547 | +126 | 29.8 | −22.7 | 1266 | −155 |
| düşük 0.5× · yüksek 1.5× | +1215 | −205 | **39.6** | −21.2 | 750 | −670 |
| vol ile orantılı | +1317 | −103 | 33.8 | −21.1 | 952 | −469 |

**Ters yönde sürpriz:** sakin dönemde riski KISMAK drawdown'ı İYİLEŞTİRMİYOR,
KÖTÜLEŞTİRİYOR (24.4 → 27.5). Sakin dönemlerin istikrarlı küçük kârı
drawdown'ları yastıklıyormuş; onu kesince kuyruk daha çıplak kalıyor.

**KARAR: eksen KAPANDI.** "Kaybettiğimiz dönemleri önleyelim" sorusunun hem
eleme hem boyutlandırma cevabı ölçüldü ve ikisi de para kaybettiriyor.
Kapanan eksen **26+ → 28+**.

---

## 4w. ⚠ DÜZELTME: ANKORUN GERÇEK maxDD'si **%24.4**, %26.2 DEĞİL

4v çalışırken kendi araçlarım arasında tutarsızlık çıktı ve kovalandı.
Sebep tamamen equity eğrisinin SIRASI:

| sıra | maxDD | kâr |
|---|---|---|
| GİRİŞ sırasıyla | 26.18 | $+1420.66 |
| **ÇIKIŞ sırasıyla** | **24.43** | $+1420.66 |

Aynı işlemler, aynı kâr — tek fark sıralama. **PnL çıkışta gerçekleşir, yani
doğru olan ÇIKIŞ sırası.** `deployed_backtest.seat_select` zaten çıkışa göre
sıralıyor; ankorun gerçek rakamı **%24.4**.

`yon_kapi.py` ve `genis_stop.py` giriş sırasını kullanıyordu ve %26.2
raporluyordu. **Δ karşılaştırmaları ETKİLENMEDİ** (iki taraf da aynı yanlış
sırayı kullanıyordu, hükümler geçerli) ama MUTLAK rakam ~1.75 puan şişkindi.
İkisi de düzeltildi.

**Pratik sonuç:** DURUM'da maxDD %26.2/%26.4 geçen yerler ~%24.4 okunmalı.
Ağustos'ta yaşanan −%26.8 böylece ankorun beklediği en kötüden DAHA KÖTÜ
olmuş oluyor — teselli değil ama doğru olan bu.


---

## 4x. PORTFÖY KÂR KİLİDİ REDDEDİLDİ (2026-09-06) — 29. eksen kapandı

Ağustos kaybının hiç ele alınmamış yarısı: −$50.62 **geri verilen açık kâr**.
`kar_kilidi.py` bunu test etti — bar bar portföy simülasyonu, kötümser mark
(tetikleme bar kapanışıyla değil ALEYHTEKİ UÇLA), erken çıkışa ek maliyet.
Kuralsız hali ankora karşı doğrulandı: 1579 / $+1420.66 ✓, maxDD %24.4 (4w).

**13 adayın 13'ü düştü.** Öne çıkanlar:

| kural | Δ$ | maxDD | en kötü ay | Δnorm |
|---|---|---|---|---|
| TABAN | — | 24.4 | −21.0 | — |
| A) başabaş ≥%10 | **+42** | **24.3** | **−20.1** | +51 |
| B) takip zirve≥%10 geri %50 | +131 | 24.9 | **−23.0** | +102 |

**A) ≥%10 üç ölçütü de hafifçe İYİLEŞTİRDİ** — 29 eksende bunu yapan tek şey.
Ama barajı geçemedi (+%3.6 < %5). Ve tunelemeye kalkışmamak için iki sebep var:

### 1. DESEN MONOTON DEĞİL → GÜRÜLTÜ
Eşik büyüdükçe kural DAHA AZ tetikler. Gerçek bir mekanizma olsaydı Δ$ tek
yönde ilerlerdi. Gözlenen: **−280 / +42 / −92 / −2** — işaret dört kez
değişiyor. Bu, mekanizma değil örneklem gürültüsü imzasıdır.

### 2. BÜYÜKLÜK ZATEN GÜRÜLTÜNÜN İÇİNDE
σ_R=1.465 · eff=$4.27 · n=1579 → toplam kârın gürültü ölçeği **±$249**.
En iyi adayın kazancı **+$42 = 0.17σ**. Barajın istediği +$71 bile 0.29σ.
Yani bu tabloda hiçbir hücre sıfırdan ayrılamaz.

### HÜKÜM
"Geri verilen açık kâr" GERÇEK bir olgu — ama korumanın bedeli faydasından
büyük, ve ölçülen fayda zaten gürültü seviyesinde. **B) takip stopu özellikle
kötü:** kârı artırır gibi görünürken en kötü ayı −21.0'dan −23.0'a
KÖTÜLEŞTİRİYOR. Sebebi anlaşılır — geçici bir geri çekilmeyi gerçekleşmiş
zarara çeviriyor. Koruma diye eklenen şey kuyruğu uzatıyor.

**Kapanan eksen 28+ → 29+.**

---

## 4y. ARAMANIN DURUMU — dürüst özet (2026-09-06)

Kullanıcının sorusu: "kayıpları öngörmenin, azaltmanın bir yolunu bul."
29 eksen kapandı. Kategorik cevap:

| ne denendi | sonuç |
|---|---|
| İŞLEM seçmek (hangi sinyal kötü?) | ölü — kesilecek negatif alt küme YOK (ic_bar 30/30 pozitif) |
| DÖNEM seçmek (hangi piyasa hali?) | ölü — şiddet öngörülemiyor (ρ=+0.034, p=0.18) |
| YÖN sınırlamak | ölü — monoton kayıp, yığılma trendde oluşuyor |
| BOYUT ayarlamak (oynaklığa göre) | ölü — sakin dönemde kısmak maxDD'yi KÖTÜLEŞTİRİYOR |
| KÂRI kilitlemek (portföy) | ölü — fayda 0.17σ, desen monoton değil |
| KALDIRAÇ kademesi | ölü — +10bp ek kaymada buhar |

**Ortak mekanizma:** her denemede kesilen küme POZİTİF beklentili çıktı.
Sistemin kayıpları ayrıştırılabilir bir kusur değil, edge'in fiyatı.

### GERİYE KALAN DÜRÜST SEÇENEKLER (edge iyileştirmesi DEĞİL)
1. **RISK_SCALE'i düşürmek** — kârı ve drawdown'ı ORANTILI küçültür. Oranı
   iyileştirmez ama dolar cinsinden acıyı azaltır. Bu bir TERCİH kolu.
2. **Bakiyenin büyümesi** — aynı %24.4 daha büyük tabanda daha çok dolar ama
   hesap daha çok drawdown'a dayanır.
3. **Dokunmamak** — 29 eksenin gösterdiği şey bu.

### HÂLÂ AÇIK TEK ARAŞTIRMA MADDESİ
`main.py:1089` çıkış modelinin 3 yıllık veriyle YENİDEN doğrulanmasını
istiyor; veri artık var, hiç yapılmadı. Bu bir kayıp-azaltma vaadi DEĞİL,
sadece kapatılmamış tek defter maddesi.


---

## 4z. SABIRLI MAKER GİRİŞ (2026-09-06) — 30. eksen, ve ölçüm mekanizmayı ÇIPLAK GÖSTERDİ

Yeni yöntem üretme işinden mezarlığa karşı sağ çıkan TEK öneri. Yapısal olarak
farklıydı: 29 kapalı eksenin hepsi işlem KÜMESİNİ ya da BOYUTUNU değiştiriyordu,
bu ikisine de dokunmuyor — aynı işlemler, sadece daha ucuz giriş.

`sabirli_maker.py` ankor koluna karşı doğrulandı (1579 / $+1420.66 ✓).

### YAN BULGU: GERÇEKÇİ TABAN ANKORUN %8.9 ALTINDA
Ölçülen 15.32bp giriş kayması dahil edildiğinde portföy
**$+1420.66 → $+1294.54**. Kaymanın bedeli **−$126.12**. Bu, maker fikrinden
kazanılabilecek paranın ÜST SINIRI.

### DOLUM SORUN DEĞİL — TERS SEÇİM SORUN
4h penceresinde dolum oranı 10bp derinlikte bile **%94.4** (ön-kayıt barajı %42
fazlasıyla aşıldı). Ama portföy karar satırında DÜŞTÜ:

| derinlik | Δ$ | |
|---|---|---|
| 0bp | +75 | ✓ |
| 2bp | +53 | ✓ |
| 5bp | +26 | ✗ |
| **10bp (karar)** | **−9** | **✗** |

Desen MONOTON — gürültü değil. Aritmetiği açınca sebep çıplak:
```
%94.4 dolum → kaymanın %94'ü tasarruf   = ~+$119
gözlenen net                             =    −$9
→ dolmayan %5.6 (~56 işlem)              = ~−$128
   işlem başına −$2.28  ·  ortalama işlem +$0.90
```
**Kaçırılan her işlem 2.5 ortalama işlem değerinde.** Çünkü dolmayanlar
rastgele değil: limit ancak fiyat GERİ GELİRSE dolar, koşan kırılım geri
gelmez. Sabırlı limit sistematik olarak KUYRUĞU kaçırıyor — sistemin bütün
parasını kazandıran şişman kuyruğu.

0bp satırının "geçmesi" ALDATICI: 0bp "fiyat seviyeye değdi mi" demek, oysa
limit kuyruğun arkasında ve fiyatın seviyeyi GEÇMESİ gerekir. Ön-kayıt tam bu
yüzden 10bp'ye bağlanmıştı; gevşetilmedi.

### ⚠ KOVALAMA KOLU: SONUÇ ARTEFAKT, HÜKÜM DEĞİL
Ölçülen kusurun doğal çaresi denendi: kırılım koşarsa limiti iptal et, hemen
piyasaya geç. Tablo düştü (Δ$ −114 … −270) **ama bu sonuç GEÇERSİZ.**
Kanıt çıktının kendisinde: 2bp ve 10bp derinlik satırları BİREBİR aynı sonucu
verdi — derinlik parametresinin hiçbir etkisi yoksa dolum kontrolüne hiç
ulaşılmıyor demektir. Sebep: 1h barında fiyat hem +10bp hem −10bp gidiyor ve
kötümser beraberlik kuralım ("aynı barda ikisi de olursa kovalama say") her
seferinde kovalamayı seçiyor. Yani test "kapanışın 10-50bp üstünden piyasa
emri ver"i ölçmüş — kovalamayı DEĞİL.

**Kovalama ÇÜRÜTÜLMEDİ, TEST EDİLEMEDİ.** Doğru test bar-içi sıra ister.

### VE CANLI KOD KOVALAYAMIYOR
`execution.py:629` giriş yolu mum kapanışında tetikleniyor: ya 45sn (piyasa
yedekli) ya 600sn (**yedeksiz — dolmazsa işlem ATLANIR**). Bar-içi fiyat izleyip
piyasaya geçen bir mekanizma YOK. Kovalama mimari değişiklik ister.

Canlıda bugün uygulanabilir iki varyant ve ikisi de zayıf:
- `DONCHIAN_MAKER_ENTRY=true` → 45sn + piyasa yedeği (~$10/yıl, 2c'de ölçüldü)
- `anchor_is_level=True` → 600sn ama YEDEKSİZ, yani koşanları ATLAR — ölçüm
  o işlemlerin en değerlileri olduğunu gösterdi, dolayısıyla daha kötü.

### KARAR: eksen KAPANIYOR (30.), kovalama ASKIDA
`veri_pencere.py` yazıldı — **ilk sürümü çöktü, iki hatası da bendendi:**

  (1) **SESSİZ HATA.** `except Exception: yok += 1; continue` hatanın SEBEBİNİ
      yutuyordu. Bütün oturum boyunca "okunamayan kaynak sıfır sayılmaz" diye
      uğraşıp aynı tuzağa kendim düştüm.
  (2) **YALANCI SAYAÇ.** Coin tamamen başarısız olunca `continue` sayaç
      toplamasını atlıyordu → çıktı `TOPLAM: 0 alındı, 0 ALINAMADI` diyordu,
      oysa 147 deneme başarısızdı. Başarısızlığın kendisi gizleniyordu.

  **KÖK SEBEP:** MEXC derin 1dk geçmişi tutmuyor. `veri_binance.py`'nin
  docstring'i bunu ZATEN yazıyordu ("MEXC 5dk'yı derin geçmişe tutmuyor") —
  kontrol etmeden MEXC'e gittim.

  **DÜZELTİLDİ:** kaynak Binance aylık ZIP dökümlerine çevrildi, ilk hata TAM
  METNİYLE basılıyor, arka arkaya 3 hatada coin bırakılıyor, sayaçlar her yolda
  toplanıyor, hiç pencere alınamazsa çıkış kodu 1. Doğrulandı (ağ kapalı
  ortamda): `TOPLAM: 0 alındı, 21 alınamadı` + hata metni + kod 1.
  Venue ayrımı korunuyor: `{COIN}_bnc_pencere_1m.csv` (keşif verisi, `_fut_`
  değil); disk şişmiyor (yalnız sinyal pencereleri saklanıyor, ~2 MB/coin).

⚠ BU KONTEYNERDEN ÖLÇÜLEMEZ: hem MEXC hem data.binance.vision ağ politikasıyla
  kapalı (403 CONNECT, proxy status ile doğrulandı). VPS'te çalıştırılıp push
  edilirse kovalama 1dk sırayla ÖLÇÜLEBİLİR hale gelir.
Ödül tavanı $126/3.24yıl ≈ $39/yıl ($190 tabanda) olduğu için öncelik DÜŞÜK —
ama "çürütüldü" demek yanlış olur, "bakılmadı" doğru.


---

## 5a. ÇIKIŞ PARAMETRELERİ DOĞRULANDI (2026-09-07) — `cikis_tara.py`

`main.py:1089`'un yıllardır beklettiği doğrulama. 30 kapanan eksenin HEPSİ giriş
tarafındaydı; bu ilk çıkış-tarafı ölçümü. Makine doğrulaması ✓ BİREBİR
(1579 / $+1420.66) — **ama araç iki kez kendini durdurdu, ikisinde de haklıydı:**

1. `MEVCUT = (2.0, 2.0, 30)` yazmıştım; ankorun donchian RR'si **2.5**
   (`A.CFG["donchian"]`). Yanlış taban hücresiyle karşılaştırma yapılıyordu.
   Sabit artık kaynaktan okunuyor, elle yazılmıyor.
2. İşlem sayısı birebir çıktı ama kâr **$2.94** saptı. Sebep: `seat_select`
   içeride `sorted()` kullanıyor ve Python sıralaması **KARARLI** — aynı zaman
   damgalı işlemlerde koltuğu kimin kapacağını **giriş listesindeki sıra**
   belirliyor. Ankor `DONCH → SQZ → BB` sırasıyla birleştiriyor.
   **ANKORUN GİZLİ VARSAYIMI:** $1420.66 rakamı liste sırasına bağlı. Hata değil
   ama hiçbir yerde yazılı değildi. Canlıda da MAX_POSITIONS dolunca aynı
   keyfiyet var (`_entry_gate` + coroutine sırası); koltuk zamanın %3.3'ünde
   dolduğu için etkisi küçük ama SIFIR değil.

### ⚠ ÖNCE GÜRÜLTÜ ÖLÇÜLDÜ (koda başlamadan)
1σ = 1.465 × $4.27 × √1579 = **$249**. 48 hücrede saf gürültünün beklenen en
yükseği ≈ 2.78σ = **+$692**. Ankor $1421. → **en yüksek hücre KARAR DEĞİLDİR.**

### [B] WALK-FORWARD OOS — mevcut ayar KALIR
| yıl | seçilen | OOS $ | mevcut $ | fark |
|---|---|---|---|---|
| 2023 | (1.5,3.0,45) | +253 | +321 | −68 |
| 2024 | (1.5,3.0,45) | +435 | +457 | −23 |
| 2025 | (2.0,2.5,45) | +468 | +447 | +21 |
| 2026 | (1.5,3.0,30) | +216 | +195 | +21 |
| **TOPLAM** | | **+1372** | **+1421** | **−48** |

Uyarlanabilir seçim OOS'ta kaybetti → parametreler AYIRT EDİLEMEZ.
**Mevcut ayar savunulabilir** — bu bir başarısızlık değil, kanıt.

### [C] YÖN TUTARLILIĞI — havuzlanmış marjinal YANILTICIYDI
Havuzlanmışta `sl_atr` monoton görünüyordu. Yıl bazında:
- `sl_atr` en iyi uç: 3.0 / 2.0 / 1.5 / 1.5 → **düzensiz.** O pürüzsüzlük tek
  bir yılın baskınlığıydı (2025'te 1.5→$538 vs 3.0→$312).
- `max_hold`: 30 / 30 / 45 / 45 → **düzensiz.**
- **`rr`: 3.0 / 3.0 / 3.0 / 3.0 — dört yılın DÖRDÜNDE de monoton artan.**

### [D] rr TEK BAŞINA — ve "rr ayarı" ASLINDA BU DEĞİL
| rr | işlem | toplam$ | maxDD | en kötü ay | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|
| 2.5 (mevcut) | 1579 | +1421 | 24.4 | **−21.0** | +321 | +457 | +447 | +195 |
| 3.0 | 1540 | +1441 | 22.4 | −27.8 | +360 | +480 | +418 | +183 |
| 5.0 | 1498 | **+1614** | 19.1 | **−29.7** | +505 | +518 | +416 | +175 |

İzole OOS toplamda +$193 önde AMA **ön-kayıt DÜŞTÜ: en kötü ay −21.0 → −29.7.**

**Ve iki şey daha, ikisi de reddi güçlendiriyor:**
1. **Fayda TERS DÖNÜYOR.** Yıl bazında: +184, +61, **−32, −20.** Kazanç tamamen
   2023-24'ten; son iki yılda mevcut ayar ÖNDE.
2. **Bu bir "rr ayarı" değil.** Çıkış kompozisyonu ölçüldü:
   | rr | TP% | SL% | max_hold% | ort R |
   |---|---|---|---|---|
   | 2.5 | 24% | 51% | 25% | +0.238 |
   | 5.0 | **7%** | 51% | **41%** | +0.300 |
   TP oranı %24→%7. Yani "rr=5" pratikte **"TP'yi KALDIR, 5 gün tut ya da stop
   ol"** demek. Yapısal değişiklik, parametre ayarı değil.
3. Eğri ızgara sınırına kadar **DÖNMEDİ** — ön-kayıtta "dönmezse bu uyarıdır,
   müjde değil" yazmıştım. Mekanizmasız monotonluk ölçüm yapısına işaret eder.

### KALICI BULGU (reddedilen adaydan bağımsız)
Ortalama R, çıkışlar TP'den max_hold'a kaydıkça YÜKSELİYOR (+0.238 → +0.300).
**2.5R'lik TP kazananları erken kesiyor.** Bu mekanizma gerçek — ama onu
`rr`'yi büyüterek hasat etmek, en kötü ayı −%29.7'ye çıkarıyor.

**SONRAKİ ADIM (test edilmedi):** takip eden çıkış (trailing) — "kazananı erken
kesme"yi, "5 gün körlemesine tut"un kuyruk riskini almadan hasat edebilir.
⚠ Bugün trailing yalnız `orb`/`ifvg` için doğrulanmış (`main.py:1071`) ve
`STOP_MOVE_ENABLED=false`. Donchian'da 3 yıllık veriyle HİÇ denenmedi.

**KARAR: hiçbir parametre değişmiyor.** Kapanan eksen **30+ → 32+**
(3B ızgara + izole rr).


---

## 5b. TRAILING REDDEDİLDİ (2026-09-07) — 33. eksen, ve ÖNCEKİ BULGUYU DOĞRULADI

5a "2.5R'lik TP kazananları erken kesiyor" demişti (ort R +0.238→+0.300).
Doğal çare trailing'di. `trail_tara.py` ölçtü — makine doğrulaması ✓ BİREBİR.

**10 adayın 10'u düştü. Hiçbiri kâr artırmadı.**

| aday | işlem | Δ$ | maxDD | en kötü ay |
|---|---|---|---|---|
| TABAN (sabit SL/TP) | 1579 | — | 24.4 | −21.0 |
| BE@1R (canlı-doğrulanmış model) | 1628 | −175 | 19.5 | −28.8 |
| ATR trail 1.5× (TP duruyor) | 1982 | **−579** | 15.0 | −26.5 |
| ATR trail 2.0× (TP yok) | 1753 | −53 | 13.9 | −25.9 |
| ATR trail 3.0× (TP yok) | 1575 | −36 | 17.2 | −30.2 |
| zirveden 0.5R geri veriş | 2160 | −94 | 11.4 | −25.8 |

**Walk-forward OOS: −$365.** 2023 ve 2025'te hakem TABANI seçti; trailing
seçilen iki yılda da kaybetti (−255, −110).

### DESEN ÇARPICI VE ONUNCUSUNDA BİLE AYNI
**10 varyantın 10'unda da maxDD İYİLEŞTİ (24.4 → 11.4-20.6) ama en kötü ay
KÖTÜLEŞTİ (−21.0 → −23.9…−30.2).** İstisnasız. Trailing equity eğrisini
pürüzsüzleştiriyor — büyük drawdown'ı çok sayıda küçük gerçekleşmiş zarara
bölüyor — ama acıyı belirli aylarda YOĞUNLAŞTIRIYOR (birçok trail aynı anda
tetikleniyor). "Daha az drawdown" ile "daha az acı" AYNI ŞEY DEĞİL.

Ayrıca işlem sayısı trail sıkılaştıkça ARTIYOR (1579 → 2160): trailing erken
çıkıyor, `occ` erken serbest kalıyor, daha çok işlem giriyor. Yani "daha sık
işlem + daha düşük maxDD + daha az kâr + daha kötü ay" tek bir mekanizmanın
dört yüzü.

### sr_breakout BULGUSU DONCHIAN'DA DOĞRULANDI
`main.py:1078` sr_breakout için yazıyordu: *"Sabit stoplar 3R'lik kazananın
koşmasına izin veriyor"* (PF 1.80→1.39). Donchian'da da aynı çıktı. O kanıt
12 aylık tek rejimdendi; bu 3 yıl ve dört yıl bağımsız olarak aynı yönü veriyor.
`main.py:1088`'in istediği "daha uzun veriyle yeniden doğrula" **YAPILDI.**

### BİRLEŞİK HÜKÜM (5a + 5b)
"TP kazananı kesiyor" ölçümü **GERÇEK** — ama çaresi ne TP'yi büyütmek
(en kötü ay −29.7) ne de trailing (10/10 ret). Geriye tek açıklama kalıyor:
**donchian'ın kârı birkaç büyük koşudan geliyor ve o koşulara DOKUNAN her
mekanizma onları erken kesiyor.** 33 kapanan eksenin ortak deseniyle birebir.

**Kapanan eksen 32+ → 33+.**


---

## 5c. "DAHA FAZLA AL" — 34. eksen, ve İLK KEZ POZİTİF OOS (ama EDGE DEĞİL)

33 kapanan eksenin HEPSİ çıkarmak/korumak üzerineydi. Bu ilk EKLEMEK denemesi:
aynı coinde eş zamanlı birden çok pozisyona izin ver (donchian sinyallerinin
%32.2'si "coin dolu" diye eleniyordu — `sessizlik.py`).

⚠ Makine doğrulaması hatayı YAKALADI (oturumun 4. öz-yakalaması): ankor
`if i <= occ` ile ÇIKIŞ BARININ KENDİSİNİ de dolu sayıyor; `x > i` yazmıştım
→ 119 fazla işlem, $40 sapma. Doğrusu `x >= i`.

| coin başına | işlem | kâr$ | Δ$ | maxDD | **en kötü ay** |
|---|---|---|---|---|---|
| 1 (MEVCUT) | 1579 | +1421 | — | 24.4 | **−21.0** |
| 2 | 1884 | +1725 | +304 | 31.5 | **−38.8** |
| 3 | 1969 | +1884 | +463 | 28.5 | **−41.0** |
| SINIRSIZ | 2017 | +1847 | +426 | 27.8 | **−45.5** |

**Walk-forward OOS: +$332 — 34 eksende İLK POZİTİF SONUÇ.**

### AMA ÖN-KAYIT REDDEDİYOR, VE HAKLI
En kötü ay −21.0'dan **−38.8…−45.5'e** çıkıyor. Kullanıcı Ağustos'ta −%26.8
yaşadı ve sarsıldı; bu kural onu neredeyse İKİYE KATLIYOR. maxDD de 3-7 puan
bozuluyor. Ön-kayıttaki dört şarttan ikisi düşüyor.

**Bu, ön-kaydın neden dört şartlı olduğunun en net kanıtı:** yalnız kâra ve
OOS'a bakılsaydı, en kötü ayı iki katına çıkaran bir değişiklik ÖNERİLECEKTİ.

### RİSK-EŞLENMİŞ KARŞILAŞTIRMA — "EDGE Mİ, KALDIRAÇ MI?"
Sabit-oran modelinde PnL boyutla DOĞRUSAL: boyut f ile çarpılırsa hem toplam
kâr hem aylık kayıp f ile çarpılır. Her adayı **en kötü ayı tabanla eşitleyecek
kadar küçültüp** kârını kıyaslayınca:

| aday | ham kâr | kötü ay | ölçek f | eşitlenmiş kâr | vs taban |
|---|---|---|---|---|---|
| TABAN | +1421 | −21.0 | 1.00 | **+1421** | — |
| 2/coin | +1725 | −38.8 | 0.54 | +934 | **−487** |
| 3/coin | +1884 | −41.0 | 0.51 | +965 | −456 |
| SINIRSIZ | +1847 | −45.5 | 0.46 | +852 | −568 |

**Aynı acıya eşitlenince ÜÇÜ DE tabanın ALTINDA.** Yani +$332'lik OOS kazancı
EDGE DEĞİL, sadece KALDIRAÇ — ve mevcut ayardan daha VERİMSİZ bir kaldıraç.
Aynı riski almak isteyen zaten `RISK_SCALE`'i büyütür ve daha iyisini alır.

### KAYIT: CANLI KISIT (geçseydi bile)
MEXC **netted** modda aynı coindeki ikinci pozisyon AYRI işlem değil, mevcudu
BÜYÜTÜR → SL/TP tek seviyeye düşer. Backtest'teki "iki işlem" canlıda "tek
büyük işlem" olurdu. Yani bu kural canlıda test edildiği gibi DAVRANMAZDI.

**Kapanan eksen 33+ → 34+.** Kör nokta da kapandı: sistem ne kesilerek ne de
çoğaltılarak iyileşiyor.


---

## 5d. ⭐ UYUM TESTİ GEÇTİ (2026-09-07) — ankorun zemini KANITLANDI

Kullanıcının fikri ve doğru fikirdi: bu dönemin verisini backtest'e sok, aynı
dönemin GERÇEK işlem geçmişiyle karşılaştır. 34 eksen boyunca her şey ANKORA
KARŞI ölçülmüştü ama ankorun canlıyla örtüştüğü uçtan uca HİÇ doğrulanmamıştı.

⚠ İLK KOŞU %22 EŞLEŞME VERDİ — ve bu ARACIN hatasıydı. `A.gen` `idx[i]` yazıyor
= pandas resample bin etiketi = BARIN BAŞLANGICI; canlı ise bar KAPANINCA
giriyor. Donchian 4h → tam 4 saat fark, ±2 saatlik pencereyle ASLA eşleşemezdi.
Aynı konvansiyonu `veri_pencere.py` ve `sabirli_maker.py`'de doğru yazmıştım,
burada unuttum. **Hatayı ele veren şey aynı çıktıdaki toplam sayılardı:**
beklenen 68 işlem vs gerçekleşen 67, beklenen $59 vs gerçekleşen $50 — gerçek
bir ayrışmada bunlar tutmazdı. Araç artık düşük eşleşmede ÖNCE KENDİNDEN
şüphelenmeyi söylüyor.

### DÜZELTİLMİŞ SONUÇ
| | |
|---|---|
| eşleşme | **48/67 = %72** (eşik %70, hüküm verilebilir) |
| canlı ort R | +0.1004 |
| backtest ort R | +0.1082 |
| FARK | **−0.0078 ± 0.0632 (%95) · z = −0.24** |

**✓ SİSTEMATİK SAPMA YOK.** Canlı, backtest'in dediğini yapıyor.
İşlem sayısı 69 beklenen / 71 gerçekleşen; kâr $59 beklenen / $50 gerçekleşen.

### ⚠ TESTİN ÇÖZÜNÜRLÜĞÜ — ne kanıtlandı, ne kanıtlanmadı
Güven aralığı **±0.063R**, ankorun edge'i **+0.166R**. Yani edge'in %38'inden
BÜYÜK bir sapma yakalanabilirdi; **%20'lik bir aşınma GÖRÜNMEZDİ.** 48 işlem
bunun için az. "Büyük bozukluk yok" kanıtlandı, "edge tam beklendiği kadar"
KANITLANMADI. Risk artışının ölçülü olmasının sebebi bu.

### `external_close` — ÖLÇÜLDÜ VE KAPANDI
En büyük 5 sapmanın DÖRDÜ `external_close` — SL'e de TP'ye de varmadan ERKEN
kapanmış pozisyonlar (canlı −0.08R vs backtest −1.00R gibi). Tasarlanmış bir
çıkış yolu DEĞİL. Toplamda zarar ettirmemiş (hem kazananı hem kaybedeni kısıyor,
net ≈0) ama mekanizma AÇIKLANMADI. `cikis_dagilim.py` ölçtü: **4 işlem (%6), toplam +$0.50.** İkisi 08-22'de
(Ağustos düşüşü günü — muhtemelen günlük fren ya da elle kapatma), ikisi
dağınık. Etkisi yarım dolar; **kovalamaya değmez, konu kapandı.**

### TEMİZ DÖNEM ÇIKIŞ PROFİLİ (67 kapanan işlem)
| çıkış | adet | pay | ort$ |
|---|---|---|---|
| sl_hit | 33 | %49 | −5.02 |
| tp_hit | 23 | %34 | **+10.82** |
| max_hold | 7 | %10 | +1.86 |
| external_close | 4 | %6 | +0.12 |

Kazanan, kaybedenin **2.16 katı** kazandırıyor; WR %34. Bir kırılım sisteminin
olması gereken profili ve ankorun PF 1.42'siyle tutarlı.

### RİSK KARARI: `RISK_SCALE` 1.125 → **1.4** — ✅ CANLIDA UYGULANDI
Doğrulandı (2026-09-07 19:27 UTC): `.env` satır 81 `RISK_SCALE=1.4`,
`load_config()` → `max_risk_per_trade = 0.028` (0.02 × 1.4), ve
`Started btc-bot.service` sed'den SONRA. Çalışan bot 1.4 ile işlem açıyor.
**Geri dönüş:** `.env`'de `RISK_SCALE=1.125` + `systemctl restart btc-bot`.
Ön-kayıtlı kural uygulandı: "sapma yok çıkarsa 1.4 savunulabilir".
| | şimdi | 1.4'te |
|---|---|---|
| beklenen aylık | ~$29 | ~$36 |
| en kötü ay | −$65 | **−$81** |
| maxDD | −$75 | −$93 |
Ağustos'ta yaşanan −$102'nin ALTINDA kalıyor. 2x önerilmedi: test çözünürlüğü
%20'lik aşınmayı göremiyor.
⚠ Bu artış EDGE'İ İYİLEŞTİRMİYOR, aynı eğriyi %24 büyütüyor. Kâr da acı da.


---

## 5e. COIN EVRENİ ŞANS MI? (2026-09-08) — ankorun BÜYÜKLÜĞÜ kısmen seçim artefaktı

Kullanıcı "daha iyi çalışan coinler bulabilir miyiz" diye sordu. O eksen zaten
kapalıydı (DURUM 4: coin eklemek en kötü ayı −21 → −58.8 yapıyor; "geçmişte iyi
gideni seç" walk-forward'da TEST'te −$254). **Ama soru hiç sorulmamış bir şeyi
ima ediyordu: mevcut 12 coin de yıllar önce TAM O YÖNTEMLE seçildi. Öyleyse
ankorun kendisi de o artefaktı taşıyor olabilir.**

### ÖLÇÜM 1 — rastgele evrenler (⚠ KUSURLU, olduğundan güçlü gösteriyor)
21 coinden rastgele 12 seçilen 300 evren: ort $+547 · medyan $+545 · en iyi
$+1,032. Mevcut evren **$+1,421** — 300'ün 300'ünden iyi.
⚠ Bu test KUSURLU: coinleri kollara RASTGELE atıyor (VET'i donchian'a, SOL'u
hafta-sonu BB'sine). Saçma atamalar rastgele tabanı zayıflatıyor. Rakam şişkin.

### ÖLÇÜM 2 — her coin KENDİ KOLUNDA sıralama (keskin olan bu)
| kol | canlıdakilerin sıraları | ort sıra | rastgele beklenti |
|---|---|---|---|
| donchian | **[1, 2, 3, 4, 5, 7, 10]** | **4.6 / 21** | 11.0 |
| squeeze | [1, 3, 5, 12] | 5.2 / 21 | 11.0 |

Donchian'da **ilk beşin beşi de canlıda.** Evren büyük ölçüde geçmiş
performansa göre seçilmiş. `coin_expand` bu prosedürün ileriye taşınmadığını
zaten göstermişti.

### RAHATLATICI YARISI — edge GERÇEK, seçim onu BÜYÜTMÜŞ
Donchian sıralamasında **21 coinin 18'i POZİTİF** (+$226 … +$21); yalnız LTC,
ETC, XMR negatif. Yani strateji geniş tabanlı çalışıyor. Seçim edge'i
YARATMADI, **büyüttü**. Kaba ölçek: mevcut 7'nin tek başına toplamı $1,026,
ortanca 7'ninki $470 → oran ~0.46.

### SONUÇ: ankorun YÖNÜ güvenilir, BÜYÜKLÜĞÜ şişkin
İleri beklenti ankorun %50-100'ü arasında bir yerde. Hangi noktada olduğu
BİLİNMİYOR ve aşağıdaki hesap yüzünden uzun süre bilinmeyecek.

---

## 5f. ⚠ KAÇ İŞLEMDE NE ANLAŞILIR — "300 işlem" iddiam EKSİKTİ

Defalarca "~300 işlemde edge'i gürültüden ayırırız" dedim. Doğru ama EKSİK:
o sayı **edge VAR MI YOK MU** sorusu için.

| soru | gereken n (2σ) | süre (~40 işlem/ay) |
|---|---|---|
| edge var mı, yok mu (0.166 vs 0) | **312** | ~8 ay |
| edge TAM mı YARIM mı (0.166 vs 0.083) | **1246** | **~31 ay** |

**Yani 5e'nin sorduğu soru — seçim primi kayboldu mu — canlı veriyle
2-3 YIL boyunca cevaplanamaz.** Bu, riskin ne kadar olması gerektiği
tartışmasında bilinmesi gereken en önemli sınırlama.

### KARAR: `RISK_SCALE` 1.4'TE KALIYOR — kullanıcının BİLGİLİ kararı
5e ölçüldükten sonra 1.125'e dönmeyi önerdim; kullanıcı 1.4'te kalmayı seçti.
Gerekçe sunuldu, karar tekrarlandı, uygulanıyor. **Bu bir ihmal değil, bilgili
bir tercih** — ve gerekçem burada kayıtlı ki ileride bakan yanılmasın.

### İZLEME KURALI (ankorda ayların %80'i pozitif)
| olay | ankor altında olasılık | ne yapmalı |
|---|---|---|
| 2 ay üst üste negatif | %4.0 | not et, bekle |
| **3 ay üst üste negatif** | **%0.8** | **DUR ve bak** |
| 4 ay üst üste negatif | %0.2 | sistem bozuk say |
| equity < $180 | — | DUR (kırmızı çizgi, 5d) |

3 ay üst üste negatif, ankor doğruysa 125 ayda bir olur. Gerçekleşirse
"şanssızlık" değil, edge'in beklenenden zayıf olduğunun işaretidir — ve
1246 işlem beklemeden elde edebileceğimiz TEK erken uyarı budur.


---

## 5g. BB KOLU GENİŞLETME REDDEDİLDİ (2026-09-08) — 35. eksen, LTC GERÇEKTEN ÖZEL

`coin_expand.py` kodu okundu: `CFG`'de yalnız donchian ve squeeze var, yani
"coin ekleme kapandı" hükmü **BB kolunu hiç kapsamamış**. DURUM'da BB'nin
HAFTA SONU olma gerekçesi belgeliydi, **tek coin olma gerekçesi DEĞİLDİ**.
On aylık kayıtta bu boşluk kimseye çarpmamış.

⚠ SEÇİM YAPILMADI — testin en önemli kuralı. coin_expand'ı öldüren şey
coinler değil "geçmişte iyi gideni seç" PROSEDÜRÜYDÜ (TRAIN muhteşem,
TEST −$254). Ana aday bu yüzden **HEPSİNİ EKLE**.

| aday | BB coin | kâr$ | Δ$ | maxDD | en kötü ay |
|---|---|---|---|---|---|
| TABAN (yalnız LTC) | 1 | +1421 | — | 24.4 | −21.0 |
| HEPSİ (seçimsiz) | 21 | +1233 | −187 | **51.3** | **−49.9** |
| BÜYÜK-KAP (yapısal) | 11 | +1405 | −16 | 47.6 | −41.4 |

Walk-forward OOS: **−$198**.

### MEKANİZMA — donchian'dakinden KESKİN
Tek tek coinlerin çoğu POZİTİF (ETH +120, LTC +114, XMR +80, XRP +73,
XLM +57, ICP +50). Öldüren şey coinler değil, **maxDD'nin ikiye katlanması**.
Sebep: **BB ortalamaya dönüş, yani DÜŞEN fiyatı ALIYOR.** Hafta sonu
çöküşünde 21 coin birden "aşırı satılmış, al" diyor ve hepsi çöküşün İÇİNE
birlikte giriyor. Korele değil, **TERS korele** — strateji en kötü anda üst
üste biniyor. DURUM'daki "BB'nin kısıtlaması doğru yerde" notu artık
gerekçeyle değil ÖLÇÜMLE doğrulanmış oldu.

### EŞ ZAMANLILIK SINIRI — teşhis doğruydu, çare yetmedi
Ölçümden doğan hipotez: sorun havuzun genişliği değil eş zamanlılık. Havuz 21
coin, aynı anda en fazla K pozisyon (SEÇİM DEĞİL — zaman önceliği).

| K | BB işlem | kâr$ | Δ$ | maxDD | en kötü ay |
|---|---|---|---|---|---|
| 1 | 303 | +1246 | −174 | **19.9** | −29.2 |
| 2 | 579 | +1243 | −178 | 21.8 | −31.9 |
| 3 | 842 | +1280 | −140 | 25.7 | −25.5 |

**Teşhis doğruydu: K=1'de maxDD 24.4 → 19.9 İYİLEŞTİ.** Ama kâr düştü.
Sebep: LTC tek başına **+$0.70/işlem** (+$114/163); havuzun ortalaması bunun
dörtte biri. "İlk sinyal kazanır" kaliteyi korumuyor, **SEYRELTİYOR**.

### HÜKÜM: LTC GERÇEKTEN ÖZEL — üç ayrı yoldan ölçüldü
hepsi · büyük-kap · eş zamanlılık sınırlı → üçü de aynı yere çıkıyor.
BB'nin değeri coin çeşitliliğinde değil, LTC'nin kendine özgü hafta sonu
davranışında. **Kapanan eksen 34+ → 35+.**

---

## 5h. STRATEJİ DIŞINDA KALAN TEK KALEM: ÜCRET

35 eksen kapandıktan sonra "daha fazla para" için stratejide bir şey kalmadı.
Ama canlı ölçümlerden çıkan bir kalem var ve **stratejiye hiç dokunmuyor**:

| | yıllık (canlı ölçümlerden) |
|---|---|
| net kâr | ~$351 |
| **ÖDENEN ÜCRET** | **~$104** (borsanın kendi kaydından, `kar_farki.py`) |
| brüt kâr | ~$455 |
| **ücretin brüte oranı** | **%23** |

Ücret indirimi olursa: **%20 indirim → yılda +$21 (+%6 net kâr)** ·
**%50 indirim → +$52 (+%15)**. Aynı işlemler, aynı risk, aynı drawdown.

⚠ MEXC'in ücret kademelerini ve MX token indirimini BURADAN doğrulayamam
(ağ kapalı). Kullanıcının hesabında bakılması gereken bir şey; strateji
araştırması değil, hesap ayarı. Ama 35 eksende bulunamayan "daha fazla para"
ya en yakın duran kalem bu.

⚠ `kar_farki.py`'deki "0.15bp/dolum · liste oranıyla tutarlı" satırı
ŞÜPHELİ: nominal MEXC dolum `amount` alanından hesaplanıyor, o da KONTRAT
sayısı olabilir (coin miktarı değil) → payda ~20x şişik olabilir. Ücretin
MUTLAK tutarı ($25.39) borsanın kendi kaydı olduğu için doğru; ORAN yorumu
düzeltilmeli.


---

## 5i. ⚡ MAKER GİRİŞ AÇILIYOR (2026-09-09) — 2g'deki deney NİHAYET başlatıldı

2g'de tasarlanan deney on aydır bekliyordu ("bulgu güçlü ama açmak bir KARAR").
Kullanıcı "bulmadan gelme, emir emirdir" dedi; kanıt yeniden okundu ve
hatırladığımdan GÜÇLÜ çıktı — 2f'deki DOĞAL DENEY canlı defterden:

| kol | yürütme | giriş kayması | n |
|---|---|---|---|
| **bb/mean_rev** | **maker limit + 45sn piyasa yedeği** | **−2.95bp** [−6.37, +0.47] | 11 |
| donchian | `force_market` | **+15.32bp** [+0.26, +30.38] | 21 |
| squeeze | `force_market` | +4.18bp | 12 |

**FARK +14.22bp [+3.87, +24.57] — sıfırı DIŞLIYOR.** Maker kolu sinyal
fiyatından DAHA İYİ giriyor. Dolum oranı %73 [%46–%99]; başabaş ~%42 ve
**güven aralığının ALT UCU (%46) bile başabaşın üstünde.**

### DEĞER — RISK_SCALE 1.4 ile İKİYE KATLANDI
donchian kayma bedeli ankor tabanında $39/yıl. Bugünkü ölçek
(equity $306 × RISKF 0.028) / (190 × 0.0225) = **2.00×** → **$78/yıl**.
| kurtarma varsayımı | yıllık kazanç |
|---|---|
| muhafazakâr (%50) | **+$39** |
| bb'nin ölçülen %73 dolumuyla | **+$57** |
Kıyas: ücret indirimi %20 → +$21, %50 → +$52. **Maker girişi en az onun kadar,
ve bu BENİM uygulayabildiğim tek kalem.**

### NEDEN GÜVENLİ — aşağı yön SINIRLI
`place_limit_order(..., fallback_market=True)`: limit 45sn'de dolmazsa PİYASAYA
düşülüyor. Yani **hiçbir işlem kaçmıyor**, yalnız giriş fiyatı değişiyor.
Bu, `sabirli_maker.py`'de reddedilen 4 SAATLİK sabırlı limitten YAPISAL OLARAK
farklı: orada ters seçim kuyruğu kaçırıyordu (dolmayan %5.6 işlem başına
−$2.28), burada pencere 45 SANİYE ve yedek var.

### ⚠ TAŞIMA RİSKİ — dürüst kayıt
Kanıt bb'den (ortalamaya dönüş) geliyor, donchian ise KIRILIM. bb'de fiyatın
limite dönmesi NORMAL yol; donchian'da dönmesi kırılımın ZAYIF olduğu anlamına
gelebilir. 45sn'de bu etki küçük ama SIFIR DEĞİL. Deneyin sebebi tam bu.

### ⚠ MODELLENMEMİŞ: KISMİ DOLUM
`place_limit_order` kısmi dolumu bookluyor, üstüne piyasa yedeği ATMIYOR
(bilinçli — çift maruziyeti önlüyor). Pozisyon hedeflenenden küçük kalabilir.
Zararlı değil (risk de orantılı küçülür) ama backtest'te modellenmedi.

### GERİ ALMA ÖLÇÜTÜ — ÖN-KAYITLI, GEVŞETİLMEYECEK
**4–6 hafta sonra `python3 kayma_denetim.py`:**
- donchian dolum oranı **%42'nin altına düşerse** → bayrak KAPAT
- donchian kayması **squeeze'e göre iyileşmezse** → bayrak KAPAT
squeeze KONTROL GRUBU olarak `force_market` kalıyor — aynı dönem, aynı piyasa,
aynı momentum mekaniği. bb'nin ortalamaya-dönüş yanlılığı böylece elenir.

**Uygulama:** `.env` → `DONCHIAN_MAKER_ENTRY=true` + restart.
**Geri alma:** aynı satır `false`.


---

## 5j. ÜCRET EKSENİ KAPANDI (2026-09-09) — "ucuz coin" YOK, ankor varsayımı GEÇERLİ

Kullanıcı "bazı coinler mesela NEAR zaten 0fee" dedi. **Vadeli dolum kayıtları
bunu DOĞRULAMADI:** 12 coinin 12'si de ücret ödüyor, NEAR 13 dolumda $1.1973.
Muhtemelen MEXC'in SPOT kampanyası ya da sona ermiş bir promosyon.

### COIN BAZINDA ORAN — yapısal fark YOK
| medyan | en düşük | en yüksek |
|---|---|---|
| **7.97 bp/tur** | BCH 6.93 | ETH 10.44 |
Hiçbiri diğerlerinin yarısı değil. `$/dolum` sütunundaki farklar (XLM 0.208 vs
XRP 0.065) tarife değil **POZİSYON BÜYÜKLÜĞÜ** farkı. **Coin bazlı ücret
arbitrajı fikri KAPANDI** — ve bu, aşırı-uydurma riski taşımayan tek coin
ayrımı olduğu için denenmeye değerdi.

### ⚠ ORAN ÖLÇÜMÜNÜN KENDİSİ GÜVENİLMEZ — İKİ TARAFLI HATA
| yöntem | bp/taraf | hatası |
|---|---|---|
| defter-tabanlı (bu araç) | 7.97 | payda EKSİK — pencere öncesi açılan işlemlerin nominali yok |
| borsa-tabanlı çapraz kontrol | **0.16** | payda FAZLA — `amount` KONTRAT sayısı olabilir |
| **DURUM 2d/2f** (iki uç kalibrasyonu) | **0.51–0.99** | **en güvenilir** |
| MEXC listesi | maker 1.0 / taker 2.0 | — |

0.16bp MEXC'in kendi maker oranının altıda biri — mümkün değil. Yani aracın
"✓ ankor varsayımı geçerli" hükmü DOĞRU sonuca ŞÜPHELİ bir sayıdan ulaştı.
**Üçgenleme sonucu:** gerçek oran 0.5–1bp/taraf bandında, ankorun
`FEE=0.0001` varsayımı gerçeğe yakın → **DÜZELTME GEREKMİYOR.**

### SAĞLAM KALAN: MUTLAK TUTAR
$30.29 / 89 gün = **~$124/yıl**. Bu dolar cinsinden, paydaya ihtiyacı YOK.
İndirim kolu: %20 → +$25/yıl · %50 → **+$62/yıl**.
SOL ve XRP satırlarında `+MX` ücret görünüyor, diğer onunda YOK → **MX ile
ücret ödeme KISMEN aktif.** Hesapta tam açılırsa indirim 12 coine yayılır.

---

## 5k. ✅ İKİ DEĞİŞİKLİK CANLIDA (2026-09-09)

| ayar | eski | yeni | değeri |
|---|---|---|---|
| `RISK_SCALE` | 1.125 | **1.4** | ölçek (edge değil) |
| `DONCHIAN_MAKER_ENTRY` | false | **true** | **+$39–57/yıl** |

Maker yolu doğrulandı: `main.py:745` `anchor_is_level=False` →
`execution.py:629` **45sn + piyasa yedeği**. Yedeksiz 600sn yoluna GİTMİYOR,
yani hiçbir işlem kaçmıyor; yalnız giriş fiyatı değişiyor.

### ⏰ 4–6 HAFTA SONRA — ÖN-KAYITLI KONTROL (gevşetilmeyecek)
```
python3 kayma_denetim.py
```
- donchian dolum oranı **%42'nin altına düşerse** → `DONCHIAN_MAKER_ENTRY=false`
- donchian kayması **squeeze'e göre iyileşmezse** → `DONCHIAN_MAKER_ENTRY=false`
squeeze KONTROL GRUBU olarak `force_market` kalıyor.

### KULLANICI TARAFINDA KALAN TEK KOL
MEXC hesabında **MX ile ücret ödeme**yi tam aç → +$25–62/yıl, sıfır risk,
sıfır strateji değişikliği.

**Toplam beklenen kazanç: +$64–119/yıl** — mevcut net kârın (~$351) **%18–34'ü**,
hiçbiri risk artırmadan (RISK_SCALE ayrı bir karar ve ayrı kayıtlı).


---

## 5l. KAYMA DENETİMİ ÇALIŞTI (2026-09-09) — İKİ SÖYLEDİĞİM DÜZELTİLDİ

`kayma_denetim.py`, n=87, **eşleşme %100**.

### ① SABİTLER ÖLÇÜLDÜ VE GÜNCELLENDİ (kod değişti)
| sabit | eski | yeni | gerekçe |
|---|---|---|---|
| `live_verify.ANK_SLIP_BP` | 13.4 | **15.85** | ölçüldü n=54, [%95: +8.34, +23.37] |
| `live_verify.TAKER_FEE` | 0.0002 | **0.0001** | iki uçtan kalibre edildi |

13.4 aralığın İÇİNDEYDİ (yanlış değildi) ama "ölçülen" diye duruyor, ölçüm
KODU yoktu — aracın kendi hükmü bunu *"bugünkü en büyük metodoloji açığı"*
diye işaretledi. TAKER_FEE ise DURUM 2g'de "yan bulgu (ayrı iş)" diye not
edilip yapılmamıştı; iki kat şişkin ücret beklenen-vs-gerçekleşen kıyasında
**SAHTE sistematik sapma** üretiyordu.

Ücret modeli iki uçtan DOĞRULANDI: zorunlu-maker kol 0.547bp (beklenen 0.500),
zorunlu-taker kollar 0.933bp (beklenen 1.000) → **"maker %0 / taker 1bp"**.

### ② ⚠ "BÜYÜDÜKÇE ORAN DÜŞER" MODELİM DESTEKLENMEDİ
Nominal aralığı **$59 … $513 (8.7×)** — kapsam guard'ının istediği 2×'in çok
üstünde, yani test GEÇERLİ.
| dilim | n | ort nominal | ort kayma |
|---|---|---|---|
| küçük | 29 | $95 | 11.67bp |
| orta | 29 | $163 | 15.84bp |
| **büyük** | 29 | **$278** | **3.35bp** |

Spearman +0.0987, **p=0.36 → ETKİ YOK.** Üstelik en büyük dilim EN AZ kayıyor.

**Muhtemel sebep — ve bu testin sınırı:** nominal bağımsız bir değişken DEĞİL.
`nom = RISKF×equity/slp` yani BÜYÜK nominal = DAR stop = SAKİN an. Sakin anda
spread de dar. Yani "büyüklük" ile "oynaklık" iç içe geçmiş; test bunları
ayıramıyor.

**Yıllık projeksiyondaki "her ikiye katlanmada edge'in %20'si gider" modeli
BU VERİYLE DESTEKLENMİYOR.** O model bir duyarlılık analizinden çıkarsanmıştı,
ölçümden değil — kullanıcıya ölçülmüş gibi sunmuştum, YANLIŞTI.
⚠ Ama ölçüm yalnız **$513 nominale kadar** geçerli. $4,000 equity'de nominal
~$3,850 olur; o bölge hakkında VERİ YOK. "Etki yok" değil, "bu aralıkta
görünmüyor".

### ③ ⚠ MAKER GİRİŞ KAZANCINI ABARTTIM — ters seçim ÖLÇÜLDÜ
Doğal deney güçlü duruyor: bb (maker) **−1.58bp** vs donchian+squeeze (market)
**+12.56bp**, fark **+14.14bp [+7.61, +20.67]**. Aracın kendi tahmini: her iki
momentum kolunu maker'a almak **~$74/yıl**.

**AMA aracın kendi çekincesi kritik:**
> BB bir ORTALAMAYA DÖNÜŞ kolu — limiti fiyatın GERİ GELDİĞİ yere koyuyor,
> dolum LEHİNE yanlı. donchian/squeeze MOMENTUM; fiyat limitten KAÇAR.
> **BB'nin oranı donchian için bir ÜST SINIRDIR, tahmin değil.**
> `maker_giris.py` ölçtü: limit **kazanan işlemlerde %9, kaybedenlerde %27**
> doluyor.

Dolum oranları: bb **%64** [%39–%89] · başabaş ~%42 (2bp) … ~%26 (10bp).
**Nokta tahmini başabaşın üstünde ama CI'nin alt ucu (%39) ALTINDA. n=14 ile
kesin konuşulamaz.**

→ Kullanıcıya verdiğim **"+$39–57/yıl"** rakamı, BB'nin oranının donchian'a
taşınacağını varsayıyordu. **O bir ÜST SINIR.** Gerçek değer sıfıra yakın,
hatta hafif negatif olabilir. Deneyin ve geri alma ölçütünün sebebi TAM BUDUR.

### DEĞİŞMEYEN
Deney doğru kurulmuş: aşağı yön **piyasa yedeğiyle sınırlı** (hiçbir işlem
kaçmıyor), squeeze **kontrol grubu** olarak `force_market` kalıyor, geri alma
ölçütü ön-kayıtlı. 4–6 hafta sonra `kayma_denetim.py` tekrar çalıştırılıp
donchian'ın KENDİ dolum oranı okunacak — BB'ninki değil.


## 5. Riski ne zaman artıracağız

**CEVAP: ARTIRMIYORUZ.** İki bağımsız sebep, ikisi de ölçüldü (risk_kademe.py).

**(a) Eski tetik ULAŞILAMAZDI — geri alındı.**
Önce şöyle yazılmıştı: "200 işlem VE alt güven sınırı 0.15'in üstünde."
İki şartın birlikte sağlanabilirliği hiç hesaplanmamıştı. Ölçüldü: **σ_R = 1.465**,
ort R 0.237 → gürültü sinyalin ~6 katı. n=200'de, gerçek edge ankor kadar iyi olsa
bile alt sınır **+0.034** (0.15'in çok altında).
Gereken n: ort R 0.237 → **1,089 işlem (35 ay)** · 0.20 → 3,298 (106 ay) ·
0.18 → 9,161 (296 ay) · 0.1096 (canlıda görülen) → **ASLA**.
Ulaşılamaz bir tetik, "asla artırma"nın süslü hâlidir.

**(b) Artırmak MEDYANI DEĞİŞTİRMİYOR, sadece kumarı büyütüyor.**
24 ay, ayda $100 katkı, canlı edge senaryosu:

| yapılandırma | %10 | MEDYAN | %90 | en kötü ay | zarar riski |
|---|---|---|---|---|---|
| sabit 1.125 (bugün) | $2,506 | **$6,377** | $18,414 | −%29.5 | **%11** |
| 6. aydan sonra 1.25 | $2,322 | **$6,488** | $20,555 | −%32.9 | %13 |
| 6. aydan sonra 1.50 | $1,940 | **$6,481** | $25,304 | −%40.7 | **%17** |
| 12. aydan sonra 1.50 | $1,990 | **$6,411** | $23,663 | −%34.2 | %17 |

Medyanlar aynı. Alt uç düşüyor, üst uç yükseliyor, en kötü ay ağırlaşıyor,
zarar riski %11 → %17. Kademeyi geciktirmek de değiştirmiyor (6. ay ≈ 12. ay).

**MEKANİZMA:** CAP'e takılanların ort R **+0.4597**, takılmayanların **+0.2056**.
Dar stoplu işlemler iki kat iyi. Risk arttıkça CAP bu İYİ işlemleri daha çok kesiyor
(%12 → %23); büyüyen şey ortalama kaliteli işlemler, kısıtlanan en iyileri.
(Aynı mekanizma CAP 1.25→1.5'in neden işe yaradığını da açıklıyor: kırpmayı azalttı.)

**YERİNE GEÇEN KURAL — kanıt beklemek yerine bozulma izle:**
1. `live_verify` her ay çalışsın (sentinel otomatik yapıyor).
2. Canlı R, ankor güven aralığının İÇİNDE kaldığı sürece sistem sağlıklı → dokunma.
3. Alt sınır sıfırın ALTINA düşer ve orada kalırsa → dur ve incele.
4. Risk artışı istatistikle değil **bakiye eşiğiyle** değerlendirilsin: bakiye
   **$1,000'i geçtiğinde** yeniden bakılır. Gerekçe: küçük hesapta artırmanın tek
   gerekçesi "edge kanıtlandı" olurdu ve o kanıt 35 ay sürüyor; bakiye eşiği ise
   ulaşılabilir ve kuyruğu mutlak dolar cinsinden anlamlı kılıyor
   (−%35'lik bir ay $203'te $71, $1,000'de $350).

---

## 6. Aylık rutin

Ayın sonunda, sırayla:

```bash
cd /opt/bot2
python3 live_verify.py      # canlı gerçekten ankorla uyumlu mu
python3 hiz_analiz.py       # işlem hızı ve tutma süresi normal mi
python3 ayar_dogrula.py     # ayarlar hâlâ doğru mu
```

Bakılacaklar:
- `live_verify [1]`: ankor güven aralığının İÇİNDE mi → evetse sorun yok
- `hiz_analiz`: oran ~0.8-1.2 arası normal, |z|>2 ise incele
- `ayar_dogrula`: son satır `✓ AYARLAR DOĞRU`

`sentinel` kuruluysa bunu ayda bir kendisi yapıp Telegram'dan haber verir.

---

## 7. Bir şeyler ters giderse

**Kod bozulduysa:**
```bash
cd /opt/bot2 && bash rollback.sh --kontrol   # önce kuru çalışma
cd /opt/bot2 && bash rollback.sh             # sonra geri dön
```

**`.env` bozulduysa:** `rollback.sh --snapshot` yedekleri `.env.kopya` içeriyor.
```bash
ls /opt/bot2-yedek/                          # yedekleri listele
```

**Bot çalışmıyorsa:**
```bash
systemctl status btc-bot
journalctl -u btc-bot -n 100 --no-pager
```

**Durdurmak istersen:** Telegram'dan elle duraklat. Loglarda artık gerçek sebebi
yazıyor (`manual pause via Telegram`), günlük zarar limitiyle karışmaz.

**Kırmızı çizgi (2026-09-07'de GÜNCELLENDİ):** eski $130 çizgisi ~$190
bakiyeye göreydi; sermaye $280.38, `RISK_SCALE` 1.4 oldu. Yeni çizgi:

  **equity $180'in altına inerse DUR ve bak.**

Gerekçesi: $184.63 temiz dönem çıpası. Oranın altına inmek "temiz dönemde
kazanılan her şey geri verildi VE eklenen sermaye yeniyor" demektir — bu artık
normal drawdown değil. 1.4 ölçekte beklenen maxDD ~%34, yani $306'dan ~$200'e
inmek HÂLÂ NORMAL; müdahale çizgisi onun altında olmalı ki normal dalgalanmada
paniğe kapılmayalım.

⚠ Aylık −$81 (en kötü ay) ve −$93 (maxDD) 1.4 ölçekte BEKLENEN rakamlardır.

---

## 8. Bugün (2026-08-12) düzeltilen üç hata

Üçü de strateji değil — sistemin kendisi hakkında **yanlış şey söyleyen** yerlerdi.

**BB kolu oynaklıkla risk büyütüyordu.** Hedefi %9'a ayarlıydı, o kadar yüksek ki
hiç devreye girmiyor ve boyutu sadece tavan belirliyordu. Sonuç: stop genişledikçe
risk büyüyordu (%1.87 → %5.62). Artık %2.25'te sabit.

**Sentinel bayat bakiye okuyordu.** `daily_stats.ending_balance` gün başında
`starting_balance` ile aynı yazılıyor ve hiç güncellenmiyor. Sentinel bunu "bakiye"
diye raporluyordu. Artık defterden yeniden kuruluyor.

**Halt mesajı yalan söylüyordu.** Sebebi ne olursa olsun "daily loss limit" yazıyordu;
elle duraklatma bile öyle görünüyordu. Artık gerçek sebep yazılıyor.

---

## 5m. `ayar_dogrula.py` iki yerden bozuktu (2026-09-09)

`RISK_SCALE`'i 1.125 → 1.4 yaptık ama doğrulayıcıyı güncellemedim. Bölüm 6'daki
aylık rutin bu betiği koşmayı söylüyor; koşulsa **canlı DOĞRUYKEN** iki ayrı
`✗` verecekti. Aylık rutinde yalancı alarm veren doğrulayıcı, doğrulayıcı
değildir — insan onu görmezden gelmeye başlar ve gerçek arızayı da kaçırır.

**Hata 1 — ezberlenmiş risk rakamı.** `BEK` sözlüğü `0.0225` yazıyordu
(`MAX_RISK_PCT 0.02 × RISK_SCALE 1.125`). Canlı artık `0.028`.
→ Beklenen değerler artık `.env` tabanı × `RISK_SCALE` ile **TÜRETİLİYOR**.
Betiğin docstring'deki iddiası zaten buydu: ".env'i değiştirmek" ile "config
katmanının onu okuduğu" ayrı şeylerdir. Türetme tam olarak o katmanı sınar ve
`RISK_SCALE` ne olursa olsun geçerli kalır.

**Hata 2 — BB testinin premisi yanlıştı.** "farklı oynaklıklarda risk% hepsi
AYNI olmalı" diyordu. Gerçek boyutlandırma `risk = min(max_risk, CAP × stop)`.
Dar stopta CAP bağlar, yani risk DÜŞÜK olmalıdır — arıza değil, tasarım.
Eski test yalnız (CAP 1.5, risk %2.25) çiftinde ve stop ızgarası tam sınırda
başladığı için geçiyordu. 1.4 ölçekte ızgara sınırın içine düştü:

```
  stop 1.50% → risk 1.87%   (0.015 × 1.25 = cap bağladı)
  stop 2.16% → risk 2.70%
```

Test bunu "✗ DEĞİŞKEN — düzeltme UYGULANMAMIŞ" diye okudu. **Yanlıştı.**
→ Test artık ankorun kendi formülüne uyumu ölçüyor, 7 noktada, cap-bağlı ve
risk-bağlı iki rejimi de kapsayarak. Korunan asıl hata (BB'nin oynaklıkla riski
BÜYÜTMESİ, %1.87 → %5.62) hâlâ yakalanıyor: o model tavanı aşıyordu, `min()`
asla aşamaz. Reddedilen kurulumlar teste sokulmuyor, ayrıca bildiriliyor.

**Yeni bölüm — ANKORA KIYAS.** Kullanıcıya verilen her getiri/maxDD tahmini
ankor birimindedir. Canlı ondan saparsa o tahminlerin hepsi aynı oranda kayar,
ve bunu hiçbir yerde görmüyorduk. Artık:

```
  risk/işlem   canlı %2.800  ankor %2.250   → 1.244x  ✓
    beklenen maxDD  ~%30.4   (ankor %24.43 × 1.24)
    ankorun aylık rakamlarını 1.24 ile ÇARP.
```

`ANKOR_RISKF` ve `ANKOR_CAP` `deployed_backtest.py` **kaynağından okunuyor**,
elle yazılmıyor — bu dosyayı bozan hatanın aynısını tekrarlamamak için.
`import` etmiyoruz: betik VPS'te koşuyor ve ağır import zinciri bir ayar
doğrulamasını veri eksikliğinden düşürmemeli.

Tavan: risk ankorun **1.5 katını** aşarsa `✗`. Gerekçe: 1.5 kat ≈ %37 maxDD,
$306'lık hesapta ~$113 tepe-dip. Ötesi "normal dalgalanma" diye savunulamaz.

### AÇIK SORU KAPANDI — canlı 1.50, çıpa 1.25, ikisi de doğru

VPS'te koşuldu: `position_cap_fraction 1.5000`. Yani **bayat olan ankor
dosyasıydı**, `.env` değil. `deployed_backtest.py:27` "canlı .env'de 1.25,
işlem boyutundan teyitli" diyordu; o yorum 2026-08-12'de geçerliliğini
yitirmiş, kimse silmemiş. DURUM bölüm 1 ise 1.5'i doğru yazıyordu — üç
kaynaktan ikisi doğru, biri yanlıştı ve ben yanlış olana baktım.

CAP 1.25 → 1.50 **bilerek** yapılmış ve gerekçesi ölçülü (bölüm 2190):
cap'e takılan işlemlerin ort R'si **+0.4597**, takılmayanların **+0.2056**.
Cap dar stoplu = iyi işlemleri kırpıyordu; 1.5 kırpmayı azalttı.

## 5n. Çıpa ile canlı arasındaki gerçek fark ÖLÇÜLDÜ (2026-09-09)

Aynı 1579 işlem, tek değişken cap, equity ÇIKIŞ sıralı:

| cap | ort risk | tavana takılan | kâr | maxDD | en kötü ay |
|---|---|---|---|---|---|
| 1.25 (çıpa) | %2.13 | %19 | **+$1420.66** | %24.43 | %−21.05 |
| 1.50 (canlı) | %2.17 | %12 | **+$1476.05** | %24.79 | %−20.46 |

1.25 satırı çıpayı **birebir** üretti (+$1420.66 · %24.43), yani ölçüm sağlam.

**Fark küçük ve lehimize:** kâr **%+3.9**, maxDD **+0.36 puan**, en kötü ay
**0.59 puan DAHA İYİ**. Yani sana verdiğim bütün aylık/yıllık rakamlar
%3.9 DÜŞÜK'tü. Hiçbir sonucu değiştirmiyor.

**Canlının çıpaya toplam oranı:**

```
kâr ölçeği   = (1476.05/1420.66) × (0.028/0.0225) = 1.293x
beklenen maxDD ~%30.8   ($306 hesapta tepe-dip ~$95)
beklenen en kötü ay ~%−25.5
```

**Kırmızı çizgi $180 GEÇERLİ KALIYOR.** Gerekçesi %34 maxDD varsayımıydı,
ölçülen %30.8 → $306'dan ~$212'ye inmek hâlâ NORMAL. $180 onun altında,
yani normal dalgalanmada paniğe kapılmıyoruz. Değişiklik gerekmiyor.

### Bunun bir daha olmaması için

`deployed_backtest.py` artık canlının değerlerini de **açıkça beyan ediyor**:
`CANLI_CAP`, `CANLI_RISKF`, `CANLI_OLCEK`, `CANLI_MAXDD_BAZ`. `ayar_dogrula.py`
bunları kaynaktan okuyup `.env` ile karşılaştırıyor. Artık iki soru ayrı
yanıtlanıyor:

- **(a) Canlı, olması gereken ayarda mı?** `.env` ↔ `CANLI_*` sabitleri.
  Sapma = ya `.env` kayıtsız değişti, ya sabitler güncellenmedi. İkisi de `✗`.
- **(b) Canlı çıpadan ne kadar sapıyor?** Ölçek oranı + ölçeklenmiş maxDD.

`CAP = 1.25` **dondurulmuş regresyon çıpası** olarak kalıyor: 49 araç
"1579 / +$1420.66" sayısını backtest motorunun bozulmadığını anlamak için
kullanıyor. O sabiti değiştirmek 49 aracı aynı anda kör ederdi.

**Ayrıca sessiz bir geri düşüş bulundu ve kapatıldı.** `_ankor_sabit` sabiti
`^RISKF` diye arıyordu, ama `RISKF` paylaşımlı satırda tanımlı
(`BAL0 = ...; RISKF = 0.0225; ...`) — hiç bulunamıyor, sessizce varsayılana
düşüyordu. Doğru sayıyı **şansa** veriyordu. Artık bulamazsa `SystemExit(2)`.
Sessiz geri düşüş, bayat sabitin ta kendisidir.

---

## 5o. 1 yıl projeksiyonu — `yil_projeksiyon.py` (2026-09-09)

"Her ay $150 eklesem 1 yıl sonra ne olur" sorusunun yanıtı **tek sayı değil**.
Araç Monte Carlo + gerçek pencere yürüyüşü yapıyor, sabit tohumla (sonuç
cherry-pick edilemez).

**Aylık (B senaryosu, çıpa − ölçülen kayma):**

| ölçü | değer |
|---|---|
| ortalama ay | %+17.52 |
| MEDYAN ay (tipik) | **%+10.18** |
| en kötü ay | %−32.62 |
| artı ay oranı | %60 |

**Yıl sonu — GERÇEK 12 aylık pencereler** (sıra korundu, 29 pencere).
Yatırılan: $306 + 12×$150 = **$2,106**.

| pencere | yıl sonu | yatırdığına göre |
|---|---|---|
| EN KÖTÜ 2025-08→2026-07 | $3,882 | +$1,776 |
| MEDYAN 2023-08→2024-07 | $7,680 | +$5,574 |
| EN İYİ 2025-02→2026-01 | $12,856 | +$10,750 |

29 pencerenin **%0'ı** yatırılanın altında bitti.

**Bootstrap (aylar bağımsız çekildi), üç senaryo:**

| senaryo | medyan yıl | %10 | %90 | yatırılanın altında bitme |
|---|---|---|---|---|
| A) çıpa aynen | $9,655 | $4,183 | $24,489 | %1 |
| B) çıpa − kayma | $6,181 | $2,668 | $15,434 | %5 |
| C) B'nin yarısı | $3,042 | $1,352 | $7,522 | **%29** |

### ⚠ BU RAKAMLARA PLAN YAPILMAZ — üç ayrı sebep

**1. Bileşik varsayımı test edilmedi.** `deployed_backtest.py`'nin kendi uyarısı:
"bileşik görünüm küçük hesapta patlar = fantezi". Çıpanın aylık ~%20'si **sabit
$190 tabanında** ölçüldü. 12 ay bileşiklemek, aynı oranın HER hesap boyutunda
geçerli olduğunu varsayar. Kayma ölçümü $59-513 nominali kapsıyor; bakiye
$2000'i geçince nominal o aralığın ÜSTÜNE çıkar ve orada **verimiz yok**.

**2. Pencerelerin çoğu boğa piyasasında.** 2023-2024 ağırlıklı. Kullanıcının
kendi gözlemi: "bot boğalarda iyi çalışıyor, boğadan sonraki süreçte dökülüyor".
EN KÖTÜ satırı bir taban değil, sadece geçmişte **gördüğümüz** en kötü.

**3. Çıpa bu veriye bakılarak seçildi.** Coin evreni geçmiş performansa göre
seçilmiş (donchian coinleri 21 içinde ort. sıra 4.6, rastgele 11.0) ve
`coin_expand` yürüyen-pencere testi seçimin ileriye taşınmadığını gösterdi.
Ama 21 coinin 18'i pozitif → edge geniş ve gerçek; seçim onu BÜYÜTTÜ, YARATMADI.
İleri beklenti çıpanın %50-100'ü. C senaryosu o aralığın alt ucu.

### Yan bulgu: `ANK_SLIP_BP` ÖLÜ KOD

`live_verify.py:50`'de tanımlı ama **hiçbir yerde kullanılmıyor**. 5l'de bu
sabiti 13.4 → 15.85 güncelledim ve kullanıcıya "metodoloji açığı kapandı"
dedim; **düzeltme kozmetikti**, hiçbir hesabı değiştirmedi. `live_verify`
canlıyı kaymasız çıpa beklentisiyle karşılaştırıyor, yani ölçtüğü fark
(−0.0078R) kaymayı ZATEN içeriyor — ama ±0.063R güven aralığı onu sıfırdan
ayıramıyor. `yil_projeksiyon.py` kaymayı bu yüzden AÇIKÇA düşüyor.
