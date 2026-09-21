"""
ikiz_risk_ozet.py — risk taramasi kosularinin SONUCUNU veritabanindan okur.

NEDEN AYRI BIR ARAC: paralel kosu 51 dakikada simulasyonu bitirdi ama koşu
sonundaki WAL aktariminda dondu (dort surec de ayni anda, sifir CPU). Islemler
kaybolmadi — .db-wal dosyasinda duruyorlar. Bu arac surecleri beklemeden o
veriyi okur, WAL'i ana dosyaya birlestirir ve karsilastirma tablosunu basar.

ARADIGIMIZ SEY: daha fazla kar DEGIL. Riski artirinca hem kar hem drawdown
artar, bu zaten biliniyor. Soru kar/drawdown dengesinin NEREDE en iyi oldugu.

Kullanim:
  py ikiz_risk_ozet.py              → klasordeki tum ikiz_risk*.db
  py ikiz_risk_ozet.py yol.db ...   → belirtilen veritabanlari
"""
import os, sys, glob, json, sqlite3
import pandas as pd, numpy as np

KOK = os.path.dirname(os.path.abspath(__file__))
BAL0 = 10_000.0
ETIKET = {"taban": "TABAN canli",
          "m": "OLCULEN maliyet",
          "m_mk": "olculen + maker",
          "f_m": "filtre + olculen",
          "f_m_mk": "filtre + olculen + maker",
          "f_m_dus": "filtre kayma 8.3",
          "f_m_yuk": "filtre kayma 23.4",
          "f_m_mk50": "filtre+maker %50 dolum",
          "f_dusuk": "filtre+kayma 8.3", "f_yuksek": "filtre+kayma 23.4",
          "mg": "gercek giris",
          "mc": "gercek cikis",
          "mgc": "giris+cikis",
          "mgcf": "GERCEK maliyet",
          "mgcf_mk": "gercek + maker",
          "f_taban": "filtre (eski model)",
          "f_mgcf": "filtre + GERCEK",
          "f_mgcf_mk": "filtre + gercek + maker",
          "f": "FILTRE %2.8",
          "f24": "FILTRE %2.4",
          "f20": "FILTRE %2.0",
          "f17": "FILTRE %1.7",
          "f14": "FILTRE %1.4",
          "r24": "filtresiz %2.4",
          "r20": "filtresiz %2.0",
          "r17": "filtresiz %1.7",
          "t1": "teyit1",
          "h20": "hacim2.0",
          "h15": "hacim1.5",
          "t1h20": "teyit1+h2.0",
          "t1h15": "teyit1+h1.5",
          "t1obv": "teyit1+OBV",
          "t1h20k": "teyit1+h2.0+korel",
          "t1h20r20": "teyit1+h2.0+%2.0risk",
          "adx20": "ADX>=20", "adx25": "ADX>=25",
          "teyit1": "teyit 1 bar",
          "teyit2": "teyit 2 bar",
          "retest2": "retest 2b",
          "retest4": "retest 4b",
          "hacim15": "hacim 1.5x",
          "hacim20": "hacim 2.0x",
          "obv": "OBV teyit",
          "hacim_obv": "hacim+OBV",
          "be_don": "BE donchian",
          "be_all": "BE don+sq",
          "be15": "BE 1.5R",
          "tr30": "takip 3xATR",
          "tr20": "takip 2xATR",
          "tr15": "takip 1.5xATR",
          "tr20g": "takip 2x @1R",
          "be_tr": "BE + takip 2x", "risk10": "%1.0", "risk14": "%1.4", "risk17": "%1.7",
          "risk20": "%2.0", "risk28": "%2.8 CANLI", "risk35": "%3.5",
          "risk40": "%4.0", "adx32": "ADX 32", "korel1": "korel 1",
          "hold24": "tutus 24", "guven": "guven boyut",
          "kor28": "korel+%2.8", "kor24": "korel+%2.4",
          "kor20": "korel+%2.0", "kor17": "korel+%1.7",
          "trail10": "takip 1.0",
          "trail15": "takip 1.5",
          "be05": "basabas 0.5",
          "bt": "basabas+takip",
          "rr15": "RR 1.5",
          "buf05": "tampon 0.5",
          "adxr25": "ADX yatay 25",
          "cl1": "1 zarar/8sa"}


def _stop_mesafesi(d):
    """R'nin paydasi: giris ile BASLANGIC stop'u arasi.

    ⚠ sl_price sutunu kullanilmaz -- stop tasinirsa (basabas/ATR takibi) o
    sutun guncelleniyor ve payda sifira yakinsayip R'yi patlatiyor. Islem
    acilirken strategy_scores'a yazilan sl0 hic degismez. Eski kosularda sl0
    yoksa sl_price'a dusulur (o kosularda stop zaten tasinmiyordu)."""
    sl0 = d.strategy_scores.apply(
        lambda s: (json.loads(s or "{}") or {}).get("sl0"))
    taban = sl0.where(sl0.notna(), d.sl_price).astype("float64")
    return (d.entry_price - taban).abs()


def _en_yeni_surum(sonuc):
    """En son degistirilen veritabaninin motor surumu."""
    if not sonuc:
        return None
    en = max(sonuc, key=lambda s: s.get("mtime", 0.0))
    return en.get("motor")


def _kod_parmak_izi():
    """Su an calisan kodun parmak izi -- ikiz/kos.py ile AYNI yontem."""
    import hashlib
    oz = hashlib.sha256()
    for d in ("ikiz/besleme.py", "ikiz/kos.py", "ikiz/saat.py", "main.py",
              "execution.py", "exchange.py", "indicators.py", "data.py",
              "portfolio.py", "config.py", "strategies/donchian.py",
              "strategies/mean_reversion.py", "strategies/squeeze.py"):
        try:
            with open(os.path.join(KOK, d), "rb") as f:
                oz.update(f.read())
        except OSError:
            oz.update(b"?")
    return oz.hexdigest()[:12]


def _meta(yol, anahtar):
    try:
        con = sqlite3.connect(f"file:{yol}?mode=ro", uri=True, timeout=10)
        try:
            r = con.execute("SELECT value FROM meta WHERE key=?",
                            (anahtar,)).fetchone()
            return r[0] if r else None
        finally:
            con.close()
    except Exception:
        return None


def motor_surumu(yol):
    """Kosunun kod surumu. None = surum yazilmadan once kosmus (ESKI)."""
    return _meta(yol, "motor_surum")


def maliyet_ayari(yol):
    """Kosunun SURTUNME ayari. Farkli maliyetle kosmus konfigurasyonlar
    karsilastirilamaz -- maliyetsiz bir tabana gore hepsi 'kotu' cikar."""
    return _meta(yol, "maliyet_ayari") or ""


def oku(yol):
    """⚠ mode=ro KULLANMA. SQLite bir WAL veritabanini okumak icin -shm
    dosyasina YAZABILMEK zorunda; salt-okunur acilista WAL'daki islemleri
    GOREMEZ ve tablo bos gorunur. Kosu dondugu icin islemlerin tamami
    -wal'da duruyor, o yuzden yazilabilir acip birlestiriyoruz."""
    con = sqlite3.connect(yol, timeout=60)
    try:
        d = pd.read_sql(
            "SELECT symbol,side,entry_price,exit_price,sl_price,entry_time,"
            "exit_time,pnl_usdt,exit_reason,strategy_scores "
            "FROM trades WHERE exit_time IS NOT NULL", con)
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.commit()
    finally:
        con.close()
    return d


def olc(d):
    """Kar ve drawdown'i AYNI egriden olcer.

    ⚠ Drawdown BILESIK egriden okunmali: bot pozisyon buyuklugunu o anki
    bakiyeden hesapliyor, yani kayiplar buyudukce pozisyonlar kuculuyor.
    Sabit-kesir egrisinden okunan drawdown gercek hesabin yasadigini vermez.
    pnl_usdt zaten kosunun kendi bilesik bakiyesinden uretildi."""
    d = d.copy()
    d["giris"] = pd.to_datetime(d.entry_time, utc=True, format="mixed")
    d["cikis"] = pd.to_datetime(d.exit_time,  utc=True, format="mixed")
    d = d.sort_values("cikis").reset_index(drop=True)

    yon  = 1 - 2 * d.side.str.lower().str.startswith("s").astype(int)
    stop = _stop_mesafesi(d)
    d["R"] = np.where(stop > 0,
                      yon * (d.exit_price - d.entry_price) / stop.replace(0, np.nan),
                      np.nan)
    d["kol"] = d.strategy_scores.apply(
        lambda s: (json.loads(s or "{}") or {}).get("strategy", "?"))

    # ⚠ egri BAL0'dan baslamali; yoksa ilk islem zararliysa tepe noktasi
    # yanlis yerden baslar ve drawdown oldugundan KUCUK olcunur.
    eq   = pd.concat([pd.Series([BAL0]), BAL0 + d.pnl_usdt.cumsum()],
                     ignore_index=True)
    tepe = eq.cummax()
    dd   = (tepe - eq) / tepe
    maxdd = float(dd.max())

    gun  = max(1, (d.cikis.max() - d.giris.min()).days)
    son  = float(eq.iloc[-1])
    yillik = (son / BAL0) ** (365.0 / gun) - 1.0

    return {
        "d": d, "n": len(d), "gun": gun, "gunde": len(d) / gun,
        "ortR": float(d.R.mean()), "sigmaR": float(d.R.std()),
        "kazanma": float((d.R > 0).mean()),
        "son": son, "getiri": son / BAL0 - 1.0, "yillik": yillik,
        "maxdd": maxdd, "mar": (yillik / maxdd) if maxdd > 0 else float("nan"),
        "ilk": d.giris.min(), "sonT": d.cikis.max(),
    }


def main():
    # ⚠ kalibi DARALT. "ikiz_*.db" klasordeki ALAKASIZ veritabanlarini da
    # yutuyordu: 8 islemlik bir dosya tabloya "trades" diye girdi ve MAR 35.55
    # ile "en iyi" ilan edildi. Yalnizca ETIKET'te tanimli tarama kosulari.
    if sys.argv[1:]:
        yollar = sys.argv[1:]
    else:
        yollar, atlanan = [], []
        for y in sorted(glob.glob(os.path.join(KOK, "ikiz_*.db"))):
            ad = os.path.splitext(os.path.basename(y))[0].replace("ikiz_", "")
            (yollar if ad in ETIKET else atlanan).append(y)
        if atlanan:
            print("  (tarama kosusu olmayan dosyalar atlandi: "
                  + ", ".join(os.path.basename(a) for a in atlanan) + ")")
    if not yollar:
        print("ikiz_*.db bulunamadi. Bu betigi IKIZ klasorunde calistir.")
        return

    sonuc = []
    for y in yollar:
        ad = os.path.splitext(os.path.basename(y))[0].replace("ikiz_", "")
        try:
            d = oku(y)
        except Exception as e:
            print(f"  {ad}: OKUNAMADI  {type(e).__name__}: {e}")
            continue
        if not len(d):
            print(f"  {ad}: kapanmis islem yok")
            continue
        s = olc(d); s["ad"] = ETIKET.get(ad, ad)
        s["motor"] = motor_surumu(y)
        try:
            s["mtime"] = os.path.getmtime(y)
        except OSError:
            s["mtime"] = 0.0
        sonuc.append(s)

    if not sonuc:
        return

    print(f"\n{'='*104}")
    print("=== RISK TARAMASI · kar/drawdown dengesi ===")
    print(f"  baslangic ${BAL0:,.0f} · bilesik boyutlama (bot bakiyeden hesapliyor)")
    print("  bakiye = GERCEKLESMIS deger (kapanmis islemler). Kosu sonunda hala")
    print("  acik pozisyon varsa botun 'serbest nakit' satiri bundan DUSUK olur;")
    print("  aradaki fark o pozisyonlarda kilitli marjdir.")
    print(f"{'='*104}")
    bas = f"{'risk':<12s}{'islem':>7s}{'gunde':>7s}{'ort R':>9s}{'kazan%':>8s}"
    bas += f"{'bakiye':>14s}{'yillik%':>9s}{'maxDD%':>8s}{'MAR':>7s}"
    # ⚠ FARKLI MOTOR SURUMLERI AYRI BASILIR. Yan yana koymak yanlis karara
    # goturur: eski (sizintili) bir kosu tabloda "en iyi" cikabilir.
    surumler = {}
    for s in sonuc:
        surumler.setdefault(s.get("motor"), []).append(s)
    # ⚠ REFERANS = EN SON KOSAN kosunun motoru.
    # Iki yanlis denedim: (1) cogunluk oyu -- damgasiz eski kosular
    # cogunluktaydi ve yenileri "ESKI" ilan etti, tam tersi. (2) calisan
    # kodun parmak izi -- dogruydu ama FAZLA KATI: 13 kaynak dosyadan
    # herhangi birine dokununca (config.py'ye bir satir bile) butun kosular
    # gecersiz sayiliyor ve her seyi yeniden kosmak gerekiyordu.
    # Dogru olan: en yeni kosu referanstir, ondan FARKLI motorla kosmus
    # olanlar onunla karsilastirilamaz.
    guncel = _en_yeni_surum(sonuc)
    if len(surumler) > 1:
        print("\n  " + "!" * 96)
        print("  !! Klasorde BIRDEN COK MOTOR SURUMUNUN sonucu var.")
        print("  !! Farkli surumler KARSILASTIRILAMAZ (orn. gelecek sizintisi")
        print("  !! duzeltilince taban 1778/+0.1581 -> 1752/+0.1675 oldu).")
        for m, g in sorted(surumler.items(), key=lambda kv: -len(kv[1])):
            etiket = (str(m) if m else "damgasiz (damga eklenmeden once kosmus)")
            isaret = ("  <- GUNCEL KOD" if m == guncel
                      else "  <- eski kod, karsilastirma GECERSIZ")
            print(f"  !!   {etiket:<28s} {len(g):>2d} kosu{isaret}")
        _kod = _kod_parmak_izi()
        if guncel is not None and _kod != guncel:
            print(f"  !! Not: su an CALISAN kod ({_kod}) en yeni kosunun")
            print(f"  !!       motorundan ({guncel}) da farkli -- arada kod")
            print("  !!       degisti. Karar verecekseniz taramayi yenileyin.")
        print("  !! Eskileri silmek icin: ikiz_tani.py ile bak, sonra sil.")
        print("  " + "!" * 96)
    sonuc = sorted(sonuc, key=lambda s: (s.get("motor") != guncel, -s["mar"]))

    print(bas)
    print("-" * 104)
    for s in sonuc:
        isaret = "" if s.get("motor") == guncel else "  (ESKI)"
        print(f"{s['ad']:<12s}{s['n']:>7d}{s['gunde']:>7.2f}{s['ortR']:>+9.4f}"
              f"{s['kazanma']*100:>8.1f}{s['son']:>14,.0f}"
              f"{s['yillik']*100:>9.1f}{s['maxdd']*100:>8.1f}{s['mar']:>7.2f}{isaret}")
    print("-" * 104)

    # ⚠ SESSİZ BAŞARISIZLIK MUHAFIZI. 2026-09-19: dört koşu da aynı ayarla
    # koştu (ikiz/kos.py:77 CANLI_ENV çağıranın RISK_SCALE'ini EZİYORDU) ve bu
    # tablo dört ÖZDEŞ satır bastı. Tablo geldiği için sonuç doğru sanıldı;
    # oysa tarama hiç yapılmamıştı ve 5 saat boşa gitti. Bir daha sessizce
    # geçmesin: aynı sonuç = tarama olmamış demektir.
    imza = {(s["n"], round(s["son"], 2), round(s["ortR"], 6)) for s in sonuc}
    if len(sonuc) > 1 and len(imza) == 1:
        print("\n  " + "!" * 88)
        print("  !! TARAMA YAPILMAMIŞ: tüm koşular BİREBİR aynı sonucu verdi.")
        print("  !! Farklı ayarlar alt süreçlere ULAŞMAMIŞ demektir; bu tablo")
        print("  !! risk sorusu hakkında hiçbir şey söylemez.")
        print("  !! Koşu başındaki 'ETKİN AYAR' satırını kontrol et: her koşu")
        print("  !! kendi RISK_SCALE değerini yazmalı.")
        print("  " + "!" * 88)
        return

    # ⚠ MAR = yillik getiri / en derin dusus. Karsilastirmanin ASIL sutunu bu.
    # Cunku riski buyutunce bakiye sutunu HER ZAMAN buyur; tek basina bakmak
    # "daha cok risk her zaman daha iyi" yanlis sonucunu verir.
    # ⚠ "en iyi" YALNIZCA guncel motordan secilir.
    aday = [s for s in sonuc if s.get("motor") == guncel] or sonuc
    en = max(aday, key=lambda s: s["mar"] if s["mar"] == s["mar"] else -9e9)
    canli = next((s for s in sonuc if "CANLI" in s["ad"]), None)
    print(f"\n  en iyi MAR (yillik getiri / maxDD): {en['ad']}  "
          f"MAR {en['mar']:.2f}  (yillik %{en['yillik']*100:.1f} · "
          f"maxDD %{en['maxdd']*100:.1f})")
    if canli is not None and canli is not en:
        print(f"  su anki CANLI ayar:                {canli['ad']}  "
              f"MAR {canli['mar']:.2f}  (yillik %{canli['yillik']*100:.1f} · "
              f"maxDD %{canli['maxdd']*100:.1f})")
    elif canli is not None:
        print("  su anki CANLI ayar zaten en iyi MAR'a sahip.")

    s0 = sonuc[0]
    print(f"\n  veri araligi: {s0['ilk'].date()} -> {s0['sonT'].date()}  "
          f"({s0['gun']} gun)")
    print(f"  (kosu tamamsa bitis 2026-07 civari olmali; cok erkense kosu "
          f"yarida kalmis demektir)")

    print(f"\n  kol dagilimi (islem sayisi · ort R):")
    for s in sonuc:
        par = "  ".join(f"{k} {len(g)}/{g.R.mean():+.3f}"
                        for k, g in s["d"].groupby("kol"))
        print(f"    {s['ad']:<12s} {par}")
    print(f"{'='*104}")


if __name__ == "__main__":
    main()
