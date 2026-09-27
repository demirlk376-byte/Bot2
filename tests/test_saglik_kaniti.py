"""
saglik_kaniti.py — "neden işlem yok?" sayacının ZAMANLAMA / DEFTER / KAPI mantığı.

2026-09-27: eski sürüm 14 YALANCI "⛔ AÇIKLANAMADI" bastı (VOL_MULT'suz Donchian, 4h
AÇILIŞ etiketi, oluşmakta olan mum, defterde çift sayım). Bu testler o hataların geri
gelmesini SENTETİK veriyle (ağsız, repo verisine dokunmadan) yakalar.

Çalıştır:  python -m pytest tests/test_saglik_kaniti.py -q
"""
import dataclasses
import os
import sqlite3
import sys
import types

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import saglik_kaniti as SK  # noqa: E402
from config import load_config  # noqa: E402

UTC = "UTC"


def _seri(n=1200, bitis="2025-03-10 00:00", seed=7):
    """1h rastgele yürüyüş — son mumun AÇILIŞI `bitis`."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(end=pd.Timestamp(bitis, tz=UTC), periods=n, freq="1h")
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.003, n))
    l = np.minimum(o, c) * (1 - rng.uniform(0, 0.003, n))
    v = rng.uniform(100, 200, n)
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}, index=idx)


class _Sabit:
    """Her barda aynı yönü veren sahte strateji — KAPI mantığını izole sınamak için."""

    def __init__(self, yon, reason="sahte"):
        self.yon, self.reason = yon, reason

    def analyze(self, df, *a):
        return types.SimpleNamespace(direction=self.yon, reason=self.reason, bb_pos=0.5)


def _st(dc=0, sq=0, bb=0):
    return {"dc": _Sabit(dc), "dc_ham": _Sabit(dc), "sq": _Sabit(sq), "sq_ham": _Sabit(sq),
            "bb": _Sabit(bb), "bb_ham": _Sabit(bb),
            "dc_kw": {"vol_mult": 2.5, "vol_lookback": 20, "confirm_bars": 0}, "sq_kw": {}}


def _cfg(**risk):
    cfg = load_config()
    cfg = dataclasses.replace(cfg, risk=dataclasses.replace(cfg.risk, **risk))
    return cfg


# ── 1) ZAMANLAMA ────────────────────────────────────────────────────────────
def test_olusmakta_olan_mum_ve_yarim_4h_bar_atilir():
    m = _seri(100, bitis="2025-03-10 10:00")
    k = SK.kapanmis(m, pd.Timestamp("2025-03-10 10:37", tz=UTC))
    assert k.index[-1] == pd.Timestamp("2025-03-10 09:00", tz=UTC)   # 10:00 mumu OLUŞMAKTA
    d4 = SK.dort_saat(k)
    # 08:00-12:00 4h barı yarım (son kapanmış 1h kapanışı 10:00) → atılmalı
    assert d4.index[-1] == pd.Timestamp("2025-03-10 04:00", tz=UTC)


def test_donchian_4h_KAPANISINDA_etiketlenir():
    m = _seri(1200)
    cfg = _cfg()
    bas = m.index[-1] - pd.Timedelta(days=3)
    ad = SK.adaylar_coin("SOL", m, cfg, ["donchian"], bas, _st(dc=1), mtf_aktif=False)
    assert ad, "sahte strateji her 4h kapanışında sinyal vermeliydi"
    for a in ad:
        assert a["t"].hour % 4 == 0 and a["t"].minute == 0, a["t"]     # 4h bar KAPANIŞI
        assert a["filtre"] is None
    son_kapanis = m.index[-1] + pd.Timedelta(hours=1)
    beklenen = [t for t in pd.date_range(bas.ceil("4h"), son_kapanis, freq="4h") if t >= bas]
    assert [a["t"] for a in ad] == beklenen


def test_bb_hafta_sonu_mum_KAPANISINA_gore():
    """main.py:274 datetime.now() kapanışta okunur: Cuma 23:00 mumu (kapanış Cmt 00:00)
    HAFTA SONU, Pazar 23:00 mumu (kapanış Pzt 00:00) HAFTA İÇİ."""
    m = _seri(400, bitis="2025-03-10 02:00")          # 2025-03-10 Pazartesi
    cfg = _cfg(bb_weekday_enabled=False, regime_filter_enabled=False)
    bas = pd.Timestamp("2025-03-07 20:00", tz=UTC)    # Cuma
    ad = {a["t"]: a for a in SK.adaylar_coin("LTC", m, cfg, ["mean_rev"], bas, _st(bb=1))}
    cmt = pd.Timestamp("2025-03-08 00:00", tz=UTC)
    pzt = pd.Timestamp("2025-03-10 00:00", tz=UTC)
    cuma = pd.Timestamp("2025-03-07 23:00", tz=UTC)
    assert ad[cmt]["filtre"] is None
    assert ad[pzt]["filtre"].startswith("hafta içi")
    assert ad[cuma]["filtre"].startswith("hafta içi")


def test_squeeze_rejim_kapisi_ve_hukmu():
    m = _seri(400)
    cfg = _cfg(adx_ranging_threshold=1000.0, regime_filter_enabled=True)
    bas = m.index[-1] - pd.Timedelta(hours=10)
    ad = SK.adaylar_coin("XRP", m, cfg, ["squeeze"], bas, _st(sq=-1))
    # kapanışı [bas, son kapanış] içinde olan 12 mum (bas dahil)
    assert len(ad) == 12 and all(a["filtre"].startswith("rejim/ADX kapısı") for a in ad)


# ── 2) DEFTER ───────────────────────────────────────────────────────────────
def _db(tmp_path, rows):
    p = tmp_path / "trades.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE trades (id TEXT PRIMARY KEY, symbol TEXT, side TEXT, "
                "entry_time TEXT, exit_time TEXT, exit_reason TEXT, pnl_usdt REAL, "
                "strategy_scores TEXT, is_paper INTEGER, entry_price REAL, quantity REAL)")
    for r in rows:
        con.execute("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?)", r + (100.0, 1.0))
    con.commit()
    con.close()
    return str(p)


def _r(i, coin, kol, giris, cikis=None, pnl=None, neden=None, paper=0, side="long"):
    return (i, f"{coin}/USDT:USDT", side, giris, cikis, neden, pnl,
            '{"strategy": "%s"}' % kol, paper)


def test_defter_salt_okur_tekil_ve_simdi_kesimi(tmp_path):
    p = _db(tmp_path, [
        _r("a", "SOL", "donchian", "2025-03-05T04:00:00+00:00"),                       # açık, pencerede
        _r("b", "ETH", "donchian", "2025-01-01T04:00:00+00:00", "2025-01-02T00:00:00+00:00", -1.0, "sl_hit"),
        _r("c", "XRP", "squeeze", "2025-03-11T04:00:00+00:00"),                        # simdi'den SONRA
        _r("d", "LTC", "mean_rev", "2025-03-08T04:00:00+00:00", "2025-03-10T05:00:00+00:00", 1.0, "tp_hit"),
        _r("e", "SOL", "donchian", "2025-03-01T04:00:00+00:00", paper=1),              # paper — sayılmaz
    ])
    simdi = pd.Timestamp("2025-03-10 00:00", tz=UTC)
    poz, kap, e0 = SK.defter(p, simdi - pd.Timedelta(days=7), simdi)
    assert e0 is None                                 # meta tablosu yok → marj tahmini yapılmaz
    ids = sorted(g["id"] for g in poz)
    assert ids == ["a", "d"]                          # b eski, c gelecek, e paper; a BİR KEZ
    assert next(g for g in poz if g["id"] == "d")["cikis"] is None   # simdi'de hâlâ açık
    assert [g["id"] for g in kap] == ["b"]            # d'nin kapanışı simdi'den sonra
    con = SK._baglan(p)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("DELETE FROM trades")
    con.close()
    assert not os.path.exists(str(tmp_path / "yok.db"))
    with pytest.raises(sqlite3.OperationalError):
        SK._baglan(str(tmp_path / "yok.db")).execute("SELECT 1 FROM trades")
    assert not os.path.exists(str(tmp_path / "yok.db"))   # mode=ro dosya OLUŞTURMAZ


def _g(i, coin, kol, giris, cikis=None, pnl=0.0, neden="", yon=1):
    return {"id": i, "symbol": f"{coin}/USDT:USDT", "coin": coin, "kol": kol, "yon": yon,
            "side": "long" if yon == 1 else "short", "giris": pd.Timestamp(giris, tz=UTC),
            "cikis": None if cikis is None else pd.Timestamp(cikis, tz=UTC),
            "pnl": pnl, "neden": neden, "max_hold": None}


def _a(coin, kol, t, yon=1):
    return SK._aday(coin, kol, pd.Timestamp(t, tz=UTC), yon, 0.0, "-", 25.0)


def test_esleme_BIRE_BIR_ve_en_gec_kapanis():
    a1 = _a("XRP", "squeeze", "2025-03-05 10:00")
    a2 = _a("XRP", "squeeze", "2025-03-05 11:00")
    g = _g("x", "XRP", "squeeze", "2025-03-05 11:00:20")
    kalan = SK.esle([a1, a2], [g])
    assert not kalan and a2["karar"] == "AÇILDI" and a1["karar"] is None
    # filtrelenmiş adaya giriş EŞLENMEZ → 'yeniden hesapta karşılığı yok' olarak raporlanır
    a3 = _a("SOL", "donchian", "2025-03-05 12:00")
    a3["filtre"] = "MTF kapısı — BEKLENEN"
    kalan = SK.esle([a3], [_g("y", "SOL", "donchian", "2025-03-05 12:00:05")])
    assert [x["id"] for x in kalan] == ["y"]


# ── 3) KAPILAR (execution.py kod sırası) ────────────────────────────────────
def test_soguma_seri_eski_kayiplari_ve_atlanan_nedenleri_bilir():
    kap = [
        _g("1", "BCH", "donchian", "2025-02-01", "2025-02-02", pnl=-5),     # 30 gün önce
        _g("2", "BCH", "donchian", "2025-03-03", "2025-03-04 08:00", pnl=-5),
        _g("3", "BCH", "donchian", "2025-03-05", "2025-03-05 04:00", pnl=-5, neden="halted_entry"),
    ]
    sg = SK.soguma_listesi(kap, 2, 240)
    assert sg[("donchian", "BCH/USDT:USDT")] == [
        (pd.Timestamp("2025-03-04 08:00", tz=UTC), pd.Timestamp("2025-03-04 12:00", tz=UTC))]
    cfg = _cfg(max_positions=7)
    a = _a("BCH", "donchian", "2025-03-04 12:00")
    assert SK.karar(a, [], sg, cfg, True, a["t"] + pd.Timedelta(days=1)).startswith("⛔")
    a = _a("BCH", "donchian", "2025-03-04 08:00")    # aynı kapanışta çıkış → soğuma
    assert SK.karar(a, [], sg, cfg, True, a["t"] + pd.Timedelta(days=1)).startswith("ardışık kayıp")
    kap.append(_g("4", "BCH", "donchian", "2025-03-06", "2025-03-06 04:00", pnl=+5))
    kap.append(_g("5", "BCH", "donchian", "2025-03-07", "2025-03-07 04:00", pnl=-5))
    assert len(SK.soguma_listesi(kap, 2, 240)[("donchian", "BCH/USDT:USDT")]) == 1   # kâr sıfırladı


def test_karar_kod_sirasi_koltuk_coin_ayni_tur():
    cfg = _cfg(max_positions=3, max_correlated_direction=0, max_same_direction=0)
    t = "2025-03-05 12:00"
    simdi = pd.Timestamp("2025-03-06", tz=UTC)
    a = _a("ADA", "donchian", t)
    acik = [_g(str(i), c, "squeeze", "2025-03-05 01:00") for i, c in enumerate(["XRP", "DOGE", "XLM"])]
    assert SK.karar(a, acik, {}, cfg, True, simdi) == "koltuk dolu (3/3) — BEKLENEN"
    # 2 açık + aynı kapanış turunda başka coinde açılan 3. → aynı tur etiketi
    tur = acik[:2] + [_g("t", "BNB", "donchian", "2025-03-05 12:00:30")]
    assert "aynı kapanış turunda" in SK.karar(a, tur, {}, cfg, True, simdi)
    # coin dolu: aynı coinde açık pozisyon (tek pozisyon/coin)
    kendi = [_g("k", "ADA", "donchian", "2025-03-04 00:00")]
    assert SK.karar(a, kendi, {}, cfg, True, simdi) == "coin dolu — BEKLENEN"
    # aynı coinde tam bu kapanışta kapanan pozisyon: PAPER'da portföyden create_task ile
    # SONRADAN düşer (ikizde ölçüldü) → engel olabilir, ayrı etiketle açıklanır
    kapanan = [_g("k", "ADA", "donchian", "2025-03-04 00:00", "2025-03-05 12:00")]
    assert SK.karar(a, kapanan, {}, cfg, True, simdi).startswith("coin dolu (aynı kapanışta")
    # kapanıştan ÖNCE kapanmış pozisyon engel DEĞİL → hiçbir kapı açıklamıyor
    once = [_g("k", "ADA", "donchian", "2025-03-04 00:00", "2025-03-05 11:00")]
    assert SK.karar(a, once, {}, cfg, True, simdi) == "⛔ AÇIKLANAMADI"
    # çok yeni kapanış: giriş henüz DB'ye düşmemiş olabilir → ⛔ değil
    assert SK.karar(a, [], {}, cfg, True, a["t"] + pd.Timedelta(minutes=2)).startswith("giriş işleniyor")


# ── 4) UÇTAN UCA (sentetik CSV, --db-yok) + salt-okur kaynak ────────────────
def test_uctan_uca_db_yok_sentetik(tmp_path, monkeypatch, capsys):
    for k, v in {"SYMBOLS": "SOL,XRP,LTC", "DONCHIAN_SYMBOLS": "SOL", "SQUEEZE_SYMBOLS": "XRP",
                 "BB_SYMBOLS": "LTC"}.items():
        monkeypatch.setenv(k, v)
    for i, c in enumerate(["SOL", "XRP", "LTC"]):
        _seri(1700, bitis="2025-03-10 05:00", seed=i).rename_axis("ts").to_csv(tmp_path / f"{c}_fut_1h.csv")
    once = sorted(os.listdir(tmp_path))
    r = SK.main(["5", "--veri", str(tmp_path), "--db-yok", "--simdi", "2025-03-10T05:30"])
    out = capsys.readouterr().out
    assert sorted(os.listdir(tmp_path)) == once                 # hiçbir şey YAZILMADI
    assert r["veri_var"] and not r["eksik_veri"] and r["db_yok"]
    assert all(a["t"] <= pd.Timestamp("2025-03-10 05:00", tz=UTC) for a in r["adaylar"])
    assert "HÜKÜM:" in out and "AÇIKLANAMADI" not in out.split("HÜKÜM")[-2]


def test_kaynak_salt_okur():
    """Kodda (yorum/docstring HARİÇ) yazma / emir / fast_bt.load çağrısı olmamalı."""
    import ast
    src = open(SK.__file__, encoding="utf-8").read()
    assert "?mode=ro" in src
    yasak = {"load", "to_csv", "to_parquet", "commit", "executemany", "place_market_order",
             "place_limit_order", "create_order", "_save_cache", "write", "write_text"}
    cagri = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Call):
            f = n.func
            ad = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if ad == "load" and not (isinstance(f, ast.Attribute)
                                     and getattr(f.value, "id", "") == "fast_bt"):
                continue                     # json.load vb. değil, yalnız fast_bt.load yasak
            if ad == "open" and len(n.args) > 1:
                cagri.add("open(yazma?)")
            if ad in yasak:
                cagri.add(ad)
    assert not cagri, cagri
