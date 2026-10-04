# SWEEP_V2 — sonuç (ön-kayıt ONKAYIT.md, commit dcee5ba + hacim tanım düzeltmesi sonuçtan önce)

- **Koşu:** `sonuclar/20261004T014533Z_78d9427b/`.
- **Taban:** V1 L3_K2_F0, birebir yeniden üretildi (keşif 3.269 işlem, −0.302R).
- **Kurallar:** NORMAL maliyet, %0.25 risk, FİNAL kapalı.

| varyant | keşif işlem | keşif ort. R | doğrulama işlem | doğrulama ort. R | doğr. alt sınır (Bonferroni) |
|---|---|---|---|---|---|
| TABAN | 3269 | −0.302 | 2276 | −0.313 | −0.383 |
| MTF (4h EMA200 + 1D EMA50 yön onayı) | 2446 | −0.299 | 1236 | −0.274 | −0.352 |
| SEANS (UTC 07–21) | 2657 | −0.325 | 1551 | −0.258 | −0.366 |
| HACIM (≥1.5× medyan) | 3135 | −0.267 | 1940 | −0.286 | −0.368 |
| RETEST | 3212 | −0.314 | 1827 | −0.324 | −0.392 |
| ORDERBOOK (±%1 dengesizlik yönde) | 2472 | −0.339 | 1391 | −0.279 | −0.378 |
| OI (son 1 saatte OI düşüşü) | 2566 | −0.303 | 1425 | −0.246 | −0.332 |
| KALABALIK (kalabalığa karşı yön) | 3077 | −0.271 | 1323 | −0.283 | −0.378 |
| HEPSİ birlikte | 223 | −0.340 | 61 | −0.292 | −0.730 |

**HÜKÜM: dokuz varyantın dokuzu ELENDİ.**
- En iyi tek filtre bile tabanı en fazla ~0.07R iyileştiriyor (OI, doğrulama). Her biri −0.25R'nin altında.
- Hepsi birlikte uygulanınca işlem sayısı 61'e düşüyor ve sonuç yine negatif.

Likidite avı, bu filtrelerle de maliyetleri karşılayan bir kenar vermiyor. V1'in maliyetsiz kenar ≈ 0
teşhisi tutarlı.
