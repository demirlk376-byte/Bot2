"""GELISIM_V8: `python3 -m research.trend_takip_v1.run_v8` — kurallar MANIFEST_V8.md."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from research.liquidity_sweep_v1 import config as C
from research.liquidity_sweep_v1.cli import write_json, sha_bytes, git, _js, t2s
from research.trend_takip_v1 import engine as E
from research.trend_takip_v1.run import metrics, ROOT, T0, load as load_old1d, DEF_DATA, DEF_META
from research.trend_takip_v1.run_v2 import combined
from research.trend_takip_v1.run_v7 import year_pnl, D4, D1N, B2
from research.trend_takip_v1 import run_v5 as V5, run_v6 as V6

OUT = os.path.join(ROOT, "research_outputs", "gelisim_v8")
VARS = {"P0": (False, 0), "S": (True, 0), "P": (False, 2), "SP": (True, 2)}
MODS = {"T1_1D": (50, C.DAY), "H4": (180, V6.H4)}


def main():
    old1 = load_old1d(DEF_DATA, DEF_META)
    new1, _ = V5.load(D1N)
    old4, _ = V6.load(D4, V6.OLD, "4h")
    new4, _ = V6.load(D4, V6.NEW, "4h")
    reg = E.regime_ma(old1["ETH"])
    sets = {"ESKI12": (old1, old4), "YENI24": (new1, new4)}
    code = {f: sha_bytes(open(os.path.join(os.path.dirname(__file__), f), "rb").read())
            for f in sorted(os.listdir(os.path.dirname(__file__))) if f.endswith((".py", ".md"))}
    man = dict(spec="GELISIM_V8 (MANIFEST_V8.md)", commit=git("rev-parse", "HEAD"), dirty=bool(git("status", "--porcelain")),
               code_hashes=code, window=[t2s(T0), t2s(B2)], variants=VARS)
    mh = sha_bytes(json.dumps(man, sort_keys=True, default=_js).encode())
    rid = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{(man['commit'] or 'x')[:8]}_{mh[:8]}"
    out = os.path.join(OUT, rid)
    os.makedirs(out, exist_ok=True)
    write_json(os.path.join(out, "experiment_manifest.json"), dict(man, run_id=rid, manifest_hash=mh))
    res = {}
    for v, (sh, pyr) in VARS.items():
        for k, (s1, s4) in sets.items():
            eq = {"NORMAL": {}, "STRESS": {}}
            trs, mods = [], {}
            for mname, (N, bar) in MODS.items():
                vid = f"N{N}_X5_{'LS' if sh else 'L'}"
                syms = s1 if bar == C.DAY else s4
                mm = {}
                for cost in (C.TWIN_MARKET_PROFILE, C.TWIN_MARKET_PROFILE.stress()):
                    tr, bl, e, led, op = E.simulate(vid, (T0, B2), syms, cost, early_days=10, bar_ms=bar, regime=reg,
                                                    short_in_bear=sh, pyr_adds=pyr)
                    m = metrics(tr, e, (T0, B2), k, led)
                    mm[cost.name] = {f: m.get(f) for f in ("closed", "expectancy_net_R", "return_pct", "MDD_close_pct", "LCB")}
                    eq[cost.name][mname] = e
                    if cost.name == "NORMAL":
                        trs.append(tr)
                        mm["shorts"] = sum(1 for x in tr if x["side"] == "SHORT")
                        mm["short_pnl_pct"] = sum(x["net_PnL"] for x in tr if x["side"] == "SHORT") / 100
                mods[mname] = dict(mm, years=year_pnl([trs[-1]]))
            pk = combined(eq["NORMAL"]["T1_1D"], eq["NORMAL"]["H4"])
            pks = combined(eq["STRESS"]["T1_1D"], eq["STRESS"]["H4"])
            res[(v, k)] = dict(modules=mods, paket=pk, paket_stress=pks, paket_years=year_pnl(trs),
                               ratio=pk["return_pct"] / pk["MDD_pct"])
            print(f"{datetime.now(timezone.utc):%H:%M:%S} {v} {k} {pk} stress={pks['return_pct']:.1f}", flush=True)
    dec = {}
    for v in ("S", "P", "SP"):
        ch = {k: dict(ret=res[(v, k)]["paket"]["return_pct"] > res[("P0", k)]["paket"]["return_pct"],
                      ratio=res[(v, k)]["ratio"] > res[("P0", k)]["ratio"],
                      stress=res[(v, k)]["paket_stress"]["return_pct"] > 0) for k in sets}
        dec[v] = dict(benimsenir=all(all(c.values()) for c in ch.values()), checks=ch)
    ad = [v for v in dec if dec[v]["benimsenir"]]
    chosen = max(ad, key=lambda v: res[(v, "ESKI12")]["ratio"]) if ad else "P0"
    summ = dict(run_id=rid, manifest_hash=mh, decisions=dec, chosen=chosen,
                results={f"{v}|{k}": x for (v, k), x in res.items()})
    write_json(os.path.join(out, "decision.json"), summ)
    print(json.dumps(dict(dec=dec, chosen=chosen), indent=1))
    print(out)


if __name__ == "__main__":
    main()
