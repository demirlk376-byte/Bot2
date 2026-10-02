# NWK_FILTRE_V3 — önceden kayıt (2026-10-02, sonuçlardan ÖNCE)

V1/V2 motoru, verisi, maliyeti, riski ve dönemleri aynen. FİNAL açılmaz.

## Kullanıcı kararı (V2'den)
T1 (N50_X5_L + E10 erken çıkış), "yarı düşüş, biraz daha az kâr" tercihiyle trend adayı olarak işaretlendi.
Bu bir tercih kararıdır; V2'nin ön-kayıtlı benimseme kuralı onu reddetmişti. Her iki gerçek kayıtlı.
Hükmü yalnız ileride FİNAL ya da kâğıt-takip verir.

## Soru
NW+KAMA (event_A, 3/15/1.5/5/1, kod aynen) girişine standart filtreler ve 2 günlük mum eklemek
sonucu iyileştiriyor mu? Çıkış V2-H2 ile aynı: X3 ATR takip stopu (günlük), LS.

## Varyantlar (8 = 2 zaman dilimi × 4 filtre)
- **Zaman dilimi:** 1D, ya da 2D. 2D = UTC epoch'tan 2 günlük blokların son günü kapanışı; giriş ertesi açılış.
- **Filtreler** (sinyal gününün günlük kapanışında):

  | kod | kural |
  |---|---|
  | F0 | yok |
  | F1 | coin kapanışı SMA200 üstündeyse yalnız long, altındaysa yalnız short |
  | F2 | ETH kapanışı SMA200 üstündeyse yalnız long, altındaysa yalnız short (piyasa rejimi; BTC 1d verisi yok) |
  | F3 | ADX14 (Wilder) > 20 |

Kimlik: `NWK{1D|2D}_{F0..F3}`. Eşikler (200, 20, 14) ders kitabı değerleri, ayarlanmaz.

## Karar kuralı (sabit)
- **Filtre:** Fk, aynı zaman dilimindeki F0'a göre "iyileştirme" sayılır, ancak hem KEŞİF hem DOĞRULAMA'da
  (NORMAL) şu dördü birden sağlanırsa:
  - ortalama R > F0,
  - MDD ≤ F0,
  - toplam getiri ≥ 0.75 × F0,
  - STRESS toplamı > 0.
- **2D:** 2D_Fk, 1D_Fk'ya göre aynı kuralla değerlendirilir.
- **İstatistiksel hüküm:** `liquidity_sweep_v1.selection` ile aynen.
- **Teşhis (karar dışı):** en iyi varyant + T1 birleşik hesap.

Sonuç görüldükten sonra hiçbir eşik, filtre ya da kural değiştirilmez.
