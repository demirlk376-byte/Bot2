"""
mtf_pb_taban.py — taban (ankor) işlemlerini ÜRET ve DİSKE ÖNBELLEKLE.

Ankor: donchian 7 (A.gen) + squeeze 4 (A.gen) + BB/LTC hafta-sonu (A.gen_bb).
Ortak 7 koltuk (A.seat_select), boyut eff=min(CANLI_RISKF, CANLI_CAP*slp).

Kullanım:  py mtf_pb_taban.py
"""
import os, pickle, sys
import numpy as np, pandas as pd
import fast_bt, deployed_backtest as A

CACHE = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/taban.pkl"


def ham_taban():
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as f: return pickle.load(f)
    d = {"donch": [], "sqz": [], "bb": []}
    for c in A.DONCH:
        t = A.gen("donchian", fast_bt.load(c, source="local"))
        d["donch"] += [(c,) + x for x in t]
    for c in A.SQZ:
        t = A.gen("squeeze", fast_bt.load(c, source="local"))
        d["sqz"] += [(c,) + x for x in t]
    for c in A.BB_COINS:
        t = A.gen_bb(fast_bt.load(c, source="local"))
        d["bb"] += [(c,) + x for x in t]
    with open(CACHE, "wb") as f: pickle.dump(d, f)
    return d


def strip(lst):
    """(coin, entry_ns, exit_ts, R, slp) -> (entry_ns, exit_ts, R, slp)"""
    return [x[1:] for x in lst]


def olc(tk, bal=None):
    bal = A.BAL0 if bal is None else bal
    R = np.array([r for _, r, _ in tk]); sp = np.array([s for _, _, s in tk])
    ex = pd.to_datetime([x for x, _, _ in tk])
    eff = np.minimum(A.CANLI_RISKF, A.CANLI_CAP * sp)
    pnl = R * eff * bal
    eq = bal + np.cumsum(pnl)
    per = ex.tz_localize(None).to_period("M")
    ay = pd.Series(pnl, index=per).groupby(level=0).sum() / bal * 100
    yil = pd.Series(pnl, index=ex.year).groupby(level=0).sum()
    return {"n": len(tk), "kar": pnl.sum(), "dd": A.maxdd(np.concatenate([[bal], eq])),
            "kotu": ay.min(), "wr": (R > 0).mean() * 100, "ortR": R.mean(),
            "ay": ay, "yil": yil, "pnl": pnl, "ex": ex, "R": R}


if __name__ == "__main__":
    d = ham_taban()
    print(f"  ham: donch {len(d['donch'])} + sqz {len(d['sqz'])} + bb {len(d['bb'])}")
    allt = strip(d["donch"]) + strip(d["sqz"]) + strip(d["bb"])
    tk = A.seat_select(allt)
    m = olc(tk)
    print(f"  TABAN {m['n']} işlem · ${m['kar']:+.2f} · maxDD %{m['dd']:.2f} · "
          f"en kötü ay %{m['kotu']:.2f} · WR %{m['wr']:.1f} · ortR {m['ortR']:+.4f}")
    print("  yıl-yıl:", {int(k): round(v, 1) for k, v in m["yil"].items()})
    print(f"  ANKOR BEKLENTİ: 1579 / +1755.21 / 27.98 / -26.38")
