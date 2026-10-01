"""
Ortak sweep olayı (şartname §5 tüketim + §6). Aile düzeyinde, model/F/portföyden BAĞIMSIZ:
seviye her varyantta ilk uygun ihlal olayında tüketilir (emir açılması şart değil).

t = ilk ihlal içeren 15m bar; olay t KAPANIŞINDA bilinir.
L = t başında seçilmiş seviye; A = t başlamadan tamamlanmış son 15m barın ATR14'ü.
Long ihlal : close[t-1] >= L ve low[t]  <= L - 0.10*A
Short ihlal: close[t-1] <= L ve high[t] >= L + 0.10*A
Aynı bar aynı ailede iki yönü birden ihlal ederse ikisi de tüketilir → DOUBLE_SIDED_SWEEP.
Karşılaştırma toleransı: tick*1e-6 (bir tam tick asla eşit sayılmaz).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import config as C
from . import indicators_adapter as I
from .levels import Derived, LevelBook


@dataclass
class MarketEvent:
    market_event_id: str
    family: str
    symbol: str
    side: str                    # "LONG" | "SHORT"
    level_id: str
    level_price: float
    level_known_at: int
    level_expires_at: int
    j15: int                     # ihlal 15m bar indeksi
    sweep_open: int
    sweep_close: int
    A: float                     # dondurulmuş ATR15[t-1]
    micro_ref: tuple | None      # (fiyat, known_at, pivot_open) — K3/K4 için t başında dondurulmuş
    double_sided: bool = False


def detect(family: str, dv: Derived, book: LevelBook):
    """Döner: (olaylar, notlar). Seviyeler kronolojik tüketilir (ısınma dahil)."""
    sd = dv.sd
    g0, eps = sd.g0, dv.eps
    c15, l15, h15, a15 = dv.c15, dv.l15, dv.h15, dv.atr15
    v15 = np.isfinite(c15)
    events, notes = [], {"INVALID_INDICATOR": 0, "DATA_INVALID_SKIP": 0}
    for j in range(1, len(c15)):
        tau = g0 + j * C.M15
        refs = {s: book.reference(s, tau) for s in ("LOW", "HIGH")}
        if refs["LOW"] is None and refs["HIGH"] is None:
            continue
        if not (v15[j] and v15[j - 1]):
            notes["DATA_INVALID_SKIP"] += 1
            continue
        A = a15[j - 1]
        hits = {}
        for s, lv in refs.items():
            if lv is None:
                continue
            L = lv.price
            if s == "LOW":
                pre = c15[j - 1] >= L - eps
                touch = l15[j] <= L + eps
            else:
                pre = c15[j - 1] <= L + eps
                touch = h15[j] >= L - eps
            if not (pre and touch):
                continue
            if not I.usable(A):
                notes["INVALID_INDICATOR"] += 1
                continue
            if s == "LOW" and l15[j] <= L - C.PENETRATION_ATR * A + eps:
                hits[s] = lv
            elif s == "HIGH" and h15[j] >= L + C.PENETRATION_ATR * A - eps:
                hits[s] = lv
        if not hits:
            continue
        close_t = tau + C.M15
        double = len(hits) == 2
        for s, lv in hits.items():
            lv.consumed_at = close_t
            lv.consume_reason = "DOUBLE_SIDED_SWEEP" if double else "SWEEP"
            side = "LONG" if s == "LOW" else "SHORT"
            micro = dv.micro_reference(side == "LONG", tau)
            events.append(MarketEvent(
                market_event_id=f"{family}|{sd.symbol}|{side}|{tau}", family=family, symbol=sd.symbol,
                side=side, level_id=lv.level_id, level_price=lv.price, level_known_at=lv.known_at,
                level_expires_at=lv.expires_at, j15=j, sweep_open=tau, sweep_close=close_t, A=float(A),
                micro_ref=micro, double_sided=double))
    return events, notes
