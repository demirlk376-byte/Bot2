# Gün içi v2 — maliyet duvarını yapısal olarak aşma: yalnız LİMİT (maker) emirli ortalamaya dönüş — ÖN KAYIT
(2026-10-17, sonuçlardan ÖNCE)

Gün içi v1 ve önceki 15 aile maliyet duvarına takıldı (taker giriş+çıkış 10–21 bp). Kalan tek yapısal kaldıraç
MALİYET: MEXC vadelide maker komisyonu %0. Giriş ve kâr alma DURAN LİMİT emirle yapılırsa gidiş-dönüş maliyeti
yalnız stop/süre çıkışlarında oluşur. Bedeli: ters seçilim (emir ancak fiyat aleyhe akarken dolar) — 5 dakikalık
mumlarla ve kuyruk payıyla muhafazakâr modellenir. Bu turun sonucu ne olursa olsun gün içi konusu KAPANIR
(sonsuz arama = sahte kazanan üretir).

## Veri
`research_data/liquidity_sweep_v1/veri/binance_5m/<COIN>.npz`, 12 coin, 2023-01-01 → 2026-09-30.
KEŞİF 2023-01-01 → 2024-12-31 · DOĞRULAMA 2025-01-01 → 2026-09-30 (giriş zamanına göre).

## Kural (M1 ve M2 yalnız bant genişliğinde farklı)
- 1 saatlik mumlar 5m'den kurulur. Her saat kapanışında (yalnız kapanmış 1h mumlarla) SMA20, std20, ATR14(1h).
- Pozisyon yokken o saat boyunca iki duran limit emir: ALIŞ = SMA20 − k·std20, SATIŞ = SMA20 + k·std20.
  k = 2.5 (M1) / 3.0 (M2). Emirler her saat yeniden hesaplanır (dolmamışsa iptal + yeni seviye).
- DOLUM (muhafazakâr kuyruk payı): bir 5m mumda düşük ≤ ALIŞ·(1 − 0.0002) ise ALIŞ fiyatından long;
  yüksek ≥ SATIŞ·(1 + 0.0002) ise SATIŞ fiyatından short. Aynı mumda ikisi birden → işlem yok (belirsiz).
  Mumun açılışı seviyenin zaten ötesindeyse (boşluk), gerçekte limit daha iyi fiyattan dolardı; muhafazakâr
  olarak dolum yine SEVİYE fiyatından sayılır (daha iyi fiyat kredi edilmez).
- KÂR AL: giriş anındaki SMA20'ye duran limit (maker); dolum için 5m yüksek ≥ TP·(1 + 0.0002) (long).
- STOP: giriş ∓ 2·ATR14(1h) (giriş anındaki değer); 5m mumda değerse stoptan, açılış ötesindeyse açılıştan.
  Aynı 5m mumda hem TP hem stop değerse STOP sayılır (muhafazakâr).
- SÜRE: 24 saat dolarsa sonraki 5m açılışında piyasa emriyle çıkış.
- Giriş mumunun kendisinde TP/stop kontrolü yalnız girişten SONRAKİ mumlardan başlar.

## Maliyet (bp, getiriden düşülür)
Giriş ve TP: 0 (maker). Stop ve süre çıkışı: NORMAL 2.5 komisyon + 3 kayma = 5.5 bp; STRESS 2.5 + 10 = 12.5 bp.

## Ölçüt (değiştirilmeyecek)
İşlem başı net bp; haftalık blok bootstrap (10 000, seed 20261018), 2 varyant → Bonferroni alt = %1.25 persentil.
Bir varyant **KAZANDI** ⇔ (1) keşif VE doğrulamada STRESS net ort > 0, (2) doğrulamada NORMAL net Bonferroni
alt > 0, (3) doğrulamada NORMAL net ort > 0 olan coin ≥ 8/12, (4) doğrulamada işlem ≥ 300. Aksi halde ELENDİ.
Rapor: dolum oranı, çıkış türü dağılımı (TP/stop/süre), yıl yıl, coin coin, uzun/kısa.

---
## SONUÇ (2026-10-17) — M1 ve M2 ELENDİ · GÜN İÇİ KONUSU KAPANDI
İki bağımsız uygulama + üçüncü denetim motoru; tek fark std/ATR tanımı (ddof, Wilder) — her tanımda sonuç aynı.
Gelecek veri yok, dolum modeli doğru. Son betik: `analiz.py`.

| varyant | dönem | işlem | brüt bp | net NORMAL | net STRESS | Bonf. alt | + coin |
|---|---|---|---|---|---|---|---|
| M1 (2.5σ) | keşif | 14876 | −24.4 | −27.6 | −31.8 | −36.5 | 0/12 |
| M1 | doğrulama | 12329 | −21.2 | −24.5 | −28.8 | −36.1 | 0/12 |
| M2 (3σ) | keşif | 10785 | −10.1 | −13.5 | −17.8 | −22.2 | 0/12 |
| M2 | doğrulama | 8601 | −11.2 | −14.6 | −18.9 | −27.4 | 0/12 |

Maliyet sıfıra yakınken bile BRÜT getiri negatif: limit emirler çoğunlukla fiyat aynı yönde akmaya devam
ederken doluyor (ters seçilim) — stop payı %51, kâr alma %39. Gün içi ortalamaya dönüş bu piyasada çalışmıyor.
Gün içi: v1 (3 hipotez) + v2 (2 varyant) + önceki ~15 aile = hepsi elendi. Konu kapandı.
