# JOINT_EXHAUSTION_HALF_RISK — kâr geri verme risk testi (HISTORICAL CANDIDATE)

**Test edilen tek varyant.** Yalnız Donchian işlemlerinde, `port_dd_ath <= 0.02` VE
`gen_islem_yonunde == 1.0` ise risk × 0.50; aksi halde × 1.00. Tanımlar
`post_peak_diagnostic` §7'den aynen alındı; eşik, özellik ve çarpan değiştirilmedi.

**Test nasıl yapıldı:**
- Gerçek ikiz, 2023-04-06 → 2026-07-19 arası baştan sona kronolojik koşuldu.
- Çarpan, gerçek boyutlama adımında uygulandı: `risk_pct_override × 0.50`, CAP kuralı aynen.
- Koşullar her girişte **varyantın kendi** işlemlerinden ve kapanmış fiyat barlarından
  yeniden hesaplandı. Baseline etiketleri kopyalanmadı.
- Production dosyaları diskte değişmedi. Sarmalayıcılar yalnız araştırma sürecinin
  belleğinde; `.env`, canlı süreç ve emirlere dokunulmadı.
- Baseline, doğrulanmış 936 işlemlik koşudur (yeniden koşulmadı).

**Yeniden çalıştırma:**
```
python3 arastirma/kar_geri_verme_risk_test/kar_geri_verme_risk_test.py --kos     # varyant replay
python3 arastirma/kar_geri_verme_risk_test/kar_geri_verme_risk_test.py --analiz  # kıyas
```

**Çıktılar:**
- `varyant_islemler.csv`
- `varyant_donchian_kararlari.csv`: her Donchian sinyalinde V, ATH, port_dd_ath, genişlik, çarpan
- `sonuclar.json`
- `epizodlar_top5.csv`
- `islem_farklari.csv`: boş, fark yok

## 0. Koşu geçerliliği — VARIANT RUN: PASS

İlk iki deneme, varyantın tanımındaki değil, **benim ölçüm kodumdaki** hatalar yüzünden
geçersiz sayıldı ve silindi. Varyant ve eşikler değişmedi.

1. **Deneme 1:** Hesap değeri `executor.current_equity()` ile saat başında kaydedildi. Bu
   değer ara durumlarda geçici sıçrıyordu (ör. 2025-09-22 01:00'da 1.88×). ATH bozuldu ve
   yalnız 2 karar 0.50 aldı.
2. **Deneme 2:** Hesap değeri dondurulmuş formülle, varyantın kendi DB'sinden kuruldu.
   - Ama ikiz aynı saatin barlarını coin coin işlediği için, T anında DB'de "açık" görünen
     bir pozisyonun stop/hedefi T−1h barında zaten değmiş olabiliyordu.
   - Örnek: 2023-06-05 16:00'da BNB'nin hedefi değmişti ama BNB henüz işlenmemişti. Pozisyon
     açık sayılınca V ve ATH şişti.
3. **Geçerli koşu:**
   - Açık görünen pozisyonlarda yalnız ts ≤ T−1h barlarıyla (ileriye bakmadan) ekonomik
     çıkış kuruldu.
   - Baseline DB'sinde çalışma anı taklidiyle 412 Donchian kararının hepsi dondurulmuş
     değerlerle uyuştu: en büyük fark 3.3e-5, eşik sınıfı farkı 0.
   - Varyant koşusunda ilk 0.50 kararına (2023-06-10) kadarki 20 kararın hepsi dondurulmuş
     değerlerle aynı (en büyük fark 2.5e-7).
   - Hata yok; marjin reddi 2 (baseline ile aynı).

## 1. Özet kıyas

| | BASELINE | JOINT_EXHAUSTION_HALF_RISK |
|---|---|---|
| son hesap değeri | $791,666 | **$1,222,430** |
| toplam net PnL | $781,666 | $1,212,430 |
| toplam getiri | ×78.4 | ×121.7 |
| en büyük düşüş % (saatlik hesap değeri) | **%47.25** | **%45.75** |
| en büyük düşüş $ | $706,269 | $1,026,706 (hesap daha büyük) |
| profit factor | 1.161 | 1.177 |
| kazanma oranı | %42.9 | %42.9 |
| ortalama R_net | +0.1965 | +0.1965 (R boyuttan bağımsız) |
| en kötü ay | −%26.7 | −%26.7 |
| medyan aylık getiri | +%10.43 | +%10.43 |
| pozitif ay oranı | %70.0 | %67.5 |
| ücret + kayma (fiyat içi) | $55.0k + $386.1k | $79.5k + $555.4k (hesap büyüklüğüyle ölçeklenir) |
| işlem sayısı | 936 | 936 |
| 0.50 uygulanan Donchian işlemi | — | **71** (91 kararın 20'si işlemle sonuçlanmadı) |

**TRAIN / TEST** (işlem sayıları girişe göre; getiri ve düşüş her bölümün kendi başlangıç
değerinden, saatlik hesap değeriyle):

| | TRAIN baseline | TRAIN varyant | fark | TEST baseline | TEST varyant | fark |
|---|---|---|---|---|---|---|
| dönem getirisi | ×12.11 | ×18.05 | **+%49** göreli | ×5.06 | ×5.44 | **+%7.5** göreli |
| en büyük düşüş | %42.5 | %38.7 | **−3.8 puan** | %47.25 | %45.75 | **−1.5 puan** |
| profit factor | 1.228 | 1.272 | +0.044 | 1.153 | 1.167 | +0.014 |
| profit giveback ratio | 0.730 | 0.727 | −0.003 | 0.759 | 0.736 | −0.023 |
| işlem | 539 | 539 | 0 | 397 | 397 | 0 |
| 0.50 uygulanan | — | 43 | | — | 28 | |

TRAIN ve TEST **aynı yönde**, ama büyüklük çok farklı: iyileşmenin büyüğü TRAIN'de.

## 2. Kâr geri verme

### `profit_giveback_ratio` (varyant koşmadan önce koda sabitlendi)

- **Epizod:** Saatlik hesap değerinde ATH'den, ATH yeniden aşılana kadar geçen dönem.
  Derinliği ≥ %5 olanlar sayılır.
- **Semboller:** P = epizod tepesi, Tr = epizod dibi, B = önceki sayılan epizodun tepesi ile
  P arasındaki en düşük değer (ilk epizodda başlangıçtan P'ye kadarki en düşük değer).
- **Formül:**

```
PGR = Σ ln(P/Tr) / Σ ln(P/B)
```

- **Anlamı:** Run-up'larda log cinsinden kazanılanın ne kadarının ardından gelen düşüşte
  geri verildiği.

**Sonuç:** 0.727 → **0.715**. Epizod sayısı 64 → 70. TRAIN 0.730 → 0.727; TEST 0.759 → 0.736.

### En büyük 5 epizod

| # | BASELINE: tepe → dip, düşüş, ATH'ye dönüş | VARYANT: tepe → dip, düşüş, ATH'ye dönüş |
|---|---|---|
| 1 | 2026-06-06 $1.495M → 2026-07-18 $0.788M · −$706k **−%47.3** · veri sonunda dönmedi | 2026-06-06 $2.244M → 2026-07-18 $1.218M · −$1.027M **−%45.7** · dönmedi |
| 2 | 2024-01-23 $69.6k → 2024-04-13 $40.0k · **−%42.5** · 194 gün | 2026-02-06 $1.772M → 2026-05-04 $1.066M · **−%39.9** · 117 gün |
| 3 | 2026-02-06 $1.216M → 2026-05-04 $0.703M · **−%42.2** · 117 gün | 2024-02-16 $85.0k → 2024-04-13 $52.1k · **−%38.7** · **95 gün** |
| 4 | 2023-07-14 $14.4k → 2023-08-08 $8.9k · −%38.0 · 35 gün | 2023-07-14 $14.6k → 2023-08-08 $9.0k · −%38.0 · 35 gün |
| 5 | 2024-12-04 $176.6k → 2025-03-08 $115.9k · −%34.4 · 125 gün | 2024-12-04 $256.6k → 2025-03-08 $168.4k · −%34.4 · 125 gün |

**Bilinen büyük düşüşlerde:**
- **2026-06 → 07:** %47.3 → %45.7.
- **2024-01 → 04:** %42.5 → %38.7. Varyantta tepe bir ay sonraya kaydı; ATH'ye dönüş
  194 → 95 gün.
- **2026-02 → 05:** %42.2 → %39.9.
- **2023-07 ve 2024-12 epizodları:** Değişmedi; bu dönemlerde koşul neredeyse hiç
  tetiklenmedi.

## 3. 0.50 uygulanan işlemlerin anatomisi (71 işlem)

**Dağılım:**
- Dönem: TRAIN 43, TEST 28.
- Yön: long 15, short 56.
- Coin: ETH 14, ADA 13, BNB 10, SOL 10, BCH 9, NEAR 8, ICP 7.
- Çıkış: SL 45, max-hold 18, TP 8.

**Baseline'daki sonuçları:**
- Ortalama R_net **−0.262**: TRAIN **−0.423**, TEST **−0.014** (yaklaşık sıfır).
- Toplam −$82,744 PnL.
- Baseline'ın toplam zarar dolarının %11.0'ı.

**Boyut:** Bu işlemlerde miktar baseline'ın ortanca ~0.69 katı. 0.50 değil, çünkü varyantın
hesabı o anda baseline'dan büyük ve CAP bazı işlemleri zaten kırpıyordu.

**İşlem listesi farkı yok:** 936/936 aynı işlem, aynı giriş/çıkış, aynı R_net. Yarım
boyut marjin ve koltuk kullanımını azalttı ama hiçbir işlemi ekleyip çıkarmadı; marjin
reddi iki koşuda da 2.

**Etiket farkı:** Teşhis çalışmasında koşulu sağlayan Donchian işlemi 66 idi; burada 71.
Varyantın kendi ATH/düşüş yolu farklı olduğu için birkaç işlemin etiketi değişti. Bu,
gerçek kronolojik replay'in beklenen sonucu.

## 4. Hüküm: **C — Pratik olarak önemli fark yaratmıyor** (kâr geri verme açısından)

**Gerekçe:**
- **Kâr geri verme az değişiyor.**
  - PGR 0.727 → 0.715 (TEST 0.759 → 0.736).
  - En büyük düşüş %47.3 → %45.7; TEST'te −1.5 puan.
  - Bugün açık duran en büyük düşüş (2026-06 → 07) hâlâ %45.7.
- **Edge/getiri korunuyor, hatta artıyor.** Son değer +%54, PF 1.161 → 1.177. Ama bu
  artışın büyüğü TRAIN'den geliyor ve **örneklem içidir**:
  - Koşul bu aynı 936 işlem üzerinde keşfedildi.
  - Yarım riske düşen işlemlerin baseline ortalaması TRAIN'de −0.42R, TEST'te yalnız
    −0.01R. Yani TEST'te koşul işlem kalitesini ayırt etmedi; oradaki küçük iyileşme daha
    çok varyans azalmasından geliyor.
- **TRAIN ile TEST yön olarak ters değil; büyüklük olarak çok farklı:**
  - TRAIN: düşüş −3.8 puan, getiri +%49 göreli, 2024 toparlanması 194 → 95 gün.
  - TEST: düşüş −1.5 puan, getiri +%7.5 göreli.
- Bu fark, etkinin büyük kısmının keşif dönemine ait olduğunu düşündürüyor.

Bu yalnız bir **HISTORICAL CANDIDATE**'tır. Production'a uygulanmadı; "kanıtlandı"
denemez. Başka varyant, eşik veya çarpan denenmedi.
