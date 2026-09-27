# Prospective OOS — dondurulmuş iki koşulun ileriye dönük gözlemi

**Yalnız gözlem.** Sinyal, execution, risk ve boyutlama davranışına dokunmaz; işlem
engellemez; production kodu ve `.env` değiştirilmedi. Henüz hiçbir ileri koşu yapılmadı;
defter boş.

## Dondurulmuş tanımlar (2026-09-27; formül, eşik ve hesaplama DEĞİŞTİRİLMEYECEK)

1. `ath_near_2pct` = `port_dd_ath <= 0.02`
2. `breadth_7of7` = `gen_islem_yonunde == 1.0`

Kesin formüller: `arastirma/post_peak_diagnostic/POST_PEAK_DIAGNOSTIC.md` §7 ve
`prospective_oos.py` içindeki `port_dd_ath_hesapla`, `gen_islem_yonunde_hesapla`.

Öz-test, bu fonksiyonların geçmiş 936 işlemde dondurulmuş `entry_state.csv`'yi ürettiğini
sınar (936/936 eşleşme, fark ≤ 5e-7 yuvarlama, iki eşik sınıfı birebir):

```
python3 arastirma/prospective_oos/prospective_oos.py --dogrula      # → PASS
```

## Cutoff mantığı

- `PROSPECTIVE_OOS_START = 2026-09-27` (UTC 00:00), `prospective_oos.py` içinde sabit.
- Deftere yalnız `entry_time >= 2026-09-27` olan işlemler girer. Öncekiler asla girmez;
  yazmadan önce `assert` ile de denetlenir.
- 2026-07-19 (dondurulmuş verinin sonu) ile 2026-09-27 arasındaki işlemler de **girmez**.
- Özellikler yine de geçmişe dayanır, ama yalnız giriş anında bilinen kısmına:
  - T anında bilinen son 1h kapanış (ts ≤ T−1h)
  - T'den önce kapanmış işlemler
  - T'de açık olan pozisyonlar
  - T'den önceki saatlik hesap değeri (ATH için)
- Giriş özellikleri, işlem deftere **ilk girdiğinde** yazılır ve bir daha değiştirilmez
  (`ilk_kayit_utc`).
- `R_net` (= pnl_usdt / (miktar × |intended_entry − sl0|)) ancak **ekonomik çıkış**,
  eldeki verinin sonundan önce gerçekleştiyse eklenir (`sonuc_kayit_utc`). Açık işlemin
  satırı boş kalır.

## Dosyalar

| dosya | ne |
|---|---|
| `prospective_oos.py` | `--dogrula` öz-test · `--islemler <csv> --veri <dizin>` defteri günceller · `--rapor` |
| `ikiz_ileri.py` | canlı-birebir ikizi 2026-07-19 sonrası veriyle devam ettirir (**henüz çalıştırılmadı**) |
| `prospective_oos_ledger.csv` | defter (şu an yalnız başlık satırı) |

Defter sütunları: symbol, strategy, side, entry_time, exit_time, ekonomik_cikis, R_net,
port_dd_ath, ath_near_2pct, gen_islem_yonunde, breadth_7of7, iki_kosul_birlikte,
ilk_kayit_utc, sonuc_kayit_utc, kaynak_sha256.

## Akış (ileride; bu tur çalıştırılmadı)

1. **Veri.** MEXC'e erişen makinede 2026-07-19 sonrası 1h futures barlarını çek.
   - Yeni bir dizine yaz: dondurulmuş `data/{COIN}_fut_1h.csv` satırlarının aynen
     kopyası + yeni barlar.
   - `data/` klasörüne yazılmaz.
   - `fast_bt.load(source="mexc_futures")` yerel önbelleği ezebilir; kullanılmamalı.
2. **İkizi ileri koş.**
   - Komut: `python3 arastirma/prospective_oos/ikiz_ileri.py --veri <dizin> --db <yeni.db> --cikti <islemler.csv>`
   - Veri sürekliliği bozuksa çalışmaz.
   - Koşu sonunda dondurulmuş 936 işlemin birebir yeniden üretildiğini denetler ve
     `<cikti>.sureklilik.json` yazar.
3. **Defteri güncelle.**
   - Komut: `python3 arastirma/prospective_oos/prospective_oos.py --islemler <islemler.csv> --veri <dizin>`
   - Süreklilik dosyası PASS değilse reddeder.
4. **Rapor:** `python3 arastirma/prospective_oos/prospective_oos.py --rapor`

Canlı hesap işlemleri bu deftere **karıştırılmaz**. `port_dd_ath` formülü ikiz defterinin
$10,000 başlangıçlı hesap değerine göre dondurulmuştur; canlı hesabın para yatırmalı
equity'sine aynen uygulanamaz.

## Karar kuralı (önceden kayıtlı)

- Karşılaştırma yalnız TRUE vs FALSE, her koşul için ayrı ve birlikte. Hafta-kümeli
  bootstrap %95 aralık.
- **Asgari örneklem:** Her karşılaştırılan grupta en az 30 **kapanmış** işlem VE cutoff
  sonrası en az 26 farklı hafta. Altında rapor **YETERSİZ VERİ** der ve fark yazmaz.
- Eşikler, formüller ve alternatif tanımlar yeniden optimize edilmez.
