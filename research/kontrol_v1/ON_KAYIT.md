# Test düzeneği kontrolü (pozitif / negatif kontrol) — ÖN KAYIT (2026-10-24, sonuçlardan ÖNCE)

Kullanıcı sorusu: "Uygun şekilde denememişizdir belki." SMC/ICT, mean reversion/range, formasyonlar ve gün içi
stratejiler elendi. Soru: elemeyi yapan test makineleri gerçek bir kenarı GÖREBİLİYOR mu (yanlış negatif), ve
kenar olmayan yerde sahte kenar ÜRETMİYOR mu (yanlış pozitif)? Bilinen cevaplı sinyaller makinelere verilir.

## Makineler (kodları değiştirilmez; kopyası scratchpad'de, yalnız sinyal YÖNÜ değiştirilir)
- **M1 SMC/ICT**: `research/liquidity_sweep_v1` (5m, 12 coin, sweep + MSS/FVG kurulumları).
- **M2 Formasyon / dönüş**: `research/mum_formasyon_v1/analiz.py` (pin bar, yutan, yıldız, iç mum, üç asker,
  marubozu; 4h/1D; eski12 seçim, yeni26 sınav).
- **M3 Gün içi / scalping**: `research/gun_ici_v1/analiz.py` (F1/F2 funding saati, C1 5m çöküş dönüşü).
Her makinenin kendi giriş zamanı, stop/hedef/süre kuralları, maliyeti (NORMAL), R/bp tanımı, bootstrap ve alt
sınır yöntemi AYNEN kullanılır (kendi ON_KAYIT'ındaki sınav/doğrulama kümesi ve istatistiği).

## Kontroller (her makinede, orijinal sinyallerin AYNI zaman ve coinlerinde)
- **NEG (negatif kontrol)**: her sinyalin yönü yazı-tura (`numpy.random.default_rng(20261024)`).
- **POS60 / POS55 (pozitif kontrol, bilerek geleceğe bakan)**: yön = sign(makinenin azami tutma süresinin sonundaki
  kapanış − giriş fiyatı); %60 (POS60) / %55 (POS55) olasılıkla bu yön, aksi halde ters (aynı seed). Eşitse yazı-tura.
- **INV (bilgi)**: orijinal yönün tersi.
Yön değişen işlemde stop ve hedef uzaklıkları giriş etrafında aynalanır (mesafeler aynı kalır).

## Ölçüt (değiştirilmeyecek)
Bir makine **SAĞLAM** ⇔ (1) NEG: maliyetsiz (brüt) ortalama 0'dan en fazla 3 standart hata uzakta VE NORMAL alt
sınır ≤ 0 (sahte kenar yok); (2) POS60: NORMAL ortalama > 0 VE makinenin kendi alt sınırı > 0 (gerçek kenarı
görüyor). POS55 ve INV karar dışı raporlanır (tespit gücü, simetri).
**DÜZENEK SAĞLAM** ⇔ üç makine de SAĞLAM. Bir makine sağlam değilse o makineyle elenen çalışmalar yeniden açılır.
Doğal pozitif kontrol (karar dışı, rapor): aynı tür ikiz/maliyet altyapısının donchian için verdiği +0.26R'nin
canlıda +0.25…+0.29R ölçülmesi.
Sonuç görüldükten sonra olasılıklar, seed, ölçüt ve makine listesi değiştirilmez.

---
## SONUÇ (2026-10-24) — ÖN KAYITLI HÜKÜM: DÜZENEK SAĞLAM DEĞİL (POS60 hiçbir makinede tam geçmedi) · makinelerde HATA YOK
| makine | ORIG yeniden üretim | NEG (sahte kenar yok) | POS60 (net > 0 ve alt > 0) | not |
|---|---|---|---|---|
| M1 SMC/ICT (22 varyant) | birebir (0 fark) | 22/22 geçti | 0/22 | POS60 brüt +0.04…+0.27R (büyük varyantlarda z≈3.6–4.1) ama maliyet ~0.27R/işlem → net negatif |
| M2 formasyon (12 test) | birebir | 11/12 (pinbar 1D: seed şansı, 200 başka seed'de 200/200 geçiyor) | 9/12 (12/12 net > 0) | pinbar 4h maliyeti 0.089R; yildiz/marubozu 1D örnek küçük |
| M3 gün içi (3 hipotez) | birebir | 3/3 | 0/3 | POS60 brüt 11–18 bp, maliyet 10 bp; POS70/80/100 geçiyor |

Denetçi: kopyalar bayt bayt aynı, yön değişimi dışında fark yok, 68/68 işlem elle doğrulandı, ölçüt doğru uygulandı.
Teşhis: başarısızlık KONTROL TASARIMINDAN — %60 isabetli kâhin tutma ufkunda yalnız ~0.1R / 10–18 bp brüt kenar
ekliyor, bu da her makinenin maliyet duvarı kadar ya da altında (M1'de kusursuz kâhin POS100 bile 2/10 varyantta net
negatif). Ön kayıttaki POS60 ölçütü "makine kenarı görüyor mu" ile "kenar maliyeti yener mi"yi karıştırdı — tasarım
hatası, açıkça belirtilir; hüküm değiştirilmez.
Anlamı: (1) makineler sahte kenar üretmiyor (37 karar testinin hepsinde NEG alt sınırı ≤ 0); (2) güçlü enjekte kenarı
görüyorlar, POS60'ın brüt kenarını M2/M3'te ve M1'in büyük varyantlarında açıkça ölçüyorlar; (3) elenen stratejilerin
ORİJİNAL brüt kenarı zaten ~0 (M1 medyan −0.003R ± 0.025, dönüş formasyonları brüt negatif) — bu, testin gücünden bağımsız
doğrudan ölçüm; (4) ama %55–60 isabetli mütevazı bir kısa vadeli kenar da bu maliyetlerle elenirdi. Yeniden açmanın
konusu motor hatası değil, kısa vadede maliyet duvarı: o stratejiler canlıda da aynı maliyeti öder.
