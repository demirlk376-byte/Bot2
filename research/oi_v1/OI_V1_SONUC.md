# OI_V1 — sonuç (ön kayıt MANIFEST.md, commit 55c1c93; motor 5/5 test)

Koşu çıktısı: `sonuclar/kos.txt`, `sonuclar/rapor.json`.

## Aile B — OI uyumsuzluğu (OD): ELENDİ
Eski 12'de 16 varyantın 16'sı da negatif (−0.06…−0.15R NORMAL). Sınava gidilmedi. Yeni zirvede OI düşüşü
tükenme değil; fiyat devam ediyor (ledger'daki "bu piyasa momentum piyasası" bulgusuyla uyumlu).

## Aile A — tasfiye çağlayanı sonrası dönüş (TC): KURALA GÖRE TUTTU, TEŞHİSTE ZAYIF
- Seçim (eski 12): TC_k2_t6_H3_L (long-only; 4h mum ≥2×ATR düşüş VE OI ≥%6 düşüş → sonraki açılışta long,
  12 saat tut, 2×ATR stop). Komşu long varyantların çoğu da pozitif.
- Sınav (yeni 26): n 271, NORMAL **+0.160R**, STRESS **+0.135R**, LCB(%1.25) **+0.002R** → ön kayıtlı
  kurala göre **TUTTU** (sınırda).
- Yıl (yeni 26): 2022 −0.035 (55) · 2023 +0.202 (132) · 2024 +0.115 (75) · 2025 +1.093 (9).
- Donchian (ikiz) ile haftalık korelasyon −0.03 → gerçekten bağımsız.

### Teşhis (karar dışı, ama dağıtım kararını belirler)
- 38 coinde 406 işlem yalnız **83 ayrı mumda** açılıyor: tasfiye çağlayanları piyasa çapında. Bir mumda
  30 coine kadar aynı anda giriş. Medyan olay 2 coin, %75'lik 5.5.
- **Olay başına** (her çağlayan bir gözlem) ortalama R **+0.006**, %95 [−0.131, +0.141]; olumlu olay %53.
  Yıl yıl olay başı: 2022 0.000 · 2023 +0.001 · 2024 −0.051 · 2025 +0.235 (7 olay).
- Yani işlem başı +0.16R, az sayıda BÜYÜK (çok coinli) çağlayanın sert dönüşünden geliyor. Tek tek
  olaylarda güvenilir bir kenar yok; etkin örnek ~83 olay ve sonuç birkaç olaya bağlı.
- Canlıda aynı anda 30 long açmak kabul edilemez; olay başı tavan konursa beklenti olay-başı ortalamaya
  (~0) yaklaşır.

## Hüküm
Ön kayıtlı istatistik kuralı geçildi ama sonucun birkaç piyasa çapında olaya dayandığı görüldü.
**Gerçek parayla DAĞITILMAZ.** İstenirse yalnız sinyal modunda ileriye dönük izleme (emir yok).
