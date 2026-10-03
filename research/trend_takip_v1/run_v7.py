"""REJIM_V7: `python3 -m research.trend_takip_v1.run_v7` — kurallar MANIFEST_V7.md."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pandas as pd

from research.liquidity_sweep_v1 import config as C
from research.liquidity_sweep_v1.cli import write_json, sha_bytes, git, _js, t2s
from research.trend_takip_v1 import engine as E
from research.trend_takip_v1.run import metrics, ROOT, T0, load as load_old1d, DEF_DATA, DEF_META
from research.trend_takip_v1.run_v2 import combined
from research.trend_takip_v1 import run_v5 as V5, run_v6 as V6

D4 = os.path.join(ROOT, "research_data", "h4_kirilim_v6", "veri")
D1N = os.path.join(ROOT, "research_data", "yeni_coin_v5", "veri")
OUT = os.path.join(ROOT, "research_outputs", "rejim_v7")
B2 = V5.B2
MODS = {"T1_1D": ("N50_X5_L", 10, C.DAY), "H4": ("N180_X5_L", 10, V6.H4)}


def year_pnl(trs):
    t = pd.DataFrame([x for tr in trs for x in tr])
    if t.empty:
        return {}
    return (t.groupby(pd.to_datetime(t.exit_time, unit="ms").dt.year).net_PnL.sum() / 100).round(2).to_dict()


def main():
    old1 = load_old1d(DEF_DATA, DEF_META)
    new1, exn = V5.load(D1N)
    old4, _ = V6.load(D4, V6.OLD, "4h")
    new4, _ = V6.load(D4, V6.NEW, "4h")
    reg = {"R0": {"ESKI12": None, "YENI24": None},
           "R1": {"ESKI12": E.regime_ma(old1["ETH"]), "YENI24": E.regime_ma(old1["ETH"])},
           "R2": {"ESKI12": E.regime_breadth(old1), "YENI24": E.regime_breadth(new1)}}
    sets = {"ESKI12": (old1, old4), "YENI24": (new1, new4)}
    code = {f: sha_bytes(open(os.path.join(os.path.dirname(__file__), f), "rb").read())
            for f in sorted(os.listdir(os.path.dirname(__file__))) if f.endswith((".py", ".md"))}
    man = dict(spec="REJIM_V7 (MANIFEST_V7.md)", commit=git("rev-parse", "HEAD"), dirty=bool(git("status", "--porcelain")),
               code_hashes=code, window=[t2s(T0), t2s(B2)], sets={k: sorted(v[0]) for k, v in sets.items()},
               regime_days_off={r: {k: (sum(1 for x in d.values() if not x) if d else 0) for k, d in v.items()}
                                for r, v in reg.items()})
    mh = sha_bytes(json.dumps(man, sort_keys=True, default=_js).encode())
    rid = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{(man['commit'] or 'x')[:8]}_{mh[:8]}"
    out = os.path.join(OUT, rid)
    os.makedirs(out, exist_ok=True)
    write_json(os.path.join(out, "experiment_manifest.json"), dict(man, run_id=rid, manifest_hash=mh))
    res = {}
    for r in reg:
        for k, (s1, s4) in sets.items():
            eqs, trs, mods = {}, [], {}
            for mname, (vid, early, bar) in MODS.items():
                syms = s1 if bar == C.DAY else s4
                mm = []
                for cost in (C.TWIN_MARKET_PROFILE, C.TWIN_MARKET_PROFILE.stress()):
                    tr, bl, eq, led, op = E.simulate(vid, (T0, B2), syms, cost, early_days=early, bar_ms=bar,
                                                     regime=reg[r][k])
                    m = metrics(tr, eq, (T0, B2), k, led)
                    mm.append({f: m.get(f) for f in ("closed", "expectancy_net_R", "return_pct", "MDD_close_pct", "LCB")})
                    if cost.name == "NORMAL":
                        eqs[mname], trs = eq, trs + [tr]
                mods[mname] = dict(NORMAL=mm[0], STRESS=mm[1], years=year_pnl([trs[-1]]))
            res[(r, k)] = dict(modules=mods, paket=combined(eqs["T1_1D"], eqs["H4"]), paket_years=year_pnl(trs))
            print(f"{datetime.now(timezone.utc):%H:%M:%S} {r} {k} {res[(r, k)]['paket']}", flush=True)
    dec = {}
    for r in ("R1", "R2"):
        ch = {}
        for k in sets:
            a, b = res[(r, k)], res[("R0", k)]
            ch[k] = dict(mdd=a["paket"]["MDD_pct"] < b["paket"]["MDD_pct"],
                         ret=a["paket"]["return_pct"] >= 0.85 * b["paket"]["return_pct"],
                         y2022=a["paket_years"].get(2022, 0.0) >= b["paket_years"].get(2022, 0.0))
        dec[r] = dict(benimsenir=all(all(c.values()) for c in ch.values()), checks=ch)
    summ = dict(run_id=rid, manifest_hash=mh, decisions=dec, results={f"{r}|{k}": v for (r, k), v in res.items()})
    write_json(os.path.join(out, "decision.json"), summ)
    print(json.dumps(dec, indent=1))
    print(out)


if __name__ == "__main__":
    main()
