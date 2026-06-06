"""
test_data_feed.py — canlı mum-kapanış tespiti doğru mu?

Kritik: ccxt fetch_ohlcv son eleman olarak HENÜZ OLUŞAN (forming) mumu döndürür.
Eğer motor forming mumda tetiklenirse:
  • hacim filtresi ~0 hacim görüp neredeyse tüm sinyalleri reddeder
  • analiz tamamlanmamış mumda yapılır → backtest ile uyuşmaz
Bu test, DataManager'ın GERÇEK kodunu (_poll_once) sürerek şunu doğrular:
  - forming mumda TETİKLENMEZ
  - bir mum kapanınca TAM 1 kez, kapanan mumun TAM verisiyle tetiklenir
  - initialize buffer'a forming mumu KOYMAZ

Çalıştır:  python tests/test_data_feed.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import StrategyConfig
from data import DataManager

H = 3_600_000   # 1h ms
T0 = 1_700_000_000_000


class MockExchange:
    """fetch_ohlcv: son eleman her zaman forming mum."""
    def __init__(self):
        self.phase = "forming"

    async def fetch_ohlcv(self, symbol, timeframe, since=None, limit=200):
        if limit >= 200:
            # initialize: 5 mum, sonuncusu forming
            return [[T0 + i*H, 100, 101, 99, 100.5, 50] for i in range(5)]
        if self.phase == "forming":
            # idx4 hala oluşuyor (az hacim) — yeni kapanış yok
            return [[T0+2*H, 100,101,99,100, 50],
                    [T0+3*H, 100,101,99,100, 50],
                    [T0+4*H, 100,100.2,99.9,100.1, 5]]
        # "closed": idx4 kapandı (tam mum), idx5 yeni forming
        return [[T0+3*H, 100,101,99,100, 50],
                [T0+4*H, 100,105,98,103, 80],
                [T0+5*H, 103,103.1,102.9,103, 3]]

    async def update_price(self, p): pass
    async def watch_ticker(self, s):
        await asyncio.sleep(3600); return {"last": 100}


async def run():
    cfg = StrategyConfig(primary_tf="1h", confirm_tf="4h")
    ex = MockExchange()
    dm = DataManager(ex, cfg, "BTC/USDT:USDT")
    await dm.initialize()

    # initialize forming mumu hariç tutmalı → 4 kapalı mum
    assert dm._buffers["1h"].size() == 4, \
        f"initialize forming mumu buffer'a koydu: {dm._buffers['1h'].size()}"
    print(f"✓ initialize: {dm._buffers['1h'].size()} kapalı mum (forming hariç)")

    fired = []
    dm.subscribe_candle_close("1h", lambda c: fired.append(c) or asyncio.sleep(0))

    # forming fazı: _poll_once GERÇEK kodu — tetikleme olmamalı
    ex.phase = "forming"
    await dm._poll_once("1h")
    assert len(fired) == 0, f"forming mumda tetiklendi: {len(fired)}"
    print(f"✓ forming poll: tetikleme yok ({len(fired)})")

    # kapanış fazı: tam 1 kez, doğru veriyle
    ex.phase = "closed"
    await dm._poll_once("1h")
    assert len(fired) == 1, f"kapanışta tetik sayısı yanlış: {len(fired)}"
    c = fired[0]
    assert c.close == 103 and c.high == 105 and c.low == 98 and c.volume == 80, \
        f"yanlış mum verisi: {c}"
    print(f"✓ kapanış poll: tam 1 tetik, doğru veri "
          f"(close={c.close} high={c.high} vol={c.volume})")

    # ikinci kez aynı kapanışta tekrar poll → tekrar tetiklememeli
    await dm._poll_once("1h")
    assert len(fired) == 1, f"aynı kapanış tekrar tetikledi: {len(fired)}"
    print(f"✓ tekrar poll: çift tetik yok ({len(fired)})")

    print("\n" + "="*64)
    print("✓ MUM-KAPANIŞ TESPİTİ DOĞRU — canlı motor forming mumda tetiklenmez")
    print("="*64)


if __name__ == "__main__":
    asyncio.run(run())
