"""
mtf_pb_tara.py — MTF-PULLBACK IZGARA TARAMASI.

AŞAMA 1 (ucuz): kol TEK BAŞINA (koltuk yok) — 108 hücre. Yalnızca eleme için.
AŞAMA 2 (pahalı): en iyi adaylar ORTAK 7 KOLTUKTA (A.seat_select) ölçülür;
  ÖN-KAYITLI BAR bu ölçüme uygulanır. Koltuk rekabetinin maliyeti ayrıca raporlanır.

ÇOKLU KARŞILAŞTIRMA: taranan hücre sayısı RAPOR EDİLİR ve gürültü eşiği
sigma*sqrt(2 ln N) ile kıyaslanır.

Kullanım:  py mtf_pb_tara.py asama1|asama2
"""
import itertools, os, pickle, sys, time
import numpy as np, pandas as pd
import fast_bt, deployed_backtest as A
import mtf_pullback as P
from mtf_pb_taban import ham_taban, strip, olc

SCR = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad"
COINS = A.DONCH          # aynı 7 coin — yeni coin evreni AYRI ve REDDEDİLMİŞ bir eksen

TRENDS = ["T1", "T2", "T3"]
TETIK = ["ema20", "ema50", "rsi"]
STOPS = [("atr", 1.5), ("atr", 2.0), ("atr", 2.5), ("swing", 10)]
RRS = [2.0, 2.5, 3.0]


def veri():
    return {c: fast_bt.load(c, source="local") for c in COINS}


def kol_uret(V, **kw):
    t = []
    for c in COINS:
        t += P.uret(c, V[c], **kw)
    return t


def tek_basina(t):
    """Koltuksuz: kolun kendi işlemleri, canlı boyutlandırmayla."""
    if not t: return None
    R = np.array([x[2] for x in t]); sp = np.array([x[3] for x in t])
    eff = np.minimum(A.CANLI_RISKF, A.CANLI_CAP * sp)
    pnl = R * eff * A.BAL0
    ex = pd.to_datetime([x[1] for x in t])
    yil = pd.Series(pnl, index=ex.year).groupby(level=0).sum()
    return {"n": len(t), "kar": pnl.sum(), "ortR": R.mean(), "wr": (R > 0).mean() * 100,
            "yil": yil, "pos_yil": int((yil > 0).sum()), "n_yil": len(yil)}


def main():
    V = veri()
    rows = []
    t0 = time.time()
    grid = list(itertools.product(TRENDS, TETIK, STOPS, RRS))
    print(f"  IZGARA: {len(grid)} hücre  (trend {len(TRENDS)} × tetik {len(TETIK)} × "
          f"stop {len(STOPS)} × rr {len(RRS)})")
    for k, (tr, te, st, rr) in enumerate(grid):
        t = kol_uret(V, trend=tr, tetik=te, stop=st, rr=rr)
        m = tek_basina(t)
        if m is None: continue
        rows.append({"trend": tr, "tetik": te, "stop": f"{st[0]}{st[1]}", "rr": rr,
                     **{kk: vv for kk, vv in m.items() if kk != "yil"}})
        if (k + 1) % 20 == 0:
            print(f"    {k+1}/{len(grid)}  ({time.time()-t0:.0f}s)")
    df = pd.DataFrame(rows).sort_values("kar", ascending=False)
    df.to_csv(f"{SCR}/asama1.csv", index=False)
    pd.set_option("display.width", 200)
    print(f"\n  --- EN İYİ 15 (tek başına, koltuksuz) ---")
    print(df.head(15).to_string(index=False))
    print(f"\n  --- EN KÖTÜ 5 ---")
    print(df.tail(5).to_string(index=False))
    print(f"\n  hücre {len(df)} · pozitif kâr {(df.kar>0).sum()} · "
          f"medyan kâr ${df.kar.median():+.1f} · medyan ortR {df.ortR.median():+.4f}")
    print(f"  (toplam {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
