import sys; sys.path.insert(0, "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/edge")
import numpy as np, pandas as pd
from sim import *

d = load_trades()
coins = {c: Coin(c) for c in d.coin.unique()}
d["simR"] = np.nan; d["simX"] = -1; d["simXT_s"] = 0
for (c, kol), g in d.groupby(["coin", "kol"]):
    cn = coins[c]
    t = g.et.values.astype("datetime64[s]").astype(np.int64)
    i0 = cn.idx(t)
    assert (cn.ts[i0] == t).all(), (c, (cn.ts[i0] != t).sum())
    gg = dict(GEOM[kol]);
    R, x, k = simulate(cn, i0, g.dirn.values, g.ie.values, g.D.values, gg)
    d.loc[g.index, "simR"] = R; d.loc[g.index, "simX"] = x
    d.loc[g.index, "simXT_s"] = cn.ts[k] + 3600
    # sanity: open of entry bar vs intended entry
    d.loc[g.index, "open_vs_ie_bp"] = (cn.o[i0] / g.ie.values - 1) * 1e4

d["simXT"] = pd.to_datetime(d.simXT_s, unit="s", utc=True)
code = {"sl_hit": 0, "tp_hit": 1, "max_hold": 2}
d["twX"] = d.exit_reason.map(code)
d.to_pickle("/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/edge/calib.pkl")
print("open vs intended bp:", d.open_vs_ie_bp.abs().describe().round(3).to_dict())
print("fee_in by kol:", d.groupby("kol").fee_in.unique().to_dict())
for name, g in [("ALL", d)] + list(d.groupby("kol")) + list(d.groupby("split")):
    m = g.simX == g.twX
    tm = (g.simXT == g.xt)
    print(f"{name:9s} n={len(g):4d}  twin R_net={g.R_net.mean():+.4f}  sim R={g.simR.mean():+.4f}  "
          f"corr={np.corrcoef(g.R_net, g.simR)[0,1]:.4f}  exit-type match={m.mean()*100:5.1f}%  "
          f"exit-time match={tm.mean()*100:5.1f}%  |dR|>0.05: {(np.abs(g.R_net-g.simR)>0.05).mean()*100:.1f}%")
print(pd.crosstab(d.exit_reason, d.simX))
mm = d[d.simX != d.twX]
print(mm[["coin", "kol", "side", "entry_time", "exit_time", "simXT", "exit_reason", "simX", "R_net", "simR"]].head(30).to_string())
dt = (d.simXT - d.xt).dt.total_seconds() / 3600
print("exit time diff hours:", dt.value_counts().head(10).to_dict())
