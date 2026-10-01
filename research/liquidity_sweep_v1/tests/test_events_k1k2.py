"""
Bağımsız davranış testleri — şartname §5 (tüketim/çatışma), §6 (ortak sweep olayı), §7 (K1),
§8 (K2) ve §21 fixture No.5, 6, 7, 8, 9, 11, 13, 14, 15 + ek zorunlu testler
("son pencere barında kabul / bir sonraki bar ret", "LEVEL_EXPIRED ile teyidin aynı anda gelmesi").

Beklenen bütün sayılar ŞARTNAMEDEN elle türetilmiş sabitlerdir (üretim fonksiyonu yeniden
çağrılarak hesaplanmaz). Fiyat adımı 0,01; contract_size=1; ücret/kayma sıfır (§21 varsayımı).

Fixture düzeni (long biçim):
  * 2 UTC günü (gün 0 + gün 1), 5m ızgara. Gün 0'ın bütün 15m barları (102, 104, 100, 102) →
    gün 1 için L1 LOW=100,00 ve L1 HIGH=104,00; known_at=gün1 00:00, expires_at=gün2 00:00.
  * Gün 1 varsayılan 15m barı (102; 102,5; 101,5; 102) → hiçbir seviyeyi ihlal etmez.
  * 15m ATR14, §21'in "warmup hazır kabul" izniyle doğrudan 2,0 sabitine ayarlanır (A=2).
  * Her 15m bar (O,H,L,C) üç 5m bara açılır: (O,O,L,L), (L,H,L,H), (H,H,C,C) → 15m toplamı
    tam olarak (O,H,L,C) olur ve ilk 5m açılışı O'dur.
Kısa yön aynası: x → P − x yansıması (varsayılan P=200; L1 LOW=100 ↔ L1 HIGH=100). OHLC
rolleri değişir: (O,H,L,C) → (P−O, P−L, P−H, P−C). Kısa yön beklenen değerleri de elle yazılmıştır.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from research.liquidity_sweep_v1 import config as C
from research.liquidity_sweep_v1 import data_contract as D
from research.liquidity_sweep_v1 import events as EV
from research.liquidity_sweep_v1 import levels as LV
from research.liquidity_sweep_v1 import replay_adapter as RA
from research.liquidity_sweep_v1 import setups as SU

SYM = "TST"
G0 = 1_704_067_200_000            # 2024-01-01 00:00 UTC
Q = 96                            # 15m bar / gün
J13 = Q + 52                      # gün 1, 13:00 15m barı
J2300, J2315, J2330, J2345 = Q + 92, Q + 93, Q + 94, Q + 95
EXPIRY = G0 + 2 * 24 * 3_600_000  # gün 1 L1 seviyesinin expires_at'i = gün 2 00:00
DAY0_LONG = (102.0, 104.0, 100.0, 102.0)
DEF_LONG = (102.0, 102.5, 101.5, 102.0)
AP = dict(abs=1e-9)


def T(j):
    """15m bar j'nin açılış zamanı (ms)."""
    return G0 + j * 15 * 60_000


def mirror(bar, P):
    O, H, L, Cc = bar
    return (round(P - O, 2), round(P - L, 2), round(P - H, 2), round(P - Cc, 2))


def bars_for(overrides, side="LONG", n_days=2, P=200.0, day0=DAY0_LONG, default=DEF_LONG):
    """overrides long biçimde yazılır; side=="SHORT" ise bütün dizi P etrafında yansıtılır."""
    bars = [day0] * Q + [default] * (Q * (n_days - 1))
    for j, b in overrides.items():
        bars[j] = b
    if side == "SHORT":
        bars = [mirror(b, P) for b in bars]
    return bars


def make_sd(bars15):
    o, h, l, c = [], [], [], []
    for (O, H, L, Cc) in bars15:
        assert L <= min(O, Cc) and max(O, Cc) <= H, (O, H, L, Cc)
        for b in ((O, O, L, L), (L, H, L, H), (H, H, Cc, Cc)):
            o.append(b[0]); h.append(b[1]); l.append(b[2]); c.append(b[3])
    n = len(c)
    return D.SymbolData(symbol=SYM, source="TEST", g0=G0, o=np.array(o, float), h=np.array(h, float),
                        l=np.array(l, float), c=np.array(c, float), v=np.ones(n), valid5=np.ones(n, bool),
                        tick=0.01, contract_size=1.0, vol_unit=0.1, min_vol=0.1, meta_source="test")


def world(bars15, family="L1", atr=2.0, atr_at=None, invalid5=()):
    sd = make_sd(bars15)
    for k in invalid5:                                  # bozuk 5m bar: NaN + geçersiz (doldurma yok)
        for a in (sd.o, sd.h, sd.l, sd.c):
            a[k] = np.nan
        sd.valid5[k] = False
    dv = LV.Derived(sd)
    dv.atr15 = np.full(len(dv.c15), float(atr))          # §21: warmup hazır kabul (A=2)
    for j, a in (atr_at or {}).items():
        dv.atr15[j] = a
    book = LV.LevelBook(family, dv)
    evs, notes = EV.detect(family, dv, book)
    return SimpleNamespace(sd=sd, dv=dv, book=book, evs=evs, notes=notes)


def level(w, side):
    lv = [x for x in w.book.levels if x.side == side]
    assert len(lv) == 1
    return lv[0]


def only_event(w, side):
    ev = [e for e in w.evs if e.side == side]
    assert len(ev) == 1, [(e.side, e.sweep_open) for e in w.evs]
    return ev[0]


def assert_signal(r, *, signal_time, extreme, E, S_raw, S, T_raw, Tt):
    assert r.terminal_status == "SIGNAL", r.terminal_status
    assert r.signal_time == signal_time
    assert r.reclaim_time == signal_time
    assert r.sweep_extreme == pytest.approx(extreme, **AP)
    assert r.E_plan == pytest.approx(E, **AP)
    assert r.S_raw == pytest.approx(S_raw, **AP)
    assert r.S == pytest.approx(S, **AP)
    assert r.T_raw == pytest.approx(T_raw, **AP)
    assert r.T == pytest.approx(Tt, **AP)


SIDES = ["LONG", "SHORT"]
LVL_SIDE = {"LONG": "LOW", "SHORT": "HIGH"}
OPP = {"LONG": "HIGH", "SHORT": "LOW"}


# ═════════════════════════ §6 ortak sweep olayı ══════════════════════════════
# No.5: L=100, A=2, önceki close=100, low[t]=99,80 (=L−0,10A), close[t]=100,60
NO5 = {J13 - 1: (102.0, 102.0, 100.0, 100.0), J13: (100.0, 100.6, 99.8, 100.6)}
NO5_EXP = {
    # S_raw = 99,80 − 0,20 = 99,60 ; T = 100,60 + 2·(100,60 − 99,60) = 102,60
    "LONG": dict(extreme=99.80, E=100.60, S_raw=99.60, S=99.60, T_raw=102.60, Tt=102.60),
    # ayna: high=100,20, close=99,40 → S=100,40 ; T = 99,40 − 2·1,00 = 97,40
    "SHORT": dict(extreme=100.20, E=99.40, S_raw=100.40, S=100.40, T_raw=97.40, Tt=97.40),
}


@pytest.mark.parametrize("side", SIDES)
def test_no5_threshold_equal_touch_is_violation_and_k1_reclaims(side):
    w = world(bars_for(NO5, side))
    assert len(w.evs) == 1
    ev = only_event(w, side)
    lv = level(w, LVL_SIDE[side])
    assert ev.level_price == pytest.approx(100.0, **AP)
    assert ev.level_id == lv.level_id
    assert ev.A == pytest.approx(2.0, **AP)
    assert ev.j15 == J13
    assert ev.sweep_open == T(J13)
    assert ev.sweep_close == T(J13 + 1)                 # olay t kapanışında bilinir
    assert ev.double_sided is False
    assert lv.consumed_at == T(J13 + 1)
    assert level(w, OPP[side]).consumed_at is None
    r = SU.eval_K1(ev, w.dv)
    assert_signal(r, signal_time=T(J13 + 1), **NO5_EXP[side])


# No.6: aynı girdi, low[t]=99,81 → 0,10 ATR derinliği yok → olay yok, seviye tüketilmez
@pytest.mark.parametrize("side", SIDES)
def test_no6_shallow_touch_no_event_and_level_not_consumed(side):
    ov = {J13 - 1: (102.0, 102.0, 100.0, 100.0), J13: (100.0, 100.6, 99.81, 100.6)}
    w = world(bars_for(ov, side))
    assert w.evs == []
    lv = level(w, LVL_SIDE[side])
    assert lv.consumed_at is None
    # seviye t+1 başında hâlâ referans (tüketilmedi)
    assert w.book.reference(LVL_SIDE[side], T(J13 + 1)) is lv


@pytest.mark.parametrize("side", SIDES)
def test_no6_shallow_touch_then_later_qualifying_bar_is_the_event(side):
    # t: sığ (99,81); t+1: close[t]=100,60 >= L ve low=99,70 <= 99,80 → olay t+1'de
    ov = {J13 - 1: (102.0, 102.0, 100.0, 100.0), J13: (100.0, 100.6, 99.81, 100.6),
          J13 + 1: (100.6, 100.6, 99.7, 100.5)}
    w = world(bars_for(ov, side))
    ev = only_event(w, side)
    assert len(w.evs) == 1
    assert ev.sweep_open == T(J13 + 1)
    assert level(w, LVL_SIDE[side]).consumed_at == T(J13 + 2)


@pytest.mark.parametrize("side", SIDES)
def test_violation_requires_prior_close_on_level_side(side):
    # t−1: close=99,99 < L (low 99,85 sığ). t: low=99,00 ama close[t−1] < L → olay yok.
    # t+1: close[t]=99,50 < L → olay yok. t+2: close[t+1]=100,30 >= L, low 99,70 → olay t+2.
    ov = {J13 - 1: (100.2, 100.2, 99.85, 99.99), J13: (99.99, 99.99, 99.0, 99.5),
          J13 + 1: (99.5, 100.5, 99.4, 100.3), J13 + 2: (100.3, 100.4, 99.7, 100.2)}
    w = world(bars_for(ov, side))
    ev = only_event(w, side)
    assert len(w.evs) == 1
    assert ev.sweep_open == T(J13 + 2)
    assert level(w, LVL_SIDE[side]).consumed_at == T(J13 + 3)


@pytest.mark.parametrize("side", SIDES)
def test_A_is_atr_of_last_15m_bar_completed_before_t(side):
    # ATR[t]=40 (t içindeki bilgi) kullanılmamalı; A = ATR[t−1] = 2 → olay var
    w = world(bars_for(NO5, side), atr_at={J13: 40.0})
    ev = only_event(w, side)
    assert ev.A == pytest.approx(2.0, **AP)
    # tersi: ATR[t−1]=40 → eşik L∓4 → 99,80/100,20 yetmez → olay yok
    w2 = world(bars_for(NO5, side), atr_at={J13 - 1: 40.0, J13: 2.0})
    assert w2.evs == []
    assert level(w2, LVL_SIDE[side]).consumed_at is None


# ═════════════════════════ §5 tüketim ve çatışma ═════════════════════════════
@pytest.mark.parametrize("side", SIDES)
def test_level_consumed_at_first_qualifying_violation_even_without_trade(side):
    # t: ihlal, close=99,90 (K1 yok). t+1 reclaim; t+3 yeni "ihlal" (close[t+2]=100,50, low=99,00)
    # → seviye t kapanışında tüketildi; ikinci olay YOK, daha eski seviyeye de dönülmez.
    ov = {J13: (100.0, 100.2, 99.6, 99.9), J13 + 1: (99.9, 100.8, 99.9, 100.6),
          J13 + 2: (100.6, 100.8, 100.3, 100.5), J13 + 3: (100.5, 100.9, 99.0, 100.7)}
    w = world(bars_for(ov, side))
    assert len(w.evs) == 1
    ev = only_event(w, side)
    assert ev.sweep_open == T(J13)
    lv = level(w, LVL_SIDE[side])
    assert lv.consumed_at == T(J13 + 1)
    assert w.book.reference(LVL_SIDE[side], T(J13 + 3)) is None
    r1 = SU.eval_K1(ev, w.dv)
    assert r1.terminal_status == "K1_RECLAIM_MISSING"
    assert r1.signal_time is None and r1.S is None
    # makine düzeyinde de: K1 varyantı bu seviyeden hiç sinyal üretmez
    recs = SU.run_machine("L1", "K1", {SYM: w.evs}, {SYM: w.dv}, G0, EXPIRY)
    assert [r.terminal_status for r in recs] == ["K1_RECLAIM_MISSING"]


@pytest.mark.parametrize("side", SIDES)
def test_no8_double_sided_sweep_consumes_both_and_no_order(side):
    # aynı 15m bar: low=99,80 (<= 100−0,2) ve high=104,20 (>= 104+0,2). close[t−1]=102 ∈ [100,104].
    # t+2 yeniden LOW ihlali gibi görünür → seviye tüketildiği için olay yok.
    ov = {J13: (102.0, 104.2, 99.8, 101.0), J13 + 2: (102.0, 102.0, 99.0, 101.0)}
    w = world(bars_for(ov, side, P=204.0))           # P=204: [100,104] kendi üstüne yansır
    assert len(w.evs) == 2
    assert {e.side for e in w.evs} == {"LONG", "SHORT"}
    lo, hi = level(w, "LOW"), level(w, "HIGH")
    assert lo.price == pytest.approx(100.0, **AP) and hi.price == pytest.approx(104.0, **AP)
    for e in w.evs:
        assert e.double_sided is True
        assert e.sweep_open == T(J13) and e.sweep_close == T(J13 + 1)
    assert lo.consumed_at == T(J13 + 1)
    assert hi.consumed_at == T(J13 + 1)
    for e in w.evs:
        for fn in (SU.eval_K1, SU.eval_K2, SU.eval_K3, SU.eval_K4):
            r = fn(e, w.dv)
            assert r.terminal_status == "DOUBLE_SIDED_SWEEP", (fn.__name__, e.side, r.terminal_status)
            assert r.S is None and r.E_plan is None
    for K in ("K1", "K2", "K3", "K4"):
        recs = SU.run_machine("L1", K, {SYM: w.evs}, {SYM: w.dv}, G0, EXPIRY)
        assert all(r.terminal_status != "SIGNAL" for r in recs), K


# ═════════════════════════ §7 K1 ═════════════════════════════════════════════
# No.9: 13:00–13:15 K1 long L=100, A=2, low=99,50, close=100,60 → S=99,30, T=103,20
#       giriş ancak 13:15 açılışında (No.10 açılışı 100,80 kullanılır).
NO9 = {J13: (102.0, 102.0, 99.5, 100.6), J13 + 1: (100.8, 101.2, 100.6, 101.0)}
NO9_EXP = {
    "LONG": dict(extreme=99.50, E=100.60, S_raw=99.30, S=99.30, T_raw=103.20, Tt=103.20),
    # ayna (P=200): high=100,50, close=99,40 → S=100,70 ; T=99,40−2·1,30=96,80
    "SHORT": dict(extreme=100.50, E=99.40, S_raw=100.70, S=100.70, T_raw=96.80, Tt=96.80),
}
NO9_OPEN = {"LONG": 100.80, "SHORT": 99.20}


@pytest.mark.parametrize("side", SIDES)
def test_no9_k1_stop_target_signal_at_1315(side):
    w = world(bars_for(NO9, side))
    ev = only_event(w, side)
    assert ev.sweep_open == G0 + 24 * 3_600_000 + 13 * 3_600_000          # 13:00
    t1315 = G0 + 24 * 3_600_000 + 13 * 3_600_000 + 15 * 60_000
    assert ev.sweep_close == t1315
    r = SU.eval_K1(ev, w.dv)
    assert_signal(r, signal_time=t1315, **NO9_EXP[side])


@pytest.mark.parametrize("side", SIDES)
def test_no9_entry_only_at_1315_open(side):
    w = world(bars_for(NO9, side, n_days=3))
    ev = [e for e in w.evs if e.sweep_open == T(J13)]
    assert len(ev) == 1 and ev[0].side == side
    r = SU.eval_K1(ev[0], w.dv)
    assert r.terminal_status == "SIGNAL"
    t1315 = G0 + 24 * 3_600_000 + 13 * 3_600_000 + 15 * 60_000
    zero = C.CostProfile(name="ZERO", entry_fee_rate=0.0, exit_fee_rate=0.0, entry_slip_bp=0.0,
                         exit_slip_bp=0.0, source="test")
    U = {"symbols": {SYM: w.sd}, "g0": G0}
    res = RA.simulate("L1_K1_F0", "TEST", (G0 + 24 * 3_600_000, G0 + 3 * 24 * 3_600_000), [r], U, zero,
                      10_000.0, record_equity=False)
    assert len(res.trades) == 1
    tr = res.trades[0]
    assert tr["fill_time"] == t1315                  # 13:15 açılışı; 13:20 kapanışı değil
    assert tr["entry_open"] == pytest.approx(NO9_OPEN[side], **AP)   # 13:00–13:15 kapanışı (100,60) değil
    assert tr["E_fill"] == pytest.approx(NO9_OPEN[side], **AP)
    assert tr["S"] == pytest.approx(NO9_EXP[side]["S"], **AP)
    assert tr["T"] == pytest.approx(NO9_EXP[side]["Tt"], **AP)


# No.11: K1 short L=110, A=2, high=110,50, close=109,40 → S=110,70, T=106,80
NO11_DAY0 = (108.0, 110.0, 106.0, 108.0)
NO11_DEF = (108.0, 108.5, 107.5, 108.0)
NO11 = {J13: (108.0, 110.5, 108.0, 109.4)}
NO11_EXP = {
    "SHORT": dict(extreme=110.50, E=109.40, S_raw=110.70, S=110.70, T_raw=106.80, Tt=106.80),
    # ayna (P=220): low=109,50, close=110,60 → S=109,30 ; T=110,60+2·1,30=113,20
    "LONG": dict(extreme=109.50, E=110.60, S_raw=109.30, S=109.30, T_raw=113.20, Tt=113.20),
}


@pytest.mark.parametrize("side", SIDES)
def test_no11_k1_short_stop_target(side):
    bars = [NO11_DAY0] * Q + [NO11_DEF] * Q
    for j, b in NO11.items():
        bars[j] = b
    if side == "LONG":
        bars = [mirror(b, 220.0) for b in bars]
    w = world(bars)
    ev = only_event(w, side)
    assert len(w.evs) == 1
    assert ev.level_price == pytest.approx(110.0, **AP)
    assert ev.A == pytest.approx(2.0, **AP)
    r = SU.eval_K1(ev, w.dv)
    assert_signal(r, signal_time=T(J13 + 1), **NO11_EXP[side])


# No.7: L=100, ihlal var, close[t]=100 → K1 yok (eşit kapanış reclaim değil); K2 bekleyebilir
NO7 = {J13: (100.0, 100.1, 99.5, 100.0), J13 + 1: (100.0, 100.7, 99.9, 100.5)}
NO7_K2_EXP = {
    # q=t+1: extreme=min(99,50; 99,90)=99,50 → S=99,30 ; E=100,50 ; T=100,50+2·1,20=102,90
    "LONG": dict(extreme=99.50, E=100.50, S_raw=99.30, S=99.30, T_raw=102.90, Tt=102.90),
    # ayna: extreme=max(100,50; 100,10)=100,50 → S=100,70 ; E=99,50 ; T=99,50−2·1,20=97,10
    "SHORT": dict(extreme=100.50, E=99.50, S_raw=100.70, S=100.70, T_raw=97.10, Tt=97.10),
}


@pytest.mark.parametrize("side", SIDES)
def test_no7_close_equal_L_is_not_k1_reclaim_and_next_bar_not_k1(side):
    w = world(bars_for(NO7, side))
    ev = only_event(w, side)
    r = SU.eval_K1(ev, w.dv)
    assert r.terminal_status == "K1_RECLAIM_MISSING"
    assert r.reclaim_time is None and r.signal_time is None and r.S is None and r.E_plan is None
    assert r.terminal_time == T(J13 + 1)


@pytest.mark.parametrize("side", SIDES)
def test_no7_k2_can_wait_after_close_equal_L(side):
    w = world(bars_for(NO7, side))
    ev = only_event(w, side)
    r = SU.eval_K2(ev, w.dv)
    assert_signal(r, signal_time=T(J13 + 2), **NO7_K2_EXP[side])


@pytest.mark.parametrize("side", SIDES)
def test_k1_level_expired_when_reclaim_close_equals_expiry(side):
    # t=23:45–24:00: seviye t başında aktif (23:45 < expires), ihlal → olay + tüketim;
    # K1 teyidi 00:00 = expires_at anında → kabul edilmez (LEVEL_EXPIRED).
    ov = {J2345: (102.0, 102.0, 99.5, 100.6)}
    w = world(bars_for(ov, side))
    ev = only_event(w, side)
    assert ev.sweep_close == EXPIRY
    assert level(w, LVL_SIDE[side]).consumed_at == EXPIRY
    r = SU.eval_K1(ev, w.dv)
    assert r.terminal_status == "LEVEL_EXPIRED"
    assert r.signal_time is None
    # kontrol: bir bar önce (23:30–23:45) aynı mum → SIGNAL (S/T No.9 ile aynı)
    w2 = world(bars_for({J2330: (102.0, 102.0, 99.5, 100.6)}, side))
    r2 = SU.eval_K1(only_event(w2, side), w2.dv)
    assert_signal(r2, signal_time=T(J2345), **NO9_EXP[side])


# ═════════════════════════ §8 K2 ═════════════════════════════════════════════
# No.13: t close=99,80, t+1=99,90, t+2=100,20; min low[t..t+2]=99,10; L=100, A=2
#        → q=t+2; S=98,90; T=102,80. t+3'te daha düşük dip (98,00) extreme'e girmemeli.
NO13 = {J13: (100.0, 100.1, 99.5, 99.8), J13 + 1: (99.8, 100.0, 99.1, 99.9),
        J13 + 2: (99.9, 100.3, 99.6, 100.2), J13 + 3: (100.2, 100.4, 98.0, 100.3)}
NO13_EXP = {
    "LONG": dict(extreme=99.10, E=100.20, S_raw=98.90, S=98.90, T_raw=102.80, Tt=102.80),
    # ayna: max high=100,90 → S=101,10 ; E=99,80 ; T=99,80−2·1,30=97,20
    "SHORT": dict(extreme=100.90, E=99.80, S_raw=101.10, S=101.10, T_raw=97.20, Tt=97.20),
}


@pytest.mark.parametrize("side", SIDES)
def test_no13_k2_delayed_reclaim(side):
    # t..t+3 içindeki ATR değişimi tamponu etkilememeli: A, t'den önce dondurulan 2,0
    w = world(bars_for(NO13, side), atr_at={J13: 7.0, J13 + 1: 7.0, J13 + 2: 7.0, J13 + 3: 7.0})
    ev = only_event(w, side)
    assert ev.A == pytest.approx(2.0, **AP)
    r = SU.eval_K2(ev, w.dv)
    assert_signal(r, signal_time=T(J13 + 3), **NO13_EXP[side])
    assert r.ATR15_frozen == pytest.approx(2.0, **AP)
    assert SU.eval_K1(ev, w.dv).terminal_status == "K1_RECLAIM_MISSING"


# No.14: ilk reclaim t+3 kapanışında → kabul (t+2 kapanışı L'ye EŞİT → reclaim değil)
NO14 = {J13: (100.0, 100.1, 99.6, 99.8), J13 + 1: (99.8, 100.0, 99.4, 99.9),
        J13 + 2: (99.9, 100.2, 99.7, 100.0), J13 + 3: (100.0, 100.5, 99.2, 100.3)}
NO14_EXP = {
    # extreme=min(99,6; 99,4; 99,7; 99,2)=99,20 → S=99,00 ; E=100,30 ; T=100,30+2·1,30=102,90
    "LONG": dict(extreme=99.20, E=100.30, S_raw=99.00, S=99.00, T_raw=102.90, Tt=102.90),
    # ayna: extreme=100,80 → S=101,00 ; E=99,70 ; T=99,70−2·1,30=97,10
    "SHORT": dict(extreme=100.80, E=99.70, S_raw=101.00, S=101.00, T_raw=97.10, Tt=97.10),
}


@pytest.mark.parametrize("side", SIDES)
def test_no14_k2_reclaim_on_t_plus_3_accepted(side):
    w = world(bars_for(NO14, side))
    ev = only_event(w, side)
    r = SU.eval_K2(ev, w.dv)
    assert_signal(r, signal_time=T(J13 + 4), **NO14_EXP[side])


# No.15: ilk reclaim t+4 kapanışında → ret, K2_TIMEOUT (t+3 kapanışı L'ye eşit)
NO15 = {J13: (100.0, 100.1, 99.6, 99.8), J13 + 1: (99.8, 100.0, 99.4, 99.9),
        J13 + 2: (99.9, 100.2, 99.7, 100.0), J13 + 3: (100.0, 100.2, 99.2, 100.0),
        J13 + 4: (100.0, 100.8, 99.9, 100.5)}


@pytest.mark.parametrize("side", SIDES)
def test_no15_k2_reclaim_on_t_plus_4_rejected_timeout(side):
    w = world(bars_for(NO15, side))
    ev = only_event(w, side)
    r = SU.eval_K2(ev, w.dv)
    assert r.terminal_status == "K2_TIMEOUT"
    assert r.terminal_time == T(J13 + 4)              # "üç bar dolunca" = t+3 kapanışı
    assert r.signal_time is None and r.S is None and r.E_plan is None and r.reclaim_time is None
    recs = SU.run_machine("L1", "K2", {SYM: w.evs}, {SYM: w.dv}, G0, EXPIRY)
    assert [x.terminal_status for x in recs] == ["K2_TIMEOUT"]


@pytest.mark.parametrize("side", SIDES)
def test_k2_not_applicable_when_violation_bar_already_reclaimed(side):
    # t kapanışı 100,60 > L (K1 reclaim). t+1/t+2 daha yüksek kapansa da K2 bu olaya girmez.
    ov = {J13: (102.0, 102.0, 99.5, 100.6), J13 + 1: (100.6, 101.5, 100.5, 101.4)}
    w = world(bars_for(ov, side))
    ev = only_event(w, side)
    r = SU.eval_K2(ev, w.dv)
    assert r.terminal_status == "K2_NOT_APPLICABLE"
    assert r.signal_time is None and r.S is None
    recs = SU.run_machine("L1", "K2", {SYM: w.evs}, {SYM: w.dv}, G0, EXPIRY)
    assert [x.terminal_status for x in recs] == ["K2_NOT_APPLICABLE"]


@pytest.mark.parametrize("side", SIDES)
def test_k2_level_expired_when_confirmation_exactly_at_expiry(side):
    # t=23:15; t+1=23:30 (reclaim yok); t+2=23:45–24:00 reclaim kapanışı 00:00 = expires_at
    ov = {J2315: (100.0, 100.1, 99.5, 99.8), J2330: (99.8, 100.0, 99.6, 99.9),
          J2345: (99.9, 100.6, 99.8, 100.5)}
    w = world(bars_for(ov, side))
    ev = only_event(w, side)
    assert ev.level_expires_at == EXPIRY
    r = SU.eval_K2(ev, w.dv)
    assert r.terminal_status == "LEVEL_EXPIRED"
    assert r.terminal_time == EXPIRY
    assert r.signal_time is None and r.S is None


K2_PRE_EXPIRY_EXP = {
    # q=t+1 (23:45 kapanış): extreme=min(99,5; 99,6)=99,50 → S=99,30 ; E=100,50 ; T=102,90
    "LONG": dict(extreme=99.50, E=100.50, S_raw=99.30, S=99.30, T_raw=102.90, Tt=102.90),
    "SHORT": dict(extreme=100.50, E=99.50, S_raw=100.70, S=100.70, T_raw=97.10, Tt=97.10),
}


@pytest.mark.parametrize("side", SIDES)
def test_k2_confirmation_one_bar_before_expiry_accepted(side):
    ov = {J2315: (100.0, 100.1, 99.5, 99.8), J2330: (99.8, 100.6, 99.6, 100.5)}
    w = world(bars_for(ov, side))
    ev = only_event(w, side)
    r = SU.eval_K2(ev, w.dv)
    assert_signal(r, signal_time=T(J2345), **K2_PRE_EXPIRY_EXP[side])


# ═════════════════════ §5 BLOCKED_ACTIVE_SETUP (run_machine) ══════════════════
@pytest.mark.parametrize("side", SIDES)
def test_blocked_active_setup_while_k2_waits(side):
    """Ev1 = gerçek No.13 olayı (K2 t+2 kapanışına kadar bekler). Ev2 = aynı yönde t+1'de gelen
    yeni uygun olay (§21 izniyle doğrudan kurulmuş; L1 ailesinde aynı yön için ikinci seviye
    45 dakikada oluşamaz) → BLOCKED_ACTIVE_SETUP; Ev1 değişmez. Ev3 = K2 kurulumu bittikten sonra
    gelen yeni olay → normal değerlendirilir (bu kez veriyle tutarlı: L3=101,60 / ayna 98,40)."""
    ov = dict(NO13)
    ov[J13 + 5] = (102.0, 102.0, 101.3, 101.5)        # L=101,60 için ihlal: low 101,30 <= 101,40
    w = world(bars_for(ov, side))
    ev1 = only_event(w, side)
    lvl2 = 99.9 if side == "LONG" else 100.1
    ev2 = EV.MarketEvent(market_event_id=f"L1|{SYM}|{side}|SYNTH2", family="L1", symbol=SYM, side=side,
                         level_id="SYNTH-2", level_price=lvl2, level_known_at=T(J13 + 1),
                         level_expires_at=EXPIRY, j15=J13 + 1, sweep_open=T(J13 + 1),
                         sweep_close=T(J13 + 2), A=2.0, micro_ref=None)
    lvl3 = 101.6 if side == "LONG" else 98.4
    ev3 = EV.MarketEvent(market_event_id=f"L1|{SYM}|{side}|SYNTH3", family="L1", symbol=SYM, side=side,
                         level_id="SYNTH-3", level_price=lvl3, level_known_at=T(J13 + 4),
                         level_expires_at=EXPIRY, j15=J13 + 5, sweep_open=T(J13 + 5),
                         sweep_close=T(J13 + 6), A=2.0, micro_ref=None)
    recs = SU.run_machine("L1", "K2", {SYM: [ev1, ev2, ev3]}, {SYM: w.dv}, G0, EXPIRY)
    by = {r.market_event_id: r for r in recs}
    assert len(recs) == 3
    b = by[ev2.market_event_id]
    assert b.terminal_status == "BLOCKED_ACTIVE_SETUP"
    assert b.signal_time is None and b.S is None
    assert_signal(by[ev1.market_event_id], signal_time=T(J13 + 3), **NO13_EXP[side])
    exp3 = {
        # q=t+1 (varsayılan bar close 102 > 101,60): extreme=101,30 → S=101,10; E=102; T=103,80
        "LONG": dict(extreme=101.30, E=102.00, S_raw=101.10, S=101.10, T_raw=103.80, Tt=103.80),
        # ayna: extreme=98,70 → S=98,90; E=98; T=98−2·0,90=96,20
        "SHORT": dict(extreme=98.70, E=98.00, S_raw=98.90, S=98.90, T_raw=96.20, Tt=96.20),
    }[side]
    assert_signal(by[ev3.market_event_id], signal_time=T(J13 + 7), **exp3)


@pytest.mark.parametrize("side", SIDES)
def test_opposite_side_event_not_blocked_by_waiting_k2(side):
    # t: long ihlal, close 99,80 (K2 bekler). t+1: high=104,20 → HIGH(104) ihlali (karşı yön);
    # long close 99,90 reclaim değil. t+2: long reclaim 100,40.
    ov = {J13: (100.0, 100.1, 99.5, 99.8), J13 + 1: (99.8, 104.2, 99.6, 99.9),
          J13 + 2: (99.9, 100.6, 99.7, 100.4)}
    w = world(bars_for(ov, side, P=204.0))
    opp = "SHORT" if side == "LONG" else "LONG"
    e_main, e_opp = only_event(w, side), only_event(w, opp)
    assert e_main.sweep_open == T(J13) and e_opp.sweep_open == T(J13 + 1)
    assert not e_main.double_sided and not e_opp.double_sided
    recs = SU.run_machine("L1", "K2", {SYM: w.evs}, {SYM: w.dv}, G0, EXPIRY)
    by = {r.market_event_id: r for r in recs}
    r_opp = by[e_opp.market_event_id]
    assert r_opp.terminal_status != "BLOCKED_ACTIVE_SETUP"
    # karşı yön olay barı zaten kendi seviyesinin içinde kapandı (99,90 < 104) → K2 girmez
    assert r_opp.terminal_status == "K2_NOT_APPLICABLE"
    exp = {
        # extreme=min(99,5; 99,6; 99,7)=99,50 → S=99,30 ; E=100,40 ; T=100,40+2·1,10=102,60
        "LONG": dict(extreme=99.50, E=100.40, S_raw=99.30, S=99.30, T_raw=102.60, Tt=102.60),
        # ayna P=204: extreme=104,50 → S=104,70 ; E=103,60 ; T=103,60−2·1,10=101,40
        "SHORT": dict(extreme=104.50, E=103.60, S_raw=104.70, S=104.70, T_raw=101.40, Tt=101.40),
    }[side]
    assert_signal(by[e_main.market_event_id], signal_time=T(J13 + 3), **exp)


@pytest.mark.parametrize("side", SIDES)
def test_k2_last_window_bar_at_expiry_is_level_expired_not_signal(side):
    # No.14 dizisi 23:00'e kaydırıldı: t+3 (23:45–24:00) reclaim kapanışı = expires_at.
    # "Seviye sona erdiği anda iptal" kuralı "son pencere barı geçerli" kuralından önce gelir.
    ov = {J2300: NO14[J13], J2315: NO14[J13 + 1], J2330: NO14[J13 + 2], J2345: NO14[J13 + 3]}
    w = world(bars_for(ov, side))
    ev = only_event(w, side)
    assert ev.sweep_open == T(J2300)
    r = SU.eval_K2(ev, w.dv)
    assert r.terminal_status == "LEVEL_EXPIRED"
    assert r.terminal_time == EXPIRY
    assert r.signal_time is None and r.S is None


@pytest.mark.parametrize("side", SIDES)
def test_k2_data_invalid_in_wait_window(side):
    # t+1 15m barının ortadaki 5m alt barı bozuk → t+1 15m DATA_INVALID; K2 DATA_INVALID ile biter
    # (t+2'deki reclaim kurtarmaz; eksik bar doldurulmaz).
    ov = {J13: (100.0, 100.1, 99.5, 99.8), J13 + 2: (99.9, 100.6, 99.7, 100.5)}
    w = world(bars_for(ov, side), invalid5=(3 * (J13 + 1) + 1,))
    assert not np.isfinite(w.dv.c15[J13 + 1])
    ev = only_event(w, side)
    r = SU.eval_K2(ev, w.dv)
    assert r.terminal_status == "DATA_INVALID"
    assert r.signal_time is None and r.S is None


@pytest.mark.parametrize("side", SIDES)
def test_single_side_violation_when_other_side_prior_close_fails_is_not_double(side):
    # t−1 close=99,90 (< LOW 100, sığ low 99,85 → ihlal değil). t: low 99,50 ve high 104,20.
    # Long için close[t−1] >= L sağlanmaz → yalnız HIGH(104) ihlali; DOUBLE_SIDED değil,
    # LOW tüketilmez. (P=204 aynası: yalnız LOW(100) ihlali.)
    ov = {J13 - 1: (100.2, 100.2, 99.85, 99.9), J13: (99.9, 104.2, 99.5, 103.0)}
    w = world(bars_for(ov, side, P=204.0))
    assert len(w.evs) == 1
    swept = "SHORT" if side == "LONG" else "LONG"
    ev = only_event(w, swept)
    assert ev.double_sided is False
    untouched = "LOW" if side == "LONG" else "HIGH"
    assert level(w, untouched).consumed_at is None
    swept_lvl = "HIGH" if untouched == "LOW" else "LOW"
    assert level(w, swept_lvl).consumed_at == T(J13 + 1)


@pytest.mark.parametrize("side", SIDES)
def test_invalid_atr_skips_event(side):
    # §4: A sıfır/NaN ise olay atlanır ve INVALID_INDICATOR yazılır
    for bad in (0.0, float("nan")):
        w = world(bars_for(NO5, side), atr_at={J13 - 1: bad})
        assert w.evs == []
        assert w.notes["INVALID_INDICATOR"] >= 1
