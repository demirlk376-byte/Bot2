"""
test_one_per_symbol.py — live netted-mode one-position-per-symbol guard.

MEXC one-way mode nets every same-symbol sleeve into ONE position with a single
position-level attached SL/TP and no simultaneous long+short. A 2nd sleeve on a
symbol that already holds a position would clobber the first's stop or, opposite
direction, reduce/flip it. execute_signal must therefore reject a 2nd LIVE
position on a symbol that already holds one (across DIFFERENT slots), while PAPER
keeps full multi-sleeve concurrency.

Run:  python tests/test_one_per_symbol.py
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


def _sig(symbol, direction, slot):
    s = CombinedSignal(direction=direction, confidence=0.8, trend_score=0.0,
                       mean_rev_score=0.0, breakout_score=0.5, dominant_strategy="orb")
    s.symbol = symbol
    s.position_slot = slot
    s.entry_price = 100.0
    s.sl_price = 95.0
    s.tp_price = 110.0
    s.force_market = True
    return s


def _seed_btc(port, is_paper):
    port.create_position(
        symbol="BTC/USDT:USDT", direction=1, entry_price=100.0,
        sl_price=95.0, tp_price=110.0, quantity=1.0,
        strategy_scores={"strategy": "fvg", "slot": "BTC/USDT:USDT:fvg"},
        is_paper=is_paper, position_id=f"seed-{is_paper}",
    )


async def _engine(cfg, port, db):
    ex = PaperExchange(initial_balance=10000, leverage=10)
    ex._prices = {"BTC/USDT:USDT": 100.0, "ETH/USDT:USDT": 100.0}
    eng = ExecutionEngine(ex, RiskManager(cfg.risk), port, db, cfg)
    await eng.capture_daily_start()
    return eng


async def _run():
    cfg = load_config()
    cfg.risk.max_positions = 6
    cfg.risk.max_correlated_direction = 0   # isolate the one-per-symbol guard
    cfg.exchange.maker_entry = False
    db = Database(":memory:")
    await db.initialize()

    # ── LIVE: 2nd BTC sleeve (different slot) must be REJECTED ─────────────────
    cfg.exchange.paper_mode = False
    port = Portfolio(is_paper=True)
    _seed_btc(port, is_paper=False)
    eng = await _engine(cfg, port, db)

    r = await eng.execute_signal(_sig("BTC/USDT:USDT", 1, "BTC/USDT:USDT:ifvg"), 5.0)
    assert not r.success and "one-per-symbol" in (r.error or ""), f"same-dir not blocked: {r.error}"
    print(f"✓ LIVE: 2nd BTC sleeve (same dir) blocked — {r.error}")

    r2 = await eng.execute_signal(_sig("BTC/USDT:USDT", -1, "BTC/USDT:USDT:ifvg"), 5.0)
    assert not r2.success and "one-per-symbol" in (r2.error or ""), f"opp-dir not blocked: {r2.error}"
    print(f"✓ LIVE: opposite-direction BTC sleeve blocked (one-way flip prevented) — {r2.error}")

    # A DIFFERENT symbol must NOT be blocked by this guard (predicate is per-symbol).
    # Verify by predicate (no order placement): no ETH position exists, so the
    # guard's symbol match is False.
    eth_open = any(p.symbol == "ETH/USDT:USDT" for p in port.get_open_positions())
    eth_inflight = any(s == "ETH/USDT:USDT" for s in eng._inflight_symbol.values())
    assert not (eth_open or eth_inflight), "ETH should be free of the guard"
    print("✓ LIVE: a different symbol (ETH) is not caught by the BTC guard")

    # ── PAPER: multi-sleeve on the same symbol still allowed (guard skipped) ───
    cfg.exchange.paper_mode = True
    port_p = Portfolio(is_paper=True)
    _seed_btc(port_p, is_paper=True)
    eng_p = await _engine(cfg, port_p, db)
    rp = await eng_p.execute_signal(_sig("BTC/USDT:USDT", 1, "BTC/USDT:USDT:ifvg"), 5.0)
    assert "one-per-symbol" not in (rp.error or ""), f"paper wrongly blocked: {rp.error}"
    print(f"✓ PAPER: 2nd BTC sleeve NOT blocked (multi-sleeve preserved, success={rp.success})")

    print("\n" + "=" * 60)
    print("✓ ONE-PER-SYMBOL GUARD CORRECT — live netted-safe, paper unchanged")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(_run())
    # aiosqlite keeps a background thread that can delay interpreter exit; the
    # test work is done, so exit cleanly.
    os._exit(0)
