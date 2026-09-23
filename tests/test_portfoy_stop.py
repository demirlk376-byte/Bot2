"""
PORTFOY STOPU: acik pozisyonlarin TOPLAM zararina ust sinir.

Neden var: her pozisyonun kendi stopu var ama TOPLAMA sinir YOK. 5 long
acikken hepsi vurulursa ~%17.5 gider; tek koruma gunluk -%35 ve o cok gec.
Kullanicinin gozlemi: "yukseliste kazaniyor ama sondaki dususte 5-6 islem
birden stop olunca hepsi batip gidiyor."

⚠ Testler URETIM METODUNU cagirir (ExecutionEngine.portfoy_stop_kontrol), mantigi
yeniden yazmaz -- yoksa test yesil olur, bot korumasiz kalir.
"""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execution import ExecutionEngine


class _Poz:
    def __init__(self, upnl, yon=1):
        self.unrealized_pnl = upnl
        self.direction = yon
        self.symbol = "X/USDT:USDT"
        self.id = "1"


class _Portfoy:
    def __init__(self, pozlar):
        self._p = pozlar
    def get_open_positions(self):
        return list(self._p)
    def get_total_unrealized_pnl(self):
        return sum(p.unrealized_pnl for p in self._p)


class _Sahte:
    """ExecutionEngine.portfoy_stop_kontrol'un ihtiyac duydugu en kucuk yuzey."""
    def __init__(self, pozlar, equity, esik, soguma=0):
        self._portfolio = _Portfoy(pozlar)
        self._equity = equity
        self._risk = types.SimpleNamespace(
            _cfg=types.SimpleNamespace(portfoy_stop=esik,
                                       portfoy_soguma_saat=soguma))
        self._portfoy_soguma_bitis = 0.0
        self.kapatildi = []
        self.uyari = []
    async def current_equity(self):
        return self._equity
    async def emergency_close_all(self, reason):
        self.kapatildi.append(reason)
    async def _alert(self, msg, sev):
        self.uyari.append((sev, msg))
    _risk_cfg_kaynak = ExecutionEngine._risk_cfg_kaynak


async def _cagir(x):
    return await ExecutionEngine.portfoy_stop_kontrol(x)


def _kos(x):
    import asyncio
    return asyncio.run(_cagir(x))


def test_VARSAYILAN_KAPALI():
    """⚠ EN KRITIK: acilmadikca canli bot etkilenmez."""
    import config as C
    c = C.load_config()
    assert c.risk.portfoy_stop == 0.0
    assert c.risk.portfoy_soguma_saat == 0


def test_kapaliyken_TETIKLENMEZ():
    x = _Sahte([_Poz(-500)], equity=1000, esik=0.0)
    assert _kos(x) is False and x.kapatildi == []


def test_esigin_ALTINDA_tetiklenmez():
    # zarar 100 / equity 1000 = %10 < %12
    x = _Sahte([_Poz(-60), _Poz(-40)], equity=1000, esik=0.12)
    assert _kos(x) is False and x.kapatildi == []


def test_esikte_TETIKLENIR_ve_hepsini_kapatir():
    # zarar 130 / equity 1000 = %13 >= %12
    x = _Sahte([_Poz(-60), _Poz(-70)], equity=1000, esik=0.12)
    assert _kos(x) is True
    assert x.kapatildi == ["portfoy_stop"]
    assert x.uyari and x.uyari[0][0] == "ERROR"


def test_KARDAYKEN_tetiklenmez():
    x = _Sahte([_Poz(+300)], equity=1000, esik=0.05)
    assert _kos(x) is False


def test_karisik_ama_NET_KARDA_tetiklenmez():
    x = _Sahte([_Poz(-200), _Poz(+250)], equity=1000, esik=0.05)
    assert _kos(x) is False


def test_ACIK_POZISYON_YOKSA_tetiklenmez():
    x = _Sahte([], equity=1000, esik=0.05)
    assert _kos(x) is False


def test_EQUITY_OKUNAMAZSA_ASLA_TETIKLENMEZ():
    """⚠ EN ONEMLI GUVENLIK KURALI. Bosa bir okuma yuzunden tum kitabi
    kapatmak, korumanin kendisinden pahaliya mal olur. enforce_daily_loss
    ile ayni kural."""
    for kotu in (None, 0, -5):
        x = _Sahte([_Poz(-900)], equity=kotu, esik=0.05)
        assert _kos(x) is False, f"equity={kotu} iken tetiklendi"
        assert x.kapatildi == []


def test_SOGUMA_damgasi_kuruluyor():
    import time
    x = _Sahte([_Poz(-200)], equity=1000, esik=0.12, soguma=24)
    assert _kos(x) is True
    assert x._portfoy_soguma_bitis > time.time() + 23 * 3600


def test_soguma_KAPALIYSA_damga_kurulmaz():
    x = _Sahte([_Poz(-200)], equity=1000, esik=0.12, soguma=0)
    assert _kos(x) is True
    assert x._portfoy_soguma_bitis == 0.0


def test_uretim_kodu_GERCEKTEN_bagli():
    """Kontrol main.py'nin mum dongusunde cagriliyor mu? Cagrilmiyorsa
    testler yesil olur ama koruma HIC calismaz."""
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    m = open(os.path.join(kok, "main.py"), encoding="utf-8").read()
    assert "portfoy_stop_kontrol()" in m
    # SL/TP dolumlarindan SONRA olmali: once mevcut stoplar islesin
    assert m.index("check_sl_tp(") < m.index("portfoy_stop_kontrol()")
    e = open(os.path.join(kok, "execution.py"), encoding="utf-8").read()
    assert "Portfoy stopu sogumasi" in e, "soguma giris kapisi yok"
