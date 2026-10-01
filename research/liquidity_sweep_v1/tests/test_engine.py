"""
Bağımsız yürütme-motoru testleri — şartname §12 (giriş anı, risk bütçesi, miktar), §14 (çıkış
sırası ve boşluklar), §15 (aynı zaman damgasında olay sırası) ve §21 fixture No.10, 12, 23, 24,
25, 26, 27, 28, 34, 36, 37. Bütün yollar replay_adapter.simulate üzerinden geçer; sinyaller
SetupRecord olarak doğrudan kurulur (§21: fixture yalnız odaklandığı kuralı izole eder).

Beklenen bütün sayılar ŞARTNAMEDEN elle türetilmiş sabitlerdir; üretim fonksiyonu yeniden
çağrılarak hesaplanmaz. Varsayılan test varsayımları (§21): ücret/kayma sıfır, contract_size=1,
fiyat adımı 0,01; miktar adımı 0,1 (No.28). C0=10.000 → per_trade_risk=25, risk cap=100.

Fixture düzeni:
  * 5m ızgara, G0 = 2023-01-01 00:00 UTC, 3 gün. Değerlendirme penceresi [G0, G0+3 gün)
    (PARTITION_TAIL testinde [G0, G0+2 gün)).
  * Her sembol düz bir fiyatla (O=H=L=C=P) doldurulur; yalnız ilgili barlar ezilir.
  * Kısa yön aynası x → 200 − x (No.24–27, 36 vb.); OHLC rolleri değişir:
    (O,H,L,C) → (200−O, 200−L, 200−H, 200−C). No.10/No.12 için şartnamenin kendi
    long/short çifti kullanılır (L=100 ↔ L=110). Kısa yön beklenen değerleri de elle yazılmıştır.
"""
from __future__ import annotations

import numpy as np
import pytest

from research.liquidity_sweep_v1 import config as C
from research.liquidity_sweep_v1 import data_contract as D
from research.liquidity_sweep_v1 import replay_adapter as RA
from research.liquidity_sweep_v1.setups import SetupRecord

G0 = 1_672_531_200_000            # 2023-01-01 00:00 UTC
M5, H1, DAY = 5 * 60_000, 3_600_000, 86_400_000
N_DAYS = 3
N5 = N_DAYS * 288
WINDOW = (G0, G0 + N_DAYS * DAY)
C0 = 10_000.0
AP = dict(abs=1e-9)
MP = 200.0                        # ayna merkezi


def K(day, hh, mm):
    """Gün/saat/dakikadan 5m bar indeksi."""
    return day * 288 + hh * 12 + mm // 5


def T(k):
    return G0 + k * M5


def mir(bar, P=MP):
    O, H, L, Cc = bar
    return (round(P - O, 2), round(P - L, 2), round(P - H, 2), round(P - Cc, 2))


def mirror_bars(bars, P=MP):
    return {k: mir(b, P) for k, b in bars.items()}


def cost(entry_fee=0.0, exit_fee=0.0, entry_slip=0.0, exit_slip=0.0):
    return C.CostProfile(name="NORMAL", entry_fee_rate=entry_fee, exit_fee_rate=exit_fee,
                         entry_slip_bp=entry_slip, exit_slip_bp=exit_slip, source="test")


ZERO = cost()


def make_sd(sym, P, bars=None, tick=0.01, cs=1.0, vol_unit=0.1, min_vol=0.1, funding=(), invalid=()):
    o, h, l, c = (np.full(N5, float(P)) for _ in range(4))
    for k, (O, H, L, Cc) in (bars or {}).items():
        assert L <= min(O, Cc) and max(O, Cc) <= H, (k, O, H, L, Cc)
        o[k], h[k], l[k], c[k] = O, H, L, Cc
    valid = np.ones(N5, bool)
    for k in invalid:
        o[k] = h[k] = l[k] = c[k] = np.nan
        valid[k] = False
    ft = np.array([t for t, _ in funding], dtype="int64")
    fr = np.array([r for _, r in funding], dtype=float)
    return D.SymbolData(symbol=sym, source="TEST", g0=G0, o=o, h=h, l=l, c=c, v=np.ones(N5), valid5=valid,
                        tick=tick, contract_size=cs, vol_unit=vol_unit, min_vol=min_vol, meta_source="test",
                        funding_t=ft, funding_rate=fr, funding_on_grid=np.ones(len(ft), bool),
                        funding_source="TEST" if len(ft) else "NOT_MODELED")


def sig(sym, side, t_sig, E, S, T_, meid=None):
    meid = meid or f"{sym}|{side}|{t_sig}"
    return SetupRecord(variant_base="L1_K1", market_event_id=meid, symbol=sym, side=side, level_id=f"lv|{meid}",
                       level_known_at=G0, level_expires_at=G0 + 10 * DAY, sweep_open=t_sig - 15 * 60_000,
                       sweep_close=t_sig, ATR15_frozen=2.0, terminal_status="SIGNAL", terminal_time=t_sig,
                       signal_time=t_sig, E_plan=E, S_raw=S, S=S, T_raw=T_, T=T_, F1_pass=True)


def run(signals, sds, cst=ZERO, window=WINDOW, c0=C0):
    U = dict(symbols={sd.symbol: sd for sd in sds}, g0=G0)
    return RA.simulate("L1_K1_F0", "DISCOVERY", window, signals, U, cst, c0)


def statuses(res, meid):
    return [o["terminal_status"] for o in res.outcomes if o["market_event_id"] == meid]


def trades_of(res, meid):
    return [t for t in res.trades if t["market_event_id"] == meid]


def eq_row(res, t):
    rows = [r for r in res.equity if r[0] == t]
    assert len(rows) == 1
    return dict(zip(RA.EQUITY_FIELDS, rows[0]))


# ═══════════════════════ No.10 / No.12 / No.28 — giriş anı ve miktar ═══════════════════════
# No.9: 13:00–13:15 K1 long, L=100, A=2, low=99,50, close=100,60 → S=99,30; T=103,20.
# No.11: K1 short, L=110, A=2, high=110,50, close=109,40 → S=110,70; T=106,80.
K_SIG_LAST = K(0, 13, 10)         # 13:00–13:15 15m barının son 5m barı (kapanışı = E_plan)
K_ENTRY = K(0, 13, 15)            # sinyal 13:15 → ilk yeni 5m açılış
K_TGT = K(0, 14, 10)              # sonradan hedef teması

NO10 = {
    "LONG": dict(flat=100.70, E=100.60, S=99.30, T=103.20,
                 bars={K(0, 13, 0): (100.70, 100.70, 99.50, 99.60), K(0, 13, 5): (99.60, 100.20, 99.60, 100.10),
                       K_SIG_LAST: (100.10, 100.70, 100.10, 100.60),
                       K_ENTRY: (100.80, 101.10, 100.70, 101.00),
                       K_TGT: (100.90, 103.30, 100.80, 103.00)},
                 O=100.80, entry_close=101.00, R=1.50, gain=2.40, Q=16.6, R0=24.9, X=103.20, gross=39.84),
    "SHORT": dict(flat=109.30, E=109.40, S=110.70, T=106.80,
                  bars={K(0, 13, 0): (109.30, 110.50, 109.30, 110.40), K(0, 13, 5): (110.40, 110.40, 109.80, 109.90),
                        K_SIG_LAST: (109.90, 109.90, 109.30, 109.40),
                        K_ENTRY: (109.20, 109.30, 109.00, 109.10),
                        K_TGT: (109.10, 109.20, 106.70, 106.90)},
                  O=109.20, entry_close=109.10, R=1.50, gain=2.40, Q=16.6, R0=24.9, X=106.80, gross=39.84),
}


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_no10_no12_entry_at_next_5m_open_and_frozen_target(side):
    f = NO10[side]
    sd = make_sd("AAA", f["flat"], f["bars"])
    r = sig("AAA", side, T(K_ENTRY), f["E"], f["S"], f["T"])
    res = run([r], [sd])
    assert statuses(res, r.market_event_id) == ["FILLED", "CLOSED"]
    (tr,) = res.trades
    # giriş yalnız 13:15 açılışında; 13:15–13:20 kapanışı veya 13:00–13:15 kapanışı (E_plan) değil
    assert tr["fill_time"] == G0 + 13 * H1 + 15 * 60_000
    assert tr["entry_open"] == pytest.approx(f["O"], **AP)
    assert tr["E_fill"] == pytest.approx(f["O"], **AP)
    assert tr["E_fill"] != pytest.approx(f["entry_close"], abs=1e-6)
    assert tr["E_fill"] != pytest.approx(f["E"], abs=1e-6)
    assert tr["E_plan"] == pytest.approx(f["E"], **AP)
    # T değişmez (dolumdan sonra 2R'ye taşınmaz)
    assert tr["S"] == pytest.approx(f["S"], **AP)
    assert tr["T"] == pytest.approx(f["T"], **AP)
    assert abs(tr["E_fill"] - tr["S"]) == pytest.approx(f["R"], abs=1e-9)          # R mesafesi 1,50
    assert abs(tr["T"] - tr["E_fill"]) == pytest.approx(f["gain"], abs=1e-9)       # hedef kazancı 2,40
    assert abs(tr["T"] - tr["E_fill"]) / abs(tr["E_fill"] - tr["S"]) == pytest.approx(1.60, abs=1e-9)
    # No.28: Q = floor_0.1(25/1,50)=16,6 ; R0=24,9
    assert tr["quantity_base"] == pytest.approx(f["Q"], abs=1e-9)
    assert tr["R0_USDT"] == pytest.approx(f["R0"], abs=1e-9)
    # hedef bar içi teması → referans T; brüt = 2,40 × 16,6 ; brüt efektif RR = 1,60
    assert tr["exit_reason"] == "TARGET"
    assert tr["X_reference"] == pytest.approx(f["X"], **AP)
    assert tr["X_fill"] == pytest.approx(f["X"], **AP)
    assert tr["gross_PnL"] == pytest.approx(f["gross"], abs=1e-9)
    assert tr["net_R"] == pytest.approx(1.60, abs=1e-9)
    assert tr["exit_interval_start"] == T(K_TGT) and tr["exit_interval_end"] == T(K_TGT) + M5
    assert res.ledger.wallet == pytest.approx(C0 + f["gross"], abs=1e-9)


# No.28 (+ kaymalı varyant): E_budget kaymalı açılıştan, tick'e aleyhe (alış yukarı, satış aşağı).
#  long : O=100,80 × (1+0,001585)=100,959768 → 100,96 ; |E−S|=1,66 ; 25/1,66=15,06 → Q=15,0 ; R0=24,90
#  short: O=109,20 × (1−0,001585)=109,026918 → 109,02 ; |E−S|=1,68 ; 25/1,68=14,88 → Q=14,8 ; R0=24,864
@pytest.mark.parametrize("side,E_budget,Q,R0", [("LONG", 100.96, 15.0, 24.90), ("SHORT", 109.02, 14.8, 24.864)])
def test_no28_quantity_from_E_budget_with_entry_slippage(side, E_budget, Q, R0):
    f = NO10[side]
    sd = make_sd("AAA", f["flat"], f["bars"])
    r = sig("AAA", side, T(K_ENTRY), f["E"], f["S"], f["T"])
    res = run([r], [sd], cst=cost(entry_slip=15.85))
    (tr,) = res.trades
    assert tr["E_budget"] == pytest.approx(E_budget, abs=1e-9)
    assert tr["E_fill"] == pytest.approx(E_budget, abs=1e-9)        # deterministik: E_budget == E_fill
    assert tr["quantity_base"] == pytest.approx(Q, abs=1e-9)
    assert tr["R0_USDT"] == pytest.approx(R0, abs=1e-9)
    assert tr["T"] == pytest.approx(f["T"], **AP)                   # T dolum fiyatına göre yeniden ayarlanmaz


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_no28_contracts_vs_base_floor(side):
    """contract_size=0,1; sözleşme adımı 1: Q_risk=16,667 base → 166,67 sözleşme → 166 → Q_base=16,6."""
    f = NO10[side]
    sd = make_sd("AAA", f["flat"], f["bars"], cs=0.1, vol_unit=1.0, min_vol=1.0)
    r = sig("AAA", side, T(K_ENTRY), f["E"], f["S"], f["T"])
    res = run([r], [sd])
    (tr,) = res.trades
    assert tr["quantity_contracts"] == pytest.approx(166.0, abs=1e-9)
    assert tr["quantity_base"] == pytest.approx(16.6, abs=1e-9)
    assert tr["R0_USDT"] == pytest.approx(24.9, abs=1e-9)
    assert tr["gross_PnL"] == pytest.approx(39.84, abs=1e-9)


@pytest.mark.parametrize("side,min_vol", [("LONG", 17.0), ("SHORT", 17.0), ("LONG", 16.7), ("SHORT", 16.7)])
def test_no28_min_order_blocked_never_rounded_up(side, min_vol):
    """Q=16,6 < minimum → MIN_ORDER_BLOCKED; 16,7'ye/17'ye yukarı büyütme yok (§12.3)."""
    f = NO10[side]
    sd = make_sd("AAA", f["flat"], f["bars"], min_vol=min_vol)
    r = sig("AAA", side, T(K_ENTRY), f["E"], f["S"], f["T"])
    res = run([r], [sd])
    assert res.trades == []
    assert statuses(res, r.market_event_id) == ["MIN_ORDER_BLOCKED"]           # No.34: tekrar emir yok
    assert res.ledger.wallet == C0 and res.ledger.fees == 0.0


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_no28_min_order_equal_to_floor_quantity_is_allowed(side):
    f = NO10[side]
    sd = make_sd("AAA", f["flat"], f["bars"], min_vol=16.6)
    r = sig("AAA", side, T(K_ENTRY), f["E"], f["S"], f["T"])
    res = run([r], [sd])
    (tr,) = res.trades
    assert tr["quantity_base"] == pytest.approx(16.6, abs=1e-9)


# ═══════════════════════════════ No.23 — OPEN_OUTSIDE_PLAN ════════════════════════════════
@pytest.mark.parametrize("side,O,expect", [
    ("LONG", 103.20, "OPEN_OUTSIDE_PLAN"), ("LONG", 103.50, "OPEN_OUTSIDE_PLAN"),
    ("LONG", 99.30, "OPEN_OUTSIDE_PLAN"), ("LONG", 99.00, "OPEN_OUTSIDE_PLAN"), ("LONG", 103.19, "FILLED"),
    ("SHORT", 106.80, "OPEN_OUTSIDE_PLAN"), ("SHORT", 106.50, "OPEN_OUTSIDE_PLAN"),
    ("SHORT", 110.70, "OPEN_OUTSIDE_PLAN"), ("SHORT", 111.00, "OPEN_OUTSIDE_PLAN"), ("SHORT", 106.81, "FILLED"),
])
def test_no23_open_outside_plan_and_no_chasing(side, O, expect):
    f = NO10[side]
    bars = dict(f["bars"])
    bars.pop(K_TGT)
    bars[K_ENTRY] = (O, O, O, O)
    bars[K_ENTRY + 1] = (f["O"], f["O"], f["O"], f["O"])      # bir sonraki açılış plana geri döner
    sd = make_sd("AAA", f["flat"], bars)
    r = sig("AAA", side, T(K_ENTRY), f["E"], f["S"], f["T"])
    res = run([r], [sd])
    st = statuses(res, r.market_event_id)
    if expect == "OPEN_OUTSIDE_PLAN":
        assert st == ["OPEN_OUTSIDE_PLAN"]                     # kuyrukta bekletme / kovalamaca yok
        assert res.trades == []
        assert res.flags["censored_open_at_end"] == 0
    else:
        assert st[0] == "FILLED"
        assert res.trades[0]["E_fill"] == pytest.approx(O, **AP)


# ═════════════════════ Giriş barında stop; önceki barın fitili uygulanmaz ═════════════════════
@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_signal_bar_wick_does_not_touch_new_position(side):
    """Sinyal barı (13:10–13:15) hem S'nin altına hem T'nin üstüne fitil atar; 13:15 açılışında
    açılan pozisyon bundan etkilenmez — çıkış daha sonraki hedef temasıdır (§14 giriş paragrafı)."""
    f = NO10[side]
    bars = dict(f["bars"])
    if side == "LONG":
        bars[K_SIG_LAST] = (100.10, 103.50, 99.00, 100.60)
    else:
        bars[K_SIG_LAST] = (109.90, 111.00, 106.50, 109.40)
    sd = make_sd("AAA", f["flat"], bars)
    r = sig("AAA", side, T(K_ENTRY), f["E"], f["S"], f["T"])
    res = run([r], [sd])
    (tr,) = res.trades
    assert tr["exit_reason"] == "TARGET"
    assert tr["exit_interval_start"] == T(K_TGT)
    assert tr["X_reference"] == pytest.approx(f["X"], **AP)


@pytest.mark.parametrize("side,entry_bar,S", [
    ("LONG", (100.80, 100.90, 99.20, 99.50), 99.30),
    ("SHORT", (109.20, 110.80, 109.10, 110.50), 110.70),
])
def test_entry_bar_stop_resolved_at_next_boundary(side, entry_bar, S):
    """Giriş barının [13:15,13:20) içindeki stop teması 13:20 sınırında, referans S ile çözülür;
    açılış anında (13:15) o barın high/low'u işlenmez (§15 adım 10)."""
    f = NO10[side]
    bars = dict(f["bars"])
    bars[K_ENTRY] = entry_bar
    sd = make_sd("AAA", f["flat"], bars)
    r = sig("AAA", side, T(K_ENTRY), f["E"], f["S"], f["T"])
    res = run([r], [sd])
    (tr,) = res.trades
    assert tr["exit_reason"] == "STOP"
    assert not tr["ambiguity_flag"]
    assert tr["X_reference"] == pytest.approx(S, **AP)
    assert tr["X_fill"] == pytest.approx(S, **AP)
    assert tr["exit_interval_start"] == T(K_ENTRY)
    assert tr["exit_interval_end"] == T(K_ENTRY) + M5
    assert tr["gross_PnL"] == pytest.approx(-24.9, abs=1e-9)           # −1,50 × 16,6
    assert tr["net_R"] == pytest.approx(-1.0, abs=1e-9)
    # §15 adım 4: t kesiti yeni emirlerden ÖNCE → 13:15 kesitinde pozisyon yok; 13:20'de kapanmış
    assert eq_row(res, T(K_ENTRY))["open_positions"] == 0
    assert eq_row(res, T(K_ENTRY + 1))["open_positions"] == 0


# ═════════════════ No.24 / No.25 / No.26 — bar içi belirsizlik ve açılış boşlukları ═════════════════
# Long E=100, S=99, T=102 (No.24). Ayna (x→200−x): short E=100, S=101, T=98.
KE = K(0, 10, 0)                  # giriş açılışı 10:00
POS = {"LONG": dict(E=100.0, S=99.0, T=102.0), "SHORT": dict(E=100.0, S=101.0, T=98.0)}


def pos_fixture(side, long_bars, cst=ZERO, extra_signals=(), funding=()):
    bars = {KE: (100.0, 100.0, 100.0, 100.0)}
    bars.update(long_bars)
    if side == "SHORT":
        bars = mirror_bars(bars)
    sd = make_sd("AAA", 100.0, bars, funding=funding)
    p = POS[side]
    r = sig("AAA", side, T(KE), p["E"], p["S"], p["T"])
    return r, run([r, *extra_signals], [sd], cst=cst)


@pytest.mark.parametrize("side,ref", [("LONG", 99.0), ("SHORT", 101.0)])
@pytest.mark.parametrize("on_entry_bar", [False, True])
def test_no24_both_touched_stop_first_with_ambiguity(side, ref, on_entry_bar):
    kb = KE if on_entry_bar else KE + 1
    r, res = pos_fixture(side, {kb: (100.0, 103.0, 98.0, 100.0)})
    (tr,) = res.trades
    assert tr["exit_reason"] in ("STOP", "AMBIGUOUS_SL_TP")
    assert bool(tr["ambiguity_flag"]) is True
    assert tr["X_reference"] == pytest.approx(ref, **AP)
    assert tr["X_fill"] == pytest.approx(ref, **AP)
    assert tr["gross_PnL"] == pytest.approx(-25.0, abs=1e-9)           # Q=25/1=25 ; −1 × 25
    assert tr["net_R"] == pytest.approx(-1.0, abs=1e-9)
    assert tr["exit_interval_start"] == T(kb) and tr["exit_interval_end"] == T(kb) + M5
    assert res.ledger.wallet == pytest.approx(C0 - 25.0, abs=1e-9)


@pytest.mark.parametrize("side,X", [("LONG", 103.0), ("SHORT", 97.0)])
def test_no25_gap_beyond_target_exits_at_open_later_low_not_a_stop(side, X):
    r, res = pos_fixture(side, {KE + 1: (103.0, 104.0, 98.0, 100.0)})
    (tr,) = res.trades
    assert tr["exit_reason"] == "TARGET"
    assert not tr["ambiguity_flag"]
    assert tr["X_reference"] == pytest.approx(X, **AP)                 # T değil, açılış
    assert tr["X_fill"] == pytest.approx(X, **AP)
    assert tr["gross_PnL"] == pytest.approx(75.0, abs=1e-9)            # 3 × 25
    assert tr["net_R"] == pytest.approx(3.0, abs=1e-9)
    assert tr["exit_interval_start"] == T(KE + 1) and tr["exit_interval_end"] == T(KE + 1)
    assert statuses(res, r.market_event_id) == ["FILLED", "CLOSED"]
    # §15 adım 4 → 7: 10:05 kapanış kesiti açılış çıkışından ÖNCE (pozisyon hâlâ açık), 10:10'da yok
    assert eq_row(res, T(KE + 1))["open_positions"] == 1
    assert eq_row(res, T(KE + 2))["open_positions"] == 0
    assert res.ledger.wallet == pytest.approx(C0 + 75.0, abs=1e-9)


@pytest.mark.parametrize("side,X_ref,X_fill,gross", [
    ("LONG", 103.0, 102.79, 69.75),      # 103×(1−0,002)=102,794 → satış aşağı 102,79 ; 2,79×25
    ("SHORT", 97.0, 97.20, 70.0),        # 97×(1+0,002)=97,194 → alış yukarı 97,20 ; 2,80×25
])
def test_gap_target_exit_with_exit_slippage(side, X_ref, X_fill, gross):
    r, res = pos_fixture(side, {KE + 1: (103.0, 104.0, 98.0, 100.0)}, cst=cost(exit_slip=20.0))
    (tr,) = res.trades
    assert tr["exit_reason"] == "TARGET"
    assert tr["X_reference"] == pytest.approx(X_ref, **AP)
    assert tr["X_fill"] == pytest.approx(X_fill, abs=1e-9)
    assert tr["gross_PnL"] == pytest.approx(gross, abs=1e-9)


@pytest.mark.parametrize("side,X_ref,X_fill,gross", [
    ("LONG", 98.50, 98.30, -42.5),       # 98,50×(1−0,002)=98,303 → 98,30 ; (98,30−100)×25
    ("SHORT", 101.50, 101.71, -42.75),   # 101,50×(1+0,002)=101,703 → 101,71 ; −(101,71−100)×25
])
def test_no26_gap_through_stop_exits_at_open_not_at_S(side, X_ref, X_fill, gross):
    r, res = pos_fixture(side, {KE + 1: (98.50, 98.60, 98.00, 98.20)}, cst=cost(exit_slip=20.0))
    (tr,) = res.trades
    assert tr["exit_reason"] == "STOP"
    assert tr["X_reference"] == pytest.approx(X_ref, **AP)           # 99'dan (S) dolum yok
    assert tr["X_fill"] == pytest.approx(X_fill, abs=1e-9)
    assert tr["gross_PnL"] == pytest.approx(gross, abs=1e-9)
    assert tr["exit_interval_start"] == T(KE + 1) and tr["exit_interval_end"] == T(KE + 1)
    assert tr["R0_USDT"] == pytest.approx(25.0, abs=1e-9)


# ═══════════════════════════════ No.27 — 12 saat zaman çıkışı ════════════════════════════════
K0815 = K(0, 8, 15)
K2015 = K(0, 20, 15)


def time_fixture(side, long_bars, extra_signals=()):
    bars = {K0815: (100.0, 100.0, 100.0, 100.0)}
    bars.update(long_bars)
    if side == "SHORT":
        bars = mirror_bars(bars)
    sd = make_sd("AAA", 100.0, bars)
    p = POS[side]
    r = sig("AAA", side, T(K0815), p["E"], p["S"], p["T"])
    return r, run([r, *[s(side) for s in extra_signals]], [sd])


@pytest.mark.parametrize("side,X", [("LONG", 100.50), ("SHORT", 99.50)])
def test_no27_time_exit_exactly_12h_at_open(side, X):
    r, res = time_fixture(side, {K2015 - 1: (100.20, 100.45, 100.10, 100.40),
                                 K2015: (100.50, 100.60, 100.40, 100.55),
                                 K2015 + 1: (100.70, 100.80, 100.60, 100.70)})
    (tr,) = res.trades
    assert tr["fill_time"] == G0 + 8 * H1 + 15 * 60_000
    assert tr["exit_reason"] == "TIME_EXIT"
    assert tr["exit_interval_start"] == G0 + 20 * H1 + 15 * 60_000     # 20:15 açılışı; 20:20 değil
    assert tr["exit_interval_end"] == G0 + 20 * H1 + 15 * 60_000
    assert tr["X_reference"] == pytest.approx(X, **AP)
    assert tr["X_fill"] == pytest.approx(X, **AP)
    assert tr["gross_PnL"] == pytest.approx(12.5, abs=1e-9)            # 0,50 × 25
    assert eq_row(res, T(K2015))["open_positions"] == 1                # 20:15 kesiti çıkıştan önce
    assert eq_row(res, T(K2015 + 1))["open_positions"] == 0


@pytest.mark.parametrize("side,O,reason", [
    ("LONG", 98.90, "STOP"), ("LONG", 102.50, "TARGET"),
    ("SHORT", 101.10, "STOP"), ("SHORT", 97.50, "TARGET"),
])
def test_gap_and_time_exit_same_instant_priority(side, O, reason):
    """12. saatte açılış boşluğu da varsa neden önceliği STOP > TARGET > TIME; tek kapanış."""
    lb = O if side == "LONG" else round(MP - O, 2)
    r, res = time_fixture(side, {K2015: (lb, lb, lb, lb)})
    (tr,) = res.trades
    assert tr["exit_reason"] == reason
    assert tr["X_reference"] == pytest.approx(O, **AP)
    assert tr["exit_interval_start"] == T(K2015)


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_time_exit_then_new_entry_same_symbol_same_open(side):
    """§15: adım 7 (mevcut pozisyonun zaman çıkışı) adım 8'den (yeni giriş) önce → aynı sembolde
    tam 20:15'teki yeni sinyal POSITION_BLOCKED olmaz, 20:15 açılışında dolar."""
    p = POS[side]
    new = lambda sd_side: sig("AAA", sd_side, T(K2015), p["E"], p["S"], p["T"], meid="NEW")
    r, res = time_fixture(side, {}, extra_signals=(new,))
    assert statuses(res, "NEW")[0] == "FILLED"
    tr_new = [t for t in res.trades if t["market_event_id"] == "NEW"]
    assert res.trades[0]["exit_reason"] == "TIME_EXIT"
    assert len(tr_new) == 1 and tr_new[0]["fill_time"] == T(K2015)


# ═══════════════════════ OPPOSITE_SIGNALS_SAME_TIME / POSITION_BLOCKED ═══════════════════════
def test_opposite_signals_same_time_cancel_both_other_symbol_unaffected():
    ka = make_sd("AAA", 100.0)
    kb = make_sd("BBB", 100.0)
    t = T(KE)
    rl = sig("AAA", "LONG", t, 100.0, 99.0, 102.0, meid="A_L")
    rs = sig("AAA", "SHORT", t, 100.0, 101.0, 98.0, meid="A_S")
    rb = sig("BBB", "LONG", t, 100.0, 99.0, 102.0, meid="B_L")
    res = run([rs, rb, rl], [ka, kb])
    assert statuses(res, "A_L") == ["OPPOSITE_SIGNALS_SAME_TIME"]
    assert statuses(res, "A_S") == ["OPPOSITE_SIGNALS_SAME_TIME"]
    assert statuses(res, "B_L")[0] == "FILLED"
    assert {t_["symbol"] for t_ in res.trades} <= {"BBB"}


@pytest.mark.parametrize("side1,side2", [("LONG", "LONG"), ("LONG", "SHORT"), ("SHORT", "SHORT"), ("SHORT", "LONG")])
def test_no34_position_blocked_never_retried(side1, side2):
    """AAA pozisyonu açıkken 11:00'de gelen ikinci sinyal POSITION_BLOCKED; pozisyon 11:00–11:05
    barında hedefle kapanır, engellenen olay 11:05 ve sonrasında yeniden emir üretmez."""
    k2 = K(0, 11, 0)
    bars = {KE: (100.0, 100.0, 100.0, 100.0), k2: (100.0, 102.5, 100.0, 100.0)}
    if side1 == "SHORT":
        bars = mirror_bars(bars)
    sd = make_sd("AAA", 100.0, bars)
    p1, p2 = POS[side1], POS[side2]
    r1 = sig("AAA", side1, T(KE), p1["E"], p1["S"], p1["T"], meid="FIRST")
    r2 = sig("AAA", side2, T(k2), p2["E"], p2["S"], p2["T"], meid="SECOND")
    res = run([r1, r2], [sd])
    assert statuses(res, "SECOND") == ["POSITION_BLOCKED"]
    assert len(res.trades) == 1 and res.trades[0]["market_event_id"] == "FIRST"
    assert res.trades[0]["exit_reason"] == "TARGET"
    assert res.trades[0]["exit_interval_start"] == T(k2)


# ═══════════════════════════════ RISK_CAP_BLOCKED (§12.2) ═══════════════════════════════
SYMS5 = ["AAA", "BBB", "CCC", "DDD", "EEE"]


@pytest.mark.parametrize("side,drift,loss_to_stops", [
    # kârda: long 102,50 → (102,50−99,30)×16,6=53,12 ×4 ; short 107,50 → (110,70−107,50)×16,6 ×4
    ("LONG", 102.50, 212.48), ("SHORT", 107.50, 212.48),
    # zararda (stopa yakın): long 99,80 → 0,50×16,6=8,3 ×4=33,2 ; short 110,20 → 8,3 ×4=33,2.
    # "güncel fiyattan stopa" ölçüsü kullanılsaydı 33,2+24,9 < 100 olur ve EEE sığardı; şartname
    # İLK dolum–ilk stop mesafesini (99,6) ister → yine RISK_CAP_BLOCKED.
    ("LONG", 99.80, 33.2), ("SHORT", 110.20, 33.2),
])
def test_risk_cap_uses_initial_stop_risk_not_current(side, drift, loss_to_stops):
    """Her işlem R0=24,9 (No.28). 4 açık → 99,6; beşinci → 124,5 > 100 → RISK_CAP_BLOCKED.
    AAA..DDD 10:00'da açılır, fiyat kaydıktan sonra EEE 11:00'de gelir. Açık kâr bütçeyi
    büyütmez; açık zarar da bütçeyi serbest bırakmaz. Kesitte ilk-stop riski ve stopa kadar ek
    kayıp ayrı raporlanır (§12.2)."""
    f = NO10[side]
    t1, k2 = T(KE), K(0, 11, 0)
    sds, sigs = [], []
    for s in SYMS5[:4]:
        bars = {KE: (f["O"], f["O"], f["O"], f["O"])}
        for k in range(KE + 1, K(1, 0, 0)):
            bars[k] = (drift, drift, drift, drift)
        sds.append(make_sd(s, f["O"], bars))
        sigs.append(sig(s, side, t1, f["E"], f["S"], f["T"], meid=s))
    sds.append(make_sd("EEE", f["O"]))
    sigs.append(sig("EEE", side, T(k2), f["E"], f["S"], f["T"], meid="EEE"))
    res = run(sigs, sds)
    for s in SYMS5[:4]:
        assert statuses(res, s)[0] == "FILLED"
    assert statuses(res, "EEE") == ["RISK_CAP_BLOCKED"]
    row = eq_row(res, T(k2))
    assert row["open_positions"] == 4
    assert row["gross_initial_stop_risk"] == pytest.approx(99.6, abs=1e-9)
    assert row["additional_loss_to_stops"] == pytest.approx(loss_to_stops, abs=1e-9)


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_risk_cap_exactly_at_limit_is_allowed(side):
    """Q=25, |E−S|=1 → R0=25; dört işlem toplam 100 = sınır (aşmıyor) → dördü de dolar;
    beşinci 125 > 100 → RISK_CAP_BLOCKED."""
    p = POS[side]
    sds = [make_sd(s, 100.0) for s in SYMS5]
    sigs = [sig(s, side, T(KE), p["E"], p["S"], p["T"], meid=s) for s in SYMS5]
    res = run(sigs, sds)
    for s in SYMS5[:4]:
        assert statuses(res, s)[0] == "FILLED"
    assert statuses(res, "EEE") == ["RISK_CAP_BLOCKED"]
    assert eq_row(res, T(KE + 1))["gross_initial_stop_risk"] == pytest.approx(100.0, abs=1e-9)


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_intrabar_exit_before_new_entries_frees_risk_budget(side):
    """§15 adım 1 (bütün sembollerde [t−5m,t) çıkışları) adım 8'den önce: AAA 10:55–11:00 barında
    stoplanır → 11:00'de EEE'nin riski sığar (24,9×3 + 24,9 = 99,6)."""
    f = NO10[side]
    k2 = K(0, 11, 0)
    stop_bar = (100.80, 100.80, 99.20, 99.40) if side == "LONG" else (109.20, 110.80, 109.20, 110.60)
    sds, sigs = [], []
    for s in SYMS5[:4]:
        bars = {k2 - 1: stop_bar} if s == "AAA" else {}
        sds.append(make_sd(s, f["O"], bars))
        sigs.append(sig(s, side, T(KE), f["E"], f["S"], f["T"], meid=s))
    sds.append(make_sd("EEE", f["O"]))
    sigs.append(sig("EEE", side, T(k2), f["E"], f["S"], f["T"], meid="EEE"))
    res = run(sigs, sds)
    assert statuses(res, "AAA") == ["FILLED", "CLOSED"]
    assert statuses(res, "EEE")[0] == "FILLED"
    tr_a = [t for t in res.trades if t["symbol"] == "AAA"][0]
    assert tr_a["exit_reason"] == "STOP" and tr_a["exit_interval_end"] == T(k2)


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_risk_budget_does_not_grow_with_realized_profit(side):
    """Kazanan işlem (+75, No.25) sonrası yeni işlemin riski yine 0,0025×C0=25: Q=25 (|E−S|=1)."""
    p = POS[side]
    k2 = K(0, 12, 0)
    bars = {KE + 1: (103.0, 104.0, 98.0, 100.0)}
    if side == "SHORT":
        bars = mirror_bars(bars)
    sa = make_sd("AAA", 100.0, bars)
    sb = make_sd("BBB", 100.0)
    ra = sig("AAA", side, T(KE), p["E"], p["S"], p["T"], meid="A")
    rb = sig("BBB", side, T(k2), p["E"], p["S"], p["T"], meid="B")
    res = run([ra, rb], [sa, sb])
    ta = [t for t in res.trades if t["market_event_id"] == "A"][0]
    assert ta["gross_PnL"] == pytest.approx(75.0, abs=1e-9)
    assert res.ledger.wallet > C0                                       # kâr gerçekleşti
    assert statuses(res, "B")[0] == "FILLED"
    tb = [t for t in res.trades if t["market_event_id"] == "B"][0]      # 12:00 → 24:00 zaman çıkışı
    assert tb["quantity_base"] == pytest.approx(25.0, abs=1e-9)
    assert tb["R0_USDT"] == pytest.approx(25.0, abs=1e-9)
    assert eq_row(res, T(k2 + 1))["gross_initial_stop_risk"] == pytest.approx(25.0, abs=1e-9)


# ═══════════════════════════════ PARTITION_TAIL_BLOCKED (§17) ═══════════════════════════════
@pytest.mark.parametrize("side", ["LONG", "SHORT"])
@pytest.mark.parametrize("hh,mm,expect", [(12, 0, "PARTITION_TAIL_BLOCKED"), (11, 55, "FILLED"),
                                          (23, 0, "PARTITION_TAIL_BLOCKED")])
def test_partition_tail_block(side, hh, mm, expect):
    window = (G0, G0 + 2 * DAY)                       # bölüm sonu = gün 2 00:00 ; yasak ≥ gün 1 12:00
    p = POS[side]
    sd = make_sd("AAA", 100.0)
    ks = K(1, hh, mm)
    r = sig("AAA", side, T(ks), p["E"], p["S"], p["T"])
    res = run([r], [sd], window=window)
    st = statuses(res, r.market_event_id)
    assert st[0] == expect
    if expect == "FILLED":
        (tr,) = res.trades                            # 11:55 giriş → 23:55 zaman çıkışı (bölüm içinde)
        assert tr["exit_reason"] == "TIME_EXIT"
        assert tr["exit_interval_start"] == T(K(1, 23, 55))
        assert res.flags["censored_open_at_end"] == 0
    else:
        assert res.trades == []


# ═══════════════════════ Giriş barında eksik veri (§12.1 adım 1) ═══════════════════════
@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_missing_entry_bar_blocks_without_queueing(side):
    p = POS[side]
    sd = make_sd("AAA", 100.0, invalid=(KE,))
    r = sig("AAA", side, T(KE), p["E"], p["S"], p["T"])
    res = run([r], [sd])
    assert statuses(res, r.market_event_id) == ["DATA_INVALID"]
    assert res.trades == []


# ═══════════════ Dolum sonrası plan geometrisi bozulursa koruma kapanışı (§12.3) ═══════════════
@pytest.mark.parametrize("side,O,E_fill,Q,gross,fee_in,fee_out", [
    # long: 101,95×1,001585=102,1116 → 102,12 ≥ T=102 ; |E−S|=3,12 ; 25/3,12=8,01 → 8,0
    ("LONG", 101.95, 102.12, 8.0, -1.36, 102.12 * 8 * 0.0006, 101.95 * 8 * 0.0006),
    # short: 98,05×0,998415=97,8946 → 97,89 ≤ T=98 ; |E−S|=3,11 ; 25/3,11=8,04 → 8,0
    ("SHORT", 98.05, 97.89, 8.0, -1.28, 97.89 * 8 * 0.0006, 98.05 * 8 * 0.0006),
])
def test_geometry_protect_close_is_recorded_not_cancelled(side, O, E_fill, Q, gross, fee_in, fee_out):
    p = POS[side]
    sd = make_sd("AAA", 100.0, {KE: (O, O, O, O)})
    r = sig("AAA", side, T(KE), p["E"], p["S"], p["T"])
    res = run([r], [sd], cst=cost(entry_fee=0.0006, exit_fee=0.0006, entry_slip=15.85))
    st = statuses(res, r.market_event_id)
    assert "FILLED" in st                                  # sinyal iptali DEĞİL
    (tr,) = res.trades
    assert tr["exit_reason"] == "GEOMETRY_PROTECT_CLOSE"
    assert tr["E_fill"] == pytest.approx(E_fill, abs=1e-9)
    assert tr["quantity_base"] == pytest.approx(Q, abs=1e-9)
    assert tr["X_reference"] == pytest.approx(O, **AP)
    assert tr["gross_PnL"] == pytest.approx(gross, abs=1e-9)
    assert tr["entry_fee"] == pytest.approx(fee_in, abs=1e-9)
    assert tr["exit_fee"] == pytest.approx(fee_out, abs=1e-9)


# ═══════════════════════ §12.1 kontrol sırası (1 → 2 → 3 → 4 → 5) ═══════════════════════
@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_order_tail_before_open_outside_plan(side):
    """Adım 1 (sınır yasak penceresi) adım 2'den önce: kuyrukta ve planı dışında açılan sinyal
    PARTITION_TAIL_BLOCKED olarak kaydedilir."""
    window = (G0, G0 + 2 * DAY)
    p = POS[side]
    ks = K(1, 13, 0)
    lb = {ks: (103.0, 103.0, 103.0, 103.0)}                  # long için O ≥ T
    sd = make_sd("AAA", 100.0, mirror_bars(lb) if side == "SHORT" else lb)
    r = sig("AAA", side, T(ks), p["E"], p["S"], p["T"])
    res = run([r], [sd], window=window)
    assert statuses(res, r.market_event_id) == ["PARTITION_TAIL_BLOCKED"]


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_order_open_outside_plan_before_position_blocked(side):
    """Adım 2 adım 3'ten önce: açık pozisyonlu sembolde, kendi planının dışında açılan ikinci
    sinyal OPEN_OUTSIDE_PLAN olur. Long ikinci plan: E=100,50 S=100 T=101,50 ; açılış 101,50 (=T).
    Short ayna: E=99,50 S=100 T=98,50 ; açılış 98,50 (=T)."""
    k2 = K(0, 11, 0)
    second = {"LONG": (100.50, 100.00, 101.50), "SHORT": (99.50, 100.00, 98.50)}[side]
    new = sig("AAA", side, T(k2), *second, meid="SECOND")
    r, res = pos_fixture(side, {k2: (101.50, 101.50, 101.50, 101.50)}, extra_signals=(new,))
    assert statuses(res, "SECOND") == ["OPEN_OUTSIDE_PLAN"]
    assert statuses(res, r.market_event_id)[0] == "FILLED"


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_order_opposite_signals_before_risk_cap(side):
    """Adım 4 adım 5'ten önce: risk sınırı doluyken (4×24,9) FFF'de aynı anda zıt iki niyet
    gelirse ikisi de OPPOSITE_SIGNALS_SAME_TIME (RISK_CAP_BLOCKED değil)."""
    f = NO10[side]
    k2 = K(0, 11, 0)
    sds = [make_sd(s, f["O"]) for s in SYMS5[:4]]
    sigs = [sig(s, side, T(KE), f["E"], f["S"], f["T"], meid=s) for s in SYMS5[:4]]
    sds.append(make_sd("FFF", 100.0))
    sigs += [sig("FFF", "LONG", T(k2), 100.0, 99.0, 102.0, meid="F_L"),
             sig("FFF", "SHORT", T(k2), 100.0, 101.0, 98.0, meid="F_S")]
    res = run(sigs, sds)
    assert statuses(res, "F_L") == ["OPPOSITE_SIGNALS_SAME_TIME"]
    assert statuses(res, "F_S") == ["OPPOSITE_SIGNALS_SAME_TIME"]


# ═══════════════ Eşit temas, açılışta tam S/T, kaymanın S/T/zaman çıkışına uygulanması ═══════════════
@pytest.mark.parametrize("side,long_bar,reason,ref", [
    ("LONG", (100.0, 100.5, 99.0, 99.5), "STOP", 99.0),          # low == S → stop teması
    ("SHORT", (100.0, 100.5, 99.0, 99.5), "STOP", 101.0),
    ("LONG", (100.0, 102.0, 99.5, 101.5), "TARGET", 102.0),      # high == T → hedef teması
    ("SHORT", (100.0, 102.0, 99.5, 101.5), "TARGET", 98.0),
])
def test_intrabar_equal_touch_triggers(side, long_bar, reason, ref):
    r, res = pos_fixture(side, {KE + 1: long_bar})
    (tr,) = res.trades
    assert tr["exit_reason"] == reason
    assert tr["X_reference"] == pytest.approx(ref, **AP)
    assert tr["exit_interval_start"] == T(KE + 1) and tr["exit_interval_end"] == T(KE + 2)


@pytest.mark.parametrize("side,long_open,reason,ref", [
    ("LONG", 99.0, "STOP", 99.0), ("SHORT", 99.0, "STOP", 101.0),       # O == S → stop-market, ref O
    ("LONG", 102.0, "TARGET", 102.0), ("SHORT", 102.0, "TARGET", 98.0),  # O == T → hedef-market, ref O
])
def test_open_exactly_at_S_or_T_closes_at_open(side, long_open, reason, ref):
    O = long_open
    r, res = pos_fixture(side, {KE + 1: (O, max(O, 100.5), min(O, 99.5), 100.0)})
    (tr,) = res.trades
    assert tr["exit_reason"] == reason
    assert tr["X_reference"] == pytest.approx(ref, **AP)
    assert tr["exit_interval_start"] == T(KE + 1) and tr["exit_interval_end"] == T(KE + 1)


@pytest.mark.parametrize("side,long_bar,reason,X_fill,gross", [
    # stop S=99: 99×(1−0,002)=98,802 → 98,80 ; (98,80−100)×25=−30
    ("LONG", (100.0, 100.5, 98.5, 99.0), "STOP", 98.80, -30.0),
    # short S=101: 101×1,002=101,202 → alış yukarı 101,21 ; −(101,21−100)×25=−30,25
    ("SHORT", (100.0, 100.5, 98.5, 99.0), "STOP", 101.21, -30.25),
    # hedef de piyasa emri (tp kayma muafiyeti yok): T=102 → 101,796 → 101,79 ; 1,79×25=44,75
    ("LONG", (100.0, 102.5, 99.5, 102.0), "TARGET", 101.79, 44.75),
    # short T=98 → 98,196 → 98,20 ; (100−98,20)×25=45
    ("SHORT", (100.0, 102.5, 99.5, 102.0), "TARGET", 98.20, 45.0),
])
def test_intrabar_exit_slippage_applied_to_S_and_T(side, long_bar, reason, X_fill, gross):
    r, res = pos_fixture(side, {KE + 1: long_bar}, cst=cost(exit_slip=20.0))
    (tr,) = res.trades
    assert tr["exit_reason"] == reason
    assert tr["X_fill"] == pytest.approx(X_fill, abs=1e-9)
    assert tr["gross_PnL"] == pytest.approx(gross, abs=1e-9)


@pytest.mark.parametrize("side,X_fill,gross", [
    ("LONG", 100.29, 7.25),      # 100,50×0,998=100,299 → 100,29 ; 0,29×25
    ("SHORT", 99.70, 7.5),       # 99,50×1,002=99,699 → 99,70 ; 0,30×25
])
def test_time_exit_with_exit_slippage(side, X_fill, gross):
    bars = {K0815: (100.0, 100.0, 100.0, 100.0), K2015: (100.50, 100.60, 100.40, 100.55)}
    if side == "SHORT":
        bars = mirror_bars(bars)
    sd = make_sd("AAA", 100.0, bars)
    p = POS[side]
    r = sig("AAA", side, T(K0815), p["E"], p["S"], p["T"])
    res = run([r], [sd], cst=cost(exit_slip=20.0))
    (tr,) = res.trades
    assert tr["exit_reason"] == "TIME_EXIT"
    assert tr["X_fill"] == pytest.approx(X_fill, abs=1e-9)
    assert tr["gross_PnL"] == pytest.approx(gross, abs=1e-9)


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_intrabar_exit_then_new_entry_same_symbol(side):
    """§15 adım 1 → 8: AAA pozisyonu 10:55–11:00 barında hedefle kapanır; 11:00 sinyali aynı
    sembolde POSITION_BLOCKED olmaz, 11:00 açılışında dolar."""
    k2 = K(0, 11, 0)
    p = POS[side]
    new = sig("AAA", side, T(k2), p["E"], p["S"], p["T"], meid="NEW")
    r, res = pos_fixture(side, {k2 - 1: (100.0, 102.5, 100.0, 100.0)}, extra_signals=(new,))
    assert statuses(res, r.market_event_id) == ["FILLED", "CLOSED"]
    assert statuses(res, "NEW")[0] == "FILLED"
    tn = trades_of(res, "NEW")
    assert len(tn) == 1 and tn[0]["fill_time"] == T(k2)


# ═══════════════════════ No.36 — aynı son mum/sinyal iki kez gelirse ═══════════════════════
K_FUND = K(0, 16, 0)
K_TGT2 = K(0, 16, 40)


@pytest.mark.parametrize("side,fund_cf,X,exit_fee,net,net_R", [
    # funding: −d×Q×mark×r = −(+1)×25×100×0,0001 = −0,25 ; çıkış 102 → ücret 102×25×0,0006=1,53
    ("LONG", -0.25, 102.0, 1.53, 50.0 - 1.5 - 1.53 - 0.25, (50.0 - 1.5 - 1.53 - 0.25) / 25.0),
    # short: +0,25 ; çıkış 98 → ücret 98×25×0,0006=1,47 ; net=47,28 ; net_R=1,8912
    ("SHORT", 0.25, 98.0, 1.47, 50.0 - 1.5 - 1.47 + 0.25, (50.0 - 1.5 - 1.47 + 0.25) / 25.0),
])
def test_no36_duplicate_signal_creates_no_second_order_fee_or_funding(side, fund_cf, X, exit_fee, net, net_R):
    bars = {KE: (100.0, 100.0, 100.0, 100.0), K_TGT2: (100.0, 102.10, 100.0, 100.0)}
    if side == "SHORT":
        bars = mirror_bars(bars)
    sd = make_sd("AAA", 100.0, bars, funding=[(T(K_FUND), 0.0001)])
    p = POS[side]
    r = sig("AAA", side, T(KE), p["E"], p["S"], p["T"], meid="EV1")
    r_dup = sig("AAA", side, T(KE), p["E"], p["S"], p["T"], meid="EV1")
    cst = cost(entry_fee=0.0006, exit_fee=0.0006)
    res = run([r, r_dup], [sd], cst=cst)
    assert len(res.trades) == 1
    (tr,) = res.trades
    assert tr["entry_fee"] == pytest.approx(1.5, abs=1e-9)             # 100×25×0,0006
    assert tr["exit_fee"] == pytest.approx(exit_fee, abs=1e-9)
    assert tr["funding_cashflow"] == pytest.approx(fund_cf, abs=1e-12)
    assert tr["net_PnL"] == pytest.approx(net, abs=1e-9)
    assert tr["net_R"] == pytest.approx(net_R, abs=1e-9)
    assert res.ledger.entry_fees == pytest.approx(1.5, abs=1e-9)
    assert res.ledger.funding == pytest.approx(fund_cf, abs=1e-12)
    assert res.ledger.wallet == pytest.approx(C0 + net, abs=1e-9)
    assert statuses(res, "EV1").count("FILLED") == 1
    # aynı girdiyle ikinci koşu: süreç/sınıf durumu sızmaz, aynı sonuç
    res2 = run([r, r_dup], [sd], cst=cst)
    assert res2.trades == res.trades and res2.ledger.wallet == res.ledger.wallet


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_no36_duplicate_signal_does_not_create_second_event_outcome(side):
    """Aynı olay ikinci kez OLUŞMAZ: yinelenen sinyal aynı market_event_id için ikinci bir
    portföy terminali (ör. sahte POSITION_BLOCKED) üretmemeli — engellenen fırsat sayısını şişirir."""
    p = POS[side]
    sd = make_sd("AAA", 100.0)
    r = sig("AAA", side, T(KE), p["E"], p["S"], p["T"], meid="EV1")
    r_dup = sig("AAA", side, T(KE), p["E"], p["S"], p["T"], meid="EV1")
    res = run([r, r_dup], [sd])
    assert "POSITION_BLOCKED" not in statuses(res, "EV1")


# ═══════════════════════ No.37 — sembol sırası ters çevrildiğinde aynı sonuç ═══════════════════════
@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_no37_reversed_symbol_order_same_decisions_and_accounting(side):
    """Beş sembol aynı 13:15 açılışında; risk sınırı yalnız dördüne izin verir. Sembol adına göre
    kararlı sıra → AAA..DDD dolar, EEE RISK_CAP_BLOCKED — girdi sırası ne olursa olsun.
    Çıkışlar sembole göre farklı (AAA hedef, BBB stop, CCC/DDD zaman çıkışı)."""
    f = NO10[side]

    def build():
        sds = {}
        for s in SYMS5:
            bars = {K_ENTRY: (f["O"], f["O"], f["O"], f["O"])}
            if s == "AAA":
                bars[K_TGT] = f["bars"][K_TGT]
            if s == "BBB":
                bars[K_TGT] = (100.80, 100.80, 99.20, 99.40) if side == "LONG" else (109.20, 110.80, 109.20, 110.60)
            sds[s] = make_sd(s, f["O"], bars)
        sigs = {s: sig(s, side, T(K_ENTRY), f["E"], f["S"], f["T"], meid=s) for s in SYMS5}
        return sds, sigs

    sds, sigs = build()
    fwd = run([sigs[s] for s in SYMS5], [sds[s] for s in SYMS5])
    sds, sigs = build()
    rev = run([sigs[s] for s in reversed(SYMS5)], [sds[s] for s in reversed(SYMS5)])
    for res in (fwd, rev):
        for s in SYMS5[:4]:
            assert statuses(res, s) == ["FILLED", "CLOSED"]
        assert statuses(res, "EEE") == ["RISK_CAP_BLOCKED"]
        by = {t["symbol"]: t for t in res.trades}
        assert set(by) == {"AAA", "BBB", "CCC", "DDD"}
        assert by["AAA"]["exit_reason"] == "TARGET"
        assert by["AAA"]["gross_PnL"] == pytest.approx(39.84, abs=1e-9)
        assert by["BBB"]["exit_reason"] == "STOP"
        assert by["BBB"]["gross_PnL"] == pytest.approx(-24.9, abs=1e-9)
        assert by["CCC"]["exit_reason"] == "TIME_EXIT" and by["DDD"]["exit_reason"] == "TIME_EXIT"
        assert by["CCC"]["gross_PnL"] == pytest.approx(0.0, abs=1e-9)
        assert res.ledger.wallet == pytest.approx(C0 + 39.84 - 24.9, abs=1e-9)
    key = lambda res: sorted((t["symbol"], t["E_fill"], t["quantity_base"], t["X_fill"], t["exit_reason"],
                              t["exit_interval_start"], t["net_PnL"]) for t in res.trades)
    assert key(fwd) == key(rev)
    assert sorted((o["market_event_id"], o["terminal_status"]) for o in fwd.outcomes) == \
        sorted((o["market_event_id"], o["terminal_status"]) for o in rev.outcomes)
    assert [r[0] for r in fwd.equity] == [r[0] for r in rev.equity]
    ef = np.array([r[2:4] + r[4:] for r in fwd.equity], dtype=float)
    er = np.array([r[2:4] + r[4:] for r in rev.equity], dtype=float)
    assert ef.shape == er.shape and np.allclose(ef, er, rtol=0, atol=1e-9)
