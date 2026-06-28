"""
test_ifvg.py — Inverse Fair Value Gap (IFVG) reversal sleeve correctness.

IFVG is stateful: zones are built, flipped, and traded across successive
candle-closes, so the test feeds bars one at a time (as the live engine does)
and asserts the full lifecycle:

  • A 3-candle imbalance (gap >= min_gap×ATR) creates a watched FVG zone.
  • A gap SMALLER than the filter is ignored (the 0.75×ATR noise filter — the
    lever that makes 2025 robust — must actually reject small gaps).
  • When price VIOLATES a bearish gap (closes back above it), the zone flips to
    support; the RETEST of that flipped zone in the EMA-trend direction fires LONG.
  • SL/TP geometry: SL = zone far edge ∓ (zone_width + 0.3×ATR buffer);
    TP = entry ± RR × stop-distance.
  • The EMA trend gate blocks a counter-trend retest entry.
  • Insufficient data → no signal, no crash.

A short ema_period is used so the scenario needs few bars; the mechanics under
test (gap detect → flip → retest) are identical at the production EMA200.

Run:  python tests/test_ifvg.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from strategies.ifvg import IfvgStrategy, SL_BUFFER_ATR


def _feed(strat: IfvgStrategy, bars: list[tuple], atr: float = 1.0):
    """Feed OHLC bars one at a time (cumulative window), returning the last
    non-zero signal (and the bar index it fired on)."""
    idx = pd.date_range("2025-01-01", periods=len(bars), freq="1h", tz="UTC")
    rows = {"open": [], "high": [], "low": [], "close": [], "volume": []}
    fired = None
    for i, (o, h, l, c) in enumerate(bars):
        rows["open"].append(o); rows["high"].append(h)
        rows["low"].append(l); rows["close"].append(c); rows["volume"].append(1.0)
        df = pd.DataFrame(rows, index=idx[: i + 1])
        sig = strat.analyze(df, atr)
        if sig.direction != 0:
            fired = (i, sig)
    return fired


def _bullish_ifvg_sequence() -> list[tuple]:
    """Build a sequence that: rises (EMA below price), prints a bearish gap,
    violates it to the upside (flip to support), then retests → LONG.
    OHLC tuples."""
    bars: list[tuple] = []
    # Warm-up rising base so the short EMA sits below later prices (uptrend).
    for p in (96, 97, 98, 99, 100):
        bars.append((p, p + 0.4, p - 0.4, p))
    # Bearish FVG triple (A,B,C): low[A] > high[C] → gap down of 2.0 (>= 0.75×ATR).
    bars.append((105, 111.0, 110.0, 110.5))   # A: low = 110.0  (zone top)
    bars.append((108, 109.0, 106.0, 107.0))   # B: middle
    bars.append((107, 108.0, 106.0, 107.0))   # C: high = 108.0 (zone bottom); gap=2.0
    # D: close back ABOVE the zone top (110) → violates bearish gap → flips to support.
    bars.append((109, 112.0, 109.0, 111.0))   # close 111 > 110
    # E: retest — dips to touch the flipped zone top (110) and closes above it,
    #    above EMA → LONG entry at the zone top.
    bars.append((111, 112.0, 110.0, 111.5))   # low 110 <= top, close 111.5
    return bars


def _run():
    # ── 1. Bullish IFVG: gap → flip → retest fires LONG with correct geometry ──
    strat = IfvgStrategy(min_gap_atr=0.75, rr=2.0, ema_period=3)
    atr = 1.0
    fired = _feed(strat, _bullish_ifvg_sequence(), atr)
    assert fired is not None, "expected a LONG IFVG retest entry, got none"
    i, sig = fired
    assert sig.direction == 1, f"expected LONG, got {sig.direction} ({sig.reason})"
    top, bottom = 110.0, 108.0
    sld = (top - bottom) + SL_BUFFER_ATR * atr        # 2.0 + 0.3 = 2.3
    assert abs(sig.entry_price - top) < 1e-6, sig.entry_price
    assert abs(sig.sl_price - (top - sld)) < 1e-6, sig.sl_price
    assert abs(sig.tp_price - (top + 2.0 * sld)) < 1e-6, sig.tp_price
    rr = (sig.tp_price - sig.entry_price) / (sig.entry_price - sig.sl_price)
    assert abs(rr - 2.0) < 1e-6, f"RR should be 2.0, got {rr}"
    print(f"✓ Bullish IFVG fires on retest: entry={sig.entry_price:.2f} "
          f"sl={sig.sl_price:.2f} tp={sig.tp_price:.2f} RR={rr:.2f}")

    # ── 2. Gap filter: a gap smaller than 0.75×ATR creates no zone → no entry ──
    # Same structure but the gap (top-bottom) is only 0.4 < 0.75×ATR=0.75.
    strat2 = IfvgStrategy(min_gap_atr=0.75, rr=2.0, ema_period=3)
    bars = []
    for p in (96, 97, 98, 99, 100):
        bars.append((p, p + 0.4, p - 0.4, p))
    bars.append((105, 110.4, 110.0, 110.2))   # A: low 110.0
    bars.append((108, 109.0, 106.0, 107.0))   # B
    bars.append((107, 109.6, 109.6, 109.0))   # C: high 109.6 → gap = 110.0-109.6 = 0.4 (< filter)
    bars.append((109, 112.0, 109.0, 111.0))   # would-be violation
    bars.append((111, 112.0, 110.0, 111.5))   # would-be retest
    fired2 = _feed(strat2, bars, atr)
    assert fired2 is None, f"sub-threshold gap must not trade, but fired {fired2}"
    print("✓ Gap filter rejects sub-0.75×ATR imbalance (no zone, no trade)")

    # ── 3. EMA trend gate blocks a counter-trend retest ───────────────────────
    # Identical gap→flip→retest, but inside a long steady DOWNTREND. A slow EMA(20)
    # lags well above spot, so the long retest (close < EMA) must be rejected.
    strat3 = IfvgStrategy(min_gap_atr=0.75, rr=2.0, ema_period=20)
    bars = []
    for k in range(26):                        # 200 → 150 steady decline (EMA stays ~160+)
        p = 200 - 2 * k
        bars.append((p, p + 0.4, p - 0.4, p))
    bars.append((149, 150.0, 148.0, 149.0))    # A: low 148  (zone top)
    bars.append((147, 148.0, 145.0, 146.0))    # B
    bars.append((146, 146.0, 145.0, 145.5))    # C: high 146 → gap = 148-146 = 2.0
    bars.append((147, 149.0, 147.0, 148.5))    # D: close 148.5 > 148 → flip to support
    bars.append((148, 149.0, 147.0, 148.2))    # E: retest, but close 148.2 << EMA(~160)
    fired3 = _feed(strat3, bars, atr)
    assert fired3 is None, f"counter-trend retest must be blocked, fired {fired3}"
    print("✓ EMA trend gate blocks counter-trend long retest")

    # ── 4. Insufficient data → no signal, no crash ────────────────────────────
    strat4 = IfvgStrategy(min_gap_atr=0.75)
    df = pd.DataFrame(
        {"open": [100, 101], "high": [101, 102], "low": [99, 100],
         "close": [100.5, 101.5], "volume": [1.0, 1.0]},
        index=pd.date_range("2025-01-01", periods=2, freq="1h", tz="UTC"),
    )
    sig = strat4.analyze(df, 1.0)
    assert sig.direction == 0, "too-short frame should be no-trade"
    print(f"✓ Insufficient data handled: {sig.reason}")

    # ── 5. Robust default: the shipped gap filter is 0.75×ATR ──────────────────
    from strategies.ifvg import DEFAULT_MIN_GAP_ATR
    assert abs(DEFAULT_MIN_GAP_ATR - 0.75) < 1e-9, DEFAULT_MIN_GAP_ATR
    assert abs(IfvgStrategy()._min_gap - 0.75) < 1e-9
    print(f"✓ Robust default gap filter = {DEFAULT_MIN_GAP_ATR}×ATR")

    print("\n" + "=" * 62)
    print("✓ IFVG SLEEVE CORRECT — gap→flip→retest, filter, trend gate, geometry")
    print("=" * 62)


if __name__ == "__main__":
    _run()
