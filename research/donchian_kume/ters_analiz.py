"""Ters küme filtresi — TERS_ON_KAYIT.md. Kullanım: python ters_analiz.py <ikiz_eski.db>"""
import json, sqlite3, sys
import numpy as np, pandas as pd

BIT = pd.Timestamp("2023-04-07", tz="UTC")
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
d = pd.read_sql("select symbol,side,entry_price,quantity,entry_time,exit_time,pnl_usdt,strategy_scores "
                "from trades where pnl_usdt is not null", c)
d["kol"] = d.strategy_scores.map(lambda s: json.loads(s).get("strategy"))
d = d[d.kol == "donchian"].copy()
d["sl0"] = d.strategy_scores.map(lambda s: json.loads(s)["sl0"])
d["R"] = d.pnl_usdt / ((d.entry_price - d.sl0).abs() * d.quantity)
d["t"] = pd.to_datetime(d.entry_time, format="ISO8601", utc=True)
d["z"] = pd.to_datetime(d.exit_time, format="ISO8601", utc=True)
d = d[d.t < BIT].sort_values("t").reset_index(drop=True)
d["mum"] = d.t.dt.floor("4h")
d["kume"] = d.groupby("mum").symbol.transform("size")
print(f"test dönemi {d.t.min().date()} → {d.t.max().date()} · donchian işlemi {len(d)} · ort R {d.R.mean():+.3f}")
for k, g in d.groupby(d.kume.clip(upper=4)):
    print(f"  küme {'4+' if k == 4 else k}: işlem {len(g):>3} · ayrı an {g.mum.nunique():>3} · ort R {g.R.mean():+.3f}"
          f" · ΣR {g.R.sum():+.1f} · long/short {(g.side == 'long').sum()}/{(g.side == 'short').sum()}")


def hesap(sec):
    eq, seri = 1.0, []
    for _, r in sec.sort_values("z").iterrows():
        eq *= 1 + 0.035 * r.R
        seri.append((r.z, eq))
    s = pd.Series([e for _, e in seri], index=[t for t, _ in seri]).resample("ME").last().ffill()
    return eq, float((1 - s / s.cummax()).max() * 100)


def ust_sinir(x, n=10_000, seed=20261005):
    if len(x) == 0:
        return float("nan")
    hafta = (x.t.dt.tz_localize(None).dt.to_period("W")).astype(str)
    g = x.groupby(hafta).R.agg(["sum", "size"]).to_numpy(float)
    rng = np.random.default_rng(seed)
    o = [(lambda s: s[0] / s[1])(g[rng.integers(0, len(g), len(g))].sum(axis=0)) for _ in range(n)]
    return float(np.percentile(o, 97.5))


tx, tdd = hesap(d)
print(f"\n{'varyant':<7}{'işlem':>6}{'ΣR':>8}{'çarpan':>9}{'maxDD%':>8}{'atlanan':>8}{'atl.ortR':>10}{'atl.üst95':>11}  karar")
print(f"{'TABAN':<7}{len(d):>6}{d.R.sum():>+8.1f}{tx:>9.2f}{tdd:>8.1f}")
for K in (3, 4):
    kal, atl = d[d.kume < K], d[d.kume >= K]
    x, dd = hesap(kal)
    ub = ust_sinir(atl)
    iyi = kal.R.sum() > d.R.sum() and dd <= tdd and len(atl) and atl.R.mean() < 0 and ub < 0.10
    print(f"{'ATLA' + str(K):<7}{len(kal):>6}{kal.R.sum():>+8.1f}{x:>9.2f}{dd:>8.1f}{len(atl):>8}"
          f"{(atl.R.mean() if len(atl) else float('nan')):>+10.3f}{ub:>+11.3f}  {'İYİ' if iyi else 'ELENDİ'}")
