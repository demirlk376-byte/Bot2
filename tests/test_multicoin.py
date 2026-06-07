"""
test_multicoin.py — çoklu coin motorunun doğruluğu.

Doğrular:
  • PaperExchange coin başına AYRI fiyat tutar (tek paylaşılan fiyat yanlış olurdu).
  • İki coin aynı anda açık pozisyon tutabilir.
  • Bir coinin mumuyla SL/TP kontrolü SADECE o coinin pozisyonunu etkiler.
  • Config SYMBOLS env'ini parse + normalize eder; yoksa tek SYMBOL'e döner.

Çalıştır:  python tests/test_multicoin.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from exchange import PaperExchange
from portfolio import Portfolio


async def _exchange_isolation() -> None:
    ex = PaperExchange(initial_balance=10_000, leverage=10)
    Portfolio(is_paper=True)

    await ex.update_price(90_000, "BTC/USDT:USDT")
    await ex.update_price(3_000, "ETH/USDT:USDT")
    await ex.update_price(2.0, "XRP/USDT:USDT")

    assert await ex.get_current_price("BTC/USDT:USDT") == 90_000
    assert await ex.get_current_price("ETH/USDT:USDT") == 3_000
    assert await ex.get_current_price("XRP/USDT:USDT") == 2.0
    print("✓ coin başına fiyat izole: BTC=90000 ETH=3000 XRP=2.0")

    await ex.place_market_order("BTC/USDT:USDT", "buy", 0.01,
                                {"stopLossPrice": 85_000, "takeProfitPrice": 100_000})
    await ex.place_market_order("ETH/USDT:USDT", "buy", 0.5,
                                {"stopLossPrice": 2_800, "takeProfitPrice": 3_500})
    assert len(ex.get_open_positions()) == 2
    print(f"✓ iki coin aynı anda açık: {len(ex.get_open_positions())} pozisyon")

    # ETH kendi mumunda SL'e değer; BTC pozisyonuna DOKUNMAMALI
    await ex.check_sl_tp(candle_high=2_850, candle_low=2_790, symbol="ETH/USDT:USDT")
    await asyncio.sleep(0)
    syms = [p.symbol for p in ex.get_open_positions()]
    assert "BTC/USDT:USDT" in syms, "BTC hâlâ açık olmalı"
    assert "ETH/USDT:USDT" not in syms, "ETH SL'e değmeli"
    print(f"✓ ETH SL izole tetiklendi; BTC etkilenmedi. Kalan: {syms}")

    # BTC kendi mumuyla TP
    await ex.check_sl_tp(candle_high=101_000, candle_low=89_000, symbol="BTC/USDT:USDT")
    await asyncio.sleep(0)
    assert len(ex.get_open_positions()) == 0, "BTC TP'ye değmeli"
    print("✓ BTC TP kendi mum aralığıyla tetiklendi")


def _config_parsing() -> None:
    from config import load_config

    os.environ["MEXC_API_KEY"] = "x"
    os.environ["MEXC_API_SECRET"] = "x"

    os.environ["SYMBOLS"] = "BTC,ETH/USDT,SOL/USDT:USDT"
    c = load_config()
    assert c.exchange.symbols == [
        "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"
    ], c.exchange.symbols
    assert c.exchange.symbol == "BTC/USDT:USDT"
    print(f"✓ SYMBOLS parse + normalize: {c.exchange.symbols}")

    del os.environ["SYMBOLS"]
    c = load_config()
    assert c.exchange.symbols == ["BTC/USDT:USDT"], c.exchange.symbols
    print(f"✓ SYMBOLS yoksa tek coin: {c.exchange.symbols}")


def main() -> int:
    asyncio.run(_exchange_isolation())
    _config_parsing()
    print("\n" + "=" * 60)
    print("✓ ÇOKLU COIN MOTORU DOĞRU — fiyatlar ve SL/TP coin bazında izole")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
