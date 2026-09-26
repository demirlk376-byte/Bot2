import json, numpy as np, pandas as pd
RR = {"donchian": 2.5, "squeeze": 2.5, "mean_rev": 5/3}
def get(path="/home/user/Bot2/ikiz_k25_cap25_islemler.csv"):
    d = pd.read_csv(path)
    j = d.strategy_scores.map(json.loads)
    d["ie"] = j.map(lambda x: x["intended_entry"]); d["sl0"] = j.map(lambda x: x["sl0"])
    d["atr"] = j.map(lambda x: x["atr"]); d["strat"] = j.map(lambda x: x["strategy"])
    d["coin"] = d.symbol.str.replace("/USDT:USDT", "", regex=False)
    d["s"] = d.side.map({"long": 1, "short": -1})
    d["stop"] = (d.ie - d.sl0).abs(); d["sp"] = d.stop / d.ie
    d["tin"] = pd.to_datetime(d.giris, utc=True); d["tout"] = pd.to_datetime(d.cikis, utc=True)
    d["Rn"] = d.pnl_usdt / (d.quantity * d.stop)
    d = d.sort_values(["tout", "tin"], kind="mergesort").reset_index(drop=True)
    eq = 1e4 + d.pnl_usdt.cumsum(); d["eqb"] = eq - d.pnl_usdt
    d["lg"] = np.log(eq / d.eqb)
    d["wk"] = (d.tin.dt.tz_convert(None) - pd.Timestamp("2023-01-02")).dt.days // 7
    d["mo"] = d.tout.dt.strftime("%Y-%m"); d["mo_in"] = d.tin.dt.strftime("%Y-%m")
    d["yr"] = d.tout.dt.year
    d["split"] = np.where(d.tout < pd.Timestamp("2025-01-01", tz="UTC"), "TRAIN", "TEST")
    d["hold"] = (d.tout - d.tin).dt.total_seconds() / 3600
    return d
def cboot(x, cl, reps=5000, seed=1):
    r = np.random.default_rng(seed); x = np.asarray(x, float)
    u, inv = np.unique(np.asarray(cl), return_inverse=True)
    S = np.bincount(inv, weights=x); C = np.bincount(inv).astype(float)
    ii = r.integers(0, len(u), (reps, len(u)))
    m = S[ii].sum(1) / C[ii].sum(1)
    return m
