"""
Giriş modelleri K1–K4 (şartname §7–§10), F0/F1 ve stop/hedef (§11). Strateji SAF veriyle
sinyal üretir; emir açmaz. Portföy kararları replay_adapter'dadır.

Bir sembol/yön/model için aktif teyit beklenirken gelen yeni olay BLOCKED_ACTIVE_SETUP ile
tüketilir. Kurulum seviye sona erdiği anda iptal olur; o anda gelen teyit kabul edilmez.
Bölüm başında bekleyen kurulum iptal edilir (setup makinesi her bölüm için ayrı koşar ve
yalnız sweep kapanışı bölüm içinde olan olayları alır).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from decimal import Decimal

import numpy as np

from . import config as C
from . import indicators_adapter as I
from .events import MarketEvent
from .levels import Derived


@dataclass
class SetupRecord:
    variant_base: str            # "L1_K3" gibi (F ayrı)
    market_event_id: str
    symbol: str
    side: str
    level_id: str
    level_known_at: int
    level_expires_at: int
    sweep_open: int
    sweep_close: int
    ATR15_frozen: float
    terminal_status: str         # SIGNAL | <neden kodu>
    terminal_time: int
    reason_code: str = ""
    reclaim_time: int | None = None
    micro_reference: float | None = None
    micro_reference_known_at: int | None = None
    first_break_time: int | None = None
    displacement_ATR5_prev: float | None = None
    fvg_known_at: int | None = None
    G_lo: float | None = None
    G_hi: float | None = None
    G_mid: float | None = None
    retest_time: int | None = None
    signal_time: int | None = None
    sweep_extreme: float | None = None
    E_plan: float | None = None
    S_raw: float | None = None
    S: float | None = None
    T_raw: float | None = None
    T: float | None = None
    F1_pass: bool | None = None
    F1_reason: str = ""

    def as_dict(self):
        return asdict(self)


# ───────────────────────────── tick yuvarlama ───────────────────────────────
def _dec(tick):
    return max(0, -Decimal(str(tick)).normalize().as_tuple().exponent)


def floor_tick(x, tick):
    return round(math.floor(x / tick + 1e-6) * tick, _dec(tick))


def ceil_tick(x, tick):
    return round(math.ceil(x / tick - 1e-6) * tick, _dec(tick))


def stop_target(side_long, extreme, A, E, tick):
    """S yuvarlaması: long aşağı, short yukarı. T girişe doğru: long aşağı, short yukarı."""
    if side_long:
        S_raw = extreme - C.STOP_BUFFER_ATR * A
        S = floor_tick(S_raw, tick)
        T_raw = E + C.TARGET_R * (E - S)
        T = floor_tick(T_raw, tick)
        ok = S < E < T
    else:
        S_raw = extreme + C.STOP_BUFFER_ATR * A
        S = ceil_tick(S_raw, tick)
        T_raw = E - C.TARGET_R * (S - E)
        T = ceil_tick(T_raw, tick)
        ok = T < E < S
    return S_raw, S, T_raw, T, ok


def f1_check(dv: Derived, side_long: bool, signal_time: int):
    """Nihai sinyal anında son TAMAMLANMIŞ 1H bar h. Eşitlik geçmez."""
    h = (signal_time - dv.sd.g0) // C.H1 - 1
    if h - C.EMA_SLOPE_BARS < 0:
        return False, "INVALID_INDICATOR"
    c, e, e3 = dv.c1h[h], dv.ema1h[h], dv.ema1h[h - C.EMA_SLOPE_BARS]
    if not (np.isfinite(c) and np.isfinite(e) and np.isfinite(e3)):
        return False, "INVALID_INDICATOR"
    if side_long:
        ok = c > e and e > e3
    else:
        ok = c < e and e < e3
    return bool(ok), "" if ok else "TREND_REJECTED"


# ───────────────────────────── modeller ──────────────────────────────────────
def _base(ev: MarketEvent, vb: str) -> SetupRecord:
    return SetupRecord(variant_base=vb, market_event_id=ev.market_event_id, symbol=ev.symbol, side=ev.side,
                       level_id=ev.level_id, level_known_at=ev.level_known_at,
                       level_expires_at=ev.level_expires_at, sweep_open=ev.sweep_open,
                       sweep_close=ev.sweep_close, ATR15_frozen=ev.A, terminal_status="PENDING",
                       terminal_time=ev.sweep_close)


def _end(r: SetupRecord, status, t):
    r.terminal_status = status
    r.reason_code = "" if status == "SIGNAL" else status
    r.terminal_time = int(t)
    return r


def _finish_signal(r: SetupRecord, dv: Derived, side_long, extreme, E, t_sig, S_fixed=None):
    tick = dv.sd.tick
    S_raw, S, T_raw, T, ok = stop_target(side_long, extreme, r.ATR15_frozen, E, tick)
    if S_fixed is not None:                         # K3/K4: stop K1 reclaim'de sabitlendi
        S_raw, S = S_fixed
        T_raw = E + C.TARGET_R * (E - S) if side_long else E - C.TARGET_R * (S - E)
        T = floor_tick(T_raw, tick) if side_long else ceil_tick(T_raw, tick)
        ok = (S < E < T) if side_long else (T < E < S)
    r.sweep_extreme, r.E_plan, r.S_raw, r.S, r.T_raw, r.T = extreme, E, S_raw, S, T_raw, T
    r.signal_time = int(t_sig)
    if not ok:
        return _end(r, "INVALID_GEOMETRY", t_sig)
    r.F1_pass, r.F1_reason = f1_check(dv, side_long, t_sig)
    return _end(r, "SIGNAL", t_sig)


def eval_K1(ev, dv, vb="K1"):
    r = _base(ev, vb)
    j, L, eps = ev.j15, ev.level_price, dv.eps
    lng = ev.side == "LONG"
    c = dv.c15[j]
    reclaim = (c > L + eps) if lng else (c < L - eps)
    if ev.double_sided:
        return _end(r, "DOUBLE_SIDED_SWEEP", ev.sweep_close)
    if not reclaim:
        return _end(r, "K1_RECLAIM_MISSING", ev.sweep_close)
    if ev.sweep_close >= ev.level_expires_at:
        return _end(r, "LEVEL_EXPIRED", ev.level_expires_at)
    r.reclaim_time = ev.sweep_close
    extreme = dv.l15[j] if lng else dv.h15[j]
    return _finish_signal(r, dv, lng, float(extreme), float(c), ev.sweep_close)


def eval_K2(ev, dv, vb="K2"):
    r = _base(ev, vb)
    j, L, eps = ev.j15, ev.level_price, dv.eps
    lng = ev.side == "LONG"
    if ev.double_sided:
        return _end(r, "DOUBLE_SIDED_SWEEP", ev.sweep_close)
    c = dv.c15[j]
    if (c > L + eps) if lng else (c < L - eps):
        return _end(r, "K2_NOT_APPLICABLE", ev.sweep_close)
    g0 = dv.sd.g0
    for i in range(1, C.K2_WINDOW_15M + 1):
        jj = j + i
        close_t = g0 + (jj + 1) * C.M15
        if close_t >= ev.level_expires_at:
            return _end(r, "LEVEL_EXPIRED", ev.level_expires_at)
        if jj >= len(dv.c15) or not np.isfinite(dv.c15[jj]):
            return _end(r, "DATA_INVALID", close_t)
        cq = dv.c15[jj]
        if (cq > L + eps) if lng else (cq < L - eps):
            r.reclaim_time = close_t
            extreme = np.min(dv.l15[j: jj + 1]) if lng else np.max(dv.h15[j: jj + 1])
            return _finish_signal(r, dv, lng, float(extreme), float(cq), close_t)
    return _end(r, "K2_TIMEOUT", g0 + (j + C.K2_WINDOW_15M + 1) * C.M15)


def _k3_core(ev, dv, vb):
    """K3/K4 ortak kısmı. Döner (kayıt, ilerleme): ilerleme=None ise kayıt terminaldir."""
    r = _base(ev, vb)
    j, L, eps = ev.j15, ev.level_price, dv.eps
    lng = ev.side == "LONG"
    sd = dv.sd
    if ev.double_sided:
        return _end(r, "DOUBLE_SIDED_SWEEP", ev.sweep_close), None
    c = dv.c15[j]
    if not ((c > L + eps) if lng else (c < L - eps)):
        return _end(r, "K1_RECLAIM_MISSING", ev.sweep_close), None
    if ev.sweep_close >= ev.level_expires_at:
        return _end(r, "LEVEL_EXPIRED", ev.level_expires_at), None
    r.reclaim_time = ev.sweep_close
    if ev.micro_ref is None:
        return _end(r, "NO_MICRO_PIVOT", ev.sweep_close), None
    Hm, known, _ = ev.micro_ref
    r.micro_reference, r.micro_reference_known_at = Hm, known
    if (c > Hm + eps) if lng else (c < Hm - eps):          # long: close[t] <= H olmalı
        return _end(r, "STRUCTURE_ALREADY_BROKEN", ev.sweep_close), None
    extreme = float(dv.l15[j] if lng else dv.h15[j])
    S_raw = extreme - C.STOP_BUFFER_ATR * ev.A if lng else extreme + C.STOP_BUFFER_ATR * ev.A
    S = floor_tick(S_raw, sd.tick) if lng else ceil_tick(S_raw, sd.tick)
    r.sweep_extreme, r.S_raw, r.S = extreme, S_raw, S
    k0 = (ev.sweep_close - sd.g0) // C.M5
    for i in range(C.K3_WINDOW_5M):
        k = k0 + i
        t_close = sd.t_open(k) + C.M5
        if t_close >= ev.level_expires_at:
            return _end(r, "LEVEL_EXPIRED", ev.level_expires_at), None
        if k >= sd.n5 or not sd.valid5[k]:
            return _end(r, "DATA_INVALID", t_close), None
        if (sd.l[k] <= S + eps) if lng else (sd.h[k] >= S - eps):
            return _end(r, "STOP_BEFORE_ENTRY", t_close), None
        brk = (sd.c[k] > Hm + eps) if lng else (sd.c[k] < Hm - eps)
        if not brk:
            continue
        a5 = dv.atr5[k - 1] if k >= 1 else np.nan
        r.first_break_time = t_close
        if not I.usable(a5):
            return _end(r, "INVALID_INDICATOR", t_close), None
        body = abs(sd.c[k] - sd.o[k])
        r.displacement_ATR5_prev = float(body / a5)
        direction_ok = (sd.c[k] > sd.o[k]) if lng else (sd.c[k] < sd.o[k])
        if not (direction_ok and body >= C.DISPLACEMENT_BODY_ATR * a5 - eps):
            return _end(r, "WEAK_FIRST_BREAK", t_close), None
        return r, dict(m=k, S=(S_raw, S), lng=lng, extreme=extreme)
    return _end(r, "K3_TIMEOUT", sd.t_open(k0 + C.K3_WINDOW_5M)), None


def eval_K3(ev, dv, vb="K3"):
    r, st = _k3_core(ev, dv, vb)
    if st is None:
        return r
    m = st["m"]
    sd = dv.sd
    return _finish_signal(r, dv, st["lng"], st["extreme"], float(sd.c[m]), sd.t_open(m) + C.M5, S_fixed=st["S"])


def eval_K4(ev, dv, vb="K4"):
    r, st = _k3_core(ev, dv, vb)
    if st is None:
        return r
    sd, eps = dv.sd, dv.eps
    m, lng = st["m"], st["lng"]
    S = st["S"][1]
    k = m + 1
    t_close = sd.t_open(k) + C.M5
    if t_close >= ev.level_expires_at:
        return _end(r, "LEVEL_EXPIRED", ev.level_expires_at)
    if k >= sd.n5 or not sd.valid5[k] or not sd.valid5[m - 1]:
        return _end(r, "DATA_INVALID", t_close)
    if (sd.l[k] <= S + eps) if lng else (sd.h[k] >= S - eps):
        return _end(r, "STOP_BEFORE_ENTRY", t_close)
    if lng:
        if not (sd.l[k] > sd.h[m - 1] + eps):
            return _end(r, "NO_FVG", t_close)
        g_lo, g_hi = float(sd.h[m - 1]), float(sd.l[k])
    else:
        if not (sd.h[k] < sd.l[m - 1] - eps):
            return _end(r, "NO_FVG", t_close)
        g_lo, g_hi = float(sd.h[k]), float(sd.l[m - 1])
    g_mid = (g_lo + g_hi) / 2
    r.fvg_known_at, r.G_lo, r.G_hi, r.G_mid = t_close, g_lo, g_hi, g_mid
    for i in range(C.K4_WINDOW_5M):
        kk = m + 2 + i
        tc = sd.t_open(kk) + C.M5
        if tc >= ev.level_expires_at:
            return _end(r, "LEVEL_EXPIRED", ev.level_expires_at)
        if kk >= sd.n5 or not sd.valid5[kk]:
            return _end(r, "DATA_INVALID", tc)
        if (sd.l[kk] <= S + eps) if lng else (sd.h[kk] >= S - eps):
            return _end(r, "STOP_BEFORE_ENTRY", tc)                 # öncelik 1
        if (sd.c[kk] < g_lo - eps) if lng else (sd.c[kk] > g_hi + eps):
            return _end(r, "FVG_INVALIDATED", tc)                    # öncelik 2
        if lng:
            conf = sd.l[kk] <= g_mid + eps and sd.c[kk] > g_hi + eps
        else:
            conf = sd.h[kk] >= g_mid - eps and sd.c[kk] < g_lo - eps
        if conf:
            r.retest_time = tc
            return _finish_signal(r, dv, lng, st["extreme"], float(sd.c[kk]), tc, S_fixed=st["S"])
    return _end(r, "K4_TIMEOUT", sd.t_open(m + 2 + C.K4_WINDOW_5M))


EVAL = {"K1": eval_K1, "K2": eval_K2, "K3": eval_K3, "K4": eval_K4}


def run_machine(family, K, events_by_symbol, derived, phase_start, phase_end):
    """Bir (aile, model) için bir bölümün kurulum kayıtları. Aktif kurulum durumu sembol/yön
    başına; bölüm başında boş başlar (bekleyen kurulumlar önceki bölümde kaldı = iptal)."""
    vb = f"{family}_{K}"
    out = []
    for sym, evs in events_by_symbol.items():
        dv = derived[sym]
        active = {"LONG": -1, "SHORT": -1}
        for ev in evs:
            if ev.sweep_close < phase_start or ev.sweep_close >= phase_end:
                continue
            if active[ev.side] > ev.sweep_close:
                r = _base(ev, vb)
                out.append(_end(r, "BLOCKED_ACTIVE_SETUP", ev.sweep_close))
                continue
            r = EVAL[K](ev, dv, vb)
            if K != "K1":
                active[ev.side] = r.terminal_time
            out.append(r)
    out.sort(key=lambda r: (r.terminal_time, r.symbol, r.side))
    return out
