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

    try:
        _karar_dosyasi()
    except Exception as e:
        print(f"\n  (KARAR.txt uretilemedi: {type(e).__name__}: {e})")

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


def _karar_dosyasi():
    """⚠ TEK EKRANLIK KARAR. Tam rapor binlerce satir ve paylasilmasi zor.
    Burada YALNIZCA karar icin gereken satirlar var: guncel kodla kosmus
    konfigurasyonlar, TRAIN/TEST dengeleri ve hukum. Dosyaya da yazilir
    (KARAR.txt) -- kopyalayip gondermek icin."""
    import ikiz_donem_analiz as DA
    import ikiz_risk_ozet as OZ

    # ⚠ Referans = EN SON kosan kosunun motoru (calisan kodun parmak izi
    # DEGIL: koda her dokunusta butun kosular gecersiz sayilirdi).
    mevcut = []
    for ad in DA.SIRA:
        y = os.path.join(KOK, f"ikiz_{ad}.db")
        if os.path.exists(y):
            try:
                mevcut.append((os.path.getmtime(y), ad, y))
            except OSError:
                pass
    if not mevcut:
        guncel = None
    else:
        guncel = OZ.motor_surumu(max(mevcut)[2])

    olcum, temel_ad = {}, None
    for _, ad, y in mevcut:
        if OZ.motor_surumu(y) != guncel:
            continue                      # farkli motor -> karsilastirilamaz
        s = DA.olc(y)
        if s and "_hata" not in s and s.get("test"):
            olcum[ad] = s
            if ad in DA.TEMEL_ADAYLARI and temel_ad is None:
                temel_ad = ad

    satirlar = []
    ekle = satirlar.append
    ekle("=" * 78)
    ekle("  K A R A R   -  yalnizca GUNCEL kodla kosmus konfigurasyonlar")
    ekle(f"  motor: {guncel or '(damgasiz)'}   "
         f"(en son kosan kosunun motoru referans alindi)")
    ekle("=" * 78)
    if not olcum:
        ekle("  Guncel kodla kosmus konfigurasyon YOK.")
        ekle("  Taramayi yeniden calistir (menude 1 veya A).")
    elif temel_ad is None:
        ekle("  TABAN kosusu yok -> karsilastirma yapilamaz.")
        ekle("  Taramayi taban kosusuyla birlikte calistir.")
    else:
        t = olcum[temel_ad]
        ekle(f"  TABAN  TRAIN MAR {t['train']['mar']:5.2f}   "
             f"TEST MAR {t['test']['mar']:5.2f}   "
             f"({t['train']['n'] + t['test']['n']} islem)")
        ekle("-" * 78)
        ekle(f"  {'ayar':<22s}{'TR MAR':>8s}{'TE MAR':>8s}"
             f"{'dTR':>7s}{'dTE':>7s}   hukum")
        ekle("-" * 78)
        sirali = sorted(
            ((a, v) for a, v in olcum.items() if a != temel_ad),
            key=lambda kv: -(kv[1]["test"]["mar"]))
        gecen = []
        for ad, v in sirali:
            dtr = v["train"]["mar"] - t["train"]["mar"]
            dte = v["test"]["mar"] - t["test"]["mar"]
            if dtr > 0 and dte > 0:
                h = "GECTI"
                gecen.append((ad, dtr, dte, v))
            elif dtr > 0 or dte > 0:
                h = "tek yari"
            else:
                h = "kaldi"
            ekle(f"  {DA.ETIKET.get(ad, ad):<22s}{v['train']['mar']:>8.2f}"
                 f"{v['test']['mar']:>8.2f}{dtr:>+7.2f}{dte:>+7.2f}   {h}")
        ekle("-" * 78)
        if gecen:
            ekle("  IKI YARIDA DA temelden iyi olanlar:")
            for ad, dtr, dte, v in sorted(gecen, key=lambda x: -x[3]["test"]["mar"]):
                ekle(f"    {DA.ETIKET.get(ad, ad):<22s}"
                     f"TEST maxDD %{v['test']['maxdd']*100:.1f}  "
                     f"TEST yillik %{v['test']['yillik']*100:.0f}")
        else:
            ekle("  Hicbiri iki yarida da gecemedi.")
    ekle("=" * 78)

    metin = "\n".join(satirlar)
    print("\n" + metin)
    yol = os.path.join(KOK, "KARAR.txt")
    with open(yol, "w", encoding="utf-8") as f:
        f.write(metin + "\n")
    print(f"\n  -> {yol}  (bu dosyayi kopyalayip gonderebilirsin)")


if __name__ == "__main__":
    main()
