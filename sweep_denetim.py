"""
sweep_denetim.py — ARŞİV DENETİMİ: "Likidite Sweep / Stop Avı" ailesi.
SADECE ÖLÇER, hiçbir üretim dosyasına dokunmaz. Yeni kol ÖNERMEZ.

AMAÇ: nk_range.py'nin zaten ölçtüğü "kenar ihlali + içeri kapanış" (= sweep üçlüsü)
sonucunu, BU SEANSIN iki yeni kısıtı altında yeniden okumak:
  · kısıt 1 (geniş stop): kayma = 15.85bp / stop_mesafesi  → nk_range bunu HİÇ eklemedi
  · kısıt 2 (short bacak boş): long/short AYRI raporla → nk_range ledger'da ayrık yok

Kullanım: py sweep_denetim.py local
"""
import sys
import numpy as np
import pandas as pd
import nk_range as NK

KAYMA = 15.85 / 1e4
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")


def olc(out, etiket):
    """out = nk_range.sim çıktısı: (i, giris_ts, cikis_ts, R, sl_pct, yon)"""
    if not out:
        return
    R = np.array([o[3] for o in out], float)
    sp = np.array([o[4] for o in out], float)
    yn = np.array([o[5] for o in out], int)
    gi = np.array([pd.Timestamp(o[1]).value for o in out])
    Rk = R - KAYMA / sp                       # kaymalı
    te = gi >= SPLIT.value
    def blok(m, ad):
        if m.sum() < 20:
            return f"{ad}: n={m.sum()} (az)"
        r, rk = R[m], Rk[m]
        z = rk.mean() / rk.std(ddof=1) * np.sqrt(len(rk))
        return (f"{ad}: n={m.sum():>6} sl%={np.median(sp[m])*100:>5.2f} "
                f"kaymasizR={r.mean():+.4f} KAYMALI={rk.mean():+.4f} z={z:+.2f}")
    print(f"\n  {etiket}")
    print(f"    {blok(np.ones(len(R), bool), 'TUMU ')}")
    print(f"    {blok(yn == 1, 'LONG ')}")
    print(f"    {blok(yn == -1, 'SHORT')}")
    m = (yn == 1) & te
    if m.sum() >= 20:
        print(f"    {blok(m, 'LONG-TEST(>=2025)')}")


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "local"
    print("veri yukleniyor...")
    NK.load_raw(src)
    print(f"yuklenen coin: {len(NK.RAW)}  ({', '.join(sorted(NK.RAW))})")

    # nk_range'in ON-KAYITLI merkez konfigurasyonu (argmax YOK)
    N, RR, SL, MH = NK.C_N, NK.C_RR, NK.C_SL, NK.C_MH
    print(f"\nmerkez konfig (nk_range on-kayitli): N={N} rr={RR} sl={SL}xATR mh={MH}")

    for tf in ["1h", "2h", "4h"]:
        for det, thr in [("none", 0.0), ("rank", 0.40)]:
            hepsi = []
            for c in sorted(NK.RAW):
                P = NK.prep(c, tf)
                if P is None:
                    continue
                sm, lm = NK.signals(P, N, det, thr)
                hepsi += NK.sim(P, sm, lm, RR, SL, MH)
            olc(hepsi, f"tf={tf} det={det}({thr})  [MEAN-REV = sweep yonu]")


if __name__ == "__main__":
    main()
