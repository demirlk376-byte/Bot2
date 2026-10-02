"""
Seviye kaydı (şartname §5). Seviye fiyatı/kimliği üretildikten sonra değişmez.
side="LOW" → long kurulumu referansı; side="HIGH" → short.

Bir 15m barın referansı, bar BAŞLANGICINDA τ için: known_at <= τ < expires_at ve tüketilmemiş.
  L1: önceki tam UTC gün (288 bar) H/L; known=D 00:00, expires=D+1 00:00.
  L2: D günü [00:00,08:00) (96 bar); known=D 08:00, expires=D+1 00:00.
  L3: en son doğrulanmış 1H pivot (2 sol/2 sağ, sıkı); known=p+2 kapanışı, expires=known+48s.
      En son pivot tüketilmiş/süresi dolmuşsa daha eskisine DÖNÜLMEZ.
  L4: aynı yöndeki ARDIŞIK iki pivot; oluşumlar arası <=48s; |fark| <= 0.10*ATR1h(p2+2);
      fiyat: tepelerin büyüğü / diplerin küçüğü; known=ikinci pivot onayı; expires=known+48s.
      Yeni pivot çifti şartı sağlamazsa o yönde L4 referansı YOKTUR (eski çifte dönülmez).
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field

import numpy as np

from . import config as C
from . import data_contract as D
from . import indicators_adapter as I


@dataclass
class Level:
    level_id: str
    symbol: str
    family: str
    side: str                    # "LOW" | "HIGH"
    price: float
    origin_times: tuple
    known_at: int
    expires_at: int
    selected_at_bar_start: int | None = None
    consumed_at: int | None = None
    consume_reason: str | None = None
    meta: dict = field(default_factory=dict)

    def active_at(self, tau):
        return self.known_at <= tau < self.expires_at and self.consumed_at is None


class Derived:
    """Bir sembolün türetilmiş zaman dilimleri ve göstergeleri (bir kez hesaplanır)."""

    def __init__(self, sd: D.SymbolData):
        self.sd = sd
        self.eps = sd.tick * 1e-6
        self.o15, self.h15, self.l15, self.c15, self.v15 = D.resample(sd, C.GRID_PER_15M)
        self.o1h, self.h1h, self.l1h, self.c1h, self.v1h = D.resample(sd, C.GRID_PER_1H)
        self.atr15 = I.atr(self.h15, self.l15, self.c15, C.ATR_PERIOD)
        self.atr1h = I.atr(self.h1h, self.l1h, self.c1h, C.ATR_PERIOD)
        self.atr5 = I.atr(sd.h, sd.l, sd.c, C.ATR_PERIOD)
        self.ema1h = I.ema(self.c1h, C.EMA_PERIOD)
        nd = -(-sd.n5 // C.GRID_PER_DAY)                 # kısmi son gün dahil (L1 o gün bilinir)
        pad = nd * C.GRID_PER_DAY - sd.n5
        hh = np.r_[sd.h, np.full(pad, np.nan)].reshape(nd, C.GRID_PER_DAY)
        ll = np.r_[sd.l, np.full(pad, np.nan)].reshape(nd, C.GRID_PER_DAY)
        vd = np.r_[sd.valid5, np.zeros(pad, bool)].reshape(nd, C.GRID_PER_DAY).all(axis=1)
        with np.errstate(all="ignore"):
            self.day_h = np.where(vd, np.nanmax(np.where(np.isnan(hh), -np.inf, hh), axis=1), np.nan)
            self.day_l = np.where(vd, np.nanmin(np.where(np.isnan(ll), np.inf, ll), axis=1), np.nan)
        self.sess_h, self.sess_l, self.sess_v = D.session_hl(sd)
        # 1H pivotlar
        self.piv1h_high = pivots(self.h1h, self.v1h, kind="high")
        self.piv1h_low = pivots(self.l1h, self.v1h, kind="low")
        # 5m mikro pivotlar: known_at listeleri (bisect için)
        self.piv5_high = pivots(sd.h, sd.valid5, kind="high")
        self.piv5_low = pivots(sd.l, sd.valid5, kind="low")
        self._k5h = [sd.g0 + (p + C.PIVOT_RIGHT + 1) * C.M5 for p in self.piv5_high]
        self._k5l = [sd.g0 + (p + C.PIVOT_RIGHT + 1) * C.M5 for p in self.piv5_low]

    def micro_reference(self, side_long: bool, tau: int):
        """τ başında bilinen EN SON onaylı 5m pivot (long: high, short: low); onayı τ'dan en fazla
        24 saat önce olmalı. Döner (fiyat, known_at, pivot_open) veya None."""
        ks, ps, arr = ((self._k5h, self.piv5_high, self.sd.h) if side_long
                       else (self._k5l, self.piv5_low, self.sd.l))
        i = bisect.bisect_right(ks, tau) - 1
        if i < 0:
            return None
        known = ks[i]
        if known < tau - C.MICRO_PIVOT_MAX_AGE_MS:
            return None
        p = ps[i]
        return float(arr[p]), known, self.sd.g0 + p * C.M5


def pivots(x: np.ndarray, valid: np.ndarray, kind: str):
    """Sıkı 2-sol/2-sağ pivot indeksleri (eşitlik pivot DEĞİL; 5 barın hepsi geçerli olmalı)."""
    n = len(x)
    L, R = C.PIVOT_LEFT, C.PIVOT_RIGHT
    if n < L + R + 1:
        return []
    p = np.arange(L, n - R)
    ok = np.ones(len(p), dtype=bool)
    for off in range(-L, R + 1):
        ok &= valid[p + off]
        if off == 0:
            continue
        if kind == "high":
            ok &= x[p] > x[p + off]
        else:
            ok &= x[p] < x[p + off]
    return [int(i) for i in p[ok]]


class LevelBook:
    """(sembol, aile) için iki yönün referans zaman çizelgesi + seviye kayıtları."""

    def __init__(self, family: str, dv: Derived):
        self.family, self.dv = family, dv
        sd = dv.sd
        self.symbol = sd.symbol
        self.levels: list[Level] = []
        # her yön: known_at'e göre sıralı (known_at, Level|None) karar listesi
        self.timeline = {"LOW": [], "HIGH": []}
        self.invalid_indicator = 0
        g0 = sd.g0
        if family == "L1":
            for d in range(1, len(dv.day_h)):
                if not np.isfinite(dv.day_h[d - 1]):
                    continue
                kn, ex = g0 + d * C.DAY, g0 + (d + 1) * C.DAY
                for side, price in (("HIGH", dv.day_h[d - 1]), ("LOW", dv.day_l[d - 1])):
                    lv = Level(f"L1|{self.symbol}|{side}|{_d(kn)}", self.symbol, "L1", side, float(price),
                               (g0 + (d - 1) * C.DAY,), kn, ex)
                    self._add(side, kn, lv)
        elif family == "L2":
            for d in range(len(dv.sess_h)):
                if not dv.sess_v[d]:
                    continue
                kn = g0 + d * C.DAY + C.SESSION_END_MS
                ex = g0 + (d + 1) * C.DAY
                for side, price in (("HIGH", dv.sess_h[d]), ("LOW", dv.sess_l[d])):
                    lv = Level(f"L2|{self.symbol}|{side}|{_d(g0 + d * C.DAY)}", self.symbol, "L2", side,
                               float(price), (g0 + d * C.DAY,), kn, ex)
                    self._add(side, kn, lv)
        elif family == "L3":
            for side, piv, arr in (("HIGH", dv.piv1h_high, dv.h1h), ("LOW", dv.piv1h_low, dv.l1h)):
                for p in piv:
                    kn = g0 + (p + C.PIVOT_RIGHT + 1) * C.H1
                    lv = Level(f"L3|{self.symbol}|{side}|{_d(g0 + p * C.H1)}", self.symbol, "L3", side,
                               float(arr[p]), (g0 + p * C.H1,), kn, kn + C.LEVEL_MAX_AGE_MS)
                    self._add(side, kn, lv)
        elif family == "L4":
            for side, piv, arr in (("HIGH", dv.piv1h_high, dv.h1h), ("LOW", dv.piv1h_low, dv.l1h)):
                prev = None
                for p in piv:
                    kn = g0 + (p + C.PIVOT_RIGHT + 1) * C.H1
                    lv = None
                    if prev is not None:
                        gap = (p - prev) * C.H1
                        a1 = dv.atr1h[p + C.PIVOT_RIGHT]          # ikinci pivot onayındaki son tam 1H bar
                        if gap > C.EQUAL_PIVOT_MAX_GAP_MS:
                            pass
                        elif not I.usable(a1):
                            self.invalid_indicator += 1
                        else:
                            tol = C.EQUAL_PIVOT_TOL_ATR * a1
                            if abs(arr[p] - arr[prev]) <= tol + dv.eps:
                                price = max(arr[p], arr[prev]) if side == "HIGH" else min(arr[p], arr[prev])
                                lv = Level(f"L4|{self.symbol}|{side}|{_d(g0 + prev * C.H1)}|{_d(g0 + p * C.H1)}",
                                           self.symbol, "L4", side, float(price),
                                           (g0 + prev * C.H1, g0 + p * C.H1), kn, kn + C.LEVEL_MAX_AGE_MS,
                                           meta=dict(A1=float(a1), tol=float(tol),
                                                     p1=float(arr[prev]), p2=float(arr[p])))
                    self._add(side, kn, lv)          # None = bu yönde L4 referansı YOK
                    prev = p
        else:
            raise ValueError(family)
        for side in self.timeline:
            self.timeline[side].sort(key=lambda x: x[0])
        self._k = {s: [x[0] for x in self.timeline[s]] for s in self.timeline}

    def _add(self, side, known, lv):
        self.timeline[side].append((known, lv))
        if lv is not None:
            self.levels.append(lv)

    def reference(self, side: str, tau: int):
        """τ anında seçilen referans (yoksa None). Tüketilmiş/süresi dolmuşsa daha eskisine dönülmez."""
        i = bisect.bisect_right(self._k[side], tau) - 1
        if i < 0:
            return None
        lv = self.timeline[side][i][1]
        if lv is None or not lv.active_at(tau):
            return None
        if lv.selected_at_bar_start is None:
            lv.selected_at_bar_start = tau
        return lv

    def finalize(self, data_end_ms):
        """Tüketilmemiş seviyeler: daha yeni bir referansla süresi dolmadan değiştirildiyse SUPERSEDED;
        süresi veri sonundan önce dolduysa LEVEL_EXPIRED; değilse CENSORED (veri bitti)."""
        sup = {}
        for side, tl in self.timeline.items():
            for (k1, lv), (k2, _nx) in zip(tl, tl[1:]):
                if lv is not None and k2 < lv.expires_at:
                    sup[id(lv)] = k2
        for lv in self.levels:
            if lv.consumed_at is not None:
                continue
            if id(lv) in sup and (sup[id(lv)] < data_end_ms):
                lv.consume_reason = "SUPERSEDED"
                lv.meta["superseded_at"] = sup[id(lv)]
            elif lv.expires_at <= data_end_ms:
                lv.consume_reason = "LEVEL_EXPIRED"
            else:
                lv.consume_reason = "CENSORED"


def _d(ms):
    return D.ms_to_str(ms).replace(" ", "T").replace("+00:00", "Z")
