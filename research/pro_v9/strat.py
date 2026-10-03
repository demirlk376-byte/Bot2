"""PRO_V9 stratejileri (MANIFEST.md): coinler arası momentum (XS) ve funding toplama (FC). Günlük döngü."""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.liquidity_sweep_v1 import config as C
from research.liquidity_sweep_v1.indicators_adapter import atr as atr_fn

DAY = C.DAY
UNIT = 25.0
WARM = 200


def _common(syms, window):
    a, b = window
    days = sorted({int(x) for s in syms.values() for x in s.t if a <= x < b})
    idx = {n: {int(t): i for i, t in enumerate(s.t)} for n, s in syms.items()}
    return days, idx


def _fund(s, t0, t1):
    i, j = np.searchsorted(s.f_t, t0, side="right"), np.searchsorted(s.f_t, t1, side="right")
    return s.f_r[i:j]


def xs_momentum(syms, window, L, mode, cost):
    """Dönüş: (günlük [(t_kapanış, kümülatif PnL)], haftalık PnL {pazartesi_ms: USDT}, açılış sayısı)."""
    days, idx = _common(syms, window)
    atr = {n: atr_fn(s.h, s.l, s.c, 20) for n, s in syms.items()}
    qty = {n: 0.0 for n in syms}
    pnl, curve, weekly, opens = 0.0, [], {}, 0

    def tcost(px, close_part, open_part):
        return px * (close_part * (cost.exit_fee_rate + cost.exit_slip_bp * 1e-4)
                     + open_part * (cost.entry_fee_rate + cost.entry_slip_bp * 1e-4))

    for t in days:
        monday = (t // DAY + 3) % 7 == 0                   # 1970-01-01 Perşembe
        wk = t - ((t // DAY + 3) % 7) * DAY
        day_pnl = 0.0
        if monday:
            for n, s in syms.items():                      # eski pozisyon: önceki kapanış → bugünkü açılış
                i = idx[n].get(t)
                if i is not None and i > 0 and qty[n]:
                    day_pnl += qty[n] * (s.o[i] - s.c[i - 1])
            sc = {}
            for n, s in syms.items():
                i = idx[n].get(t)
                if i is None or i < max(WARM, L + 1):
                    continue
                if not (np.isfinite(atr[n][i - 1]) and atr[n][i - 1] > 0):
                    continue
                sc[n] = s.c[i - 1] / s.c[i - 1 - L] - 1
            k = max(1, int(0.25 * len(sc))) if sc else 0
            rk = sorted(sc, key=lambda n: (sc[n], n))
            tgt = {n: 0.0 for n in syms}
            if k:
                for n in rk[-k:]:
                    tgt[n] = 1.0
                if mode == "LS":
                    for n in rk[:k]:
                        tgt[n] = -1.0
            for n, s in syms.items():
                i = idx[n].get(t)
                if i is None:
                    continue                               # o gün veri yok: pozisyon olduğu gibi kalır
                O = s.o[i]
                new_q = tgt[n] * (UNIT / (2 * atr[n][i - 1] / s.c[i - 1])) / O if tgt[n] else 0.0
                dq = new_q - qty[n]
                if abs(dq) < 1e-15:
                    continue
                if qty[n] * new_q < 0:
                    cp, op = abs(qty[n]), abs(new_q)
                elif abs(new_q) > abs(qty[n]):
                    cp, op = 0.0, abs(dq)
                else:
                    cp, op = abs(dq), 0.0
                day_pnl -= tcost(O, cp, op)
                opens += 1 if op and not cp and qty[n] == 0 or (cp and op) else 0
                qty[n] = new_q
        for n, s in syms.items():
            i = idx[n].get(t)
            if i is None or not qty[n]:
                continue
            ref = s.o[i] if monday else (s.c[i - 1] if i > 0 else s.o[i])
            day_pnl += qty[n] * (s.c[i] - ref)
            for r in _fund(s, t, t + DAY):
                day_pnl += -qty[n] * s.o[i] * r            # long öder, short alır
        if t == days[-1]:                                  # dönem sonu: kapanışta kapat
            for n, s in syms.items():
                i = idx[n].get(t)
                if i is not None and qty[n]:
                    day_pnl -= tcost(s.c[i], abs(qty[n]), 0.0)
                    qty[n] = 0.0
        pnl += day_pnl
        weekly[wk] = weekly.get(wk, 0.0) + day_pnl
        curve.append((t + DAY, pnl))
    return curve, weekly, opens


def funding_carry(syms, window, theta, cost, notional=1000.0, max_pos=6, spot_fee=0.0010):
    days, idx = _common(syms, window)
    held = {}
    pnl, curve, weekly, trades = 0.0, [], {}, 0
    for t in days:
        wk = t - ((t // DAY + 3) % 7) * DAY
        day_pnl = 0.0
        if (t // DAY + 3) % 7 == 0:
            sc = {}
            for n, s in syms.items():
                if idx[n].get(t) is None:
                    continue
                r = _fund(s, t - 7 * DAY, t)
                if len(r) >= 3 and np.mean(r) >= theta:
                    sc[n] = float(np.mean(r))
            keep = set(sorted(sc, key=lambda n: -sc[n])[:max_pos])
            for n in list(held):
                if n not in keep:
                    day_pnl -= notional * (cost.exit_fee_rate + spot_fee + 2 * cost.exit_slip_bp * 1e-4)
                    del held[n]
            for n in keep:
                if n not in held:
                    day_pnl -= notional * (cost.entry_fee_rate + spot_fee + 2 * cost.entry_slip_bp * 1e-4)
                    held[n] = t
                    trades += 1
        for n in held:
            s = syms[n]
            i = idx[n].get(t)
            if i is None:
                continue
            for r in _fund(s, t, t + DAY):
                day_pnl += notional * r                    # short perp: pozitif oranı ALIR
        pnl += day_pnl
        weekly[wk] = weekly.get(wk, 0.0) + day_pnl
        curve.append((t + DAY, pnl))
    if held and days:                                  # dönem sonu: kapat
        c = len(held) * notional * (cost.exit_fee_rate + spot_fee + 2 * cost.exit_slip_bp * 1e-4)
        pnl -= c
        weekly[max(weekly)] -= c
        curve[-1] = (curve[-1][0], pnl)
    return curve, weekly, trades
