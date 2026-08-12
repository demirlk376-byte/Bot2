"""
pw_daily_halt.py — İYİ AYLARA DOKUNMADAN KÖTÜ AYLARI KISABİLİR MİYİZ? (günlük zarar freni)

BUGÜNE KADAR REDDEDİLEN 20 EKSENİN HEPSİ **İŞLEM BAZINDA** maruziyeti kısıyordu:
trailing, breakeven, kısmi çıkış, rr genişletme, maruziyet tavanı, koltuk azaltma...
Hepsi aynı duvara çarptı: kuyruk riski FİYATLI. Satarsan puan başına en fazla $23.6
kazanıyorsun, satın alırsan puan başına en az $80 ödüyorsun.

BU FARKLI BİR MEKANİZMA: **GÜN BAZINDA PORTFÖY** freni. Tek tek işlemlere değil,
bir günün toplamına bakıyor. risk.py:246 (check_daily_loss_limit) zaten var ve
execution.py:470 tetiklendiğinde `halt_trading` + `emergency_close_all` çağırıyor.

AMA CANLI EŞİK **DAILY_MAX_LOSS_PCT=0.35** — yani bir günde bakiyenin %35'i.
Ankorun en kötü AYI %21. Yani bu fren pratikte HİÇ tetiklenmiyor; ölü bir kontrol.

HİPOTEZ: kötü aylar, birçok pozisyonun aynı gün birlikte kaybettiği birkaç GÜNDEN
oluşuyorsa, gün bazında bir fren o günleri kesip iyi aylara dokunmayabilir (iyi
aylarda öyle günler yok).

⚠️ BU MODELİN BİLİNEN EKSİĞİ — sonucu okurken şart:
Canlı fren ÖZ SERMAYEYE bakıyor, yani AÇIK pozisyonların gerçekleşmemiş zararını da
sayıyor ve pozisyon KAPANMADAN tetikleniyor. Bu betik yalnızca GERÇEKLEŞEN (kapanmış)
zararı görebiliyor, çünkü A.gen işlem içi eşik-eşik fiyat vermiyor. Dolayısıyla burada
modellenen fren GERÇEĞİNDEN DAHA GEÇ tetikleniyor. Sonuç: buradaki etki gerçek etkinin
ALT SINIRI; gerçek fren daha çok keser (hem kötüyü hem iyiyi).

⚠️ AYRICA: bu test işlem KÜMESİNİ değiştiriyor. pw_cooldown'da öğrenildi ki kümeyi
değiştiren testlerde kuyruk metrikleri bir avuç işleme duyarlı (6 işlem = 1.9 puan).
O yüzden "kaç işlem atlandı" ve "kaç gün frenlendi" HER SATIRDA raporlanıyor; az
sayıda güne dayanan bir iyileşme bulgu değildir.

KONTROL: eşik %35 (canlı) → ankoru BİREBİR üretmeli (fren hiç tetiklenmemeli).

ÖN-KAYITLI BAR (değişmedi): Δ$ > +28 · hiçbir yıl >%10 kötüleşmeyecek ·
maxDD +2 puandan fazla artmayacak · EN KÖTÜ AY KÖTÜLEŞMEYECEK.
AMA BU EKSENDE ASIL SORU FARKLI: en kötü ay ÇOK iyileşirken kâr az kaybediyorsa
bu bir TAKAS adayıdır ve ayrıca raporlanıyor (puan başına kaç dolar).

Kullanım:  py pw_daily_halt.py local
"""
import heapq
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A

CAP_YENI = 1.50      # paket sonrası hâl


def olaylar(source):
    """(entry_ns, exit_ns, R, sl_pct) — giriş zamanına göre sıralı."""
    t = []
    for c in A.DONCH:
        for x in A.gen("donchian", fast_bt.load(c, source=source)):
            t.append((x[0], x[1].value, x[2], x[3]))
    for c in A.SQZ:
        for x in A.gen("squeeze", fast_bt.load(c, source=source)):
            t.append((x[0], x[1].value, x[2], x[3]))
    for c in A.BB_COINS:
        for x in A.gen_bb(fast_bt.load(c, source=source)):
            t.append((x[0], x[1].value, x[2], x[3]))
    return sorted(t, key=lambda z: z[0])


def gun(ns):
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).date()


def calistir(ev, esik, cap=CAP_YENI):
    """esik=None → fren kapalı. Fren: o GÜN gerçekleşen zarar > esik×BAL ise
    günün geri kalanında YENİ GİRİŞ yok (açık pozisyonlar devam eder)."""
    koltuk = []          # (exit_ns, ctr)
    kapanis = []         # (exit_ns, ctr, pnl$)
    ctr = 0
    alinan = []
    bugun = None
    gun_pnl = 0.0
    frenli = False
    atlanan = 0
    frenli_gunler = set()
    for e_ns, x_ns, R, slp in ev:
        g = gun(e_ns)
        if g != bugun:
            bugun, gun_pnl, frenli = g, 0.0, False
        # bu girişten ÖNCE kapanan işlemlerin sonucunu güne işle
        while kapanis and kapanis[0][0] <= e_ns:
            k_ns, _, pnl = heapq.heappop(kapanis)
            if gun(k_ns) == bugun:
                gun_pnl += pnl
                if esik is not None and gun_pnl < -esik * A.BAL0:
                    if not frenli:
                        frenli_gunler.add(bugun)
                    frenli = True
        while koltuk and koltuk[0][0] <= e_ns:
            heapq.heappop(koltuk)
        if frenli:
            atlanan += 1
            continue
        if len(koltuk) < A.MAXPOS:
            ctr += 1
            eff = min(A.RISKF, cap * slp)
            heapq.heappush(koltuk, (x_ns, ctr))
            heapq.heappush(kapanis, (x_ns, ctr, R * eff * A.BAL0))
            alinan.append((x_ns, R, slp))
    return alinan, atlanan, len(frenli_gunler)


def olc(taken, cap=CAP_YENI):
    r = np.array([t[1] for t in taken]); sp = np.array([t[2] for t in taken])
    eff = np.minimum(A.RISKF, cap * sp)
    pnl = r * eff * A.BAL0
    eq = A.BAL0 + np.cumsum(pnl)
    ex = [pd.Timestamp(t[0]) for t in taken]
    mon = pd.Series(pnl).groupby([x.tz_localize(None).to_period("M") for x in ex]).sum() / A.BAL0 * 100
    yr = pd.Series(pnl).groupby([x.year for x in ex]).sum()
    dip = mon.nsmallest(3)
    return dict(n=len(taken), tot=float(pnl.sum()),
                dd=float(A.maxdd(np.concatenate([[A.BAL0], eq]))),
                worst=float(mon.min()), posm=float((mon > 0).mean() * 100),
                yr={int(k): float(v) for k, v in yr.items()},
                dip=[(str(k), float(v)) for k, v in dip.items()])


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    ev = olaylar(source)
    print(f"\n{'=' * 122}")
    print("=== GÜNLÜK ZARAR FRENİ: iyi aylara dokunmadan kötü ayları kısabilir miyiz? ===")
    print(f"  {len(ev)} aday sinyal · canlı DAILY_MAX_LOSS_PCT=0.35 (pratikte ölü) · CAP={CAP_YENI}")

    base, _, _ = calistir(ev, None)
    taban = olc(base)
    print(f"\n  KONTROL (fren kapalı): {taban['n']} işlem / ${taban['tot']:+.2f}")
    k35, a35, g35 = calistir(ev, 0.35)
    print(f"  KONTROL (eşik %35 = canlı): {len(k35)} işlem / atlanan {a35} / frenli gün {g35}"
          f" → {'✓ fren hiç tetiklenmiyor, doğrulandı' if a35 == 0 else '✗ tetikleniyor?'}")

    years = sorted(taban["yr"])
    print(f"\n  {'eşik%':>6s} {'işlem':>6s} {'atlanan':>8s} {'frenli gün':>11s} {'toplam$':>9s} "
          f"{'Δ$':>7s} {'maxDD%':>7s} {'kötü ay%':>9s} {'Δkötü ay':>9s} {'poz-ay':>7s} | " +
          " ".join(f"{y:>7d}" for y in years))
    print(f"  {'—':>6s} {taban['n']:>6d} {0:>8d} {0:>11d} {taban['tot']:>+9.0f} {0:>+7.0f} "
          f"{taban['dd']:>7.1f} {taban['worst']:>+9.1f} {0:>+9.1f} {taban['posm']:>7.0f} | " +
          " ".join(f"{taban['yr'].get(y, 0.0):>+7.0f}" for y in years) + "   ← FREN YOK")

    # İNCE IZGARA: kaba taramada %6 tek başına iyi göründü ama eğri ZIGZAG (%4 kötü,
    # %6 iyi, %8-10 nötr). Gerçek mekanizma doz-yanıt verir. Komşuları da ölçüp
    # %6'nın bir bıçak sırtı mı yoksa gerçek bir eşik mi olduğunu ayırt ediyoruz.
    ince = len(sys.argv) > 2 and sys.argv[2] == "ince"
    izgara = ((0.045, 0.050, 0.055, 0.060, 0.065, 0.070, 0.075, 0.080) if ince
              else (0.04, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20))
    sonuc = {}
    for esik in izgara:
        t, atl, gn = calistir(ev, esik)
        v = olc(t); sonuc[esik] = (v, atl, gn)
        print(f"  {esik*100:>5.0f}% {v['n']:>6d} {atl:>8d} {gn:>11d} {v['tot']:>+9.0f} "
              f"{v['tot']-taban['tot']:>+7.0f} {v['dd']:>7.1f} {v['worst']:>+9.1f} "
              f"{v['worst']-taban['worst']:>+9.1f} {v['posm']:>7.0f} | " +
              " ".join(f"{v['yr'].get(y, 0.0):>+7.0f}" for y in years))

    # ── HÜKÜM ──
    print(f"\n{'=' * 122}\n=== HÜKÜM ===")
    print(f"\n  [1] ÖN-KAYITLI BAR (kâr da artmalı, kuyruk da kötüleşmemeli)")
    gecen = []
    for esik, (v, atl, gn) in sonuc.items():
        w = []
        if v["tot"] - taban["tot"] <= 28: w.append(f"kâr {v['tot']-taban['tot']:+.0f}$")
        for y in years:
            b = taban["yr"].get(y, 0)
            if abs(b) > 1e-9 and (v["yr"].get(y, 0) - b) / abs(b) < -0.10:
                w.append(f"{y} kötü"); break
        if v["dd"] > taban["dd"] + 2: w.append(f"maxDD {v['dd']:.1f}")
        if v["worst"] < taban["worst"] - 0.05: w.append(f"en kötü ay {v['worst']:.1f}")
        if not w:
            gecen.append(esik); print(f"      ★ GEÇTİ  eşik %{esik*100:.0f}")
    if not gecen:
        print(f"      hiçbiri geçmedi (beklenen: fren kâr EKLEMEZ, işlem çıkarır).")

    print(f"\n  [2] TAKAS FİYATI — en kötü ayı 1 puan iyileştirmek kaç dolara mal oluyor?")
    print(f"      (bugüne kadar ölçülen piyasa fiyatı: koruma ALMAK ≥ $80/puan)")
    print(f"      {'eşik%':>6s} {'Δkötü ay':>9s} {'Δkâr$':>8s} {'$/puan':>10s} {'frenli gün':>11s}")
    for esik, (v, atl, gn) in sonuc.items():
        d_worst = v["worst"] - taban["worst"]
        d_tot = v["tot"] - taban["tot"]
        if d_worst > 0.05:
            fiyat = -d_tot / d_worst
            not_ = "  ← BEDAVA/KÂRLI" if d_tot >= 0 else ("  ← UCUZ" if fiyat < 80 else "")
            print(f"      {esik*100:>5.0f}% {d_worst:>+9.1f} {d_tot:>+8.0f} "
                  f"{fiyat:>10.0f}{not_}")
        else:
            print(f"      {esik*100:>5.0f}% {d_worst:>+9.1f} {d_tot:>+8.0f} "
                  f"{'—':>10s}   (kuyruk iyileşmedi)")

    print(f"\n  [3] EN KÖTÜ ÜÇ AY — 'iyileşme' gerçek mi, yoksa sıralama mı değişti?")
    print(f"      Kuyruk gerçekten kısılıyorsa EN KÖTÜ ÜÇ AYIN HEPSİ iyileşmeli. Yalnız")
    print(f"      birincisi iyileşip ikincisi yerine geçiyorsa o iyileşme SAHTEDİR.")
    print(f"      {'eşik':>6s}  " + "  ".join(f"{'dip-'+str(i+1):>16s}" for i in range(3)))
    print(f"      {'—':>6s}  " + "  ".join(f"{a+' '+f'{b:+.1f}':>16s}" for a, b in taban["dip"]))
    for esik, (v, atl, gn) in sonuc.items():
        print(f"      {esik*100:>5.0f}%  " +
              "  ".join(f"{a+' '+f'{b:+.1f}':>16s}" for a, b in v["dip"]))

    print(f"\n  [4] KIRILGANLIK UYARISI")
    for esik, (v, atl, gn) in sonuc.items():
        if v["worst"] - taban["worst"] > 0.5 and gn <= 5:
            print(f"      ⚠ eşik %{esik*100:.0f}: kuyruk {v['worst']-taban['worst']:+.1f} puan "
                  f"iyileşiyor ama bu YALNIZ {gn} frenli güne dayanıyor → bulgu SAYILMAZ.")
    print(f"\n  ⚠ Bu model gerçeğinden GEÇ tetikleniyor (yalnız gerçekleşen zararı görüyor;")
    print(f"    canlı fren açık pozisyonların zararını da sayar). Etki ALT SINIRDIR.")


if __name__ == "__main__":
    main()
