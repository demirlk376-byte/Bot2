"""btcd_filtre.py davranış testleri:  python3 -m pytest -q arastirma/btcd_filtre/test_btcd_filtre.py"""
import io
import os
import sys
import types
import zipfile

import numpy as np
import pandas as pd
import pytest

BURA = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BURA)
import btcd_filtre as B  # noqa: E402

H = pd.Timedelta(hours=1)


def seri(baslangic="2024-01-01", n=24 * 30, fn=lambda i: 50.0):
    kap = pd.date_range(baslangic, periods=n, freq="h", tz="UTC") + H
    return pd.Series([fn(i) for i in range(n)], index=kap)


def islem(giris, yon, R=1.0, kol="donchian"):
    t = pd.Timestamp(giris, tz="UTC")
    return dict(giris=t, yon=yon, net_R=R, kol=kol,
                hafta=t.tz_localize(None).to_period("W").strftime("%Y-%m-%d"))


# ── veri okuma ────────────────────────────────────────────────────────────────
def _zip(metin):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("x.csv", metin)
    return b.getvalue()


def test_zip_basliksiz_ve_baslikli_ve_mikrosaniye():
    a = B._zip_csv(_zip("1700000000000,1,2,0.5,1.5,10,1700003599999\n"))
    b = B._zip_csv(_zip("open_time,open,high,low,close,volume\n1700000000000000,1,2,0.5,1.5,10\n"))
    assert list(a.columns) == ["open_time", "open", "high", "low", "close"]
    assert float(a["close"].iat[0]) == 1.5 and float(b["close"].iat[0]) == 1.5
    assert int(B._ms(b["open_time"]).iat[0]) == 1700000000000   # µs → ms


def test_deger_gelecegi_kullanmaz_ve_bayat_veriyi_atar():
    s = seri(n=10, fn=lambda i: float(i))          # i. mum kapanışı = başlangıç + (i+1) saat
    t0 = s.index[3]
    v = B.deger(s, pd.Series([t0, t0 - pd.Timedelta(minutes=1), t0 + pd.Timedelta(minutes=59)]))
    assert list(v) == [3.0, 2.0, 3.0]              # tam kapanış anında o mum; öncesinde bir önceki
    s2 = s.drop(s.index[5:9])                      # 4 saatlik boşluk
    v2 = B.deger(s2, pd.Series([s.index[7]]))      # son mevcut değer 3 saat önce kapandı → bayat
    assert np.isnan(v2[0])
    assert np.isnan(B.deger(s, pd.Series([s.index[0] - H]))[0])


def test_filtre_yonleri_ve_esikler():
    # dominans 7 günde %5 yükseliyor
    s = seri(n=24 * 20, fn=lambda i: 50.0 * np.exp(0.05 * min(i, 24 * 14) / (24 * 7)))
    t = s.index[24 * 10]
    d = pd.DataFrame([islem(t.isoformat(), 1), islem(t.isoformat(), -1)])
    e = B.etiketle(d, s)
    assert e["d7"].iat[0] == pytest.approx(0.05, rel=1e-6)
    assert list(e["F1"]) == [True, False]           # yükselişte LONG engellenir, short kalır
    assert list(e["F2"]) == [True, False]           # %5 > %2 bant
    assert list(e["F3"]) == [True, False]
    s_az = seri(n=24 * 20, fn=lambda i: 50.0 * np.exp(0.01 * min(i, 24 * 14) / (24 * 7)))
    e2 = B.etiketle(d, s_az)
    assert list(e2["F1"]) == [True, False] and list(e2["F2"]) == [False, False]   # %1 bant içinde
    s_dus = seri(n=24 * 20, fn=lambda i: 50.0 * np.exp(-0.05 * min(i, 24 * 14) / (24 * 7)))
    e3 = B.etiketle(d, s_dus)
    assert list(e3["F1"]) == [False, True]          # düşüşte SHORT engellenir


def test_kesme_sonraki_veri_etiketleri_degistirmez():
    rng = np.random.default_rng(1)
    adim = rng.normal(0, 0.002, 24 * 90).cumsum()
    s = seri(n=24 * 90, fn=lambda i: 50 * np.exp(adim[i]))
    tl = [s.index[24 * 10 + 7 * k] for k in range(250)]
    d = pd.DataFrame([islem(t.isoformat(), 1 if k % 2 else -1) for k, t in enumerate(tl)])
    tam = B.etiketle(d, s)
    sinir = s.index[24 * 50]
    kesik = B.etiketle(d, s[s.index <= sinir])
    m = d["giris"] <= sinir
    pd.testing.assert_frame_equal(tam.loc[m, ["d7", "d3", "F1", "F2", "F3"]],
                                  kesik.loc[m, ["d7", "d3", "F1", "F2", "F3"]])


def test_ayristirma_tabana_toplanir_ve_kapsam_disi_engellenmez():
    s = seri(n=24 * 40, fn=lambda i: 50.0 + 0.01 * i)
    d = pd.DataFrame([islem((s.index[24 * 10] + k * 5 * H).isoformat(), 1 if k % 3 else -1, R=(k % 5) - 1.5)
                      for k in range(100)] + [islem("2023-01-01", 1, R=3.0)])   # son işlem veri öncesi
    e = B.etiketle(d, s)
    assert not e["kapsamda"].iat[-1] and not e["F1"].iat[-1]
    k = e[e["kapsamda"]]
    a, b = B.grup(k, k["F1"]), B.grup(k, ~k["F1"])
    assert a["toplam_R"] + b["toplam_R"] == pytest.approx(k["net_R"].sum())
    assert a["n"] + b["n"] == len(k)


def test_net_R_islemler_dosyasindan():
    d = B.islemler()
    assert len(d) == 936
    r = d.iloc[0]
    assert r["net_R"] == pytest.approx(r["pnl_usdt"] / (abs(r["entry_price"] - r["sl0"]) * r["quantity"]))
    assert d["net_R"].notna().all()


def test_hafta_bootstrap_belirleyici():
    x = np.r_[np.full(50, -1.0), np.full(50, 0.5)]
    w = np.repeat(np.arange(20), 5)
    assert B.boot(x, w) == B.boot(x, w)
    lo, hi = B.boot(x, w)
    assert lo <= x.mean() <= hi


def test_plasebo_rastgele_rejimde_ortada_kalir():
    rng = np.random.default_rng(7)
    adim = rng.normal(0, 0.003, 24 * 400).cumsum()
    s = seri(baslangic="2023-01-01", n=24 * 400, fn=lambda i: 50 * np.exp(adim[i]))
    tl = [s.index[24 * 10 + 13 * k] for k in range(600)]
    d = pd.DataFrame([islem(t.isoformat(), 1 if k % 2 else -1, R=float(rng.normal(0.1, 1)))
                      for k, t in enumerate(tl)])
    e = B.etiketle(d, s)
    gercek = float(e.loc[e["kapsamda"] & e["F1"], "net_R"].mean())
    p = B.plasebo(d, s, gercek)
    assert p["kaydirma"] == B.PLASEBO_N
    assert 5 < p["yuzdelik"] < 95                   # bağımsız R → gerçek değer olağan aralıkta


# ── indirme (sahte Binance) ────────────────────────────────────────────────────
class _Yanit:
    def __init__(self, kod, icerik=b"", js=None):
        self.status_code, self.content, self._js = kod, icerik, js

    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(self.status_code)

    def json(self):
        return self._js


def _mumlar(bas, bit):
    t = pd.date_range(bas, bit, freq="h", tz="UTC", inclusive="left")
    return [[int(x.timestamp() * 1000), 1, 2, 0.5, 4000 + i * 0.1, 10] for i, x in enumerate(t)]


def test_indir_aylik_eksikse_gunluge_ve_fapiye_duser(tmp_path, monkeypatch):
    simdi = pd.Timestamp("2024-03-10 05:30", tz="UTC")
    cagri = []

    class Ses:
        headers = {}

        def get(self, url, params=None, timeout=None):
            cagri.append(url)
            if "monthly" in url:
                ay = url.rsplit("-1h-", 1)[1][:7]
                if ay == "2024-01":
                    return _Yanit(404)                   # bu ay aylık yok → günlük
                p = pd.Period(ay)
                rows = _mumlar(p.start_time, p.end_time.ceil("D"))
                return _Yanit(200, _zip("\n".join(",".join(map(str, r)) for r in rows)))
            if "daily" in url:
                g = pd.Timestamp(url.rsplit("-1h-", 1)[1][:10])
                rows = _mumlar(g, g + pd.Timedelta(days=1))
                return _Yanit(200, _zip("open_time,open,high,low,close,volume\n" +
                                        "\n".join(",".join(map(str, r)) for r in rows)))
            if "fapi" in url:
                st = pd.Timestamp(params["startTime"], unit="ms", tz="UTC")
                return _Yanit(200, js=_mumlar(st, simdi.floor("h") + H) if st < simdi else [])
            raise AssertionError(url)

    sahte = types.SimpleNamespace(Session=lambda: Ses())
    monkeypatch.setitem(sys.modules, "requests", sahte)
    gercek_now = pd.Timestamp.now
    monkeypatch.setattr(pd.Timestamp, "now", classmethod(lambda cls, tz=None: simdi))
    monkeypatch.setattr(B.time, "sleep", lambda s: None)
    a = types.SimpleNamespace(cikti=str(tmp_path), bas="2023-12-01")
    B.indir(a)
    monkeypatch.setattr(pd.Timestamp, "now", gercek_now)
    d = pd.read_csv(tmp_path / "btcdom_1h.csv")
    t = pd.to_datetime(d["open_time"], unit="ms", utc=True)
    assert t.min() == pd.Timestamp("2023-12-01", tz="UTC")
    assert t.max() == simdi.floor("h") - H              # oluşmakta olan mum atıldı
    assert (t.diff().dropna() == H).all()               # boşluksuz
    assert any("BTCDOMUSDT-1h-2024-01-15.zip" in u for u in cagri)   # aylık yok → günlük
    assert any("fapi" in u for u in cagri)                            # bugün → fapi
    s = B.btcd_yukle(str(tmp_path / "btcdom_1h.csv"))
    assert s.index[0] == pd.Timestamp("2023-12-01 01:00", tz="UTC")   # indeks = kapanış zamanı
