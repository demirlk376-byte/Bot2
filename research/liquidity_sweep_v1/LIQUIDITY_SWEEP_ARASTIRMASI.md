# LIQUIDITY_SWEEP_V1 — sonuç (2026-10-02)

**KARAR: KANIT YETERSİZ** (`DISCOVERY_SOME_UNDETERMINED`)

Örneklemi yeterli olan **22 varyantın 22'si de ELENDİ**. Hepsi iki maliyet senaryosunda da
negatif; çoğunun %95 aralığı tamamen sıfırın altında.

Kalan 10 varyantın işlem sayısı 7–67 arasında; bu yüzden karar verilemiyor. Şartname §18.5
öncelik 1 gereği: örneklem tabanı sağlanmadığında hüküm ELENDİ değil KANIT YETERSİZ'dir.
Doğrulamaya hiçbir aday geçmedi; doğrulama ve final aşamaları AÇILMADI.

Olumlu bir sonuç olsaydı bile bu, canlıya alma onayı olmazdı.

## Koşu kimliği ve tekrar üretim
- **run_id:** `20261002T115151Z_0f5afa63_157aff93`
- **manifest hash:** `157aff931031…`
- **commit:** `0f5afa6` (dal `research/liquidity-sweep-v1`)
- **Komut:** `python3 -m research.liquidity_sweep_v1.cli verify && python3 -m research.liquidity_sweep_v1.cli run-all --jobs 1`.
  Tek komutluk sürüm: `run_sweep_v1.sh`.
- **Veri:** GitHub `veri/sweep5m` dalı (`git archive origin/veri/sweep5m veri`).
  - Binance USDⓈ-M 5m, 12 coin, 2023-01-01 → 2026-09-30.
  - Sembol başına 394.272 bar, eksik bar 0.
  - Binance fundingRate (4.107 settlement/sembol, kapsam boşluğu 0).
  - MEXC contract/detail.
- **Dönemler:**

  | aşama | aralık |
  |---|---|
  | T0 | 2023-02-12 |
  | KEŞİF | 2023-02-12 → 2025-04-18 |
  | DOĞRULAMA | 2025-04-18 → 2026-01-08 |
  | FİNAL | 2026-01-08 → 2026-10-01 |

  Hiçbir dönem dokunulmamış değil (`previous_data_use`).
- **Maliyet:** ikizin belgelenmiş piyasa profili.
  - NORMAL: komisyon 1bp/taraf, giriş kayması 15.85bp, çıkış kayması 0.24bp.
  - STRESS: kaymalar 2 kat.
  - TP de piyasa emri sayıldı.
- **Risk:** C0 = 10.000 (araştırma varsayımı), işlem başı ilk-stop riski 25 USDT, toplam 100 USDT.
  Canlı LEVERAGE, MAX_POSITIONS, POSITION_CAP_FRACTION ve DAILY_MAX_LOSS_PCT kapıları uygulandı.

## Keşif sonuçları (NORMAL; STRESS ayrı sütunda)

| varyant | durum | işlem | ort. net R | %95 GA | PF | net USDT | MDD % | STRESS R |
|---|---|---|---|---|---|---|---|---|
| L1_K1_F0 | ELENDİ | 2827 | −0.326 | [−0.37, −0.28] | 0.52 | −10.000 | 100 | −0.44 |
| L1_K1_F1 | ELENDİ | 1230 | −0.305 | [−0.37, −0.24] | 0.54 | −9.028 | 91 | −0.41 |
| L1_K2_F0 | ELENDİ | 2194 | −0.189 | [−0.24, −0.14] | 0.71 | −9.548 | 96 | −0.30 |
| L1_K2_F1 | ELENDİ | 622 | −0.223 | [−0.33, −0.12] | 0.65 | −3.466 | 36 | −0.33 |
| L1_K3_F0 | ELENDİ | 253 | −0.219 | [−0.36, −0.07] | 0.61 | −1.383 | 15 | −0.30 |
| L1_K3_F1 | örneklem az | 67 | −0.385 | [−0.60, −0.14] | 0.37 | −644 | 7 | −0.45 |
| L1_K4_F0 | örneklem az | 45 | +0.089 | [−0.23, +0.40] | 1.21 | +100 | 2 | −0.02 |
| L1_K4_F1 | örneklem az | 9 | +0.008 | [−0.74, +0.89] | 1.01 | +2 | 1 | −0.12 |
| L2_K1_F0 | ELENDİ | 2960 | −0.375 | [−0.42, −0.33] | 0.51 | −10.000 | 100 | −0.50 |
| L2_K1_F1 | ELENDİ | 2135 | −0.367 | [−0.41, −0.32] | 0.47 | −9.998 | 100 | −0.49 |
| L2_K2_F0 | ELENDİ | 2794 | −0.250 | [−0.30, −0.20] | 0.57 | −9.999 | 100 | −0.38 |
| L2_K2_F1 | ELENDİ | 1256 | −0.284 | [−0.34, −0.22] | 0.58 | −8.769 | 89 | −0.38 |
| L2_K3_F0 | ELENDİ | 350 | −0.252 | [−0.36, −0.15] | 0.60 | −2.199 | 23 | −0.34 |
| L2_K3_F1 | ELENDİ | 139 | −0.229 | [−0.41, −0.05] | 0.65 | −795 | 9 | −0.32 |
| L2_K4_F0 | örneklem az | 55 | −0.094 | [−0.42, +0.26] | 0.82 | −129 | 2 | −0.20 |
| L2_K4_F1 | örneklem az | 27 | +0.028 | [−0.41, +0.51] | 1.05 | +18 | 2 | −0.10 |
| L3_K1_F0 | ELENDİ | 3362 | −0.389 | [−0.43, −0.35] | 0.50 | −10.000 | 100 | −0.49 |
| L3_K1_F1 | ELENDİ | 2872 | −0.392 | [−0.44, −0.35] | 0.44 | −10.000 | 100 | −0.53 |
| L3_K2_F0 | ELENDİ | 3269 | −0.302 | [−0.35, −0.26] | 0.58 | −10.000 | 100 | −0.42 |
| L3_K2_F1 | ELENDİ | 2532 | −0.303 | [−0.35, −0.26] | 0.52 | −10.000 | 100 | −0.43 |
| L3_K3_F0 | ELENDİ | 841 | −0.177 | [−0.27, −0.09] | 0.70 | −3.722 | 39 | −0.27 |
| L3_K3_F1 | ELENDİ | 348 | −0.198 | [−0.34, −0.06] | 0.69 | −1.723 | 18 | −0.29 |
| L3_K4_F0 | ELENDİ | 136 | −0.090 | [−0.30, +0.14] | 0.84 | −305 | 5 | −0.19 |
| L3_K4_F1 | örneklem az | 57 | −0.175 | [−0.48, +0.18] | 0.72 | −249 | 3 | −0.26 |
| L4_K1_F0 | ELENDİ | 839 | −0.346 | [−0.42, −0.27] | 0.50 | −7.245 | 73 | −0.47 |
| L4_K1_F1 | ELENDİ | 404 | −0.290 | [−0.41, −0.18] | 0.56 | −2.926 | 30 | −0.43 |
| L4_K2_F0 | ELENDİ | 582 | −0.300 | [−0.40, −0.20] | 0.55 | −4.359 | 44 | −0.40 |
| L4_K2_F1 | ELENDİ | 248 | −0.286 | [−0.40, −0.16] | 0.57 | −1.770 | 19 | −0.40 |
| L4_K3_F0 | örneklem az | 55 | +0.084 | [−0.23, +0.38] | 1.17 | +115 | 2 | −0.04 |
| L4_K3_F1 | örneklem az | 31 | −0.049 | [−0.49, +0.38] | 0.92 | −38 | 2 | −0.16 |
| L4_K4_F0 | örneklem az (iki maliyette +) | 12 | +0.147 | [−0.62, +0.72] | 1.34 | +44 | 1 | +0.05 |
| L4_K4_F1 | örneklem az | 7 | −0.261 | [−1.04, +0.78] | 0.65 | −46 | 1 | −0.33 |

"Net USDT −10.000" satırları hesabın bitmesini gösterir. Sabit 25 USDT risk ve binlerce
negatif işlemden sonra marjin kapıları yeni girişi durdurdu.

## Teşhis (seçime girmedi)
- **Maliyet öncesi kenar yok:** Aynı keşif koşuları SIFIR maliyetle tekrarlandı. İşlemi bol olan
  varyantların ortalama R'si −0.03 ile +0.03 arasında; örneğin L3_K1_F0 11.469 işlemde −0.012,
  L1_K1_F0 3.774 işlemde −0.007.
  - Bu, 2026-08 Binance 5m Sweep+Reclaim testinin (24.307 işlem, brüt −0.010R) bulgusunun
    aynısıdır.
  - İşlem başına ~0.3R maliyet (giriş kayması + komisyon), sıfır kenarı belirgin zarara çeviriyor.
- **K4 kombinasyonları:** Maliyetsiz R'leri olumlu görünüyor (+0.08 ile +0.30), ama işlem sayıları
  7–136. Şartnamenin aday seçimine giremezler. Sonradan bunları seçmek, §1'in yasakladığı "kazanan
  alt grubu sonradan seçme" olur.
- **F1 karşılaştırması:** `f0_f1_karsilastirma.csv`. Trend filtresi sinyallerin çoğunu eliyor,
  ama elenmeyenler de negatif.
- **Kırılımlar:** `breakdowns_discovery_NORMAL.csv` (yıl/çeyrek/coin/yön, K/F grupları).

## Doğrulama ve uyum (koşu öncesi, aynı kodla)
- **Testler:** 445 davranış testi geçti (`tests_report.txt`).
  - Bağımsız test yazarları beklenen değerleri koddan değil şartnameden türetti.
  - §21'deki 38 sayısal örnek, kısa-yön aynaları, kesim/gelecek değişikliği değişmezliği.
- **Uyum kapıları** (`fidelity_report.md`), altısı da geçti:

  | kapı | sonuç |
  |---|---|
  | G1 testler | 445 test geçti |
  | G2 gerçek `PaperExchange` mutabakatı | 400 işlem, en büyük fark 6e-11 USDT |
  | G3 referans izolasyonu | eski 1H ikizin 25 işlemi, paket yüklüyken/değilken ve 936 referansıyla birebir |
  | G4 30 günlük duman | 32 varyant hatasız |
  | G5 determinizm | tekrarlar aynı hash |
  | G6 yanlılık | sentetik rastgele yürüyüşte maliyetsiz ort. R +0.05, z=1.5 |
- **Şüpheci denetim:** Altı alanda şüpheci denetçi kodu şartnameyle karşılaştırdı.
  - Tek YÜKSEK bulgu: funding kapsamı denetimi. Bu veride gerçekleşmedi (kapsam tam), yine de
    düzeltildi.
  - İşlem ya da seçimi etkileyebilecek bütün orta bulgular koşudan ÖNCE düzeltildi.

## Bilinen sınırlamalar
- **Venue vekili:** Fiyatlar Binance USDⓈ-M; MEXC 5m geçmişi yalnız 2025-10'dan var.
  - Tick, kontrat ve minimum emir MEXC'in GÜNCEL metadatası; tarihsel değil.
  - Funding Binance vekili; mark yerine son 5m kapanışı.
- **Yürütme idealize:** İlk 5m açılışında tam dolum. Emir defteri, kuyruk ve gecikme modellenmedi.
  Likidasyon modellenmedi.
- **Hayatta kalma yanlılığı:** Evren bugünkü 12 sembol; delist olmuş sözleşme yok.
- **Raporlama denetiminin açık kalan bulguları** (sonucu değiştirmeyen; sonraki sürümde
  düzeltilecek):
  - Tek tek aşama komutlarında da RUN_FAILED kaydı.
  - Raporda yüklenen veri hash'lerinin tam eşleşmesi.
  - events.csv'de portföy sonucu için `reason_code`.
  - Bölüm sonunda bekleyen kurulumların CENSORED işaretlenmesi (işlemleri etkilemez).
  - Kırılımlarda boş dönem satırları.
  - Uyum çıktılarının koşu klasörüne atomik kopyası. Bu koşuda elle kopyalandı.

## Dosyalar
- **Kod ve testler:** `research/liquidity_sweep_v1/`.
- **Bu koşunun küçük çıktıları:** `sonuclar/20261002T115151Z_0f5afa63_157aff93/`
  - manifest, seçim dosyaları, `variant_results.csv`, `decision.json`, `data_quality.json`
  - `fidelity_report.md`, `tests_report.txt`
  - kırılımlar ve F0/F1 karşılaştırması
- **Büyük çıktılar repoya alınmadı** (koşu başına trades/events/equity_5m, toplam ~355 MB).
  Komutla yeniden üretilir.
- **Ek belge:** `ESKI_YENI_FARKLAR.md` (eski sweep kurguları ↔ bu deney).
