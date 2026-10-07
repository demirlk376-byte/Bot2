#!/usr/bin/env python3
"""Likidite filtresi (donchian girisleri) -- FINAL reconciled implementation.

Spec: /home/user/sweep/research/likidite_filtre/ON_KAYIT.md (followed exactly; thresholds
and criteria unchanged).  Inputs are opened read-only (sqlite immutable=1); the script
writes only sonuc.json next to itself.  Run with:  python3 -I analiz.py

Reconciled disagreement (A=13 vs B=10 no-feature trades in L1|BAGIMSIZ)
-----------------------------------------------------------------------
Three BAGIMSIZ ICP trades (2022-10-11 00:00, 2022-10-12 16:00, 2022-11-08 20:00).  Binance
ICPUSDT-perp did not trade 2022-06-10 10:00 .. 2022-08-31 23:00: the 1h file holds 1982
forward-filled placeholder bars there (O=H=L=C=6.44, volume=0), then has no rows at all
2022-09-01 .. 2022-09-26.  These placeholder bars are not market observations ("veri"):
counting them, B obtained median q_d = 0 and LQ = +inf for all three (kept, counted as having a
feature -> 10).  Excluding them (A), the 90-day baseline of each trade has only 6-34 real full
days < 60 required, so per spec ("en az 60 gun veri; yoksa filtre uygulanmaz, islem kalir") the
filter is not applied: the trades are KEPT and counted as no-feature -> 13.  (Counting placeholder
days as data but treating x/0 as undefined would give 12: one of the three then gets a finite
LQ = 8.29 whose baseline median is dragged down by 29 fake zero days -- an artefact.)
Skip/keep decisions -- hence every sumR / maxDD / bootstrap value and every verdict -- are
identical under all of these conventions (asserted below); only n_no_feature and the LQ
quintile table change.

Windows: calendar (L = last UTC day ended <= E; 7-day window L-6..L, 90-day window
L-96..L-7, at least 60 full days with data in the 90-day window).  A "full day" is a UTC day
that ended at or before E with all 24 hourly bars present (every bar then has ts+1h <= E).
B's row-based reading ("last 7 available full days / 90 before them") is reported as a
sensitivity only.
"""
import json
import math
import os
import sqlite3

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------
# Paths (all read-only inputs)
# ----------------------------------------------------------------------------
SCR = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad"
DB_KESIF = f"{SCR}/ikiz_kanit/ikiz_gercek.db"
DB_BAGIMSIZ = f"{SCR}/ikiz_kanit/ikiz_eski.db"
H1_KESIF = "/tmp/claude-0/canli_wt/data/{coin}_fut_1h.csv"
H1_BAGIMSIZ = f"{SCR}/eski_kos/data/{{coin}}_fut_1h.csv"
BOOK = "/home/user/sweep/research_data/kalabalik/veri/{coin}_bookdepth_5m.csv.gz"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
IMPL_A = f"{SCR}/likidite_implA/results.json"
IMPL_B = f"{SCR}/likidite_implB/sonuc.json"

# ----------------------------------------------------------------------------
# Constants from the spec (unchanged)
# ----------------------------------------------------------------------------
EPOCH = pd.Timestamp("1970-01-01", tz="UTC")
MS = pd.Timedelta(milliseconds=1)
H1 = pd.Timedelta(hours=1)
D1 = pd.Timedelta(days=1)

KESIF_LO = pd.Timestamp("2023-04-07", tz="UTC")      # KESIF entries >= 2023-04-07
KESIF_HI = pd.Timestamp("2026-07-19", tz="UTC")      # ... through 2026-07-18 inclusive
BAG_HI = pd.Timestamp("2023-04-07", tz="UTC")        # BAGIMSIZ entries < 2023-04-07
L2_HI = pd.Timestamp("2026-01-08", tz="UTC")         # L2 window entries < 2026-01-08
L2_SPLIT = pd.Timestamp("2024-09-01", tz="UTC")      # halves: < / >= 2024-09-01

RISK = 0.035
N_BOOT = 10000
SEED = 20261007
N7, N90, MIN90 = 7, 90, 60
BOOK_MAX_AGE_MS = 15 * 60 * 1000

L1_THR = {"L1a": 1.00, "L1b": 0.75}
L2_THR = {"L2a": 0.0, "L2b": -0.10}


def to_ms(t):
    """tz-aware datetime(s) -> int ms since epoch, independent of datetime resolution."""
    return (t - EPOCH) // MS


# ----------------------------------------------------------------------------
# Trades
# ----------------------------------------------------------------------------
def load_trades(db, lo, hi):
    con = sqlite3.connect(f"file:{db}?immutable=1", uri=True)
    df = pd.read_sql_query(
        "SELECT id, symbol, side, entry_price, quantity, entry_time, exit_time, "
        "pnl_usdt, strategy_scores FROM trades", con)
    con.close()
    sc = df["strategy_scores"].map(lambda s: json.loads(s) if s else {})
    df["strategy"] = sc.map(lambda d: d.get("strategy"))
    df["sl0"] = sc.map(lambda d: d.get("sl0"))
    info = {"rows_total": int(len(df)),
            "donchian_all": int((df["strategy"] == "donchian").sum()),
            "donchian_pnl_null": int(((df["strategy"] == "donchian") & df["pnl_usdt"].isna()).sum())}
    d = df[(df["strategy"] == "donchian") & df["pnl_usdt"].notna()].copy()
    d["E"] = pd.to_datetime(d["entry_time"], utc=True)
    d["X"] = pd.to_datetime(d["exit_time"], utc=True)
    info["donchian_closed"] = int(len(d))
    d = d[(d["E"] >= lo) & (d["E"] < hi)].copy()
    info["donchian_in_window"] = int(len(d))
    assert d["X"].notna().all() and (d["X"] >= d["E"]).all()
    assert d["sl0"].notna().all()
    assert set(d["side"]) <= {"long", "short"}
    # E is a 4h bar close instant
    assert ((d["E"].dt.minute == 0) & (d["E"].dt.second == 0) & (d["E"].dt.hour % 4 == 0)).all()
    risk = (d["entry_price"].astype(float) - d["sl0"].astype(float)).abs() * d["quantity"].astype(float)
    assert (risk > 0).all()
    d["R"] = d["pnl_usdt"].astype(float) / risk
    d["dir"] = np.where(d["side"] == "long", 1, -1)
    d["coin"] = d["symbol"].str.split("/").str[0]
    d["E_ms"] = to_ms(d["E"]).astype("int64")
    d = d.sort_values(["E", "symbol", "id"]).reset_index(drop=True)
    info["E_min"], info["E_max"] = str(d["E"].min()), str(d["E"].max())
    return d, info


# ----------------------------------------------------------------------------
# L1: daily cash volume and LQ
# ----------------------------------------------------------------------------
def load_hourly(path):
    h = pd.read_csv(path)
    ts = pd.to_datetime(h["ts"], utc=True)                       # bar OPEN time
    assert ts.is_unique and ts.is_monotonic_increasing, path
    assert ((ts.dt.minute == 0) & (ts.dt.second == 0)).all(), path
    out = pd.DataFrame({"ts": ts, "vol": h["volume"].astype(float), "close": h["close"].astype(float),
                        "qv": h["volume"].astype(float) * h["close"].astype(float),
                        "flat": (h["open"] == h["high"]) & (h["high"] == h["low"]) & (h["low"] == h["close"])})
    out["ts_ms"] = to_ms(out["ts"]).astype("int64")
    return out


def day_groups(h):
    """Per-UTC-day aggregates.  nreal = bars with volume > 0."""
    day = h["ts"].dt.floor("D")
    return h.assign(real=(h["vol"] > 0).astype(int)).groupby(day).agg(
        q=("qv", "sum"), n=("qv", "size"), nreal=("real", "sum"), tsmax_ms=("ts_ms", "max"))


def valid_days(g, rule):
    """Which days count as full days with data.
    day0_missing (PRIMARY): 24 hourly bars and q_d > 0 (all-zero placeholder day = no data)
    zero_data             : 24 hourly bars (placeholder zero days count as q_d = 0)
    bar0_missing          : 24 hourly bars with volume > 0 (any zero-volume bar -> partial day)"""
    if rule == "day0_missing":
        return (g["n"] == 24) & (g["q"] > 0)
    if rule == "zero_data":
        return g["n"] == 24
    if rule == "bar0_missing":
        return g["nreal"] == 24
    raise ValueError(rule)


def daily_table(h, end_day, rule):
    """Calendar table indexed by day D (= L, the last full day used).
    mean7 = mean q_d over valid days in [D-6, D];
    med90 = median q_d over valid days in [D-96, D-7] (needs >= 60 valid days)."""
    g = day_groups(h)
    valid = valid_days(g, rule)
    cal = pd.date_range(g.index.min(), max(g.index.max(), end_day), freq="D")
    q = g["q"].where(valid).reindex(cal)
    ok = q.notna().astype(float)
    t = pd.DataFrame(index=cal)
    t["mean7"] = q.rolling(N7, min_periods=1).mean()
    t["cnt7"] = ok.rolling(N7, min_periods=1).sum()
    t["med90"] = q.rolling(N90, min_periods=MIN90).median().shift(N7)
    t["cnt90"] = ok.rolling(N90, min_periods=1).sum().shift(N7)
    # latest bar open-ts (ms) that can enter the feature (for the no-future check)
    t["last_bar_ms"] = g["tsmax_ms"].where(valid).reindex(cal).rolling(N7, min_periods=1).max()
    return t


def lq_calendar(trades, hourly, rule="day0_missing", den0="undefined"):
    """Vectorised calendar LQ.  den0: 'undefined' (x/0 -> no feature) or 'inf' (B's convention)."""
    end_day = (trades["E"] - D1).dt.floor("D").max()
    parts = []
    for coin, grp in trades.groupby("coin"):
        tab = daily_table(hourly[coin], end_day, rule)
        L = (grp["E"] - D1).dt.floor("D")                       # last UTC day ended <= E
        assert ((L + D1) <= grp["E"]).all() and ((L + 2 * D1) > grp["E"]).all()
        sub = tab.reindex(pd.DatetimeIndex(L))
        sub.index = grp.index
        parts.append(sub)
    f = pd.concat(parts).reindex(trades.index)
    has = (f["cnt90"] >= MIN90) & (f["cnt7"] >= 1) & f["med90"].notna() & f["mean7"].notna()
    with np.errstate(divide="ignore", invalid="ignore"):
        lq = (f["mean7"] / f["med90"]).where(has)
    if den0 == "undefined":
        lq = lq.where(~(f["med90"] <= 0))
    else:
        lq = lq.where(~(f["mean7"].eq(0) & f["med90"].eq(0)))   # 0/0 -> no feature; x/0 -> +inf
    used = lq.notna()
    # NO FUTURE DATA: every hourly bar that enters the feature satisfies ts + 1h <= E
    assert (f.loc[used, "last_bar_ms"] + 3_600_000 <= trades.loc[used, "E_ms"]).all(), "future data in L1"
    return lq, f


def lq_brute(trades, hourly, rule="day0_missing"):
    """Per-trade brute force (independent of rolling/shift logic); x/0 -> no feature."""
    out = np.full(len(trades), np.nan)
    for i, (coin, E) in enumerate(zip(trades["coin"], trades["E"])):
        h = hourly[coin]
        known = h[h["ts"] + H1 <= E]
        assert (known["ts"] + H1 <= E).all()
        if known.empty:
            continue
        g = day_groups(known)
        g = g[g.index + D1 <= E]                                # day ended by E
        g = g[valid_days(g, rule)]
        L = (E - D1).floor("D")
        w7 = g[(g.index >= L - 6 * D1) & (g.index <= L)]["q"]
        w90 = g[(g.index >= L - 96 * D1) & (g.index <= L - 7 * D1)]["q"]
        if len(w90) >= MIN90 and len(w7) >= 1 and w90.median() > 0:
            out[i] = w7.mean() / w90.median()
    return pd.Series(out, index=trades.index)


def lq_rowbased(trades, hourly, zero_is_data):
    """SENSITIVITY (B's primary reading): last 7 available full days / median of the up-to-90
    available full days before them (needs >= 7+60 full days); median 0 -> +inf (B)."""
    out = np.full(len(trades), np.nan)
    for i, (coin, E) in enumerate(zip(trades["coin"], trades["E"])):
        h = hourly[coin]
        known = h[h["ts"] + H1 <= E]
        g = known.groupby(known["ts"].dt.floor("D"))["qv"].agg(["sum", "size"])
        g = g[g.index + D1 <= E]
        keep = g["size"] == 24
        if not zero_is_data:
            keep &= g["sum"] > 0
        s = g[keep]["sum"]
        if len(s) < N7 + MIN90:
            continue
        m7, m90 = s.iloc[-N7:].mean(), s.iloc[-(N7 + N90):-N7].median()
        out[i] = m7 / m90 if m90 > 0 else (np.inf if m7 > 0 else np.nan)
    return pd.Series(out, index=trades.index)


# ----------------------------------------------------------------------------
# L2: order-book imbalance
# ----------------------------------------------------------------------------
def l2_feature(trades):
    s = pd.Series(np.nan, index=trades.index)
    age = pd.Series(np.nan, index=trades.index)
    for coin, grp in trades.groupby("coin"):
        b = pd.read_csv(BOOK.format(coin=coin), usecols=["t_kapanis", "imb1"])
        assert b["imb1"].notna().all()
        t = b["t_kapanis"].to_numpy(dtype="int64")
        imb = b["imb1"].to_numpy(dtype=float)
        assert np.all(np.diff(t) > 0)
        e = grp["E_ms"].to_numpy(dtype="int64")
        idx = np.searchsorted(t, e, side="right") - 1           # last t_kapanis <= E
        has = idx >= 0
        ti = np.where(has, t[np.clip(idx, 0, None)], np.iinfo(np.int64).min)
        # NO FUTURE DATA: chosen record closed at or before E, and the next one is after E
        assert np.all(ti[has] <= e[has])
        nxt = np.clip(idx + 1, 0, len(t) - 1)
        assert np.all((idx + 1 >= len(t)) | (t[nxt] > e))
        a = np.where(has, (e - ti) / 60000.0, np.nan)
        ok = has & ((e - ti) <= BOOK_MAX_AGE_MS)
        v = np.where(ok, imb[np.clip(idx, 0, None)], np.nan)
        s.loc[grp.index] = v * grp["dir"].to_numpy()
        age.loc[grp.index] = a
        # independent cross-check: merge_asof (backward, exact match allowed, 15-min tolerance)
        left = pd.DataFrame({"k": e, "j": np.arange(len(e))}).sort_values("k")
        right = pd.DataFrame({"k": t, "imb1": imb})
        mm = pd.merge_asof(left, right, on="k", direction="backward", allow_exact_matches=True,
                           tolerance=BOOK_MAX_AGE_MS).sort_values("j")["imb1"].to_numpy()
        assert np.array_equal(np.isnan(mm), np.isnan(v)) and np.array_equal(mm[~np.isnan(mm)], v[~np.isnan(v)])
    return s, age


# ----------------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------------
def max_dd(df):
    """eq *= 1 + 0.035 R in exit order; month-end last value (ffill); prepend 1.0 at the
    month-end before the first exit; maxDD = max(1 - s/cummax) * 100."""
    if len(df) == 0:
        return 0.0
    d = df.sort_values(["X", "E", "id"], kind="stable")
    eq = np.cumprod(1.0 + RISK * d["R"].to_numpy())
    s = pd.Series(eq, index=pd.DatetimeIndex(d["X"]))
    m = s.resample("ME").last().ffill()
    start = pd.Series([1.0], index=pd.DatetimeIndex([m.index[0] - pd.offsets.MonthEnd(1)]))
    m = pd.concat([start, m])
    assert m.index.is_monotonic_increasing
    return float((1.0 - m / m.cummax()).max() * 100.0)


def max_dd_loop(df):
    """Independent check of max_dd: plain python month loop."""
    if len(df) == 0:
        return 0.0
    rows = sorted(zip(df["X"], df["R"]), key=lambda x: x[0])
    first = rows[0][0]
    y, mth = first.year, first.month
    last = rows[-1][0]
    eq, i, peak, dd = 1.0, 0, 1.0, 0.0
    while (y, mth) <= (last.year, last.month):
        while i < len(rows) and (rows[i][0].year, rows[i][0].month) == (y, mth):
            eq *= 1.0 + RISK * rows[i][1]
            i += 1
        peak = max(peak, eq)
        dd = max(dd, 1.0 - eq / peak)
        y, mth = (y + 1, 1) if mth == 12 else (y, mth + 1)
    assert i == len(rows)
    return dd * 100.0


def boot_mean(df):
    if len(df) == 0:
        return float("nan"), float("nan"), float("nan"), 0
    iso = df["E"].dt.isocalendar()
    key = iso["year"].astype("int64") * 100 + iso["week"].astype("int64")
    g = pd.DataFrame({"k": key.to_numpy(), "R": df["R"].to_numpy()}).groupby("k")["R"].agg(["sum", "size"])
    sums, cnts = g["sum"].to_numpy(), g["size"].to_numpy().astype(float)
    W = len(g)
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, W, size=(N_BOOT, W))
    means = sums[idx].sum(axis=1) / cnts[idx].sum(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(sums.sum() / cnts.sum()), float(lo), float(hi), W


def make_row(variant, window, base, feat, thr):
    nofeat = feat.isna().to_numpy()
    skip = ((feat < thr) & feat.notna()).to_numpy()
    kept, sk = base[~skip], base[skip]
    assert len(kept) + len(sk) == len(base)
    assert not np.any(skip & nofeat)
    mr, lo, hi, W = boot_mean(sk)
    r = {"variant": variant, "window": window,
         "n_base": int(len(base)), "n_kept": int(len(kept)), "n_skipped": int(len(sk)),
         "n_no_feature": int(nofeat.sum()),
         "sumR_base": float(base["R"].sum()), "sumR_kept": float(kept["R"].sum()),
         "dd_base": max_dd(base), "dd_kept": max_dd(kept),
         "skipped_meanR": mr, "skipped_ci_lo": lo, "skipped_ci_hi": hi, "skipped_weeks": W}
    for k, dd in (("dd_base", max_dd_loop(base)), ("dd_kept", max_dd_loop(kept))):
        assert abs(r[k] - dd) < 1e-9, (variant, window, k, r[k], dd)
    return r


def l1_rows(K, B, fK, fB, tag=""):
    rows = []
    for v, thr in L1_THR.items():
        for w, T, f in (("KESIF", K, fK), ("BAGIMSIZ", B, fB)):
            rows.append(make_row(v + tag, w, T, f, thr))
    return rows


def l1_verdicts(rows):
    out = {}
    for v in L1_THR:
        rs = [r for r in rows if r["variant"].startswith(v)]
        assert len(rs) == 2
        ok = all(r["sumR_kept"] > r["sumR_base"] and r["dd_kept"] <= r["dd_base"] + 1.0 for r in rs)
        out[v] = "IYI" if ok else "ELENDI"
    return out


def quintile_table(x, R, E, ids, label):
    m = x.notna().to_numpy() & np.isfinite(x.to_numpy(dtype=float, na_value=np.nan))
    d = pd.DataFrame({"x": x[m], "R": R[m], "E": E[m], "id": ids[m]}).sort_values(["x", "E", "id"])
    lines = [f"{label} (n with finite feature = {int(m.sum())}; equal-count rank quintiles)"]
    for qi, part in enumerate(np.array_split(np.arange(len(d)), 5)):
        g = d.iloc[part]
        lines.append(f"  Q{qi+1}: n={len(g):3d} range=[{g.x.min():+.4f}, {g.x.max():+.4f}] "
                     f"meanR={g.R.mean():+.4f} sumR={g.R.sum():+.2f}")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
def main():
    K, infoK = load_trades(DB_KESIF, KESIF_LO, KESIF_HI)
    B, infoB = load_trades(DB_BAGIMSIZ, pd.Timestamp("1900-01-01", tz="UTC"), BAG_HI)
    hK = {c: load_hourly(H1_KESIF.format(coin=c)) for c in sorted(set(K["coin"]))}
    hB = {c: load_hourly(H1_BAGIMSIZ.format(coin=c)) for c in sorted(set(B["coin"]))}
    checks = []

    # ------------------------------ L1 primary ------------------------------
    lqK, fK = lq_calendar(K, hK)
    lqB, fB = lq_calendar(B, hB)
    for name, lq, T, h in (("KESIF", lqK, K, hK), ("BAGIMSIZ", lqB, B, hB)):
        mm = lq.notna().to_numpy()
        assert np.isfinite(lq[mm]).all()
        for rule in ("day0_missing", "zero_data", "bar0_missing"):
            vec = lq if rule == "day0_missing" else lq_calendar(T, h, rule=rule)[0]
            bf = lq_brute(T, h, rule=rule)
            assert np.array_equal(vec.isna().to_numpy(), bf.isna().to_numpy()), (name, rule)
            m2 = vec.notna().to_numpy()
            assert np.allclose(vec.to_numpy()[m2], bf.to_numpy()[m2], rtol=1e-12, atol=0), (name, rule)
        checks.append(f"L1 {name}: vectorised calendar LQ == per-trade brute force (NaN pattern + values, "
                      f"rtol 1e-12) for all three day-validity rules; primary LQ all finite; no bar with "
                      f"ts+1h > E used")
    K["LQ"], B["LQ"] = lqK, lqB
    rows = l1_rows(K, B, lqK, lqB)

    # ---- disputed point: n_no_feature in L1|BAGIMSIZ (A=13, B=10)
    conv = {
        "B_rowbased_zero_as_data_inf (impl B primary)": (lq_rowbased(K, hK, True), lq_rowbased(B, hB, True)),
        "calendar_zero_as_data_inf": (lq_calendar(K, hK, "zero_data", "inf")[0],
                                      lq_calendar(B, hB, "zero_data", "inf")[0]),
        "calendar_zero_as_data_x/0_undefined": (lq_calendar(K, hK, "zero_data")[0],
                                                lq_calendar(B, hB, "zero_data")[0]),
        "calendar_any_zero_volume_bar_makes_day_partial": (lq_calendar(K, hK, "bar0_missing")[0],
                                                           lq_calendar(B, hB, "bar0_missing")[0]),
    }
    infB = conv["calendar_zero_as_data_inf"][1]
    undB = conv["calendar_zero_as_data_x/0_undefined"][1]
    rowB = conv["B_rowbased_zero_as_data_inf (impl B primary)"][1]
    disp = B.index[lqB.isna() & rowB.notna()]
    assert len(disp) == 3 and set(B.loc[disp, "coin"]) == {"ICP"} and np.isinf(rowB[disp]).all()
    assert (B.index[lqB.isna() & infB.notna()] == disp).all()
    assert (lqB.notna() <= rowB.notna()).all()
    disputed_lines = []
    hI = hB["ICP"]
    zb = hI[hI["vol"] == 0]
    # every zero-volume ICP bar is a flat forward-filled placeholder (O=H=L=C, one constant price)
    assert len(zb) == 1982 and zb["flat"].all() and zb["close"].nunique() == 1
    assert str(zb["ts"].min()) == "2022-06-10 10:00:00+00:00" and str(zb["ts"].max()) == "2022-08-31 23:00:00+00:00"
    assert not ((hI["ts"] >= pd.Timestamp("2022-09-01", tz="UTC")) & (hI["ts"] < pd.Timestamp("2022-09-27", tz="UTC"))).any()
    checks.append(f"ICP Binance 1h: {len(zb)} zero-volume bars 2022-06-10 10:00..2022-08-31 23:00, all flat O=H=L=C="
                  f"{zb['close'].iloc[0]} (placeholders of a non-trading market); no rows 2022-09-01..09-26")
    for i in disp:
        E = B.at[i, "E"]
        L = (E - D1).floor("D")
        g = day_groups(hI[hI["ts"] + H1 <= E])
        w90 = g[(g.index >= L - 96 * D1) & (g.index <= L - 7 * D1)]
        disputed_lines.append(
            f"  ICP E={E} R={B.at[i, 'R']:+.4f}: 90d window {(L - 96 * D1).date()}..{(L - 7 * D1).date()} = "
            f"{int(((w90.n == 24) & (w90.q == 0)).sum())} placeholder zero-volume days + "
            f"{int(((w90.n == 24) & (w90.q > 0)).sum())} real full days + {90 - len(w90)} days without rows "
            f"(+{int((w90.n < 24).sum())} partial) -> B: LQ=+inf; zero-as-data,x/0 undefined: "
            f"LQ={undB[i]:.4f}; FINAL: < 60 real days -> no feature; kept in every convention")
    conv_rows = {}
    for cname, (ck, cb) in conv.items():
        rr = l1_rows(K, B, ck, cb)
        conv_rows[cname] = rr
        same = all(r0[k] == r1[k] for r0, r1 in zip(rows, rr)
                   for k in ("n_kept", "n_skipped", "sumR_kept", "dd_kept", "skipped_meanR",
                             "skipped_ci_lo", "skipped_ci_hi"))
        conv_rows[cname + "__same_decisions"] = same
    for cname in ("B_rowbased_zero_as_data_inf (impl B primary)", "calendar_zero_as_data_inf",
                  "calendar_zero_as_data_x/0_undefined"):
        assert conv_rows[cname + "__same_decisions"], cname
        nf = {(r["variant"], r["window"]): r["n_no_feature"] for r in conv_rows[cname]}
        for r in rows:
            d = r["n_no_feature"] - nf[(r["variant"], r["window"])]
            assert d == (0 if r["window"] == "KESIF" else (1 if "undefined" in cname else 3)), (cname, d)
    checks.append("Disputed n_no_feature (L1|BAGIMSIZ): FINAL 13. Under B's convention (placeholder zero days as "
                  "data, x/0=+inf; row-based or calendar) it is 10, under zero-as-data with x/0 undefined it is 12; "
                  "in all three every skip decision, sumR, maxDD and bootstrap value is bit-identical to FINAL")

    # ------------------------------ L2 ------------------------------
    sK, ageK = l2_feature(K)
    K["s"], K["book_age_min"] = sK, ageK
    L2 = K[K["E"] < L2_HI].copy()
    assert L2["E"].min() >= KESIF_LO
    wins = {"L2_TUM": L2, "L2_YARI1": L2[L2["E"] < L2_SPLIT], "L2_YARI2": L2[L2["E"] >= L2_SPLIT]}
    assert len(wins["L2_YARI1"]) + len(wins["L2_YARI2"]) == len(L2)
    for v, thr in L2_THR.items():
        for w, T in wins.items():
            rows.append(make_row(v, w, T, T["s"], thr))
    checks.append("L2: searchsorted lookup == merge_asof (backward, exact allowed, 15-min tolerance); chosen "
                  "record t_kapanis <= E and next record > E for every trade")
    checks.append("maxDD: resample('ME') implementation == independent month loop (|diff| < 1e-9) for all rows")

    verdicts = l1_verdicts(rows[:4])
    for v in L2_THR:
        r = {x["window"]: x for x in rows if x["variant"] == v}
        ok = (r["L2_YARI1"]["sumR_kept"] > r["L2_YARI1"]["sumR_base"]
              and r["L2_YARI2"]["sumR_kept"] > r["L2_YARI2"]["sumR_base"]
              and r["L2_TUM"]["dd_kept"] <= r["L2_TUM"]["dd_base"] + 1.0)
        verdicts[v] = "IYI (zayif kanit)" if ok else "ELENDI"

    # ------------------------------ sensitivity (decision-free) ------------------------------
    sens = {}
    for cname, rr in conv_rows.items():
        if cname.endswith("__same_decisions"):
            continue
        sens[cname] = {"verdicts": l1_verdicts(rr), "same_decisions_as_final": conv_rows[cname + "__same_decisions"],
                       "rows": [(r["variant"], r["window"], r["n_skipped"], r["n_no_feature"],
                                 round(r["sumR_kept"], 4), round(r["dd_kept"], 4)) for r in rr]}
    a_, b_ = lq_rowbased(K, hK, False), lq_rowbased(B, hB, False)
    rr = l1_rows(K, B, a_, b_)
    sens["rowbased_placeholder_days_missing"] = {
        "verdicts": l1_verdicts(rr),
        "rows": [(r["variant"], r["window"], r["n_skipped"], r["n_no_feature"],
                  round(r["sumR_kept"], 4), round(r["dd_kept"], 4)) for r in rr]}

    # ------------------------------ compare with implementations A and B ------------------------------
    cmp_lines = []
    A = {(r["variant"], r["window"]): r for r in json.load(open(IMPL_A))["rows"]}
    Bj = {(r["variant"], r["window"]): r for r in json.load(open(IMPL_B))["rows"]}
    for r in rows:
        key = (r["variant"], r["window"])
        for src, ref in (("A", A[key]), ("B", Bj[key])):
            diffs = []
            for k in ("n_base", "n_kept", "n_skipped", "n_no_feature", "sumR_base", "sumR_kept",
                      "dd_base", "dd_kept", "skipped_meanR", "skipped_ci_lo", "skipped_ci_hi"):
                x, y = r[k], ref.get(k)
                y = float(y) if isinstance(y, str) else y
                if y is None or (isinstance(x, float) and math.isnan(x)):
                    continue
                if abs(x - y) > 5e-6:
                    diffs.append(f"{k}: final={x} {src}={y}")
            if diffs:
                cmp_lines.append(f"  {key} vs {src}: " + "; ".join(diffs))
    # expected: only n_no_feature differs, only vs B, only L1*|BAGIMSIZ
    assert all("vs B" in l and "BAGIMSIZ" in l and l.count("final=") == 1 and "n_no_feature" in l
               for l in cmp_lines), cmp_lines
    assert len(cmp_lines) == 2
    checks.append("Final rows == impl A on every field (<=5e-6); == impl B on every field except "
                  "n_no_feature in L1a/L1b|BAGIMSIZ (13 vs 10)")

    # ------------------------------ diagnostics ------------------------------
    diag = [quintile_table(K["LQ"], K["R"], K["E"], K["id"], "LQ quintiles KESIF"),
            quintile_table(B["LQ"], B["R"], B["E"], B["id"], "LQ quintiles BAGIMSIZ"),
            quintile_table(L2["s"], L2["R"], L2["E"], L2["id"], "s quintiles L2_TUM")]
    cov = [f"KESIF DB: {infoK}", f"BAGIMSIZ DB: {infoB}",
           f"KESIF LQ available {int(K.LQ.notna().sum())}/{len(K)}; no-LQ trades are the first weeks of the "
           f"MEXC 1h files (start 2023-04-06/07): first E with LQ {K.loc[K.LQ.notna(), 'E'].min()}",
           f"BAGIMSIZ LQ available {int(B.LQ.notna().sum())}/{len(B)}; no-LQ by coin "
           f"{B.loc[B.LQ.isna()].groupby('coin').size().to_dict()} (10 = start of Binance history, "
           f"3 = ICP after the 2022 delisting gap)",
           "Disputed trades:\n" + "\n".join(disputed_lines),
           f"Trades with LQ but < 7 valid days in 7d window: KESIF {int(((fK.cnt7 < 7) & K.LQ.notna()).sum())}, "
           f"BAGIMSIZ {int(((fB.cnt7 < 7) & B.LQ.notna()).sum())}; min valid days in 90d window among LQ trades: "
           f"KESIF {fK.loc[K.LQ.notna(), 'cnt90'].min():.0f}, BAGIMSIZ {fB.loc[B.LQ.notna(), 'cnt90'].min():.0f}",
           f"LQ KESIF max {K.LQ.max():.2f} (BCH 2023-06-30: MEXC BCH daily cash volume jumped ~100x on "
           f"2023-06-21 vs a ~1e8 baseline; data used as-is)",
           f"L2_TUM s available {int(L2.s.notna().sum())}/{len(L2)}; book age at E (min) of used records: "
           f"{L2.loc[L2.s.notna(), 'book_age_min'].value_counts().to_dict()}; no-s trades: "
           f"{[(c, str(e), a) for c, e, a in L2.loc[L2.s.isna(), ['coin', 'E', 'book_age_min']].itertuples(index=False)]}",
           f"KESIF trades with E >= 2026-01-08 (outside L2): {int((K.E >= L2_HI).sum())}; book files end "
           f"2026-01-08 00:00 UTC",
           f"Sensitivity (decision-free): {json.dumps(sens)}"]
    diagnostics = "\n\n".join(diag) + "\n\nCOVERAGE / CHECKS:\n" + "\n".join(cov) + "\n" + "\n".join(checks)

    def clean(x):
        if isinstance(x, (float, np.floating)) and not np.isfinite(x):
            return None
        return x
    res = {"rows": [{k: clean(v) for k, v in r.items()} for r in rows], "verdicts": verdicts,
           "diagnostics": diagnostics, "sensitivity": sens, "checks": checks,
           "comparison_with_impls": cmp_lines}
    with open(os.path.join(OUT_DIR, "sonuc.json"), "w") as fh:
        json.dump(res, fh, indent=1, default=str)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(pd.DataFrame(rows).round(4).to_string(index=False))
    print("\nVERDICTS:", json.dumps(verdicts))
    print("\nDIFFERENCES vs implementations:\n" + "\n".join(cmp_lines))
    print("\n" + diagnostics)


if __name__ == "__main__":
    main()
