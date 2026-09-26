# 2026-09-26 araştırma arşivi

Bu klasör, `DEVIR_RAPORU.md`'deki bulguları üreten betiklerin ve metin çıktılarının
kopyasıdır. Asılları oturumun geçici çalışma alanındaydı; `.pkl`/`.npz`/büyük `.csv`
ara dosyaları arşivlenmedi (yeniden üretilebilir).

⚠ 15 betikte `/tmp/claude-0/...` mutlak yolları sabit yazılı. Yeniden koşmadan önce
yolları repo köküne göre düzeltin. Girdi verisi: repo kökündeki `ikiz_*_islemler.csv`
dosyaları ve `data/{COIN}_fut_1h.csv`.

| klasör | ne | ana dosyalar |
|---|---|---|
| `edge/attr/` | kâr ayrıştırma (kol, yön, çıkış, coin, yıl, maliyet) | `attrib.py`, `attrib_out.txt`, `placebo_attr.py` |
| `edge/` (kök) | plasebo simülatörü ve testleri | `sim.py`, `calib.py`, `placebo.py`, `analyze.py`, `new_report.txt` |
| `edge/` (kök) | kayıp serisi / düşüş null modelleri | `streak_null.py`, `split_year.py`, `episodes.py`, `out_cap25.txt`, `out_split.txt`, `out_episodes.txt` |
| `edge/` (kök) | piyasa / rejim ilişkisi | `market_edge.py`, `extra2.py`, `extra3.py`, `out1-3.txt` |
| `edge/` (kök) | hacim filtresi denetimi | `volfilter_audit.py`, `volfilter_book.py`, `sizing_check.py` |
| `edge/rv_placebo`, `edge/rev*`, `edge/review` | ÇÜRÜTÜCÜ (bağımsız doğrulayıcı) betikleri | her klasör bir doğrulayıcı |
| `kayip/` | kayıp anatomisi, erken_uyari kalibrasyonu | `anatomi.py`, `dd.py`, `testler.py`, `kume.py`, `aynibar.py`, `butce2.py`, `kalibre_canli.py`, `alarm_kalibre.py`, `cusum.py` |
| `ikiz_rr/` | İKİZ koşu sürücüleri (RR düzeltmesi, ablasyon, O/N) | `kos4.py`, `kos_havuz.py`, `kos_son.py`, `degerlendir.py` |
| `canli_olcek.py` | ankor canlı ölçek sabitlerinin yeniden ölçümü | |

Not: `edge/placebo_out.txt` (kök) ile `edge/attr/placebo_attr_out.txt` aynı analizin iki
kopyasıdır; paylaşılan klasörde bir ajan diğerinin `placebo.py`'sinin üzerine yazdı —
kök `placebo.py` plasebo analistinindir.
