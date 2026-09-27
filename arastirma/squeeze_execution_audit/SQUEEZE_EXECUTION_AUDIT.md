# Squeeze giriş kayması denetimi (canlı)

## Sonuç (VPS 2. koşu, 2026-09-27; canlı işlemler 2026-06-30 → 2026-09-23)

```
SQUEEZE n:                         19 taker (R için stopu bilinen 19) · tüm dolumlar 21
SQUEEZE mean/median slippage bp:   +1.49 / +0.71    (%95 GA [−2.52, +5.13])
SQUEEZE mean slippage R:           +0.0232  (medyan +0.0128)
DONCHIAN n:                        64 taker · tüm dolumlar 75
DONCHIAN mean/median slippage bp:  +12.30 / +9.63   (%95 GA [+7.29, +17.58])
IKIZ assumption:                   15.85bp
SQUEEZE gross edge lost:           %3.8 (ölçülen bp, ikiz stoplarıyla)
                                   %9.9 (ölçülen canlı R doğrudan) · ikiz varsayımıyla %40.0
notional-slippage relationship:    INSUFFICIENT (squeeze n=19)
HÜKÜM:                             D
```

### Hüküm: D — önceden sabitlenen kural gereği

Squeeze taker n=19, sınır 20. Kural "n<20 → D" diyor ve bu kural veri görülmeden
yazıldı. Sonuç zorla A yapılmadı.

Ama işaret güçlü ve tek yönlü:
- %95 güven aralığının **üst** ucu +5.13bp. Bu, 15.85bp'nin üçte biri.
- 20. işlemle ortalamanın 15.85bp'ye çıkması için o işlemin tek başına
  **≥ +289bp** aleyhe kayması gerekir:

  ```
  20 × 15.85 − 19 × 1.49 = 288.7
  ```

- Ölçülen canlı squeeze kayması ikiz varsayımının yaklaşık 1/10'u.
- Bir sonraki squeeze piyasa girişiyle betik yeniden koşulmalı; kural hükmü o zaman
  kendisi verir.

### Ana kıyas (ücret HARİÇ; + = aleyhe)

| grup | n | ort bp | medyan | p25 / p75 | p90 | %95 GA | ort R | medyan R |
|---|---|---|---|---|---|---|---|---|
| **SQUEEZE taker (ANA)** | 19 | **+1.49** | +0.71 | +0.15 / +5.37 | +8.72 | [−2.52, +5.13] | **+0.0232** | +0.0128 |
| SQUEEZE tüm dolumlar | 21 | +1.35 | +0.60 | +0.00 / +5.04 | +6.94 | [−2.21, +4.74] | +0.0210 | +0.0077 |
| **DONCHIAN taker (ANA)** | 64 | **+12.30** | +9.63 | +0.00 / +23.24 | +41.35 | [+7.29, +17.58] | +0.0306 | +0.0263 |
| DONCHIAN tüm dolumlar | 75 | +10.50 | +5.01 | +0.00 / +18.78 | +37.45 | [+6.00, +15.09] | +0.0265 | +0.0191 |
| İKİZ varsayımı | — | 15.85 | | | | | | |

- **Canlı ortalama stop:** squeeze %1.28, donchian %4.19. Ücret ayrı: taker girişte 1.00bp.
- **Stop kaynağı:**
  - squeeze: `sl0` 2, ATR ile doğrulanmış `sl_price` 19
  - donchian: `sl0` 1, ATR ile doğrulanmış 73, bilinmiyor 1 (bu işlemin bp'si sayıldı, R'si sayılmadı)
- **Elenen:** squeeze 1 işlem (`intended_entry` kaydı yok). Tahmini dolum 0.
- **Donchian tutarlılığı:** Canlı donchian +12.30bp ölçüldü ve %95 GA 15.85'i içeriyor.
  Yani ikizin donchian'dan aldığı 15.85bp ile tutarlı.

### Alt gruplar (squeeze; hepsi n<20, yalnız betimsel, hüküm yok)

- **Dolum tipi:** maker n=2 (0.00bp), taker n=19 (+1.49bp).
- **Coin (taker):**

  | coin | n | ort |
  |---|---|---|
  | DOGE | 4 | +0.49 |
  | TRX | 3 | +0.40 |
  | XLM | 7 | +1.18 |
  | XRP | 5 | +3.37 |

- **Yön:** long n=11 −1.65bp · short n=8 +5.80bp.
- **Nominal dilimi:** küçük n=7 +7.08 · orta n=6 +0.56 · büyük n=6 −4.11.
  Büyüklükle artan bir kayma görünmüyor, ama n çok küçük.

### Nominal / kayma (bölüm 7)

- **squeeze:** n=19 < 20 → **ölçülemiyor (INSUFFICIENT)**.
- **donchian (karşılaştırma):** Spearman rho −0.091, p 0.484, n=64. Bugünkü hesap
  büyüklüğünde nominal arttıkça kaymanın arttığına dair bir işaret yok.
- **Kapsam sınırı:** Canlı nominaller küçük (hesap yaklaşık $330). İkizin büyük hesap
  aşamalarında sabit bp varsayımı bu veriyle **sınanamaz**.

### Ekonomi (bölüm 6; yeni backtest yok)

- İkizin 368 squeeze işlemi: brüt (giriş kayması öncesi) ort **+0.2341R**.

| giriş kayması | kayma R | net R | ham edge'in payı |
|---|---|---|---|
| İkiz varsayımı 15.85bp (ikiz stopları, ort %2.14) | 0.0937 | +0.1404 | **%40.0** |
| Ölçülen 1.49bp, ikiz stoplarına uygulanmış | 0.0088 | +0.2253 | **%3.8** |
| Ölçülen canlı R doğrudan (canlı stoplar, ort %1.28) | 0.0232 | +0.2109 | **%9.9** |

- **Neden iki ölçülen satır var:** Canlı dönemin stopları ikiz ortalamasından dar
  (%1.28'e karşı %2.14). Bu yüzden aynı bp canlıda daha fazla R ediyor. İki yöntem de
  %40'ın çok altında.
- **Bu hesabın kapsamı:** Yalnız giriş kaymasının yeniden fiyatlanması. Çıkış kayması,
  ücret ve funding ikizdeki gibi kalır.

## VPS 1. koşu (2026-09-27): GEÇERSİZ, betik kusuru

İlk koşunun sonucu: squeeze n=2 (−17.50bp), donchian n=1 (+26.18bp), hüküm D.

**Kusur:** Betik `sl0` kaydı olmayan **19 squeeze ve 74 donchian** işlemini kayma
hesabından da atmıştı. `sl0` 2026-09-20'den önce kaydedilmiyordu
(`execution.py:918-924`). Oysa bp hesabı stop gerektirmez; stop yalnız R için lazım.

**Düzeltme (2. koşudan ÖNCE yapıldı):**
- bp, gerçek (tahmini olmayan) dolumu olan her işlemde hesaplanır.
- R için stop kaynağı sırasıyla:
  1. `sl0`
  2. yoksa `trades.sl_price`, ama yalnız `|niyet − sl_price| = 2.0 × atr` (±%2) ise.
     Bu, stopun hiç taşınmadığını doğrular.
  3. tutmazsa R yok, bp yine sayılır.
- Yedek kural ikizde sınandı: `sl0` gizlenince 782/782 işlemde gerçek `sl0`'ı buldu,
  yanlış stop 0.
- **Ana grup = taker (piyasa) dolumlar.** Bu, canlının bugünkü yolu ve ikizin
  modellediği giriş. Maker dolumlar (reddedilmiş squeeze maker denemesi, eski donchian
  maker dönemi) ayrı satırda gösterilir, hükme girmez.

## Neden

İkiz squeeze'e 15.85bp giriş kayması uyguluyor. Bu sayı donchian'dan ölçülmüştü (n=54).
Squeeze'e uygulanması bir varsayımdı. Defterdeki "SQUEEZE'İN KENDİ KAYMASINI ÖLÇ"
maddesi (`RESEARCH_LEDGER.md:4546`) daha önce hiç yapılmadı. Repoda squeeze'e özel bir
ölçüm de yoktu:

- `kayma_denetim.py` bar kapanışına göre ölçüyor; `intended_entry`, `sl0` ve R hesabı yok.
- `cikis_kayma.py` çıkış kaymasını ölçüyor.

## Tanım

| Alan | Kaynak |
|---|---|
| niyet fiyatı | `strategy_scores.intended_entry`. Squeeze'de sinyal barının 1h kapanışı (`strategies/squeeze.py:238`). |
| gerçek dolum | `trades.entry_price` |
| başlangıç stopu | `strategy_scores.sl0`; yoksa ATR ile doğrulanmış `trades.sl_price` |
| maker/taker | `strategy_scores.entry_fee_rate` (0 = maker) |
| tahmini dolum | `strategy_scores.entry_price_estimated` → ana hesaptan çıkarılır, sayısı yazılır |

- **Kayma:**
  - LONG `(dolum − niyet)/niyet·1e4`
  - SHORT `(niyet − dolum)/niyet·1e4`
  - Artı değer aleyhe demek.
- **Stop ve R:** `stop_pct = |niyet − stop|/niyet`, `kayma_R = kayma/stop_pct`.
- **Ücret:** Kaymaya dahil değil.
- **Kapsam:** Yalnız `is_paper=0`, kollar squeeze + donchian. Diğer kollar (asia_bo 4,
  bb 17, fvg 10, orb 21) sayılıp dışarıda bırakıldı.

## Hüküm kuralı (önceden sabit, eşik optimize edilmedi)

Hüküm ANA grup (taker) üzerinden verilir:

| Koşul | Hüküm |
|---|---|
| squeeze taker n < 20 | D |
| %95 bootstrap GA tamamen < 15.85 | A |
| %95 GA tamamen > 15.85 | C |
| GA 15.85'i içeriyor | B |

- **Alt gruplar:** n<10 betimsel, n<20 zayıf. Alt gruplarda hüküm verilmez.
- **Nominal–kayma ilişkisi:** Spearman ve 5000 permütasyon. n<20 ise INSUFFICIENT.
  n≥20 ve p<0.05 ve rho>0 ise YES.

## Doğrulama (çevrimdışı)

1. **İkiz DB (`--paper`):** İkiz her işleme tam 15.85bp uyguluyor.
   - Betik squeeze n=369 ve donchian n=413'te 15.85bp'yi birebir geri buldu; hüküm B.
   - Bir kusur yakalanıp düzeltildi: GA tam 15.85'e eşitken ondalık hata yüzünden A
     çıkıyordu. Karşılaştırmaya 1e-6 tolerans eklendi.
2. **Sentetik DB:**
   - İşaretler doğru çıktı: long +20bp/0.10R, short +10bp/0.05R, lehe −10bp.
   - Tahmini dolum elendi.
   - Taşınmış stopta R yok, bp sayıldı.
   - Maker ana gruba girmedi.
   - Başka kol ve `is_paper=1` satırları dışarıda kaldı.
3. **Yedek stop kuralı:** İkizde `sl0` gizlenince 782/782 doğru, yanlış 0.

## Yeniden çalıştırma (VPS, salt okur; emir yok, borsa yok, `.env` yok)

```
cd /opt/bot2 && git pull && venv/bin/python arastirma/squeeze_execution_audit/squeeze_execution_audit.py
```

İşlem düzeyi CSV `/tmp/squeeze_execution_audit/squeeze_execution_trades.csv` dosyasına
yazılır; repoya değil.
