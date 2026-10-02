"""NWK_FILTRE_V4 koşucusu: `python3 -m research.trend_takip_v1.run_v4` — kurallar MANIFEST_V4.md."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pandas as pd

from research.liquidity_sweep_v1 import config as C, selection as SL
from research.liquidity_sweep_v1.cli import write_json, write_csv, sha_bytes, git, _js, t2s
from research.trend_takip_v1 import engine as E
from research.trend_takip_v1.run import load, dates, metrics, DEF_DATA, DEF_META, ROOT
from research.trend_takip_v1.run_v2 import combined
from research.trend_takip_v1.run_v3 import better, PH

OUT = os.path.join(ROOT, "research_outputs", "nwk_filtre_v4")
KEYS = ["NWK1D_F0", "NWK1D_G1", "NWK1D_G2", "NWK1D_G3"]


def main():
    syms = load(DEF_DATA, DEF_META)
    d = dates(syms)
    code = {f: sha_bytes(open(os.path.join(os.path.dirname(__file__), f), "rb").read())
            for f in sorted(os.listdir(os.path.dirname(__file__))) if f.endswith((".py", ".md"))}
    man = dict(spec="NWK_FILTRE_V4 (MANIFEST_V4.md)", commit=git("rev-parse", "HEAD"),
               dirty=bool(git("status", "--porcelain")), code_hashes=code, variants=KEYS,
               dates={k: t2s(d[k]) for k in ("T0", "B1", "B2", "T1")}, final_opened=False)
    mh = sha_bytes(json.dumps(man, sort_keys=True, default=_js).encode())
    rid = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{(man['commit'] or 'x')[:8]}_{mh[:8]}"
    out = os.path.join(OUT, rid)
    os.makedirs(out, exist_ok=True)
    write_json(os.path.join(out, "experiment_manifest.json"), dict(man, run_id=rid, manifest_hash=mh))
    res, eqs = {ph: {} for ph in PH}, {ph: {} for ph in PH}
    runs = [(k, "N50_X3_LS", None, E.nwk_entries(syms, filt=k[-2:])) for k in KEYS] + [("T1", "N50_X5_L", 10, None)]
    for ph in PH:
        for k, vid, early, sg in runs:
            mm = []
            for cost in (C.TWIN_MARKET_PROFILE, C.TWIN_MARKET_PROFILE.stress()):
                tr, bl, eq, led, op = E.simulate(vid, d[ph], syms, cost, early_days=early,
                                                 entry="NWK" if sg else "DONCHIAN", entry_sigs=sg)
                m = metrics(tr, eq, d[ph], ph, led)
                m.update(variant_id=k, cost=cost.name)
                p = os.path.join(out, ph, f"{k}_{cost.name}")
                write_csv(os.path.join(p, "trades.csv"), pd.DataFrame(tr))
                write_json(os.path.join(p, "metrics.json"), m)
                mm.append(m)
                if cost.name == "NORMAL":
                    eqs[ph][k] = eq
            res[ph][k] = tuple(mm)
    dec = {f"{k}_vs_F0": better(res, k, "NWK1D_F0") for k in KEYS[1:]}
    comb = {k: {ph: combined(eqs[ph]["T1"], eqs[ph][k]) for ph in PH} for k in KEYS}
    tab = {ph: {k: {c: {f: v[i].get(f) for f in ("closed", "expectancy_net_R", "return_pct", "MDD_close_pct",
                                                    "win_rate", "LCB", "years")}
                    for i, c in enumerate(("NORMAL", "STRESS"))} for k, v in res[ph].items()} for ph in PH}
    sel = {ph: SL.select({k: res[ph][k] for k in KEYS}, ph) for ph in PH}
    summ = dict(run_id=rid, manifest_hash=mh, table=tab, decisions=dec, combined_T1=comb,
                selection={ph: dict(selected=s[0], rows=s[1]) for ph, s in sel.items()})
    write_json(os.path.join(out, "decision.json"), summ)
    print(out)


if __name__ == "__main__":
    main()
