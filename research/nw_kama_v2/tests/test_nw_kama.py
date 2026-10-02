"""NW+KAMA V2 davranış testleri: nedensellik, giriş zamanı, stop/hedef, max tutuş."""
import numpy as np
import pytest

from research.liquidity_sweep_v1 import config as C, replay_adapter as RA
from research.liquidity_sweep_v1.tests.sentetik import sentetik_evren
from research.nw_kama_v2 import signals as SG


def test_varyant_sayisi_ve_kimlik():
    assert len(SG.VARIANT_IDS) == 24 and "2h_event_A" in SG.VARIANT_IDS and "1D_agree_B" in SG.VARIANT_IDS


@pytest.mark.parametrize("vid", ["1h_event_A", "2h_state_B", "4h_agree_A", "1h_agree_B"])
def test_gelecek_veri_gecmis_sinyalleri_degistirmez(vid):
    U1 = sentetik_evren(n_days=90, seed=5)
    U2 = sentetik_evren(n_days=90, seed=5)
    X = U1["g0"] + 60 * C.DAY + 7 * C.H1
    kx = (X - U1["g0"]) // C.M5
    for sd in U2["symbols"].values():
        for arr in (sd.o, sd.h, sd.l, sd.c):
            arr[kx:] *= 1.11
    s1 = [(r.symbol, r.signal_time, r.side, r.S, r.T) for r in SG.build(U1, vid) if r.signal_time <= X]
    s2 = [(r.symbol, r.signal_time, r.side, r.S, r.T) for r in SG.build(U2, vid) if r.signal_time <= X]
    assert s1 == s2 and len(s1) > 0


def test_sinyal_tf_kapanisinda_stop_hedef_atr():
    U = sentetik_evren(n_days=60, seed=2)
    sig = SG.build(U, "2h_state_A")
    assert sig
    for r in sig[:50]:
        assert (r.signal_time - U["g0"]) % (24 * C.M5) == 0            # 2h bar kapanışı
        a = r.ATR15_frozen
        if r.side == "LONG":
            assert r.S == pytest.approx(r.E_plan - 2 * a, abs=0.011) and r.T == pytest.approx(r.E_plan + 4 * a, abs=0.011)
            assert r.S < r.E_plan < r.T
        else:
            assert r.S == pytest.approx(r.E_plan + 2 * a, abs=0.011) and r.T == pytest.approx(r.E_plan - 4 * a, abs=0.011)
            assert r.T < r.E_plan < r.S


def test_giris_sonraki_5m_acilisi_ve_15_bar_tutus():
    U = sentetik_evren(n_days=60, seed=2)
    vid = "4h_state_A"
    sig = SG.build(U, vid)
    win = (U["g0"] + 20 * C.DAY, U["g0"] + 55 * C.DAY)
    sig = [r for r in sig if win[0] <= r.signal_time < win[1]]
    z = C.CostProfile("Z", 0, 0, 0, 0, "t")
    res = RA.simulate(vid, "T", win, sig, U, z, 10_000.0, record_equity=False, max_hold_ms=SG.max_hold_ms(vid))
    assert res.trades
    for t in res.trades:
        sd = U["symbols"][t["symbol"]]
        k = (t["fill_time"] - sd.g0) // C.M5
        assert t["fill_time"] == t["signal_time"] and t["entry_open"] == sd.o[k]   # q kapanışı = sonraki açılış
        held = t["exit_interval_end"] - t["fill_time"]
        assert held <= 15 * 48 * C.M5
        if t["exit_reason"] == "TIME_EXIT":
            assert held == 15 * 48 * C.M5


def test_donem_sonunda_acik_pozisyon_kalmaz_uzun_tutus():
    U = sentetik_evren(n_days=80, seed=4)
    vid = "4h_state_A"
    win = (U["g0"] + 20 * C.DAY, U["g0"] + 70 * C.DAY)
    sig = [r for r in SG.build(U, vid) if win[0] <= r.signal_time < win[1]]
    res = RA.simulate(vid, "T", win, sig, U, C.TWIN_MARKET_PROFILE, 10_000.0, record_equity=False,
                      max_hold_ms=SG.max_hold_ms(vid))
    assert res.flags["censored_open_at_end"] == 0
    blocked = [o for o in res.outcomes if o["reason_code"] == "PARTITION_TAIL_BLOCKED"]
    assert all(o["signal_time"] >= win[1] - SG.max_hold_ms(vid) for o in blocked)
