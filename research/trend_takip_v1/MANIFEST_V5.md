# YENI_COIN_V5 — önceden kayıt (2026-10-02, yeni coin verisi inerken, sonuçlardan ÖNCE)

## Neden
Doğrulama dönemi birkaç denemede kullanıldı; artık tarafsız değil. Yeni bir filtre daha aramak yerine
paketi DONDURUP hiç görülmemiş coinlerde sınıyoruz. Bu bağımsız bir örneklem: bu 26 coinin hiçbir
verisine bu araştırmada bakılmadı.

## Donmuş paket (kod commit 79fbe83 ile aynı; hiçbir parametre değişmez)
- **T1:** N50_X5_L + E10 erken çıkış.
- **NWK1D_G1:** NW+KAMA event_A 1D + funding kalabalığı filtresi, X3 takip stopu, LS.
- **Kıyas:** taban N50_X5_L ve NWK1D_F0.
- **PAKET:** T1 + NWK1D_G1, aynı 10.000 USDT hesapta, iki ayrı defter; özsermaye değişimleri toplanır.

## Veri ve dönem
- **Coinler:** LINK AVAX DOT UNI ATOM FIL ETC AAVE ALGO XTZ SAND MANA AXS EGLD RUNE EOS THETA GRT CRV HBAR
  VET APT ARB OP INJ SUI (Binance USDⓈ-M 1d ve funding).
  - MEXC güncel metadatası olmayan coin dışlanır ve raporlanır.
- **Dönem:** [2021-01-01, B2 = 2025-08-08). Yani eski KEŞİF + DOĞRULAMA aralığı, tek parça.
  FİNAL hâlâ açılmaz.
- **Kurallar:** maliyet, risk (%0.25, 300 USDT toplam risk tavanı), canlı kapılar ve 200 gün ısınma aynen.

## Başarı ölçütü (sabit)
- **T1 ve NWK1D_G1, ayrı ayrı "yeni coinlerde tuttu" sayılır**, ancak:
  - NORMAL ve STRESS toplam net > 0,
  - ortalama net R > 0,
  - haftalık 4 haftalık blok bootstrap LCB > 0 (`metrics` aynen).
- **G1 filtresi**, yeni coinlerde ortalama R > F0 ve toplam ≥ 0.75 × F0 ise tutarlı sayılır.
- **PAKET:** % getiri ve MDD raporlanır.

Sonuç görüldükten sonra coin listesi, dönem, parametre ya da ölçüt değiştirilmez.
