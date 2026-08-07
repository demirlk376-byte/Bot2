# 📱 SEYAHAT REHBERİ — bir ay uzaktayken

Telefondan bakılacak tek sayfa. Ezber gerekmez; sadece **eşiklere** bak.

---

## 🟢 NORMAL — hiçbir şey yapma

Bot 40 aylık geçmişte şöyle davranıyor ($185 hesap üzerinden):

| | | |
|---|---|---|
| tipik ay (medyan) | +%12.9 | **+$24** |
| ortalama ay | +%18.7 | +$35 |
| kötü ay (10'da 1) | −%11.1 | −$20 |
| çok kötü ay (20'de 1) | −%14.5 | −$27 |
| **en kötü ay (tarihte)** | **−%21.0** | **−$39** |

**5 ayın 1'i zararla kapanıyor.** Bu bozukluk değil, sistemin normali.
Tüm geçmişte en uzun ardışık zarar serisi **1 ay**.

**Bakiye $147'nin (−%21) üstündeyse hiçbir şey yapma.** Kâr olmayan bir ay bile
tamamen beklenen bir şey — dağılım sağa çarpık, kazanç birkaç iyi ayda toplanıyor.

---

## 🟡 BAK — sebebini anla, acele etme

- **Sentinel'den uyarı mesajı geldi** → mesaj neyi söylüyor: servis mi öldü, disk mi doldu,
  veri mi bayatladı? Metin sorunu açıkça yazıyor.
- **Telegram 24 saatten uzun süre sessiz** → `/status` yaz. Cevap gelmiyorsa bot veya
  VPS düşmüş olabilir.
- **Haftalık özet gelmedi** (Pazar) → nöbetçinin kendisi de düşmüş olabilir.

Bu üç durumda da **panik satışı yok**. Botu durdurmak pozisyonları kapatmaz; borsadaki
stop emirleri yerinde durmaya devam eder.

---

## 🔴 DURDUR — tek eşik

**Bakiye $130'un altına inerse** (−%30):

```
systemctl stop btc-bot
```

Bu seviye tarihte **hiç görülmedi**. Görülürse "kötü ay" değil "bir şey bozuldu"
bölgesidir ve incelenmeden devam etmemeli.

Not: `stop` botu durdurur, **pozisyonları kapatmaz**. Borsadaki SL/TP emirleri
çalışmaya devam eder — yani durdurmak sizi korumasız bırakmaz.

---

## 📲 TELEGRAM KOMUTLARI

| komut | ne verir |
|---|---|
| `/status` | canlı bakiye, açık pozisyonlar, uPnL |
| `/rapor` | ay sonu raporu — kâr, WR, PF, kol bazında kırılım |
| `/balance` | sadece bakiye |

`/status` ile `/rapor` **aynı bakiyeyi göstermeli**. Göstermiyorsa bana söyleyin.

---

## 🖥️ VPS'E ERİŞİMİNİZ VARSA

```bash
cd /opt/bot2

python3 sentinel.py --report      # tüm sağlık kontrolleri tek ekranda
python3 live_verify.py            # canlı sonuçlar backtest'i tutuyor mu (İSTATİSTİKLİ)
systemctl status btc-bot          # servis durumu
```

`live_verify.py`'nin **[1] numaralı satırı** en önemlisi: ortalama R'nin güven aralığı.

- Aralık **sıfırın üstündeyse** → edge canlıda da var
- **Ankor (+0.237R) aralığın içindeyse** → backtest tutuyor
- Aralık sıfırı içeriyorsa → henüz yeterli işlem yok, "bozuldu" **denemez**

⚠️ n<100 iken PF ve WR'yi tek başına okumayın. Noktaya değil **aralığa** bakın.

---

## ❓ DÖNÜNCE KONUŞULACAKLAR

1. **`live_verify.py` çıktısı** — bir aylık gerçek veri, overfit edilemeyen tek kanıt.
   Bu, geçmişteki tüm backtestlerin toplamından daha bilgilendirici.
2. **Risk artırma kararı** — ancak (1) ankoru doğrularsa gündeme gelir. Şu an körlemesine olurdu.
3. **Pairs** — engel sermaye değil KOD çıktı (`get_position()` tek bacak dönüyor,
   mutabakat açık pozisyonları "kapandı" sanabilir). Ya bu üç yer sembol+yön bazlı yapılacak,
   ya da ayrı hesap açılacak. Ayrı hesap daha güvenli.

---

## 🔒 DEĞİŞMEYECEKLER

Seyahat boyunca **hiçbir strateji parametresi değişmeyecek**:
donchian rr2.5 / SL 2×ATR / maxhold 30 / kanal 40 / EMA200 · squeeze 4 coin ·
BB hafta sonu LTC · MAX_POSITIONS 7 · RISK_SCALE 1.125 · CAP 1.25

Bunlar 18 eksende test edildi ve mevcut ayarların ölçülmüş bir optimumda olduğu görüldü:
kuyruk riskini satmak puan başına en fazla **$23.6** kazandırıyor, geri almak en az
**$80**'e mal oluyor. Her iki yön de kötü takas.
