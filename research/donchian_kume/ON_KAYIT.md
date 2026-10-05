# Donchian "küme" filtresi — ÖN KAYIT (2026-10-05, sonuçlardan önce)

Kullanıcı fikri: donchian aynı anda (aynı 4h kapanışında) en az K coinde sinyal verirse hepsine gir,
vermezse hiç girme; isteğe bağlı olarak küme girişinden sonra 2 gün yeni işlem açma.

## Veri
Gerçek maliyetli ikiz (ikiz_gercek.db: giriş kayması 15.85bp, çıkış 0.24bp, komisyon 2.5bp, funding,
squeeze kapalı), 412 donchian işlemi, 2023-04-07 → 2026-07-18. Küme = aynı 4h giriş mumu.
Not: ikiz işlemleri sonradan süzülür (boşalan koltuklara girebilecek başka sinyaller modellenmez —
koltuk tavanı 7, donchian işlemlerinin çoğu tavana takılmıyor; sınırlama olarak raporlanır).

## Varyantlar
- TABAN: tüm donchian işlemleri.
- K3, K4: yalnız küme büyüklüğü ≥ 3 / ≥ 4 olan mumlardaki işlemler.
- K3_B2, K4_B2: aynısı + küme girişinden sonraki 48 saat içinde açılan (küme dışı/içi) işlemler atlanır.
- Tamamlayıcı teşhis: küme büyüklüğü 1, 2, 3, 4+ için işlem başı ort R.

## Ölçüt (değiştirilmeyecek)
Bir varyant TABAN'dan İYİ sayılır ancak:
1. Toplam R (Σ R) TABAN'dan yüksek, VE
2. Her iki yarıda da (2023-04→2024-12, 2025-01→2026-07) toplam R TABAN'dan yüksek, VE
3. Hesap etkisi: işlem başı %3.5 risk, bileşik, ay sonu değerleriyle en büyük düşüş TABAN'dan kötü değil.
Aksi halde ELENDİ.

---
## SONUÇ (sonuc.txt) — 4/4 varyant ELENDİ
- Tek başına gelen sinyaller (küme 1: 280 işlem) ort **+0.270R**; küme 2: +0.297R; küme 3: −0.422R
  (15 işlem, 5 an); küme 4+: +0.071R (57 işlem, 11 an — hepsi SHORT, piyasa çapında çöküş anları).
- K3: 72 işlem, ΣR −2.3 (taban +91.1), maxDD %47.7 (taban %34.4). K4: ΣR +4.1, maxDD %44.5.
  2 gün bekleme kuralı sonucu değiştirmiyor (kümeler zaten 48 saatten seyrek).
- Hüküm: kümeye göre girmek kârın ~%95'ini atıyor ve düşüşü büyütüyor. Kenar tek başına gelen
  kırılımlarda.
