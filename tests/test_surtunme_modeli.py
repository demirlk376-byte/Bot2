"""
PaperExchange surtunme modeli.

NEDEN: model canliyi EKSIK temsil ediyordu ve backtest karini sistematik
olarak YUKSEK gosteriyordu -- giris kaymasi 5bp varsayiliyordu (canlida
olculen 15.85bp), cikista kayma HIC yoktu (oysa stop tetiklenince borsa
PIYASA emri atiyor), maker limit HER ZAMAN doluyordu (olculen ~%66).

EN ONEMLI TEST ILK SIRADA: varsayilanlarla hicbir sey degismemeli.
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from exchange import PaperExchange


@pytest.fixture
def borsa():
    b = PaperExchange(initial_balance=100_000.0, leverage=10)
    eski = {k: getattr(PaperExchange, k) for k in
            ("SLIP_GIRIS_BP", "SLIP_CIKIS_BP", "MAKER_DOLUM_P", "FUNDING_BP_8SA")}
    yield b
    for k, v in eski.items():
        setattr(PaperExchange, k, v)


def _ac(b, yon="buy", fiyat=100.0, qty=10.0):
    asyncio.run(b.update_price(fiyat, "BTC/USDT:USDT"))
    return asyncio.run(b.place_market_order(
        "BTC/USDT:USDT", yon, qty,
        {"stopLossPrice": 90.0, "takeProfitPrice": 120.0}))


def test_VARSAYILAN_bugunku_davranis(borsa):
    """⚠ Varsayilanlar: giris 5bp, cikis 0, funding 0, maker hep dolar."""
    assert PaperExchange.SLIP_GIRIS_BP == 5.0
    assert PaperExchange.SLIP_CIKIS_BP == 0.0
    assert PaperExchange.MAKER_DOLUM_P == 1.0
    assert PaperExchange.FUNDING_BP_8SA == 0.0
    o = _ac(borsa)
    assert o.filled_price == pytest.approx(100.0 * (1 + 0.0005))


def test_giris_kaymasi_ayarlanabilir_ve_hep_ALEYHE(borsa):
    PaperExchange.SLIP_GIRIS_BP = 15.85
    al = _ac(borsa, "buy", 100.0)
    assert al.filled_price == pytest.approx(100.0 * (1 + 0.001585)), "long PAHALI almali"
    sat = _ac(borsa, "sell", 100.0)
    assert sat.filled_price == pytest.approx(100.0 * (1 - 0.001585)), "short UCUZ satmali"


def test_cikis_kaymasi_TP_DISINDA_uygulanir(borsa):
    """⚠ TP duran LIMIT emri -> tam seviyeden dolar, kayma ODEMEZ. SL
    (stop-market) ve max_hold (market) oder. Bu ayrim onemli: hepsine yazmak
    maliyeti ~%45 fazla gosterirdi (cikislarin %30'u TP)."""
    PaperExchange.SLIP_CIKIS_BP = 20.0
    for neden, kayar in (("tp_hit", False), ("sl_hit", True), ("max_hold", True)):
        b = PaperExchange(initial_balance=100_000.0, leverage=10)
        asyncio.run(b.update_price(100.0, "BTC/USDT:USDT"))
        o = asyncio.run(b.place_market_order("BTC/USDT:USDT", "buy", 10.0, {}))
        pos = b._positions[o.order_id]
        asyncio.run(b._close_paper_position(pos, 110.0, neden))
        beklenen = 110.0 * (1 - 0.0020) if kayar else 110.0
        assert pos.exit_price == pytest.approx(beklenen), (
            f"{neden}: cikis {pos.exit_price}, beklenen {beklenen}")


def test_cikis_kaymasi_SHORTTA_ters_yonde(borsa):
    PaperExchange.SLIP_CIKIS_BP = 20.0
    b = PaperExchange(initial_balance=100_000.0, leverage=10)
    asyncio.run(b.update_price(100.0, "BTC/USDT:USDT"))
    o = asyncio.run(b.place_market_order("BTC/USDT:USDT", "sell", 10.0, {}))
    pos = b._positions[o.order_id]
    asyncio.run(b._close_paper_position(pos, 90.0, "sl_hit"))
    assert pos.exit_price == pytest.approx(90.0 * (1 + 0.0020)), "short YUKSEKTEN kapanmali"


def test_funding_tutus_SURESIYLE_birikir(borsa):
    """Funding 8 saatte bir notional uzerinden. Uzun tutus daha cok oder."""
    PaperExchange.FUNDING_BP_8SA = 10.0
    sonuclar = []
    for saat in (0.0, 8.0, 80.0):
        b = PaperExchange(initial_balance=100_000.0, leverage=10)
        asyncio.run(b.update_price(100.0, "BTC/USDT:USDT"))
        o = asyncio.run(b.place_market_order("BTC/USDT:USDT", "buy", 10.0, {}))
        pos = b._positions[o.order_id]
        pos.giris_ts -= saat * 3600.0          # tutusu geriye al
        bak0 = b._balance
        asyncio.run(b._close_paper_position(pos, 100.0, "tp_hit"))
        sonuclar.append(b._balance - bak0 - pos.margin_used)
    assert sonuclar[0] > sonuclar[1] > sonuclar[2], "uzun tutus daha cok odemeli"
    # 8 saat -> notional 1000 x 10bp = 1.0 $
    assert (sonuclar[0] - sonuclar[1]) == pytest.approx(1.0, rel=0.02)


def test_maker_dolmama_PIYASAYA_duser_ve_DETERMINIST(borsa):
    """Dolmayan maker emri piyasa yedegine duser (taker + kayma). Karar
    RASTGELE OLMAMALI -- ayni kosu ayni sonucu vermeli."""
    PaperExchange.MAKER_DOLUM_P = 0.5
    PaperExchange.SLIP_GIRIS_BP = 10.0

    def kosu():
        b = PaperExchange(initial_balance=1_000_000.0, leverage=10)
        asyncio.run(b.update_price(100.0, "BTC/USDT:USDT"))
        return [asyncio.run(b.place_limit_order(
            "BTC/USDT:USDT", "buy", 1.0, 100.0 + i * 0.01, {})).filled_price
            for i in range(40)]

    a, c = kosu(), kosu()
    assert a == c, "karar deterministik degil -- kosular karsilastirilamaz"
    dolmayan = sum(1 for i, f in enumerate(a) if f != pytest.approx(100.0 + i * 0.01))
    assert 8 <= dolmayan <= 32, f"dolum orani sacma: 40 emirde {dolmayan} dusmus"


def test_maker_dolum_1_ise_hicbiri_dusmez(borsa):
    PaperExchange.MAKER_DOLUM_P = 1.0
    b = PaperExchange(initial_balance=1_000_000.0, leverage=10)
    asyncio.run(b.update_price(100.0, "BTC/USDT:USDT"))
    for i in range(20):
        o = asyncio.run(b.place_limit_order("BTC/USDT:USDT", "buy", 1.0, 100.0 + i, {}))
        assert o.filled_price == pytest.approx(100.0 + i)
