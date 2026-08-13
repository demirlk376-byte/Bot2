# Sistem Durumu

*Son güncelleme: 2026-08-12*

Bu dosya tek doğruluk kaynağı. "Ne yapıyorduk, neyi kanıtladık, ne zaman ne
değiştireceğiz" sorularının cevabı burada. Yeni bir şey yapmadan önce buraya bak.

---

## 1. Şu anki yapılandırma

```
LEVERAGE=10                RISK_SCALE=1.125
MAX_RISK_PCT=0.02          POSITION_CAP_FRACTION=1.5      ← 2026-08-12'de değişti
MAX_POSITIONS=7            CONSECUTIVE_LOSS_LIMIT=2
COOLDOWN_MINUTES=240       DAILY_MAX_LOSS_PCT=0.35
FIXED_MARGIN_USDT=0        MAKER_ENTRY=true
```

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

**Kırmızı çizgi:** bakiye $130'un altına inerse dur ve bak. Aylık −%21 normaldir,
o çizgiye kadar müdahale gerekmez.

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
