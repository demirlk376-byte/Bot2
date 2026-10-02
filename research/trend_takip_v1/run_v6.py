"""H4_KIRILIM_V6: `python3 -m research.trend_takip_v1.run_v6 --data4h DIR --data1d DIR` — kurallar MANIFEST_V6.md."""
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
from research.trend_takip_v1 import run_v5 as V5

H4 = 4 * C.H1
OLD = "SOL ETH ADA NEAR BCH XRP DOGE TRX XLM LTC ICP BNB".split()
NEW = V5.COINS
B2 = V5.B2
VARS = [f"H4_N{n}_{x}_{e}" for n in (60, 180) for x in ("X3", "X5") for e in ("E0", "E10")]
T1_REF = dict(return_pct=19.09, MDD=7.07)
OUT = os.path.join(ROOT, "research_outputs", "h4_kirilim_v6")


def load(data, coins, suffix):
    det = json.load(open(os.path.join(data, "mexc_contract_detail.json")))
    syms, excl = {}, {}
    for s in coins:
        cm = contract_meta(det, s)
        p = os.path.join(data, f"{s}_{suffix}.csv")
        if cm is None or not os.path.exists(p):
            excl[s] = "MEXC_METADATA_YOK" if cm is None else "VERI_YOK"
            continue
        k = pd.read_csv(p).sort_values("open_time").drop_duplicates("open_time")
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


def parts(v):
    _, n, x, e = v.split("_")
    return f"N{n[1:]}_{x}_L", (10 if e == "E10" else None)


def run(syms, v, out, tag, bar_ms=H4, early=None, vid=None):
    if vid is None:
        vid, early = parts(v)
    mm, eq_n, tr_n = [], None, None
    for cost in (C.TWIN_MARKET_PROFILE, C.TWIN_MARKET_PROFILE.stress()):
        tr, bl, eq, led, op = E.simulate(vid, (T0, B2), syms, cost, early_days=early, bar_ms=bar_ms)
        m = metrics(tr, eq, (T0, B2), tag, led)
        m.update(variant_id=v, cost=cost.name,
                 blocked=pd.Series([b["reason"] for b in bl]).value_counts().to_dict() if bl else {})
        p = os.path.join(out, tag, f"{v}_{cost.name}")
        write_csv(os.path.join(p, "trades.csv"), pd.DataFrame(tr))
        write_json(os.path.join(p, "metrics.json"), m)
        mm.append(m)
        if cost.name == "NORMAL":
            eq_n, tr_n = eq, tr
    return mm, eq_n, tr_n


def ratio(m):
    return m["return_pct"] / m["MDD_close_pct"] if m["MDD_close_pct"] > 0 else float("inf")


def diag(tr):
    t = pd.DataFrame(tr)
    if t.empty:
        return {}
    r = t.net_PnL.sort_values(ascending=False)
    t["y"] = pd.to_datetime(t.exit_time, unit="ms").dt.year
    return dict(top5_removed_pct=float(r[5:].sum() / 100), by_year_pct=(t.groupby("y").net_PnL.sum() / 100).round(2).to_dict(),
                avg_hold_days=float(t.hold_days.mean()))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data4h", required=True)
    ap.add_argument("--data1d", required=True)
    a = ap.parse_args(argv)
    old, ex_o = load(a.data4h, OLD, "4h")
    new, ex_n = load(a.data4h, NEW, "4h")
    hashes = {f: sha_bytes(open(os.path.join(a.data4h, f), "rb").read()) for f in sorted(os.listdir(a.data4h))}
    man = dict(spec="H4_KIRILIM_V6 (MANIFEST_V6.md)", commit=git("rev-parse", "HEAD"),
               dirty=bool(git("status", "--porcelain")), data_hashes=hashes, old=sorted(old), new=sorted(new),
               excluded=dict(old=ex_o, new=ex_n), variants=VARS, window=[t2s(T0), t2s(B2)], final_opened=False)
    mh = sha_bytes(json.dumps(man, sort_keys=True, default=_js).encode())
    rid = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{(man['commit'] or 'x')[:8]}_{mh[:8]}"
    out = os.path.join(OUT, rid)
    os.makedirs(out, exist_ok=True)
    write_json(os.path.join(out, "experiment_manifest.json"), dict(man, run_id=rid, manifest_hash=mh))
    sel = {}
    for v in VARS:
        sel[v] = run(old, v, out, "SECIM_ESKI12")[0]
        print(f"{datetime.now(timezone.utc):%H:%M:%S} secim {v}", flush=True)
    ok = [v for v in VARS if sel[v][0]["net_USDT"] > 0 and sel[v][1]["net_USDT"] > 0
          and isinstance(sel[v][0].get("expectancy_net_R"), float) and sel[v][0]["expectancy_net_R"] > 0]
    chosen = max(ok, key=lambda v: ratio(sel[v][0])) if ok else None
    test, eqs, trs = {}, {}, {}
    for v in VARS:                                   # hepsi koşulur; KARAR yalnız seçilen varyantla
        test[v], eqs[v], trs[v] = run(new, v, out, "SINAV_YENI")
        print(f"{datetime.now(timezone.utc):%H:%M:%S} sinav {v}", flush=True)
    d1, _ = V5.load(a.data1d)
    t1m, t1eq, t1tr = run(d1, "T1_1D", out, "SINAV_YENI", bar_ms=C.DAY, early=10, vid="N50_X5_L")
    verdict = None
    if chosen:
        n, s = test[chosen]
        r = n.get("expectancy_net_R")
        c = dict(normal_pos=n["net_USDT"] > 0, stress_pos=s["net_USDT"] > 0, meanR_pos=isinstance(r, float) and r > 0,
                 LCB_pos=bool(n["LCB"] is not None and n["LCB"] > 0))
        comb = combined(t1eq, eqs[chosen])
        t1_ratio = t1m[0]["return_pct"] / t1m[0]["MDD_close_pct"]
        verdict = dict(chosen=chosen, checks=c, TUTTU=all(c.values()),
                       T1_den_iyi=bool(n["return_pct"] >= T1_REF["return_pct"] and n["MDD_close_pct"] <= T1_REF["MDD"]),
                       ek_modul_degerli=bool(comb["return_pct"] / comb["MDD_pct"] > t1_ratio),
                       combined_T1_H4=comb, T1_ratio=t1_ratio, T1_reproduced=t1m[0]["return_pct"])
    f = ("closed", "expectancy_net_R", "return_pct", "MDD_close_pct", "win_rate", "LCB", "best_trade_R")
    tab = lambda R: {v: {c: {k: m[i].get(k) for k in f} for i, c in enumerate(("NORMAL", "STRESS"))} for v, m in R.items()}
    summ = dict(run_id=rid, manifest_hash=mh, excluded=dict(old=ex_o, new=ex_n), selection_ok=ok, chosen=chosen,
                verdict=verdict, decision="ELENDİ" if not chosen else ("TUTTU" if verdict["TUTTU"] else "TUTMADI"),
                secim_eski12=tab(sel), sinav_yeni=tab(test), T1_1D_yeni=tab({"T1_1D": t1m})["T1_1D"],
                diag={v: diag(trs[v]) for v in VARS} | {"T1_1D": diag(t1tr)})
    write_json(os.path.join(out, "decision.json"), summ)
    print(out)
    return out


if __name__ == "__main__":
    main()
