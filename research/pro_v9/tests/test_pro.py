import numpy as np
import pytest

from research.liquidity_sweep_v1 import config as C
from research.trend_takip_v1 import engine as E
from research.pro_v9 import strat as S

DAY = C.DAY
T0 = 1_578_268_800_000                  # bir Pazartesi (2020-01-06)
ZERO = C.CostProfile("Z", 0, 0, 0, 0, "t")


def sym(name, closes, funding=()):
    c = np.asarray(closes, float)
    o = np.r_[c[0], c[:-1]]
    t = (T0 + np.arange(len(c)) * DAY).astype("int64")
    ft = np.array([x for x, _ in funding], dtype="int64")
    fr = np.array([r for _, r in funding], float)
    return E.Sym(name, t, o, np.maximum(o, c) * 1.01, np.minimum(o, c) * 0.99, c, 0.01, 1, 1, 1, ft, fr)


def test_pazartesi_hesabi():
    assert (T0 // DAY + 3) % 7 == 0


def test_xs_gucluyu_long_zayifi_short_alir_ve_kazanir():
    n = 400
    up = [100 * 1.002 ** i for i in range(n)]
    dn = [100 * 0.998 ** i for i in range(n)]
    fl = [100.0 + (i % 2) for i in range(n)]
    syms = {"UP": sym("UP", up), "DN": sym("DN", dn), "F1": sym("F1", fl), "F2": sym("F2", fl)}
    curve, weekly, opens = S.xs_momentum(syms, (T0 + 210 * DAY, T0 + n * DAY), 28, "LS", ZERO)
    assert curve[-1][1] > 0 and opens >= 2
    assert sum(weekly.values()) == pytest.approx(curve[-1][1])


def test_xs_gelecek_degisince_gecmis_ayni():
    n = 400
    r = np.random.default_rng(5)
    base = {k: list(100 * np.exp(np.cumsum(r.normal(0, 0.03, n)))) for k in "ABCD"}
    alt = {k: v[:300] + [x * 1.5 for x in v[300:]] for k, v in base.items()}
    w = (T0 + 210 * DAY, T0 + n * DAY)
    c1 = S.xs_momentum({k: sym(k, v) for k, v in base.items()}, w, 28, "LS", ZERO)[0]
    c2 = S.xs_momentum({k: sym(k, v) for k, v in alt.items()}, w, 28, "LS", ZERO)[0]
    cut = T0 + 299 * DAY
    assert [p for t, p in c1 if t <= cut] == pytest.approx([p for t, p in c2 if t <= cut])


def test_fc_yuksek_funding_toplar_maliyet_dusulur():
    n = 60
    fund = [(T0 + i * 8 * C.H1 + 1, 0.0005) for i in range(3 * n)]
    syms = {"A": sym("A", [100.0] * n, fund), "B": sym("B", [100.0] * n)}
    cost = C.TWIN_MARKET_PROFILE
    curve, weekly, tr = S.funding_carry(syms, (T0, T0 + n * DAY), 0.0003, cost)
    assert tr == 1
    days_held = n - 7                       # ilk pazartesi (gün 7) seçilir
    gross = 1000 * 0.0005 * 3 * days_held
    c_in = 1000 * (cost.entry_fee_rate + 0.001 + 2 * cost.entry_slip_bp * 1e-4)
    c_out = 1000 * (cost.exit_fee_rate + 0.001 + 2 * cost.exit_slip_bp * 1e-4)
    assert curve[-1][1] == pytest.approx(gross - c_in - c_out, rel=0.02)
