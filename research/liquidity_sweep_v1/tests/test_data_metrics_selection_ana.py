"""Veri sözleşmesi, metrikler, seçim/karar (şartname §3, §17, §18, §19, §21 No.4, No.35)."""
import os
import json

import numpy as np
import pandas as pd
import pytest

from research.liquidity_sweep_v1 import (config as C, data_contract as D, metrics as MT, selection as SL,
                                         setups as SU, cli)
from research.liquidity_sweep_v1.levels import Derived
from research.liquidity_sweep_v1.tests.sentetik import sentetik_evren

G0 = 1_672_531_200_000           # 2023-01-01 00:00 UTC (Pazar)


def _sd_flat(n5, valid=None):
    o = np.full(n5, 100.0)
    v = np.ones(n5, bool) if valid is None else valid
    o2 = o.copy()
    o2[~v] = np.nan
    return D.SymbolData(symbol="AAA", source="T", g0=G0, o=o2, h=o2 + 1, l=o2 - 1, c=o2.copy(), v=np.ones(n5),
                        valid5=v, tick=0.01, contract_size=1.0, vol_unit=1.0, min_vol=1.0, meta_source="t")


# ── §3.3 bar denetimi ─────────────────────────────────────────────────────────
def test_no4_analog_eksik_alt_bar_ust_tf_gecersiz_doldurma_yok():
    v = np.ones(C.GRID_PER_DAY * 2, bool)
    v[4] = False                                        # 00:20 5m barı yok
    sd = _sd_flat(len(v), v)
    o15, h15, l15, c15, ok15 = D.resample(sd, C.GRID_PER_15M)
    assert not ok15[1] and np.isnan(c15[1]) and ok15[0] and ok15[2]
    _, _, _, c1h, ok1h = D.resample(sd, C.GRID_PER_1H)
    assert not ok1h[0] and ok1h[1]
    assert not D.agg_valid(v, C.GRID_PER_DAY)[0] and D.agg_valid(v, C.GRID_PER_DAY)[1]
    H, L, sv = D.session_hl(sd)
    assert not sv[0] and np.isnan(H[0]) and sv[1]
    assert np.isnan(sd.c[4])                            # ileri/geri doldurma yok


def test_validate_rows_gecersizleri_sayar():
    t = np.array([G0, G0 + C.M5, G0 + 2 * C.M5, G0 + 3 * C.M5, G0 + 3 * C.M5, G0 + 4 * C.M5 + 7, G0 // 1000,
                  G0 + 6 * C.M5, G0 + 6 * C.M5], dtype="int64")
    o = np.array([100, 100, 100, 100, 100, 100, 100, 100, 100.0])
    h = np.array([101, 101, 99, 101, 101, 101, 101, 101, 101.0])   # 3. satır: high < open
    l = np.array([99, 99, 98, 99, 99, 99, 99, 99, 99.0])
    c = np.array([100, 100, 98.5, 100, 100.5, 100, 100, 100, 100.0])
    v = np.array([1, 1, 1, 1, 1, 1, 1, 1, 1.0])
    raw = dict(t=t, o=o, h=h, l=l, c=c, v=v)
    keep, q = D.validate_rows(raw)
    assert q["ohlc_inconsistent"] == 1
    assert q["off_grid"] == 2                            # +7 ms ve saniye birimli satır
    assert q["out_of_range_time"] == 1                   # saniye birimli damga (ms değil) → reddedilir
    assert q["conflicting_timestamps"] == 1              # aynı damga farklı kapanış
    assert q["duplicate_exact"] == 1                     # birebir aynı satır tekilleştirilir
    assert list(keep) == [True, True, False, False, False, False, False, True, False]


@pytest.mark.parametrize("unit,mul", [("s", 10**-3), ("ms", 1), ("us", 10**3), ("ns", 10**6)])
def test_pandas_birimleri_ayni_ana_doner(unit, mul):
    ms = G0 + 13 * C.H1
    raw = int(ms * mul) if mul >= 1 else ms // 1000
    ts = pd.to_datetime(raw, unit=unit, utc=True)
    assert int(ts.value // 10**6) == ms


def test_partition_tarihleri():
    U = sentetik_evren(n_days=120)
    d = D.partition_dates(U)
    n = (d["T1"] - d["T0"]) // C.DAY
    assert d["B1"] == d["T0"] + int(np.floor(0.6 * n)) * C.DAY
    assert d["B2"] == d["T0"] + int(np.floor(0.8 * n)) * C.DAY
    assert d["T0"] % C.DAY == 0 and d["T1"] % C.DAY == 0
    # ısınma: 1000 tam 1H bar = 41g16s → sonraki UTC gün başı
    assert d["T0"] == G0 + 42 * C.DAY


# ── F1 ────────────────────────────────────────────────────────────────────────
def test_f1_yalniz_tamamlanmis_1h_bar_ve_f0_etkilenmez():
    U = sentetik_evren(n_days=40)
    sd = U["symbols"]["AAA"]
    dv = Derived(sd)
    t = G0 + 30 * C.DAY + 13 * C.H1 + 15 * C.MIN            # 13:15 sinyali → son tam 1H bar 12:00–13:00
    ok1, r1 = SU.f1_check(dv, True, t)
    h = (t - G0) // C.H1 - 1
    exp = dv.c1h[h] > dv.ema1h[h] and dv.ema1h[h] > dv.ema1h[h - 3]
    assert ok1 == bool(exp)
    # 13:00–14:00 barının (henüz kapanmamış) verisini değiştirmek 13:15 kararını değiştirmez
    k = (G0 + 30 * C.DAY + 13 * C.H1 - G0) // C.M5
    sd.c[k:k + 12] *= 1.5
    dv2 = Derived(sd)
    assert SU.f1_check(dv2, True, t) == (ok1, r1)


# ── bootstrap / hafta ataması ─────────────────────────────────────────────────
def test_hafta_pazartesi_ve_bar_ici_cikis_onceki_haftaya():
    mon = 1_672_617_600_000                                  # 2023-01-02 Pazartesi
    assert MT.week_start(mon) == mon and MT.week_start(mon - 1) == mon - 7 * C.DAY
    tr = pd.DataFrame(dict(exit_interval_start=[mon - C.M5, mon], net_R=[1.0, -1.0]))
    weeks, S, N = MT.weekly_SN(tr, mon - 7 * C.DAY, mon + 7 * C.DAY)
    assert weeks == [mon - 7 * C.DAY, mon]
    assert list(S) == [1.0, -1.0] and list(N) == [1, 1]


def test_tam_hafta_disi_islem_bootstrapa_girmez():
    mon = 1_672_617_600_000
    tr = pd.DataFrame(dict(exit_interval_start=[mon - C.DAY], net_R=[5.0]))   # bölüm Pazar başlıyor
    weeks, S, N = MT.weekly_SN(tr, mon - C.DAY, mon + 14 * C.DAY)
    assert weeks == [mon, mon + 7 * C.DAY] and S.sum() == 0


def test_bootstrap_oran_tahmincisi_belirleyici_bos_hafta():
    S = np.array([2.0, 0.0, -1.0, 0.0] * 10)
    N = np.array([2, 0, 1, 0] * 10, dtype=float)
    a = MT.block_bootstrap(S, N)
    b = MT.block_bootstrap(S, N)
    assert a == b
    assert a["ci"][0] <= S.sum() / N.sum() <= a["ci"][1]
    z = MT.block_bootstrap(np.zeros(8), np.zeros(8))
    assert z["invalid_frac"] == 1.0 and not z["reliable"]


def test_mdd_tepe_C0_icerir():
    eq_t = np.arange(3) * C.M5
    mdd, uw, uw_open = MT.mdd_and_underwater(eq_t, np.array([9_900.0, 9_800.0, 9_950.0]), 10_000.0)
    assert mdd == pytest.approx(2.0)
    assert uw_open > 0


def test_pf_zarar_yoksa_sayi_degil():
    assert MT.pf([1.0, 2.0]) == "INF"
    assert MT.pf([]) == "NA"
    assert MT.pf([2.0, -1.0]) == pytest.approx(2.0)


# ── seçim ve karar önceliği ───────────────────────────────────────────────────
def _m(exp=0.1, net=100.0, lcb=0.05, mdd=5.0, closed=200, wkt=30, wk=60, valid=True):
    return dict(expectancy_net_R=exp, net_USDT=net, LCB=lcb, MDD_close_pct=mdd, closed=closed,
                weeks_with_trades=wkt, full_weeks=wk, metrics_valid=valid, data_gap_exposure=False,
                funding_order_ambiguous=False, boot_reliable=True)


def test_siralama_anahtari():
    res = {"B": (_m(lcb=0.1), _m(lcb=0.0)), "A": (_m(lcb=0.1), _m(lcb=0.0)), "C": (_m(lcb=0.2), _m(lcb=-1)),
           "D": (_m(lcb=0.1, mdd=1.0), _m(lcb=0.0)), "E": (_m(lcb=0.1), _m(lcb=0.05))}
    sel, rows = SL.select(res, "DISCOVERY")
    assert sel == ["C", "E", "D"]                       # LCB↓, STRESS LCB↓, MDD↑, id
    res2 = {"A": (_m(lcb=0.1), _m(lcb=0.0)), "B": (_m(lcb=0.1), _m(lcb=0.0))}
    assert SL.select(res2, "DISCOVERY")[0] == ["A", "B"]


def test_karar_onceligi():
    assert SL.stage_status(_m(valid=False), _m(), "DISCOVERY", False)[1] == SL.YETERSIZ
    assert SL.stage_status(_m(closed=10), _m(), "DISCOVERY", False)[1] == SL.YETERSIZ
    assert SL.stage_status(_m(), _m(exp=-0.01), "DISCOVERY", False)[1] == SL.ELENDI
    assert SL.stage_status(_m(net=-1), _m(), "DISCOVERY", False)[1] == SL.ELENDI
    assert SL.stage_status(_m(lcb=-0.1), _m(), "DISCOVERY", False)[0] is True       # keşifte LCB şart değil
    assert SL.stage_status(_m(lcb=-0.1), _m(), "VALIDATION", True)[1] == SL.YETERSIZ
    assert SL.final_decision(_m(closed=40, wkt=10, wk=20), _m(closed=40, wkt=10, wk=20), 50.0, False)[0] == SL.YETERSIZ
    assert SL.final_decision(_m(closed=40, wkt=10, wk=20), _m(closed=40, wkt=10, wk=20), -5.0, True)[0] == SL.YETERSIZ
    assert SL.final_decision(_m(closed=40, wkt=10, wk=20), _m(closed=40, wkt=10, wk=20), 5.0, True)[0] == SL.ADAY


def test_genel_karar_finalsiz():
    rows = [dict(status=SL.ELENDI, reason="NOT_POSITIVE")] * 3
    assert SL.overall_without_final(rows, [])[0] == SL.ELENDI
    assert SL.overall_without_final(rows + [dict(status=SL.YETERSIZ, reason="SAMPLE_FLOOR_POSITIVE")], [])[0] == SL.YETERSIZ
    assert SL.overall_without_final(rows, [dict(status=SL.YETERSIZ, reason="LCB_NOT_POSITIVE")])[0] == SL.YETERSIZ


# ── No.35: veri kesimi / gelecek değişikliği ──────────────────────────────────
def test_no35_gelecek_degisince_kesim_oncesi_ayni():
    U1 = sentetik_evren(n_days=90, seed=3)
    U2 = sentetik_evren(n_days=90, seed=3)
    X = G0 + 70 * C.DAY + 7 * C.H1 + 35 * C.MIN
    kx = (X - G0) // C.M5
    for sd in U2["symbols"].values():
        for arr in (sd.o, sd.h, sd.l, sd.c):
            arr[kx:] *= 1.07
    W1, W2 = cli.World(universe=U1), cli.World(universe=U2)
    for fam in C.LEVEL_FAMILIES:
        for s in U1["symbols"]:
            e1 = [e for e in W1.events[fam][s] if e.sweep_close <= X]
            e2 = [e for e in W2.events[fam][s] if e.sweep_close <= X]
            assert [e.market_event_id for e in e1] == [e.market_event_id for e in e2]
    for vid in ("L1_K1_F0", "L3_K2_F1", "L2_K3_F0", "L3_K4_F0"):
        r1, s1 = W1.signals(vid, "DISCOVERY")
        r2, s2 = W2.signals(vid, "DISCOVERY")
        a = [(r.market_event_id, r.terminal_status, r.S, r.T) for r in r1 if r.terminal_time < X]
        b = [(r.market_event_id, r.terminal_status, r.S, r.T) for r in r2 if r.terminal_time < X]
        assert a == b
        _, x1 = cli.run_variant(W1, vid, "DISCOVERY", C.TWIN_MARKET_PROFILE, 10_000.0)
        _, x2 = cli.run_variant(W2, vid, "DISCOVERY", C.TWIN_MARKET_PROFILE, 10_000.0)
        q1 = [t for t in x1.trades if t["exit_interval_end"] < X]
        q2 = [t for t in x2.trades if t["exit_interval_end"] < X]
        assert q1 == q2
        assert [e for e in x1.equity if e[0] < X] == [e for e in x2.equity if e[0] < X]


# ── final seçim dosyası / hash koruması ───────────────────────────────────────
def test_final_secim_dosyasi_yoksa_reddedilir(tmp_path, monkeypatch):
    man = dict(source_hashes=cli.code_hashes(),
               config_hash=cli.sha_bytes(json.dumps(cli.config_dict(), sort_keys=True, default=str).encode()),
               data_hashes={}, manifest_hash="h", dates_ms={})
    (tmp_path / "experiment_manifest.json").write_text(json.dumps(man))

    class A:
        run = str(tmp_path)
        data = "yok"
    with pytest.raises(SystemExit, match="selection_final.json yok"):
        cli.cmd_final(A)


def test_hash_degisince_devam_reddedilir(tmp_path):
    f = tmp_path / "veri.bin"
    f.write_bytes(b"abc")
    man = dict(source_hashes=cli.code_hashes(),
               config_hash=cli.sha_bytes(json.dumps(cli.config_dict(), sort_keys=True, default=str).encode()),
               data_hashes={str(f): D.sha256_file(str(f))}, manifest_hash="h", dates_ms={})
    (tmp_path / "experiment_manifest.json").write_text(json.dumps(man))
    cli.load_manifest(str(tmp_path))
    f.write_bytes(b"abd")
    with pytest.raises(SystemExit, match="VERİ HASH"):
        cli.load_manifest(str(tmp_path))
    man["source_hashes"] = {"x.py": "0"}
    (tmp_path / "experiment_manifest.json").write_text(json.dumps(man))
    with pytest.raises(SystemExit, match="KOD/KONFİG"):
        cli.load_manifest(str(tmp_path))
