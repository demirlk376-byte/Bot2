# Uyum raporu (fidelity_report)

Genel: GEÇTİ

| kapı | sonuç | ayrıntı |
|---|---|---|
| G1_pytest | ✓ | {"summary": "445 passed in 17.18s"} |
| G6_bias | ✓ | {"trades": 1701, "mean_R": 0.05072632789148843, "z": 1.4706618724379175, "note": "sentetik rastgele yürüyüş, sıfır maliyet; işlemler varyantlar arası bağımsız DEĞİL (ortak olaylar) → z kaba bir yanlılık alarmıdır"} |
| G2_paper_reconciliation | ✓ | {"trades": 400, "max_abs_diff": 5.766409572061093e-11, "tol": 1e-06, "variant": "L1_K1_F0"} |
| G4_smoke_30d | ✓ | {"errors": [], "window": ["2023-02-12 00:00:00+00:00", "2023-03-14 00:00:00+00:00"]} |
| G5_determinism | ✓ | {} |
| G3_reference_isolation | ✓ | {"trades": 25, "window": "2023-04-06→2023-05-20", "note": "aynı süreçte araştırma paketi yüklü/yüklü değil"} |
| source_hashes | ✗ | {"accounting.py": "9ada6082e64d0033d09048bd822a8a2a3cdb94a3e563fd81724ce8e571d5197f", "cli.py": "570b73d79a5861bf38099b6e20122125e13e6e41a0d6c879f733a5afa01696e2", "config.py": "d254ad0ee66ae0db67279b6fd182c700cb1af17bfb4d445ac276368461bc8157", "data_contract.py": "28d72919eee12142c0e456a42e39a1b007f2bc62af33d410d47e66cfc1a11b6c", "events.py": "2bfd0af801ccd1990d3a132fc78963542c3c413664a6ae5af3e8f |

## Model sınırları

| varsayım | durum |
|---|---|
| emir defteri / kuyruk | yok; tam dolum varsayımı |
| veri gecikmesi / ağ | yok; ilk 5m açılışında idealize yürütme |
| mark / tetik fiyatı | tarihsel mark yok; stop/hedef trade OHLCV ile; birebir mark tetikleme İDDİA EDİLMEZ |
| likidasyon | modellenmez (risk/marjin kapıları likidasyon mesafesinin çok altında) |
| venue | fiyat Binance USDⓈ-M (MEXC vekili); tick/kontrat MEXC güncel metadata |
| funding | Binance gerçek settlement zamanları (vekil); mark = son 5m kapanışı |
