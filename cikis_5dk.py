"""
cikis_5dk.py — SENİN FİKRİNİN KALAN VARYANTI: 5dk'yı GİRİŞTE değil ÇIKIŞTA kullan.

ic_bar.py girişte filtrelemeyi test etti ve kapandı: bar içi 5dk yapısı, kırılımın
çökeceğini KIRILIM ANINDA haber vermiyor (30 dilimin 30'u pozitif).

Bu dosya farklı bir soruyu soruyor. Girişte elimizde yalnız GEÇMİŞ var. Girişten
SONRA ise YENİ bilgi geliyor: kırılım seviyesi geri kaybediliyor mu?
"Sahte kırılım" tanımının kendisi budur — fiyat seviyeyi geçip sonra geri düşer.
`fake_kirilim` bu grubun ort R'sini −0.2488 ölçmüştü. Soru: o grubu GERÇEK ZAMANLI
yakalayıp erken çıkmak para kazandırır mı?

⚠ BU BİR "DAHA DAR STOP" DEĞİL — ve neden olmadığını baştan söylemek gerekiyor,
çünkü öyleyse zaten test edilmiş demektir (sl_sweep.py, power_exit.py stop
mesafelerini taramıştı). Fark: sabit ATR stopu HER işlemde aynı uzaklıkta.
Seviye-kaybı çıkışı YAPISAL: tetiklendiği mesafe işlemden işleme değişir, çünkü
giriş (bar kapanışı) ile kanal seviyesi arasındaki mesafe değişkendir. Bazı
işlemlerde ATR stopundan ÖNCE, bazılarında SONRA tetiklenir.
Rapor bu mesafenin dağılımını basıyor; hepsi aynı yerdeyse eksen zaten kapanır.

═══ ÖNCE GEREK ŞART, SONRA HER ŞEY ═══════════════════════════════════════════
Bugünkü kural: bir çıkış kuralı ancak KESTİĞİ GRUBUN ort R'si NEGATİFSE para
kazandırır. Bu araç ÖNCE onu soruyor:
    "işlem sırasında seviyeyi kaybeden işlemlerin MEVCUT kuralla ort R'si kaç?"
Pozitifse eksen ORADA kapanır, çıkış simülasyonu bile çalıştırılmaz.
Negatifse ikinci soru gelir: erken çıkmak, o grubun kaybından DAHA AZ mı maliyetli?

⚠ 5dk ÇÖZÜNÜRLÜK ETKİSİ ayrıca raporlanıyor: mevcut ankor 4 SAATLİK barlarla
simüle ediyor ve bar-içi fitilleri göremiyor. Aynı işlemleri 5dk yolunda simüle
edince stoplar DAHA SIK tetiklenir. Bu farkın kendisi bir bulgudur: ankorun
gerçeği ne kadar iyimser gösterdiğini söyler.

⚠ VENUE: sinyaller + seviyeler MEXC 1h (ankor verisi), 5dk yol Binance
(korelasyon 0.99976). Bir kural eşiği geçerse MEXC doğrulaması ŞART.

Kullanım (VPS'te):
    nohup python3 -u cikis_5dk.py > /tmp/cikis.log 2>&1 & disown
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import deployed_backtest as A
import fast_bt
from ic_bar import donchian_izli

CACHE = "data"
# ÖN-KAYITLI: seviye "kaybedildi" sayılması için 5dk KAPANIŞININ seviyeyi ne kadar
# geçmesi gerektiği (ATR biriminde). 0.0 = temiz kapanış yeter. Karar bu satırdan.
TAMPON = [0.0, 0.25, 0.5]
KARAR_TAMPON = 0.0


def yol_5dk(tr: dict, b5: pd.DataFrame, cikis_ts) -> pd.DataFrame:
    """Girişten (4h bar kapanışı) çıkışa kadarki 5dk barları."""
    t0 = tr["t0"] + pd.Timedelta(hours=4)          # 4h bar KAPANIŞI = giriş anı
    t1 = pd.Timestamp(cikis_ts) + pd.Timedelta(hours=4)
    return b5.loc[(b5.index >= t0) & (b5.index < t1)]


def sim(tr: dict, yol: pd.DataFrame, tampon: float | None):
    """5dk yolunda çıkışı simüle eder.
    tampon=None → yalnız SL/TP (temel kol).
    tampon=x    → SL/TP + seviye-kaybı çıkışı (5dk kapanışı seviyeyi x·ATR geçerse).
    Döner: (R, cikis_turu, bar_sayisi, seviye_kaybi_oldu_mu)"""
    d_ = tr["yon"]; e = tr["kapanis"]; a = tr["atr"]
    sld = 2.0 * a                                   # ankor: sl_atr=2.0
    sl = e - d_ * sld; tp = e + d_ * 2.0 * sld      # ankor: rr=2.0
    lvl = tr["seviye"]
    hi = yol["high"].values; lo = yol["low"].values; cl = yol["close"].values
    kayip = False
    for j in range(len(cl)):
        # STOP ÖNCE (kötümser) — aynı 5dk barında ikisi de olursa
        if d_ == 1 and lo[j] <= sl: return (d_*(sl-e)/sld - 2*A.FEE*e/sld, "sl", j, kayip)
        if d_ == -1 and hi[j] >= sl: return (d_*(sl-e)/sld - 2*A.FEE*e/sld, "sl", j, kayip)
        if d_ == 1 and hi[j] >= tp: return (d_*(tp-e)/sld - 2*A.FEE*e/sld, "tp", j, kayip)
        if d_ == -1 and lo[j] <= tp: return (d_*(tp-e)/sld - 2*A.FEE*e/sld, "tp", j, kayip)
        # SEVİYE KAYBI — kapanış seviyenin GERİ tarafında
        esik = lvl - d_ * tampon * a if tampon is not None else None
        kayip_simdi = (cl[j] < lvl - (0 if tampon is None else tampon)*a) if d_ == 1 \
                      else (cl[j] > lvl + (0 if tampon is None else tampon)*a)
        if kayip_simdi:
            kayip = True
            if tampon is not None:
                x = cl[j]
                return (d_*(x-e)/sld - 2*A.FEE*e/sld, "seviye", j, True)
    # yol bitti (4h max-hold) → son kapanış
    if len(cl) == 0:
        return (0.0, "bos", 0, kayip)
    x = cl[-1]
    return (d_*(x-e)/sld - 2*A.FEE*e/sld, "mh", len(cl)-1, kayip)


def ozet(r: np.ndarray) -> str:
    if len(r) == 0: return "n=0"
    se = r.std(ddof=1)/np.sqrt(len(r)) if len(r) > 1 else float("nan")
    pf = r[r>0].sum()/max(-r[r<=0].sum(), 1e-9)
    return (f"n={len(r):<5d} ort {r.mean():+.4f} [{r.mean()-1.96*se:+.4f},"
            f"{r.mean()+1.96*se:+.4f}]  PF {pf:5.2f}  WR {(r>0).mean()*100:4.1f}%")


def main() -> None:
    print("=" * 112)
    print("=== 5dk ÇIKIŞ TESTİ — seviye kaybedilince erken çık ===")
    print("  ic_bar GİRİŞTE filtrelemeyi kapattı. Bu, ÇIKIŞTA kullanmayı sınıyor.")
    print("  Girişte yalnız geçmiş var; girişten SONRA yeni bilgi geliyor.")

    # ── KONTROL ──
    trades = []
    for c in A.DONCH: trades += A.gen("donchian", fast_bt.load(c, source="local"))
    for c in A.SQZ: trades += A.gen("squeeze", fast_bt.load(c, source="local"))
    for c in A.BB_COINS: trades += A.gen_bb(fast_bt.load(c, source="local"))
    tk = A.seat_select(trades)
    rr = np.array([R for _, R, _ in tk]); spp = np.array([s for _, _, s in tk])
    tot = (rr*np.minimum(A.RISKF, A.CAP*spp)*A.BAL0).sum()
    ok = len(tk) == 1579 and abs(tot-1420.66) < 1.0
    print(f"\n  DOĞRULAMA (ankor): {len(tk)} işlem / ${tot:+.2f} → "
          f"{'✓ BİREBİR' if ok else '✗ SAPMA — git checkout -- data/ ve tekrar dene'}")
    if not ok:
        return

    # ── donchian işlemleri + 5dk yolları ──
    kayit = []
    for c in A.DONCH:
        m = fast_bt.load(c, source="local")
        tr_l = donchian_izli(m)
        try:
            b5 = pd.read_csv(f"{CACHE}/{c}_bnc_5m.csv", index_col=0, parse_dates=True)
            if b5.index.tz is None: b5.index = b5.index.tz_localize("UTC")
        except FileNotFoundError:
            print(f"  {c}: 5dk veri YOK"); continue
        n0 = len(kayit)
        for t in tr_l:
            y = yol_5dk(t, b5, t["exit_ts"])
            if len(y) < 6:            # en az 30 dakikalık yol
                continue
            kayit.append((t, y))
        print(f"  {c:<5s} {len(tr_l):>4d} sinyal → {len(kayit)-n0:>4d} yol", flush=True)
    if len(kayit) < 200:
        print(f"\n  ⛔ n={len(kayit)} çok az."); return
    print(f"\n  toplam {len(kayit)} işlem 5dk yoluyla eşleşti")

    # ── TEMEL KOL: yalnız SL/TP, ama 5dk çözünürlükte ──
    tabanR, tur, kayipvar = [], [], []
    for t, y in kayit:
        R, k, _, kb = sim(t, y, None)
        tabanR.append(R); tur.append(k); kayipvar.append(kb)
    tabanR = np.array(tabanR); kayipvar = np.array(kayipvar)
    ank_r = np.array([t["R"] for t, _ in kayit])

    print(f"\n{'='*112}\n=== [1] 5dk ÇÖZÜNÜRLÜK ETKİSİ (ankorun kendi iyimserliği) ===")
    print(f"  ankor (4h barlarla)  : {ozet(ank_r)}")
    print(f"  aynı işlemler 5dk yolu: {ozet(tabanR)}")
    print(f"  FARK: {tabanR.mean()-ank_r.mean():+.4f}R/işlem")
    print(f"  → 4 saatlik bar, bar-içi fitilleri göremiyor. 5dk yolunda stoplar daha")
    print(f"    sık tetikleniyorsa ankor gerçeği İYİMSER gösteriyor demektir.")
    d = {k: tur.count(k) for k in set(tur)}
    print(f"  çıkış dağılımı (5dk): " + " · ".join(f"{k} {v}" for k, v in sorted(d.items())))

    # ── [2] GEREK ŞART — kesilecek grup NEGATİF mi? ──
    print(f"\n{'='*112}\n=== [2] GEREK ŞART: seviyeyi kaybeden grubun ort R'si ===")
    print(f"  Bugünkü kural: kesilen grubun ort R'si NEGATİF DEĞİLSE filtre para")
    print(f"  kazandırmaz. Pozitifse eksen BURADA kapanır.")
    g1 = tabanR[kayipvar]; g0 = tabanR[~kayipvar]
    print(f"\n  seviyeyi KAYBEDEN  : {ozet(g1)}")
    print(f"  seviyeyi KORUYAN   : {ozet(g0)}")
    if len(g1) > 1 and len(g0) > 1:
        z = (g0.mean()-g1.mean())/np.sqrt(g0.var(ddof=1)/len(g0)+g1.var(ddof=1)/len(g1))
        print(f"  ayrışma z = {z:+.2f}")
    if len(g1) == 0 or g1.mean() >= 0:
        print(f"\n{'='*112}\n=== HÜKÜM ===")
        print(f"  ✗ Seviyeyi kaybeden grup NEGATİF DEĞİL ({g1.mean() if len(g1) else 0:+.4f}R).")
        print(f"    Erken çıkmak, kârlı bir grubu kesmek olur. EKSEN KAPANDI —")
        print(f"    çıkış simülasyonu çalıştırılmadı (gereksiz).")
        return
    print(f"\n  ✓ Grup negatif → ikinci soruya geçiliyor: erken çıkmak neye mal oluyor?")

    # ── [3] ÇIKIŞ SİMÜLASYONU ──
    print(f"\n{'='*112}\n=== [3] SEVİYE-KAYBI ÇIKIŞI — tampon taraması ===")
    print(f"  {'tampon':>7s} {'kesilen':>8s} {'toplam ort R':>26s} {'Δ vs taban':>11s}"
          f" {'tetik mesafe (ATR)':>20s}")
    for tmp in TAMPON:
        R2, mes = [], []
        for t, y in kayit:
            R, k, j, _ = sim(t, y, tmp)
            R2.append(R)
            if k == "seviye":
                mes.append(abs(t["kapanis"] - t["seviye"]) / t["atr"])
        R2 = np.array(R2)
        n_kes = sum(1 for t, y in kayit if sim(t, y, tmp)[1] == "seviye")
        se = R2.std(ddof=1)/np.sqrt(len(R2))
        mm = f"{np.mean(mes):.2f}±{np.std(mes):.2f}" if mes else "—"
        mark = "  ← KARAR" if tmp == KARAR_TAMPON else ""
        print(f"  {tmp:>7.2f} {n_kes:>8d} {R2.mean():>+13.4f} "
              f"[{R2.mean()-1.96*se:+.4f},{R2.mean()+1.96*se:+.4f}] "
              f"{R2.mean()-tabanR.mean():>+11.4f} {mm:>20s}{mark}")
    print(f"\n  ⚠ 'tetik mesafe' = giriş ile seviye arası, ATR biriminde. Ankorun stopu")
    print(f"    2.00 ATR. Bu sayı 2.00'a çok yakınsa kural SABİT STOPtan farklı değildir")
    print(f"    ve zaten sl_sweep.py'de taranmıştır — o zaman eksen kapanır.")


if __name__ == "__main__":
    main()
