# Paylaşım paketi — 2026-09-26

**Canlı veri bu pakette YOK.** Hazırlayan oturumun VPS'e ve canlı `trades.db`'ye erişimi
yoktu. Canlı işlemleri aşağıdaki komutla salt okunur biçimde üretip `canli/` adıyla bu
klasöre ekleyin.

## İçerik

| yol | ne | kaynak |
|---|---|---|
| `DEVIR_RAPORU.md` | devir raporu | repo kökü |
| `ikiz/ikiz_k25_cap25_islemler.csv` | canlı ile birebir ikizin 936 işlemi | repo kökü (sha256 aynı) |
| `kar_geri_verme/` | `KAR_GERI_VERME_ANALIZI.md`, `islem_mfe_mae.csv`, `equity_saatlik.csv`, `giris_boyutlama.csv`, `sonuclar.json`, `kar_geri_verme.py` | `arastirma/kar_geri_verme/` kopyası, yeniden üretilmedi |
| `canli_disa_aktar.py` | canlı `trades.db` salt okunur dışa aktarımı | bu paket |

Pakette `.env`, API anahtarı, token veya ham veritabanı yok.

`kar_geri_verme.py`'nin buradaki kopyası okumak içindir. Betik repo köküne göre yol
arıyor; yeniden çalıştırmak için asıl konumundan çalıştırın:

```
python3 arastirma/kar_geri_verme/kar_geri_verme.py
```

## Canlı dışa aktarım (VPS'te)

```
cd /opt/bot2 && git pull && python3 arastirma/paylasim_paketi_2026-09-26/canli_disa_aktar.py --db /opt/bot2/trades.db --cikti /tmp/canli_disa_aktarim
```

- Yalnız standart kütüphane kullanır.
- Bot modüllerini (`main`, `exchange`, `config`) içe aktarmaz, borsaya bağlanmaz, emir
  gönderemez, `.env` okumaz.
- Veritabanı `mode=ro` ile açılır. İkiz veritabanının bir kopyasında denendi: çalışma
  öncesi ve sonrası sha256 aynı.
- `git pull` çalışan bot sürecini etkilemez; yeniden başlatma gerekmez.

**Çıktılar:**
- `islemler_kapali.csv` ve `islemler_acik.csv`: `is_paper=0`, ilk canlı işlemden bugüne,
  **tüm stratejiler**, kapatılan kollar dahil.
- `bakiye_gunluk.csv`
- `meta.csv`
- Varsa `diger_<tablo>.csv`
- `manifest.json`: şema, satır sayıları, sha256 değerleri, repo commit'i.

## Alanlar ve eksik kayıtlar

Doğrulanmış şema (`database.py`):
- `trades`: id, symbol, side, entry_price, exit_price, quantity, sl_price, tp_price,
  entry_time, exit_time, pnl_usdt, pnl_pct, exit_reason, strategy_scores, fees_usdt, is_paper
- `daily_stats`
- `meta`

| istenen | durum |
|---|---|
| işlem kimliği, sembol, yön, UTC zamanları, miktar, çıkış nedeni | var |
| strateji | `strategy_scores` JSON'unda (`ss_strategy`, `ss_slot`) |
| gerçek dolum fiyatları | `entry_price` / `exit_price`, bot defterine yazılan fiyatlar. Borsa dolumuyla farkı geçmişte görüldü (aşağıda) |
| ilk stop | `ss_sl0`, yalnız bu alanı yazan sürümlerden sonra. Yoksa boş bırakıldı. `sl_price` **son** stoptur, stop taşındıysa ilk değildir |
| ilk hedef | `tp_price`. Kodda güncelleyen bir yol yok |
| net PnL | `pnl_usdt` (defter) |
| brüt PnL | tabloda yok. `turetilmis_fiyat_pnl_usdt` = yön × (çıkış − giriş) × miktar, kayıttaki fiyatlardan türetildi |
| komisyon | `fees_usdt`. Kapanış kodunda varsayılan değeri 0.0; **0 değeri "bilinmiyor" anlamına da gelebilir**. Sütun eski tabloda yoksa çıktıda da olmaz. Giriş ücret oranı `ss_entry_fee_rate`'te (varsa) |
| funding | **kayıt yok** |
| sürüm/ayar | işlem başına kayıtlı değil. Yalnız `strategy_scores` içindeki alanlar (`ss_max_hold`, `ss_intended_entry` gibi) ve `manifest.json`'daki **bugünkü** repo commit'i var. Geçmiş ayarlar bugünkü ayardan türetilmedi; dönem ayarları için `DURUM.md` ve `RESEARCH_LEDGER.md`'deki tarihli kararlar kullanılmalı (doğrulanmamış dönemler belirsiz sayılmalı) |
| para yatırma/çekme | **tarihli kayıt yok.** `meta`'da yalnız birikimli toplamlar var (`total_deposits`, `inception_balance`, `sermaye_taban*`) |
| bakiye/equity | `daily_stats`: gün başında yazılan başlangıç bakiyesi. Gün içi güncellenmez |
| emir gerçekleşme (fill) kayıtları | **veritabanında yok**, borsada. `kar_farki.py` / `gercek_pnl.py` bunları borsadan okuyabilir ama API anahtarı kullanır; bu paket için çalıştırılmadı |
| $62.80 defter–borsa farkı | çözülmedi. Kısmen izlendi: ücret $22.80, funding $1.61, çıkış fiyatları (DURUM ~L1291-1320). Borsa fill kayıtları olmadan kapatılamaz |

Bilinmeyen alanlar boş bırakıldı; hiçbir alan sıfırla doldurulmadı.
