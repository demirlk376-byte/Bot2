"""Bar-by-bar exit simulator mirroring the twin (PaperExchange.check_sl_tp + _enforce_max_hold).

Conventions (verified against ikiz_k25_cap25_islemler.csv):
- entry_time = open ts of entry bar i0; intended_entry = open[i0] (= close of signal bar)
- SL/TP checked on bars i0 .. i0+MH-1 (MH bars), STOP first if both touched
- max_hold exit at close of bar i0+MH-1 (verified: twin max_hold price = that close; twin's
  exit_time LABEL is close-of-exit-bar + 1h, a pure labelling lag)
- entry slippage 15.85bp (donchian/squeeze), 0 (mean_rev); exit slip 0.24bp on SL and
  max_hold (TP is a resting limit, no slip -- as in exchange.py KAYMASIZ_CIKISLAR)
- fees: entry fee_in (1bp taker, 0 for mean_rev maker per twin JSON), exit 1bp
- funding: direction-signed sum of Binance funding rates in (entry_ts, exit_ts], times entry notional
- R normalised by intended risk D = |intended_entry - sl0|  (R_net as defined in the task)
"""
import numpy as np, pandas as pd

DATA = "/home/user/Bot2/data"
SLIP_OUT = 0.24e-4
FEE_OUT = 1e-4
GEOM = {"donchian": dict(RR=2.5, MH=120, slip=15.85e-4, fee_in=1e-4),
        "squeeze":  dict(RR=2.5, MH=48,  slip=15.85e-4, fee_in=1e-4),
        "mean_rev": dict(RR=1.667, MH=48, slip=0.0,     fee_in=0.0)}


class Coin:
    def __init__(self, coin):
        d = pd.read_csv(f"{DATA}/{coin}_fut_1h.csv")
        ts = pd.to_datetime(d.ts, utc=True)
        self.ts = ts.values.astype("datetime64[s]").astype(np.int64)
        self.o, self.h, self.l, self.c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        f = pd.read_csv(f"{DATA}/{coin}_funding_bnc.csv")
        fts = pd.to_datetime(f.dt, utc=True, format="mixed").values.astype("datetime64[s]").astype(np.int64)
        cum = np.concatenate([[0.0], np.cumsum(f.rate.to_numpy(float))])
        # F(t) = sum of rates with ts <= t
        self.F_open = cum[np.searchsorted(fts, self.ts, side="right")]
        self.F_close = cum[np.searchsorted(fts, self.ts + 3600, side="right")]
        self.n = len(self.ts)
        # Wilder ATR(14) on 1h, known at the open of bar i (uses bars < i)
        pc = np.r_[np.nan, self.c[:-1]]
        tr = np.nanmax(np.vstack([self.h - self.l, np.abs(self.h - pc), np.abs(self.l - pc)]), axis=0)
        atr = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().to_numpy()
        self.atr_open = np.r_[np.nan, atr[:-1]]

    def idx(self, t_sec):
        return np.searchsorted(self.ts, t_sec)


def simulate(cn, i0, dirn, P, D, g, return_detail=False):
    """Vectorised. i0,dirn,P,D arrays (same length). Entry at reference price P (pre-slippage).
    Returns R_net (in units of D), exit code (0 sl,1 tp,2 max_hold), exit bar index."""
    RR, MH, slip, fee_in = g["RR"], g["MH"], g["slip"], g["fee_in"]
    i0 = np.asarray(i0); dirn = np.asarray(dirn, float); P = np.asarray(P, float); D = np.asarray(D, float)
    out_R = np.empty(len(i0)); out_x = np.empty(len(i0), int); out_k = np.empty(len(i0), int)
    CH = 40000
    for s in range(0, len(i0), CH):
        a = slice(s, s + CH)
        ii, dd, pp, DD = i0[a], dirn[a], P[a], D[a]
        win = ii[:, None] + np.arange(MH)[None, :]
        win = np.minimum(win, cn.n - 1)
        H, L = cn.h[win], cn.l[win]
        sl = (pp - dd * DD)[:, None]; tp = (pp + dd * RR * DD)[:, None]
        long_ = (dd > 0)[:, None]
        slh = np.where(long_, L <= sl, H >= sl)
        tph = np.where(long_, H >= tp, L <= tp)
        anyh = slh | tph
        has = anyh.any(1)
        first = np.where(has, anyh.argmax(1), MH - 1)
        rows = np.arange(len(ii))
        is_sl = has & slh[rows, first]
        is_tp = has & ~is_sl
        k = ii + first
        k = np.minimum(k, cn.n - 1)
        ep = pp * (1 + dd * slip)
        px = np.where(is_sl, sl[:, 0] * (1 - dd * SLIP_OUT),
             np.where(is_tp, tp[:, 0], cn.c[k] * (1 - dd * SLIP_OUT)))
        fund = cn.F_close[k] - cn.F_open[ii]
        pnl = dd * (px - ep) - (ep * fee_in + px * FEE_OUT) - dd * fund * ep
        out_R[a] = pnl / DD
        out_x[a] = np.where(is_sl, 0, np.where(is_tp, 1, 2))
        out_k[a] = k
    return out_R, out_x, out_k


def load_trades(path="/home/user/Bot2/ikiz_k25_cap25_islemler.csv"):
    import json
    d = pd.read_csv(path)
    s = d.strategy_scores.map(json.loads)
    d["ie"] = s.map(lambda x: x["intended_entry"])
    d["sl0"] = s.map(lambda x: x["sl0"])
    d["fee_in"] = s.map(lambda x: x.get("entry_fee_rate", 1e-4))
    d["dirn"] = np.where(d.side == "long", 1, -1)
    d["D"] = (d.ie - d.sl0).abs()
    d["stop_pct"] = d.D / d.ie
    d["R_net"] = d.pnl_usdt / (d.quantity * d.D)
    d["coin"] = d.symbol.str.split("/").str[0]
    d["et"] = pd.to_datetime(d.entry_time, utc=True)
    d["xt"] = pd.to_datetime(d.exit_time, utc=True)
    d["split"] = np.where(d.xt < pd.Timestamp("2025-01-01", tz="UTC"), "TRAIN", "TEST")
    d["w"] = np.minimum(0.035, 2.5 * d.stop_pct) / 0.035
    return d
