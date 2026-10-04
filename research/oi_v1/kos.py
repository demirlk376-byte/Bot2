"""OI_V1 koşusu: eski 12'de seçim, yeni 26'da dondurulmuş sınav (MANIFEST.md)."""
import json
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from research.oi_v1 import motor as M   # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sonuclar")
os.makedirs(OUT, exist_ok=True)
VERI = {}


def veri(coin):
    if coin not in VERI:
        VERI[coin] = M.yukle(coin)
    return VERI[coin]


def havuz(coinler, aile, p, kat):
    tr = []
    for c in coinler:
        tr += M.islemler(veri(c), aile, p, kat)
    tr.sort()
    return tr


def ozet(tr):
    R = np.array([x[2] for x in tr]) if tr else np.array([])
    return dict(n=len(tr), ortR=float(R.mean()) if len(R) else float("nan"))


def main():
    # akıl kontrolü: OI eşleşme oranı
    for c in ("ETH", "LINK"):
        d = veri(c)
        m = d["open_time"] >= M.BAS
        print(f"{c}: OI eşleşme (kapanış) {d.loc[m, 'oi_kap'].notna().mean():.1%}  (açılış) {d.loc[m, 'oi_ac'].notna().mean():.1%}")
    rapor = {}
    for aile in ("TC", "OD"):
        print(f"\n===== AİLE {aile} — SEÇİM (eski 12)")
        satir = []
        for p in M.varyantlar(aile):
            n_ = ozet(havuz(M.ESKI12, aile, p, 1.0))
            s_ = ozet(havuz(M.ESKI12, aile, p, 2.0))
            satir.append((p, n_, s_))
            print(f"  {p['ad']:<22} n {n_['n']:>5}  NORMAL {n_['ortR']:+.3f}R  STRESS {s_['ortR']:+.3f}R")
        uygun = [x for x in satir if x[1]["ortR"] > 0 and x[2]["ortR"] > 0 and x[1]["n"] >= 60]
        if not uygun:
            print(f"  → {aile} ELENDİ (seçimde uygun varyant yok)")
            rapor[aile] = dict(karar="ELENDI_SECIM")
            continue
        p, _, _ = max(uygun, key=lambda x: x[2]["ortR"])
        print(f"  → seçilen: {p['ad']}")
        trN = havuz(M.YENI26, aile, p, 1.0)
        trS = havuz(M.YENI26, aile, p, 2.0)
        n_, s_ = ozet(trN), ozet(trS)
        lcb = M.bootstrap_lcb(trN)
        tuttu = n_["ortR"] > 0 and s_["ortR"] > 0 and lcb > 0 and n_["n"] >= 60
        print(f"===== AİLE {aile} — SINAV (yeni 26) {p['ad']}")
        print(f"  n {n_['n']}  NORMAL {n_['ortR']:+.3f}R  STRESS {s_['ortR']:+.3f}R  LCB(%1.25) {lcb:+.3f}R"
              f"  → {'TUTTU' if tuttu else 'TUTMADI'}")
        yil = {}
        for t, d, R in trN:
            y = int(np.datetime64(int(t), "ms").astype("datetime64[Y]").astype(int) + 1970)
            yil.setdefault(y, []).append(R)
        print("  yıl: " + " · ".join(f"{y} {np.mean(v):+.3f}({len(v)})" for y, v in sorted(yil.items())))
        uz = [R for _, d, R in trN if d == 1]; ks = [R for _, d, R in trN if d == -1]
        print(f"  long {np.mean(uz) if uz else float('nan'):+.3f}({len(uz)}) · short {np.mean(ks) if ks else float('nan'):+.3f}({len(ks)})")
        rapor[aile] = dict(secilen=p, sinav_normal=n_, sinav_stress=s_, lcb=lcb, karar="TUTTU" if tuttu else "TUTMADI",
                           yil={str(y): [float(np.mean(v)), len(v)] for y, v in yil.items()})
    json.dump(rapor, open(os.path.join(OUT, "rapor.json"), "w"), indent=1, default=str)


main()
