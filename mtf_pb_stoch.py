"""mtf_pb_stoch.py — brief'in açıkça istediği Stoch tetiği (ek 36 hücre)."""
import itertools
import numpy as np, pandas as pd
import deployed_backtest as A
from mtf_pb_tara import COINS, TRENDS, STOPS, RRS, veri, kol_uret, tek_basina
from mtf_pb_taban import ham_taban, strip, olc

V = veri(); d = ham_taban()
tb = strip(d["donch"]) + strip(d["sqz"]) + strip(d["bb"])
T = olc(A.seat_select(tb))
rows = []
for tr, st, rr in itertools.product(TRENDS, STOPS, RRS):
    t = kol_uret(V, trend=tr, tetik="stoch", stop=st, rr=rr)
    s = tek_basina(t); C = olc(A.seat_select(tb + t))
    dy = C["yil"] - T["yil"]; kot = float((dy / T["yil"].abs()).min() * 100)
    gec = (C["kar"]-T["kar"] >= 36 and C["kotu"] >= T["kotu"]
           and C["dd"]-T["dd"] <= 2.0 and kot >= -10.0)
    rows.append({"trend": tr, "stop": f"{st[0]}{st[1]}", "rr": rr, "kol_n": s["n"],
                 "kol_kar": s["kar"], "kol_ortR": s["ortR"], "d_kar": C["kar"]-T["kar"],
                 "d_dd": C["dd"]-T["dd"], "d_kotu": C["kotu"]-T["kotu"],
                 "kotu_yil%": kot, "bar": "GECTI" if gec else ""})
df = pd.DataFrame(rows).sort_values("d_kar", ascending=False)
pd.set_option("display.width", 220)
print(f"  TABAN ${T['kar']:+.2f} · maxDD %{T['dd']:.2f} · en kötü ay %{T['kotu']:.2f}")
print(f"\n  === STOCH TETİĞİ — {len(df)} hücre, en iyi 8 ===")
print(df.head(8).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
print(f"\n  Δ$>0 olan {int((df.d_kar>0).sum())}/{len(df)} · BARI GEÇEN {int((df.bar=='GECTI').sum())}"
      f" · medyan Δ$ {df.d_kar.median():+.1f} · en iyi tek-başına ${df.kol_kar.max():+.1f}")
