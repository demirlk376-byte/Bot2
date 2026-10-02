"""
Bağımsız şartname testleri (SWEEP_V1_2026-10-01):
  §3   veri sözleşmesi — üst TF agregası (No.4 analoğu), satır denetimi, birim, tarih bölmesi
  §11  F1 yalnız son TAMAMLANMIŞ 1H barı kullanır; F0 trendden etkilenmez
  §18  haftalık blok bootstrap, seçim sıralaması, karar önceliği
  §19  MDD tepesi C0'ı içerir; zarar yoksa PF etiketlenir
  §21 No.35  veri kesimi / gelecek fiyat değişikliği → kesim öncesi her şey aynı

Beklenen sayılar şartnameden ELLE türetilmiştir; üretim fonksiyonu çağrılarak hesaplanmamıştır.
Yön içeren her fixture için fiyat yansıtmalı (high/low rolleri değişen) kısa ayna da vardır.
"""
from __future__ import annotations

import copy
import types

import numpy as np
import pandas as pd
import pytest

from research.liquidity_sweep_v1 import (cli, config as C, data_contract as D, events as EV, levels as LV,
                                         metrics as MT, replay_adapter as RA, selection as SL, setups as SU)
from research.liquidity_sweep_v1.tests.sentetik import sentetik_evren

# ── sabit zaman birimleri (ms) — config'ten bağımsız ─────────────────────────
M5 = 300_000
M15 = 900_000
H1 = 3_600_000
DAY = 86_400_000
WEEK = 7 * DAY
G0 = 1_672_531_200_000           # 2023-01-01 00:00 UTC (Pazar)

ZERO_COST = C.CostProfile(name="ZERO", entry_fee_rate=0.0, exit_fee_rate=0.0, entry_slip_bp=0.0,
                          exit_slip_bp=0.0, source="test")
C0 = 10_000.0
FAMS = ("L1", "L2", "L3", "L4")
KS = ("K1", "K2", "K3", "K4")


# ═════════════════════════════ yardımcılar ══════════════════════════════════
def _flat(n, p=100.0, half=0.05):
    return np.full(n, p), np.full(n, p + half), np.full(n, p - half), np.full(n, p)


def _sd(o, h, l, c, valid=None, symbol="AAA", g0=G0, v=None, tick=0.01):
    o, h, l, c = (np.array(x, dtype=float) for x in (o, h, l, c))
    n = len(c)
    valid = np.ones(n, bool) if valid is None else np.array(valid, dtype=bool)
    vol = np.ones(n) if v is None else np.array(v, dtype=float)
    o, h, l, c, vol = (np.where(valid, x, np.nan) for x in (o, h, l, c, vol))
    return D.SymbolData(symbol=symbol, source="TEST", g0=g0, o=o, h=h, l=l, c=c, v=vol, valid5=valid,
                        tick=tick, contract_size=1.0, vol_unit=0.1, min_vol=0.1, meta_source="test")


def _reflect(o, h, l, c, K):
    """x → K − x (pozitif kalacak K ile); yeni high = K − low, yeni low = K − high."""
    r = lambda x: np.round(K - np.asarray(x, dtype=float), 2)
    return r(o), r(l), r(h), r(c)


def _clone(U):
    U2 = dict(U)
    U2["symbols"] = {s: copy.deepcopy(sd) for s, sd in U["symbols"].items()}
    return U2


def _rec(mid, symbol, side, t_sig, E, S, T, f1=True):
    """Nihai sinyal kaydı (sonraki kuralı izole eden fixture; şartname §21 buna izin verir)."""
    return SU.SetupRecord(variant_base="L1_K1", market_event_id=mid, symbol=symbol, side=side,
                          level_id=f"lv-{mid}", level_known_at=t_sig - DAY, level_expires_at=t_sig + DAY,
                          sweep_open=t_sig - M15, sweep_close=t_sig, ATR15_frozen=1.0,
                          terminal_status="SIGNAL", terminal_time=t_sig, signal_time=t_sig, E_plan=E,
                          S_raw=S, S=S, T_raw=T, T=T, F1_pass=f1, F1_reason="" if f1 else "TREND_REJECTED")


def _isnan(x):
    return isinstance(x, float) and x != x


# ═══════════════ §3.3 — üst TF agregası, No.4 analoğu, doldurma yok ═════════
@pytest.mark.parametrize("mirror", [False, True], ids=["long_fiyat", "kisa_ayna"])
def test_no4_analogu_15m_1h_gun_eksik_alt_bar_gecersiz_ve_doldurulmaz(mirror):
    n = 288
    o, h, l, c = _flat(n)
    bars = {9: (100.00, 100.40, 99.90, 100.30), 10: (100.30, 100.80, 100.20, 100.70),
            11: (100.70, 100.75, 100.10, 100.20), 12: (100.20, 100.50, 100.00, 100.40),
            13: (100.40, 100.95, 100.35, 100.60), 14: (100.60, 101.00, 100.50, 100.90),
            15: (100.90, 101.20, 100.80, 101.10), 16: (101.10, 101.30, 100.95, 101.00),
            17: (101.00, 101.05, 100.60, 100.65)}
    for k, row in bars.items():
        o[k], h[k], l[k], c[k] = row
    if mirror:
        o, h, l, c = _reflect(o, h, l, c, 200.0)
    valid = np.ones(n, bool)
    valid[13] = False                                   # 01:05 5m barı hiç gelmedi
    sd = _sd(o, h, l, c, valid)
    o15, h15, l15, c15, v15 = D.resample(sd, 3)
    o1h, h1h, l1h, c1h, v1h = D.resample(sd, 12)
    if not mirror:
        exp_j3, exp_j5, exp_h0 = (100.00, 100.80, 99.90, 100.20), (100.90, 101.30, 100.60, 100.65), \
            (100.00, 100.80, 99.90, 100.20)
    else:
        exp_j3, exp_j5, exp_h0 = (100.00, 100.10, 99.20, 99.80), (99.10, 99.40, 98.70, 99.35), \
            (100.00, 100.10, 99.20, 99.80)
    # 15m: üç tam 5m alt bar gerekir
    assert len(o15) == 96 and v15[3] and v15[5] and not v15[4]
    assert (o15[3], h15[3], l15[3], c15[3]) == pytest.approx(exp_j3)
    assert (o15[5], h15[5], l15[5], c15[5]) == pytest.approx(exp_j5)
    assert all(np.isnan(x[4]) for x in (o15, h15, l15, c15))     # iki alt bardan kısmi bar üretilmez
    # 1H: on iki tam alt bar gerekir
    assert v1h[0] and not v1h[1] and v1h[2]
    assert (o1h[0], h1h[0], l1h[0], c1h[0]) == pytest.approx(exp_h0)
    assert all(np.isnan(x[1]) for x in (o1h, h1h, l1h, c1h))
    assert (o1h[2], h1h[2], l1h[2], c1h[2]) == pytest.approx((100.00, 100.05, 99.95, 100.00))
    # gün: 288 tam bar gerekir
    dv = LV.Derived(sd)
    assert len(dv.day_h) == 1 and np.isnan(dv.day_h[0]) and np.isnan(dv.day_l[0])
    assert np.isnan(dv.c15[4]) and np.isnan(dv.c1h[1])
    # 5m eksik bar ileri/geri doldurulmaz; sentetik sıfır hacimli bar yapılmaz
    assert not sd.valid5[13]
    assert all(np.isnan(x[13]) for x in (sd.o, sd.h, sd.l, sd.c, sd.v))


@pytest.mark.parametrize("mirror", [False, True], ids=["long_fiyat", "kisa_ayna"])
def test_gun_288_seans_96_tam_bar_eksikse_seviye_yok(mirror):
    n = 4 * 288
    o, h, l, c = _flat(n)
    h[120], l[180] = 103.00, 98.00                      # gün 0: 10:00 tepe, 15:00 dip
    h[288 + 36], l[288 + 60] = 102.50, 98.20            # gün 1 seans içi (03:00, 05:00)
    h[288 + 144] = 104.00                               # gün 1 12:00 — seans dışı
    if mirror:
        o, h, l, c = _reflect(o, h, l, c, 200.0)
    valid = np.ones(n, bool)
    valid[288 + 108] = False                            # gün 1 09:00 yok → gün geçersiz, seans geçerli
    valid[576 + 95] = False                             # gün 2 07:55 yok → seans ve gün geçersiz
    sd = _sd(o, h, l, c, valid)
    H, L, sv = D.session_hl(sd)
    dv = LV.Derived(sd)
    d0 = (103.00, 98.00) if not mirror else (102.00, 97.00)
    s1 = (102.50, 98.20) if not mirror else (101.80, 97.50)
    assert list(sv) == [True, True, False, True]
    assert (H[0], L[0]) == pytest.approx((100.05, 99.95)) and (H[1], L[1]) == pytest.approx(s1)
    assert np.isnan(H[2]) and np.isnan(L[2]) and (H[3], L[3]) == pytest.approx((100.05, 99.95))
    assert (dv.day_h[0], dv.day_l[0]) == pytest.approx(d0)
    assert np.isnan(dv.day_h[1]) and np.isnan(dv.day_h[2]) and np.isnan(dv.day_l[1]) and np.isnan(dv.day_l[2])
    assert (dv.day_h[3], dv.day_l[3]) == pytest.approx((100.05, 99.95))
    # L1: yalnız gün 1 (tam gün 0'dan); gün 2 ve 3 için önceki gün eksik → L1 yok
    b1 = LV.LevelBook("L1", dv)
    got = sorted((lv.side, lv.price, lv.known_at, lv.expires_at) for lv in b1.levels)
    assert got == [("HIGH", pytest.approx(d0[0]), G0 + DAY, G0 + 2 * DAY),
                   ("LOW", pytest.approx(d0[1]), G0 + DAY, G0 + 2 * DAY)]
    assert b1.reference("HIGH", G0 + 2 * DAY + 9 * H1) is None
    assert b1.reference("LOW", G0 + 3 * DAY + 9 * H1) is None
    # L2: seansı tam olan günler 0, 1, 3; gün 2 seansı eksik → seviye yok
    b2 = LV.LevelBook("L2", dv)
    assert sorted({lv.known_at for lv in b2.levels}) == [G0 + 8 * H1, G0 + DAY + 8 * H1, G0 + 3 * DAY + 8 * H1]
    ref = b2.reference("LOW", G0 + DAY + 9 * H1)
    assert ref is not None and ref.price == pytest.approx(s1[1])
    assert b2.reference("HIGH", G0 + DAY + 9 * H1).price == pytest.approx(s1[0])   # 104 seans dışıydı
    assert b2.reference("LOW", G0 + 2 * DAY + 9 * H1) is None


def test_bitmemis_son_ust_tf_bari_uretilmez():
    sd = _sd(*_flat(288 + 2))                           # gün 1'in yalnız 00:00 ve 00:05 barları var
    assert len(D.resample(sd, 3)[0]) == 96
    assert len(D.resample(sd, 12)[0]) == 24
    dv = LV.Derived(sd)
    # kısmi gün 1 için bir gün/seans barı ÜRETİLMEZ (değer yok); kısmi gün yalnız L1'in bilinmesi için
    # dizide yer tutar (No.35 gün ortası kesim düzeltmesi)
    assert np.isfinite(dv.day_h[0]) and all(np.isnan(dv.day_h[1:]))
    assert np.isfinite(dv.sess_h[0]) and all(np.isnan(dv.sess_h[1:]))


def test_izgaraya_yerlestirme_bosluk_nan_sifir_hacim_gecerli():
    t = np.array([G0, G0 + M5, G0 + 3 * M5, G0 + 4 * M5, G0 + 5 * M5], dtype="int64")   # k=2 hiç yok
    raw = dict(t=t, o=np.array([100.0, 100.1, 100.2, 100.3, 100.4]), h=np.array([100.2, 100.3, 100.4, 100.5, 100.6]),
               l=np.array([99.9, 100.0, 100.1, 100.2, 100.3]), c=np.array([100.1, 100.2, 100.3, 100.4, 100.5]),
               v=np.array([5.0, 6.0, 0.0, 7.0, 8.0]))                                    # k=3 gerçek sıfır hacim
    keep, q = D.validate_rows(raw)
    assert keep.all()
    arrs, valid = D.to_grid(raw, keep, G0, 6)
    assert list(valid) == [True, True, False, True, True, True]
    assert all(np.isnan(arrs[f][2]) for f in ("o", "h", "l", "c", "v"))      # 0 değil, önceki değer değil
    assert arrs["v"][3] == 0.0 and arrs["c"][3] == pytest.approx(100.3)
    sd = D.SymbolData(symbol="AAA", source="T", g0=G0, o=arrs["o"], h=arrs["h"], l=arrs["l"], c=arrs["c"],
                      v=arrs["v"], valid5=valid, tick=0.01, contract_size=1.0, vol_unit=1.0, min_vol=1.0,
                      meta_source="t")
    o15, h15, l15, c15, v15 = D.resample(sd, 3)
    assert list(v15) == [False, True]                  # sıfır hacimli gerçek bar 15m'yi geçersiz yapmaz
    assert (o15[1], h15[1], l15[1], c15[1]) == pytest.approx((100.2, 100.6, 100.1, 100.5))


# ═══════════════ §3.3 — satır denetimi ══════════════════════════════════════
@pytest.mark.parametrize("mirror", [False, True], ids=["long_fiyat", "kisa_ayna"])
def test_validate_rows_ohlc_tutarsizligini_reddeder_sinir_esitligi_gecerli(mirror):
    rows = [(100.0, 100.5, 99.5, 100.2),     # geçerli
            (100.0, 100.5, 99.5, 100.6),     # close > high
            (100.0, 100.5, 100.1, 100.3),    # low > open
            (100.0, 99.0, 101.0, 100.0),     # high < low
            (100.0, 100.5, 100.0, 100.5)]    # low = open, high = close → geçerli (<=)
    o, h, l, c = (np.array(x) for x in zip(*rows))
    if mirror:
        o, h, l, c = _reflect(o, h, l, c, 200.0)
    t = np.array([G0 + i * M5 for i in range(5)], dtype="int64")
    keep, q = D.validate_rows(dict(t=t, o=o, h=h, l=l, c=c, v=np.ones(5)))
    assert list(keep) == [True, False, False, False, True]
    assert q["ohlc_inconsistent"] == 3


def test_validate_rows_yinelenen_cakisan_izgara_disi_birim_hatasi():
    base = (100.2, 100.6, 99.9, 100.4)
    spec = [  # (t, o, h, l, c, v)
        (G0, 100.0, 100.5, 99.5, 100.2, 10.0),                    # 0 geçerli
        (G0 + 5 * M5, *base, 7.0),                                # 1 } birebir aynı → biri kalır
        (G0 + 5 * M5, *base, 7.0),                                # 2 }
        (G0 + 6 * M5, *base, 7.0),                                # 3 } aynı damga, farklı close → ikisi de yok
        (G0 + 6 * M5, 100.2, 100.6, 99.9, 100.5, 7.0),            # 4 }
        (G0 + 7 * M5 + 7, *base, 7.0),                            # 5 ızgara dışı (+7 ms)
        (G0 + 8 * M5 + 60_000, *base, 7.0),                       # 6 ızgara dışı (1 dk kayık)
        (1_672_500_000, *base, 7.0),                              # 7 SANİYE birimi (ms ızgarasına oturuyor)
        ((G0 + 9 * M5) * 1_000, *base, 7.0),                      # 8 MİKROSANİYE birimi
        ((G0 + 10 * M5) * 1_000_000, *base, 7.0),                 # 9 NANOSANİYE birimi
        (G0 + 11 * M5, 100.0, 100.1, 99.9, 100.0, 0.0),           # 10 gerçek sıfır hacim → geçerli
        (G0 + 12 * M5, *base, -1.0),                              # 11 negatif hacim
        (G0 + 13 * M5, 100.0, 100.5, 0.0, 100.2, 1.0),            # 12 sıfır fiyat
        (G0 + 14 * M5, 100.0, np.nan, 99.5, 100.2, 1.0),          # 13 NaN high
        (G0 + 15 * M5, 100.0, 100.5, 99.5, np.inf, 1.0),          # 14 sonsuz close
        (G0 + 16 * M5, 100.0, 100.5, 99.5, 100.2, np.nan),        # 15 hacim sonlu değil
    ]
    t, o, h, l, c, v = (np.array(x) for x in zip(*spec))
    raw = dict(t=t.astype("int64"), o=o.astype(float), h=h.astype(float), l=l.astype(float),
               c=c.astype(float), v=v.astype(float))
    keep, q = D.validate_rows(raw)
    assert keep[0] and keep[10]
    assert int(keep[1]) + int(keep[2]) == 1                        # tekilleştirildi, atılmadı
    assert not keep[3] and not keep[4]                             # çatışma çözülmeden kullanılamaz
    assert not any(keep[5:10]) and not any(keep[11:])
    assert int(keep.sum()) == 3
    assert q["duplicate_exact"] == 1 and q["conflicting_timestamps"] == 1
    assert q["off_grid"] == 2 and q["out_of_range_time"] == 3
    assert q["negative_volume"] == 1 and q["non_positive"] == 1 and q["non_finite"] == 3
    # ızgarada: yalnız k = 0, 5, 11 geçerli; çatışan k=6'ya iki satırdan biri seçilmez
    arrs, valid = D.to_grid(raw, keep, G0, 17)
    assert list(np.flatnonzero(valid)) == [0, 5, 11]
    assert arrs["c"][5] == pytest.approx(100.4) and np.isnan(arrs["c"][6])


def test_validate_rows_aynisi_ve_catisani_olan_damga_tamamen_kullanilmaz():
    row_a = (100.2, 100.6, 99.9, 100.4, 7.0)
    row_b = (100.2, 100.6, 99.9, 100.4, 8.0)                       # yalnız hacim farklı → yine çatışma
    t = np.array([G0, G0, G0, G0 + M5], dtype="int64")
    o, h, l, c, v = (np.array(x, dtype=float) for x in zip(row_a, row_a, row_b, row_a))
    keep, q = D.validate_rows(dict(t=t, o=o, h=h, l=l, c=c, v=v))
    assert list(keep) == [False, False, False, True]
    assert q["conflicting_timestamps"] == 1


def _write_npz(path, rows):
    t, o, h, l, c, v = (np.array(x) for x in zip(*rows))
    np.savez(path, open_time_ms=t.astype("int64"), open=o.astype(float), high=h.astype(float),
             low=l.astype(float), close=c.astype(float), volume=v.astype(float))


def test_build_universe_tek_kaynak_metadata_eksigi_dislanir_cakisma_izgarada_nan(tmp_path):
    import json
    (tmp_path / "binance_5m").mkdir()
    rows = [(G0 + k * M5, 100.0, 100.1, 99.9, 100.0, 1.0) for k in range(2 * 288)]
    rows = [r for r in rows if r[0] != G0 + 30 * M5]                       # k=30 hiç gelmedi
    rows += [(G0 + 10 * M5, 100.0, 100.1, 99.9, 100.0, 1.0),               # k=10 birebir aynı → tekil
             (G0 + 20 * M5, 100.0, 100.1, 99.9, 100.05, 1.0),              # k=20 çatışan close
             (G0 + 40 * M5 + 7, 100.0, 100.1, 99.9, 100.0, 1.0)]           # ızgara dışı
    _write_npz(tmp_path / "binance_5m" / "AAA.npz", rows)
    _write_npz(tmp_path / "binance_5m" / "BBB.npz", [(G0 + k * M5, 50.0, 50.1, 49.9, 50.0, 1.0)
                                                      for k in range(2 * 288)])
    (tmp_path / "indirme_ozeti.json").write_text(json.dumps({"olusturma": "2023-01-03T10:00:00+00:00"}))
    (tmp_path / "mexc_contract_detail.json").write_text(json.dumps(
        {"AAA": {"priceUnit": 0.01, "contractSize": 1, "volUnit": 1, "minVol": 1}}))
    U = D.build_universe(str(tmp_path), ["AAA", "BBB", "CCC"])
    assert U["source"] == "binance_5m"                                     # MEXC tam değil → evrenin tamamı tek kaynak
    assert set(U["symbols"]) == {"AAA"}
    assert U["excluded"]["BBB"].startswith("METADATA_MISSING")              # performansla değil veriyle dışlandı
    assert U["excluded"]["CCC"].startswith("DATA_MISSING")
    sd = U["symbols"]["AAA"]
    assert sd.g0 == G0 and sd.source == "binance_5m"
    assert not sd.valid5[20] and np.isnan(sd.c[20])                        # çatışma çözülmeden kullanılmadı
    assert not sd.valid5[30] and np.isnan(sd.c[30]) and np.isnan(sd.v[30])
    assert sd.valid5[10] and sd.valid5[40]
    assert int(sd.valid5.sum()) == 2 * 288 - 2
    assert sd.quality["conflicting_timestamps"] == 1 and sd.quality["duplicate_exact"] == 1
    assert sd.quality["off_grid"] == 1
    assert sd.funding_source == "NOT_MODELED" and len(sd.funding_t) == 0   # funding sıfırla doldurulmaz


# ═══════════════ §3.3 / §21 ek test — pandas s/ms/us/ns birimleri ══════════
def _epoch_ms(idx) -> np.ndarray:
    """Fixture yardımcısı: tz-aware UTC DatetimeIndex → epoch ms. Birim indeksin dtype'ından gelir;
    sayının büyüklüğüne bakılarak tahmin YAPILMAZ."""
    idx = pd.DatetimeIndex(idx)
    if idx.tz is None or str(idx.tz) != "UTC":
        raise ValueError("timezone-aware UTC indeks gerekli")
    return np.asarray(idx.as_unit("ms").asi8, dtype="int64")


_BASE_MS = np.array([1_672_578_000_000 + i * M5 for i in range(6)], dtype="int64")   # 2023-01-01 13:00..13:25
_MUL = {"s": None, "ms": 1, "us": 1_000, "ns": 1_000_000}


def _ints_in_unit(unit):
    return _BASE_MS // 1_000 if unit == "s" else _BASE_MS * _MUL[unit]


@pytest.mark.parametrize("unit", ["s", "ms", "us", "ns"])
def test_pandas_birim_indeksleri_ayni_ana_ve_ayni_izgara_hucresine_doner(unit, tmp_path):
    idx_a = pd.DatetimeIndex(_BASE_MS.astype("datetime64[ms]").astype(f"datetime64[{unit}]")).tz_localize("UTC")
    idx_b = pd.to_datetime(_ints_in_unit(unit), unit=unit, utc=True)
    assert idx_a.unit == unit
    for idx in (idx_a, idx_b):
        ms = _epoch_ms(idx)
        assert list(ms) == [1_672_578_000_000 + i * 300_000 for i in range(6)]
        assert D.ms_to_str(int(ms[0])) == "2023-01-01 13:00:00+00:00"
    ms = _epoch_ms(idx_a)
    px = np.linspace(100.0, 100.5, 6)
    p = tmp_path / f"AAA_{unit}.npz"
    np.savez(p, open_time_ms=ms, open=px, high=px + 0.1, low=px - 0.1, close=px, volume=np.ones(6))
    raw = D.load_raw_npz(str(p))
    keep, q = D.validate_rows(raw)
    assert keep.all()
    arrs, valid = D.to_grid(raw, keep, G0, 288)
    assert list(np.flatnonzero(valid)) == [156, 157, 158, 159, 160, 161]      # 13:00 = 156. 5m bar
    assert arrs["c"][156] == pytest.approx(100.0) and arrs["c"][161] == pytest.approx(100.5)


@pytest.mark.parametrize("unit", ["s", "us", "ns"])
def test_birim_donusturulmeden_ms_sanilan_damga_sessizce_kabul_edilmez(unit):
    naive = pd.to_datetime(_ints_in_unit(unit), unit=unit, utc=True).as_unit(unit).asi8   # ms DEĞİL
    px = np.full(6, 100.0)
    keep, q = D.validate_rows(dict(t=np.asarray(naive, dtype="int64"), o=px, h=px + 0.1, l=px - 0.1, c=px,
                                   v=np.ones(6)))
    assert not keep.any()
    assert q["out_of_range_time"] == 6


# ═══════════════ §3.2 / §17 — T0, T1, B1, B2 ═══════════════════════════════
def test_partition_dates_T0_tavan_T1_ortak_son_gun_B1_B2_taban():
    n = 70 * 288
    va = np.zeros(n, bool)
    va[2 * 288 + 96:] = True                 # AAA: 2g 08:00'den sona kadar → 1000. 1H bar tam 44g 00:00'da kapanır
    vb = np.zeros(n, bool)
    vb[288 + 6: 65 * 288 + 60] = True        # BBB: 1g 00:30 → 65g 05:00 (son bar 04:55–05:00)
    U = dict(symbols={"AAA": _sd(*_flat(n), va, symbol="AAA"), "BBB": _sd(*_flat(n), vb, symbol="BBB")})
    d = D.partition_dates(U)
    # AAA ısınması tam gün sınırında → T0 o sınırın kendisidir (eşit veya sonraki ilk gün başı)
    # BBB ısınması 42g 17:00 → 43g; en geç olan 44g
    assert d["T0"] == G0 + 44 * DAY
    assert d["T1"] == G0 + 65 * DAY                     # BBB'nin bitmemiş son günü atılır
    assert d["N_days"] == 21
    assert d["B1"] == G0 + 56 * DAY                     # 44 + floor(12.6)=12 (yuvarlama 13 olurdu)
    assert d["B2"] == G0 + 60 * DAY                     # 44 + floor(16.8)=16 (yuvarlama 17 olurdu)
    assert [D.ms_to_str(d[k]) for k in ("T0", "B1", "B2", "T1")] == [
        "2023-02-14 00:00:00+00:00", "2023-02-26 00:00:00+00:00", "2023-03-02 00:00:00+00:00",
        "2023-03-07 00:00:00+00:00"]
    assert d["DISCOVERY"] == (G0 + 44 * DAY, G0 + 56 * DAY)
    assert d["VALIDATION"] == (G0 + 56 * DAY, G0 + 60 * DAY)
    assert d["FINAL"] == (G0 + 60 * DAY, G0 + 65 * DAY)


@pytest.mark.parametrize("mirror", [False, True], ids=["long", "short_ayna"])
def test_bolum_son_12_saatinde_yeni_giris_yok(mirror):
    n = 3 * 288
    U = dict(symbols={s: _sd(*_flat(n), symbol=s) for s in ("AAA", "BBB")}, g0=G0)
    side, S, T = ("LONG", 99.0, 102.0) if not mirror else ("SHORT", 101.0, 98.0)
    end = G0 + 3 * DAY
    sigs = [_rec("E-A", "AAA", side, end - 12 * H1 - M5, 100.0, S, T),      # sınırdan 5 dk önce → girer
            _rec("E-B", "BBB", side, end - 12 * H1, 100.0, S, T)]           # tam end−12s → engellenir
    res = RA.simulate("TEST", "DISCOVERY", (G0 + DAY, end), sigs, U, ZERO_COST, C0)
    st = {(o["market_event_id"], o["terminal_status"]) for o in res.outcomes}
    assert ("E-A", "FILLED") in st and ("E-B", "PARTITION_TAIL_BLOCKED") in st
    assert not any(o["market_event_id"] == "E-B" and o["terminal_status"] == "FILLED" for o in res.outcomes)
    t = res.trades[0]                                                        # 12 saat sonra, bölüm bitmeden
    assert (t["exit_reason"], t["exit_interval_start"]) == ("TIME_EXIT", end - M5)
    assert res.flags["censored_open_at_end"] == 0


@pytest.mark.parametrize("mirror", [False, True], ids=["long", "short_ayna"])
def test_bolum_basinda_bekleyen_kurulum_iptal_tasinmaz(mirror):
    # K2: ihlal barı [23:30,23:45) reclaim yapmaz, reclaim [23:45,24:00) kapanışında = bölüm sınırı
    n = 2 * 288
    o, h, l, c = _flat(n)
    for k, row in {282: (100.00, 100.05, 99.50, 99.70), 283: (99.70, 99.90, 99.60, 99.80),
                   284: (99.80, 99.85, 99.75, 99.80), 285: (99.80, 100.10, 99.75, 100.00),
                   286: (100.00, 100.30, 99.95, 100.20), 287: (100.20, 100.35, 100.15, 100.30)}.items():
        o[k], h[k], l[k], c[k] = row
    if mirror:
        o, h, l, c = _reflect(o, h, l, c, 210.0)
    dv = LV.Derived(_sd(o, h, l, c))
    P1 = G0 + DAY
    ev = EV.MarketEvent(market_event_id="K2-EV", family="L1", symbol="AAA", side="SHORT" if mirror else "LONG",
                        level_id="lv", level_price=110.0 if mirror else 100.0, level_known_at=G0,
                        level_expires_at=G0 + 2 * DAY, j15=94, sweep_open=P1 - 30 * 60_000,
                        sweep_close=P1 - M15, A=2.0, micro_ref=None)
    prev = SU.run_machine("L1", "K2", {"AAA": [ev]}, {"AAA": dv}, G0, P1)
    assert [(r.terminal_status, r.signal_time) for r in prev] == [("SIGNAL", P1)]
    assert (prev[0].S, prev[0].T) == pytest.approx((99.30, 102.30) if not mirror else (110.70, 107.70))
    assert SU.run_machine("L1", "K2", {"AAA": [ev]}, {"AAA": dv}, P1, G0 + 2 * DAY) == []   # yeni bölüme taşınmaz
    U = dict(symbols={"AAA": dv.sd}, g0=G0)
    ra = RA.simulate("TEST", "DISCOVERY", (G0 + 12 * H1, P1), prev, U, ZERO_COST, C0)
    assert ra.trades == [] and not any(o["terminal_status"] == "FILLED" for o in ra.outcomes)


def test_bolme_ve_bootstrap_sabitleri_sartname_degerleri():
    assert (C.SPLIT_1, C.SPLIT_2) == (0.60, 0.80)
    assert (C.BOOT_REPS, C.BOOT_BLOCK_WEEKS, C.BOOT_SEED, C.BOOT_INVALID_MAX) == (10_000, 4, 20261001, 0.05)
    assert C.SAMPLE_FLOORS == {"DISCOVERY": (100, 12, 26), "VALIDATION": (50, 8, 13), "FINAL": (30, 6, 13)}
    assert C.PARTITION_TAIL_MS == 12 * H1
    assert (C.WARMUP_1H, C.WARMUP_LOWER_TF) == (1000, 100)


# ═══════════════ §11 / §21 ek test — F1 yalnız tamamlanmış 1H; F0 sızıntısız ══
def _f1_sd(mirror, shock):
    p = np.array([100.0 + 0.05 * i for i in range(240)])      # düzenli yükselen saatlik fiyat
    if shock:
        p[200] = 80.0                                          # 200. saat (8. gün 08:00–09:00) çöküş
    if mirror:
        p = 300.0 - p                                          # düşen seri; şok 220'ye sıçrama
    px = np.round(np.repeat(p, 12), 2)
    return _sd(px, px, px, px)


_IN_HOUR = [G0 + 200 * H1 + m * 60_000 for m in (0, 5, 15, 30, 55)]   # son tamamlanmış 1H: 199
_AFTER = G0 + 201 * H1                                                 # 200. saat yeni kapandı


@pytest.mark.parametrize("mirror", [False, True], ids=["long", "short_ayna"])
def test_f1_kapanmamis_1h_bari_kullanmaz_kapaninca_degisir(mirror):
    with_side, against = (True, False) if not mirror else (False, True)
    dv0 = LV.Derived(_f1_sd(mirror, shock=False))
    dvs = LV.Derived(_f1_sd(mirror, shock=True))
    for tau in _IN_HOUR + [_AFTER]:
        assert SU.f1_check(dv0, with_side, tau) == (True, "")
        assert SU.f1_check(dv0, against, tau) == (False, "TREND_REJECTED")
    # şok saati henüz kapanmadıysa karar değişmez (o saatin 5m barları sinyal anında bilinse bile)
    for tau in _IN_HOUR:
        assert SU.f1_check(dvs, with_side, tau) == (True, "")
        assert SU.f1_check(dvs, against, tau) == (False, "TREND_REJECTED")
    # saat kapandığı anda h=200 kullanılır: kapanış EMA'nın ters tarafında, EMA eğimi döndü
    assert SU.f1_check(dvs, with_side, _AFTER) == (False, "TREND_REJECTED")
    assert SU.f1_check(dvs, against, _AFTER) == (True, "")


def test_f0_trendi_yok_sayar_f1_reddi_portfoye_ulasmaz():
    n = 4 * 288
    syms = {}
    for s in ("AAA", "BBB"):
        o, h, l, c = _flat(n)
        syms[s] = _sd(o, h, l, c, symbol=s)
    U = dict(symbols=syms, g0=G0, g1=G0 + 4 * DAY)
    W = cli.World(universe=U)
    t_sig = G0 + 2 * DAY + 13 * H1 + 15 * 60_000
    rej = _rec("EV-REJ", "AAA", "LONG", t_sig, 100.0, 99.0, 102.0, f1=False)
    ok = _rec("EV-OK", "BBB", "LONG", t_sig, 100.0, 99.0, 102.0, f1=True)
    W._setups[("L1", "K1", "DISCOVERY")] = [rej, ok]
    recs0, sig0 = W.signals("L1_K1_F0", "DISCOVERY")
    recs1, sig1 = W.signals("L1_K1_F1", "DISCOVERY")
    assert [r.market_event_id for r in sig0] == ["EV-REJ", "EV-OK"]
    assert [r.market_event_id for r in sig1] == ["EV-OK"]
    win = (G0 + 2 * DAY, G0 + 4 * DAY)
    r0 = RA.simulate("L1_K1_F0", "DISCOVERY", win, sig0, U, ZERO_COST, C0)
    r1 = RA.simulate("L1_K1_F1", "DISCOVERY", win, sig1, U, ZERO_COST, C0)
    assert sorted(o["market_event_id"] for o in r0.outcomes if o["terminal_status"] == "FILLED") == ["EV-OK", "EV-REJ"]
    assert [o["market_event_id"] for o in r1.outcomes if o["terminal_status"] == "FILLED"] == ["EV-OK"]
    assert all(o["market_event_id"] != "EV-REJ" for o in r1.outcomes)     # reddedilen olay sonradan denenmez
    ev1 = cli.events_frame(recs1, r1, "L1_K1_F1", "F1").set_index("market_event_id")
    assert ev1.loc["EV-REJ", "terminal_status"] == "TREND_REJECTED"


@pytest.fixture(scope="module")
def dunya7():
    U = sentetik_evren(n_days=75, seed=7)
    return U, cli.World(universe=U)


def _ref_f1_tables(U):
    """Bağımsız F1 referansı (§4 EMA200 tanımı, §11 kuralı) — üretim göstergesi kullanılmaz."""
    a = 2.0 / 201.0
    out = {}
    for s, sd in U["symbols"].items():
        c1h = sd.c[11::12][: len(sd.c) // 12]
        e = np.empty(len(c1h))
        for i, x in enumerate(c1h):
            e[i] = x if i == 0 else a * x + (1 - a) * e[i - 1]
        out[s] = (c1h, e)
    return out


def test_f1_bayragi_bagimsiz_referansla_ayni_f0_hepsini_tasir(dunya7):
    U, W = dunya7
    tab = _ref_f1_tables(U)
    seen = {("LONG", True): 0, ("LONG", False): 0, ("SHORT", True): 0, ("SHORT", False): 0}
    for fam in FAMS:
        for K in KS:
            recs = W.setups(fam, K, "DISCOVERY")
            sig = [r for r in recs if r.terminal_status == "SIGNAL"]
            ref = {}
            for r in sig:
                c1h, e = tab[r.symbol]
                h = (r.signal_time - U["g0"]) // H1 - 1
                if r.side == "LONG":
                    ref[r.market_event_id] = bool(c1h[h] > e[h] and e[h] > e[h - 3])
                else:
                    ref[r.market_event_id] = bool(c1h[h] < e[h] and e[h] < e[h - 3])
                assert bool(r.F1_pass) == ref[r.market_event_id], (fam, K, r.market_event_id)
                seen[(r.side, ref[r.market_event_id])] += 1
            f0 = W.signals(f"{fam}_{K}_F0", "DISCOVERY")[1]
            f1 = W.signals(f"{fam}_{K}_F1", "DISCOVERY")[1]
            assert [r.market_event_id for r in f0] == [r.market_event_id for r in sig]
            assert [r.market_event_id for r in f1] == [r.market_event_id for r in sig if ref[r.market_event_id]]
    assert all(v > 0 for v in seen.values()), seen        # her iki yönde hem geçen hem reddedilen var


# ═══════════════ §18.1 — haftalar ve haftaya atama ═══════════════════════════
def test_utc_haftasi_pazartesi_baslar_tam_haftalar():
    mon = G0 + DAY                                                   # 2023-01-02 Pazartesi
    assert MT.week_start(mon) == mon
    assert MT.week_start(mon - 1) == mon - WEEK                      # Pazar 23:59:59.999 önceki hafta
    assert MT.week_start(mon + 6 * DAY + 23 * H1 + 55 * 60_000) == mon
    assert MT.week_start(G0) == G0 - 6 * DAY                         # Pazar → 2022-12-26 Pazartesi
    wed, tue = G0 + 3 * DAY, G0 + 37 * DAY                           # 2023-01-04 Çar, 2023-02-07 Sal
    assert MT.full_weeks(wed, tue) == [G0 + 8 * DAY, G0 + 15 * DAY, G0 + 22 * DAY, G0 + 29 * DAY]
    assert MT.full_weeks(mon, G0 + 29 * DAY) == [mon, mon + WEEK, mon + 2 * WEEK, mon + 3 * WEEK]
    assert MT.full_weeks(mon, G0 + 28 * DAY) == [mon, mon + WEEK, mon + 2 * WEEK]


def test_weekly_SN_sinir_ve_kenar_haftalari():
    mon = G0 + 15 * DAY                                              # 2023-01-16 Pazartesi
    tr = pd.DataFrame(dict(
        exit_interval_start=[mon - M5, mon, mon, mon - 9 * DAY, mon + 7 * DAY + H1],
        exit_interval_end=[mon, mon, mon + M5, mon - 9 * DAY + M5, mon + 7 * DAY + H1 + M5],
        exit_phase=["INTRABAR", "OPEN", "INTRABAR", "INTRABAR", "INTRABAR"],
        net_R=[-1.0, 0.5, 2.0, 7.0, 3.0]))
    # bölüm: Çar 2023-01-11 → Pzt 2023-01-30; tam haftalar 16 ve 23 Ocak
    weeks, S, N = MT.weekly_SN(tr, G0 + 10 * DAY, G0 + 29 * DAY)
    assert weeks == [mon, mon + WEEK]
    # Pazar 23:55–24:00 bar içi çıkış önceki (kenar) haftaya → bootstrap dışı; 07.01 kenar, 23.01 haftası 3.0
    assert list(S) == [2.5, 3.0] and list(N) == [2, 1]
    weeks2, S2, N2 = MT.weekly_SN(tr.iloc[:0], G0 + 10 * DAY, G0 + 29 * DAY)
    assert list(S2) == [0.0, 0.0] and list(N2) == [0, 0]               # işlemsiz haftalar 0/0 olarak dahil


def _week_universe(mirror):
    n = 23 * 288
    k_sun = 14 * 288 + 287                     # 2023-01-15 23:55 (Pazar)
    k_mon = 15 * 288                           # 2023-01-16 00:00 (Pazartesi)
    out = {}
    for s in ("AAA", "BBB", "CCC"):
        o, h, l, c = _flat(n)
        if s == "AAA":                         # Pazar 23:55 barında bar içi stop
            o[k_sun], h[k_sun], l[k_sun], c[k_sun] = 100.00, 100.05, 98.80, 99.90
        elif s == "BBB":                       # Pazartesi 00:00 açılışı stopun altında
            o[k_mon:], h[k_mon:], l[k_mon:], c[k_mon:] = 98.50, 98.60, 98.40, 98.50
        else:                                  # Pazartesi 00:00–00:05 barında bar içi stop
            o[k_mon], h[k_mon], l[k_mon], c[k_mon] = 100.00, 100.05, 98.90, 99.10
        if mirror:
            o, h, l, c = _reflect(o, h, l, c, 200.0)
        out[s] = _sd(o, h, l, c, symbol=s)
    return dict(symbols=out, g0=G0)


@pytest.mark.parametrize("mirror", [False, True], ids=["long", "short_ayna"])
def test_pazar_2355_bar_ici_cikis_onceki_haftaya_pazartesi_acilisi_yeni_haftaya(mirror):
    U = _week_universe(mirror)
    side, S, T = ("LONG", 99.0, 102.0) if not mirror else ("SHORT", 101.0, 98.0)
    sun = G0 + 14 * DAY
    sigs = [_rec("E-AAA", "AAA", side, sun + 20 * H1, 100.0, S, T),
            _rec("E-BBB", "BBB", side, sun + 21 * H1, 100.0, S, T),
            _rec("E-CCC", "CCC", side, sun + 22 * H1, 100.0, S, T)]
    win = (G0 + 8 * DAY, G0 + 22 * DAY)                              # Pzt 9 Ocak → Pzt 23 Ocak
    res = RA.simulate("TEST", "DISCOVERY", win, sigs, U, ZERO_COST, C0)
    tr = {t["symbol"]: t for t in res.trades}
    assert sorted(tr) == ["AAA", "BBB", "CCC"]
    mon = G0 + 15 * DAY
    exp = {"AAA": ("INTRABAR", mon - M5, mon, 99.00 if not mirror else 101.00, -1.0, -25.0),
           "BBB": ("OPEN", mon, mon, 98.50 if not mirror else 101.50, -1.5, -37.5),
           "CCC": ("INTRABAR", mon, mon + M5, 99.00 if not mirror else 101.00, -1.0, -25.0)}
    for s, (ph, a, b, xref, nr, npnl) in exp.items():
        t = tr[s]
        assert t["exit_reason"] == "STOP" and t["exit_phase"] == ph
        assert (t["exit_interval_start"], t["exit_interval_end"]) == (a, b)
        assert t["X_reference"] == pytest.approx(xref) and t["E_fill"] == pytest.approx(100.0)
        assert t["net_R"] == pytest.approx(nr) and t["net_PnL"] == pytest.approx(npnl)
    weeks, Sw, Nw = MT.weekly_SN(pd.DataFrame(res.trades), *win)
    assert weeks == [G0 + 8 * DAY, G0 + 15 * DAY]
    assert list(Sw) == pytest.approx([-1.0, -2.5]) and list(Nw) == [1, 2]


# ═══════════════ §18.1 — blok bootstrap ═════════════════════════════════════
def test_bootstrap_oran_tahmincisi_ve_dairesel_tam_blok():
    # W=4: her tekrar tek blok = 4 haftanın dairesel dönüşü → her tekrar ΣS/ΣN = 2/4
    # (haftalık oranların ortalaması 1.333 olurdu; boş haftalar 0/0)
    S = np.array([3.0, 0.0, -1.0, 0.0])
    N = np.array([1.0, 0.0, 3.0, 0.0])
    r = MT.block_bootstrap(S, N)
    assert r["ci"] == pytest.approx([0.5, 0.5]) and r["lcb"] == pytest.approx(0.5)
    assert r["invalid_frac"] == 0.0 and r["reliable"] is True


def test_bootstrap_yuzdelikler_2_5_ve_97_5_dairesel_bloklar():
    # W=8, N_w=1, S_w=w. Blok toplamları s=0..7: 6,10,14,18,22,18,14,10 (dairesel).
    # İki blok: P(oran=12/8)=1/64 < %2.5 < P(<=16/8)=5/64 → %2.5 yüzdeliği 2.0
    #           P(oran=44/8)=1/64, P(>=40/8)=5/64 → %97.5 yüzdeliği 5.0
    # (dairesel olmayan başlangıç [0,W-4] olsaydı P(12/8)=1/25 → alt sınır 1.5 olurdu)
    S = np.arange(8, dtype=float)
    N = np.ones(8)
    r = MT.block_bootstrap(S, N)
    assert r["ci"] == pytest.approx([2.0, 5.0]) and r["lcb"] == pytest.approx(2.0)
    assert r["invalid_frac"] == 0.0


def test_bootstrap_W_haftada_kesilir():
    # W=5: blok(4 hafta) + ikinci bloğun ilk haftası → her tekrarda N*=5.
    # S*: 2 (p=4/25), 1 (17/25), 0 (4/25) → oranlar 0.4 / 0.2 / 0.0 → CI [0.0, 0.4]
    # (kesilmeseydi N*=8 ve üst sınır 0.25 olurdu)
    r = MT.block_bootstrap(np.array([1.0, 0, 0, 0, 0]), np.ones(5))
    assert r["ci"] == pytest.approx([0.0, 0.4])


def test_bootstrap_gecersiz_tekrar_orani_ve_guvenilirlik():
    # W=8, yalnız hafta 0 ve 7'de işlem (iki haftanın oranı da 0.5).
    # Bir blok {0,7}'den birini s∈{0,4,5,6,7} için içerir (5/8) → geçersiz tekrar (3/8)^2 = 9/64
    r = MT.block_bootstrap(np.array([1.0, 0, 0, 0, 0, 0, 0, 2.0]), np.array([2.0, 0, 0, 0, 0, 0, 0, 4.0]))
    assert r["invalid_frac"] == pytest.approx(9 / 64, abs=0.015)
    assert r["reliable"] is False                                    # %5'ten fazla geçersiz
    assert r["ci"] == pytest.approx([0.5, 0.5])
    # hafta 0 ve 4: her blok tam birini içerir → geçersiz tekrar yok; oran -1 / 0 / +1
    r2 = MT.block_bootstrap(np.array([1.0, 0, 0, 0, -1.0, 0, 0, 0]), np.array([1.0, 0, 0, 0, 1.0, 0, 0, 0]))
    assert r2["invalid_frac"] == 0.0 and r2["reliable"] is True
    assert r2["ci"] == pytest.approx([-1.0, 1.0])
    z = MT.block_bootstrap(np.zeros(6), np.zeros(6))
    assert z["invalid_frac"] == 1.0 and z["reliable"] is False and _isnan(z["lcb"])
    e = MT.block_bootstrap(np.zeros(0), np.zeros(0))
    assert e["reliable"] is False and _isnan(e["lcb"])


def test_bootstrap_belirleyici_seed_ve_varyantlar_arasi_ayni_indeksler():
    g = np.random.default_rng(5)
    S = g.normal(0.1, 1.0, 30)
    N = g.integers(0, 4, 30).astype(float)
    a = MT.block_bootstrap(S, N)
    assert a == MT.block_bootstrap(S, N)                             # aynı girdi → aynı sonuç
    assert a == MT.block_bootstrap(S, N, reps=10_000, block=4, seed=20261001)
    assert MT.block_bootstrap(S, N, seed=20261002)["ci"] != a["ci"]
    # aynı hafta indeksleri: ikinci varyantın her haftası 2 katıysa her tekrar oranı 2 katıdır
    b = MT.block_bootstrap(2 * S, N)
    assert b["ci"] == pytest.approx([2 * a["ci"][0], 2 * a["ci"][1]], rel=1e-12)


# ═══════════════ §19 — MDD, PF, rapor alanları ══════════════════════════════
def test_mdd_tepe_C0_icerir_ve_bitmemis_dusus_ayri():
    t = np.arange(4) * M5
    mdd, uw, uw_open = MT.mdd_and_underwater(t[:3], np.array([9_900.0, 9_800.0, 9_950.0]), 10_000.0)
    assert mdd == pytest.approx(2.0)                                 # özsermaye hiç C0'ı aşmadı
    assert uw_open > 0                                               # tepeye dönülmedi
    mdd2, _, open2 = MT.mdd_and_underwater(t, np.array([10_100.0, 9_595.0, 10_200.0, 10_098.0]), 10_000.0)
    assert mdd2 == pytest.approx(5.0)
    mdd3, _, open3 = MT.mdd_and_underwater(t[:3], np.array([10_000.0, 10_050.0, 10_100.0]), 10_000.0)
    assert mdd3 == 0.0 and open3 == 0.0
    mdd4, _, open4 = MT.mdd_and_underwater(t[:3], np.array([10_000.0, 9_900.0, 10_000.0]), 10_000.0)
    assert mdd4 == pytest.approx(1.0) and open4 == 0.0               # tepeye eşit dönüş = kurtarıldı


def test_pf_zarar_yoksa_sayisal_degil():
    for x in ([3.0, 2.0], [5.0]):
        v = MT.pf(x)
        assert isinstance(v, str)                                    # sonsuz/tanımsız etiketi
        assert v not in (1, 1.0, 5.0)
    assert isinstance(MT.pf([0.0, 0.0]), str)                        # 0/0 tanımsız
    assert isinstance(MT.pf([]), str)
    assert MT.pf([3.0, -1.5, 1.5]) == pytest.approx(3.0)
    assert MT.pf([-1.0, -2.0]) == pytest.approx(0.0)


def _fake_res(trades, equity, wallet, outcomes=()):
    led = types.SimpleNamespace(entry_fees=0.0, exit_fees=0.0, funding=0.0, slip_cost_diag=0.0, wallet=wallet)
    flags = dict(identity_max_gap=0.0, censored_open_at_end=0, data_gap_positions=0, funding_off_grid=0,
                 stale_mark=0)
    return types.SimpleNamespace(trades=list(trades), equity=list(equity), ledger=led, flags=flags,
                                 outcomes=list(outcomes))


def _eq(t, e):
    return (t, "CLOSE", e, 0.0, 0.0, 0.0, 0.0, e, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def test_run_metrics_kenar_haftalar_pnlde_kalir_bootstraptan_cikar():
    win = (G0 + 3 * DAY, G0 + 37 * DAY)                              # Çar 4 Oca → Sal 7 Şub: 4 tam hafta
    trades = [dict(exit_interval_start=G0 + 4 * DAY + 12 * H1, net_R=2.0, net_PnL=50.0, ambiguity_flag=False),
              dict(exit_interval_start=G0 + 9 * DAY + 9 * H1, net_R=-1.0, net_PnL=-25.0, ambiguity_flag=False),
              dict(exit_interval_start=G0 + 24 * DAY, net_R=0.0, net_PnL=0.0, ambiguity_flag=False),
              dict(exit_interval_start=G0 + 36 * DAY + 10 * H1, net_R=1.2, net_PnL=30.0, ambiguity_flag=True)]
    eqs = [_eq(G0 + 3 * DAY + i * M5, e) for i, e in enumerate([10_000.0, 9_900.0, 10_200.0, 9_690.0, 10_300.0])]
    res = _fake_res(trades, eqs, wallet=C0 + 55.0,
                    outcomes=[dict(terminal_status="CLOSED", reason_code="STOP")] * 4
                    + [dict(terminal_status="MIN_ORDER_BLOCKED", reason_code="MIN_ORDER_BLOCKED")])
    m = MT.run_metrics(res, [], win, C0, "DISCOVERY")
    assert m["closed"] == 4 and m["net_USDT"] == pytest.approx(55.0) and m["return_pct"] == pytest.approx(0.55)
    assert m["win_rate"] == pytest.approx(0.5) and m["zero_pnl"] == 1
    assert m["expectancy_net_R"] == pytest.approx(0.55)              # Σ net_R / kapanış (2.2/4)
    assert m["profit_factor_usdt"] == pytest.approx(3.2) and m["profit_factor_R"] == pytest.approx(3.2)
    assert m["ambiguous_exits"] == 1
    assert m["full_weeks"] == 4 and m["weeks_with_trades"] == 2      # kenar haftalardaki iki işlem hariç
    assert m["LCB"] == pytest.approx(-0.5) and m["nominal_CI"] == pytest.approx([-0.5, -0.5])
    assert m["MDD_close_pct"] == pytest.approx(5.0)                  # 10200 → 9690
    assert m["metrics_valid"] is True
    assert m["blocked_reasons"] == {"MIN_ORDER_BLOCKED": 1}


def test_run_metrics_islem_yoksa_NA_ve_NO_TRADES():
    eqs = [_eq(G0 + 3 * DAY + i * M5, C0) for i in range(3)]
    m = MT.run_metrics(_fake_res([], eqs, wallet=C0), [], (G0 + 3 * DAY, G0 + 37 * DAY), C0, "DISCOVERY")
    assert m["closed"] == 0 and m["status_note"] == "NO_TRADES"
    for k in ("win_rate", "expectancy_net_R", "profit_factor_usdt", "profit_factor_R"):
        assert m[k] == "NA"
    assert m["net_USDT"] == 0.0 and m["boot_reliable"] is False
    ok, code, why = SL.stage_status(m | dict(MDD_close_pct=0.0), m | dict(MDD_close_pct=0.0), "DISCOVERY", False)
    assert (ok, code) == (False, SL.YETERSIZ)                         # işlemsiz koşu başarı sayılmaz


# ═══════════════ §18.3–18.5 — seçim ve karar önceliği ═══════════════════════
def _mm(exp=0.12, net=300.0, lcb=0.03, mdd=4.0, closed=150, wkt=20, wk=40, valid=True, gap=False, famb=False,
        reliable=True):
    return dict(expectancy_net_R=exp, net_USDT=net, LCB=lcb, MDD_close_pct=mdd, closed=closed,
                weeks_with_trades=wkt, full_weeks=wk, metrics_valid=valid, data_gap_exposure=gap,
                funding_order_ambiguous=famb, boot_reliable=reliable)


def test_secim_siralama_anahtari_lcb_stres_lcb_mdd_kimlik():
    R = {"L4_K4_F1": (_mm(lcb=0.30, mdd=9.0), _mm(lcb=-0.50)),
         "L3_K1_F0": (_mm(lcb=0.20, mdd=9.0), _mm(lcb=0.10)),
         "L2_K3_F0": (_mm(lcb=0.20, mdd=3.0), _mm(lcb=0.05)),
         "L2_K2_F1": (_mm(lcb=0.20, mdd=3.0), _mm(lcb=0.05)),
         "L1_K1_F0": (_mm(lcb=0.20, mdd=8.0), _mm(lcb=0.05)),
         "L1_K2_F0": (_mm(lcb=-0.05, mdd=1.0), _mm(lcb=0.40)),         # keşifte negatif LCB engel değil
         "L1_K1_F1": (_mm(lcb=0.90, closed=99), _mm(lcb=0.90))}         # örneklem tabanı yok
    sel, rows = SL.select(R, "DISCOVERY")
    assert sel == ["L4_K4_F1", "L3_K1_F0", "L2_K2_F1"]               # en fazla üç
    by = {r["variant_id"]: r for r in rows}
    assert len(rows) == 7 and by["L1_K1_F1"]["eligible"] is False and by["L1_K1_F1"]["status"] == SL.YETERSIZ
    assert by["L1_K2_F0"]["eligible"] is True
    sub = {k: R[k] for k in ("L2_K3_F0", "L2_K2_F1", "L1_K1_F0", "L1_K2_F0")}
    assert SL.select(sub, "DISCOVERY")[0] == ["L2_K2_F1", "L2_K3_F0", "L1_K1_F0"]
    assert SL.select({k: R[k] for k in ("L1_K1_F0", "L1_K2_F0")}, "DISCOVERY")[0] == ["L1_K1_F0", "L1_K2_F0"]
    neg = {"B": (_mm(lcb=-0.05), _mm(lcb=0.0)), "A": (_mm(lcb=-0.10), _mm(lcb=0.9))}
    assert SL.select(neg, "DISCOVERY")[0] == ["B", "A"]


def test_dogrulamada_en_fazla_bir_aday_ve_normal_lcb_pozitif_sarti():
    V = {"L2_K2_F1": (_mm(lcb=0.02, mdd=6.0), _mm(lcb=-0.3)),
         "L1_K1_F0": (_mm(lcb=0.02, mdd=2.0), _mm(lcb=-0.3)),         # STRESS LCB şartı yok
         "L1_K1_F1": (_mm(lcb=0.0, mdd=0.5), _mm(lcb=0.5))}           # LCB = 0 → > 0 değil
    sel, rows = SL.select(V, "VALIDATION")
    assert sel == ["L1_K1_F0"]
    by = {r["variant_id"]: r for r in rows}
    assert by["L1_K1_F1"]["eligible"] is False and by["L1_K1_F1"]["status"] == SL.YETERSIZ


@pytest.mark.parametrize("phase,floors", [("DISCOVERY", (100, 12, 26)), ("VALIDATION", (50, 8, 13)),
                                          ("FINAL", (30, 6, 13))])
def test_orneklem_tabanlari_sinirda_ve_iki_maliyette(phase, floors):
    n, wt, w = floors
    need = phase != "DISCOVERY"
    ok_m = _mm(closed=n, wkt=wt, wk=w)
    assert SL.stage_status(ok_m, ok_m, phase, need)[0] is True
    for bad in (_mm(closed=n - 1, wkt=wt, wk=w), _mm(closed=n, wkt=wt - 1, wk=w), _mm(closed=n, wkt=wt, wk=w - 1)):
        assert SL.stage_status(bad, ok_m, phase, need)[:2] == (False, SL.YETERSIZ)
        assert SL.stage_status(ok_m, bad, phase, need)[:2] == (False, SL.YETERSIZ)   # STRESS de kontrol edilir


def test_karar_onceligi_teknik_orneklem_once_sonra_pozitiflik_sonra_lcb():
    st = SL.stage_status
    # 1) teknik/veri/muhasebe veya örneklem → KANIT YETERSİZ (negatif sonuç olsa bile ELENDİ değil)
    assert st(_mm(valid=False, exp=-0.2, net=-50), _mm(), "DISCOVERY", False)[:2] == (False, SL.YETERSIZ)
    assert st(_mm(gap=True), _mm(), "DISCOVERY", False)[:2] == (False, SL.YETERSIZ)
    assert st(_mm(), _mm(famb=True), "DISCOVERY", False)[:2] == (False, SL.YETERSIZ)
    assert st(_mm(closed=99, exp=-0.2, net=-50), _mm(), "DISCOVERY", False)[:2] == (False, SL.YETERSIZ)
    # 2) yeterli örneklemde sıfır/negatif ortalama veya toplam → ELENDİ (NORMAL ya da STRESS)
    assert st(_mm(), _mm(exp=0.0), "DISCOVERY", False)[:2] == (False, SL.ELENDI)
    assert st(_mm(net=0.0), _mm(), "DISCOVERY", False)[:2] == (False, SL.ELENDI)
    assert st(_mm(exp=-0.01, net=100.0), _mm(), "DISCOVERY", False)[:2] == (False, SL.ELENDI)
    assert st(_mm(), _mm(net=-1.0), "VALIDATION", True)[:2] == (False, SL.ELENDI)
    assert st(_mm(lcb=-1.0), _mm(net=-1.0), "VALIDATION", True)[:2] == (False, SL.ELENDI)   # 2, 3'ten önce
    # 3) pozitif ama NORMAL LCB <= 0 → KANIT YETERSİZ (yalnız doğrulama/final)
    assert st(_mm(lcb=-0.1), _mm(), "DISCOVERY", False)[0] is True
    assert st(_mm(lcb=0.0), _mm(), "VALIDATION", True)[:2] == (False, SL.YETERSIZ)
    assert st(_mm(lcb=0.01), _mm(lcb=-0.4), "VALIDATION", True)[0] is True
    assert st(_mm(lcb=0.05, reliable=False), _mm(), "VALIDATION", True)[:2] == (False, SL.YETERSIZ)


def test_final_karari_bagimsizlik_ve_en_iyi_bes_cikarma():
    good = _mm(closed=40, wkt=8, wk=15, lcb=0.04)
    fd = SL.final_decision
    assert fd(good, _mm(closed=40, wkt=8, wk=15, lcb=-0.2), 12.0, True)[0] == SL.ADAY
    assert fd(good, good, 12.0, False)[0] == SL.YETERSIZ             # final bağımsız değil
    assert fd(good, good, 0.0, True)[0] == SL.YETERSIZ               # en iyi 5 çıkınca kalan > 0 değil
    assert fd(good, good, -3.0, True)[0] == SL.YETERSIZ
    # öncelik: pozitiflik (2) bağımsızlıktan (4) önce → ELENDİ
    assert fd(good, _mm(closed=40, wkt=8, wk=15, net=-5.0), 12.0, False)[0] == SL.ELENDI
    # öncelik: teknik (1) her şeyden önce
    assert fd(_mm(closed=40, wkt=8, wk=15, valid=False, exp=-1.0, net=-9.0), good, 12.0, True)[0] == SL.YETERSIZ
    assert fd(_mm(closed=29, wkt=8, wk=15, exp=-1.0, net=-9.0), good, 12.0, True)[0] == SL.YETERSIZ
    # (3) LCB şartı
    assert fd(_mm(closed=40, wkt=8, wk=15, lcb=-0.01), good, 12.0, True)[0] == SL.YETERSIZ


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_funding_modellenmemis_kosu_final_adayi_olamaz(side):
    U = dict(symbols={"AAA": _sd(*_flat(3 * 288))}, g0=G0)            # funding_t boş → NOT_MODELED
    assert U["symbols"]["AAA"].funding_source == "NOT_MODELED"
    S, T = (99.0, 102.0) if side == "LONG" else (101.0, 98.0)
    win = (G0 + DAY, G0 + 3 * DAY)
    res = RA.simulate("L1_K1_F0", "FINAL", win, [_rec("E", "AAA", side, G0 + DAY + 10 * H1, 100.0, S, T)], U,
                      ZERO_COST, C0)
    m = MT.run_metrics(res, [], win, C0, "FINAL")
    assert m["closed"] == 1                                            # 12 saat sonra TIME_EXIT ile kapandı
    perf = dict(closed=40, weeks_with_trades=8, full_weeks=15, expectancy_net_R=0.2, net_USDT=500.0, LCB=0.05,
                boot_reliable=True)                                    # performans şartları sağlanmış varsayılır
    assert SL.final_decision({**m, **perf}, {**m, **perf}, 50.0, True)[0] != SL.ADAY


def _manifest(tmp_path, mh="MH"):
    import json
    man = dict(source_hashes=cli.code_hashes(),
               config_hash=cli.sha_bytes(json.dumps(cli.config_dict(), sort_keys=True, default=str).encode()),
               data_hashes={}, manifest_hash=mh, dates_ms={}, previous_data_use=cli.PREVIOUS_DATA_USE,
               risk_caps=dict(C0=C0))
    (tmp_path / "experiment_manifest.json").write_text(json.dumps(man))
    return types.SimpleNamespace(run=str(tmp_path), data=str(tmp_path / "veri_yok"), out=str(tmp_path))


def test_secim_dosyasi_olmadan_dogrulama_ve_final_reddedilir(tmp_path):
    import json
    a = _manifest(tmp_path)
    with pytest.raises(SystemExit, match="selection_discovery.json"):
        cli.cmd_validation(a)
    with pytest.raises(SystemExit, match="selection_final.json"):
        cli.cmd_final(a)
    assert not (tmp_path / "final_result.json").exists() and not (tmp_path / "FINAL").exists()
    # farklı manifestle üretilmiş final seçimi de reddedilir
    (tmp_path / "selection_final.json").write_text(json.dumps(dict(manifest_hash="BASKA", selected=["L1_K1_F0"])))
    with pytest.raises(SystemExit):
        cli.cmd_final(a)
    assert not (tmp_path / "FINAL").exists()


def test_uygun_aday_yoksa_sonraki_asamalar_acilmaz(tmp_path):
    import json
    a = _manifest(tmp_path)
    sel = dict(manifest_hash="MH", selected=[])
    sel["hash"] = cli.sha_bytes(json.dumps(sel, sort_keys=True, default=cli._js).encode())   # hash'li seçim dosyası
    (tmp_path / "selection_discovery.json").write_text(json.dumps(sel))
    _, obj = cli.cmd_validation(a)                      # veri dizini yok: dünya kurulsaydı hata verirdi
    assert obj["selected"] == [] and "skip_reason" in obj
    _, fin = cli.cmd_final(a)
    assert fin["candidate"] is None and "skip_reason" in fin and "decision" not in fin
    assert not (tmp_path / "VALIDATION").exists() and not (tmp_path / "FINAL").exists()


def test_final_acilmadan_genel_karar_acik_durumlar():
    el = dict(status=SL.ELENDI, reason="NOT_POSITIVE", eligible=False)
    assert SL.overall_without_final([el] * 32, [])[0] == SL.ELENDI
    tech = dict(status=SL.YETERSIZ, reason="TECHNICAL_INVALID", eligible=False)
    assert SL.overall_without_final([el] * 31 + [tech], [])[0] == SL.YETERSIZ
    assert SL.overall_without_final([el] * 32, [dict(status=SL.ELENDI, reason="NOT_POSITIVE")] * 2)[0] == SL.ELENDI
    assert SL.overall_without_final([el] * 32, [dict(status=SL.ELENDI, reason="NOT_POSITIVE"),
                                                dict(status=SL.YETERSIZ, reason="LCB_NOT_POSITIVE")])[0] == SL.YETERSIZ


# ═══════════════ §21 No.35 — elle hesaplanmış K1 fixture'ı ══════════════════
_D2_13 = G0 + 2 * DAY + 13 * H1
_K13 = 2 * 288 + 156


def _no35_universe(after, mirror):
    """No.9/No.10 sayıları: L=100, A=2, 13:00–13:15 low=99.50 close=100.60, 13:15 açılışı 100.80.
    Kesim X=13:20; sonrasında 'up' hedefe, 'down' stopa gider."""
    n = 4 * 288
    o, h, l, c = _flat(n)
    bars = {_K13: (100.00, 100.10, 99.50, 99.70), _K13 + 1: (99.70, 100.30, 99.60, 100.20),
            _K13 + 2: (100.20, 100.70, 100.10, 100.60), _K13 + 3: (100.80, 101.10, 100.70, 101.00)}
    if after == "up":
        bars[_K13 + 4], rest = (101.00, 103.30, 100.90, 103.00), (103.00, 103.05, 102.95, 103.00)
    else:
        bars[_K13 + 4], rest = (101.00, 101.05, 99.20, 99.40), (99.40, 99.45, 99.35, 99.40)
    o[_K13 + 5:], h[_K13 + 5:], l[_K13 + 5:], c[_K13 + 5:] = rest
    for k, row in bars.items():
        o[k], h[k], l[k], c[k] = row
    if mirror:
        o, h, l, c = _reflect(o, h, l, c, 210.0)                     # L=100 ↔ 110
    return dict(symbols={"AAA": _sd(o, h, l, c)}, g0=G0, g1=G0 + 4 * DAY)


def _no35_event(mirror):
    return EV.MarketEvent(market_event_id="L1|AAA|X", family="L1", symbol="AAA",
                          side="SHORT" if mirror else "LONG", level_id="L1|AAA|lv",
                          level_price=110.0 if mirror else 100.0, level_known_at=G0 + 2 * DAY,
                          level_expires_at=G0 + 3 * DAY, j15=2 * 96 + 52, sweep_open=_D2_13,
                          sweep_close=_D2_13 + M15, A=2.0, micro_ref=None, double_sided=False)


@pytest.mark.parametrize("mirror", [False, True], ids=["long", "short_ayna"])
def test_no35_elle_kesim_oncesi_sinyal_dolum_muhasebe_ayni(mirror):
    X = _D2_13 + 20 * 60_000
    exp_S, exp_T, exp_E, exp_O, exp_c = ((99.30, 103.20, 100.60, 100.80, 101.00) if not mirror
                                         else (110.70, 106.80, 109.40, 109.20, 109.00))
    out = {}
    for after in ("up", "down"):
        U = _no35_universe(after, mirror)
        dv = LV.Derived(U["symbols"]["AAA"])
        r = SU.eval_K1(_no35_event(mirror), dv, "L1_K1")
        assert r.terminal_status == "SIGNAL" and r.signal_time == _D2_13 + M15
        assert (r.S, r.T, r.E_plan) == pytest.approx((exp_S, exp_T, exp_E))
        res = RA.simulate("L1_K1_F0", "DISCOVERY", (G0 + 2 * DAY, G0 + 4 * DAY), [r], U, ZERO_COST, C0)
        fills = [o for o in res.outcomes if o["terminal_status"] == "FILLED"]
        assert [o["signal_time"] for o in fills] == [_D2_13 + M15]
        snap = [e for e in res.equity if e[0] == X][0]
        # Q = floor_0.1(25 / 1.50) = 16.6 ; açık PnL = 0.20 × 16.6 = 3.32 ; ilk stop riski = 24.9
        assert snap[2] == pytest.approx(C0) and snap[6] == pytest.approx(3.32) and snap[7] == pytest.approx(10_003.32)
        assert snap[8] == 1 and snap[11] == pytest.approx(24.9)
        assert (snap[9], snap[10]) == pytest.approx((1676.6, 0.0) if not mirror else (0.0, 1809.4))
        t = res.trades[0]
        assert (t["E_fill"], t["quantity_base"], t["S"], t["T"]) == pytest.approx((exp_O, 16.6, exp_S, exp_T))
        assert t["exit_interval_start"] == X                          # kesimden sonraki ilk bar
        out[after] = (r.as_dict(), [e for e in res.equity if e[0] <= X], fills, t)
    assert out["up"][0] == out["down"][0] and out["up"][1] == out["down"][1] and out["up"][2] == out["down"][2]
    # kesim sonrası farklı: up → TARGET (net_R 1.60), down → STOP (net_R −1.00)
    assert (out["up"][3]["exit_reason"], out["up"][3]["net_R"]) == ("TARGET", pytest.approx(1.6))
    assert (out["down"][3]["exit_reason"], out["down"][3]["net_R"]) == ("STOP", pytest.approx(-1.0))


# ═══════════════ §21 No.35 — sentetik evrende tam zincir değişmezliği ═════════
_X35 = G0 + 52 * DAY + 13 * H1 + 25 * 60_000       # 15m ve 1H barlarının ortasında kesim


def _mirror_universe(U):
    U2 = _clone(U)
    for sd in U2["symbols"].values():
        K = round(float(np.nanmax(sd.h) + np.nanmin(sd.l)), 2)
        sd.o, sd.h, sd.l, sd.c = _reflect(sd.o, sd.h, sd.l, sd.c, K)
    return U2


def _alter_after(U, X, factor):
    U2 = _clone(U)
    kx = (X - U["g0"]) // M5
    for sd in U2["symbols"].values():
        for a in (sd.o, sd.h, sd.l, sd.c):
            a[kx:] = np.round(a[kx:] * factor, 2)
    return U2


def _nan_after(U, X):
    U2 = _clone(U)
    kx = (X - U["g0"]) // M5
    for sd in U2["symbols"].values():
        for a in (sd.o, sd.h, sd.l, sd.c, sd.v):
            a[kx:] = np.nan
        sd.valid5[kx:] = False
    return U2


def _truncate_at(U, X):
    U2 = _clone(U)
    kx = (X - U["g0"]) // M5
    for sd in U2["symbols"].values():
        for name in ("o", "h", "l", "c", "v", "valid5"):
            setattr(sd, name, getattr(sd, name)[:kx].copy())
        m = sd.funding_t < X
        sd.funding_t, sd.funding_rate, sd.funding_on_grid = sd.funding_t[m], sd.funding_rate[m], sd.funding_on_grid[m]
    U2["g1"] = X
    return U2


def _level_view(b, X):
    # known_at == X olan seviye ancak X'te başlayan bara referans olabilir (olayı X'ten sonra kapanır)
    return [(lv.level_id, lv.side, lv.price, lv.origin_times, lv.known_at, lv.expires_at,
             lv.consumed_at if lv.consumed_at is not None and lv.consumed_at <= X else None,
             lv.consume_reason if lv.consumed_at is not None and lv.consumed_at <= X else None)
            for lv in b.levels if lv.known_at < X]


def _assert_events_levels_equal(W1, W2, X):
    sides = set()
    for fam in FAMS:
        for s in W1.events[fam]:
            e1 = [e for e in W1.events[fam][s] if e.sweep_close <= X]
            e2 = [e for e in W2.events[fam][s] if e.sweep_close <= X]
            assert e1 == e2, (fam, s)
            sides |= {e.side for e in e1}
            assert _level_view(W1.books[fam][s], X) == _level_view(W2.books[fam][s], X), (fam, s)
    assert sides == {"LONG", "SHORT"}


def _entry_view(res, X):
    return [o for o in res.outcomes if o["signal_time"] < X and o["terminal_status"] not in ("CLOSED", "CENSORED")]


def _closed_before(res, X):
    return [t for t in res.trades
            if t["exit_interval_end"] < X or (t["exit_interval_end"] == X and t["exit_phase"] == "INTRABAR")]


_ENTRY_FIELDS = ("trade_id", "market_event_id", "symbol", "side", "signal_time", "fill_time", "E_plan", "entry_open",
                 "E_budget", "E_fill", "S", "T", "quantity_contracts", "quantity_base", "initial_margin", "R0_USDT",
                 "entry_fee")


def _assert_chain_equal(W1, U1, W2, U2, X, win, compare_open_trade_entries):
    stats = dict(fills=0, closed=0, sides=set())
    for fam in FAMS:
        for K in KS:
            r1 = SU.run_machine(fam, K, W1.events[fam], W1.derived, *win)
            r2 = SU.run_machine(fam, K, W2.events[fam], W2.derived, *win)
            assert [r.as_dict() for r in r1 if r.terminal_time <= X] == \
                   [r.as_dict() for r in r2 if r.terminal_time <= X], (fam, K)
            for F in ("F0", "F1"):
                s1 = [r for r in r1 if r.terminal_status == "SIGNAL" and (F == "F0" or r.F1_pass)]
                s2 = [r for r in r2 if r.terminal_status == "SIGNAL" and (F == "F0" or r.F1_pass)]
                x1 = RA.simulate(f"{fam}_{K}_{F}", "DISCOVERY", win, s1, U1, C.TWIN_MARKET_PROFILE, C0)
                x2 = RA.simulate(f"{fam}_{K}_{F}", "DISCOVERY", win, s2, U2, C.TWIN_MARKET_PROFILE, C0)
                assert [e for e in x1.equity if e[0] <= X] == [e for e in x2.equity if e[0] <= X], (fam, K, F)
                assert _entry_view(x1, X) == _entry_view(x2, X), (fam, K, F)
                q1, q2 = _closed_before(x1, X), _closed_before(x2, X)
                assert q1 == q2, (fam, K, F)
                if compare_open_trade_entries:
                    a = [{k: t[k] for k in _ENTRY_FIELDS} for t in x1.trades if t["fill_time"] < X]
                    b = [{k: t[k] for k in _ENTRY_FIELDS} for t in x2.trades if t["fill_time"] < X]
                    assert sorted(a, key=lambda d: d["trade_id"]) == sorted(b, key=lambda d: d["trade_id"])
                stats["fills"] += sum(o["terminal_status"] == "FILLED" for o in _entry_view(x1, X))
                stats["closed"] += len(q1)
                stats["sides"] |= {t["side"] for t in q1}
    assert stats["fills"] > 0 and stats["closed"] > 0 and stats["sides"] == {"LONG", "SHORT"}, stats


@pytest.mark.parametrize("mirror", [False, True], ids=["evren", "ayna_evren"])
def test_no35_gelecek_fiyatlar_degisince_kesim_oncesi_zincir_ayni(dunya7, mirror):
    U, W = dunya7
    if mirror:
        U = _mirror_universe(U)
        W = cli.World(universe=U)
    win = W.dates["DISCOVERY"]
    assert win[0] < _X35 < win[1] - DAY
    U2 = _alter_after(U, _X35, 0.93)
    W2 = cli.World(universe=U2)
    _assert_events_levels_equal(W, W2, _X35)
    _assert_chain_equal(W, U, W2, U2, _X35, win, compare_open_trade_entries=True)


def test_no35_veri_kesildi_nan_kuyruk_kesim_oncesi_zincir_ayni(dunya7):
    U, W = dunya7
    win = W.dates["DISCOVERY"]
    U2 = _nan_after(U, _X35)
    W2 = cli.World(universe=U2)
    _assert_events_levels_equal(W, W2, _X35)
    _assert_chain_equal(W, U, W2, U2, _X35, win, compare_open_trade_entries=False)


def test_no35_dizi_gun_sinirinda_kesildi_ayni_pencerede_birebir_ayni(dunya7):
    U, W = dunya7
    Xd = G0 + 52 * DAY
    U2 = _truncate_at(U, Xd)
    W2 = cli.World(universe=U2)
    _assert_events_levels_equal(W, W2, Xd)
    win = (W.dates["DISCOVERY"][0], Xd)
    for fam in FAMS:
        for K in KS:
            r1 = SU.run_machine(fam, K, W.events[fam], W.derived, *win)
            r2 = SU.run_machine(fam, K, W2.events[fam], W2.derived, *win)
            assert [r.as_dict() for r in r1 if r.terminal_time <= Xd] == \
                   [r.as_dict() for r in r2 if r.terminal_time <= Xd], (fam, K)
            s1 = [r for r in r1 if r.terminal_status == "SIGNAL"]
            s2 = [r for r in r2 if r.terminal_status == "SIGNAL"]
            x1 = RA.simulate(f"{fam}_{K}_F0", "DISCOVERY", win, s1, U, C.TWIN_MARKET_PROFILE, C0)
            x2 = RA.simulate(f"{fam}_{K}_F0", "DISCOVERY", win, s2, U2, C.TWIN_MARKET_PROFILE, C0)
            assert x1.trades == x2.trades and x1.equity == x2.equity and x1.outcomes == x2.outcomes, (fam, K)
            assert x1.flags == x2.flags


_MIDDAY_BUG = ("CODE_BUG: levels.LevelBook L1/L2 yalnız dizide TAM bulunan günler için seviye üretir "
               "(range(1, len(day_h)), session_hl nd=n5//288). Veri gün ortasında kesilince o günün L1 "
               "(D−1 tam) ve 08:00'de bilinen L2 seviyesi hiç oluşmaz → kesim öncesi L1/L2 olayları kaybolur "
               "(No.35 ihlali). Üretim ızgarası gün hizalı olduğundan dondurulmuş koşu etkilenmez; ileri/paper "
               "kullanımında gün içi L1/L2 hiç oluşmaz.")


@pytest.mark.parametrize("mirror", [False, True], ids=["long_fiyat", "kisa_ayna"])
def test_no35_gun_ortasi_kesimde_gunun_L1_L2_seviyesi_bilinir(mirror):
    n = 2 * 288 + 161                                   # son bar gün 2 13:20–13:25; kesim 13:25
    o, h, l, c = _flat(n)
    h[288 + 120], l[288 + 180] = 103.00, 98.00          # gün 1 (tam): tepe 103, dip 98
    h[576 + 24], l[576 + 72] = 101.50, 99.00            # gün 2 seansı (00–08, tam): 02:00 tepe, 06:00 dip
    if mirror:
        o, h, l, c = _reflect(o, h, l, c, 200.0)
    dv = LV.Derived(_sd(o, h, l, c))
    l1, l2 = LV.LevelBook("L1", dv), LV.LevelBook("L2", dv)
    tau = G0 + 2 * DAY + 13 * H1                        # kesimden önce başlayan 15m bar
    exp_l1 = (103.00, 98.00) if not mirror else (102.00, 97.00)
    exp_l2 = (101.50, 99.00) if not mirror else (101.00, 98.50)
    r_hi, r_lo = l1.reference("HIGH", tau), l1.reference("LOW", tau)
    assert r_hi is not None and r_lo is not None
    assert (r_hi.price, r_lo.price, r_hi.known_at, r_hi.expires_at) == \
           (pytest.approx(exp_l1[0]), pytest.approx(exp_l1[1]), G0 + 2 * DAY, G0 + 3 * DAY)
    s_hi, s_lo = l2.reference("HIGH", tau), l2.reference("LOW", tau)
    assert s_hi is not None and s_lo is not None
    assert (s_hi.price, s_lo.price, s_hi.known_at) == \
           (pytest.approx(exp_l2[0]), pytest.approx(exp_l2[1]), G0 + 2 * DAY + 8 * H1)


def test_no35_dizi_gun_ortasinda_kesildi_kesim_oncesi_olaylar_ayni(dunya7):
    U, W = dunya7
    W2 = cli.World(universe=_truncate_at(U, _X35))
    _assert_events_levels_equal(W, W2, _X35)
