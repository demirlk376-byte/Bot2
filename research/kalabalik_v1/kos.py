"""KALABALIK_V1 koşucusu: `PYTHONPATH=. python3 -m research.kalabalik_v1.kos --metrics <veri/kalabalik/veri>`"""
from __future__ import annotations

import argparse, json, os, subprocess, math
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from research.liquidity_sweep_v1 import config as C, metrics as MT
from research.trend_gelistirme.veri import yukle, BOT12, KOK
from research.trend_takip_v1 import run_v5 as V5
from research.kalabalik_v1.motor import Motor, kalabalik_ozellik

ms = lambda s: int(pd.Timestamp(s, tz="UTC").timestamp() * 1000)
KES_A, KES_B, DOG_B = ms("2022-02-01"), ms("2024-06-14"), ms("2025-08-08")
MAL = {"NORMAL": C.TWIN_MARKET_PROFILE, "STRESS": C.TWIN_MARKET_PROFILE.stress()}
YUZDELIK = 1.25                       # iki varyant, Bonferroni (%95 iki taraflı → her biri %97.5)


def bootstrap_alt(tr, a, b, yuzdelik=YUZDELIK, reps=10_000, blok=4, tohum=20261001):
    df = pd.DataFrame(tr) if len(tr) else pd.DataFrame(columns=["exit_interval_start", "net_R"])
    w, S, N = MT.weekly_SN(df, a, b)
    W = len(S)
    if W == 0 or N.sum() == 0:
        return float("nan"), 0
    rng = np.random.default_rng(tohum)
    nb = math.ceil(W / blok)
    st = rng.integers(0, W, size=(reps, nb))
    idx = ((st[:, :, None] + np.arange(blok)[None, None, :]) % W).reshape(reps, nb * blok)[:, :W]
    sS, sN = S[idx].sum(1), N[idx].sum(1)
    ok = sN > 0
    return float(np.percentile(sS[ok] / sN[ok], yuzdelik)), int(N.sum())


def olc(tr, a, b):
    t = [x for x in tr if a <= x["cikis_t"] < b]
    r = np.array([x["net_R"] for x in t]) if t else np.zeros(0)
    lcb, n = bootstrap_alt(t, a, b)
    return dict(n=len(t), ort_R=float(r.mean()) if len(r) else float("nan"), net=float(sum(x["net_PnL"] for x in t)),
                kazanan=float((r > 0).mean()) if len(r) else float("nan"), alt_sinir=lcb)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--metrics", required=True)
    a = ap.parse_args(argv)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=KOK).stdout.strip()
    rid = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{commit[:8]}"
    out = os.path.join(KOK, "research_outputs", "kalabalik_v1", rid)
    os.makedirs(out, exist_ok=True)
    sonuc = {}
    for evren, coinler in (("bot12", BOT12), ("diger24", V5.COINS)):
        veri, dis = yukle(coinler)
        oz = {}
        for k in list(veri):
            p = os.path.join(a.metrics, f"{k}_metrics_1h.csv.gz")
            if os.path.exists(p):
                oz[k] = kalabalik_ozellik(pd.read_csv(p))
        kapsam = {k: (str(pd.to_datetime(v.t.iloc[0], unit="ms").date()) if len(v) else None) for k, v in oz.items()}
        for v in ("H1", "H2"):
            for mal, prof in MAL.items():
                m = Motor({k: c for k, c in veri.items() if k in oz}, oz, v, prof, KES_A, DOG_B).kos()
                pd.DataFrame(m.islemler).to_csv(os.path.join(out, f"islemler_{evren}_{v}_{mal}.csv"), index=False)
                sonuc[f"{evren}|{v}|{mal}"] = dict(KESIF=olc(m.islemler, KES_A, KES_B), DOGRULAMA=olc(m.islemler, KES_B, DOG_B),
                                                   TUMU=olc(m.islemler, KES_A, DOG_B), kapsam=kapsam, dislanan=dis)
    karar = {}
    for v in ("H1", "H2"):
        d12, d24 = sonuc[f"bot12|{v}|NORMAL"]["DOGRULAMA"], sonuc[f"diger24|{v}|NORMAL"]["TUMU"]
        s12, s24 = sonuc[f"bot12|{v}|STRESS"]["DOGRULAMA"], sonuc[f"diger24|{v}|STRESS"]["TUMU"]
        if d12["n"] < 30 or d24["n"] < 30:
            karar[v] = "D (örnek yetersiz)"
        else:
            ok = (d12["ort_R"] > 0 and d12["alt_sinir"] > 0 and d24["ort_R"] > 0 and d24["alt_sinir"] > 0
                  and s12["net"] > 0 and s24["net"] > 0)
            karar[v] = "TUTTU" if ok else "ELENDİ"
    json.dump(dict(run_id=rid, commit=commit, karar=karar, sonuc=sonuc), open(os.path.join(out, "ozet.json"), "w"),
              indent=1, ensure_ascii=False, default=str)
    print(out)
    print(json.dumps(karar, ensure_ascii=False))


if __name__ == "__main__":
    main()
