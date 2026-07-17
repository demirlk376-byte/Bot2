"""
test_stop_move.py — BE@1R (ORB+IFVG) + canlı stop-taşıma kapısı.

Doğrulananlar (main._update_trailing_stops + LiveExchange.move_stop_loss akışı):
  1. PAPER: orb long +1R'de SL→entry (BE), sonrasında dokunulmaz (BE-only).
  2. PAPER: ifvg short +1R'de SL→entry; +1R altında tetiklenmez.
  3. PAPER: mean_rev / fvg sleeve'lerine ASLA dokunulmaz (BE onlara zarar verir).
  4. LIVE + STOP_MOVE_ENABLED=false: taşıma bastırılır, exchange'e istek gitmez,
     internal state (sl_price / breakeven_moved) gerçek borsa stopuyla senkron kalır.
  5. LIVE + enabled: move_stop_loss False dönerse state DEĞİŞMEZ (sonraki mumda
     retry); True dönünce sl_price + breakeven_moved commit edilir.

Run:  python tests/test_stop_move.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.update({"API_KEY": "x", "API_SECRET": "x", "MEXC_API_KEY": "x",
                   "MEXC_API_SECRET": "x"})

import main
from config import load_config
from exchange import PaperExchange
from portfolio import Portfolio, Position


class _FakeDash:
    def log_message(self, *a, **k): pass


class _FakeDb:
    def __init__(self): self.sl_updates = []
    async def update_trade_sl(self, tid, sl): self.sl_updates.append((tid, sl))


class _FakeExecutor:
    """main._update_trailing_stops canlı taşımayı executor._symbol_lock içinde
    yapar (audit v2) — testte gerçek kilit semantiği yeterli."""
    def __init__(self): self._locks = {}
    def _symbol_lock(self, symbol):
        import asyncio
        return self._locks.setdefault(symbol, asyncio.Lock())


class _FakeLive:
    """LiveExchange yerine geçer (isinstance(PaperExchange) → False).
    move_stop_loss çağrılarını kaydeder, scripted sonuç döner."""
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    async def move_stop_loss(self, symbol, position_side, new_sl, amount):
        self.calls.append((symbol, position_side, new_sl, amount))
        return self.results.pop(0) if self.results else True


def _pos(tag, direction=1, entry=100.0, sl=95.0, tp=110.0):
    return Position(
        id=f"p-{tag}-{direction}", symbol="BTC/USDT:USDT", direction=direction,
        entry_price=entry, sl_price=sl, tp_price=tp, quantity=0.01,
        entry_time=datetime.now(timezone.utc),
        strategy_scores={"strategy": tag, "atr": 2.0},
    )


def _setup(paper=True, stop_move=False, live_results=()):
    cfg = load_config()
    cfg.exchange.stop_move_enabled = stop_move
    main.config = cfg
    main.portfolio = Portfolio(is_paper=paper)
    main.dashboard = _FakeDash()
    main.db = _FakeDb()
    main.executor = _FakeExecutor()
    main.exchange = PaperExchange(10_000.0, 10) if paper else _FakeLive(live_results)
    return main.exchange


async def run():
    S = "BTC/USDT:USDT"

    # 1) PAPER orb long: R=5. +1R altında dokunma, +1R'de BE, sonra BE-only.
    _setup(paper=True)
    p = _pos("orb", 1, entry=100.0, sl=95.0)
    main.portfolio.add_position(p)
    await main._update_trailing_stops(S, 104.9, 2.0)
    assert p.sl_price == 95.0 and not p.breakeven_moved, "erken BE tetiklendi"
    await main._update_trailing_stops(S, 105.0, 2.0)
    assert p.sl_price == 100.0 and p.breakeven_moved, \
        f"BE olmadı: sl={p.sl_price} be={p.breakeven_moved}"
    await main._update_trailing_stops(S, 130.0, 2.0)
    assert p.sl_price == 100.0, "BE-only ihlali: orb SL trail edildi"
    print("✓ PAPER orb long: +1R'de BE (95→100), sonrası BE-only")

    # 2) PAPER ifvg short: entry 100, SL 104 → R=4; +1R = 96.
    _setup(paper=True)
    p = _pos("ifvg", -1, entry=100.0, sl=104.0, tp=92.0)
    main.portfolio.add_position(p)
    await main._update_trailing_stops(S, 96.1, 2.0)
    assert p.sl_price == 104.0 and not p.breakeven_moved
    await main._update_trailing_stops(S, 96.0, 2.0)
    assert p.sl_price == 100.0 and p.breakeven_moved, \
        f"ifvg short BE olmadı: sl={p.sl_price}"
    print("✓ PAPER ifvg short: +1R'de BE (104→100)")

    # 3) PAPER mean_rev + fvg + sr_breakout: hiçbir koşulda dokunulmaz.
    #    (sr_breakout 2026-07-13 denetimiyle çıkarıldı: doğrulanan modeli sabit
    #    SL/TP — 1m intrabar test: fixed PF 1.80/+23.4R vs trail PF 1.39/+7.1R.)
    _setup(paper=True)
    for tag in ("mean_rev", "fvg", "squeeze", "asia_bo", "sr_breakout"):
        p = _pos(tag, 1, entry=100.0, sl=95.0)
        main.portfolio.add_position(p)
    await main._update_trailing_stops(S, 150.0, 2.0)
    for p in main.portfolio.get_open_positions():
        assert p.sl_price == 95.0 and not p.breakeven_moved, \
            f"{p.strategy_scores['strategy']} sleeve'ine dokunuldu!"
    print("✓ PAPER mean_rev/fvg/squeeze/asia_bo/sr_breakout: stop-move YOK")

    # 4) LIVE, STOP_MOVE_ENABLED=false: bastırılır, exchange'e istek yok.
    ex = _setup(paper=False, stop_move=False)
    p = _pos("orb", 1, entry=100.0, sl=95.0)
    main.portfolio.add_position(p)
    await main._update_trailing_stops(S, 110.0, 2.0)
    assert ex.calls == [], "kapalıyken move_stop_loss çağrıldı!"
    assert p.sl_price == 95.0 and not p.breakeven_moved, \
        "kapalıyken internal state borsadan koptu"
    print("✓ LIVE kapalı: taşıma bastırıldı, state borsayla senkron")

    # 5) LIVE, enabled: ilk deneme False → state değişmez (retry); sonra True → commit.
    ex = _setup(paper=False, stop_move=True, live_results=[False, True])
    p = _pos("orb", 1, entry=100.0, sl=95.0)
    main.portfolio.add_position(p)
    await main._update_trailing_stops(S, 105.0, 2.0)
    assert len(ex.calls) == 1 and ex.calls[0][2] == 100.0
    assert p.sl_price == 95.0 and not p.breakeven_moved, \
        "başarısız taşımada state commit edildi!"
    await main._update_trailing_stops(S, 105.0, 2.0)   # retry sonraki mumda
    assert len(ex.calls) == 2
    assert p.sl_price == 100.0 and p.breakeven_moved, "başarılı taşıma commit edilmedi"
    print("✓ LIVE açık: fail→state değişmez+retry, success→commit")

    # 6) LIVE sr_breakout: stop-move kapısı açıkken bile DOKUNULMAZ (sabit model).
    ex = _setup(paper=False, stop_move=True, live_results=[True])
    p = _pos("sr_breakout", 1, entry=100.0, sl=95.0)
    main.portfolio.add_position(p)
    await main._update_trailing_stops(S, 150.0, 2.0)
    assert ex.calls == [] and p.sl_price == 95.0 and not p.breakeven_moved, \
        "sr_breakout'a canlıda dokunuldu — sabit SL/TP modeli ihlal!"
    print("✓ LIVE sr_breakout: kapı açıkken bile sabit SL/TP (dokunulmadı)")

    print("\n" + "=" * 64)
    print("✓ STOP-MOVE DOĞRU — BE@1R yalnız orb/ifvg, canlı kapı fail-safe")
    print("=" * 64)


if __name__ == "__main__":
    asyncio.run(run())
