"""
ikiz_rapor.py — TEK KOMUT, TUM RAPORLAR.

Eskiden uc ayri betik ayri ayri calistiriliyordu (ozet, filtre gecerliligi,
donem bolmesi) ve hangisinin ne yaptigini hatirlamak gerekiyordu. Uc rapor
birbirini tamamliyor, ayri calistirilmalarinin hicbir faydasi yok:

  1. OZET          hangi konfigurasyon ne kazandirdi, ne kadar dustu (MAR)
  2. GECERLILIK    bir filtre GERCEKTEN kotu islemleri mi eliyor, yoksa sans mi
  3. DONEM         etki TRAIN ve TEST yarilarinin IKISINDE de duruyor mu

Karar HER UCUNE birden bakilarak verilir: ozette en iyi gorunen sey donem
bolmesinde cokebilir (2026-09-20: "tampon 0.5" ozette MAR 5.90 ile birinciydi,
TRAIN 19.21 / TEST 2.16 cikti -- ders kitabi uydurma).
"""
import os
import sys
import traceback

KOK = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KOK)

BOLUMLER = [
    ("ikiz_risk_ozet",     "1/3  OZET - kar / drawdown dengesi"),
    ("ikiz_filtre_analiz", "2/3  GECERLILIK - filtre kotu islemleri mi eliyor"),
    ("ikiz_donem_analiz",  "3/3  DONEM - etki iki yarida da duruyor mu"),
]


def main():
    # ⚠ Alt raporlar sys.argv'e bakiyor; kendi argumanlarimizi onlara
    # sizdirmayalim.
    eski_argv = sys.argv[:]
    sys.argv = [sys.argv[0]]
    try:
        for modul_adi, baslik in BOLUMLER:
            print(f"\n\n{'#' * 100}")
            print(f"#  {baslik}")
            print(f"{'#' * 100}", flush=True)
            try:
                modul = __import__(modul_adi)
                modul.main()
            except Exception:
                # ⚠ BIR RAPOR DUSERSE DIGERLERI YINE CALISSIN. Eskiden uc betik
                # ayri calistiginda biri patlayinca kullanici digerlerini de
                # kaybediyordu.
                print(f"\n  !! {modul_adi} calistirilamadi:")
                traceback.print_exc()
    finally:
        sys.argv = eski_argv

    print(f"\n\n{'=' * 100}")
    print("  NASIL OKUNUR")
    print(f"{'=' * 100}")
    print("  * TABAN satiri her taramada var ve DEGISIKLIK ICERMEZ. Motorun")
    print("    dogru calistiginin kanitidir; beklenen degerleri vermezse")
    print("    tablonun geri kalanina GUVENME.")
    print("  * MAR = yillik getiri / en derin dusus. Ana karsilastirma sutunu;")
    print("    bakiye tek basina yaniltir (risk buyudukce hep buyur).")
    print("  * Bir fikir ancak DONEM bolmesinde IKI yarida da temelden iyiyse")
    print("    canliya alinir. Tek yarida parlayan sey gecmise uydurulmustur.")
    print(f"{'=' * 100}\n")


if __name__ == "__main__":
    main()
