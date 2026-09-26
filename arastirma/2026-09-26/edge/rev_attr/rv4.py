import numpy as np, pandas as pd, pickle
from rv_load import get, cboot, RR
H = {"donchian": 120, "squeeze": 48, "mean_rev": 48}
d = get()
OH = {}
for c in d.coin.unique():
    x = pd.read_csv(f"/home/user/Bot2/data/{c}_fut_1h.csv"); x["ts"] = pd.to_datetime(x.ts, utc=True)
    x = x.drop_duplicates("ts").set_index("ts").sort_index()
    # check regular hourly grid
    gaps = (x.index.to_series().diff() != pd.Timedelta(hours=1)).sum() - 1
    tr = np.maximum(x.high - x.low, np.maximum((x.high - x.close.shift()).abs(), (x.low - x.close.shift()).abs()))
    x["atr"] = tr.ewm(alpha=1/14, adjust=False).mean()
    OH[c] = x
    if gaps: print(c, "non-hourly gaps:", gaps)
# entry bar: bar whose CLOSE time == tin  (open ts = tin - 1h)
d["i0"] = [OH[t.coin].index.get_indexer([t.tin - pd.Timedelta(hours=1)])[0] for t in d.itertuples()]
print("missing i0:", (d.i0 < 0).sum())
print("max |close(i0)/ie-1| bp:", max(abs(OH[c].close.values[i]/ie - 1)*1e4 for c, i, ie in zip(d.coin, d.i0, d.ie)))
# alt alignment: open(i0+1)
print("median |open(i0+1)/ie-1| bp:", np.median([abs(OH[c].open.values[i+1]/ie - 1)*1e4 for c, i, ie in zip(d.coin, d.i0, d.ie)]))

def sim(hi, lo, cl, i0, s, sp, rr, h, ex_off=0):
    i0 = np.asarray(i0); n = len(cl); s = np.broadcast_to(s, i0.shape).astype(float); sp = np.broadcast_to(sp, i0.shape)
    e = cl[i0]; st = sp * e; SL = e - s*st; TP = e + s*rr*st
    idx = np.minimum(i0[:, None] + np.arange(1, h+1)[None], n-1)
    Hh, Ll = hi[idx], lo[idx]
    slh = np.where(s[:, None] > 0, Ll <= SL[:, None], Hh >= SL[:, None])
    tph = np.where(s[:, None] > 0, Hh >= TP[:, None], Ll <= TP[:, None])
    B = h + 9
    fs = np.where(slh.any(1), slh.argmax(1), B); ft = np.where(tph.any(1), tph.argmax(1), B)
    why = np.where((fs < B) & (fs <= ft), 0, np.where(ft < B, 1, 2))
    last = np.minimum(i0 + h + ex_off, n-1)
    R = np.where(why == 0, -1.0, np.where(why == 1, rr, s*(cl[last]-e)/st))
    return R, why

code = d.exit_reason.map({"sl_hit": 0, "tp_hit": 1, "max_hold": 2}).values
xm = d.exit_price / (1 - d.s*0.24e-4); Rg = (d.s*(xm - d.ie)/d.stop).values
rep = np.zeros(len(d)); why0 = np.zeros(len(d), int); rep1 = np.zeros(len(d))
for j, t in enumerate(d.itertuples()):
    x = OH[t.coin]; k = t.kol
    R, w = sim(x.high.values, x.low.values, x.close.values, [t.i0], t.s, t.sp, RR[k], H[k]); rep[j] = R[0]; why0[j] = w[0]
    R1, _ = sim(x.high.values, x.low.values, x.close.values, [t.i0], t.s, t.sp, RR[k], H[k], ex_off=1); rep1[j] = R1[0]
print("exit reason agreement:", (why0 == code).mean())
mhm = code == 2
print("max_hold exit: |replay(close i0+H) - twin| mean %.4f ; |replay(close i0+H+1) - twin| mean %.4f" % (np.abs(rep[mhm]-Rg[mhm]).mean(), np.abs(rep1[mhm]-Rg[mhm]).mean()))
print("replay gross mean %.4f (H) %.4f (H+1) vs twin %.4f" % (rep.mean(), np.where(mhm, rep1, rep).mean(), Rg.mean()))
d["ratio_atr"] = [t.stop / OH[t.coin].atr.values[t.i0] for t in d.itertuples()]
print("stop/ATR14(1h) by kol:", d.groupby("kol").ratio_atr.describe()[["25%", "50%", "75%"]].round(2).to_dict())
pickle.dump((d, OH), open("rv4.pkl", "wb"))
