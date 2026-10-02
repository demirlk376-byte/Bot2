"""
TREND_TAKİP_V1 koşucusu: `python3 -m research.trend_takip_v1.run [--data DIR] [--meta FILE]`
Kurallar: MANIFEST.md. Seçim/karar: liquidity_sweep_v1.selection aynen.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from research.liquidity_sweep_v1 import config as C, metrics as MT, selection as SL
from research.liquidity_sweep_v1.cli import write_json, write_csv, sha_bytes, git, _js, t2s
from research.liquidity_sweep_v1.data_contract import contract_meta
from research.trend_takip_v1 import engine as E

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEF_DATA = os.path.join(ROOT, "research_data", "trend_takip_v1", "veri")
DEF_META = os.path.join(ROOT, "research_data", "liquidity_sweep_v1", "veri", "mexc_contract_detail.json")
OUT = os.path.join(ROOT, "research_outputs", "trend_takip_v1")
T0 = int(pd.Timestamp("2021-01-01", tz="UTC").timestamp() * 1000)


def load(data, meta):
    det = json.load(open(meta))
    syms = {}
    for s in C.UNIVERSE:
        k = pd.read_csv(os.path.join(data, f"{s}_1d.csv")).sort_values("open_time")
        k = k[(k.high >= k[["open", "close"]].max(axis=1)) & (k.low <= k[["open", "close"]].min(axis=1)) & (k.low > 0)]
        f = pd.read_csv(os.path.join(data, f"{s}_funding.csv"))
        ft = pd.to_numeric(f.iloc[:, 0], errors="coerce").to_numpy()
        fr = pd.to_numeric(f.iloc[:, 1], errors="coerce").to_numpy()
        ok = np.isfinite(ft) & np.isfinite(fr)
        o = np.argsort(ft[ok])
        tick, cs, vu, mv, _ = contract_meta(det, s)
        syms[s] = E.Sym(s, k.open_time.to_numpy("int64"), *(k[c].to_numpy(float) for c in ("open", "high", "low", "close")),
                        tick, cs, vu, mv, ft[ok][o].astype("int64"), fr[ok][o], v=k.volume.to_numpy(float))
    return syms


def dates(syms):
    t1 = min(int(s.t[-1]) + C.DAY for s in syms.values())
    t1 = (t1 // C.DAY) * C.DAY
    n = (t1 - T0) // C.DAY
    b1, b2 = T0 + math.floor(0.6 * n) * C.DAY, T0 + math.floor(0.8 * n) * C.DAY
    return dict(DISCOVERY=(T0, b1), VALIDATION=(b1, b2), FINAL=(b2, t1), T0=T0, B1=b1, B2=b2, T1=t1)


def metrics(trades, equity, window, phase, led):
    tr = pd.DataFrame(trades)
    n = len(tr)
    m = dict(phase=phase, closed=n, metrics_valid=True, data_gap_exposure=False, funding_order_ambiguous=False,
             funding_modeled=True)
    if n:
        r = tr.net_R.to_numpy(float)
        m.update(expectancy_net_R=float(r.mean()), net_USDT=float(tr.net_PnL.sum()), win_rate=float((r > 0).mean()),
                 profit_factor_usdt=MT.pf(tr.net_PnL), avg_hold_days=float(tr.hold_days.mean()),
                 best_trade_R=float(r.max()))
    else:
        m.update(expectancy_net_R="NA", net_USDT=0.0)
    w, S, N = MT.weekly_SN(tr if n else pd.DataFrame(columns=["exit_interval_start", "net_R"]), *window)
    bs = MT.block_bootstrap(S, N)
    m.update(full_weeks=len(w), weeks_with_trades=int((N > 0).sum()), nominal_CI=bs["ci"], LCB=bs["lcb"],
             boot_reliable=bs["reliable"])
    eq = np.array([e[1] for e in equity]) if equity else np.zeros(0)
    et = np.array([e[0] for e in equity]) if equity else np.zeros(0)
    mdd, uw, uwo = MT.mdd_and_underwater(et, eq, C.C0_FALLBACK)
    recon = (led.wallet - C.C0_FALLBACK) - (float(tr.net_PnL.sum()) if n else 0.0)
    m.update(MDD_close_pct=mdd, underwater_longest_d=uw / 24, return_pct=100 * m["net_USDT"] / C.C0_FALLBACK,
             reconciliation_gap=recon, funding=float(led.funding), fees=float(led.fees))
    if abs(recon) > 1e-6:
        m["metrics_valid"] = False
    yrs = (window[1] - window[0]) / (365.25 * C.DAY)
    m["years"] = yrs
    return m


def run_phase(syms, d, vids, phase, out):
    res, nets = {}, {}
    for vid in vids:
        mm = []
        for cost in (C.TWIN_MARKET_PROFILE, C.TWIN_MARKET_PROFILE.stress()):
            tr, bl, eq, led, openp = E.simulate(vid, d[phase], syms, cost)
            m = metrics(tr, eq, d[phase], phase, led)
            m.update(variant_id=vid, cost=cost.name, open_at_end=len(openp),
                     missing_funding=getattr(led, "missing_funding_settlements", 0),
                     blocked=pd.Series([b["reason"] for b in bl]).value_counts().to_dict() if bl else {})
            if openp:
                m["metrics_valid"] = False
            p = os.path.join(out, phase, f"{vid}_{cost.name}")
            write_csv(os.path.join(p, "trades.csv"), pd.DataFrame(tr))
            write_csv(os.path.join(p, "equity_1d.csv"), pd.DataFrame(eq, columns=["t", "equity", "open", "risk"]))
            write_json(os.path.join(p, "metrics.json"), m)
            mm.append(m)
            if cost.name == "NORMAL":
                nets[vid] = [t["net_PnL"] for t in tr]
        res[vid] = tuple(mm)
        print(f"{datetime.now(timezone.utc):%H:%M:%S} {phase} {vid}", flush=True)
    return res, nets


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DEF_DATA)
    ap.add_argument("--meta", default=DEF_META)
    a = ap.parse_args(argv)
    syms = load(a.data, a.meta)
    d = dates(syms)
    hashes = {f: sha_bytes(open(os.path.join(a.data, f), "rb").read()) for f in sorted(os.listdir(a.data))}
    code = {f: sha_bytes(open(os.path.join(os.path.dirname(__file__), f), "rb").read())
            for f in sorted(os.listdir(os.path.dirname(__file__))) if f.endswith(".py")}
    man = dict(spec="TREND_TAKIP_V1 (MANIFEST.md)", commit=git("rev-parse", "HEAD"), dirty=bool(git("status", "--porcelain")),
               data_hashes=hashes, code_hashes=code, variants=E.VARIANTS,
               dates={k: t2s(d[k]) for k in ("T0", "B1", "B2", "T1")},
               cost=C.TWIN_MARKET_PROFILE.as_dict(), previous_data_use="previously_examined")
    mh = sha_bytes(json.dumps(man, sort_keys=True, default=_js).encode())
    rid = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{(man['commit'] or 'x')[:8]}_{mh[:8]}"
    out = os.path.join(OUT, rid)
    os.makedirs(out, exist_ok=True)
    write_json(os.path.join(out, "experiment_manifest.json"), dict(man, run_id=rid, manifest_hash=mh))
    print("manifest", rid, man["dates"], flush=True)
    disc, _ = run_phase(syms, d, E.VARIANTS, "DISCOVERY", out)
    sel, rows = SL.select(disc, "DISCOVERY")
    write_json(os.path.join(out, "selection_discovery.json"), dict(manifest_hash=mh, selected=sel, rows=rows,
               metrics={v: dict(NORMAL=x[0], STRESS=x[1]) for v, x in disc.items()}))
    vrows, chosen, fin = [], [], None
    if sel:
        val, _ = run_phase(syms, d, sel, "VALIDATION", out)
        chosen, vrows = SL.select(val, "VALIDATION")
        write_json(os.path.join(out, "selection_final.json"), dict(manifest_hash=mh, candidates=sel, selected=chosen,
                   rows=vrows, metrics={v: dict(NORMAL=x[0], STRESS=x[1]) for v, x in val.items()}))
    if chosen:
        f, nets = run_phase(syms, d, chosen, "FINAL", out)
        v = chosen[0]
        top5 = float(sum(sorted(nets[v], reverse=True)[5:]))
        dec, why = SL.final_decision(*f[v], top5, False)
        fin = dict(candidate=v, decision=dec, reason=why, top5_removed=top5, metrics=dict(NORMAL=f[v][0], STRESS=f[v][1]))
    dec, why = (fin["decision"], fin["reason"]) if fin else SL.overall_without_final(rows, vrows)
    summ = dict(run_id=rid, decision=dec, reason=why, discovery_selected=sel, final_selected=chosen, final=fin,
                status_counts=pd.Series([r["reason"] for r in rows]).value_counts().to_dict())
    write_json(os.path.join(out, "decision.json"), summ)
    print(json.dumps(summ, indent=1, ensure_ascii=False, default=_js))
    return out


if __name__ == "__main__":
    main()
