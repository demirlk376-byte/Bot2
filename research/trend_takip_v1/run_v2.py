"""
TREND_TAKİP_V2 koşucusu: `python3 -m research.trend_takip_v1.run_v2` — kurallar MANIFEST_V2.md.
Keşif + doğrulama (FİNAL açılmaz). Tabanlar ve 6 varyant, NORMAL/STRESS.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from research.liquidity_sweep_v1 import config as C, selection as SL
from research.liquidity_sweep_v1.cli import write_json, write_csv, sha_bytes, git, _js, t2s
from research.trend_takip_v1 import engine as E
from research.trend_takip_v1.run import load, dates, metrics, DEF_DATA, DEF_META, ROOT

OUT = os.path.join(ROOT, "research_outputs", "trend_takip_v2")
SPECS = {
    "BASE_N50_X5_L": ("N50_X5_L", None, "DONCHIAN"),
    "BASE_N100_X5_LS": ("N100_X5_LS", None, "DONCHIAN"),
    "T1": ("N50_X5_L", 10, "DONCHIAN"),
    "T2": ("N50_X5_L", 20, "DONCHIAN"),
    "T3": ("N100_X5_LS", 10, "DONCHIAN"),
    "T4": ("N100_X5_LS", 20, "DONCHIAN"),
    "H1": ("N50_X5_LS", None, "NWK"),
    "H2": ("N50_X3_LS", None, "NWK"),
}
BASE_OF = {"T1": "BASE_N50_X5_L", "T2": "BASE_N50_X5_L", "T3": "BASE_N100_X5_LS", "T4": "BASE_N100_X5_LS"}


def run_one(syms, d, key, phase, out):
    vid, early, entry = SPECS[key]
    mm, eqs = [], {}
    for cost in (C.TWIN_MARKET_PROFILE, C.TWIN_MARKET_PROFILE.stress()):
        tr, bl, eq, led, openp = E.simulate(vid, d[phase], syms, cost, early_days=early, entry=entry)
        m = metrics(tr, eq, d[phase], phase, led)
        m.update(variant_id=key, cost=cost.name, open_at_end=len(openp))
        if openp:
            m["metrics_valid"] = False
        p = os.path.join(out, phase, f"{key}_{cost.name}")
        write_csv(os.path.join(p, "trades.csv"), pd.DataFrame(tr))
        write_csv(os.path.join(p, "equity_1d.csv"), pd.DataFrame(eq, columns=["t", "equity", "open", "risk"]))
        write_json(os.path.join(p, "metrics.json"), m)
        mm.append(m)
        eqs[cost.name] = eq
    return tuple(mm), eqs


def adopt(res):
    out = {}
    for k, b in BASE_OF.items():
        ok, why = True, []
        for ph in ("DISCOVERY", "VALIDATION"):
            v, bb = res[ph][k][0], res[ph][b][0]
            vr = v.get("expectancy_net_R"); br = bb.get("expectancy_net_R")
            c = dict(meanR=isinstance(vr, float) and vr >= br, total=v["net_USDT"] >= 0.9 * bb["net_USDT"],
                     mdd=v["MDD_close_pct"] <= bb["MDD_close_pct"], stress=res[ph][k][1]["net_USDT"] > 0)
            why.append({ph: c})
            ok &= all(c.values())
        out[k] = dict(adopted=bool(ok), checks=why)
    for k in ("H1", "H2"):
        ok = all(res[ph][k][i]["net_USDT"] > 0 for ph in ("DISCOVERY", "VALIDATION") for i in (0, 1))
        out[k] = dict(works=bool(ok))
    return out


def combined(eqa, eqb):
    a = pd.Series({t: e for t, e, *_ in eqa}); b = pd.Series({t: e for t, e, *_ in eqb})
    ix = a.index.union(b.index)
    a = a.reindex(ix).ffill().fillna(C.C0_FALLBACK); b = b.reindex(ix).ffill().fillna(C.C0_FALLBACK)
    eq = a + b - C.C0_FALLBACK
    mdd = float(((eq.cummax() - eq) / eq.cummax()).max() * 100)
    return dict(return_pct=float(100 * (eq.iloc[-1] - C.C0_FALLBACK) / C.C0_FALLBACK), MDD_pct=mdd)


def main():
    syms = load(DEF_DATA, DEF_META)
    d = dates(syms)
    code = {f: sha_bytes(open(os.path.join(os.path.dirname(__file__), f), "rb").read())
            for f in sorted(os.listdir(os.path.dirname(__file__))) if f.endswith((".py", ".md"))}
    man = dict(spec="TREND_TAKIP_V2 (MANIFEST_V2.md)", commit=git("rev-parse", "HEAD"),
               dirty=bool(git("status", "--porcelain")), code_hashes=code, specs=SPECS,
               dates={k: t2s(d[k]) for k in ("T0", "B1", "B2", "T1")}, final_opened=False)
    mh = sha_bytes(json.dumps(man, sort_keys=True, default=_js).encode())
    rid = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{(man['commit'] or 'x')[:8]}_{mh[:8]}"
    out = os.path.join(OUT, rid)
    os.makedirs(out, exist_ok=True)
    write_json(os.path.join(out, "experiment_manifest.json"), dict(man, run_id=rid, manifest_hash=mh))
    res, eqs = {}, {}
    for ph in ("DISCOVERY", "VALIDATION"):
        res[ph], eqs[ph] = {}, {}
        for k in SPECS:
            res[ph][k], eqs[ph][k] = run_one(syms, d, k, ph, out)
            print(f"{datetime.now(timezone.utc):%H:%M:%S} {ph} {k}", flush=True)
    stat = {ph: SL.select({k: v for k, v in res[ph].items()}, ph) for ph in res}
    ad = adopt(res)
    best_t = max(["BASE_N50_X5_L"] + [k for k in BASE_OF if ad[k]["adopted"]],
                 key=lambda k: res["DISCOVERY"][k][0]["net_USDT"] + res["VALIDATION"][k][0]["net_USDT"])
    comb = {ph: {h: combined(eqs[ph][best_t]["NORMAL"], eqs[ph][h]["NORMAL"]) for h in ("H1", "H2")}
            for ph in res}
    tab = {ph: {k: {c: {f: v[i].get(f) for f in ("closed", "expectancy_net_R", "return_pct", "MDD_close_pct",
                                                    "win_rate", "LCB", "years")}
                    for i, c in enumerate(("NORMAL", "STRESS"))} for k, v in res[ph].items()} for ph in res}
    summ = dict(run_id=rid, manifest_hash=mh, table=tab, adoption=ad, best_trend=best_t, combined=comb,
                selection={ph: dict(selected=s[0], rows=s[1]) for ph, s in stat.items()})
    write_json(os.path.join(out, "decision.json"), summ)
    print(json.dumps(dict(adoption=ad, best_trend=best_t, combined=comb), indent=1, default=_js))
    return out


if __name__ == "__main__":
    main()
