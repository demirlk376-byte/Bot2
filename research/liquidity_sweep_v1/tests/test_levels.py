"""
Bağımsız seviye testleri (şartname §5, §21 No.1-3 ve "Ek zorunlu testler" L3/L4 maddeleri).

Beklenen değerler şartnameden elle türetilmiştir; üretim fonksiyonu yalnız girdiyi kurmak ve
gözlenecek nesneyi üretmek için çağrılır. Her long/LOW fixture'ının kısa/HIGH aynası
(fiyat' = 200 - fiyat; high/low rolleri yer değiştirir) aynı testte `mirror` parametresiyle koşar.

Fixture düzeni: g0 = 2023-01-01 00:00 UTC. "Saatlik" kurucu her 1H barı 12 özdeş 5m bara
(o=O, h=H, l=L, c=C) böler; böylece 1H ve 15m agregaları da (O,H,L,C) olur. Varsayılan bar
(100, 101, 99, 100): TR=2 ve ATR14=2 (ilk TR tohumu) olur; tolerans 0.10*2 = 0.20.
"""
from __future__ import annotations

import numpy as np
import pytest

from research.liquidity_sweep_v1 import config as C
from research.liquidity_sweep_v1 import data_contract as D
from research.liquidity_sweep_v1 import events as E
from research.liquidity_sweep_v1 import levels as LV

G0 = 1_672_531_200_000          # 2023-01-01 00:00:00 UTC
H = 3_600_000                   # 1 saat (ms) — literal, config'ten bağımsız
M15 = 900_000
DAY = 86_400_000
K = 200.0                       # ayna sabiti
DEF = (100.0, 101.0, 99.0, 100.0)
MIRROR = [pytest.param(False, id="long_HIGHbase"), pytest.param(True, id="mirror")]


# ───────────────────────────── yardımcılar ───────────────────────────────────
def sw(side, mirror):
    """Aynada HIGH<->LOW."""
    return side if not mirror else {"HIGH": "LOW", "LOW": "HIGH"}[side]


def px(p, mirror):
    return p if not mirror else K - p


def make_sd(o, h, l, c, valid=None):
    o, h, l, c = (np.asarray(x, dtype=float) for x in (o, h, l, c))
    n = len(c)
    if valid is None:
        valid = np.isfinite(c)
    return D.SymbolData(symbol="TST", source="TEST", g0=G0, o=o, h=h, l=l, c=c, v=np.ones(n),
                        valid5=np.asarray(valid, bool), tick=0.01, contract_size=1.0, vol_unit=1.0,
                        min_vol=1.0, meta_source="test")


def reflect(o, h, l, c, mirror):
    if not mirror:
        return o, h, l, c
    return K - o, K - l, K - h, K - c


def hourly(n_hours, bars=None, o5=None, mirror=False, n5=None):
    """bars: {saat: (O,H,L,C)}; o5: {5m indeksi: (o,h,l,c)} (saatlik değerin üstüne yazar)."""
    bars = bars or {}
    o, h, l, c = (np.empty(n_hours * 12) for _ in range(4))
    for hr in range(n_hours):
        O, Hh, L, Cc = bars.get(hr, DEF)
        s = slice(hr * 12, hr * 12 + 12)
        o[s], h[s], l[s], c[s] = O, Hh, L, Cc
    for k, (oo, hh, ll, cc) in (o5 or {}).items():
        o[k], h[k], l[k], c[k] = oo, hh, ll, cc
    if n5 is not None:
        o, h, l, c = o[:n5], h[:n5], l[:n5], c[:n5]
    return make_sd(*reflect(o, h, l, c, mirror))


def five_min(n_days, bars, missing=(), mirror=False, base=(100.0, 100.5, 99.5, 100.0)):
    """5m düzeyinde kurulum: düz taban + {k: (o,h,l,c)} + eksik barlar (NaN, valid=False)."""
    n = n_days * 288
    o, h, l, c = (np.full(n, v) for v in base)
    for k, (oo, hh, ll, cc) in bars.items():
        o[k], h[k], l[k], c[k] = oo, hh, ll, cc
    o, h, l, c = reflect(o, h, l, c, mirror)
    valid = np.ones(n, bool)
    for k in missing:
        o[k] = h[k] = l[k] = c[k] = np.nan
        valid[k] = False
    return make_sd(o, h, l, c, valid)


def book(family, sd):
    dv = LV.Derived(sd)
    return dv, LV.LevelBook(family, dv)


def side_levels(bk, side):
    return [lv for lv in bk.levels if lv.side == side]


def origin_is(lv, hours):
    """origin_times = pivot barlarının oluşum zamanları. Şartname açılış/kapanış damgasını
    sabitlemediği için iki gösterimi de kabul et (fark/48s kuralı ikisinde aynı)."""
    got = set(int(x) for x in lv.origin_times)
    return got in ({G0 + h * H for h in hours}, {G0 + (h + 1) * H for h in hours})


def k5(day, hh, mm):
    """Gün içi saat:dakika → 5m ızgara indeksi."""
    return day * 288 + (hh * 60 + mm) // 5


def t(day, hh=0, mm=0):
    return G0 + day * DAY + hh * H + mm * 60_000


# ───────────────────── §21 No.1 — pivot 5. bar kapanmadan görünmez ────────────
NO1 = {0: (99.0, 100.0, 98.0, 99.0), 1: (100.0, 101.0, 99.0, 100.0), 2: (104.0, 105.0, 103.0, 104.0),
       3: (102.0, 103.0, 101.0, 102.0), 4: (101.0, 102.0, 100.0, 101.0)}
FLAT102 = (101.0, 102.0, 100.0, 101.0)


def _no1_bars(n):
    b = {i: FLAT102 for i in range(5, n)}
    b.update(NO1)
    return b


@pytest.mark.parametrize("mirror", MIRROR)
def test_no1_pivot_known_only_at_close_of_fifth_bar(mirror):
    n = 72
    _, bk = book("L3", hourly(n, _no1_bars(n), mirror=mirror))
    side = sw("HIGH", mirror)
    lvs = side_levels(bk, side)
    assert len(lvs) == 1
    lv = lvs[0]
    assert lv.price == pytest.approx(px(105.0, mirror), abs=1e-9)
    assert lv.known_at == G0 + 5 * H                 # p=2 → p+2 (04:00-05:00) kapanışı 05:00
    assert lv.expires_at == G0 + 5 * H + 48 * H
    assert origin_is(lv, (2,))
    # 04:45 15m barı başında (5. 1H bar kapanmadan) görünmez; 05:00 barında seçilir
    assert bk.reference(side, G0 + 4 * H + 45 * 60_000) is None
    assert bk.reference(side, G0 + 5 * H - 1) is None
    got = bk.reference(side, G0 + 5 * H)
    assert got is not None and got.level_id == lv.level_id


@pytest.mark.parametrize("mirror", MIRROR)
def test_no1_truncated_before_fifth_close_has_no_pivot(mirror):
    # 4 tam saat + 5. saatin 11 adet 5m barı: 5. 1H bar tamamlanmadı → pivot yok
    _, bk = book("L3", hourly(5, NO1, mirror=mirror, n5=4 * 12 + 11))
    assert side_levels(bk, sw("HIGH", mirror)) == []
    # beşinci bar kapandığında (12. 5m bar da geldi) pivot var
    _, bk2 = book("L3", hourly(5, NO1, mirror=mirror, n5=5 * 12))
    lvs = side_levels(bk2, sw("HIGH", mirror))
    assert len(lvs) == 1 and lvs[0].price == pytest.approx(px(105.0, mirror), abs=1e-9)
    assert lvs[0].known_at == G0 + 5 * H


# ───────────────────── §21 No.2 — sıkı eşitsizlik ─────────────────────────────
@pytest.mark.parametrize("mirror", MIRROR)
def test_no2_equal_highs_no_pivot(mirror):
    n = 72
    b = _no1_bars(n)
    b[3] = (104.0, 105.0, 103.0, 104.0)          # high dizisi 100,101,105,105,102
    _, bk = book("L3", hourly(n, b, mirror=mirror))
    side = sw("HIGH", mirror)
    assert side_levels(bk, side) == []
    for tau in (G0 + 5 * H, G0 + 6 * H, G0 + 30 * H):
        assert bk.reference(side, tau) is None


@pytest.mark.parametrize("mirror", MIRROR)
def test_one_tick_lower_neighbour_is_still_pivot(mirror):
    # 105 vs 104.99: bir tam tick farkı eşit sayılmaz → 105 pivot
    n = 72
    b = _no1_bars(n)
    b[3] = (103.99, 104.99, 102.99, 103.99)
    _, bk = book("L3", hourly(n, b, mirror=mirror))
    lvs = side_levels(bk, sw("HIGH", mirror))
    assert len(lvs) == 1
    assert lvs[0].price == pytest.approx(px(105.0, mirror), abs=1e-9)


# ───────────────────── §21 No.3 + L2 kuralları ────────────────────────────────
def _l2_fixture(mirror):
    bars = {
        k5(1, 0, 0): (100.0, 100.5, 96.0, 100.0),     # seansın ilk barı: seans dibi 96 (dahil)
        k5(1, 7, 55): (100.0, 105.0, 99.5, 100.0),    # seansın son barı: seans tepesi 105 (dahil)
        k5(1, 8, 0): (100.0, 107.0, 99.5, 100.0),     # 08:00 barı: pencere dışında
        k5(1, 8, 20): (100.0, 100.5, 93.0, 100.0),    # 08:20 barı: pencere dışında
        k5(0, 23, 55): (100.0, 100.5, 92.0, 100.0),   # önceki gün 23:55: pencere dışında
    }
    # gün 2 seansında bir bar eksik → gün 2 için L2 yok (96 tam bar şartı)
    return five_min(3, bars, missing=(k5(2, 3, 0),), mirror=mirror)


@pytest.mark.parametrize("mirror", MIRROR)
def test_no3_l2_known_at_0800_and_0745_bar_cannot_use_it(mirror):
    _, bk = book("L2", _l2_fixture(mirror))
    hi, lo = sw("HIGH", mirror), sw("LOW", mirror)
    # gün 1 seviyeleri: [00:00,08:00) → HIGH 105, LOW 96 (aynada LOW 95, HIGH 104)
    lh = [lv for lv in side_levels(bk, hi) if lv.known_at == t(1, 8)]
    ll = [lv for lv in side_levels(bk, lo) if lv.known_at == t(1, 8)]
    assert len(lh) == 1 and len(ll) == 1
    assert lh[0].price == pytest.approx(px(105.0, mirror), abs=1e-9)
    assert ll[0].price == pytest.approx(px(96.0, mirror), abs=1e-9)
    for lv in (lh[0], ll[0]):
        assert lv.expires_at == t(2)
    # 07:45 barı (ve gün başı): gün-0 L2 süresi 00:00'da doldu, gün-1 L2 henüz bilinmiyor
    for tau in (t(1, 0), t(1, 7, 30), t(1, 7, 45)):
        assert bk.reference(hi, tau) is None
        assert bk.reference(lo, tau) is None
    # ilk aday 08:00 barı
    assert bk.reference(hi, t(1, 8)).level_id == lh[0].level_id
    assert bk.reference(lo, t(1, 8)).level_id == ll[0].level_id
    # son geçerli bar 23:45; D+1 00:00'da süresi doldu
    assert bk.reference(hi, t(1, 23, 45)).level_id == lh[0].level_id
    assert bk.reference(hi, t(2)) is None


@pytest.mark.parametrize("mirror", MIRROR)
def test_l2_day0_values_and_expiry(mirror):
    _, bk = book("L2", _l2_fixture(mirror))
    hi, lo = sw("HIGH", mirror), sw("LOW", mirror)
    # gün 0 seansı düz: high 100.5, low 99.5 (23:55'teki 92 seans dışında)
    h0 = bk.reference(hi, t(0, 8))
    l0 = bk.reference(lo, t(0, 8))
    assert h0.price == pytest.approx(px(100.5, mirror), abs=1e-9)
    assert l0.price == pytest.approx(px(99.5, mirror), abs=1e-9)
    assert h0.known_at == t(0, 8) and h0.expires_at == t(1)
    assert bk.reference(hi, t(0, 7, 45)) is None


@pytest.mark.parametrize("mirror", MIRROR)
def test_l2_incomplete_session_no_level(mirror):
    _, bk = book("L2", _l2_fixture(mirror))
    for side in ("HIGH", "LOW"):
        assert not [lv for lv in bk.levels if lv.side == side and lv.known_at == t(2, 8)]
        for tau in (t(2, 8), t(2, 12), t(2, 23, 45)):
            assert bk.reference(side, tau) is None


@pytest.mark.parametrize("mirror", MIRROR)
def test_no3_first_l2_event_is_0800_bar(mirror):
    """Gün 1'de 08:00'dan önce hiçbir L2 olayı yok; ilk olay 08:00 barında (seans tepesi 105'in
    07:55 barından sonra 08:00 barı 107'ye çıkıyor)."""
    dv, bk = book("L2", _l2_fixture(mirror))
    evs, _ = E.detect("L2", dv, bk)
    day1 = sorted((e for e in evs if t(1) <= e.sweep_open < t(2)), key=lambda e: e.sweep_open)
    assert all(e.sweep_open >= t(1, 8) for e in day1)
    assert day1, "gün 1 için L2 olayı bekleniyordu"
    first = day1[0]
    assert first.sweep_open == t(1, 8)
    assert first.side == ("SHORT" if not mirror else "LONG")
    assert first.level_price == pytest.approx(px(105.0, mirror), abs=1e-9)


# ───────────────────── L1 — önceki UTC gün ────────────────────────────────────
def _l1_fixture(mirror, missing=()):
    bars = {
        k5(0, 10, 0): (100.0, 110.0, 99.5, 100.0),  # gün 0 tepe 110
        k5(0, 14, 0): (100.0, 100.5, 95.0, 100.0),  # gün 0 dip 95
        k5(1, 6, 0): (100.0, 120.0, 99.5, 100.0),   # gün 1 tepe 120 (gün 1 L1'ini değiştirmemeli)
        k5(1, 18, 0): (100.0, 100.5, 85.0, 100.0),  # gün 1 dip 85
        k5(2, 12, 0): (100.0, 112.0, 99.5, 100.0),  # gün 2 tepe 112
        k5(2, 13, 0): (100.0, 100.5, 88.0, 100.0),  # gün 2 dip 88
    }
    return five_min(4, bars, missing=missing, mirror=mirror)


@pytest.mark.parametrize("mirror", MIRROR)
def test_l1_previous_day_levels_known_and_expiry(mirror):
    _, bk = book("L1", _l1_fixture(mirror))
    hi, lo = sw("HIGH", mirror), sw("LOW", mirror)
    # gün 0: önceki gün yok → L1 yok
    for tau in (t(0), t(0, 12), t(0, 23, 45)):
        assert bk.reference(hi, tau) is None and bk.reference(lo, tau) is None
    exp = {1: (110.0, 95.0), 2: (120.0, 85.0), 3: (112.0, 88.0)}
    ids_h, ids_l = set(), set()
    for d, (ph, pl) in exp.items():
        rh, rl = bk.reference(hi, t(d)), bk.reference(lo, t(d))
        assert rh.price == pytest.approx(px(ph, mirror), abs=1e-9)
        assert rl.price == pytest.approx(px(pl, mirror), abs=1e-9)
        assert rh.known_at == t(d) and rh.expires_at == t(d + 1)
        assert rl.known_at == t(d) and rl.expires_at == t(d + 1)
        # gün boyunca aynı kimlik/fiyat (gün içi yeni tepe/dip seviyeyi değiştirmez)
        for hh, mm in ((6, 5), (12, 0), (23, 45)):
            assert bk.reference(hi, t(d, hh, mm)).level_id == rh.level_id
            assert bk.reference(lo, t(d, hh, mm)).level_id == rl.level_id
        ids_h.add(rh.level_id)
        ids_l.add(rl.level_id)
    assert len(ids_h) == 3 and len(ids_l) == 3
    # günde yön başına tek seviye
    assert len(side_levels(bk, hi)) == 3 and len(side_levels(bk, lo)) == 3
    # gün 1 akşamı: fiyat hâlâ 110 (gün 1'in 120 tepesi değil)
    assert bk.reference(hi, t(1, 23, 45)).price == pytest.approx(px(110.0, mirror), abs=1e-9)


@pytest.mark.parametrize("mirror", MIRROR)
def test_l1_missing_previous_day_no_level(mirror):
    # gün 1'de bir 5m bar eksik → gün 2'de L1 yok; gün 1 L1'i (gün 0'dan) ve gün 3 L1'i var
    _, bk = book("L1", _l1_fixture(mirror, missing=(k5(1, 12, 0),)))
    hi, lo = sw("HIGH", mirror), sw("LOW", mirror)
    assert bk.reference(hi, t(1)).price == pytest.approx(px(110.0, mirror), abs=1e-9)
    assert bk.reference(lo, t(1)).price == pytest.approx(px(95.0, mirror), abs=1e-9)
    for tau in (t(2), t(2, 8), t(2, 23, 45)):
        assert bk.reference(hi, tau) is None
        assert bk.reference(lo, tau) is None
    assert not [lv for lv in bk.levels if lv.known_at == t(2)]
    assert bk.reference(hi, t(3)).price == pytest.approx(px(112.0, mirror), abs=1e-9)
    assert bk.reference(lo, t(3)).price == pytest.approx(px(88.0, mirror), abs=1e-9)


# ───────────────────── L3 — en son doğrulanmış 1H pivot ───────────────────────
PIV_A = (100.0, 103.0, 99.0, 100.0)       # saat 10: tepe 103
PIV_B = (100.0, 102.0, 99.0, 100.0)       # saat 20: tepe 102


@pytest.mark.parametrize("mirror", MIRROR)
def test_l3_known_expiry_and_latest_wins(mirror):
    _, bk = book("L3", hourly(96, {10: PIV_A, 20: PIV_B}, mirror=mirror))
    side = sw("HIGH", mirror)
    lvs = sorted(side_levels(bk, side), key=lambda x: x.known_at)
    assert len(lvs) == 2
    a, b = lvs
    assert a.price == pytest.approx(px(103.0, mirror), abs=1e-9)
    assert b.price == pytest.approx(px(102.0, mirror), abs=1e-9)
    assert a.known_at == G0 + 13 * H and a.expires_at == G0 + 61 * H
    assert b.known_at == G0 + 23 * H and b.expires_at == G0 + 71 * H
    assert a.level_id != b.level_id
    assert bk.reference(side, G0 + 13 * H - M15) is None
    assert bk.reference(side, G0 + 13 * H).level_id == a.level_id
    assert bk.reference(side, G0 + 23 * H - M15).level_id == a.level_id
    # yeni pivot bilindiği an referans odur (eski daha yüksek tepe hâlâ aktif olsa da)
    assert bk.reference(side, G0 + 23 * H).level_id == b.level_id
    assert bk.reference(side, G0 + 71 * H - M15).level_id == b.level_id
    assert bk.reference(side, G0 + 71 * H) is None


@pytest.mark.parametrize("mirror", MIRROR)
def test_l3_consumed_latest_pivot_no_fallback_to_older(mirror):
    """B (102) saat 24'te süpürülür ve tüketilir. Saat 25'te A'yı (103, hâlâ süresi dolmamış)
    süpüren hareket olay üretmemeli: en son pivot tüketildiyse eskisine dönülmez."""
    o5 = {24 * 12: (100.0, 102.6, 99.0, 100.0),     # B'yi süpürür: 102.6 >= 102 + 0.1*A15
          25 * 12: (100.0, 104.0, 99.0, 100.0)}     # A'yı süpürecek kadar: 104 >= 103 + 0.1*A15
    dv, bk = book("L3", hourly(96, {10: PIV_A, 20: PIV_B}, o5=o5, mirror=mirror))
    side = sw("HIGH", mirror)
    lvs = sorted(side_levels(bk, side), key=lambda x: x.known_at)
    a, b = lvs[0], lvs[1]
    assert a.price == pytest.approx(px(103.0, mirror), abs=1e-9)
    assert b.price == pytest.approx(px(102.0, mirror), abs=1e-9)
    evs, _ = E.detect("L3", dv, bk)
    ev_side = "SHORT" if not mirror else "LONG"
    mine = [e for e in evs if e.side == ev_side]
    assert [e.level_id for e in mine if e.sweep_open < G0 + 28 * H] == [b.level_id]
    assert mine[0].sweep_open == G0 + 24 * H
    assert b.consumed_at == G0 + 24 * H + M15
    assert not [e for e in evs if e.level_id == a.level_id]
    assert a.consumed_at is None
    # B tüketildikten sonra A aktif (known<=τ<expires, tüketilmemiş) olsa da seçilmez
    for tau in (G0 + 24 * H + M15, G0 + 25 * H, G0 + 27 * H + 45 * 60_000):
        assert bk.reference(side, tau) is None
    # saat 25 (104) yeni pivot: 28:00'de bilinir, yeni kimlik
    c = bk.reference(side, G0 + 28 * H)
    assert c is not None and c.level_id not in (a.level_id, b.level_id)
    assert c.price == pytest.approx(px(104.0, mirror), abs=1e-9)


@pytest.mark.parametrize("mirror", MIRROR)
def test_l3_directly_consumed_latest_no_fallback(mirror):
    _, bk = book("L3", hourly(96, {10: PIV_A, 20: PIV_B}, mirror=mirror))
    side = sw("HIGH", mirror)
    a, b = sorted(side_levels(bk, side), key=lambda x: x.known_at)
    # kitap kronolojik/durumludur: tüketimden önceki sorgu tüketimden önce yapılır
    assert bk.reference(side, G0 + 30 * H - M15).level_id == b.level_id
    b.consumed_at = G0 + 30 * H
    b.consume_reason = "SWEEP"
    for tau in (G0 + 30 * H, G0 + 40 * H, G0 + 60 * H + 45 * 60_000):
        assert a.known_at <= tau < a.expires_at          # A hâlâ aktif aralıkta
        assert bk.reference(side, tau) is None


# ───────────────────── L4 — birbirine yakın iki pivot ─────────────────────────
P102 = (100.0, 102.0, 100.0, 101.0)          # TR=2 (önceki close 100 aralıkta)
P1018 = (100.0, 101.8, 99.8, 100.8)          # TR=2
P10179 = (100.0, 101.79, 99.79, 100.79)      # TR=2; fark 0.21 = 0.20 + 1 tick


@pytest.mark.parametrize("mirror", MIRROR)
@pytest.mark.parametrize("first,second", [(P102, P1018), (P1018, P102)], ids=["hi_first", "hi_second"])
def test_l4_tolerance_exactly_equal_accepted(mirror, first, second):
    # ATR1h = 2 her yerde → tol = 0.20; |102.0 - 101.8| = 0.20 → kabul; fiyat = 102.0 (aynada 98.0)
    _, bk = book("L4", hourly(120, {10: first, 30: second}, mirror=mirror))
    side = sw("HIGH", mirror)
    lvs = side_levels(bk, side)
    assert len(lvs) == 1
    lv = lvs[0]
    assert lv.price == pytest.approx(px(102.0, mirror), abs=1e-9)
    assert lv.known_at == G0 + 33 * H
    assert lv.expires_at == G0 + 81 * H
    assert origin_is(lv, (10, 30))
    assert bk.reference(side, G0 + 13 * H) is None          # tek pivot: L4 yok
    assert bk.reference(side, G0 + 33 * H - M15) is None
    assert bk.reference(side, G0 + 33 * H).level_id == lv.level_id
    assert bk.reference(side, G0 + 81 * H - M15).level_id == lv.level_id
    assert bk.reference(side, G0 + 81 * H) is None
    assert side_levels(bk, sw("LOW", mirror)) == []


@pytest.mark.parametrize("mirror", MIRROR)
def test_l4_one_tick_beyond_tolerance_rejected(mirror):
    _, bk = book("L4", hourly(120, {10: P102, 30: P10179}, mirror=mirror))
    side = sw("HIGH", mirror)
    assert side_levels(bk, side) == []
    for tau in (G0 + 33 * H, G0 + 50 * H):
        assert bk.reference(side, tau) is None


@pytest.mark.parametrize("mirror", MIRROR)
@pytest.mark.parametrize("gap,ok", [(48, True), (49, False)], ids=["gap48_ok", "gap49_reject"])
def test_l4_formation_gap_at_most_48h(mirror, gap, ok):
    _, bk = book("L4", hourly(120, {10: P102, 10 + gap: P1018}, mirror=mirror))
    side = sw("HIGH", mirror)
    lvs = side_levels(bk, side)
    if ok:
        assert len(lvs) == 1
        assert lvs[0].price == pytest.approx(px(102.0, mirror), abs=1e-9)
        assert lvs[0].known_at == G0 + (10 + gap + 3) * H
        assert bk.reference(side, G0 + (10 + gap + 3) * H).level_id == lvs[0].level_id
    else:
        assert lvs == []
        assert bk.reference(side, G0 + (10 + gap + 3) * H) is None


@pytest.mark.parametrize("mirror", MIRROR)
def test_l4_atr_from_bar_completed_at_second_confirmation(mirror):
    """İkinci pivot p2=30 (101.75, fark 0.25). Bar 31 TR=2, bar 32 (=p2+2) TR=16:
    ATR[32] = 16/14 + 2*13/14 = 3.0 → tol 0.30 → kabul. (ATR[30] veya ATR[31] = 2 → tol 0.20 → ret.)"""
    bars = {10: P102, 30: (100.0, 101.75, 99.75, 100.75), 31: (100.75, 101.0, 99.0, 100.0),
            32: (100.0, 101.0, 85.0, 100.0)}
    _, bk = book("L4", hourly(120, bars, mirror=mirror))
    side = sw("HIGH", mirror)
    lvs = side_levels(bk, side)
    assert len(lvs) == 1
    assert lvs[0].price == pytest.approx(px(102.0, mirror), abs=1e-9)
    assert lvs[0].known_at == G0 + 33 * H


@pytest.mark.parametrize("mirror", MIRROR)
def test_l4_no_lookahead_atr(mirror):
    """p2=30 (101.70, fark 0.30). ATR[32] = 2 → tol 0.20 → ret. Bar 33 (onaydan SONRA) TR=16 ile
    ATR[33] = 3 olur; bu gelecekteki değer kullanılırsa 0.30 <= 0.30 kabul edilirdi."""
    bars = {10: P102, 30: (100.0, 101.7, 99.7, 100.7), 31: (100.7, 101.0, 99.0, 100.0),
            33: (100.0, 101.0, 85.0, 100.0)}
    _, bk = book("L4", hourly(120, bars, mirror=mirror))
    side = sw("HIGH", mirror)
    assert side_levels(bk, side) == []
    assert bk.reference(side, G0 + 33 * H) is None
    assert bk.reference(side, G0 + 40 * H) is None


@pytest.mark.parametrize("mirror", MIRROR)
def test_l4_new_nonqualifying_pivot_removes_reference(mirror):
    """P1=102 (10), P2=101.8 (30) → L4 102 @33:00. P3=102.1 (50): |P3-P2|=0.30 > tol(~0.2006) → 53:00'dan
    itibaren bu yönde L4 yok; L4(P1,P2) süresi (81:00) dolmamış olsa da seçilmez. |P3-P1|=0.10 olsa da
    ardışık olmayan 'en iyi çift' seçilmez."""
    bars = {10: P102, 30: P1018, 50: (100.0, 102.1, 100.0, 101.0)}
    _, bk = book("L4", hourly(120, bars, mirror=mirror))
    side = sw("HIGH", mirror)
    lvs = side_levels(bk, side)
    assert len(lvs) == 1
    lv = lvs[0]
    assert origin_is(lv, (10, 30))
    assert bk.reference(side, G0 + 53 * H - M15).level_id == lv.level_id
    for tau in (G0 + 53 * H, G0 + 60 * H, G0 + 80 * H + 45 * 60_000):
        assert tau < lv.expires_at
        assert bk.reference(side, tau) is None
    assert not [x for x in lvs if origin_is(x, (30, 50)) or origin_is(x, (10, 50))]


@pytest.mark.parametrize("mirror", MIRROR)
def test_l4_same_pair_not_recreated_after_consumption(mirror):
    """L4(P1,P2)=102 @33:00; saat 35-37 tepeleri 102.5 (eşit → pivot değil) ve saat 35'in ilk
    15m barı seviyeyi süpürüp tüketir. P3=101.9 (50): |P3-P2|=0.10 <= tol → yeni L4(P2,P3)=101.9,
    yeni kimlik, 53:00'da bilinir. Arada L4(P1,P2) yeni kimlikle dirilmez."""
    sweep = (100.0, 102.5, 99.0, 100.0)
    bars = {10: P102, 30: P1018, 35: sweep, 36: sweep, 37: sweep, 50: (100.0, 101.9, 99.9, 100.9)}
    dv, bk = book("L4", hourly(120, bars, mirror=mirror))
    side = sw("HIGH", mirror)
    lvs = sorted(side_levels(bk, side), key=lambda x: x.known_at)
    assert len(lvs) == 2
    a, b = lvs
    assert origin_is(a, (10, 30))
    assert origin_is(b, (30, 50))
    assert a.price == pytest.approx(px(102.0, mirror), abs=1e-9)
    assert b.price == pytest.approx(px(101.9, mirror), abs=1e-9)
    assert a.level_id != b.level_id
    assert len({lv.level_id for lv in bk.levels}) == len(bk.levels)
    evs, _ = E.detect("L4", dv, bk)
    ev_side = "SHORT" if not mirror else "LONG"
    mine = [e for e in evs if e.side == ev_side]
    assert [(e.level_id, e.sweep_open) for e in mine] == [(a.level_id, G0 + 35 * H)]
    assert a.consumed_at == G0 + 35 * H + M15
    # tüketimden sonra P3 onayına kadar referans yok; aynı çift yeni kimlikle geri gelmez
    for tau in (G0 + 35 * H + M15, G0 + 40 * H, G0 + 53 * H - M15):
        assert bk.reference(side, tau) is None
    assert bk.reference(side, G0 + 53 * H).level_id == b.level_id
    # olay tespitinden sonra da çift sayısı değişmedi
    same_pair = [lv for lv in bk.levels if origin_is(lv, (10, 30))]
    assert len(same_pair) == 1
