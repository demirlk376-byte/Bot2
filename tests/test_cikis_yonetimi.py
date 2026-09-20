"""
Cikis yonetimi: basabas + ATR takibi.

NEDEN EKLENDI: _update_trailing_stops kol listesi SABIT ("orb","ifvg") idi ve
ikisi de canlida kapali -- yani calisan uc kol (donchian/squeeze/mean_rev)
hicbir stop yonetimi almiyordu. Pozisyon acildiktan sonra zarar-kes hic
kipirdamiyordu, islem +3R'den -1R'ye donebiliyordu.

Testler dort seyi garanti ediyor:
  1. VARSAYILAN DAVRANIS DEGISMEDI  (canli risk almadan yayina cikabilsin)
  2. Basabas dogru esikte, dogru yonde
  3. Takip stop'u ASLA GEVSETMIYOR
  4. Takip stop'u FIYATIN OTESINE GECMIYOR (yoksa sonraki mumda aninda
     tetiklenir ve cikisi hic islem gormemis bir seviyeden kaydeder)
"""
import asyncio
from datetime import datetime, timezone

import pytest

import main as M
from portfolio import Portfolio, Position
from config import load_config
from exchange import PaperExchange


class _DB:
    async def update_trade_sl(self, *a, **k): pass


class _Pano:
    def log_message(self, *a, **k): pass
    def update_regime(self, *a, **k): pass


def _kur(strateji, yon=1, entry=100.0, sl=98.0, **ayar):
    cfg = load_config()
    for k, v in ayar.items():
        setattr(cfg.risk, k, v)
    p = Portfolio(is_paper=True)
    pos = Position(id="t1", symbol="BTC/USDT:USDT", direction=yon,
                   entry_price=entry, sl_price=sl,
                   tp_price=entry + yon * 10, quantity=1.0,
                   entry_time=datetime.now(timezone.utc),
                   strategy_scores={"strategy": strateji})
    p.add_position(pos)
    M.config, M.portfolio, M.db, M.dashboard = cfg, p, _DB(), _Pano()
    M.exchange = PaperExchange(initial_balance=10_000.0)
    return pos


def _sur(fiyat, atr=1.0):
    asyncio.run(M._update_trailing_stops("BTC/USDT:USDT", fiyat, atr))


# ── 1. varsayilan davranis ────────────────────────────────────────────────
@pytest.mark.parametrize("kol", ["donchian", "squeeze", "mean_rev"])
def test_varsayilanda_calisan_kollar_dokunulmadan_kalir(kol):
    """⚠ EN ONEMLI TEST. Varsayilan ayar bugunku canliyla BIREBIR ayni
    olmali; yoksa bu degisiklik canli botu habersiz etkiler."""
    pos = _kur(kol)
    for f in (100.0, 102.0, 105.0, 110.0, 103.0):
        _sur(f)
    assert pos.sl_price == 98.0, f"{kol}: varsayilanda stop KIPIRDAMAMALI"
    assert not pos.breakeven_moved


def test_varsayilanda_orb_hala_1R_de_basabasa_cekiliyor():
    pos = _kur("orb")                 # entry 100, sl 98 -> 1R = 2.0
    _sur(101.9)
    assert pos.sl_price == 98.0, "1R'ye varmadan tasinmamali"
    _sur(102.0)
    assert pos.sl_price == 100.0 and pos.breakeven_moved


# ── 2. basabas acildiginda ────────────────────────────────────────────────
def test_basabas_donchian_icin_acilabiliyor():
    pos = _kur("donchian", be_sleeves="orb,ifvg,donchian")
    _sur(102.0)
    assert pos.sl_price == 100.0 and pos.breakeven_moved


def test_basabas_esigi_ayarlanabiliyor():
    pos = _kur("donchian", be_sleeves="donchian", be_trigger_r=2.0)
    _sur(103.9)
    assert pos.sl_price == 98.0, "2R'ye varmadan tasinmamali"
    _sur(104.0)
    assert pos.sl_price == 100.0


def test_basabas_shortta_ters_yonde():
    pos = _kur("donchian", yon=-1, entry=100.0, sl=102.0,
               be_sleeves="donchian")
    _sur(98.0)
    assert pos.sl_price == 100.0 and pos.breakeven_moved


# ── 3. ATR takibi ─────────────────────────────────────────────────────────
def test_takip_zirveyi_izler():
    pos = _kur("donchian", be_sleeves="", trail_sleeves="donchian",
               trail_atr_mult=2.0)
    _sur(110.0, atr=1.0)                 # zirve 110 -> stop 108
    assert pos.sl_price == pytest.approx(108.0)
    _sur(115.0, atr=1.0)                 # zirve 115 -> stop 113
    assert pos.sl_price == pytest.approx(113.0)


def test_takip_ASLA_GEVSEMEZ():
    """Fiyat geri gelince stop asagi inmemeli -- inseydi koruma geri alinirdi."""
    pos = _kur("donchian", be_sleeves="", trail_sleeves="donchian",
               trail_atr_mult=2.0)
    _sur(115.0, atr=1.0)
    assert pos.sl_price == pytest.approx(113.0)
    for f in (112.0, 108.0, 114.0):
        _sur(f, atr=1.0)
        assert pos.sl_price >= 113.0 - 1e-9, f"fiyat {f}: stop GEVSEDI"


def test_takip_fiyatin_otesine_gecmez():
    """ATR carpani cok kucukse aday stop fiyatin USTUNE cikar; oyle bir stop
    sonraki mumda aninda tetiklenir ve cikisi hic islem gormemis bir
    seviyeden kaydeder."""
    pos = _kur("donchian", be_sleeves="", trail_sleeves="donchian",
               trail_atr_mult=0.0001)
    _sur(110.0, atr=1.0)
    assert pos.sl_price < 110.0, "stop guncel fiyati GECMEMELI"


def test_takip_shortta_ters_yonde_ve_gevsemez():
    pos = _kur("donchian", yon=-1, entry=100.0, sl=102.0, be_sleeves="",
               trail_sleeves="donchian", trail_atr_mult=2.0)
    _sur(90.0, atr=1.0)                  # dip 90 -> stop 92
    assert pos.sl_price == pytest.approx(92.0)
    _sur(95.0, atr=1.0)                  # geri geldi
    assert pos.sl_price <= 92.0 + 1e-9, "shortta stop GEVSEDI"


def test_takip_baslangic_esigi():
    pos = _kur("donchian", be_sleeves="", trail_sleeves="donchian",
               trail_atr_mult=2.0, trail_start_r=2.0)   # 1R=2.0 -> 2R=+4
    _sur(103.0, atr=1.0)
    assert pos.sl_price == 98.0, "esige varmadan takip baslamamali"
    _sur(104.0, atr=1.0)
    assert pos.sl_price > 98.0


# ── 4. R tabani ───────────────────────────────────────────────────────────
def test_R_basabastan_sonra_kucULMEZ():
    """⚠ Stop basabasa cekilince guncel SL'den hesaplanan R SIFIRA yakinsar.
    R baslangic stop'una sabitlenmezse takip esikleri sacmalar."""
    pos = _kur("donchian", be_sleeves="donchian", trail_sleeves="donchian",
               trail_atr_mult=2.0, trail_start_r=3.0)   # 1R=2 -> 3R=+6
    _sur(102.0, atr=1.0)                 # basabas: sl 98 -> 100
    assert pos.sl_price == 100.0
    assert pos.initial_sl_price == 98.0, "baslangic stop'u sabitlenmeliydi"
    _sur(105.0, atr=1.0)                 # +5 < 3R=6 -> takip HENUZ baslamamali
    assert pos.sl_price == 100.0
    _sur(106.0, atr=1.0)                 # +6 = 3R -> takip basliyor
    assert pos.sl_price > 100.0
