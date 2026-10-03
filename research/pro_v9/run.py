"""PRO_V9 koşucusu: `python3 -m research.pro_v9.run` — kurallar MANIFEST.md."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from research.liquidity_sweep_v1 import config as C, metrics as MT
from research.liquidity_sweep_v1.cli import write_json, sha_bytes, git, _js, t2s
from research.trend_takip_v1 import engine as E, run_v5 as V5, run_v6 as V6
from research.trend_takip_v1.run import T0, load as load_old1d, DEF_DATA, DEF_META, ROOT
from research.trend_takip_v1.run_v7 import D4, D1N, B2
from research.pro_v9 import strat as S

OUT = os.path.join(ROOT, "research_outputs", "pro_v9")
W = (T0, B2)
XS = [f"XS_L{L}_{m}" for L in (28, 56) for m in ("LS", "L")]
FC = {"FC_T1": 0.0001, "FC_T2": 0.0002, "FC_T3": 0.0003}
C0 = C.C0_FALLBACK


def series(curve):
    return pd.Series({t: p for t, p in curve}).sort_index()


def stats(curve, weekly):
    p = series(curve)
    eq = C0 + p.to_numpy()
    mdd = MT.mdd_and_underwater(p.index.to_numpy(), eq, C0)[0]
    weeks = MT.full_weeks(*W)
    Sw = np.array([weekly.get(int(w), 0.0) / S.UNIT for w in weeks])
    bs = MT.block_bootstrap(Sw, np.ones(len(Sw)))
    yrs = {int(y): round(float(v) / 100, 2) for y, v in
           p.diff().fillna(p.iloc[0]).groupby(pd.to_datetime(p.index - 1, unit="ms").year).sum().items()}
    return dict(return_pct=float(p.iloc[-1] / C0 * 100), MDD_pct=float(mdd), LCB_week_units=bs["lcb"], years=yrs)


def run_xs(syms, v, cost):
    _, L, m = v.split("_")
    return S.xs_momentum(syms, W, int(L[1:]), m, cost)


def run_fc(syms, v, cost):
    return S.funding_carry(syms, W, FC[v], cost)


def both(fn, syms, v):
    n = fn(syms, v, C.TWIN_MARKET_PROFILE)
    s = fn(syms, v, C.TWIN_MARKET_PROFILE.stress())
    return dict(NORMAL=dict(stats(n[0], n[1]), trades=n[2]), STRESS=stats(s[0], s[1])), n[0]


def trend_curve(s1, s4, reg):
    out = []
    for N, bar, sy in ((50, C.DAY, s1), (180, V6.H4, s4)):
        eq = E.simulate(f"N{N}_X5_L", W, sy, C.TWIN_MARKET_PROFILE, early_days=10, bar_ms=bar, regime=reg, pyr_adds=2)[2]
        out.append(pd.Series({t: e - C0 for t, e, *_ in eq}))
    return out


def combine(parts):
    ix = sorted(set().union(*[p.index for p in parts]))
    tot = sum(p.reindex(ix).ffill().fillna(0.0) for p in parts)
    eq = C0 + tot.to_numpy()
    peak = np.maximum.accumulate(np.r_[C0, eq])[1:]
    yrs = {int(y): round(float(v) / 100, 2) for y, v in
           tot.diff().fillna(tot.iloc[0]).groupby(pd.to_datetime(np.array(ix) - 1, unit="ms").year).sum().items()}
    return dict(return_pct=float(tot.iloc[-1] / C0 * 100), MDD_pct=float((100 * (peak - eq) / peak).max()), years=yrs)


def main():
    old1 = load_old1d(DEF_DATA, DEF_META)
    new1, exn = V5.load(D1N)
    old4, _ = V6.load(D4, V6.OLD, "4h")
    new4, _ = V6.load(D4, V6.NEW, "4h")
    reg = E.regime_ma(old1["ETH"])
    code = {f: sha_bytes(open(os.path.join(os.path.dirname(__file__), f), "rb").read())
            for f in sorted(os.listdir(os.path.dirname(__file__))) if f.endswith((".py", ".md"))}
    man = dict(spec="PRO_V9 (MANIFEST.md)", commit=git("rev-parse", "HEAD"), dirty=bool(git("status", "--porcelain")),
               code_hashes=code, window=[t2s(T0), t2s(B2)], XS=XS, FC=FC, excluded_new=exn)
    mh = sha_bytes(json.dumps(man, sort_keys=True, default=_js).encode())
    rid = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{(man['commit'] or 'x')[:8]}_{mh[:8]}"
    out = os.path.join(OUT, rid)
    os.makedirs(out, exist_ok=True)
    write_json(os.path.join(out, "experiment_manifest.json"), dict(man, run_id=rid, manifest_hash=mh))
    res = {"ESKI12": {}, "YENI24": {}}
    curves = {"ESKI12": {}, "YENI24": {}}
    for k, sy in (("ESKI12", old1), ("YENI24", new1)):
        for v in XS:
            res[k][v], curves[k][v] = both(run_xs, sy, v)
        for v in FC:
            res[k][v], curves[k][v] = both(run_fc, sy, v)
        print(f"{datetime.now(timezone.utc):%H:%M:%S} {k}", flush=True)
    r = res["ESKI12"]
    ok_xs = [v for v in XS if r[v]["NORMAL"]["return_pct"] > 0 and r[v]["STRESS"]["return_pct"] > 0]
    xs = max(ok_xs, key=lambda v: r[v]["NORMAL"]["return_pct"] / max(r[v]["NORMAL"]["MDD_pct"], 1e-9)) if ok_xs else None
    ok_fc = [v for v in FC if r[v]["STRESS"]["return_pct"] > 0]
    fc = max(ok_fc, key=lambda v: r[v]["NORMAL"]["return_pct"]) if ok_fc else None
    verdict = {}
    tp = {"ESKI12": trend_curve(old1, old4, reg), "YENI24": trend_curve(new1, new4, reg)}
    base = {k: combine(tp[k]) for k in tp}
    for name, v in (("XS", xs), ("FC", fc)):
        if v is None:
            verdict[name] = dict(chosen=None, decision="ELENDİ")
            continue
        n, s = res["YENI24"][v]["NORMAL"], res["YENI24"][v]["STRESS"]
        tut = n["return_pct"] > 0 and s["return_pct"] > 0 and n["LCB_week_units"] > 0
        cb = {k: combine(tp[k] + [series(curves[k][v])]) for k in tp}
        verdict[name] = dict(chosen=v, TUTTU=bool(tut), combined=cb,
                             sepete_katki={k: cb[k]["return_pct"] / cb[k]["MDD_pct"] > base[k]["return_pct"] / base[k]["MDD_pct"]
                                           for k in tp})
    hepsi = {k: combine(tp[k] + [series(curves[k][v]) for v in (xs, fc) if v]) for k in tp}
    summ = dict(run_id=rid, manifest_hash=mh, results=res, chosen=dict(XS=xs, FC=fc), verdict=verdict,
                trend_P=base, trend_P_plus_all=hepsi)
    write_json(os.path.join(out, "decision.json"), summ)
    print(out)


if __name__ == "__main__":
    main()
