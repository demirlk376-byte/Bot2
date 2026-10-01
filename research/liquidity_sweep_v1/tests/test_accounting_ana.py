"""Muhasebe ve funding (şartname §13, §15, §16; §21 No.26, 29–33, 38). Beklenen sayılar şartnameden."""
import numpy as np
import pytest

from research.liquidity_sweep_v1 import accounting as A, config as C, data_contract as D, replay_adapter as RA
from research.liquidity_sweep_v1.setups import SetupRecord

G0 = 1_672_531_200_000           # 2023-01-01 00:00 UTC


def test_bp_birimi():
    assert 15.85 / 10_000 == pytest.approx(0.001585)


def test_no26_bosluklu_stop_dolumu_yuvarlama_oncesi():
    # Long S=99; açılış 98.50; çıkış kayması 20bp → yuvarlama öncesi 98.303; 99'dan dolum yok
    raw = 98.50 * (1 - 20 / 10_000)
    assert raw == pytest.approx(98.303)
    assert A.exit_fill(98.50, +1, 20, 0.001) == pytest.approx(98.303)     # tick 0.001: tam
    assert A.exit_fill(98.50, +1, 20, 0.01) == pytest.approx(98.30)       # satış AŞAĞI yuvarlanır
    assert A.exit_fill(101.50, -1, 20, 0.01) == pytest.approx(101.71)     # short kapanış = alış YUKARI (101.703→101.71)


def test_giris_dolumu_aleyhe_yuvarlama():
    assert A.entry_fill(100.0, +1, 15.85, 0.01) == pytest.approx(100.16)   # 100.1585 → yukarı
    assert A.entry_fill(100.0, -1, 15.85, 0.01) == pytest.approx(99.84)    # 99.8415 → aşağı


def test_no29_no30_sozlesme_baz_ve_net():
    q_contracts, cs = 3, 0.1
    q_base = q_contracts * cs
    assert q_base == pytest.approx(0.3)
    gross = (102 - 100) * q_base
    assert gross == pytest.approx(0.6)
    R0 = abs(100 - 99) * q_base
    assert R0 == pytest.approx(0.3)
    fee_in, fee_out = 100 * q_base * 0.001, 102 * q_base * 0.001
    assert (fee_in, fee_out) == (pytest.approx(0.03), pytest.approx(0.0306))
    f = A.funding_cashflow(+1, q_base, 101, 0.0001)
    assert f == pytest.approx(-0.00303)
    net = gross - fee_in - fee_out + f
    assert net == pytest.approx(0.53637)
    assert net / R0 == pytest.approx(1.7879, abs=1e-4)


def test_funding_isareti():
    assert A.funding_cashflow(+1, 2.0, 50.0, 0.001) == pytest.approx(-0.1)   # pozitif oranda long öder
    assert A.funding_cashflow(-1, 2.0, 50.0, 0.001) == pytest.approx(+0.1)   # short alır
    assert A.funding_cashflow(+1, 2.0, 50.0, -0.001) == pytest.approx(+0.1)


def test_no38_paper_ekonomik_ozsermaye():
    assert A.economic_equity_from_paper(900, 100, 20, 1) == pytest.approx(1019)


def test_ledger_kimligi_ve_marjin_zarar_degil():
    L = A.Ledger(1000.0)
    L.open(100.0, 1.0)
    assert L.wallet == pytest.approx(999.0) and L.free_collateral == pytest.approx(899.0)
    L.fund(-0.5)
    L.close(10.0, 1.1, 100.0)
    assert L.wallet == pytest.approx(1000 - 1 - 0.5 + 10 - 1.1)
    assert L.reserved_margin == pytest.approx(0.0)
    assert abs(L.identity_gap()) < 1e-12


# ───────────────────────── motor üzerinden funding zamanlaması ──────────────────────────────
def _sd(n_days=2, price=100.0, funding=()):
    n5 = n_days * C.GRID_PER_DAY
    o = np.full(n5, price)
    h = o + 0.05
    l = o - 0.05
    c = o.copy()
    ft = np.array([t for t, _ in funding], dtype="int64")
    fr = np.array([r for _, r in funding], dtype=float)
    return D.SymbolData(symbol="AAA", source="T", g0=G0, o=o, h=h, l=l, c=c, v=np.ones(n5), valid5=np.ones(n5, bool),
                        tick=0.01, contract_size=1.0, vol_unit=1.0, min_vol=1.0, meta_source="t", funding_t=ft,
                        funding_rate=fr, funding_on_grid=np.ones(len(ft), bool), funding_source="T")


def _sig(t, side="LONG", E=100.0, S=99.0, T=102.0):
    return SetupRecord(variant_base="L1_K1", market_event_id=f"E{t}", symbol="AAA", side=side, level_id="x",
                       level_known_at=0, level_expires_at=10**15, sweep_open=t - C.M15, sweep_close=t,
                       ATR15_frozen=1.0, terminal_status="SIGNAL", terminal_time=t, signal_time=t, E_plan=E,
                       S_raw=S, S=S, T_raw=T, T=T)


ZERO = C.CostProfile("Z", 0.0, 0.0, 0.0, 0.0, "t")


def _run(sd, sigs, end_h=40):
    U = dict(symbols={"AAA": sd}, g0=G0)
    return RA.simulate("L1_K1_F0", "T", (G0 + C.DAY // 2, G0 + end_h * C.H1), sigs, U, ZERO, 10_000.0)


def test_no31_tam_settlement_aninda_acilan_pozisyon_odemez():
    t8 = G0 + 20 * C.H1                              # ertesi güne değil, aynı gün 20:00 settlement
    res = _run(_sd(funding=[(t8, 0.001)]), [_sig(t8)])
    tr = res.trades[0]
    assert tr["funding_cashflow"] == 0.0 and tr["funding_events"] == 0


def test_no32_zaman_cikisi_aninda_funding_once_islenir():
    t_in = G0 + 14 * C.H1
    t_out = t_in + 12 * C.H1                         # 02:00 ertesi gün: hem settlement hem zaman çıkışı
    res = _run(_sd(funding=[(t_out, 0.001)]), [_sig(t_in)])
    tr = res.trades[0]
    assert tr["exit_reason"] == "TIME_EXIT" and tr["exit_interval_start"] == t_out
    q = tr["quantity_base"]
    assert tr["funding_cashflow"] == pytest.approx(-q * 100.0 * 0.001)
    assert tr["funding_events"] == 1
    assert len(res.trades) == 1                      # tek kapanış


def test_no33_onceki_barda_stoplanan_pozisyon_funding_e_girmez():
    t_in = G0 + 14 * C.H1
    t8 = G0 + 16 * C.H1
    sd = _sd(funding=[(t8, 0.001)])
    kb = (t8 - G0) // C.M5 - 1                        # 15:55–16:00 barı stopa değiyor
    sd.l[kb] = 98.0
    res = _run(sd, [_sig(t_in)])
    tr = res.trades[0]
    assert tr["exit_reason"] == "STOP" and tr["exit_interval_end"] == t8
    assert tr["funding_cashflow"] == 0.0


def test_funding_net_pnl_ve_cuzdanda_bir_kez():
    t_in = G0 + 14 * C.H1
    fs = [(G0 + 16 * C.H1, 0.001), (G0 + 24 * C.H1, -0.0005)]
    res = _run(_sd(funding=fs), [_sig(t_in)])
    tr = res.trades[0]
    q = tr["quantity_base"]
    exp = -q * 100 * 0.001 + q * 100 * 0.0005
    assert tr["funding_cashflow"] == pytest.approx(exp)
    assert res.ledger.funding == pytest.approx(exp)
    assert res.ledger.wallet - 10_000.0 == pytest.approx(tr["net_PnL"])
    assert tr["net_PnL"] == pytest.approx(tr["gross_PnL"] - tr["entry_fee"] - tr["exit_fee"] + exp)


def test_giris_ucreti_dolumda_dusulur_ozsermayede_gorunur_ve_iki_kez_dusulmez():
    t_in = G0 + 14 * C.H1
    cost = C.CostProfile("F", 0.001, 0.001, 0.0, 0.0, "t")
    U = dict(symbols={"AAA": _sd()}, g0=G0)
    res = RA.simulate("L1_K1_F0", "T", (G0 + C.DAY // 2, G0 + 40 * C.H1), [_sig(t_in)], U, cost, 10_000.0)
    tr = res.trades[0]
    k = [r for r in res.equity if r[0] == t_in + C.M5][0]            # giriş sonrası ilk kesit
    assert k[2] == pytest.approx(10_000.0 - tr["entry_fee"])          # nakit
    assert res.ledger.wallet - 10_000.0 == pytest.approx(tr["net_PnL"])
    assert tr["net_PnL"] == pytest.approx(tr["gross_PnL"] - tr["entry_fee"] - tr["exit_fee"])


def test_funding_yinelenen_ve_catisan_settlement(tmp_path):
    p = tmp_path / "f.csv"
    p.write_text("calc_time,funding_interval_hours,last_funding_rate\n"
                 f"{G0 + 8 * C.H1},8,0.0001\n{G0 + 8 * C.H1 + 5},8,0.0001\n"     # aynı settlement, ms titreşimi
                 f"{G0 + 16 * C.H1},8,0.0002\n{G0 + 16 * C.H1},8,-0.0005\n"      # çatışma
                 f"{G0 + 40 * C.H1},8,0.0001\nbozuk,8,x\n")
    t, r, g, src, q = D.load_funding(str(p), G0, G0 + 3 * C.DAY)
    assert list(t) == [G0 + 8 * C.H1, G0 + 40 * C.H1]
    assert q["duplicates_after_snap"] == 1 and q["conflicting_settlements"] == 1
    assert q["dropped_unparseable"] == 1
    assert q["coverage_gaps"] == 1                     # 08:00 → ertesi gün 16:00 > 8s+1dk
    t2, *_ = D.load_funding(None, G0, G0 + C.DAY)
    assert len(t2) == 0
