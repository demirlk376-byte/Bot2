"""
TREND_TAKİP_V1 günlük motoru (MANIFEST.md). Muhasebe/dolum fonksiyonları liquidity_sweep_v1'den.

Gün d için olay sırası (tek küresel saat, semboller ad sırasıyla):
  AÇILIŞ  1) açılış boşluğu: stop açılışta aşılmışsa açılıştan çıkış
          2) önceki kapanışta bilinen çıkış emirleri (XH, PARTITION_END) açılışta
          3) önceki kapanışta bilinen giriş sinyalleri açılışta (stop açılışın doğru tarafında olmalı)
  GÜN İÇİ 4) stop dokunuşu (X3/X5): stop fiyatından (kayma ile) çıkış
  KAPANIŞ 5) funding (gün içindeki settlement'lar; açık pozisyonlar)
          6) takip eden stop güncellemesi (yalnız lehe), XH çıkış sinyali, yeni giriş sinyalleri
          7) özsermaye kesiti (kapanış fiyatıyla)
Sinyaller yalnız d ve öncesi verisini kullanır; dolum d+1 açılışında.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from research.liquidity_sweep_v1 import config as C
from research.liquidity_sweep_v1.accounting import (Ledger, entry_fill, exit_fill, floor_step,
                                                    funding_cashflow)
from research.liquidity_sweep_v1.indicators_adapter import atr as atr_fn

DAY = C.DAY
WARMUP_DAYS = 200
ATR_N = 20


@dataclass
class Sym:
    name: str
    t: np.ndarray          # gün açılış ms
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    tick: float
    cs: float
    vu: float
    mv: float
    f_t: np.ndarray        # funding settlement ms
    f_r: np.ndarray
    v: np.ndarray = None   # günlük hacim (yalnız filtre G2/G3)


def variant_parts(vid):
    n, x, side = vid.split("_")
    return int(n[1:]), x, side


VARIANTS = [f"N{n}_{x}_{s}" for n in (50, 100) for x in ("X3", "X5", "XH") for s in ("L", "LS")]


def indicators(s: Sym, N):
    hh = pd.Series(s.h).shift(1).rolling(N).max().to_numpy()       # ÖNCEKİ N günün tepesi
    ll = pd.Series(s.l).shift(1).rolling(N).min().to_numpy()
    half = max(1, N // 2)
    ll_half = pd.Series(s.l).rolling(half).min().to_numpy()         # bugün DAHİL son N/2 dip (çıkış için)
    hh_half = pd.Series(s.h).rolling(half).max().to_numpy()
    atr = atr_fn(s.h, s.l, s.c, ATR_N)
    return hh, ll, ll_half, hh_half, atr


def nwk_signals(s: Sym):
    """NW+KAMA 1D event_A girişleri (validate_nw_kama.sigs, kod aynen): gün indeksi → yön."""
    import sys, os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if root not in sys.path:
        sys.path.insert(0, root)
    import validate_nw_kama as V
    return {int(t): int(d) for t, d in V.sigs(pd.DataFrame({"close": s.c}), "event", 3, 15, 1.5, 5, 1)}


def adx(h, l, c, n=14):
    """Wilder ADX (nedensel)."""
    up, dn = np.diff(h, prepend=np.nan), -np.diff(l, prepend=np.nan)
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum(h - l, np.maximum(abs(h - np.r_[np.nan, c[:-1]]), abs(l - np.r_[np.nan, c[:-1]])))
    w = lambda x: pd.Series(x).ewm(alpha=1 / n, adjust=False, min_periods=n).mean().to_numpy()
    atr_w = w(np.nan_to_num(tr))
    pdi, mdi = 100 * w(pdm) / atr_w, 100 * w(mdm) / atr_w
    dx = 100 * abs(pdi - mdi) / np.where(pdi + mdi > 0, pdi + mdi, np.nan)
    return w(np.nan_to_num(dx))


def nwk_entries(syms: dict, tf_days=1, filt="F0", market="ETH"):
    """NW+KAMA event_A girişleri, tf_days günlük mumda (2D: UTC epoch'tan 2 günlük blokların son günü
    kapanışı), sinyal o blok-son günün indeksine yazılır. filt: F0 yok, F1 coin SMA200 yönü,
    F2 piyasa (ETH) SMA200 yönü, F3 ADX14 > 20, G1 funding (long: 3g ort ≤ 0.0001, short: ≥ 0),
    G2 hacim > önceki 20g medyanı, G3 = G1 ve G2."""
    sma = {n: pd.Series(s.c).rolling(200).mean().to_numpy() for n, s in syms.items()}
    mk = syms.get(market)
    mk_up = {int(t): (c > m) for t, c, m in zip(mk.t, mk.c, sma[market])} if mk is not None else {}
    mk_ok = {int(t) for t, m in zip(mk.t, sma[market]) if np.isfinite(m)} if mk is not None else set()
    out = {}
    for n, s in syms.items():
        ix = np.arange(len(s.c)) if tf_days == 1 else np.flatnonzero((s.t // DAY) % tf_days == tf_days - 1)
        raw = nwk_signals_c(s.c[ix])
        ax = adx(s.h, s.l, s.c) if filt == "F3" else None
        o = {}
        for j, d in raw.items():
            i = int(ix[j])
            if filt == "F1" and not (np.isfinite(sma[n][i]) and (s.c[i] > sma[n][i]) == (d > 0)):
                continue
            if filt == "F2" and not (int(s.t[i]) in mk_ok and mk_up[int(s.t[i])] == (d > 0)):
                continue
            if filt == "F3" and not (np.isfinite(ax[i]) and ax[i] > 20):
                continue
            if filt in ("G1", "G3"):                 # funding kalabalığı: son 3 günün settlement ortalaması
                tc = int(s.t[i]) + DAY
                a, b = np.searchsorted(s.f_t, tc - 3 * DAY, side="right"), np.searchsorted(s.f_t, tc, side="right")
                if b <= a:
                    continue
                fm = float(np.mean(s.f_r[a:b]))
                if (d > 0 and fm > 0.0001) or (d < 0 and fm < 0.0):
                    continue
            if filt in ("G2", "G3"):                 # hacim teyidi: sinyal günü hacmi > önceki 20 gün medyanı
                if s.v is None or i < 20 or not s.v[i] > np.median(s.v[i - 20:i]):
                    continue
            o[i] = d
        out[n] = o
    return out


def nwk_signals_c(c):
    import sys, os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if root not in sys.path:
        sys.path.insert(0, root)
    import validate_nw_kama as V
    return {int(t): int(d) for t, d in V.sigs(pd.DataFrame({"close": c}), "event", 3, 15, 1.5, 5, 1)}


def simulate(vid, window, syms: dict, cost, C0=C.C0_FALLBACK, early_days=None, entry="DONCHIAN", entry_sigs=None):
    """early_days: girişten bu kadar gün sonra en iyi kapanış +1R'ye ulaşmamışsa ertesi açılışta çık.
    entry="NWK": giriş sinyali NW+KAMA 1D event_A (yön her iki taraf), çıkış X kuralıyla."""
    N, X, side = variant_parts(vid)
    nwk = entry_sigs if entry_sigs is not None else (
        {n: nwk_signals(s) for n, s in syms.items()} if entry == "NWK" else None)
    start, end = window
    k_mult = {"X3": 3.0, "X5": 5.0}.get(X)
    risk_per = C.PER_TRADE_RISK_FRAC * C0
    risk_cap = 12 * risk_per
    lev = C.LIVE_GATES["LEVERAGE"]
    ind = {n: indicators(s, N) for n, s in syms.items()}
    days = sorted({int(x) for s in syms.values() for x in s.t if start <= x < end})
    idx = {n: {int(t): i for i, t in enumerate(s.t)} for n, s in syms.items()}
    led = Ledger(C0)
    pos, pend_entry, pend_exit = {}, {}, {}
    trades, blocked, equity = [], [], []
    tid = 0
    missing_fund = [0]
    last_day = days[-1] if days else None

    def close(n, ref, reason, t_ev, phase):
        p = pos.pop(n)
        s = syms[n]
        xf = exit_fill(ref, p["d"], cost.exit_slip_bp, s.tick)
        gross = p["d"] * (xf - p["E"]) * p["q"]
        fee = abs(xf * p["q"]) * cost.exit_fee_rate
        led.close(gross, fee, p["margin"])
        net = gross - p["fee_in"] - fee + p["fund"]
        trades.append(dict(trade_id=p["id"], variant_id=vid, symbol=n, side="LONG" if p["d"] > 0 else "SHORT",
                           signal_time=p["sig"], fill_time=p["t"], E_fill=p["E"], S0=p["S0"], quantity_base=p["q"],
                           R0_USDT=p["R0"], exit_time=t_ev, exit_interval_start=t_ev, exit_phase=phase,
                           exit_reason=reason, X_reference=ref, X_fill=xf, gross_PnL=gross, entry_fee=p["fee_in"],
                           exit_fee=fee, funding_cashflow=p["fund"], net_PnL=net, net_R=net / p["R0"],
                           ambiguity_flag=False, hold_days=(t_ev - p["t"]) / DAY))

    for t in days:
        # 1–2) açılış: boşluk stopları ve bekleyen çıkışlar
        for n in sorted(list(pos)):
            i = idx[n].get(t)
            if i is None:
                continue
            p, O = pos[n], syms[n].o[i]
            if p["stop"] is not None and ((p["d"] > 0 and O <= p["stop"]) or (p["d"] < 0 and O >= p["stop"])):
                close(n, O, "STOP_GAP", t, "OPEN")
            elif pend_exit.pop(n, None):
                close(n, O, "EXIT_SIGNAL", t, "OPEN")
            elif t == last_day:
                close(n, O, "PARTITION_END", t, "OPEN")
        pend_exit.clear()
        # 3) girişler
        for n in sorted(pend_entry):
            sig = pend_entry[n]
            i = idx[n].get(t)
            if i is None or n in pos or t == last_day:
                blocked.append(dict(symbol=n, signal_time=sig["sig"], reason="PARTITION_TAIL_BLOCKED" if t == last_day
                                    else ("POSITION_BLOCKED" if n in pos else "DATA_INVALID")))
                continue
            s, d, S0 = syms[n], sig["d"], sig["S0"]
            O = s.o[i]
            if (d > 0 and not O > S0) or (d < 0 and not O < S0):
                blocked.append(dict(symbol=n, signal_time=sig["sig"], reason="OPEN_OUTSIDE_PLAN"))
                continue
            E = entry_fill(O, d, cost.entry_slip_bp, s.tick)
            dist = abs(E - S0)
            eq_now = led.wallet + sum(pp["d"] * (syms[m].o[idx[m][t]] - pp["E"]) * pp["q"]
                                      for m, pp in pos.items() if t in idx[m])
            n_risk = floor_step(risk_per / dist / s.cs, s.vu)
            n_not = floor_step(C.LIVE_GATES["POSITION_CAP_FRACTION"] * eq_now / (E * s.cs), s.vu)
            need = E * s.cs / lev + E * s.cs * (cost.entry_fee_rate + cost.exit_fee_rate)
            n_mar = floor_step(max(0.0, C.LIVE_GATES["MARGIN_PREFLIGHT_FRAC"] * led.free_collateral) / need, s.vu)
            nq = min(n_risk, n_not, n_mar)
            if sum(pp["R0"] for pp in pos.values()) + max(nq, s.mv) * s.cs * dist > risk_cap + 1e-6:
                blocked.append(dict(symbol=n, signal_time=sig["sig"], reason="RISK_CAP_BLOCKED"))
                continue
            if nq < s.mv - 1e-12:
                blocked.append(dict(symbol=n, signal_time=sig["sig"],
                                    reason="MIN_ORDER_BLOCKED" if n_risk < s.mv else "MARGIN_BLOCKED"))
                continue
            q = nq * s.cs
            fee = abs(E * q) * cost.entry_fee_rate
            margin = E * q / lev
            led.open(margin, fee)
            tid += 1
            pos[n] = dict(id=f"{vid}|{cost.name}|{tid}", d=d, E=E, q=q, S0=S0, stop=S0 if X != "XH" else None,
                          xh_stop=S0 if X == "XH" else None, best=sig["c"], fee_in=fee, margin=margin,
                          R0=dist * q, fund=0.0, t=t, sig=sig["sig"])
        pend_entry.clear()
        # 4) gün içi stop (X3/X5)
        for n in sorted(list(pos)):
            p = pos[n]
            i = idx[n].get(t)
            if i is None or p["stop"] is None:
                continue
            s = syms[n]
            if (p["d"] > 0 and s.l[i] <= p["stop"]) or (p["d"] < 0 and s.h[i] >= p["stop"]):
                close(n, p["stop"], "STOP", t, "INTRADAY")
        # 5) funding: (t, t+1g] içindeki settlement'lar, açık pozisyonlar
        for n, p in pos.items():
            s = syms[n]
            a = np.searchsorted(s.f_t, max(t, p["t"]), side="right")
            b = np.searchsorted(s.f_t, t + DAY, side="right")
            if b > a:
                i = idx[n].get(t)
                if i is None:            # o gün mum yok: settlement fiyatı bilinmiyor → sayılır, ücretlenmez
                    missing_fund[0] += b - a
                    continue
                cf = sum(funding_cashflow(p["d"], p["q"], s.o[i], r) for r in s.f_r[a:b])
                p["fund"] += cf
                led.fund(cf)
        # 6) kapanış: stop güncelle, XH çıkışı, yeni sinyaller
        for n, s in syms.items():
            i = idx[n].get(t)
            if i is None or i < WARMUP_DAYS:
                continue
            hh, ll, llh, hhh, atr = ind[n]
            c = s.c[i]
            if n in pos:
                p = pos[n]
                if X in ("X3", "X5") and np.isfinite(atr[i]):
                    p["best"] = max(p["best"], c) if p["d"] > 0 else min(p["best"], c)
                    cand = p["best"] - p["d"] * k_mult * atr[i]
                    p["stop"] = max(p["stop"], cand) if p["d"] > 0 else min(p["stop"], cand)
                elif X == "XH":
                    if (p["d"] > 0 and c < ll_prev_half(s, i, N)) or (p["d"] < 0 and c > hh_prev_half(s, i, N)):
                        pend_exit[n] = True
                p["mfe_c"] = max(p.get("mfe_c", 0.0), p["d"] * (c - p["E"]))
                if early_days and (t + DAY - p["t"]) >= early_days * DAY and p["mfe_c"] < abs(p["E"] - p["S0"]):
                    pend_exit[n] = True                     # kırılım tutmadı: +1R'ye ulaşmadı
                continue
            if not (np.isfinite(hh[i]) and np.isfinite(atr[i]) and atr[i] > 0):
                continue
            if nwk is not None:
                d = nwk[n].get(i, 0)
                if side == "L" and d < 0:
                    d = 0
            else:
                d = 1 if c > hh[i] else (-1 if (side == "LS" and c < ll[i]) else 0)
            if not d:
                continue
            if X == "XH":
                S0 = ll_prev_half(s, i + 1, N) if d > 0 else hh_prev_half(s, i + 1, N)
            else:
                S0 = c - d * k_mult * atr[i]
            if not np.isfinite(S0) or (d > 0 and S0 >= c) or (d < 0 and S0 <= c):
                continue
            pend_entry[n] = dict(d=d, S0=float(S0), c=float(c), sig=int(t + DAY))
        # 7) özsermaye kesiti
        unr = sum(pp["d"] * (syms[m].c[idx[m][t]] - pp["E"]) * pp["q"] for m, pp in pos.items() if t in idx[m])
        equity.append((t + DAY, led.wallet + unr, len(pos), sum(pp["R0"] for pp in pos.values())))
    led.missing_funding_settlements = missing_fund[0]
    return trades, blocked, equity, led, pos


def ll_prev_half(s, i, N):
    """i gününden ÖNCEKİ N/2 günün en düşük dibi (i dahil değil)."""
    h = max(1, N // 2)
    return float(np.min(s.l[max(0, i - h):i])) if i - h >= 0 else np.nan


def hh_prev_half(s, i, N):
    h = max(1, N // 2)
    return float(np.max(s.h[max(0, i - h):i])) if i - h >= 0 else np.nan
