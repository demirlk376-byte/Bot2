"""
5m araştırma yürütme adaptörü (şartname §12, §14, §15). Tek küresel saat; her 5m sınırı t'de:

  1. Tüm sembollerde az önce biten [t-5m,t) barının açık pozisyon stop/hedef olayları (bar içi).
  2. Ortak kapanış fiyatları (mark = close[t-5m]); UTC gün değiştiyse gün başı özsermayesi.
  3. Tam t'deki funding — önceki bar çözümünden sonra hâlâ açık pozisyonlara.
  4. Kapanış kesiti: bakiye, marjin, açık PnL, özsermaye kaydı (yeni emirlerden ÖNCE).
  5–6. Yeni tamamlanan veri + nihai sinyaller (setup makinesinde önceden hesaplandı; yalnız
       signal_time == t olanlar burada görünür → gelecek sızmaz).
  7. t açılışı yalnız yürütmeye: mevcut pozisyonların açılış boşluğu (STOP>TARGET) ve 12 saat
     zaman çıkışı.
  8–10. F1 + portföy kapıları, sembol adına göre kararlı sıra, aynı sembolde zıt niyetler iptal,
     miktar/maliyet, açılış. Yeni pozisyonun ilk bar high/low'u bir sonraki sınırda işlenir.

Strateji emir açmaz; bu modül emir niyetini yürütür. Fiyat/maliyet yalnız BURADA uygulanır.
"""
from __future__ import annotations

import numpy as np

from . import config as C
from .accounting import Ledger, Position, entry_fill, exit_fill, floor_step, funding_cashflow

EQUITY_FIELDS = ["timestamp_utc", "snapshot_phase", "cash_balance", "reserved_margin",
                 "unposted_entry_fee_accrual", "funding_accrual_if_any", "unrealized_PnL", "equity",
                 "open_positions", "long_notional", "short_notional", "gross_initial_stop_risk",
                 "additional_loss_to_stops", "cumulative_fees", "cumulative_funding"]


class RunResult:
    def __init__(self):
        self.trades = []
        self.outcomes = []            # her sinyal/olay için portföy terminali
        self.equity = []              # EQUITY_FIELDS satırları
        self.flags = {"data_gap_positions": 0, "funding_off_grid": 0, "identity_max_gap": 0.0,
                      "censored_open_at_end": 0, "stale_mark": 0}
        self.counters = {}


def simulate(variant_id, phase, window, signals, universe, cost, C0, record_equity=True):
    """signals: bu varyant/bölüm için SetupRecord listesi (terminal SIGNAL olanlar; F zaten
    uygulanmış). Döner RunResult."""
    syms = universe["symbols"]
    start, end = window
    g0 = universe["g0"]
    k_start, k_end = (start - g0) // C.M5, (end - g0) // C.M5
    led = Ledger(C0)
    res = RunResult()
    risk_per_trade = C.PER_TRADE_RISK_FRAC * C0
    risk_cap = C.PORTFOLIO_RISK_CAP_FRAC * C0
    tol = max(1e-6, C0 * 1e-10)
    lev = C.LIVE_GATES["LEVERAGE"]
    by_time = {}
    for r in signals:
        by_time.setdefault(r.signal_time, []).append(r)
    open_pos: dict[str, Position] = {}
    marks = {}
    for s, sd in syms.items():
        k = k_start - 1
        marks[s] = float(sd.c[k]) if k >= 0 and sd.valid5[k] else np.nan
    # funding olayları: (sınır indeksi → [(sembol, oran, ızgarada mı)])
    fund = {}
    for s, sd in syms.items():
        for t, rate, on in zip(sd.funding_t, sd.funding_rate, sd.funding_on_grid):
            if start <= t <= end:
                kk = int(-(-(int(t) - g0) // C.M5))         # ızgarada değilse SONRAKİ sınır (bayraklı)
                fund.setdefault(kk, []).append((s, float(rate), bool(on)))
    day_start_equity = C0
    tid = 0

    def close_pos(p: Position, ref, reason, k_ev, phase_tag, ambiguous=False):
        sd = syms[p.symbol]
        xf = exit_fill(ref, p.d, cost.exit_slip_bp, sd.tick)
        gross = p.d * (xf - p.E_fill) * p.q_base
        fee = abs(xf * p.q_base) * cost.exit_fee_rate
        led.close(gross, fee, p.margin)
        led.slip_cost_diag += abs(xf - ref) * p.q_base
        net = gross - p.entry_fee - fee + p.funding
        t_ev = g0 + k_ev * C.M5
        if phase_tag == "INTRABAR":
            iv0, iv1 = t_ev - C.M5, t_ev
        else:
            iv0 = iv1 = t_ev
        rec = p.rec
        res.trades.append(dict(
            trade_id=p.trade_id, market_event_id=rec.market_event_id, variant_id=variant_id, phase=phase,
            cost_scenario=cost.name, symbol=p.symbol, side="LONG" if p.d > 0 else "SHORT",
            signal_time=rec.signal_time, order_time=p.entry_time, fill_time=p.entry_time, E_plan=rec.E_plan,
            entry_open=p.entry_open, E_budget=p.E_budget, E_fill=p.E_fill, S_raw=rec.S_raw, S=p.S,
            T_raw=rec.T_raw, T=p.T, contract_size=p.contract_size, quantity_contracts=p.q_contracts,
            quantity_base=p.q_base, initial_margin=p.margin, R0_USDT=p.R0, exit_interval_start=iv0,
            exit_interval_end=iv1, exit_phase=phase_tag, X_reference=ref, X_fill=xf, exit_reason=reason,
            gross_PnL=gross, entry_fee=p.entry_fee, exit_fee=fee, funding_cashflow=p.funding, net_PnL=net,
            net_R=(net / p.R0) if p.R0 > 0 and np.isfinite(p.R0) else np.nan, ambiguity_flag=ambiguous,
            data_gap=p.data_gap, funding_events=p.funding_events))
        res.outcomes.append(dict(market_event_id=rec.market_event_id, symbol=p.symbol, signal_time=rec.signal_time,
                                 terminal_status="CLOSED", reason_code=reason, trade_id=p.trade_id))
        del open_pos[p.symbol]

    for k in range(k_start, k_end + 1):
        t = g0 + k * C.M5
        # 1) bar içi çıkışlar: [t-5m, t)
        for s in sorted(open_pos):
            p = open_pos[s]
            if p.entry_k > k - 1:
                continue
            sd = syms[s]
            b = k - 1
            if not sd.valid5[b]:
                if not p.data_gap:
                    res.flags["data_gap_positions"] += 1
                p.data_gap = True
                continue
            lo, hi = sd.l[b], sd.h[b]
            eps = sd.tick * 1e-6
            if p.d > 0:
                st, tg = lo <= p.S + eps, hi >= p.T - eps
            else:
                st, tg = hi >= p.S - eps, lo <= p.T + eps
            if st and tg:
                close_pos(p, p.S, "STOP", k, "INTRABAR", ambiguous=True)
            elif st:
                close_pos(p, p.S, "STOP", k, "INTRABAR")
            elif tg:
                close_pos(p, p.T, "TARGET", k, "INTRABAR")
        # 2) ortak kapanış fiyatları
        for s, sd in syms.items():
            b = k - 1
            if b >= 0 and sd.valid5[b]:
                marks[s] = float(sd.c[b])
            elif s in open_pos:
                res.flags["stale_mark"] += 1
        if t % C.DAY == 0 or k == k_start:
            day_start_equity = led.wallet + sum(p.unrealized(marks[s]) for s, p in open_pos.items())
        # 3) funding (t'den önce açılmış ve t'ye ulaşmış pozisyonlar)
        for s, rate, on in fund.get(k, ()):
            p = open_pos.get(s)
            if p is None or p.entry_k >= k:
                continue
            if not on:
                res.flags["funding_off_grid"] += 1
            cf = funding_cashflow(p.d, p.q_base, marks[s], rate)
            p.funding += cf
            p.funding_events += 1
            led.fund(cf)
        # 4) kapanış kesiti
        unr = sum(p.unrealized(marks[s]) for s, p in open_pos.items())
        gap = abs(led.identity_gap())
        res.flags["identity_max_gap"] = max(res.flags["identity_max_gap"], gap)
        if record_equity:
            ln = sum(p.q_base * marks[s] for s, p in open_pos.items() if p.d > 0)
            sn = sum(p.q_base * marks[s] for s, p in open_pos.items() if p.d < 0)
            res.equity.append((t, "CLOSE", led.wallet, led.reserved_margin, 0.0, 0.0, unr, led.wallet + unr,
                               len(open_pos), ln, sn, sum(p.R0 for p in open_pos.values()),
                               sum(p.loss_to_stop(marks[s]) for s, p in open_pos.items()), led.fees, led.funding))
        if k == k_end:
            break
        # 7) açılış: boşluk ve zaman çıkışları
        for s in sorted(open_pos):
            p = open_pos[s]
            sd = syms[s]
            if not sd.valid5[k]:
                if not p.data_gap:
                    res.flags["data_gap_positions"] += 1
                p.data_gap = True
                continue
            O = float(sd.o[k])
            if (O <= p.S) if p.d > 0 else (O >= p.S):
                close_pos(p, O, "STOP", k, "OPEN")
            elif (O >= p.T) if p.d > 0 else (O <= p.T):
                close_pos(p, O, "TARGET", k, "OPEN")
            elif t - p.entry_time >= C.MAX_HOLD_MS:
                close_pos(p, O, "TIME_EXIT", k, "OPEN")
        # 8–10) yeni girişler
        cands = by_time.get(t, [])
        if not cands:
            continue
        survivors = []
        for r in sorted(cands, key=lambda x: (x.symbol, x.side)):
            sd = syms[r.symbol]
            d = 1 if r.side == "LONG" else -1
            if t >= end:
                _block(res, r, "CENSORED")
                continue
            if t >= end - C.PARTITION_TAIL_MS:
                _block(res, r, "PARTITION_TAIL_BLOCKED")
                continue
            if not sd.valid5[k]:
                _block(res, r, "DATA_INVALID")
                continue
            O = float(sd.o[k])
            if not ((r.S < O < r.T) if d > 0 else (r.T < O < r.S)):
                _block(res, r, "OPEN_OUTSIDE_PLAN")
                continue
            if r.symbol in open_pos:
                _block(res, r, "POSITION_BLOCKED")
                continue
            survivors.append((r, d, O))
        sides = {}
        for r, d, O in survivors:
            sides.setdefault(r.symbol, set()).add(d)
        final = []
        for r, d, O in survivors:
            if len(sides[r.symbol]) > 1:
                _block(res, r, "OPPOSITE_SIGNALS_SAME_TIME")
            else:
                final.append((r, d, O))
        for r, d, O in final:                      # sembol adına göre sıralı
            sd = syms[r.symbol]
            if r.symbol in open_pos:               # aynı sembolde aynı anda ikinci niyet (ayrılmış yuva)
                _block(res, r, "POSITION_BLOCKED")
                continue
            if len(open_pos) >= C.LIVE_GATES["MAX_POSITIONS"]:
                _block(res, r, "MAX_POSITIONS_BLOCKED")
                continue
            equity_now = led.wallet + sum(p.unrealized(marks[s]) for s, p in open_pos.items())
            if equity_now <= day_start_equity * (1 - C.LIVE_GATES["DAILY_MAX_LOSS_PCT"]):
                _block(res, r, "DAILY_LOSS_BLOCKED")
                continue
            E_budget = entry_fill(O, d, cost.entry_slip_bp, sd.tick)
            dist = abs(E_budget - r.S)
            if not (dist > 0 and np.isfinite(dist)):
                _block(res, r, "INVALID_GEOMETRY")
                continue
            q_risk = risk_per_trade / dist
            n_risk = floor_step(q_risk / sd.contract_size, sd.vol_unit)
            # dondurulmuş notional / marjin sınırları → miktarı AŞAĞI yuvarla
            per_c_notional = E_budget * sd.contract_size
            n_notional = floor_step(C.LIVE_GATES["POSITION_CAP_FRACTION"] * equity_now / per_c_notional,
                                    sd.vol_unit)
            per_c_need = per_c_notional / lev + per_c_notional * (cost.entry_fee_rate + cost.exit_fee_rate)
            free = led.free_collateral
            n_margin = floor_step(max(0.0, C.LIVE_GATES["MARGIN_PREFLIGHT_FRAC"] * free) / per_c_need,
                                  sd.vol_unit)
            n = min(n_risk, n_notional, n_margin)
            if n < sd.min_vol - 1e-12:
                _block(res, r, "MIN_ORDER_BLOCKED" if n_risk < sd.min_vol - 1e-12 else "MARGIN_BLOCKED")
                continue
            q_base = n * sd.contract_size
            new_risk = q_base * dist
            if sum(p.R0 for p in open_pos.values()) + new_risk > risk_cap + tol:
                _block(res, r, "RISK_CAP_BLOCKED")
                continue
            E_fill = E_budget                       # deterministik model: E_budget == E_fill
            notional = E_fill * q_base
            margin = notional / lev
            fee = abs(notional) * cost.entry_fee_rate
            led.open(margin, fee)
            led.slip_cost_diag += abs(E_fill - O) * q_base
            tid += 1
            p = Position(trade_id=f"{variant_id}|{phase}|{cost.name}|{tid}", symbol=r.symbol, d=d, q_contracts=n,
                         q_base=q_base, contract_size=sd.contract_size, E_fill=E_fill, S=r.S, T=r.T, entry_k=k,
                         entry_time=t, entry_open=O, E_budget=E_budget, margin=margin, entry_fee=fee,
                         R0=abs(E_fill - r.S) * q_base, rec=r)
            open_pos[r.symbol] = p
            res.outcomes.append(dict(market_event_id=r.market_event_id, symbol=r.symbol, signal_time=r.signal_time,
                                     terminal_status="FILLED", reason_code="FILLED", trade_id=p.trade_id))
            # dolum sonrası geometri koruması (kayma hedefi/stopu geçtiyse) — sinyal iptali DEĞİL
            if not ((r.S < E_fill < r.T) if d > 0 else (r.T < E_fill < r.S)):
                close_pos(p, O, "GEOMETRY_PROTECT_CLOSE", k, "OPEN")
    for s, p in list(open_pos.items()):
        res.flags["censored_open_at_end"] += 1
        res.outcomes.append(dict(market_event_id=p.rec.market_event_id, symbol=s, signal_time=p.rec.signal_time,
                                 terminal_status="CENSORED", reason_code="CENSORED", trade_id=p.trade_id))
    res.ledger = led
    res.window = window
    return res


def _block(res, r, code):
    res.outcomes.append(dict(market_event_id=r.market_event_id, symbol=r.symbol, signal_time=r.signal_time,
                             terminal_status=code, reason_code=code, trade_id=None))
