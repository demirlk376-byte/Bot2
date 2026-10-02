"""
NW+KAMA V2 koşucusu — `python3 -m research.nw_kama_v2.run [--data DIR] [--out DIR]`
freeze → keşif (24 varyant × NORMAL/STRESS) → seçim → doğrulama → final → karar.
Yürütme, muhasebe, metrik ve seçim: research.liquidity_sweep_v1 (aynı kod, aynı kurallar).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from research.liquidity_sweep_v1 import config as C, data_contract as D, metrics as MT, replay_adapter as RA
from research.liquidity_sweep_v1 import selection as SL
from research.liquidity_sweep_v1.cli import atomic_write, write_json, write_csv, sha_bytes, git, _js, t2s
from research.nw_kama_v2 import signals as SG

PKG = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(PKG))
DEFAULT_DATA = os.path.join(ROOT, "research_data", "liquidity_sweep_v1", "veri")
DEFAULT_OUT = os.path.join(ROOT, "research_outputs", "nw_kama_v2")
PHASES = ("DISCOVERY", "VALIDATION", "FINAL")


def code_hashes():
    files = [os.path.join(PKG, f) for f in sorted(os.listdir(PKG)) if f.endswith(".py")]
    sw = os.path.join(ROOT, "research", "liquidity_sweep_v1")
    files += [os.path.join(sw, f) for f in sorted(os.listdir(sw)) if f.endswith(".py")]
    files += [os.path.join(ROOT, "validate_nw_kama.py"), os.path.join(ROOT, "backtest_nw_kama.py")]
    return {os.path.relpath(f, ROOT): sha_bytes(open(f, "rb").read()) for f in files}


def run_variant(U, dates, sig_cache, vid, phase, cost, out=None):
    a, b = dates[phase]
    if vid not in sig_cache:
        sig_cache[vid] = SG.build(U, vid)
    sig = [r for r in sig_cache[vid] if a <= r.signal_time < b]
    res = RA.simulate(vid, phase, (a, b), sig, U, cost, C.C0_FALLBACK, record_equity=True,
                      max_hold_ms=SG.max_hold_ms(vid))
    m = MT.run_metrics(res, sig, (a, b), C.C0_FALLBACK, phase)
    m.update(variant_id=vid, cost_scenario=cost.name, signals=len(sig))
    nets = [t["net_PnL"] for t in res.trades]
    if out:
        d = os.path.join(out, phase, f"{vid}_{cost.name}")
        write_csv(os.path.join(d, "trades.csv"), pd.DataFrame(res.trades))
        write_json(os.path.join(d, "metrics.json"), {k: v for k, v in m.items() if k != "flags"})
    return m, nets


def phase_run(U, dates, cache, vids, phase, out):
    res, nets = {}, {}
    for i, vid in enumerate(vids):
        mN, nN = run_variant(U, dates, cache, vid, phase, C.TWIN_MARKET_PROFILE, out)
        mS, _ = run_variant(U, dates, cache, vid, phase, C.TWIN_MARKET_PROFILE.stress(), out)
        res[vid], nets[vid] = (mN, mS), nN
        print(f"{datetime.now(timezone.utc):%H:%M:%S} {phase} {i + 1}/{len(vids)} {vid}", flush=True)
    return res, nets


def strip(m):
    return {k: v for k, v in m.items() if k not in ("flags",)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--out", default=DEFAULT_OUT)
    a = ap.parse_args(argv)
    t0 = time.time()
    U = D.build_universe(a.data)
    dates = D.partition_dates(U)
    # önceden kayıtla birebir: kaynak, evren ve dönem sınırları değişmişse koşma
    if U["source"] != "binance_5m" or set(U["symbols"]) != set(C.UNIVERSE) or dates is None:
        raise SystemExit(f"veri ön-kayıttan farklı: source={U['source']} excluded={U['excluded']}")
    beklenen = dict(T0="2023-02-12", B1="2025-04-18", B2="2026-01-08", T1="2026-10-01")
    for k, v in beklenen.items():
        if t2s(dates[k])[:10] != v:
            raise SystemExit(f"dönem sınırı {k} ön-kayıttan farklı: {t2s(dates[k])} != {v}")
    man = dict(spec="NW_KAMA_V2_2026-10-02 (MANIFEST.md)", base_commit=git("rev-parse", "HEAD"),
               dirty=bool(git("status", "--porcelain")), source_hashes=code_hashes(), data_hashes=U["raw_hashes"],
               source_exchange=f"{U['source']} (BINANCE_USDM = MEXC venue vekili)",
               active_universe=list(U["symbols"]), excluded=U["excluded"],
               dates={k: t2s(dates[k]) for k in ("T0", "B1", "B2", "T1")}, variant_ids=SG.VARIANT_IDS,
               params=dict(TFS=SG.TFS, MODES=SG.MODES, PARAMS=SG.PARAMS, SL_ATR=SG.SL_ATR, TP_ATR=SG.TP_ATR,
                           MAX_HOLD_BARS=SG.MAX_HOLD_BARS),
               cost=C.TWIN_MARKET_PROFILE.as_dict(), stress=C.TWIN_MARKET_PROFILE.stress().as_dict(),
               risk=dict(C0=C.C0_FALLBACK, per_trade=C.PER_TRADE_RISK_FRAC * C.C0_FALLBACK,
                         cap=C.PORTFOLIO_RISK_CAP_FRAC * C.C0_FALLBACK, gates=C.LIVE_GATES),
               previous_data_use="previously_examined (tüm dönemler; FİNAL bağımsız değil)")
    mh = sha_bytes(json.dumps(man, sort_keys=True, default=_js).encode())
    run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{(man['base_commit'] or 'nogit')[:8]}_{mh[:8]}"
    man.update(run_id=run_id, manifest_hash=mh)
    out = os.path.join(a.out, run_id)
    os.makedirs(out, exist_ok=True)
    write_json(os.path.join(out, "experiment_manifest.json"), man)
    print("manifest", run_id, flush=True)
    cache = {}
    disc, _ = phase_run(U, dates, cache, SG.VARIANT_IDS, "DISCOVERY", out)
    sel, rows = SL.select(disc, "DISCOVERY")
    write_json(os.path.join(out, "selection_discovery.json"),
               dict(manifest_hash=mh, selected=sel, rows=rows,
                    metrics={v: dict(NORMAL=strip(x[0]), STRESS=strip(x[1])) for v, x in disc.items()}))
    val_rows, chosen, fin = [], [], None
    if sel:
        val, _ = phase_run(U, dates, cache, sel, "VALIDATION", out)
        chosen, val_rows = SL.select(val, "VALIDATION")
        write_json(os.path.join(out, "selection_final.json"),
                   dict(manifest_hash=mh, candidates=sel, selected=chosen, rows=val_rows,
                        metrics={v: dict(NORMAL=strip(x[0]), STRESS=strip(x[1])) for v, x in val.items()}))
    if chosen:
        f, nets = phase_run(U, dates, cache, chosen, "FINAL", out)
        vid = chosen[0]
        top5 = float(sum(sorted(nets[vid], reverse=True)[5:]))
        dec, why = SL.final_decision(*f[vid], top5, False)
        fin = dict(candidate=vid, decision=dec, reason=why, top5_removed_net_USDT=top5,
                   metrics=dict(NORMAL=strip(f[vid][0]), STRESS=strip(f[vid][1])))
    if fin:
        decision, why = fin["decision"], fin["reason"]
    else:
        decision, why = SL.overall_without_final(rows, val_rows)
    summ = dict(run_id=run_id, manifest_hash=mh, decision=decision, reason=why, discovery_selected=sel,
                final_selected=chosen, final=fin,
                discovery_status_counts=pd.Series([r["reason"] for r in rows]).value_counts().to_dict(),
                minutes=round((time.time() - t0) / 60, 1))
    write_json(os.path.join(out, "decision.json"), summ)
    print(json.dumps(summ, indent=1, ensure_ascii=False, default=_js))
    return out, summ


if __name__ == "__main__":
    main()
