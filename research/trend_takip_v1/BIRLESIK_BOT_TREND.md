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

## Düzeltme: giriş anı bakiyesiyle bileşik (`birlesik_aylik_giris_bazli.py`)

Yukarıdaki "kapanış sırasıyla bileşik" yöntemi, aynı anda açık işlemler birlikte kapandığında kârı
şişiriyordu: bir işlemin kârı, kendisinden sonra açılmamış ama ondan önce kapanmış işlemlerin
kârıyla büyümüş bakiyeye uygulanıyordu. Doğru yöntem: risk tutarı işlemin AÇILDIĞI andaki
gerçekleşmiş bakiyeden hesaplanır.

**Kalibrasyon:** bot tek başına bu yöntemle aylık %12.5, maxDD %45.1. Resmi ikiz ölçümü aylık
%10–13, DD %37–46. Yöntem resmi ölçümle uyumlu.

| | aylık geo | maxDD | 2023 (Nis–Ara) | 2024 | 2025 | 2026 (Oca–18 Tem) |
|---|---|---|---|---|---|---|
| bot %3.5 | %12.5 | %45.1 | +604% | +163% | +354% | +33% |
| bot %3.5 + trend %1 (botun 12 coini) | %16.0 | %45.1 | +674% | +641% | +404% | +33% |

Trend kısmı seçim kümesinde (iyimser). 2026'daki trend ayları eski 12 coinin FİNAL dönemine düşüyor
(bkz. FINAL_IHLAL_NOTU.md). İkiz verisi 2026-07-18'de bitiyor.

## ⚠ Netted kısıtı: önceki birleşik tahmin iyimserdi (2026-10-03)

RESEARCH_LEDGER (2026-09-14) ölçmüştü: MEXC'te bir sembol = bir net pozisyon (execution.py). Trend
kolu botun coinlerini haftalarca tutarsa botun o coindeki işlemleri engellenir. Ledger ölçümüne göre
botun işlemlerinin %12.5'i, getirisinin %19.6'sı. Yukarıdaki "botun 12 coini" satırları bunu
modellemiyor; gerçekte o kurulum net NEGATİF olabilir.

**Çakışmasız kurulum:** trend yalnız botun İŞLEM YAPMADIĞI 24 coinde. Coin başına tek pozisyon
(1D ve 4H modülleri arasında ilk açılan kazanır). Giriş-anı bileşik, 2023-04 → 2025-08-08,
FİNAL dışı (`birlesik_ayri_coin.py`):

| | aylık geo | maxDD | en kötü ay |
|---|---|---|---|
| bot %3.5 | %13.5 | %35.2 | −16.4 |
| + trend %1.0 (24 ayrı coin) | %14.5 | %40.2 | −21.4 |
| + trend %1.5 | %14.6 | %43.9 | −25.2 |
| + trend %2.0 | %14.6 | %47.5 | −30.8 |

**Sonuç:**
- Bu pencerede trend eklemek, riski artırmaya denk. Getiri/MDD oranı 0.38'den 0.36'ya iniyor.
- Pencerede 2021 tipi güçlü altcoin boğası yok; trendin asıl değeri orada olurdu. Ama botun ikizi
  2023-04'ten önceye gitmediği için o dönem birlikte ölçülemiyor.

## "Kısıtı kaldır": ayrı alt hesap senaryosu (2026-10-03)

Netted kısıtı borsa kuralı; kodla kapatılamaz. Tam kaldırmanın yolu, trendi ayrı bir MEXC alt
hesabında çalıştırmak. Ama o zaman sermaye bölünür ve trend kendi hesabının bakiyesine göre risk alır.
- **Pencere:** 2023-04 → 2025-08-08.
- **Trend:** 36 coin, coin başına tek pozisyon.
- **Betikler:** `birlesik_kisitsiz.py` (tek bakiye varsayımı, ulaşılamaz üst sınır) ve
  `birlesik_iki_hesap.py` (gerçekçi iki hesap).

| kurulum | aylık geo | maxDD |
|---|---|---|
| bot tek, %100 sermaye | %13.5 | %35.2 |
| tek bakiye + trend 36 coin %1 (üst sınır; aynı hesapta netted yüzünden ULAŞILAMAZ) | %17.6 | %40.5 |
| alt hesap %20 (hesap içi risk %5), dengelemesiz | %12.8 | %33.9 |
| alt hesap %30 (hesap içi risk %3.3), dengelemesiz | %12.5 | %32.9 |
| alt hesap %20, AYLIK dengeleme (elle transfer) | %15.2 | — |
| alt hesap %30, AYLIK dengeleme | %14.2 | — |

- Trend alt hesabının kendi düşüşü %69–85 (hesap içi risk %3.3–5).
- Dengelemesiz kurulum, bot tek başına kalmaktan KÖTÜ.

Aynı hesapta, botun kullanmadığı 24 coinde ayrı süreç (çakışmasız) en verimli kurulum:
aylık %13.5 → %14.5, maxDD +5 puan. Modellenmeyen ek maliyet: trend pozisyonlarının teminatı
botun teminat ön-kontrolünü (%95 serbest teminat) daraltıp bazı bot girişlerini engelleyebilir.
