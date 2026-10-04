"""
test_cikis_komisyonu.py — mutabakat çıkışının GERÇEK komisyonu DB'ye kadar doğru taşınıyor mu?

NEDEN VAR (doğrulanmış hata, 2026-09-28): main.py mutabakat yolu fetch_close_fill ile gerçek
çıkış komisyonunu alıyordu ama _close_position_internal'a AKTARMIYORDU; execution.py ücreti
her zaman çıkış × 0.0001 olarak yeniden hesaplıyordu. DB (fees_usdt, pnl_usdt), işlem sonucu
serisi (kayıp sayacı) ve kapanış bildirimi o yeniden hesaplanan değeri kullanıyordu.

Bu testler kaynakta kelime ARAMAZ: gerçek mutabakat döngüsünü (main.position_reconciliation_loop)
bellekte bir DB ile BİR tur koşturur ve satırı DB'den geri okur. Ayrıca doğrudan
_close_position_internal ve fetch_close_fill davranışını sınar.

Senaryo (kullanıcı): long giriş 100, miktar 10, çıkış 99, giriş ücret oranı 0.0001,
gerçek çıkış ücreti 0.25 → toplam ücret 0.35, net PnL −10.35 (hatalı eski: 0.199 / −10.199).
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_config            # noqa: E402
from database import Database, TradeRecord  # noqa: E402
from exchange import LiveExchange          # noqa: E402
from execution import ExecutionEngine      # noqa: E402
from portfolio import Portfolio, Position  # noqa: E402
from risk import RiskManager               # noqa: E402

SYM = "ADA/USDT:USDT"
TOL = 1e-9


class _SahteBorsa:
    """Mutabakatın dokunduğu uçlar: pozisyon borsada KAPANMIŞ, gerçek dolum ayarlanabilir."""
    def __init__(self, dolum):
        self.dolum = dolum            # fetch_close_fill dönüşü: (px, ücret|None, n) ya da None
        self.sorgu = 0

    async def get_position(self, symbol, side=None):
        return None                   # borsada pozisyon yok → dışarıdan kapanmış

    async def get_current_price(self, symbol):
        return self.guncel

    guncel = 99.0

    async def fetch_close_fill(self, symbol, side, qty, since_ms):
        self.sorgu += 1
        return self.dolum


async def _kur(dolum):
    cfg = load_config()
    cfg.exchange.paper_mode = False
    db = Database(":memory:")
    await db.initialize()
    port = Portfolio(is_paper=False)
    borsa = _SahteBorsa(dolum)
    eng = ExecutionEngine(borsa, RiskManager(cfg.risk), port, db, cfg)
    bildirim = []
    eng.register_close_callback(lambda pos, px, pnl, reason: bildirim.append((px, pnl, reason)))

    async def _yok(*a, **k):
        return True
    eng._resync_symbol_stops_locked = _yok
    eng.enforce_daily_loss = _yok
    t0 = datetime.now(timezone.utc) - timedelta(hours=5)
    pos = Position(id="t1", symbol=SYM, direction=1, entry_price=100.0, sl_price=95.0,
                   tp_price=110.0, quantity=10.0, entry_time=t0, is_paper=False,
                   strategy_scores={"strategy": "donchian", "entry_fee_rate": 0.0001})
    port.add_position(pos)
    await db.log_trade_open(TradeRecord(
        id="t1", symbol=SYM, side="long", entry_price=100.0, quantity=10.0, sl_price=95.0,
        tp_price=110.0, entry_time=t0.isoformat(), is_paper=False,
        strategy_scores=dict(pos.strategy_scores)))
    return cfg, db, port, borsa, eng, pos, bildirim


async def _mutabakat_bir_tur(dolum, guncel=99.0, patlat=False):
    """main.position_reconciliation_loop'u GERÇEKTEN bir tur koşturur."""
    import main as M
    cfg, db, port, borsa, eng, pos, bildirim = await _kur(dolum)
    borsa.guncel = guncel
    if patlat:
        async def _hata(*a, **k):
            raise RuntimeError("borsa okunamadı")
        borsa.fetch_close_fill = _hata
    eski = {k: getattr(M, k) for k in ("config", "portfolio", "exchange", "executor", "asyncio")}

    class _Dur(Exception):
        pass

    gercek_asyncio = eski["asyncio"]

    async def _uyu(sn, *a, **k):
        if sn >= 120:                 # tur sonu → döngüden çık
            raise _Dur()
        return None                   # başlangıç (30 sn) ve teyit (2 sn) beklemeleri atlanır

    M.asyncio = SimpleNamespace(sleep=_uyu, **{k: getattr(gercek_asyncio, k)
                                              for k in dir(gercek_asyncio) if not k.startswith("_") and k != "sleep"})
    M.config, M.portfolio, M.exchange, M.executor = cfg, port, borsa, eng
    try:
        try:
            await M.position_reconciliation_loop()
        except _Dur:
            pass
    finally:
        for k, v in eski.items():
            setattr(M, k, v)
    satir = (await db.get_all_trades(limit=5, is_paper=False))[0]
    await db.close()
    return satir, bildirim, eng, borsa


def test_gercek_ucret_dbye_kadar_tasinir():
    satir, bildirim, eng, borsa = asyncio.run(_mutabakat_bir_tur((99.0, 0.25, 1)))
    assert borsa.sorgu == 1
    assert satir.exit_reason == "external_close"
    assert abs(satir.exit_price - 99.0) < TOL
    assert abs(satir.fees_usdt - 0.35) < TOL, satir.fees_usdt          # 0.10 giriş + 0.25 gerçek çıkış
    assert abs(satir.pnl_usdt - (-10.35)) < TOL, satir.pnl_usdt        # eski hatalı: −10.199
    assert satir.strategy_scores["exit_fee_source"] == "exchange"
    assert abs(satir.strategy_scores["exit_fee_usdt"] - 0.25) < TOL
    assert not satir.strategy_scores.get("exit_price_estimated")
    assert len(bildirim) == 1 and abs(bildirim[0][1] - (-10.35)) < TOL  # bildirim AYNI net PnL
    assert eng._consecutive_losses.get("donchian:" + SYM) == 1          # işlem sonucu bir kez
    # pnl_pct de aynı net PnL'den (marjin üzerinden, 10x)
    assert abs(satir.pnl_pct - (-10.35) / (100.0 * 10.0 / eng._config.exchange.leverage)) < TOL


def test_gercek_sifir_ucret_tahminle_degistirilmez():
    satir, bildirim, _, _ = asyncio.run(_mutabakat_bir_tur((99.0, 0.0, 1)))
    assert abs(satir.fees_usdt - 0.10) < TOL, satir.fees_usdt           # yalnız giriş ücreti
    assert abs(satir.pnl_usdt - (-10.10)) < TOL
    assert satir.strategy_scores["exit_fee_source"] == "exchange"
    assert satir.strategy_scores["exit_fee_usdt"] == 0.0
    assert abs(bildirim[0][1] - (-10.10)) < TOL


def test_ucret_bilinmiyorsa_tahmin_ve_kalici_isaret():
    # dolum bulundu ama ücret doğrulanamadı (fetch_close_fill → ücret None)
    satir, bildirim, _, _ = asyncio.run(_mutabakat_bir_tur((99.0, None, 1)))
    assert abs(satir.fees_usdt - 0.199) < TOL, satir.fees_usdt          # 0.10 + 99×10×0.0001
    assert abs(satir.pnl_usdt - (-10.199)) < TOL
    assert satir.strategy_scores["exit_fee_source"] == "estimate_taker_1bp"
    assert not satir.strategy_scores.get("exit_price_estimated")        # fiyat gerçek dolumdan


def test_dolum_bulunamazsa_fiyat_ve_ucret_tahmin_isaretli():
    satir, bildirim, _, _ = asyncio.run(_mutabakat_bir_tur(None))
    assert satir.strategy_scores["exit_fee_source"] == "estimate_taker_1bp"
    assert satir.strategy_scores["exit_price_estimated"] is True        # KALICI (eskiden yalnız bellekte)
    assert abs(satir.exit_price - 99.0) < TOL                           # seviye yok → güncel fiyat
    assert abs(satir.fees_usdt - 0.199) < TOL


def test_ayni_kapanis_iki_kez_cagrilir():
    async def _k():
        cfg, db, port, borsa, eng, pos, bildirim = await _kur(None)
        n1 = await eng._close_position_internal(pos, 99.0, "external_close", exit_fee_usdt=0.25)
        n2 = await eng._close_position_internal(pos, 99.0, "external_close", exit_fee_usdt=0.25)
        n3 = await eng._close_position_internal(pos, 50.0, "max_hold")   # farklı değerle de
        satir = (await db.get_all_trades(limit=5, is_paper=False))[0]
        await db.close()
        return n1, n2, n3, satir, bildirim, eng
    n1, n2, n3, satir, bildirim, eng = asyncio.run(_k())
    assert abs(n1 - (-10.35)) < TOL and n2 is None and n3 is None
    assert abs(satir.pnl_usdt - (-10.35)) < TOL and satir.exit_reason == "external_close"
    assert len(bildirim) == 1                                            # tek bildirim
    assert eng._consecutive_losses.get("donchian:" + SYM) == 1           # kayıp bir kez sayıldı


def test_gecersiz_ucret_tahmine_duser():
    async def _k():
        cfg, db, port, borsa, eng, pos, bildirim = await _kur(None)
        n = await eng._close_position_internal(pos, 99.0, "external_close", exit_fee_usdt=float("nan"))
        satir = (await db.get_all_trades(limit=5, is_paper=False))[0]
        await db.close()
        return n, satir
    n, satir = asyncio.run(_k())
    assert abs(satir.fees_usdt - 0.199) < TOL and satir.strategy_scores["exit_fee_source"] == "estimate_taker_1bp"


def _borsa(fills):
    lx = LiveExchange.__new__(LiveExchange)

    class _C:
        async def fetch_my_trades(self, symbol, since, limit):
            return fills
    lx._exchange = _C()
    return lx


def test_fetch_close_fill_ucret_yok_sifir_degil_none():
    f = [{"timestamp": 2, "side": "4", "info": {"side": 4}, "price": 99.0, "amount": 10.0, "cost": 990.0}]
    px, ucret, n = asyncio.run(_borsa(f).fetch_close_fill(SYM, "sell", 10.0, 0))
    assert abs(px - 99.0) < TOL and ucret is None                       # eskiden 0.0 (sessiz)


def test_fetch_close_fill_gercek_sifir_korunur():
    f = [{"timestamp": 2, "side": "4", "info": {"side": 4}, "price": 99.0, "amount": 10.0, "cost": 990.0,
          "fee": {"cost": 0.0, "currency": "USDT"}}]
    px, ucret, n = asyncio.run(_borsa(f).fetch_close_fill(SYM, "sell", 10.0, 0))
    assert ucret == 0.0


def test_fetch_close_fill_usdt_disi_ucret_bilinmiyor():
    f = [{"timestamp": 2, "side": "4", "info": {"side": 4}, "price": 99.0, "amount": 10.0, "cost": 990.0,
          "fee": {"cost": 0.3, "currency": "MX"}}]
    px, ucret, n = asyncio.run(_borsa(f).fetch_close_fill(SYM, "sell", 10.0, 0))
    assert ucret is None


def test_fetch_close_fill_bir_dolumda_ucret_eksikse_toplam_bilinmiyor():
    f = [{"timestamp": 3, "side": "4", "info": {"side": 4}, "price": 99.0, "amount": 6.0, "cost": 594.0,
          "fee": {"cost": 0.15, "currency": "USDT"}},
         {"timestamp": 2, "side": "4", "info": {"side": 4}, "price": 98.0, "amount": 4.0, "cost": 392.0}]
    px, ucret, n = asyncio.run(_borsa(f).fetch_close_fill(SYM, "sell", 10.0, 0))
    assert n == 2 and ucret is None                                      # kısmi toplam gerçek sayılmaz


# ─────────── inceleme sonrası eklenen davranış testleri ───────────

def test_dolum_fiyati_guncel_fiyattan_ayirt_edilir():
    satir, _, _, _ = asyncio.run(_mutabakat_bir_tur((99.0, 0.25, 1), guncel=99.3))
    assert abs(satir.exit_price - 99.0) < TOL                            # güncel 99.3 DEĞİL, gerçek dolum
    assert abs(satir.pnl_usdt - (-10.35)) < TOL


def test_fetch_close_fill_hata_verirse_tahmin_isaretli():
    satir, _, _, _ = asyncio.run(_mutabakat_bir_tur((99.0, 0.25, 1), patlat=True))
    assert satir.strategy_scores["exit_fee_source"] == "estimate_taker_1bp"
    assert satir.strategy_scores["exit_price_estimated"] is True
    assert abs(satir.fees_usdt - 0.199) < TOL                            # sıfır ücret SAYILMADI


def test_gercek_sifir_ucret_isaret_degistirir_seri_sayaci():
    # long 100 × 10, çıkış 100.015, gerçek ücret 0 → brüt +0.15, net +0.05 (kazanç).
    # Eski 1bp tahminiyle net −0.05 (kayıp) olur ve kayıp sayacı artardı.
    satir, bildirim, eng, _ = asyncio.run(_mutabakat_bir_tur((100.015, 0.0, 1), guncel=100.015))
    assert abs(satir.pnl_usdt - 0.05) < 1e-6, satir.pnl_usdt
    assert eng._consecutive_losses.get("donchian:" + SYM, 0) == 0
    assert abs(bildirim[0][1] - 0.05) < 1e-6


def test_cikis_fiyati_sifirsa_tahmin_isaretli():
    async def _k():
        cfg, db, port, borsa, eng, pos, bildirim = await _kur(None)
        await eng._close_position_internal(pos, 0.0, "external_close", exit_fee_usdt=0.25)
        satir = (await db.get_all_trades(limit=5, is_paper=False))[0]
        await db.close()
        return satir
    satir = asyncio.run(_k())
    assert satir.strategy_scores["exit_price_estimated"] is True
    assert abs(satir.exit_price - 100.0) < TOL


def _market_kapanis(fill_estimated):
    """ExecutionEngine.close_position (max_hold / manuel / acil yolu) → DB."""
    from exchange import OrderResult

    async def _k():
        cfg, db, port, borsa, eng, pos, bildirim = await _kur(None)

        async def close_position(symbol, side, qty, reason):
            return OrderResult(order_id="o1", symbol=symbol, side="sell", filled_price=99.0,
                               quantity=qty, timestamp=0, is_paper=False,
                               fill_estimated=fill_estimated)
        borsa.close_position = close_position
        ok = await eng.close_position(pos, "max_hold", 99.3)
        satir = (await db.get_all_trades(limit=5, is_paper=False))[0]
        await db.close()
        return ok, satir, bildirim
    return asyncio.run(_k())


def test_market_kapanis_yolu_ucret_tahmin_isaretli():
    ok, satir, bildirim = _market_kapanis(False)
    assert ok and satir.exit_reason == "max_hold" and abs(satir.exit_price - 99.0) < TOL
    assert abs(satir.fees_usdt - 0.199) < TOL and abs(satir.pnl_usdt - (-10.199)) < TOL
    assert satir.strategy_scores["exit_fee_source"] == "estimate_taker_1bp"
    assert not satir.strategy_scores.get("exit_price_estimated")
    assert len(bildirim) == 1 and abs(bildirim[0][1] - (-10.199)) < TOL


def test_market_kapanis_mark_yedegi_tahmin_isaretli():
    ok, satir, _ = _market_kapanis(True)
    assert satir.strategy_scores["exit_price_estimated"] is True


def test_short_kapanisi_ham_kod_2_ile_eslesir_long_girisi_eslesmez():
    # ccxt: ham '2' (short KAPAT = alış) → normalize 'sell'; ham '1' (long AÇ) → 'buy'.
    f = [{"timestamp": 3, "side": "buy", "info": {"side": 1}, "price": 2.47, "amount": 38.0,
          "cost": 93.86, "fee": {"cost": 0.0, "currency": "USDT"}},             # yeni long GİRİŞİ
         {"timestamp": 2, "side": "sell", "info": {"side": 2}, "price": 2.50, "amount": 38.0,
          "cost": 95.0, "fee": {"cost": 0.02375, "currency": "USDT"}}]         # short KAPANIŞI
    px, ucret, n = asyncio.run(_borsa(f).fetch_close_fill(SYM, "buy", 38.0, 0))
    assert abs(px - 2.50) < TOL and abs(ucret - 0.02375) < TOL and n == 1


def test_normalize_yon_tek_basina_kapanis_sayilmaz():
    f = [{"timestamp": 2, "side": "sell", "price": 99.0, "amount": 10.0, "cost": 990.0,
          "fee": {"cost": 0.25, "currency": "USDT"}}]                          # ham kod yok
    assert asyncio.run(_borsa(f).fetch_close_fill(SYM, "sell", 10.0, 0)) is None


def test_kismi_eslesmede_fiyat_var_ucret_bilinmiyor():
    f = [{"timestamp": 2, "side": "4", "info": {"side": 4}, "price": 99.0, "amount": 9.5,
          "cost": 940.5, "fee": {"cost": 0.2375, "currency": "USDT"}}]         # 9.5 / 10 eşleşti
    px, ucret, n = asyncio.run(_borsa(f).fetch_close_fill(SYM, "sell", 10.0, 0))
    assert abs(px - 99.0) < TOL and ucret is None
