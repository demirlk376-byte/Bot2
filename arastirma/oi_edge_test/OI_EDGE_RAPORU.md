# OI → Donchian kırılım kalitesi (önceden kayıt)

**Durum: VPS koşusu 2026-09-27 yapıldı → HÜKÜM C** (sonuç en altta). Tanımlar koşudan önce sabitlendi.
- Canlı `trades.db` ve güncel `data/oi_log.csv` VPS'te.
- Aşağıdaki tanımlar, eşikler ve karar kuralı **sonuç görülmeden** sabitlendi. Sonuçtan
  sonra değiştirilmez.
- Bu test başarısız olursa başka lookback veya eşik denenmez. Yeni hipotez ayrı ve
  önceden kayıtlı olmak zorunda.

## Hipotez

Donchian kırılımı sırasında OI artıyorsa, hareket yeni pozisyon açılışıyla destekleniyor
olabilir. OI düşüyorsa hareket pozisyon kapanışı ağırlıklı olabilir ve devamı zayıf
kalabilir. Bu bir **hipotezdir**; "OI artar = iyi" varsayılmaz.

## Tanımlar (sabit)

| | |
|---|---|
| örneklem | `trades.is_paper = 0`, kol = donchian (`erken_uyari.kol_adi`), kapanmış işlemler |
| T | işlemin `entry_time` değeri (Donchian 4h bar kapanışından sonraki piyasa girişi) |
| OI_T | OI kaydı: T anında veya **öncesindeki** son kayıt. T − kayıt > 30 dk → geçersiz |
| OI_T−4h | T−4h anında veya öncesindeki son kayıt. (T−4h) − kayıt > 30 dk → geçersiz |
| **tek özellik** | `oi_change_4h = OI_T / OI_T−4h − 1` |
| gruplar | OI_RISING: `oi_change_4h > 0` · OI_NOT_RISING: `oi_change_4h <= 0` |
| outcome | **`erken_uyari.r_net`**: kanonik canlı net R. Defterdeki `pnl_usdt` (ücret + funding dahil) / (\|entry − stop\| × miktar) |
| stop güvenilirliği | `r_net`, `sl0` yoksa `sl_price` sütununa düşer. Bu sütun Donchian stopu taşındıkça değişir. Bu yüzden R yalnız şu iki durumda sayılır: `sl0` varsa, ya da \|giriş − sl_price\| = 2.0 × ATR (±%2) ise, yani stop hiç taşınmamışsa. Diğerleri "R güvenilmez" diye elenir ve sayılır. |

**Denenmeyecekler:**
- Başka lookback (1h/2h/8h/12h/24h/48h)
- z-skor, yüzdelik, EMA
- OI/hacim ya da OI/funding kombinasyonları
- Farklı eşik ya da quantile

## Veri kapıları (sabit)

| koşul | sonuç |
|---|---|
| lookahead assert ihlali (OI_T ts > T veya OI_T−4h ts > T−4h), tek bir tane bile | **TEST INVALID** |
| geçerli n < 30 | edge tablosu yok · **D** |
| 30 ≤ n < 60 | yalnız keşif tablosu, karar yok · **D** |
| OI takvim kapsamı < 30 gün | **D** (n yüksek olsa bile) |
| veri kalitesi FAIL | **D** |
| ≥ 30 gün **ve** n ≥ 60 **ve** kalite PASS | primary test |

### Veri kalitesi FAIL kuralları

- null / bozuk / ≤0 OI oranı > %1
- Herhangi bir Donchian coininde 15 dk ızgara kapsamı < %80
- Herhangi bir Donchian coininde ardışık iki kayıt arasında ×10 veya ÷10 sıçrama
  (açıklanamayan ölçek kırılması)

## Primary test ve karar kuralı (sabit)

- **Etki:** `delta_R = ort R(OI_RISING) − ort R(OI_NOT_RISING)`.
- **Ana güven aralığı:** hafta-kümeli bootstrap (ISO hafta, 5000 tekrar, sabit tohum
  20260928), %95 GA. İşlem düzeyi bootstrap ayrıca verilir, ama karar hafta-kümeli GA ile.
- **Kontrol:** `Spearman(oi_change_4h, R_net)`, 5000 permütasyon. Bu bir karar ölçütü
  değil, yalnız işaret kontrolü.

| hüküm | koşul |
|---|---|
| **A**: OI destekli kırılım adayı | delta_R > 0 **ve** hafta-kümeli GA tamamen > 0 **ve** rho ≥ 0 |
| **B**: ilişki var, kanıt yetersiz | delta_R > 0 ama GA sıfırı içeriyor (veya rho < 0 ama anlamlı değil) |
| **C**: OI bu şekilde işe yaramıyor | delta_R ≤ 0, **veya** rho < 0 ve p < 0.05 (hipotezin tersi) |
| **D** | veri kapıları |

A çıksa bile production değişmez. Sonuç yalnız **HISTORICAL / FORWARD-DATA CANDIDATE**
olur.

**Betimsel çıktılar (karar ve filtre önerisi değildir):**
- long/short: n ve ort R
- coin başına: n, ort oi_change_4h, ort R

## Veri kalitesi notları

- **OI alanı:** `oi_collect.py` ticker'da bulduğu ilk alanı yazar; öncelik `holdVol`
  (kontrat adedi). CSV alan adını kaydetmez. Ölçek tutarlılığı sıçrama denetimiyle
  kontrol edilir.
  - Alanı kesin görmek için ayrı ve isteğe bağlı bir komut var:
    `venv/bin/python oi_collect.py --probe`. Halka açık ticker'ı okur; emir veya hesap
    erişimi yok.
- **`oi_usd` USD değildir:** `oi_usd = kontrat × fiyat`. contractSize ≠ 1 olan coinlerde
  (örneğin ETH) bu değer USD'yi göstermez. Bu test `oi_usd` kullanmaz. Yalnız
  kontrat-adedi oranı kullanılır ve birim sabit kaldıkça etkilenmez.

**Repodaki OI kopyası (`data/oi_log.csv`, 2026-09-09'a kadar) üzerinde kapsam:**
- 2026-07-29 21:46 → 2026-09-09 20:47, yani 42.0 gün.
- 47.676 satır, 12 coin × 3.973.
- Toplama aralığı medyan 15.12 dk; 15 dk ızgara kapsamı %98.6; en büyük boşluk 16 dk.
- Duplicate, bozuk ya da ≤0 kayıt 0; sıçrama 0.
- Kalite **PASS**.
- Kapsamın %100 değil %98.6 çıkması beklenen bir durum: toplayıcı 15 değil yaklaşık
  15.1-15.3 dakikada bir çalışıyor, bu yüzden arada bir 15 dk'lık dilim boş kalıyor.

## Doğrulama (çevrimdışı, sentetik defter + repodaki OI verisi)

**Eleme yolları:** Her durum ayrı sayıldı:
- OI başlangıcından önceki işlem
- 3 saatlik yapay OI boşluğundaki bayat işlem
- açık işlem
- taşınmış stoplu işlem
- başka kol ve `is_paper=1` işlemler (sayıma girmedi)

`sl0`'ı olmayan ama stopu ATR ile doğrulanan işlem geçerli sayıldı.

**Lookahead:** 71 eşleşmede de OI_T ≤ T ve OI_T−4h ≤ T−4h (gecikme 0.5-15.4 dk). Yapay
bir ihlal enjekte edilince doğru yakalandı.

**Hüküm yolları:**

| senaryo | hüküm |
|---|---|
| n=20 | D, edge tablosu yok |
| n=45 | D + keşif tablosu |
| rastgele R, n=71 | C |
| R'ye OI yönüne bağlı gerçek bir etki yerleştirildi | A |

## VPS'te çalıştırma (salt okur)

```
cd /opt/bot2 && git pull && venv/bin/python arastirma/oi_edge_test/oi_edge_audit.py
```

- Yalnız veri kapsamı: aynı komuta `--yalniz-kapsam` ekle.
- Borsa API'si çağrılmaz, emir yok, `.env` okunmaz, bota dokunulmaz.
- `trades.db` `mode=ro` ile açılır. Yalnız `data/oi_log.csv` okunur.
- İşlem düzeyi lookahead CSV'si `/tmp/oi_edge_audit/oi_donchian_eslesme.csv` dosyasına
  yazılır.

## Sonuç

**VPS koşusu (2026-09-27): HÜKÜM C — OI bu şekilde işe yaramıyor.**

**Veri:**
- OI kapsamı: 2026-07-29 21:46 → 2026-09-27 22:11, yani 60.0 gün.
- 68.196 satır, 15 dk ızgara kapsamı %98.6, en büyük boşluk 16 dk.
- Duplicate, bozuk kayıt ve sıçrama 0. Kalite **PASS**.
- En büyük ardışık OI oranı ETH'de |ln| 1.215, BCH'de 1.146. İkisi de ×10 eşiğinin
  (|ln| 2.303) altında.

**Donchian işlemleri:**
- Toplam 74, geçerli OI eşleşmesi **65**.
- Geçersiz 9:
  - 7'si OI başlangıcından önce açılmış.
  - 2'sinde "coin için OI yok".
- R güvenilmez: 0. Lookahead ihlali: **0**.

**Primary test:**

| grup | n | ort R | medyan | WR | PF | TP/SL/max-hold/diğer |
|---|---|---|---|---|---|---|
| OI_RISING (>0) | 24 | +0.078 | −1.003 | %33.3 | 1.13 | 6/13/1/4 |
| OI_NOT_RISING (≤0) | 41 | +0.662 | +0.505 | %56.1 | 2.74 | 13/14/3/11 |

- **delta_R −0.583.** Hafta-kümeli %95 GA [−1.230, +0.136] (9 hafta). İşlem düzeyi GA
  [−1.305, +0.165].
- **Spearman** rho −0.246, p 0.052 (kontrol).
- Etki hipotezin **tersi** yönünde, ama istatistiksel olarak anlamlı değil. GA sıfırı
  içeriyor, p > 0.05.
- Kural gereği delta_R ≤ 0 → **C**.

**Betimsel (karar değildir):**
- long n=57, ort R +0.593 · short n=8, ort R −0.601.
- Coin başına n=6-13; hepsi küçük.

**Dikkat:**
- n=65 kapının hemen üstünde. Yalnız 9 hafta ve tek bir piyasa dönemi (Ağustos-Eylül 2026).
- "diğer" çıkışlar (15 işlem; büyük olasılıkla Telegram'dan elle kapatmalar) outcome'a
  gürültü katıyor.
- 09-22'de hacim filtresi devreye girdi; örneklem iki farklı giriş kuralını karıştırıyor.

**Bu önceden kayıtlı hipotez kapandı.**
- Ters yöndeki işaret yeni bir filtre önerisi **değildir**.
- Test edilecekse ayrı, önceden kayıtlı bir hipotez ve yeni (bu 65 işlemden bağımsız)
  veri gerekir.
- Başka lookback veya eşik denenmedi.
