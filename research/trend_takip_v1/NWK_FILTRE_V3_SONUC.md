# NWK_FILTRE_V3 — sonuç (ön-kayıt MANIFEST_V3.md, commit 8874edd)

Koşu: `sonuclar_v3/20261002T215110Z_8874edd9_e2ded364/`. %0.25 risk, NORMAL maliyet. FİNAL açılmadı.

| varyant | keşif (3.45 y) | MDD | doğrulama (1.15 y) | MDD |
|---|---|---|---|---|
| 1D F0 (filtresiz) | +3.5% | 2.9% | **+4.0%** | 1.7% |
| 1D F1 (SMA200) | +6.0% | 2.7% | −0.5% | 1.4% |
| 1D F2 (ETH rejimi) | +4.3% | 3.8% | −1.0% | 1.6% |
| 1D F3 (ADX>20) | **+6.3%** | 2.6% | +1.8% | 1.7% |
| 2D F0 | −0.1% | 4.8% | +4.7% | 2.6% |
| 2D F1 | +3.1% | 2.6% | −0.4% | 0.9% |
| 2D F2 | +3.5% | 2.2% | −1.2% | 1.4% |
| 2D F3 | −3.5% | 4.3% | +0.1% | 1.1% |

**Hüküm:** Hiçbir filtre ve 2D, ön-kayıtlı kuralı geçmedi.
- Filtreler keşifte iyileştiriyor ama doğrulamada bozuyor. Bu, klasik aşırı uyum işareti.
- 2D, 1D'den iyi değil.
- İstatistik: doğrulamada örneklem tabanı altında kaldı → KANIT YETERSİZ.

**Teşhis (karar dışı), birleşik hesap T1 + NWK1D:**

| birleşim | keşif | MDD | doğrulama | MDD |
|---|---|---|---|---|
| T1 + F0 | +14.4% | 4.6% | +11.4% | 5.5% |
| T1 + F3 | +17.2% | 4.0% | +9.2% | 5.4% |

F3 burada iki dönem toplamıyla seçildi, yani hafif seçim yanlılığı var.
Önerilen paket filtresiz: **T1 + NWK1D_F0**.
