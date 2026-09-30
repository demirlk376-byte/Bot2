# FAILED_PULLBACK_V1 — sonuç raporu (2026-09-30)

**KARAR: ELENDİ.**
Önceden kayıtlı iki eleme koşulunun ikisi de gerçekleşti (kurallar: `MANIFEST.md`, commit `f1b2999`, sonuçlardan önce):
- S ortalama net R ≤ 0.
- B − A75 ≤ 0.

Kural uyarlaması Linda Raschke'nin başarısız trend devamı fikrinden esinlenir; onun sisteminin
ya da kanıtlanmış bir kripto stratejisinin testi değildir.

## 1. Temel ve referans
- **Taban:** commit `532da4e`, üretim dosyaları değişmedi. Ayar ikizin `CANLI_ENV` değeri, başlangıç
  10.000 USDT.
- **Evren ve dönem:** 12 coin, 2023-04-06 → 2026-07-19. Maliyet ve funding: `MANIFEST.md`.
- **A referansla birebir eşleşti:** 936/936 işlem (sembol, yön, giriş dakikası). Toplam PnL farkı 0.00 USDT.
- **Kancalar pasif:** A'da aday yalnız gözlendi, sonuç değişmedi.
- **Eşdeğer strateji yok:** Mevcut kodda eşdeğer strateji yok.
  - `DONCHIAN_MOD=basarisiz` 4h kanal kırılımının geri dönüşüdür; canlıda da kapalı.
  - O modda ADX eşiği, EMA20 ilk teması, P seviyesi ve geri kazanım başarısızlığı yok.
  - `strategies/trend.py` main'de kullanılmıyor.
  - `mtf_pullback.py` trend yönünde geri çekilme girişidir, başarısızlık değil.

## 2. Portföy karşılaştırması (ana maliyet)
| koşu | net USDT | getiri | işlem (aday) | beklenti USDT | PF | maks DD | en uzun sualtı | komisyon | kayma | funding | açık risk ort/maks | marjin ort/maks |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | +793.565 | %7.936 | 936 (0) | 835 | 1.16 | %46.6 | 194 gün | 54.988 | 383.993 | yok* | %5.3 / %37.6 | %13.2 / %95.7 |
| A75 | +416.267 | %4.163 | 937 (0) | 440 | 1.20 | %38.0 | 124 gün | 24.271 | 170.551 | yok* | %4.0 / %29.2 | %10.2 / %82.0 |
| B | +116.449 | %1.164 | 1200 (264) | 96 | 1.11 | %42.8 | 214 gün | 15.748 | 116.473 | yok* | %4.1 / %29.2 | %10.6 / %82.0 |

\* Ana ikizde funding fiilen 0'dır; bu 936 referansıyla aynıdır.

- **B − A75 = −299.817 USDT.** Bu, aday eklemenin etkisidir.
- **B − A = −677.116 USDT.**
- Yüzdelerin büyüklüğü bileşik büyümeden gelir. Karşılaştırma için anlamlı olan, B'nin A75'ten
  daha kötü olmasıdır:
  - Her yıl daha düşük getiri (aşağıdaki tablo).
  - Daha derin düşüş (%42.8'e karşı %38.0).
  - Daha uzun sualtı süresi (214 güne karşı 124 gün).

**Maliyet ve funding dayanıklılığı:**

| senaryo | A | A75 | B | B − A75 |
|---|---|---|---|---|
| kayma 2x | +148.302 | +107.530 | +7.857 | **−99.673** |
| funding (Binance vekil) | +721.186 | +385.523 | +107.651 | **−277.871** |

B'nin maksimum düşüşü:
- kayma 2x'te %56.1, A75'te %40.5.
- funding koşusunda %43.0.

Funding vekil veridir (Binance; MEXC dosyası daha uzunsa o). Kanıt değil, duyarlılıktır.

**Yıllara göre (B / A75):**

| yıl | A75 | B | B − A75 (USDT) |
|---|---|---|---|
| 2023 | %338 | %224 | −11.423 |
| 2024 | %112 | %47 | −33.875 |
| 2025 | %253 | %155 | −161.366 |
| 2026 | %30 | %4 | −93.154 |

## 3. Aday tek başına (S, sabit risk birimi 100 USDT)
**Huni:**
- 4.637 hazırlık (2.523 long, 2.114 short).
- 4.319 iptal:
  - p süresi aşıldı: 1.625
  - ilk temas EMA ötesinde kapandı: 1.216
  - f süresi aşıldı: 928
  - P geri alındı: 373
  - q süresi aşıldı: 177
- 10 eksik mum.
- **317 sinyal.** Dağılımı:
  - 25'i TRX; risk haritasında yok.
  - 84'ü engellendi; nedeni yetersiz marjin (aşağıya bakın).
  - **208 dolum.** 208'i de kapandı.

| koşu | işlem | kazanma | ort net R [%95 GA, hafta-kümeli] | toplam R | PF |
|---|---|---|---|---|---|
| S | 208 | %28.8 | **−0.370** [−0.498, −0.236] | −77.0 | 0.48 |
| S_2x | 132 | %25.0 | −0.515 [−0.651, −0.367] | −68.0 | 0.29 |
| S_cikis (aday çıkışına 15.85bp) | 137 | %24.1 | −0.608 [−0.774, −0.433] | −83.3 | 0.33 |
| B içindeki aday | 264 | %27.3 | −0.416 [−0.531, −0.296] | −109.9 | 0.41 |

**Maliyet öncesi de negatif.** Maliyet işlem başına ortalama 0.23R. Maliyet düşülmeden önce bile
ortalama −0.14R. Yani sorun yalnız kayma değil; kurulum ters yönde de kazanmıyor.

**Kırılımlar (S):**
- **Yön:** long −0.378R (105 işlem), short −0.363R (103 işlem). İki yön de ayrı ayrı negatif.
- **Coin:** 11 coinin hepsi negatif. En iyisi SOL −0.08R (9 işlem), en kötüsü XLM −0.69R.
- **Yıl:** 2023 −0.50, 2024 −0.43, 2025 −0.13, 2026 −0.27.
- **Kronolojik yarılar** (sınır 2024-12-01): −0.46 ve −0.16.
- **En iyi işlemler çıkarılınca toplam R:** 1 işlem −78.8, 3 işlem −82.4, 5 işlem −85.8, 10 işlem −94.1.

**Uç işaretleri:**
- Aynı mumda stop ve hedef: S'de 5, B'de 12 (stop önce sayıldı).
- Boşluklu stop geçişi: 0.
- Geçersiz veya sıfır risk: 0.
- Ortalama tutuş 3.6 mum.

**Not — marjin engelleri:** S'deki 84 engel, sabit 100 USDT riskin 10.000 USDT tabana göre
boyutlanmasından kaynaklanır. Özsermaye %90 eridiği için sonraki girişlere serbest marjin yetmedi.
R istatistikleri dolan 208 işlem üzerindendir. B'de aynı sinyal havuzu 264 dolum verdi ve sonuç
aynı yönde (−0.42R).

## 4. B'de engellenen adaylar
- 28 sinyal gerçek portföyde alınamadı:
  - 24'ü aynı coinde **ters** yönde açık bot pozisyonu vardı. Kod `SEMBOLDE_TERS_POZISYON`,
    örneğin donchian long açıkken short sinyali.
  - 4'ü aynı yönde açık pozisyon vardı.
- Mevcut pozisyon hiç kapatılmadı.
- Engellenen sinyallerin kârı portföye eklenmedi.
- Ayrıntı: `aday_engellenen_B.csv` (a/p/f/q zamanları, plan, stop, hedef, neden kodu, mevcut pozisyon).

## 5. A'nın kötü dönemlerinde B (sonradan teşhis; girişe filtre yapılmadı)
**75 negatif A haftası:**
- B − A75 toplamı +505.688 USDT. Bu, adayın katkısı **değil**. Aynı haftalarda adayın kapanan
  işlemleri −36.701 USDT kaybettirdi.
- Fark, B'nin daha küçük özsermayesinden gelir: aynı yüzde kayıp daha az USDT eder. Yüzde
  bazında karşılaştırma için aşağıdaki DD tablosu kullanılmalı.

**A'nın en büyük 5 düşüşü** (`a_dusus_donemleri.csv`):
- 4'ünde B, A75'ten daha kötü (−2.3 ile −5.6 puan).
- Bu 4 dönemde aday kaybettirdi.
- Yalnız 2024-12 → 2025-03 düşüşünde B +3.9 puan daha iyi; burada aday +2.535 USDT kazandı
  (21 işlem).
- Sonuç: aday, "yükselişte kazanıp geri verme" dönemlerinde koruma sağlamadı.

## 6. Davranış doğrulaması (koşu edildi)
**Testler:** `python3 -m pytest -q arastirma/failed_pullback_v1/test_fpb.py` → **31 geçti.**
Kapsam:
- ilk temasın başarısız olması ve sonraki temasın seçilmemesi
- p/f/q pencerelerinin iki ucu, P geri alma, EMA koşulları
- long ayna kuralları, ADX eşiğinin iki ucu, 100 mum ısınma
- eksik ve tekrar mum
- aktif kurulumda ve bitiş mumunda yeni hazırlık olmaması; bir hazırlıktan tek sinyal
- q kapanışında tek deneme; engellenen sinyalin yeniden denenmemesi
- açılışın seviye dışında kalması
- aynı damgada bot önceliği ve sembol sırası
- boşluklu stop (açılıştan, kaymalı), aynı mumda stop/hedef
- kötü dolumda hedefin 2R'ye taşınmaması
- max_hold=12, R hesabı
- akış göstergelerinin `indicators.py` ile eşitliği
- 12 coinde 3 kesme noktasında kesilmiş veri = tam verinin o tarihe kadarki olayları

**Mutasyon sınaması:** 12 kural bozulması denendi, 12'si de en az bir testi düşürdü. İlk turda
ADX `≤` → `<` mutasyonu yakalanmadı; sınır testi eklendi.

**Tam koşu değişmezleri** (tüm aday koşularında 0 ihlal):
- Giriş = q kapanışı = q+1 açılışı.
- Dolum = q kapanışı ± giriş kayması.
- DB stop/hedef = sinyal S/T.
- max_hold çıkışı = q+12 kapanışı ± çıkış kayması.
- stop/hedef çıkışı seviyede.
- ≤ 12 mum tutuş.
- Aynı hazırlıktan tekrar deneme 0.
- Aynı damgada aynı sembolde bot girişi 0.

Testlerin geçmesi kârlılık kanıtı değildir.

**İkiz kayıt notu:** DB'deki `exit_time`, asenkron kapanış kaydı yüzünden bazen bir damga geç
yazılıyor. Fiyat ve bakiye doğru. Tüm kollar için geçerli, sonucu değiştirmez. Analiz çıkış mumunu
veriden bulur.

## 7. Sınırlar
- **Dokunulmamış dönem yok:** Veri 2023-04 → 2026-07. Bu veri bot geliştirmede defalarca incelendi.
  2026-07-19 sonrası bu ortamda yok.
- **Dolum ve miktar:** Dolum ikizin kapanış fiyatıdır. Kontrat ve fiyat adımı yuvarlaması hiçbir kol
  için modellenmiyor. Aday nominali yüzlerce/binlerce USDT olduğu için etkisi ihmal edilebilir.
- **Kayma:** Aday için canlı kayma ölçümü yok.
  - Ana koşu 15.85bp giriş kaymasıyla yapıldı; bu ihtiyatlı bir varsayım.
  - Aday maliyet öncesi de negatif olduğu için karar maliyet varsayımına bağlı değil.
- **Miktar:** Sonuç 208 (S) ve 264 (B) işlem üzerinde.
  - Bütün yıllar, yönler ve coinler aynı işaretli.
  - En iyi işlemleri çıkarmak sonucu kötüleştiriyor. Olumsuz sonuç birkaç uç işlemden gelmiyor.

## 8. Yeniden üretme
```
cd <repo>                      # research/failed-pullback-v1 dalı
pip install -r requirements.txt pytest
python3 -m pytest -q arastirma/failed_pullback_v1/test_fpb.py
bash arastirma/failed_pullback_v1/kos_hepsi.sh ./fpb_kosular 3    # 12 koşu (~2 sa, 4 çekirdek) + analiz
```
Tek koşu: `AD=B MOD=B SLIP_KAT=1 FIX_FUNDING=0 REPLAY_DB=$PWD/B.db python3 arastirma/failed_pullback_v1/fpb_kos.py`.

## 9. Dosyalar
- **Kod:**
  - `fpb_aday.py`: kurallar ve akış göstergeleri.
  - `fpb_kos.py`: ikiz kancaları.
  - `fpb_risk_haritasi.py` ve `risk_haritasi.json`.
  - `fpb_analiz.py`, `kos_hepsi.sh`, `test_fpb.py`.
- **Sonuçlar:**
  - `karsilastirma.csv`: 12 koşu.
  - `sonuclar.json`: huni, istatistik, GA, yarılar, değişmezler, referans eşlemesi.
  - `ozsermaye_saatlik_{A,A75,B}.csv.gz`: ortak saatlik özsermaye (açık pozisyonlar dahil), marjin,
    stopa kadar açık risk.
  - `aday_islemler_{B,S}.csv`: a/p/f/q zamanları, yön, plan/dolum, stop/hedef, miktar, komisyon,
    kayma, funding, net PnL, R0, net R, işaretler.
  - `aday_engellenen_{B,S}.csv`, `aday_kirilim_{B,S}_{yil,coin,yon}.csv`.
  - `a_negatif_haftalar.csv`, `a_dusus_donemleri.csv`.
