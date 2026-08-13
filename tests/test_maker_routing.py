"""
test_maker_routing.py — donchian maker+yedek deneyinin YÖNLENDİRME testi.

BU TESTİN VARLIK SEBEBİ: execution.py giriş yolunu `sl_price > 0` çıkarımıyla
seçiyordu. donchian/squeeze sl_price'ı DOLDURUYOR ama SL'i seviyeye değil GİRİŞ
FİYATINA ATR ile çapalıyor. Yani çıkarım onları "yapı-tabanlı" sayıp piyasa
yedeğini KAPATIYORDU — dolmayan limit işlemi ATIYORDU. 2026-07-16'da denenip
haklı olarak geri alınan felaket tam buydu (main.py:640-647).

Açık bayrak (`anchor_is_level`) eklendi. Bu test ÜÇ ŞEYİ kanıtlar:

  1) BAYRAK KAPALIYKEN DAVRANIŞ BİT BİT AYNI. En kritik madde: `git pull` tek
     başına canlı emir tipini değiştirmemeli.
  2) anchor_is_level VERİLMEDİĞİNDE eski çıkarım (sl_price>0) aynen çalışır —
     yani mevcut tüm kollar etkilenmez.
  3) anchor_is_level=False verildiğinde limit PİYASA YEDEĞİYLE gider
     (fallback_market=True, timeout 45sn), True verildiğinde yedeksiz gider.

Run:  python tests/test_maker_routing.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.update({"API_KEY": "x", "API_SECRET": "x", "MEXC_API_KEY": "x",
                   "MEXC_API_SECRET": "x", "DAILY_MAX_LOSS_PCT": "0.35"})

from config import load_config
from exchange import PaperExchange
from portfolio import Portfolio
from risk import RiskManager
from database import Database
from execution import ExecutionEngine
from strategies.signal_combiner import CombinedSignal


class SpyExchange(PaperExchange):
    """Hangi yolun seçildiğini KAYDEDER — üretim sınıfını taklit etmez, ondan türer."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.cagrilar = []

    async def place_limit_order(self, symbol, side, amount, limit_price, params,
                                timeout=45.0, poll=3.0, fallback_market=True):
        self.cagrilar.append(("limit", timeout, fallback_market))
        return await self.place_market_order(symbol, side, amount, params)

    async def place_market_order(self, symbol, side, amount, params=None):
        if not self.cagrilar or self.cagrilar[-1][0] != "limit":
            self.cagrilar.append(("market", None, None))
        return await super().place_market_order(symbol, side, amount, params)


def _sig(strateji, **kw):
    s = CombinedSignal(direction=1, confidence=0.8, trend_score=0.0,
                       mean_rev_score=0.0, breakout_score=0.5,
                       dominant_strategy=strateji)
    s.symbol = "ETH/USDT:USDT"
    s.position_slot = f"ETH/USDT:USDT:{strateji}"
    s.entry_price = 100.0
    s.sl_price = 95.0          # donchian/squeeze de BUNU dolduruyor — testin özü
    s.tp_price = 110.0
    for k, v in kw.items():
        setattr(s, k, v)
    return s


async def _calistir(cfg, sinyal):
    ex = SpyExchange(initial_balance=10000, leverage=10)
    ex._prices = {"ETH/USDT:USDT": 100.0}
    db = Database(":memory:")
    await db.initialize()
    port = Portfolio(is_paper=True)
    eng = ExecutionEngine(ex, RiskManager(cfg.risk), port, db, cfg)
    await eng.capture_daily_start()
    try:
        r = await eng.execute_signal(sinyal, 5.0)
        assert r.success, f"işlem açılmadı: {r.error}"
        return ex.cagrilar[0]
    finally:
        # Kapatılmazsa olay döngüsü kapanmıyor ve test "geçti" yazdıktan SONRA
        # asılı kalıyor — CI'da bu, geçen bir testi başarısız gösterir.
        await db.close()


async def _run():
    cfg = load_config()
    cfg.risk.max_positions = 6
    cfg.risk.max_correlated_direction = 0
    cfg.exchange.paper_mode = False
    cfg.exchange.maker_entry = True

    # 1) VARSAYILAN KAPALI — .env'de DONCHIAN_MAKER_ENTRY yokken
    assert cfg.exchange.donchian_maker_entry is False, \
        "DONCHIAN_MAKER_ENTRY varsayılanı AÇIK gelmiş — git pull canlıyı değiştirir!"
    print("✓ varsayılan KAPALI — 'git pull' tek başına emir tipini değiştirmez")

    # 2) force_market=True (bayrak kapalıyken donchian'ın aldığı yol) → PİYASA
    yol = await _calistir(cfg, _sig("donchian", force_market=True, anchor_is_level=False))
    assert yol[0] == "market", f"force_market piyasa yolunu almadı: {yol}"
    print(f"✓ bayrak KAPALI (force_market=True) → {yol[0]} — bugünkü davranış AYNEN")

    # 3) anchor_is_level VERİLMEZSE eski çıkarım: sl_price>0 → yapı → YEDEKSİZ
    yol = await _calistir(cfg, _sig("orb", force_market=False))
    assert yol[0] == "limit" and yol[2] is False, f"eski çıkarım bozuldu: {yol}"
    assert yol[1] == 600.0, f"yapı-tabanlı timeout değişmiş: {yol}"
    print(f"✓ anchor_is_level YOK → eski çıkarım korunuyor "
          f"(limit, timeout {yol[1]:.0f}sn, yedek {yol[2]}) — mevcut kollar etkilenmiyor")

    # 4) anchor_is_level=False → ATR-çapalı → 45sn + PİYASA YEDEĞİ
    yol = await _calistir(cfg, _sig("donchian", force_market=False, anchor_is_level=False))
    assert yol[0] == "limit" and yol[2] is True, f"yedek AÇILMADI: {yol}"
    assert yol[1] == 45.0, f"timeout yanlış: {yol}"
    print(f"✓ anchor_is_level=False → limit + PİYASA YEDEĞİ "
          f"(timeout {yol[1]:.0f}sn, yedek {yol[2]}) — işlem KAÇMAZ")

    # 5) anchor_is_level=True → yapı → yedek YOK (R/R korunur)
    yol = await _calistir(cfg, _sig("fvg", force_market=False, anchor_is_level=True))
    assert yol[0] == "limit" and yol[2] is False, f"yapı kolu yedek almış: {yol}"
    print(f"✓ anchor_is_level=True → yedek YOK (yapı kollarının R/R'si korunuyor)")

    # 6) bayrak AÇIKKEN donchian'ın gerçekten aldığı yol (main.py'deki ifadenin aynısı)
    cfg.exchange.donchian_maker_entry = True
    yol = await _calistir(cfg, _sig(
        "donchian", force_market=not cfg.exchange.donchian_maker_entry,
        anchor_is_level=False))
    assert yol[0] == "limit" and yol[2] is True and yol[1] == 45.0, \
        f"bayrak açıkken yol yanlış: {yol}"
    print(f"✓ bayrak AÇIK → donchian limit + 45sn + yedek")

    print("\n✓ TÜM YÖNLENDİRME TESTLERİ GEÇTİ")


if __name__ == "__main__":
    asyncio.run(_run())
