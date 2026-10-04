# SWEEP_V2 — likidite avına filtreler, önceden kayıt (2026-10-04, veri inerken, sonuçlardan ÖNCE)

**Kullanıcı isteği:** farklı zaman dilimleriyle yön onayı, yalnız seans saatleri, hacim, retest, emir
defteri ve varsa başka filtreler; tek tek ve birlikte.

**Taban:** SWEEP_V1 motoru ve tanımları aynen.
- Seviye ailesi L3 (onaylı swing pivot), giriş K2 (15m kapanışla seviyeye geri dönüş), F0.
- Gerekçe: en yaygın "likidite" tanımı ve "onaylı" giriş. Örneklem de en büyüklerden.
- V1'de bu taban keşifte −0.30R (n = 3.269). Maliyetsiz kenarı ≈ 0.

**Önemli uyarı:** sıfır kenarlı bir tabana filtre eklemek nadiren gerçek kenar yaratır; çoklu deneme şans
eseri "kazanan" üretir. Bu yüzden karar eşiği çoklu teste göre sertleştirildi (aşağıda).

## Filtreler
Hepsi sinyal anında bilinen veriyle; gelecek yok.

| kod | kural |
|---|---|
| **MTF** | LONG yalnız 4h kapanış > 4h EMA200 VE 1D kapanış > 1D EMA50 iken; SHORT tersi. Sinyalden önceki son tamamlanmış 4h/1D mumları; 5m'den kurulur. |
| **SEANS** | sinyal saati UTC [07:00, 21:00) içindeyse (Londra + New York). |
| **HACIM** | ihlal mumunun (sweep_open) 5m hacmi ≥ 1.5 × önceki 48 adet 5m mumunun medyan hacmi. |
| **RETEST** | K2 sinyalinden sonra en fazla 12 adet 5m mum içinde fiyat süpürülen seviyeye geri dokunur ve doğru tarafta kapatırsa o mumun kapanışında yeni sinyal. Long: low ≤ seviye + 0.10×ATR15 VE close > seviye. Stop aynı kural (ihlal ucu − 0.10×ATR15), hedef 2R yeni girişten. Retest olmazsa işlem yok. |
| **ORDERBOOK** | sinyal anındaki SON 5m emir defteri dengesizliği (±%1 bant): LONG için imb1 > 0, SHORT için < 0. Veri yoksa işlem yok. |
| **OI** | sinyalden önceki 1 saatte açık pozisyon (15m metrics) AZALMIŞ olmalı: zorla kapanan pozisyonların süpürdüğü hareket. |
| **KALABALIK** | LONG yalnız perakende L/S z(30g) < 0 (kalabalık short tarafta); SHORT yalnız z > 0. |
| **HEPSI** | yedi filtre birlikte. |

**Varyantlar (9):** TABAN, 7 tek filtre, HEPSI.

## Yürütme ve karar
- **Yürütme, maliyet, risk:** V1 ile aynı (`replay_adapter.simulate`, NORMAL/STRESS, %0.25 risk).
- **Dönemler:** V1 ile aynı (KEŞİF 2023-02-12 → 2025-04-18, DOĞRULAMA → 2026-01-08). FİNAL (2026-01-08 →) AÇILMAZ.
- **Seçim:** keşifte `liquidity_sweep_v1.selection` aynen (örneklem tabanları ve LCB).
- **Çoklu test düzeltmesi:** doğrulamada bir varyant ancak şu ikisi birden sağlanırsa **TUTTU** sayılır:
  - V1 kuralları;
  - haftalık blok bootstrap alt sınırı yüzdelik 0.28 (9 varyant için Bonferroni, %95 tek taraflı) > 0.
- **ORDERBOOK ve OI verisi:** yalnız 12 coin ve veri kapsamında. Kapsam dışı sinyal işlem yapmaz;
  kapsam oranı raporlanır.

Sonuçtan sonra eşik, pencere ya da filtre tanımı değiştirilmez; ek filtre aranmaz.
