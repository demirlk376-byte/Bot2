"""_hyb_cache.py — ham sinyalleri bir kez uretip pickle'a yazar (kitap + fade izgarasi)."""
import os, pickle, sys
import numpy as np, pandas as pd
import fast_bt
import deployed_backtest as DB
from indicators import atr as atr_fn, adx as adx_fn

OUT = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/raw.pkl"
FREE = ["AAVE", "ALGO", "ATOM", "AVAX", "BTC", "DOT", "ETC", "LINK", "VET", "XMR"]
FEE = 0.0001
CHANNEL, SL_A, MH = 40, 2.0, 30


def fade_gen(m, adx_max, rr, tf="4h", channel=CHANNEL, sl_a=SL_A, mh=MH):
    """fade_test.gen'in BIREBIR kopyasi ama deployed_backtest.gen ile ayni tuple formati:
       (entry_ns, exit_ts, R, sl_pct)  -> seat_select'e dogrudan girer."""
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    ch_hi = d["high"].rolling(channel).max().shift(1).values
    ch_lo = d["low"].rolling(channel).min().shift(1).values
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    out = []; occ = -1
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0 or i <= occ: continue
        if not (np.isfinite(ch_hi[i]) and np.isfinite(ch_lo[i])): continue
        ax = adx_ser[i]
        if not np.isfinite(ax) or ax >= adx_max: continue
        c = cl[i]
        if c > ch_hi[i]: d_ = -1
        elif c < ch_lo[i]: d_ = +1
        else: continue
        e = c; sld = sl_a * a; slp = e - d_ * sld; tp = e + d_ * rr * sld
        ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * FEE * e / sld
        out.append((idx[i].value, idx[j], R, sld / e)); occ = j
    return out


def main():
    src = "local"
    book = {}
    for c in DB.DONCH: book[("donchian", c)] = DB.gen("donchian", fast_bt.load(c, source=src))
    for c in DB.SQZ:   book[("squeeze", c)]  = DB.gen("squeeze",  fast_bt.load(c, source=src))
    for c in DB.BB_COINS: book[("bb", c)]    = DB.gen_bb(fast_bt.load(c, source=src))
    print("kitap ham:", sum(len(v) for v in book.values()), flush=True)

    ms = {c: fast_bt.load(c, source=src) for c in FREE}
    fade = {}
    for adx_max in (15, 20, 25):
        for rr in (1.0, 1.5, 2.5):
            for c in FREE:
                fade[(adx_max, rr, c)] = fade_gen(ms[c], adx_max, rr)
            print(f"fade adx<{adx_max} rr{rr}: "
                  f"{sum(len(fade[(adx_max,rr,c)]) for c in FREE)}", flush=True)
    with open(OUT, "wb") as f:
        pickle.dump({"book": book, "fade": fade, "free": FREE}, f)
    print("yazildi", OUT)


if __name__ == "__main__":
    main()
