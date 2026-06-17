"""
Whale-flow strategy — average-trade-size z-spike, follow the candle.

EDGE (research_microstructure.py, Binance 1m klines, honest TRAIN/TEST + year-by-year):
  avg_size = quote_volume / trade_count  (büyük = balina/kurumsal aktivite)
  WHALE z2.5 SL2.0 RR1.5 + body>=0.5ATR (BTC 1h 2023-2026):
    PF 1.48, 203 trades, POSITIVE EVERY YEAR:
      2023 PF 1.13 | 2024 PF 2.50 | 2025 PF 1.05 | 2026 PF 1.15
    (test period 2026 positive). PF in line with ORB 1.44 / FVG 1.37.
  Plain z2.0 RR2.0 (no body filter) was only PF 1.17 — the body filter lifts it.
  ETH backtest too weak/thin → BTC-only.

LOGIC:
  • When a 1h candle's average trade size spikes (z-score ≥ threshold over the
    trailing `zwin` hours), aggressive size = institutional commitment. Trade in
    the candle's own direction (bullish close>open → long; bearish → short).
  • Body filter: the candle's body |close-open| must be ≥ min_body_atr × ATR —
    whale size must coincide with a real directional move, not one big fill in a
    quiet candle. This lifts PF from 1.17 to 1.48.
  • SL = entry ± sl_atr × ATR.  TP = entry ± rr × (SL distance).
  • One signal per qualifying candle.

WHY IT WORKS (hypothesis):
  Retail trades small; whales/desks trade big. A candle whose AVERAGE fill size
  is abnormally large means informed size is being deployed — and informed size
  tends to be on the right side of the next move. Raw volume can't see this (a
  volume spike can be a thousand retail panic clicks); only average size, which
  needs the trade COUNT, separates whales from the crowd.

DATA NOTE:
  MEXC futures klines do NOT carry trade count, so avg_size cannot be derived
  from OHLCV. It is supplied live by whale_flow.WhaleFlowMonitor, which buckets
  watch_trades into hourly (count, quote_volume) and z-scores avg_size. This
  module is pure: it takes the precomputed z-score and the candle, nothing else.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WhaleSignal:
    direction: int        # +1 long | -1 short | 0 none
    strength: float       # 0.0 – 1.0
    reason: str
    sl_price: float = 0.0
    tp_price: float = 0.0
    entry_price: float = 0.0
    z: float = 0.0


class WhaleStrategy:
    """Pure whale-flow signal. analyze() is called on a closed 1h candle with the
    avg-trade-size z-score from the live aggregator."""

    def __init__(self, z_threshold: float = 2.5, sl_atr: float = 2.0,
                 rr: float = 1.5, min_body_atr: float = 0.5):
        self._z = z_threshold
        self._sl_atr = sl_atr
        self._rr = rr
        self._min_body = min_body_atr

    def analyze(
        self, open_price: float, close_price: float, avg_size_z: float, atr_val: float
    ) -> WhaleSignal:
        if atr_val <= 0:
            return WhaleSignal(0, 0.0, "ATR not available")
        if avg_size_z is None:
            return WhaleSignal(0, 0.0, "no avg_size z-score (warming up)")
        if avg_size_z < self._z:
            return WhaleSignal(0, 0.0, f"avg_size z={avg_size_z:.2f} < {self._z}")

        # Body filter: whale size must coincide with a real directional move.
        body = abs(close_price - open_price)
        if self._min_body > 0 and body < self._min_body * atr_val:
            return WhaleSignal(0, 0.0,
                               f"body {body:.2f} < {self._min_body}×ATR (quiet candle)")

        # Follow the candle's direction.
        if close_price > open_price:
            direction = 1
        elif close_price < open_price:
            direction = -1
        else:
            return WhaleSignal(0, 0.0, "doji (close==open)")

        entry = close_price
        sl_d = self._sl_atr * atr_val
        sl = entry - direction * sl_d
        tp = entry + direction * self._rr * sl_d
        side = "long" if direction == 1 else "short"
        return WhaleSignal(
            direction=direction,
            strength=min(1.0, 0.6 + 0.1 * (avg_size_z - self._z)),
            reason=f"whale {side}: avg_size z={avg_size_z:.2f}",
            sl_price=sl, tp_price=tp, entry_price=entry, z=avg_size_z,
        )
