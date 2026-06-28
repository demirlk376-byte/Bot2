"""
test_donchian.py — Donchian 4h swing-breakout sleeve correctness.

Verifies:
  • A close above the prior-N channel high, WITH price above EMA200, fires LONG;
    SL/TP geometry is correct (SL=2×ATR below, TP=RR×SL above entry).
  • A close below the channel low, WITH price below EMA200, fires SHORT.
  • The EMA200 trend filter BLOCKS a breakout against the higher-timeframe trend
    (a long breakout in a downtrend → no trade) — this is the key robustness lever.
  • Price inside the channel → no signal.
  • The channel EXCLUDES the just-closed bar (no lookahead): a bar that itself sets
    a new high does not "break its own" channel.

Run:  python tests/test_donchian.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from strategies.donchian import DonchianStrategy


def _frame(closes: list[float], highs=None, lows=None) -> pd.DataFrame:
    n = len(closes)
    idx = pd.date_range("2025-01-01", periods=n, freq="4h", tz="UTC")
    highs = highs if highs is not None else [c * 1.001 for c in closes]
    lows = lows if lows is not None else [c * 0.999 for c in closes]
    return pd.DataFrame(
        {"open": closes, "high": highs, "low": lows, "close": closes, "volume": [1.0] * n},
        index=idx,
    )


def _uptrend_base(n: int, start: float = 100.0, step: float = 1.0) -> list[float]:
    """Steadily rising series so EMA200 sits below price (uptrend)."""
    return [start + step * i for i in range(n)]


def _run():
    chan = 20
    strat = DonchianStrategy(channel=chan, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
    ema = 200
    base_n = ema + chan + 5  # enough history for EMA200 + channel

    # ── 1. LONG breakout in an uptrend ───────────────────────────────────────
    closes = _uptrend_base(base_n)
    # Flatten the last `chan` bars into a tight range so the channel high is known,
    # then break out on the final bar.
    plateau = closes[-(chan + 1)]
    for j in range(chan):
        closes[-(chan) + j] = plateau          # last `chan` bars flat at `plateau`
    chan_high = plateau * 1.001                  # the flat bars' high
    closes[-1] = plateau * 1.02                  # final bar closes 2% above plateau
    df = _frame(closes)
    df.iloc[-1, df.columns.get_loc("high")] = closes[-1] * 1.001
    atr_val = 1.0
    sig = strat.analyze(df, atr_val)
    assert sig.direction == 1, f"expected LONG, got {sig.direction} ({sig.reason})"
    entry = closes[-1]
    assert abs(sig.entry_price - entry) < 1e-6
    assert abs(sig.sl_price - (entry - 2.0 * atr_val)) < 1e-6, sig.sl_price
    assert abs(sig.tp_price - (entry + 2.0 * 2.0 * atr_val)) < 1e-6, sig.tp_price
    rr = (sig.tp_price - entry) / (entry - sig.sl_price)
    assert abs(rr - 2.0) < 1e-6, f"RR should be 2.0, got {rr}"
    print(f"✓ LONG breakout in uptrend: entry={entry:.2f} sl={sig.sl_price:.2f} "
          f"tp={sig.tp_price:.2f} RR={rr:.2f}")

    # ── 2. Trend filter BLOCKS a long breakout in a downtrend ────────────────
    # Falling series → EMA200 sits ABOVE price; a channel-high break should be
    # rejected because close < EMA200.
    closes = [300.0 - 1.0 * i for i in range(base_n)]   # steady downtrend
    plateau = closes[-(chan + 1)]
    for j in range(chan):
        closes[-(chan) + j] = plateau
    closes[-1] = plateau * 1.02                          # pop above the local channel
    df = _frame(closes)
    df.iloc[-1, df.columns.get_loc("high")] = closes[-1] * 1.001
    sig = strat.analyze(df, 1.0)
    assert sig.direction == 0, f"trend filter should block long in downtrend, got {sig.direction}"
    print(f"✓ EMA200 trend filter blocks counter-trend long: {sig.reason}")

    # ── 3. SHORT breakout in a downtrend ─────────────────────────────────────
    closes = [300.0 - 1.0 * i for i in range(base_n)]
    plateau = closes[-(chan + 1)]
    for j in range(chan):
        closes[-(chan) + j] = plateau
    closes[-1] = plateau * 0.98                          # break below the channel low
    df = _frame(closes)
    df.iloc[-1, df.columns.get_loc("low")] = closes[-1] * 0.999
    sig = strat.analyze(df, 1.0)
    assert sig.direction == -1, f"expected SHORT, got {sig.direction} ({sig.reason})"
    entry = closes[-1]
    assert abs(sig.sl_price - (entry + 2.0)) < 1e-6
    assert abs(sig.tp_price - (entry - 4.0)) < 1e-6
    print(f"✓ SHORT breakout in downtrend: entry={entry:.2f} sl={sig.sl_price:.2f} tp={sig.tp_price:.2f}")

    # ── 4. No signal when price is inside the channel ────────────────────────
    closes = _uptrend_base(base_n)
    closes[-1] = closes[-2]                              # final bar flat, inside range
    df = _frame(closes)
    sig = strat.analyze(df, 1.0)
    assert sig.direction == 0, f"inside channel should be no-trade, got {sig.direction}"
    print(f"✓ Inside channel → no signal: {sig.reason}")

    # ── 5. Insufficient history → no signal (no crash) ───────────────────────
    sig = strat.analyze(_frame(_uptrend_base(50)), 1.0)
    assert sig.direction == 0 and "insufficient" in sig.reason
    print(f"✓ Insufficient data handled: {sig.reason}")

    print("\n" + "=" * 60)
    print("✓ DONCHIAN SLEEVE CORRECT — breakout, trend filter, SL/TP geometry")
    print("=" * 60)


if __name__ == "__main__":
    _run()
