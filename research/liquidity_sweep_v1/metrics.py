"""
Koşu metrikleri (şartname §18.1, §19). Haftalık blok bootstrap:
  • UTC haftası Pazartesi 00:00; bölüm içindeki TAM haftalar ortak takvim.
  • İşlem, çıkış olayının ait olduğu haftaya: bar içi çıkış → exit_interval_start; açılış çıkışı → o an.
  • S_w = haftanın net_R toplamı, N_w = işlem sayısı (işlemsiz hafta 0/0 dahil).
  • 4 haftalık ardışık bloklar, başlangıçlar uniform/replacement, dairesel; W'de kes.
  • tekrar beklentisi = ΣS*/ΣN* ; 10.000 tekrar, seed 20261001 ; ΣN*=0 olan tekrar geçersiz.
Bu aralık 32 aday arasından seçimi düzelten bir anlamlılık testi DEĞİLDİR.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import config as C

MONDAY_EPOCH = 4 * C.DAY       # 1970-01-05 Pazartesi 00:00 UTC = 4 gün


def week_start(ms):
    return ((ms - MONDAY_EPOCH) // (7 * C.DAY)) * (7 * C.DAY) + MONDAY_EPOCH


def full_weeks(start, end):
    w0 = week_start(start)
    if w0 < start:
        w0 += 7 * C.DAY
    out = []
    w = w0
    while w + 7 * C.DAY <= end:
        out.append(w)
        w += 7 * C.DAY
    return out


def weekly_SN(trades: pd.DataFrame, start, end):
    weeks = full_weeks(start, end)
    idx = {w: i for i, w in enumerate(weeks)}
    S = np.zeros(len(weeks))
    N = np.zeros(len(weeks))
    if len(trades):
        wk = trades["exit_interval_start"].map(lambda x: week_start(int(x)))
        for w, r in zip(wk, trades["net_R"]):
            i = idx.get(int(w))
            if i is not None and np.isfinite(r):
                S[i] += r
                N[i] += 1
    return weeks, S, N


def block_bootstrap(S, N, reps=C.BOOT_REPS, block=C.BOOT_BLOCK_WEEKS, seed=C.BOOT_SEED):
    W = len(S)
    if W == 0:
        return dict(ci=[float("nan"), float("nan")], lcb=float("nan"), invalid_frac=1.0, reliable=False)
    rng = np.random.default_rng(seed)
    nb = math.ceil(W / block)
    starts = rng.integers(0, W, size=(reps, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % W
    idx = idx.reshape(reps, nb * block)[:, :W]
    sS, sN = S[idx].sum(axis=1), N[idx].sum(axis=1)
    ok = sN > 0
    vals = sS[ok] / sN[ok]
    inv = float(1 - ok.mean())
    if not len(vals):
        return dict(ci=[float("nan"), float("nan")], lcb=float("nan"), invalid_frac=inv, reliable=False)
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return dict(ci=[float(lo), float(hi)], lcb=float(lo), invalid_frac=inv,
                reliable=inv <= C.BOOT_INVALID_MAX, numpy_version=np.__version__)


def mdd_and_underwater(eq_t, eq, C0):
    if not len(eq):
        return float("nan"), 0.0, 0.0
    peak = np.maximum.accumulate(np.r_[C0, eq])[1:]
    dd = 100 * (peak - eq) / peak
    under = eq < peak - 1e-12
    longest = 0
    t_start = None
    for i, u in enumerate(under):
        if u and t_start is None:
            t_start = eq_t[i - 1] if i > 0 else eq_t[i]
        elif not u and t_start is not None:
            longest = max(longest, eq_t[i] - t_start)        # tepeye DÖNÜLEN kesite kadar
            t_start = None
    unfinished = (eq_t[-1] - t_start) if t_start is not None else 0
    return float(dd.max()), longest / C.H1, unfinished / C.H1


def pf(x):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    g, l = x[x > 0].sum(), -x[x < 0].sum()
    if l == 0:
        return "INF" if g > 0 else "NA"
    return float(g / l)


def run_metrics(res, outcomes_events, window, C0, phase):
    tr = pd.DataFrame(res.trades)
    start, end = window
    eq = np.array([r[7] for r in res.equity]) if res.equity else np.zeros(0)
    eq_t = np.array([r[0] for r in res.equity]) if res.equity else np.zeros(0)
    n = len(tr)
    m = dict(closed=n, signals=None, phase=phase)
    if n:
        r = tr["net_R"].to_numpy(dtype=float)
        m.update(win_rate=float((tr["net_PnL"] > 0).mean()), zero_pnl=int((tr["net_PnL"] == 0).sum()),
                 expectancy_net_R=float(np.nansum(r) / n), profit_factor_usdt=pf(tr["net_PnL"]),
                 profit_factor_R=pf(r), net_USDT=float(tr["net_PnL"].sum()),
                 ambiguous_exits=int(tr["ambiguity_flag"].sum()),
                 invalid_R=int((~np.isfinite(r)).sum()))
    else:
        m.update(win_rate="NA", expectancy_net_R="NA", profit_factor_usdt="NA", profit_factor_R="NA",
                 net_USDT=0.0, ambiguous_exits=0, status_note="NO_TRADES")
    m["return_pct"] = 100 * m["net_USDT"] / C0
    weeks, S, N = weekly_SN(tr if n else pd.DataFrame(columns=["exit_interval_start", "net_R"]), start, end)
    bs = block_bootstrap(S, N)
    m.update(full_weeks=len(weeks), weeks_with_trades=int((N > 0).sum()), nominal_CI=bs["ci"], LCB=bs["lcb"],
             boot_invalid_frac=bs["invalid_frac"], boot_reliable=bs["reliable"])
    mdd, uw, uw_open = mdd_and_underwater(eq_t, eq, C0)
    m.update(MDD_close_pct=mdd, underwater_longest_h=uw, underwater_unfinished_h=uw_open)
    led = res.ledger
    m.update(entry_fees=led.entry_fees, exit_fees=led.exit_fees, funding=led.funding,
             slippage_diag_usdt=led.slip_cost_diag, end_wallet=led.wallet)
    # uzlaşma: cüzdan değişimi = kapanan işlemlerin net PnL toplamı (açık pozisyon kalmamalı)
    tol = max(1e-6, C0 * 1e-10)
    recon = (led.wallet - C0) - (float(tr["net_PnL"].sum()) if n else 0.0)
    m["reconciliation_gap"] = recon
    m["identity_max_gap"] = res.flags["identity_max_gap"]
    m["flags"] = dict(res.flags)
    invalid = abs(recon) > tol or res.flags["identity_max_gap"] > tol or res.flags["censored_open_at_end"] > 0
    m["metrics_valid"] = not invalid
    m["data_gap_exposure"] = res.flags["data_gap_positions"] > 0
    m["funding_order_ambiguous"] = res.flags["funding_off_grid"] > 0
    m["funding_modeled"] = res.flags.get("funding_not_modeled", 0) == 0
    m["funding_scope"] = "komisyon/kayma/funding dahil" if m["funding_modeled"] else \
        "komisyon/kayma dahil, funding HARİÇ (NOT_MODELED)"
    if len(eq):
        open_frac = float(np.mean([r[8] > 0 for r in res.equity]))
        m.update(exposure_time_frac=open_frac,
                 avg_long_notional=float(np.mean([r[9] for r in res.equity])),
                 avg_short_notional=float(np.mean([r[10] for r in res.equity])),
                 max_initial_stop_risk=float(np.max([r[11] for r in res.equity])),
                 max_margin=float(np.max([r[3] for r in res.equity])))
    oc = pd.DataFrame(res.outcomes)
    m["blocked_reasons"] = (oc.loc[~oc["terminal_status"].isin(["FILLED", "CLOSED"]), "reason_code"]
                            .value_counts().to_dict() if len(oc) else {})
    m["fills"] = int((oc["terminal_status"] == "FILLED").sum()) if len(oc) else 0
    return m
