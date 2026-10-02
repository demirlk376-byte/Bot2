"""YENI_COIN_V5: `python3 -m research.trend_takip_v1.run_v5 --data DIR` — kurallar MANIFEST_V5.md."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from research.liquidity_sweep_v1 import config as C
from research.liquidity_sweep_v1.cli import write_json, write_csv, sha_bytes, git, _js, t2s
from research.liquidity_sweep_v1.data_contract import contract_meta
from research.trend_takip_v1 import engine as E
from research.trend_takip_v1.run import metrics, ROOT, T0
from research.trend_takip_v1.run_v2 import combined

COINS = ("LINK AVAX DOT UNI ATOM FIL ETC AAVE ALGO XTZ SAND MANA AXS EGLD RUNE EOS THETA GRT CRV HBAR "
         "VET APT ARB OP INJ SUI").split()
B2 = int(pd.Timestamp("2025-08-08", tz="UTC").timestamp() * 1000)
OUT = os.path.join(ROOT, "research_outputs", "yeni_coin_v5")
RUNS = {"BASE_N50_X5_L": ("N50_X5_L", None, None), "T1": ("N50_X5_L", 10, None),
        "NWK1D_F0": ("N50_X3_LS", None, "F0"), "NWK1D_G1": ("N50_X3_LS", None, "G1")}


def load(data):
    det = json.load(open(os.path.join(data, "mexc_contract_detail.json")))
    syms, excl = {}, {}
    for s in COINS:
        cm = contract_meta(det, s)
        p = os.path.join(data, f"{s}_1d.csv")
        if cm is None or not os.path.exists(p):
            excl[s] = "MEXC_METADATA_YOK" if cm is None else "VERI_YOK"
            continue
        k = pd.read_csv(p).sort_values("open_time")
        k = k[(k.high >= k[["open", "close"]].max(axis=1)) & (k.low <= k[["open", "close"]].min(axis=1)) & (k.low > 0)]
        f = pd.read_csv(os.path.join(data, f"{s}_funding.csv"))
        ft = pd.to_numeric(f.iloc[:, 0], errors="coerce").to_numpy()
        fr = pd.to_numeric(f.iloc[:, 1], errors="coerce").to_numpy()
        ok = np.isfinite(ft) & np.isfinite(fr)
        o = np.argsort(ft[ok])
        tick, cs, vu, mv, _ = cm
        syms[s] = E.Sym(s, k.open_time.to_numpy("int64"), *(k[c].to_numpy(float) for c in ("open", "high", "low", "close")),
                        tick, cs, vu, mv, ft[ok][o].astype("int64"), fr[ok][o], v=k.volume.to_numpy(float))
    return syms, excl


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    a = ap.parse_args(argv)
    syms, excl = load(a.data)
    w = (T0, B2)
    hashes = {f: sha_bytes(open(os.path.join(a.data, f), "rb").read()) for f in sorted(os.listdir(a.data))}
    man = dict(spec="YENI_COIN_V5 (MANIFEST_V5.md)", commit=git("rev-parse", "HEAD"),
               dirty=bool(git("status", "--porcelain")), data_hashes=hashes, coins=sorted(syms), excluded=excl,
               window=[t2s(T0), t2s(B2)], final_opened=False)
    mh = sha_bytes(json.dumps(man, sort_keys=True, default=_js).encode())
    rid = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{(man['commit'] or 'x')[:8]}_{mh[:8]}"
    out = os.path.join(OUT, rid)
    os.makedirs(out, exist_ok=True)
    write_json(os.path.join(out, "experiment_manifest.json"), dict(man, run_id=rid, manifest_hash=mh))
    res, eqs = {}, {}
    for k, (vid, early, filt) in RUNS.items():
        sg = E.nwk_entries(syms, filt=filt) if filt else None
        mm = []
        for cost in (C.TWIN_MARKET_PROFILE, C.TWIN_MARKET_PROFILE.stress()):
            tr, bl, eq, led, op = E.simulate(vid, w, syms, cost, early_days=early,
                                             entry="NWK" if sg else "DONCHIAN", entry_sigs=sg)
            m = metrics(tr, eq, w, "YENI_COIN", led)
            m.update(variant_id=k, cost=cost.name,
                     blocked=pd.Series([b["reason"] for b in bl]).value_counts().to_dict() if bl else {})
            p = os.path.join(out, f"{k}_{cost.name}")
            write_csv(os.path.join(p, "trades.csv"), pd.DataFrame(tr))
            write_json(os.path.join(p, "metrics.json"), m)
            mm.append(m)
            if cost.name == "NORMAL":
                eqs[k] = eq
        res[k] = mm
    def held(k):
        n, s = res[k]
        r = n.get("expectancy_net_R")
        return dict(normal_pos=n["net_USDT"] > 0, stress_pos=s["net_USDT"] > 0,
                    meanR_pos=isinstance(r, float) and r > 0, LCB_pos=bool(n["LCB"] is not None and n["LCB"] > 0))
    verdict = {k: held(k) for k in ("T1", "NWK1D_G1")}
    for k in verdict:
        verdict[k]["TUTTU"] = all(verdict[k].values())
    g, f0 = res["NWK1D_G1"][0], res["NWK1D_F0"][0]
    g1_ok = (isinstance(g.get("expectancy_net_R"), float) and isinstance(f0.get("expectancy_net_R"), float)
             and g["expectancy_net_R"] > f0["expectancy_net_R"] and g["net_USDT"] >= 0.75 * f0["net_USDT"])
    tab = {k: {c: {f: v[i].get(f) for f in ("closed", "expectancy_net_R", "return_pct", "MDD_close_pct", "win_rate",
                                            "LCB", "years", "best_trade_R")} for i, c in enumerate(("NORMAL", "STRESS"))}
           for k, v in res.items()}
    summ = dict(run_id=rid, manifest_hash=mh, coins=sorted(syms), excluded=excl, table=tab, verdict=verdict,
                G1_consistent=bool(g1_ok), paket=combined(eqs["T1"], eqs["NWK1D_G1"]))
    write_json(os.path.join(out, "decision.json"), summ)
    print(json.dumps(summ, indent=1, default=_js))
    return out


if __name__ == "__main__":
    main()
