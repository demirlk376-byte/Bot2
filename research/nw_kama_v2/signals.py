"""
NW+KAMA V2 sinyal üretimi (MANIFEST.md). Sinyal kuralları DEĞİŞTİRİLMEDEN validate_nw_kama.py'den.
Her sinyal, sweep motorunun anladığı SetupRecord'a çevrilir; yürütme/muhasebe sweep motorundadır.
"""
from __future__ import annotations

import os
import sys

import numpy as np

from research.liquidity_sweep_v1 import config as C, data_contract as D, indicators_adapter as I
from research.liquidity_sweep_v1.setups import SetupRecord, floor_tick, ceil_tick

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import validate_nw_kama as V  # noqa: E402  (sigs, sigs_agree — aynen)

TFS = {"1h": 12, "2h": 24, "4h": 48, "1D": 288}          # 5m bar sayısı
MODES = ("event", "state", "agree")
PARAMS = {"A": dict(h=3, win=15, mult=1.5, er=5, lb={"event": 1, "state": 2, "agree": 0}),
          "B": dict(h=5, win=25, mult=2.0, er=10, lb={"event": 2, "state": 3, "agree": 0})}
SL_ATR, TP_ATR, MAX_HOLD_BARS = 2.0, 4.0, 15
VARIANT_IDS = [f"{tf}_{m}_{p}" for tf in TFS for m in MODES for p in PARAMS]
assert len(VARIANT_IDS) == 24


def tf_bars(sd: D.SymbolData, per: int):
    """5m ızgaradan TF barı; eksik alt bar varsa bar YOK (NaN). Döner o,h,l,c,valid ve açılış ms."""
    o, h, l, c, v = D.resample(sd, per)
    t_open = sd.g0 + np.arange(len(c)) * per * C.M5
    return o, h, l, c, v, t_open


def raw_signals(c_valid: np.ndarray, mode, p):
    """validate_nw_kama kuralları; eksik barlar dizide yer almaz (yalnız tam barlar sırayla)."""
    import pandas as pd
    df = pd.DataFrame({"close": c_valid})
    if mode == "agree":
        return V.sigs_agree(df, p["h"], p["win"], p["mult"], p["er"], 0)
    return V.sigs(df, mode, p["h"], p["win"], p["mult"], p["er"], p["lb"][mode])


def build(universe, vid):
    """Tüm dönem için bir varyantın sinyalleri (SetupRecord listesi, signal_time sıralı)."""
    tf, mode, pk = vid.split("_")
    per, p = TFS[tf], PARAMS[pk]
    out = []
    for sym, sd in universe["symbols"].items():
        o, h, l, c, v, t_open = tf_bars(sd, per)
        idx = np.flatnonzero(v)                       # yalnız tam barlar (sentetik bar yok)
        if len(idx) < p["win"] + 5:
            continue
        cv, hv, lv_ = c[idx], h[idx], l[idx]
        atr = I.atr(hv, lv_, cv, C.ATR_PERIOD)
        for t, d in raw_signals(cv, mode, p):
            a = atr[t]
            if not I.usable(a):
                continue
            k = idx[t]
            sig_time = int(t_open[k] + per * C.M5)     # TF bar KAPANIŞI
            E = float(cv[t])
            if d > 0:
                S, T = floor_tick(E - SL_ATR * a, sd.tick), floor_tick(E + TP_ATR * a, sd.tick)
                ok = S < E < T
            else:
                S, T = ceil_tick(E + SL_ATR * a, sd.tick), ceil_tick(E - TP_ATR * a, sd.tick)
                ok = T < E < S
            if not ok:
                continue
            out.append(SetupRecord(
                variant_base=f"{tf}_{mode}_{pk}", market_event_id=f"{vid}|{sym}|{sig_time}", symbol=sym,
                side="LONG" if d > 0 else "SHORT", level_id="", level_known_at=0, level_expires_at=2 ** 62,
                sweep_open=int(t_open[k]), sweep_close=sig_time, ATR15_frozen=float(a), terminal_status="SIGNAL",
                terminal_time=sig_time, signal_time=sig_time, E_plan=E, S_raw=E - d * SL_ATR * a, S=S,
                T_raw=E + d * TP_ATR * a, T=T))
    out.sort(key=lambda r: (r.signal_time, r.symbol))
    return out


def max_hold_ms(vid):
    return MAX_HOLD_BARS * TFS[vid.split("_")[0]] * C.M5
