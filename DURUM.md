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

Gerçekçi tipik ay: **$15 – $31**.

Ayda $100 katkıyla 12 ay sonunda (yatırılan $1403):
- beklenen ~**$2,500**
- kötü senaryo (%10) ~$1,150
- yatırdığından az çıkma ihtimali ~**%19**

Kâr, riski artırarak değil **bakiye büyüyerek** artar. $203 → $400 olduğunda aynı
%2.25 riskle aylık kâr ikiye katlanır.

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

**Şimdi değil.** RISK_SCALE 1.125 → 2.0 kârı %56 artırıyor ama en kötü ayı %86
kötüleştiriyor. Takas aleyhine.

Ön-kayıtlı tetik — üçü birden sağlanmadan değiştirilmez:

1. Aktif kollardan **en az 200 kapanmış işlem** (şu an ~41)
2. O örneklemde canlı ortalama R'nin **alt güven sınırı 0.15'in üstünde**
3. Ancak o zaman RISK_SCALE 1.125 → **1.25**. Daha ötesi yok.

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
