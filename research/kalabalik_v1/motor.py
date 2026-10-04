"""KALABALIK_V1 motoru (ONKAYIT.md): 4h ortak saat, coin başına tek pozisyon, 72s/2×ATR çıkış, %0.25 sabit risk."""
from __future__ import annotations

import os
import numpy as np
import pandas as pd

from research.liquidity_sweep_v1.accounting import entry_fill, exit_fill, floor_step
from research.trend_gelistirme.motor import atr_wilder

H4 = 4 * 3_600_000
DAY = 86_400_000
Z_PENCERE = 720
TUTUS = 18
STOP_ATR = 2.0
RISK = 25.0
TAVAN = 12 * RISK


def zskor(seri: pd.Series, n=Z_PENCERE):
    m = seri.rolling(n, min_periods=n).mean()
    s = seri.rolling(n, min_periods=n).std()
    return (seri - m) / s


def kalabalik_ozellik(metrics_1h: pd.DataFrame) -> pd.DataFrame:
    d = metrics_1h.sort_values("t_kapanis").reset_index(drop=True)
    out = pd.DataFrame({"t": d.t_kapanis.astype("int64")})
    out["z_per"] = zskor(d["count_long_short_ratio"].astype(float)).to_numpy()
    out["z_buy"] = zskor(d["sum_toptrader_long_short_ratio"].astype(float)).to_numpy()
    return out


def sinyal(varyant, zp, zb):
    if not (np.isfinite(zp) and np.isfinite(zb)):
        return 0
    if varyant == "H1":
        return -1 if zp >= 2 else (1 if zp <= -2 else 0)
    if varyant == "H2":
        if zb <= -1 and zp >= 1:
            return -1
        if zb >= 1 and zp <= -1:
            return 1
    return 0


class Motor:
    def __init__(self, coins: dict, ozellik: dict, varyant, maliyet, t_bas, t_bit):
        self.coins, self.oz, self.v, self.m = coins, ozellik, varyant, maliyet
        self.t_bas, self.t_bit = t_bas, t_bit
        self.poz, self.bek, self.islemler = {}, {}, []
        self.saat = sorted({int(x) for c in coins.values() for x in c.t if t_bas <= x and x + H4 <= t_bit})
        self.atr = {k: atr_wilder(c.h, c.l, c.c) for k, c in coins.items()}

    def _oz_al(self, k, T):
        f = self.oz.get(k)
        if f is None or f.empty:
            return np.nan, np.nan
        i = int(np.searchsorted(f.t.to_numpy(), T, "right")) - 1
        if i < 0:
            return np.nan, np.nan
        return float(f.z_per.iat[i]), float(f.z_buy.iat[i])

    def _kapat(self, k, ref, t, neden):
        p = self.poz.pop(k)
        c = self.coins[k]
        xf = exit_fill(ref, p["d"], self.m.exit_slip_bp, c.tick)
        brut = p["d"] * (xf - p["E"]) * p["q"]
        uc = abs(xf * p["q"]) * self.m.exit_fee_rate
        net = brut - p["uc"] - uc + p["fund"]
        self.islemler.append(dict(coin=k, yon=p["d"], sinyal_t=p["st"], giris_t=p["t"], cikis_t=t, neden=neden,
                                  E=p["E"], S=p["S"], cikis=xf, q=p["q"], R0=p["R0"], net_PnL=net,
                                  net_R=net / p["R0"], exit_interval_start=t, funding=p["fund"]))

    def kos(self):
        for t in self.saat:
            T = t + H4
            for k in sorted(self.coins):
                c = self.coins[k]
                i = c.idx.get(t)
                if i is None:
                    continue
                O = c.o[i]
                p = self.poz.get(k)
                if p is not None:
                    if (p["d"] > 0 and O <= p["S"]) or (p["d"] < 0 and O >= p["S"]):
                        self._kapat(k, O, t, "STOP_BOSLUK"); p = None
                    elif p.get("cik"):
                        self._kapat(k, O, t, "SURE"); p = None
                b = self.bek.pop(k, None)
                if b is not None and k not in self.poz:
                    d = b["d"]
                    E = entry_fill(O, d, self.m.entry_slip_bp, c.tick)
                    S = E - d * STOP_ATR * b["atr"]
                    dist = abs(E - S)
                    acik = sum(x["R0"] for x in self.poz.values())
                    n = floor_step(RISK / dist / c.cs, c.vu) if dist > 0 else 0
                    if n >= c.mv - 1e-12 and acik + n * c.cs * dist <= TAVAN + 1e-9:
                        q = n * c.cs
                        self.poz[k] = dict(d=d, E=E, S=S, q=q, R0=dist * q, uc=abs(E * q) * self.m.entry_fee_rate,
                                           fund=0.0, t=t, st=b["st"], n=0)
                p = self.poz.get(k)
                if p is not None and p["t"] <= t:
                    if (p["d"] > 0 and c.l[i] <= p["S"]) or (p["d"] < 0 and c.h[i] >= p["S"]):
                        self._kapat(k, p["S"], t, "STOP"); p = None
                if p is not None:
                    a_, b_ = np.searchsorted(c.f_t, t, "right"), np.searchsorted(c.f_t, T, "right")
                    for r in c.f_r[a_:b_]:
                        p["fund"] += -p["d"] * p["q"] * c.o[i] * r
                    p["n"] += 1
                    if p["n"] >= TUTUS:
                        p["cik"] = True
                    continue
                if k in self.bek:
                    continue
                zp, zb = self._oz_al(k, T)
                d = sinyal(self.v, zp, zb)
                if d and np.isfinite(self.atr[k][i]) and self.atr[k][i] > 0 and T + H4 <= self.t_bit:
                    self.bek[k] = dict(d=d, atr=float(self.atr[k][i]), st=T)
        # dönem sonu: açık pozisyonları son açılışta kapat
        for k in list(self.poz):
            c = self.coins[k]
            j = int(np.searchsorted(c.t, self.t_bit, "left")) - 1
            self._kapat(k, float(c.c[j]), int(c.t[j]) + H4, "DONEM_SONU")
        return self
