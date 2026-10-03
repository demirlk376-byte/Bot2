"""trend_kolu (saf mantık) ve trend_canli (sinyal modu) testleri — ağ yok, emir yok."""
import asyncio
import importlib
import json
import os

import numpy as np
import pandas as pd
import pytest

import trend_kolu as TK

T0 = 1_577_836_800_000  # 2020-01-01


def bars(closes, ms=TK.DAY_MS, spread=1.0):
    c = np.asarray(closes, float)
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"t": T0 + np.arange(len(c)) * ms, "open": o, "high": np.maximum(o, c) + spread,
                         "low": np.minimum(o, c) - spread, "close": c})


ACIK = {T0 + k * TK.DAY_MS: True for k in range(-5, 2000)}     # ETH rejimi her gün açık


def yukselis(n_duz=80, up=60, down=40):
    return [100.0] * n_duz + [100 + 2 * i for i in range(1, up + 1)] + [220 - 4 * i for i in range(1, down + 1)]


def test_kirilim_ertesi_acilista_giris_ve_iz_suren_stopla_cikis():
    d = TK.Defter()
    b = bars(yukselis())
    ol = d.mum_isle("AAA", "1D", b, ACIK)
    tur = [o.tur for o in ol]
    assert tur[0] == "GIRIS_SINYALI" and tur[1] == "GIRIS"
    g = next(o for o in ol if o.tur == "GIRIS")
    assert g.t == b.t[81]                      # kırılım 80. mumda (101 > 100+1 tepesi değil → ilk gerçek kırılım)
    assert "CIKIS" in tur and d.kapanan[0]["R"] > 3
    assert d.kapanan[0]["ekler"] == 2           # +2R ve +4R'de iki ek


def test_ayni_mum_iki_kez_islenmez_ve_durum_json_dongusu():
    d = TK.Defter()
    b = bars(yukselis(up=30, down=0))
    d.mum_isle("AAA", "1D", b, ACIK)
    d2 = TK.Defter.yukle(json.loads(json.dumps(d.durum())))
    assert d2.mum_isle("AAA", "1D", b, ACIK) == []          # yeni mum yok → olay yok
    assert d2.poz.keys() == d.poz.keys()


def test_eth_rejimi_kapaliyken_giris_yok():
    b = bars(yukselis())
    kapali = {int(t): False for t in b.t}
    d = TK.Defter()
    assert not [o for o in d.mum_isle("AAA", "1D", b, kapali) if o.tur.startswith("GIRIS")]


def test_coin_basina_tek_pozisyon_iki_modul():
    d = TK.Defter()
    b1 = bars(yukselis())
    d.mum_isle("AAA", "1D", b1, ACIK)
    assert "AAA" in d.poz or d.kapanan
    b4 = bars([100.0] * 200 + [100 + i for i in range(1, 50)], ms=TK.H4_MS)
    # 1D pozisyonu açıkken (aynı zaman dilimi değil ama defter tek pozisyon tutar) 4H girişi açılmaz
    if "AAA" in d.poz:
        assert not [o for o in d.mum_isle("AAA", "4H", b4, ACIK) if o.tur == "GIRIS"]


def test_erken_cikis_tutmayan_kirilim():
    c = [100.0] * 80 + [103.0] + [103.0] * 30
    d = TK.Defter()
    d.mum_isle("AAA", "1D", bars(c, spread=0.5), ACIK)
    assert d.kapanan and d.kapanan[0]["neden"] == "ERKEN_ÇIKIŞ"


def test_gunluk_4h_den_yalniz_tam_gunler():
    b4 = bars(list(range(1, 20)), ms=TK.H4_MS)           # 19 mum = 3 tam gün + 1 eksik
    g = TK.gunluk_4h_den(b4)
    assert len(g) == 3 and g.close.iloc[0] == 6 and g.high.iloc[1] == 12 + 1


def test_trend_canli_kapaliyken_hicbir_sey_yapmaz(monkeypatch):
    monkeypatch.setenv("TREND_MODE", "kapali")
    import trend_canli
    importlib.reload(trend_canli)
    assert trend_canli.AKTIF is False
    trend_canli.tetikle(pd.Timestamp("2026-01-01 03:00", tz="UTC"), None, [], None, None)   # istisna yok, görev yok
    assert not trend_canli._gorevler


def test_trend_canli_sinyal_modu_sahte_borsayla(monkeypatch, tmp_path):
    monkeypatch.setenv("TREND_MODE", "sinyal")
    monkeypatch.setenv("TREND_DURUM_DOSYASI", str(tmp_path / "durum.json"))
    import trend_canli
    importlib.reload(trend_canli)
    simdi = 1_800_000_000_000
    n = 700
    t = (simdi // TK.H4_MS) * TK.H4_MS - np.arange(n)[::-1] * TK.H4_MS - TK.H4_MS
    fiyat = np.r_[np.full(500, 100.0), 100 + np.arange(1, 201) * 0.5]

    class Sahte:
        emir = 0

        async def fetch_ohlcv(self, sym, tf, since, limit):
            assert tf == "4h"
            m = t >= (since or 0)
            idx = np.flatnonzero(m)[:limit]
            return [[int(t[i]), fiyat[i], fiyat[i] + 1, fiyat[i] - 1, fiyat[i], 1.0] for i in idx]

        async def create_order(self, *a, **k):   # çağrılırsa test düşer
            Sahte.emir += 1
            raise AssertionError("sinyal modunda emir gönderilmemeli")

    monkeypatch.setattr(trend_canli.time, "time", lambda: simdi / 1000)
    mesajlar = []

    async def gonder(m):
        mesajlar.append(m)

    async def ozs():
        return 1000.0

    asyncio.run(trend_canli._calistir(Sahte(), ["AAA/USDT:USDT", "ETH/USDT:USDT"], gonder, ozs))
    assert mesajlar and "sinyal modu" in mesajlar[0]
    assert os.path.exists(tmp_path / "durum.json") and Sahte.emir == 0


# ── 2. aşama: canlı yol (sahte borsa + sahte yürütücü; ağ yok, gerçek emir yok) ──────────────
class _Poz:
    def __init__(self, pid, sym, entry, sl, tp, qty):
        self.id, self.symbol, self.entry_price, self.sl_price, self.tp_price, self.quantity = pid, sym, entry, sl, tp, qty
        self.strategy_scores = {"strategy": "trend_kolu"}
        self.side = "long"


class _Port:
    def __init__(self):
        self.p = []

    def get_open_positions(self):
        return list(self.p)


class _Res:
    def __init__(self, ok, pos=None, err=None):
        self.success, self.position, self.error = ok, pos, err


class _Exec:
    def __init__(self):
        self._portfolio = _Port()
        self.girisler, self.kapanan = [], []
        import types
        self._config = types.SimpleNamespace(risk=types.SimpleNamespace(fixed_margin_usdt=0.0))
        self._kilit = asyncio.Lock()

    def _symbol_lock(self, s):
        return self._kilit

        class _DB:
            async def update_trade_sl(self, *a):
                pass
        self._db = _DB()

    async def current_equity(self):
        return 1000.0

    async def execute_signal(self, sig, atr):
        assert sig.dominant_strategy == "trend_kolu" and ":trend" in sig.position_slot and sig.tp_price > sig.entry_price
        p = _Poz(f"o{len(self.girisler)}", sig.symbol, sig.entry_price, sig.sl_price, sig.tp_price, 1.0)
        self._portfolio.p.append(p)
        self.girisler.append(sig)
        return _Res(True, p)

    async def close_position(self, pos, reason, price):
        self._portfolio.p.remove(pos)
        self.kapanan.append((pos.id, reason))
        return True


class _Borsa:
    def __init__(self, fiyat=150.0):
        self.fiyat, self.tasimalar, self.stoplar_var, self.teminat = fiyat, [], True, []

    async def get_current_price(self, s):
        return self.fiyat

    async def list_attached_stops(self, s):
        return [{"orderId": "o0"}, {"orderId": "o1"}, {"orderId": "o2"}] if self.stoplar_var else []

    async def move_stop_loss(self, sym, side, sl, qty, order_id=None, tp_yedek=None):
        assert order_id is not None and tp_yedek and tp_yedek > 0
        self.tasimalar.append((order_id, sl))
        return True

    async def get_leg(self, s, side):
        self.leg_okuma = getattr(self, "leg_okuma", 0) + 1
        liq = "140" if not self.teminat else "100"
        return {"liquidatePrice": liq, "holdVol": str(getattr(self, "hold", 1)), "positionId": 1}

    async def get_position_mode(self):
        return 1

    async def cancel_attached_stop_for_order(self, s, oid):
        return True

    async def add_leg_margin(self, s, side, amt):
        self.teminat.append(amt)
        return True

    def _contract_size(self, s):
        return 1.0


def test_canli_giris_stop_tasima_ve_teminat(monkeypatch):
    import trend_canli
    ex, br = _Exec(), _Borsa()
    d = TK.Defter()
    d.bekleyen["AAA"] = {"tur": "giris", "modul": "1D", "S0": 120.0, "c": 150.0, "sinyal_t": 0}   # mum_isle'nin bıraktığı
    olay = TK.Olay("GIRIS_SINYALI", "AAA", "1D", 0, 150.0, 120.0)
    asyncio.run(trend_canli._canli_uygula(d, [olay], br, ex, lambda m: asyncio.sleep(0)))
    assert len(ex.girisler) == 1 and ex.girisler[0].sl_price == 120.0
    assert br.teminat, "tasfiye (140) hedefin (120 − 0.5×30 = 105) üstünde → ek teminat beklenir"
    assert not ex.kapanan, "bekleyen giriş varken yeni açılan gerçek pozisyon kapatılmamalı"
    d.bekleyen.clear()
    # sanal pozisyon stopu yükselince canlı kolun KENDİ stopu taşınır
    d.poz["AAA"] = TK.Pozisyon("AAA", "1D", 0, 0, 150.0, 30.0, 120.0, 130.0, 150.0)
    asyncio.run(trend_canli._canli_uygula(d, [], br, ex, lambda m: asyncio.sleep(0)))
    assert br.tasimalar == [("o0", 130.0)] and ex._portfolio.p[0].sl_price == 130.0


def test_canli_senkron_sanal_kapaninca_gercek_kapanir_ve_stopsuz_kapanir():
    import trend_canli
    ex, br = _Exec(), _Borsa()
    ex._portfolio.p.append(_Poz("o0", "AAA/USDT:USDT", 150, 120, 1500, 1))
    d = TK.Defter()                                    # sanal pozisyon yok, bekleyen giriş yok
    asyncio.run(trend_canli._canli_uygula(d, [], br, ex, lambda m: asyncio.sleep(0)))
    assert ex.kapanan == [("o0", "trend_senkron")]
    ex2, br2 = _Exec(), _Borsa()
    br2.stoplar_var = False
    ex2._portfolio.p.append(_Poz("o0", "AAA/USDT:USDT", 150, 120, 1500, 1))
    d2 = TK.Defter()
    d2.poz["AAA"] = TK.Pozisyon("AAA", "1D", 0, 0, 150.0, 30.0, 120.0, 120.0, 150.0)
    asyncio.run(trend_canli._canli_uygula(d2, [], br2, ex2, lambda m: asyncio.sleep(0)))
    assert ex2.kapanan == [("o0", "trend_stopsuz")]


def test_canli_erken_cikis_ve_yalniz_sanal_dokunulmaz():
    import trend_canli
    ex, br = _Exec(), _Borsa()
    ex._portfolio.p.append(_Poz("o0", "AAA/USDT:USDT", 150, 120, 1500, 1))
    d = TK.Defter()
    d.poz["AAA"] = TK.Pozisyon("AAA", "1D", 0, 0, 150.0, 30.0, 120.0, 120.0, 150.0)
    asyncio.run(trend_canli._canli_uygula(d, [TK.Olay("CIKIS_SINYALI", "AAA", "1D", 0, 150, 120, "ERKEN_ÇIKIŞ")],
                                          br, ex, lambda m: asyncio.sleep(0)))
    assert ex.kapanan and ex.kapanan[0][1] == "trend_erken_cikis"
    ex3 = _Exec()
    d3 = TK.Defter()
    d3.meta["yalniz_sanal"] = ["BBB"]
    asyncio.run(trend_canli._canli_uygula(d3, [TK.Olay("GIRIS_SINYALI", "BBB", "4H", 0, 150, 120)],
                                          _Borsa(), ex3, lambda m: asyncio.sleep(0)))
    assert ex3.girisler == []


def test_canli_onkosul_hedge_kapaliyken_reddedilir(monkeypatch):
    import trend_canli, exchange as EXM
    monkeypatch.setattr(EXM, "HEDGE_AWARE_RECON", False)
    assert "HEDGE_AWARE_RECON" in asyncio.run(trend_canli._canli_onkosul(_Borsa(), _Exec()))
    monkeypatch.setattr(EXM, "HEDGE_AWARE_RECON", True)
    assert asyncio.run(trend_canli._canli_onkosul(_Borsa(), _Exec())) is None
    b = _Borsa()

    async def tek_yon():
        return 2
    b.get_position_mode = tek_yon
    assert "hedge" in asyncio.run(trend_canli._canli_onkosul(b, _Exec()))


def test_acik_risk_tavani():
    import trend_canli
    ex, br = _Exec(), _Borsa()
    for i in range(30):   # her biri 30 USDT risk → tavan (%24 × 1000 = 240) aşılır
        ex._portfolio.p.append(_Poz(f"x{i}", f"C{i}/USDT:USDT", 150, 120, 1500, 1))
    d = TK.Defter()
    for i in range(30):
        d.poz[f"C{i}"] = TK.Pozisyon(f"C{i}", "1D", 0, 0, 150.0, 30.0, 120.0, 120.0, 150.0)
    asyncio.run(trend_canli._canli_uygula(d, [TK.Olay("GIRIS_SINYALI", "AAA", "1D", 0, 150, 120)],
                                          br, ex, lambda m: asyncio.sleep(0)))
    assert ex.girisler == []


def test_bacak_eksikse_trend_kapatma_emri_gonderilmez():
    """Stop zaten tetiklenmişse (bacak iç toplamdan küçük) kapatma emri öbür kolu satardı → gönderilmez."""
    import trend_canli
    ex, br = _Exec(), _Borsa()
    br.hold = 0.5                                   # borsada 0.5, içeride 1 → bir stop tetiklenmiş
    ex._portfolio.p.append(_Poz("o0", "AAA/USDT:USDT", 150, 120, 1500, 1))
    d = TK.Defter()                                 # sanal kapalı → normalde senkron kapatırdı
    asyncio.run(trend_canli._canli_uygula(d, [], br, ex, lambda m: asyncio.sleep(0)))
    assert ex.kapanan == []


def test_eski_olaylar_canlida_uygulanmaz_ve_ek_tekrar_acilmaz():
    import trend_canli
    ex, br = _Exec(), _Borsa()
    d = TK.Defter()
    d.bekleyen["AAA"] = {"tur": "giris", "modul": "1D", "S0": 120.0, "c": 150.0, "sinyal_t": 5}
    eski = TK.Olay("GIRIS_SINYALI", "AAA", "1D", 5, 150.0, 120.0)
    asyncio.run(trend_canli._canli_uygula(d, [eski], br, ex, lambda m: asyncio.sleep(0), {("AAA", "1D"): 9}))
    assert ex.girisler == []                         # son mum 9, olay 5 → uygulanmaz
    # ek: defterdeki ek sayısından slot → ikinci kez aynı ek denenirse slot aynı ("…:trend:ek1")
    ex._portfolio.p.append(_Poz("o0", "AAA/USDT:USDT", 150, 120, 1500, 1))
    d.bekleyen.clear()
    d.poz["AAA"] = TK.Pozisyon("AAA", "1D", 0, 0, 150.0, 30.0, 120.0, 125.0, 210.0)
    ek = TK.Olay("EK_SINYALI", "AAA", "1D", 9, 210.0, 125.0)
    asyncio.run(trend_canli._canli_uygula(d, [ek], br, ex, lambda m: asyncio.sleep(0), {("AAA", "1D"): 9}))
    assert ex.girisler and ex.girisler[-1].position_slot.endswith(":trend:ek1")


def test_rejim_bilinmiyorsa_giris_yok():
    d = TK.Defter()
    assert not [o for o in d.mum_isle("AAA", "1D", bars(yukselis()), {}) if o.tur.startswith("GIRIS")]


def _iki_modul():
    b4 = bars([100.0] * 1300 + [100 + 0.4 * i for i in range(1, 300)] + [220 - 1.0 * i for i in range(1, 120)],
              ms=TK.H4_MS)
    return b4, TK.gunluk_4h_den(b4)


def test_zaman_sirali_toplu_mum_mum_kaydet_ayni():
    import json
    b4, d1 = _iki_modul()
    toplu = TK.Defter()
    o1 = toplu.zaman_sirali_isle("AAA", {"1D": d1, "4H": b4}, ACIK)
    assert any(o.tur == "GIRIS" for o in o1)
    adim = TK.Defter()
    o2 = []
    for n in range(50, len(b4) + 1, 37):                 # veri parça parça geliyor
        b4n = b4.iloc[:n]
        o2 += adim.zaman_sirali_isle("AAA", {"1D": TK.gunluk_4h_den(b4n), "4H": b4n}, ACIK)
        adim = TK.Defter.yukle(json.loads(json.dumps(adim.durum())))   # her adımda kaydet → yükle
    o2 += adim.zaman_sirali_isle("AAA", {"1D": d1, "4H": b4}, ACIK)
    assert [(o.tur, o.modul, o.t) for o in o1] == [(o.tur, o.modul, o.t) for o in o2]
    assert toplu.kapanan == adim.kapanan and toplu.durum()["poz"] == adim.durum()["poz"]


def test_zaman_sirali_ilk_gelen_modul_kazanir():
    """4H kırılımı günlükten önce gelirse pozisyon 4H'nin olmalı (eski sıralı yükleme 1D'yi öne alıyordu)."""
    b4, d1 = _iki_modul()
    d = TK.Defter()
    ol = d.zaman_sirali_isle("AAA", {"1D": d1, "4H": b4}, ACIK)
    ilk = next(o for o in ol if o.tur == "GIRIS")
    sinyaller = [o for o in ol if o.tur == "GIRIS_SINYALI"]
    assert ilk.modul == sinyaller[0].modul
    acik = {}
    for k in sorted(d.kapanan, key=lambda x: x["giris_t"]):
        assert acik.get("AAA", -1) <= k["giris_t"]
        acik["AAA"] = k["cikis_t"]
