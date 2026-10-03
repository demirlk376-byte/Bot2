# GELISIM_V8 — önceden kayıt (2026-10-03, sonuçlardan ÖNCE)

## Taban paket (P0)
- günlük T1 (N50_X5_L, E10),
- 4h H4 (N180_X5_L, E10),
- ikisinde de R1 ETH200 anahtarı (yeni long yalnız ETH > SMA200).

## Geliştirmeler
| kod | değişiklik |
|---|---|
| S | Ayıda short. Varyantlar LS. Short girişi YALNIZ ETH ≤ SMA200 iken: kapanış önceki N mumun dibinin altında → short, k×ATR takip stopu, aynı E10. |
| P | Piramit. Kapanış ilk girişten +2R ve +4R lehe gidince, sonraki açılışta güncel stopa göre yine %0.25 riskle ek lot (en fazla 2 ek). Ortak stop, tüm kapılar (notional, marjin, 300 USDT risk tavanı) geçerli. Ekler rejimden bağımsız. |
| SP | S + P |

Parametreler (2R adım, 2 ek, aynı N/k/E) ders kitabı/Turtle tarzı sabit değerler, ayarlanmaz.

## Veri ve dönem
V7 ile aynı: eski 12 ve yeni 24 coin, [2021-01-01, 2025-08-08), FİNAL kapalı, maliyet ve risk aynen.

## Karar kuralı
Geliştirme X "benimsenir", ancak İKİ kümede de şu üçü birden sağlanırsa:
- paket getirisi > P0,
- paket getiri/MDD > P0,
- paket STRESS getirisi > 0.

Birden fazla geliştirme benimsenirse eski kümedeki getiri/MDD oranı en yüksek olan seçilir.
2022 ve yıllık dağılım teşhis olarak raporlanır. Sonuçtan sonra parametre ya da kural değiştirilmez.
