# Canlı bot ikizi + trend paketi birleşik tahmin (teşhis, 2026-10-03)

- **Betik:** `birlesik_bot_trend.py` (`PYTHONPATH=. python3 ...`).
- **Girdi:** canlı-birebir ikiz işlemleri (`ikiz_y_taban_islemler.csv`, 936 işlem), trend paketi
  T1 + H4 + ETH200 + piramit.
- **Pencere:** 2023-04-07 → 2025-08-08 (29 ay). FİNAL dönemi kullanılmadı.
- **Yöntem:** işlem kapanışı sırasıyla bileşik, her işlem getirisi = R × risk.
  - Eşzamanlı pozisyonlar ve marjin modellenmedi.
  - Bot-tek sonucu bu yöntemle aylık %14.6 / DD %35. Resmi ikiz ölçümü aylık %10–13 / DD %37–46.
    Yani yöntem ~2–4 puan iyimser.

| bot riski | trend riski | trend evreni | aylık ort. | en kötü ay | maxDD (kapanış) |
|---|---|---|---|---|---|
| %3.5 | — | — | %14.6 | −15.2 | %35.0 |
| %3.5 | %1.0 | diğer 24 coin (dürüst) | %16.8 | −20.7 | %39.4 |
| %3.5 | %1.0 | botun 12 coini (seçim kümesi, iyimser) | %23.0 | −17.7 | %35.3 |
| %3.5 | %2.0 | diğer 24 coin | %18.6 | −30.0 | %46.3 |

Trend tek başına bu 29 ayda zayıf bir dönem geçirdi (2021 boğası pencerede yok): diğer 24 coinde
%0.25 riskle aylık %0.5.
