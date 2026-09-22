"""
ikiz_ham_rapor.py — bir IKIZ kosusunun HAM karnesi.

NEDEN: 60 filtre denendi, hepsi elendi. Filtre eklemeye devam etmek yerine
EDGE'IN NEREDE KAZANIP NEREDE KAYBETTIGINI gormek gerekiyor. Bu arac tek bir
kosunun tam dokumunu cikarir: kol x yon x cikis nedeni.

Kullanim:  py ikiz_ham_rapor.py [veritabani]
"""
import json
import os
import sqlite3
import sys

import numpy as np
import pandas as pd

KOK = os.path.dirname(os.path.abspath(__file__))
TF = {"donchian": "4h kanal (1h dongusunden)", "squeeze": "1h (4h MTF teyitli)",
      "mean_rev": "1h BB"}


def oku(yol):
    c = sqlite3.connect(yol, timeout=60)
    try:
        d = pd.read_sql(
            "SELECT symbol,side,entry_price,exit_price,sl_price,tp_price,"
            "quantity,entry_time,exit_time,pnl_usdt,exit_reason,strategy_scores "
            "FROM trades WHERE exit_time IS NOT NULL", c)
    finally:
        c.close()
    d["kol"] = d.strategy_scores.apply(
        lambda s: (json.loads(s or "{}") or {}).get("strategy", "?"))
    sl0 = d.strategy_scores.apply(
        lambda s: (json.loads(s or "{}") or {}).get("sl0"))
    taban = sl0.where(sl0.notna(), d.sl_price).astype("float64")
    d["giris"] = pd.to_datetime(d.entry_time, utc=True, format="mixed")
    d["cikis"] = pd.to_datetime(d.exit_time, utc=True, format="mixed")
    d["yon"] = np.where(d.side.str.lower().str.startswith("l"), 1, -1)
    d["Rmes"] = (d.entry_price - taban).abs()
    d = d[d.Rmes > 0].copy()
    d["R"] = d.yon * (d.exit_price - d.entry_price) / d.Rmes
    d["saat"] = (d.cikis - d.giris).dt.total_seconds() / 3600.0
    return d.sort_values("cikis").reset_index(drop=True)


def maxdd_R(g):
    """Kapanis sirasina gore kumulatif R egrisinde en derin dusus (R cinsinden)."""
    e = g.R.cumsum().to_numpy()
    if not len(e):
        return 0.0
    return float(np.max(np.maximum.accumulate(np.concatenate([[0.0], e]))
                        - np.concatenate([[0.0], e])))


def karne(g, ad, girinti=""):
    if len(g) < 3:
        print(f"{girinti}{ad:<22s} n={len(g)}  (yetersiz)")
        return
    kaz, kay = g[g.R > 0], g[g.R <= 0]
    brut_k = kaz.R.sum()
    brut_z = -kay.R.sum()
    pf = brut_k / brut_z if brut_z > 0 else float("inf")
    ust = g.exit_reason.value_counts(normalize=True) * 100
    print(f"{girinti}{ad:<22s}"
          f"n={len(g):>5d}  WR%{(g.R>0).mean()*100:>5.1f}  PF {pf:>5.2f}  "
          f"beklenti {g.R.mean():>+7.4f}R  netR {g.R.sum():>+8.1f}  "
          f"maxDD {maxdd_R(g):>6.1f}R  "
          f"ortKaz {kaz.R.mean() if len(kaz) else 0:>+5.2f}  "
          f"ortKay {kay.R.mean() if len(kay) else 0:>+5.2f}  "
          f"TP%{ust.get('tp_hit',0):>4.1f} SL%{ust.get('sl_hit',0):>4.1f} "
          f"MH%{ust.get('max_hold',0):>4.1f}  "
          f"sure {g.saat.median():>5.0f}sa")


def main():
    yol = sys.argv[1] if len(sys.argv) > 1 else os.path.join(KOK, "ikiz_duzeltilmis.db")
    if not os.path.exists(yol):
        print(f"veritabani yok: {yol}"); return
    d = oku(yol)
    print(f"\n{'='*150}")
    print(f"=== HAM KARNE · {os.path.basename(yol)} · {len(d)} islem · "
          f"{d.giris.min().date()} -> {d.cikis.max().date()} ===")
    print(f"  R = giris ile BASLANGIC stop'u arasi. netR/maxDD sabit-kesir "
          f"(boyut etkisi yok). sure = ortanca tutus.")
    print(f"{'='*150}")
    karne(d, "TUMU")
    print(f"\n  --- KOL BAZINDA ---")
    for k, g in d.groupby("kol"):
        karne(g, k, "  ")
        print(f"      zaman dilimi: {TF.get(k,'?')}")
        for y, ad in ((1, "LONG"), (-1, "SHORT")):
            karne(g[g.yon == y], ad, "      ")
    print(f"\n  --- CIKIS NEDENI BAZINDA (tum kollar) ---")
    for r, g in d.groupby("exit_reason"):
        karne(g, r, "  ")
    print(f"\n  --- YIL BAZINDA ---")
    for y, g in d.groupby(d.cikis.dt.year):
        karne(g, str(y), "  ")
    print(f"{'='*150}\n")


if __name__ == "__main__":
    main()
