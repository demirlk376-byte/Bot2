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
            s["maliyet"] = OZ.maliyet_ayari(y)
            olcum[ad] = s
            if ad in DA.TEMEL_ADAYLARI and temel_ad is None:
                temel_ad = ad

    satirlar = []
    ekle = satirlar.append
    ekle("=" * 92)
    ekle("  K A R A R   -  yalnizca GUNCEL kodla kosmus konfigurasyonlar")
    ekle(f"  motor: {guncel or '(damgasiz)'}   (en son kosan kosunun motoru)")
    ekle("=" * 92)

    if not olcum:
        ekle("  Guncel kodla kosmus konfigurasyon YOK. Taramayi calistir.")
    else:
        # ⚠ HER MALIYET GRUBU KENDI ICINDE. Ucuncu kez isirdi: arac maliyetli
        # kosulari MALIYETSIZ tabana gore kiyasliyor, hepsi "kaldi" cikiyordu.
        # Oysa ayni maliyet altinda ALTI ayar iki yarida da kazaniyordu.
        # Artik her grubun KENDI tabani var: o gruptaki EN COK ISLEM yapan
        # kosu (= en az filtreleyen), yani "hicbir sey degistirmemis" hali.
        gruplar = {}
        for _ad, _v in olcum.items():
            gruplar.setdefault(_v.get("maliyet", ""), []).append((_ad, _v))

        tum_gecen = []
        for gi, (mal, uyeler) in enumerate(
                sorted(gruplar.items(), key=lambda kv: -len(kv[1])), 1):
            if len(uyeler) < 2:
                continue
            taban_ad, tv = max(uyeler,
                               key=lambda kv: kv[1]["train"]["n"] + kv[1]["test"]["n"])
            etiket = mal if mal else "(maliyetsiz / damgasiz)"
            ekle("")
            ekle(f"  GRUP {gi}: {etiket[:84]}")
            ekle(f"  taban = {DA.ETIKET.get(taban_ad, taban_ad)}  "
                 f"({tv['train']['n']+tv['test']['n']} islem · "
                 f"TR MAR {tv['train']['mar']:.2f} · TE MAR {tv['test']['mar']:.2f} · "
                 f"TE yillik %{tv['test']['yillik']*100:.1f} · "
                 f"TE maxDD %{tv['test']['maxdd']*100:.1f})")
            ekle("  " + "-" * 88)
            ekle(f"  {'ayar':<22s}{'islem':>6s}{'TE yil%':>9s}{'TE DD%':>7s}"
                 f"{'aylik%':>8s}{'TR MAR':>8s}{'TE MAR':>8s}{'dTR':>7s}{'dTE':>7s}  hukum")
            ekle("  " + "-" * 88)
            for ad, v in sorted(uyeler, key=lambda kv: -kv[1]["test"]["mar"]):
                dtr = v["train"]["mar"] - tv["train"]["mar"]
                dte = v["test"]["mar"] - tv["test"]["mar"]
                if ad == taban_ad:
                    h = "<- TABAN"
                elif dtr > 0 and dte > 0:
                    h = "GECTI"
                    tum_gecen.append((ad, v, dtr, dte))
                elif dtr > 0 or dte > 0:
                    h = "tek yari"
                else:
                    h = "kaldi"
                _ay = (1 + v["test"]["yillik"]) ** (1 / 12) - 1
                ekle(f"  {DA.ETIKET.get(ad, ad):<22s}"
                     f"{v['train']['n']+v['test']['n']:>6d}"
                     f"{v['test']['yillik']*100:>9.1f}{v['test']['maxdd']*100:>7.1f}"
                     f"{_ay*100:>8.2f}{v['train']['mar']:>8.2f}{v['test']['mar']:>8.2f}"
                     f"{dtr:>+7.2f}{dte:>+7.2f}  {h}")

        ekle("")
        ekle("=" * 92)
        if tum_gecen:
            ekle("  KENDI GRUBUNDA IKI YARIDA DA GECENLER (en iyi TEST MAR once):")
            for ad, v, dtr, dte in sorted(tum_gecen, key=lambda x: -x[1]["test"]["mar"]):
                _ay = (1 + v["test"]["yillik"]) ** (1 / 12) - 1
                ekle(f"    {DA.ETIKET.get(ad, ad):<22s} aylik %{_ay*100:5.2f}   "
                     f"TE MAR {v['test']['mar']:.2f}   "
                     f"maxDD %{v['test']['maxdd']*100:.1f}   "
                     f"dTR {dtr:+.2f} / dTE {dte:+.2f}")
        else:
            ekle("  Hicbir grupta iki yarida da gecen ayar yok.")
        ekle("  Not: TRAIN 2023-04..2024-12 | TEST 2025-01..2026-07")
        ekle("  Karar kurali: kendi maliyet grubunun tabanina gore IKI yarida da iyi.")
    ekle("=" * 92)

    metin = "\n".join(satirlar)
    print("\n" + metin)
    yol = os.path.join(KOK, "KARAR.txt")
    with open(yol, "w", encoding="utf-8") as f:
        f.write(metin + "\n")
    print(f"\n  -> {yol}  (bu dosyayi kopyalayip gonderebilirsin)")


if __name__ == "__main__":
    main()
