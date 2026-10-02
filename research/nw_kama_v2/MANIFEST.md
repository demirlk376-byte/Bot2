# NW+KAMA V2 — önceden kayıt (2026-10-02, sonuçlardan ÖNCE)

## Soru
Nadaraya-Watson zarfı (aşırı uç) ile KAMA'nın (Kaufman adaptif ortalama) aynı yönde birleştiği
kombinasyonlar, gerçek maliyetler düşüldükten sonra bir kenar üretiyor mu? Hangi zaman dilimi
ve kombinasyon modu?

## Geçmiş (bu test bunlardan bağımsız yeniden yapılıyor)
- 2026-07 `nw_kama_combo.py`, 4h/1G/2G: kombo −78$. NW tek başına −656$, KAMA tek başına +107$
  (PF 1.13, yalnız short).
- 2026-07 `validate_nw_kama.py`: 10 coin × 11 config; 2/10 coin "güçlü". Bu, çoklu karşılaştırma
  şansının öngördüğü sayı.
- 2026-07-14 → `nw_kama_tracker.py`: ETH+AVAX 1G event, ileriye dönük takip.
  - Karar kuralı: n≥15 ve PF≥1.3.
  - Sonucu VPS'teki `nw_kama_status.txt` dosyasında; bu teste karışmaz.

## Sinyal tanımları (KOD DEĞİŞMEDEN `validate_nw_kama.py`'den alınır)
- **event:** NW bandı son `lb` bar içinde uçta **ve** KAMA bu bar aynı yönde KESİŞİYOR (+eğim).
- **state:** NW bandı son `lb` bar içinde uçta **ve** fiyat KAMA'nın tarafında, eğim aynı yönde.
  3 bar içinde yeniden sinyal yok.
- **agree:** KAMA durumu (son kesişim) ile NW durumu (bant dokunuşu, ortalamaya dönüşte nötr)
  aynı yöne döndüğü İLK bar.

Göstergeler nedenseldir (NW uç nokta tahmini; MAE geçmiş pencereden).

## Matris: 4 zaman dilimi × 3 mod × 2 parametre seti = 24 varyant
- **Zaman dilimi:** 1h, 2h, 4h, 1D. Barlar 5m ızgaradan türetilir; tüm alt barlar tam olmalı.
- **Parametre setleri** (`validate_nw_kama.GRID`'den):

  | set | h | win | mult | er | lb (event / state / agree) |
  |---|---|---|---|---|---|
  | A (hızlı) | 3 | 15 | 1.5 | 5 | 1 / 2 / 0 |
  | B (yavaş) | 5 | 25 | 2.0 | 10 | 2 / 3 / 0 |

- **Varyant kimliği:** `{TF}_{mod}_{A|B}`, ör. `2h_event_A`.

## Giriş, çıkış, maliyet, risk, dönem, seçim
- **Giriş:** Sinyal TF barının kapanışında bilinir. Giriş, sonraki 5m AÇILIŞINDA yapılır
  (`liquidity_sweep_v1.replay_adapter`, aynı olay sırası).
- **Stop/hedef:** Sinyal anında sabitlenir. S = E ∓ 2·ATR14(TF), T = E ± 4·ATR14(TF).
  Tick yuvarlaması aleyhe yapılır. Tutuş en fazla 15 TF barı.
- **Maliyet:**
  - NORMAL: 1bp/taraf komisyon, 15.85bp giriş kayması, 0.24bp çıkış kayması.
  - STRESS: kaymalar ×2.
  - Funding: Binance vekili.
- **Risk:** C0 10.000, işlem başı 25 USDT, toplam 100 USDT. Canlı kapılar uygulanır.
- **Veri:** `veri/sweep5m` (Binance USDⓈ-M 5m, 12 coin). Sweep testinin aynısı; aynı T0/B1/B2/T1:
  - KEŞİF 2023-02-12 → 2025-04-18
  - DOĞRULAMA → 2026-01-08
  - FİNAL → 2026-10-01
- **Seçim ve karar:** `liquidity_sweep_v1.selection` aynen.
  - Örneklem tabanları 100/12/26, 50/8/13, 30/6/13.
  - Keşiften en fazla 3 aday, doğrulamadan 1 aday.
  - LCB > 0 şartı doğrulama ve finalde aranır.
  - Final "previously_examined" olduğundan en iyi hüküm KANIT YETERSİZ olabilir.
- **İstatistik:** 4 haftalık blok bootstrap, 10.000 tekrar, seed 20261001.

Sonuç görüldükten sonra hiçbir eşik, mod, zaman dilimi ya da parametre değiştirilmez.

## Düzeltme 1 (2026-10-02, ilk koşudan SONRA — teknik, parametre değil)
İlk koşu (`20261002T202306Z_331facb3_d053a78d`) 11 varyantı TECHNICAL_INVALID işaretledi:
dönem sonu giriş yasağı sweep'ten kalan 12 saatti, oysa bu deneyde tutuş 15 TF barı (1D'de 15 gün).
Pozisyonlar bölüm bitince açık kalıp defter uzlaşmasını bozdu (CENSORED). Şartnamenin ilkesi
"çıkış için bir sonraki bölümün fiyatı gerekmesin" olduğundan yasak penceresi
max(12 saat, varyantın tutuş süresi) yapıldı. Hiçbir sinyal/eşik/parametre değişmedi; ilk koşu
INVALIDATED olarak saklandı.
