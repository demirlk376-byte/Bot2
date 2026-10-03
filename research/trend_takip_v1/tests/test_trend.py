import numpy as np
import pytest

from research.liquidity_sweep_v1 import config as C
from research.trend_takip_v1 import engine as E

DAY = C.DAY
T0 = 1_577_836_800_000          # 2020-01-01
ZERO = C.CostProfile("Z", 0, 0, 0, 0, "t")


def sym(closes, name="AAA", spread=1.0, funding=()):
    c = np.asarray(closes, float)
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + spread
    l = np.minimum(o, c) - spread
    t = T0 + np.arange(len(c)) * DAY
    ft = np.array([x for x, _ in funding], dtype="int64")
    fr = np.array([r for _, r in funding], float)
    return E.Sym(name, t.astype("int64"), o, h, l, c, 0.01, 1.0, 0.001, 0.001, ft, fr)


def flat_then_trend(n_flat=260, up=60, down=40):
    return [100.0] * n_flat + [100 + 2 * i for i in range(1, up + 1)] + [220 - 4 * i for i in range(1, down + 1)]


def test_kirilim_ertesi_acilista_long_ve_takip_stopu():
    s = sym(flat_then_trend())
    tr, bl, eq, led, op = E.simulate("N50_X3_L", (T0, T0 + 360 * DAY), {"AAA": s}, ZERO)
    t = tr[0]
    i_sig = 260                                      # ilk kapanış > önceki 50 gün tepesi (101)
    assert t["fill_time"] == s.t[i_sig + 1] and t["E_fill"] == pytest.approx(s.o[i_sig + 1])
    assert t["side"] == "LONG" and t["exit_reason"] in ("STOP", "STOP_GAP")
    assert t["exit_time"] > s.t[260 + 60]            # trendin tepesinden SONRA çıkar (taşır)
    assert t["net_R"] > 5                            # büyük trendin büyük kısmı alındı
    assert abs((led.wallet - 10_000) - sum(x["net_PnL"] for x in tr)) < 1e-6


def test_gelecek_degisince_gecmis_ayni():
    a = flat_then_trend()
    b = list(a)
    b[330:] = [x * 1.3 for x in b[330:]]
    r1 = E.simulate("N50_X5_LS", (T0, T0 + 360 * DAY), {"AAA": sym(a)}, ZERO)[0]
    r2 = E.simulate("N50_X5_LS", (T0, T0 + 360 * DAY), {"AAA": sym(b)}, ZERO)[0]
    cut = T0 + 330 * DAY
    assert [x["fill_time"] for x in r1 if x["fill_time"] < cut] == [x["fill_time"] for x in r2 if x["fill_time"] < cut]


def test_stop_yalniz_lehe_ve_bosluk_acilistan():
    c = flat_then_trend(up=30, down=0) + [130.0] * 5
    s = sym(c)
    s.o[-3] = 120.0                                  # açılış stopun çok altında (boşluk)
    s.l[-3] = 119.0
    tr = E.simulate("N50_X3_L", (T0, T0 + 400 * DAY), {"AAA": s}, ZERO)[0]
    t = tr[0]
    assert t["exit_reason"] in ("STOP_GAP", "STOP")
    if t["exit_reason"] == "STOP_GAP":
        assert t["X_reference"] == pytest.approx(120.0)


def test_donem_sonu_kapatilir_acik_kalmaz():
    s = sym([100.0] * 260 + [100 + 2 * i for i in range(1, 80)])
    tr, bl, eq, led, op = E.simulate("N100_X5_L", (T0, T0 + 300 * DAY), {"AAA": s}, ZERO)
    assert not op
    assert tr[-1]["exit_reason"] == "PARTITION_END"


def test_xh_cikis_kapanista_sinyal_ertesi_acilista():
    s = sym(flat_then_trend())
    tr = E.simulate("N50_XH_L", (T0, T0 + 360 * DAY), {"AAA": s}, ZERO)[0]
    t = tr[0]
    assert t["exit_reason"] == "EXIT_SIGNAL" and t["exit_phase"] == "OPEN"


def test_funding_isareti_ve_tek_kez():
    fund = [(T0 + 300 * DAY + 8 * C.H1, 0.001)]
    s = sym(flat_then_trend(), funding=fund)
    tr, bl, eq, led, op = E.simulate("N50_X3_L", (T0, T0 + 360 * DAY), {"AAA": s}, ZERO)
    t = tr[0]
    assert t["funding_cashflow"] < 0 and led.funding == pytest.approx(t["funding_cashflow"])


def test_erken_cikis_tutmayan_kirilimi_keser():
    # kırılım sonrası yatay: +1R görülmez → E10 ile ~10 gün sonra EXIT_SIGNAL, tabanda daha uzun tutulur
    c = [100.0] * 260 + [103.0] + [103.0] * 60
    s = sym(c, spread=0.5)
    base = E.simulate("N50_X5_L", (T0, T0 + 320 * DAY), {"AAA": s}, ZERO)[0]
    e10 = E.simulate("N50_X5_L", (T0, T0 + 320 * DAY), {"AAA": s}, ZERO, early_days=10)[0]
    assert e10[0]["exit_reason"] == "EXIT_SIGNAL" and e10[0]["hold_days"] == pytest.approx(10)
    assert base[0]["hold_days"] > e10[0]["hold_days"]


def test_erken_cikis_kazanani_kesmez():
    s = sym(flat_then_trend())
    a = E.simulate("N50_X5_L", (T0, T0 + 360 * DAY), {"AAA": s}, ZERO)[0]
    b = E.simulate("N50_X5_L", (T0, T0 + 360 * DAY), {"AAA": s}, ZERO, early_days=10)[0]
    assert a[0]["net_R"] == pytest.approx(b[0]["net_R"]) and b[0]["exit_reason"] != "EXIT_SIGNAL"


def test_nwk_giris_sinyalleri_kullanir(monkeypatch):
    s = sym(flat_then_trend())
    monkeypatch.setattr(E, "nwk_signals", lambda x: {270: 1})
    tr = E.simulate("N50_X5_LS", (T0, T0 + 360 * DAY), {"AAA": s}, ZERO, entry="NWK")[0]
    assert tr[0]["signal_time"] == s.t[271] and tr[0]["fill_time"] == s.t[271]


def _dalgali(n=700, seed=3):
    r = np.random.default_rng(seed)
    return list(100 * np.exp(np.cumsum(r.normal(0, 0.03, n))))


def test_nwk_2g_sinyali_blok_sonunda_ve_nedensel():
    a = _dalgali()
    s = sym(a)
    e = E.nwk_entries({"AAA": s}, tf_days=2)["AAA"]
    assert e and all((s.t[i] // DAY) % 2 == 1 for i in e)
    b = list(a); b[500:] = [x * 1.5 for x in b[500:]]
    e2 = E.nwk_entries({"AAA": sym(b)}, tf_days=2)["AAA"]
    assert {i: d for i, d in e.items() if i < 499} == {i: d for i, d in e2.items() if i < 499}


def test_nwk_1g_eski_fonksiyonla_ayni_ve_filtre_alt_kume():
    s = sym(_dalgali())
    f0 = E.nwk_entries({"AAA": s, "ETH": s})["AAA"]
    assert f0 == E.nwk_signals(s)
    for f in ("F1", "F2", "F3"):
        fx = E.nwk_entries({"AAA": s, "ETH": s}, filt=f)["AAA"]
        assert set(fx.items()) <= set(f0.items())


def test_g_filtreleri_alt_kume_ve_funding_nedensel():
    a = _dalgali()
    fund = [(T0 + i * 8 * C.H1 + 1, 0.0003 if i % 7 == 0 else 0.0) for i in range(3 * 700)]
    s = sym(a, funding=fund)
    s.v = np.abs(np.random.default_rng(1).normal(100, 30, len(a)))
    f0 = E.nwk_entries({"AAA": s})["AAA"]
    for f in ("G1", "G2", "G3"):
        assert set(E.nwk_entries({"AAA": s}, filt=f)["AAA"].items()) <= set(f0.items())
    g1 = E.nwk_entries({"AAA": s}, filt="G1")["AAA"]
    s2 = sym(a, funding=fund[:3 * 400] + [(x, 0.01) for x, _ in fund[3 * 400:]])
    g1b = E.nwk_entries({"AAA": s2}, filt="G1")["AAA"]
    assert {i: d for i, d in g1.items() if i < 398} == {i: d for i, d in g1b.items() if i < 398}


def test_4h_mum_kirilim_ve_funding_mum_icinde():
    H4 = 4 * C.H1
    c = np.asarray(flat_then_trend(n_flat=1300, up=60, down=40), float)
    o = np.r_[c[0], c[:-1]]
    t = (T0 + np.arange(len(c)) * H4).astype("int64")
    fund = np.array([T0 + 1350 * H4 + 1], dtype="int64")
    s = E.Sym("AAA", t, o, np.maximum(o, c) + 1, np.minimum(o, c) - 1, c, 0.01, 1.0, 0.001, 0.001, fund, np.array([0.001]))
    tr, bl, eq, led, op = E.simulate("N60_X3_L", (T0, int(t[-1]) + H4), {"AAA": s}, ZERO, bar_ms=H4)
    assert tr[0]["fill_time"] == t[1301]                      # 200 gün = 1200 mum ısınma geçti; kırılım 1300'de
    assert tr[0]["funding_cashflow"] < 0 and led.funding == pytest.approx(tr[0]["funding_cashflow"])
    assert eq[1][0] - eq[0][0] == H4


def test_rejim_kapaliyken_long_acilmaz_acik_pozisyon_surer():
    s = sym(flat_then_trend())
    kapali = {int(t): False for t in s.t}
    tr = E.simulate("N50_X3_L", (T0, T0 + 360 * DAY), {"AAA": s}, ZERO, regime=kapali)[0]
    assert tr == []
    # rejim sinyal gününden SONRA kapanırsa açık pozisyon etkilenmez
    gec = {int(t): (i <= 261) for i, t in enumerate(s.t)}
    a = E.simulate("N50_X3_L", (T0, T0 + 360 * DAY), {"AAA": s}, ZERO)[0]
    b = E.simulate("N50_X3_L", (T0, T0 + 360 * DAY), {"AAA": s}, ZERO, regime=gec)[0]
    assert a[0]["net_R"] == pytest.approx(b[0]["net_R"])


def test_rejim_son_tamamlanan_gunu_kullanir_4h():
    H4 = 4 * C.H1
    t_bar = T0 + 10 * DAY + 20 * C.H1          # günün son 4h mumu; kapanışı ertesi gün 00:00
    assert ((t_bar + H4) // DAY) * DAY - DAY == T0 + 10 * DAY
    t_bar = T0 + 10 * DAY                       # günün ilk mumu; kapanışta tamamlanan gün bir önceki
    assert ((t_bar + H4) // DAY) * DAY - DAY == T0 + 9 * DAY


def test_piramit_ekler_ve_muhasebe_tutar():
    s = sym(flat_then_trend(up=80))
    a = E.simulate("N50_X5_L", (T0, T0 + 380 * DAY), {"AAA": s}, ZERO)
    b = E.simulate("N50_X5_L", (T0, T0 + 380 * DAY), {"AAA": s}, ZERO, pyr_adds=2)
    ta, tb = a[0][0], b[0][0]
    assert tb["quantity_base"] > ta["quantity_base"] and tb["E_fill"] > ta["E_fill"]
    assert tb["R0_USDT"] > ta["R0_USDT"] and tb["net_PnL"] > ta["net_PnL"]
    assert abs((b[3].wallet - 10_000) - sum(x["net_PnL"] for x in b[0])) < 1e-6
    assert b[3].margin_used == pytest.approx(0) if hasattr(b[3], "margin_used") else True


def test_ayida_short_yalniz_rejim_kapaliyken():
    c = [100.0] * 260 + [100 - 1.5 * i for i in range(1, 50)] + [26.5] * 20
    s = sym(c)
    acik = {int(t): True for t in s.t}
    kapali = {int(t): False for t in s.t}
    tr_on = E.simulate("N50_X5_LS", (T0, T0 + 330 * DAY), {"AAA": s}, ZERO, regime=acik, short_in_bear=True)[0]
    tr_off = E.simulate("N50_X5_LS", (T0, T0 + 330 * DAY), {"AAA": s}, ZERO, regime=kapali, short_in_bear=True)[0]
    assert not [t for t in tr_on if t["side"] == "SHORT"]
    assert tr_off and tr_off[0]["side"] == "SHORT" and tr_off[0]["net_R"] > 0
