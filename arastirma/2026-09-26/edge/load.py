"""Shared loader: live-faithful twin trades with R decomposition and equity reconstruction."""
import json
import numpy as np
import pandas as pd

SLIP_X = 0.24e-4   # exit slippage (fraction)
FEE = 1e-4         # taker fee per side


def load(path="/home/user/Bot2/ikiz_k25_cap25_islemler.csv", bal0=10_000.0):
    d = pd.read_csv(path)
    s = d.strategy_scores.apply(json.loads)
    d["ie"] = s.apply(lambda x: x["intended_entry"])
    d["sl0"] = s.apply(lambda x: x["sl0"])
    d["kol"] = s.apply(lambda x: x["strategy"])
    d["coin"] = d.symbol.str.split("/").str[0]
    d["sg"] = np.where(d.side == "long", 1, -1)
    d["stop"] = (d.ie - d.sl0).abs()
    d["stop_pct"] = d.stop / d.ie
    d["t_in"] = pd.to_datetime(d.entry_time, utc=True, format="mixed")
    d["t_out"] = pd.to_datetime(d.exit_time, utc=True, format="mixed")
    d["hold_h"] = (d.t_out - d.t_in).dt.total_seconds() / 3600
    # ---- R decomposition (risk unit = qty * |intended_entry - sl0|) ----
    risk_usd = d.quantity * d.stop
    d["R_net"] = d.pnl_usdt / risk_usd
    exit_raw = d.exit_price / (1 - d.sg * SLIP_X)          # undo exit slippage
    d["R_gross"] = d.sg * (exit_raw - d.ie) / d.stop        # pre-slip, pre-fee, pre-funding
    d["c_slip_in"] = d.sg * (d.ie - d.entry_price) / d.stop
    d["c_slip_out"] = d.sg * (d.exit_price - exit_raw) / d.stop
    d["c_fee"] = -FEE * (d.entry_price + d.exit_price) / d.stop
    d["c_fund"] = d.R_net - (d.R_gross + d.c_slip_in + d.c_slip_out + d.c_fee)
    # ---- equity reconstruction (realised, exit order) ----
    d = d.sort_values(["t_out", "t_in"]).reset_index(drop=True)
    eq_after = bal0 + d.pnl_usdt.cumsum()
    d["eq_before"] = eq_after - d.pnl_usdt
    d["r_eq"] = d.pnl_usdt / d.eq_before
    d["logc"] = np.log1p(d.r_eq)
    # equity at entry (realised pnl of trades closed before entry) -> risk fraction actually used
    closed_cum = np.concatenate([[0.0], d.pnl_usdt.cumsum().values])
    idx = np.searchsorted(d.t_out.values, d.t_in.values, side="right")
    d["eq_entry"] = bal0 + closed_cum[idx]
    d["risk_frac"] = risk_usd / d.eq_entry
    d["split"] = np.where(d.t_out < pd.Timestamp("2025-01-01", tz="UTC"), "TRAIN", "TEST")
    d["year"] = d.t_out.dt.year
    d["month"] = d.t_out.dt.tz_localize(None).dt.to_period("M")
    d["week"] = d.t_in.dt.tz_localize(None).dt.to_period("W")
    d["win"] = d.R_net > 0
    return d
