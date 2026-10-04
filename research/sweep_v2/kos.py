"""SWEEP_V2 koşucusu (ONKAYIT.md): `PYTHONPATH=. python3 -m research.sweep_v2.kos --kalabalik <veri/kalabalik/veri>`"""
from __future__ import annotations

import argparse, copy, json, math, os, subprocess
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from research.liquidity_sweep_v1 import config as C, data_contract as D, metrics as MT, replay_adapter as RA
from research.liquidity_sweep_v1 import selection as SL, setups as SU, indicators_adapter as I
from research.liquidity_sweep_v1.cli import World
from research.kalabalik_v1.motor import kalabalik_ozellik

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VERI = os.path.join(KOK, "research_data", "liquidity_sweep_v1", "veri")
TABAN = "L3_K2_F0"
FILTRELER = ["MTF", "SEANS", "HACIM", "RETEST", "ORDERBOOK", "OI", "KALABALIK"]
VARYANTLAR = ["TABAN"] + FILTRELER + ["HEPSI"]
MAL = {"NORMAL": C.TWIN_MARKET_PROFILE, "STRESS": C.TWIN_MARKET_PROFILE.stress()}
YUZDELIK = 0.28                  # 9 varyant, Bonferroni %95 tek taraflı: 5/9 ≈ 0.56 → iki yönlü yerine tek: 0.28 muhafazakâr


class Ek:
    """Sinyal anında bilinen ek seriler (her sembol)."""

    def __init__(self, W, kdir):
        self.W = W
        self.mtf = {}
        for s, dv in W.derived.items():
            sd = dv.sd
            o4, h4, l4, c4, v4 = D.resample(sd, 48)
            od, hd, ld, cd, vd = D.resample(sd, C.GRID_PER_DAY)
            self.mtf[s] = dict(c4=c4, e4=I.ema(c4, 200), cd=cd, ed=I.ema(cd, 50), g0=sd.g0)
        # 15m hacim: 5m hacimlerin toplamı (D.resample'in 5. çıktısı geçerlilik maskesidir, hacim DEĞİL)
        self.v15 = {}
        for s, dv in W.derived.items():
            sd = dv.sd
            n = (sd.n5 // 3) * 3
            v = np.where(sd.valid5[:n], sd.v[:n], np.nan).reshape(-1, 3).sum(1)
            gecerli = sd.valid5[:n].reshape(-1, 3).all(1)
            self.v15[s] = np.where(gecerli, v, np.nan)
        self.ob, self.oi, self.kal = {}, {}, {}
        for s in W.derived:
            p = os.path.join(kdir, f"{s}_bookdepth_5m.csv.gz")
            if os.path.exists(p):
                self.ob[s] = pd.read_csv(p)
            p = os.path.join(kdir, f"{s}_metrics_15m.csv.gz")
            if os.path.exists(p):
                self.oi[s] = pd.read_csv(p)[["t_kapanis", "sum_open_interest"]].dropna()
            p = os.path.join(kdir, f"{s}_metrics_1h.csv.gz")
            if os.path.exists(p):
                self.kal[s] = kalabalik_ozellik(pd.read_csv(p))

    @staticmethod
    def _son(df, col_t, t, maks_gecikme):
        if df is None or df.empty:
            return None
        tt = df[col_t].to_numpy("int64")
        i = int(np.searchsorted(tt, t, "right")) - 1
        if i < 0 or t - tt[i] > maks_gecikme:
            return None
        return i

    def mtf_ok(self, r):
        m = self.mtf[r.symbol]
        k4 = (r.signal_time - m["g0"]) // (4 * C.H1) - 1          # son TAMAMLANMIŞ 4h
        kd = (r.signal_time - m["g0"]) // C.DAY - 1
        if k4 < 0 or kd < 0 or not (np.isfinite(m["e4"][k4]) and np.isfinite(m["ed"][kd])):
            return False
        lng = r.side == "LONG"
        a = m["c4"][k4] > m["e4"][k4] and m["cd"][kd] > m["ed"][kd]
        b = m["c4"][k4] < m["e4"][k4] and m["cd"][kd] < m["ed"][kd]
        return a if lng else b

    def seans_ok(self, r):
        h = (r.signal_time // C.H1) % 24
        return 7 <= h < 21

    def hacim_ok(self, r):
        dv = self.W.derived[r.symbol]
        v15 = self.v15[r.symbol]
        j = (r.sweep_open - dv.sd.g0) // C.M15
        if j < 48 or j >= len(v15):
            return False
        onceki = v15[j - 48:j]
        onceki = onceki[np.isfinite(onceki)]
        return len(onceki) >= 24 and np.isfinite(v15[j]) and v15[j] >= 1.5 * np.median(onceki)

    def ob_ok(self, r):
        df = self.ob.get(r.symbol)
        i = self._son(df, "t_kapanis", r.signal_time, 10 * C.MIN)
        if i is None or "imb1" not in df.columns or not np.isfinite(df["imb1"].iat[i]):
            return None
        return df["imb1"].iat[i] > 0 if r.side == "LONG" else df["imb1"].iat[i] < 0

    def oi_ok(self, r):
        df = self.oi.get(r.symbol)
        i = self._son(df, "t_kapanis", r.signal_time, 20 * C.MIN)
        j = self._son(df, "t_kapanis", r.signal_time - C.H1, 20 * C.MIN)
        if i is None or j is None:
            return None
        return df["sum_open_interest"].iat[i] < df["sum_open_interest"].iat[j]

    def kal_ok(self, r):
        f = self.kal.get(r.symbol)
        i = self._son(f, "t", r.signal_time, 2 * C.H1)
        if i is None or not np.isfinite(f["z_per"].iat[i]):
            return None
        z = f["z_per"].iat[i]
        return z < 0 if r.side == "LONG" else z > 0


def retest(W, r, seviye):
    """K2 sinyalinden sonra en fazla 12 adet 5m mumda seviyeye dokunup doğru tarafta kapanış → yeni sinyal."""
    dv = W.derived[r.symbol]
    sd = dv.sd
    k0 = (r.signal_time - sd.g0) // C.M5                     # sinyal anında başlayan ilk 5m mum
    lng = r.side == "LONG"
    tol = 0.10 * r.ATR15_frozen
    for k in range(k0, min(k0 + 12, sd.n5)):
        if not sd.valid5[k]:
            return None
        if (lng and sd.l[k] <= seviye + tol and sd.c[k] > seviye) or \
                (not lng and sd.h[k] >= seviye - tol and sd.c[k] < seviye):
            E = float(sd.c[k])
            S_raw, S, T_raw, T, ok = SU.stop_target(lng, r.sweep_extreme, r.ATR15_frozen, E, sd.tick)
            if not ok:
                return None
            y = copy.copy(r)
            y.retest_time = int(sd.t_open(k) + C.M5)
            y.signal_time = y.retest_time
            y.E_plan, y.S_raw, y.S, y.T_raw, y.T = E, S_raw, S, T_raw, T
            return y
    return None


def sinyaller(W, ek, seviye_fiyat, varyant, phase):
    recs, sig = W.signals(TABAN, phase)
    a, b = W.window(phase)
    filt = FILTRELER if varyant == "HEPSI" else ([] if varyant == "TABAN" else [varyant])
    out, kapsam_disi = [], 0
    for r in sig:
        y = r
        if "RETEST" in filt:
            y = retest(W, r, seviye_fiyat[r.market_event_id])
            if y is None or not (a <= y.signal_time < b):
                continue
        tamam = True
        for f in filt:
            if f == "RETEST":
                continue
            v = {"MTF": ek.mtf_ok, "SEANS": ek.seans_ok, "HACIM": ek.hacim_ok, "ORDERBOOK": ek.ob_ok,
                 "OI": ek.oi_ok, "KALABALIK": ek.kal_ok}[f](y)
            if v is None:
                kapsam_disi += 1
                tamam = False
                break
            if not v:
                tamam = False
                break
        if tamam:
            out.append(y)
    return recs, out, kapsam_disi


def alt_sinir(trades, a, b, yuzdelik=YUZDELIK, reps=10_000, blok=4, tohum=20261001):
    df = pd.DataFrame(trades) if trades else pd.DataFrame(columns=["exit_interval_start", "net_R"])
    w, S, N = MT.weekly_SN(df, a, b)
    W_ = len(S)
    if W_ == 0 or N.sum() == 0:
        return float("nan")
    rng = np.random.default_rng(tohum)
    nb = math.ceil(W_ / blok)
    st = rng.integers(0, W_, size=(reps, nb))
    idx = ((st[:, :, None] + np.arange(blok)[None, None, :]) % W_).reshape(reps, nb * blok)[:, :W_]
    sS, sN = S[idx].sum(1), N[idx].sum(1)
    ok = sN > 0
    return float(np.percentile(sS[ok] / sN[ok], yuzdelik))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--kalabalik", required=True)
    a = ap.parse_args(argv)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=KOK).stdout.strip()
    rid = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{commit[:8]}"
    out = os.path.join(KOK, "research_outputs", "sweep_v2", rid)
    os.makedirs(out, exist_ok=True)
    W = World(VERI)
    beklenen = dict(T0="2023-02-12", B1="2025-04-18", B2="2026-01-08")
    for k, v in beklenen.items():
        if str(pd.to_datetime(W.dates[k], unit="ms").date()) != v:
            raise SystemExit(f"dönem sınırı {k} beklenenden farklı")
    ek = Ek(W, a.kalabalik)
    seviye = {e.market_event_id: e.level_price for evs in W.events["L3"].values() for e in evs}
    sonuc, disc, val = {}, {}, {}
    for phase in ("DISCOVERY", "VALIDATION"):
        win = W.window(phase)
        for v in VARYANTLAR:
            recs, sig, kd = sinyaller(W, ek, seviye, v, phase)
            mm = []
            for mal, prof in MAL.items():
                res = RA.simulate(f"V2_{v}", phase, win, sig, W.U, prof, C.C0_FALLBACK, record_equity=True)
                m = MT.run_metrics(res, sig, win, C.C0_FALLBACK, phase)
                m.update(variant_id=v, cost_scenario=mal, signals=len(sig), kapsam_disi=kd)
                if mal == "NORMAL":
                    m["alt_sinir_bonferroni"] = alt_sinir(res.trades, *win)
                    pd.DataFrame(res.trades).to_csv(os.path.join(out, f"islemler_{phase}_{v}.csv"), index=False)
                mm.append({k: x for k, x in m.items() if k != "flags"})
            (disc if phase == "DISCOVERY" else val)[v] = tuple(mm)
            sonuc[f"{phase}|{v}"] = dict(NORMAL={k: mm[0].get(k) for k in ("signals", "closed", "expectancy_net_R", "LCB",
                                                                           "alt_sinir_bonferroni", "net_USDT", "kapsam_disi",
                                                                           "MDD_close_pct", "expectancy_gross_R")},
                                         STRESS={k: mm[1].get(k) for k in ("expectancy_net_R", "net_USDT")})
            print(phase, v, sonuc[f"{phase}|{v}"]["NORMAL"], flush=True)
    sec, satir = SL.select(disc, "DISCOVERY")
    vsec, vsatir = SL.select({k: val[k] for k in val}, "VALIDATION")
    karar = {}
    for v in VARYANTLAR:
        n = val[v][0]
        r = n.get("expectancy_net_R")
        ok = (v in vsec and isinstance(r, float) and r > 0 and val[v][1].get("net_USDT", -1) > 0
              and np.isfinite(n.get("alt_sinir_bonferroni", np.nan)) and n["alt_sinir_bonferroni"] > 0)
        karar[v] = "TUTTU" if ok else ("ÖRNEK AZ" if (n.get("closed") or 0) < 30 else "ELENDİ")
    json.dump(dict(run_id=rid, commit=commit, kesif_secilen=sec, kesif_satir=satir, dogrulama_secilen=vsec,
                   dogrulama_satir=vsatir, karar=karar, sonuc=sonuc), open(os.path.join(out, "ozet.json"), "w"),
              indent=1, ensure_ascii=False, default=str)
    print(out)
    print(json.dumps(karar, ensure_ascii=False))


if __name__ == "__main__":
    main()
