"""
Vectorized fast backtester for large multi-month datasets.

Precomputes ALL indicators once on the full series (O(n) instead of O(n^2)),
then walks through candles reading precomputed values. The scoring logic
mirrors the strategy modules in strategies/ exactly, so backtest results
are representative of live behavior.

Why a separate backtester: the strategy modules recompute indicators on
growing DataFrame slices every candle, which is fine live (one call per
5 minutes) but O(n^2) for backtests over 100k+ candles.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from config import AppConfig
from indicators import ema, macd, bollinger_bands, rsi, atr, adx, bb_width
from risk import RiskManager, MIN_BTC_ORDER


@dataclass
class FastTrade:
    direction: int
    entry_price: float
    exit_price: float
    quantity: float
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp
    pnl_usdt: float
    exit_reason: str
    dominant: str


@dataclass
class FastResult:
    total_trades: int
    winning_trades: int
    win_rate: float
    total_pnl_usdt: float
    total_pnl_pct: float
    max_drawdown: float
    profit_factor: float
    sharpe: float
    avg_trade_pnl: float
    trades: list[FastTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)


def _precompute(df: pd.DataFrame, cfg) -> pd.DataFrame:
    """Attach all indicator columns to a 5m frame."""
    out = df.copy()
    out["ema_fast"] = ema(df["close"], cfg.ema_fast)
    out["ema_slow"] = ema(df["close"], cfg.ema_slow)
    macd_line, signal_line, hist = macd(df["close"], cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
    out["macd_hist"] = hist
    bb_u, bb_m, bb_l = bollinger_bands(df["close"], cfg.bb_period, cfg.bb_std)
    out["bb_upper"] = bb_u
    out["bb_lower"] = bb_l
    out["rsi"] = rsi(df["close"], cfg.rsi_period)
    out["atr"] = atr(df["high"], df["low"], df["close"], cfg.atr_period)
    out["adx"] = adx(df["high"], df["low"], df["close"], cfg.adx_period)
    out["bb_width"] = bb_width(df["close"], cfg.bb_period, cfg.bb_std)
    out["bb_width_avg"] = out["bb_width"].rolling(cfg.bb_period).mean()
    out["vol_avg"] = df["volume"].rolling(20).mean()
    return out


class FastBacktester:
    FEE_RATE = 0.0001
    SLIPPAGE = 0.0005
    MIN_ATR_PCT = 0.0012
    TRAIL_BREAKEVEN_ATR = 1.5
    TRAIL_LOCK_ATR = 2.5
    TRAIL_LOCK_BUFFER = 0.4

    # Trend strategy params (mirror strategies/trend.py)
    PULLBACK_TOUCH_PCT = 0.002
    MIN_SEPARATION = 0.002

    ENTRY_THRESHOLD = 0.42
    CONFLICT_STRENGTH = 0.6

    def __init__(self, config: AppConfig):
        self._cfg = config
        self._scfg = config.strategy
        self._risk = RiskManager(config.risk)

    # ----- per-candle strategy scoring (vectorized inputs) -----

    def _trend_signal(self, w: pd.DataFrame, conf_aligned: int) -> tuple[int, float]:
        """w = window slice ending at current candle (small, for cross/pullback lookback)."""
        row = w.iloc[-1]
        sep = (row["ema_fast"] - row["ema_slow"]) / row["ema_slow"]
        bull = bear = 0.0
        cross = "none"

        # Fresh crossover in last 3 bars
        ef = w["ema_fast"].values
        es = w["ema_slow"].values
        for k in range(max(1, len(w) - 3), len(w)):
            if ef[k - 1] <= es[k - 1] and ef[k] > es[k]:
                cross = "bull"
                break
            if ef[k - 1] >= es[k - 1] and ef[k] < es[k]:
                cross = "bear"
                break

        if cross == "bull":
            bull += 0.4
        elif cross == "bear":
            bear += 0.4
        elif abs(sep) >= self.MIN_SEPARATION:
            price = row["close"]
            ema_f = row["ema_fast"]
            tol = ema_f * self.PULLBACK_TOUCH_PCT
            if sep > 0:
                touched = w["low"].iloc[-4:-1].min() <= ema_f + tol
                if touched and price > ema_f:
                    bull += 0.30
                    cross = "pullback"
            else:
                touched = w["high"].iloc[-4:-1].max() >= ema_f - tol
                if touched and price < ema_f:
                    bear += 0.30
                    cross = "pullback"

        # 15m alignment
        if conf_aligned == 1:
            bull += 0.2
        elif conf_aligned == -1:
            bear += 0.2

        # MACD histogram
        h0 = w["macd_hist"].iloc[-1]
        h1 = w["macd_hist"].iloc[-2]
        if h0 > 0 and h0 > h1:
            bull += 0.2
        elif h0 < 0 and h0 < h1:
            bear += 0.2

        # ADX
        adx_v = row["adx"]
        if not np.isnan(adx_v):
            if adx_v > 25:
                if bull > bear:
                    bull += 0.2
                elif bear > bull:
                    bear += 0.2
            elif adx_v < 18:
                bull *= 0.65
                bear *= 0.65

        # RSI extreme guard
        rsi_v = row["rsi"]
        if not np.isnan(rsi_v):
            if rsi_v > 68 and bull > bear:
                bull *= 0.55
            elif rsi_v < 32 and bear > bull:
                bear *= 0.55

        if bull > bear and bull > 0.18:
            return 1, min(bull, 1.0)
        if bear > bull and bear > 0.18:
            return -1, min(bear, 1.0)
        return 0, 0.0

    def _mean_rev_signal(self, row, conf_rsi: float) -> tuple[int, float]:
        bull = bear = 0.0
        squeeze = (not np.isnan(row["bb_width"]) and not np.isnan(row["bb_width_avg"])
                   and row["bb_width"] < row["bb_width_avg"] * 0.7)
        bb_sig = "none"
        if row["close"] < row["bb_lower"]:
            bull += 0.35
            bb_sig = "below"
        elif row["close"] > row["bb_upper"]:
            bear += 0.35
            bb_sig = "above"

        if not np.isnan(row["rsi"]):
            if row["rsi"] < self._scfg.rsi_oversold:
                bull += 0.35
            elif row["rsi"] > self._scfg.rsi_overbought:
                bear += 0.35

        if not np.isnan(conf_rsi):
            if conf_rsi < 40 and bb_sig == "below":
                bull += 0.15
            elif conf_rsi > 60 and bb_sig == "above":
                bear += 0.15

        if squeeze:
            bull *= 0.5
            bear *= 0.5

        if bull > bear and bull > 0.1:
            return 1, min(bull, 1.0)
        if bear > bull and bear > 0.1:
            return -1, min(bear, 1.0)
        return 0, 0.0

    def _breakout_signal(self, w: pd.DataFrame, sr_high: float, sr_low: float) -> tuple[int, float]:
        """Simplified S/R using recent rolling extremes (sr_high/sr_low precomputed)."""
        row = w.iloc[-1]
        prev = w.iloc[-2]
        bull = bear = 0.0
        min_break = row["close"] * 0.002

        vol_spike = (not np.isnan(row["vol_avg"])
                     and row["volume"] > row["vol_avg"] * self._scfg.volume_spike_mult)
        squeeze = (not np.isnan(row["bb_width"]) and not np.isnan(row["bb_width_avg"])
                   and row["bb_width"] < row["bb_width_avg"] * 0.7)

        rng = row["high"] - row["low"]
        body = abs(row["close"] - row["open"])
        body_ratio = body / rng if rng > 0 else 0

        # Breakout above recent resistance
        if row["close"] > sr_high + min_break and prev["close"] <= sr_high:
            bull += 0.4
            if body_ratio > 0.6:
                bull += 0.1
        # Breakdown below recent support
        elif row["close"] < sr_low - min_break and prev["close"] >= sr_low:
            bear += 0.4
            if body_ratio > 0.6:
                bear += 0.1

        if bull == 0 and bear == 0:
            return 0, 0.0

        if vol_spike:
            if bull > bear:
                bull += 0.3
            else:
                bear += 0.3

        adx_v = row["adx"]
        if not np.isnan(adx_v) and adx_v > 20:
            if bull > bear:
                bull += 0.1
            else:
                bear += 0.1

        if squeeze:
            bull = max(bull - 0.3, 0.0)
            bear = max(bear - 0.3, 0.0)

        if bull > bear and bull > 0.1:
            return 1, min(bull, 1.0)
        if bear > bull and bear > 0.1:
            return -1, min(bear, 1.0)
        return 0, 0.0

    def _combine(self, t, m, b, adx_v, htf_bias) -> tuple[int, float, str]:
        t_dir, t_str = t
        m_dir, m_str = m
        b_dir, b_str = b

        if adx_v > 25:
            wt, wb, wm = 0.50, 0.35, 0.15
        elif adx_v < 20:
            wt, wb, wm = 0.20, 0.25, 0.55
        else:
            wt, wb, wm = 0.40, 0.35, 0.25

        t_eff = t_dir * t_str
        m_eff = m_dir * m_str
        b_eff = b_dir * b_str
        weighted = t_eff * wt + m_eff * wm + b_eff * wb

        # Conflict
        sigs = [("trend", t_dir, t_str), ("mean_rev", m_dir, m_str), ("breakout", b_dir, b_str)]
        if weighted > 0:
            opp = [s for s in sigs if s[1] < 0 and s[2] >= self.CONFLICT_STRENGTH]
        else:
            opp = [s for s in sigs if s[1] > 0 and s[2] >= self.CONFLICT_STRENGTH]
        if opp:
            return 0, 0.0, "conflict"

        # htf soft penalty
        if htf_bias != 0 and weighted != 0:
            if (htf_bias > 0 and weighted < 0) or (htf_bias < 0 and weighted > 0):
                weighted *= 0.85

        if abs(weighted) < self.ENTRY_THRESHOLD:
            return 0, 0.0, "below_threshold"

        direction = 1 if weighted > 0 else -1
        contribs = [("trend", abs(t_eff * wt)), ("mean_rev", abs(m_eff * wm)), ("breakout", abs(b_eff * wb))]
        dominant = max(contribs, key=lambda x: x[1])[0]
        return direction, min(abs(weighted), 1.0), dominant

    def run(self, df_5m_raw: pd.DataFrame, df_15m_raw: pd.DataFrame,
            df_1h_raw: pd.DataFrame, initial_balance: float = 10000.0) -> FastResult:
        cfg = self._scfg
        df = _precompute(df_5m_raw, cfg)

        # 15m confirmation: precompute EMA stack alignment + RSI, reindexed to 5m
        df15 = df_15m_raw.copy()
        ema_f15 = ema(df15["close"], cfg.ema_fast)
        ema_s15 = ema(df15["close"], cfg.ema_slow)
        align15 = pd.Series(np.where(ema_f15 > ema_s15, 1, -1), index=df15.index)
        rsi15 = rsi(df15["close"], cfg.rsi_period)
        align15_5m = align15.reindex(df.index, method="ffill")
        rsi15_5m = rsi15.reindex(df.index, method="ffill")

        # 1h bias: EMA20 vs EMA50 cross, reindexed to 5m
        df1h = df_1h_raw.copy()
        ema20_1h = ema(df1h["close"], 20)
        ema50_1h = ema(df1h["close"], 50)
        bias1h = pd.Series(np.where(ema20_1h > ema50_1h, 1, -1), index=df1h.index)
        bias1h_5m = bias1h.reindex(df.index, method="ffill").fillna(0)

        # S/R via rolling extremes on 5m (lookback window)
        sr_high = df["high"].rolling(cfg.sr_lookback).max().shift(1)
        sr_low = df["low"].rolling(cfg.sr_lookback).min().shift(1)

        balance = initial_balance
        equity = [balance]
        trades: list[FastTrade] = []
        open_t: Optional[dict] = None
        leverage = self._cfg.exchange.leverage

        n = len(df)
        warmup = 60
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        atrs = df["atr"].values
        adxs = df["adx"].values

        for i in range(warmup, n):
            # --- manage open trade ---
            if open_t is not None:
                d = open_t["dir"]
                entry = open_t["entry"]
                qty = open_t["qty"]
                atr_e = open_t["atr_e"]
                tp = open_t["tp"]
                sl = open_t["trail_sl"]

                # trailing stop update
                if d == 1:
                    fav = highs[i] - entry
                    if fav >= atr_e * self.TRAIL_LOCK_ATR:
                        sl = max(sl, entry + atr_e * self.TRAIL_LOCK_BUFFER)
                    elif fav >= atr_e * self.TRAIL_BREAKEVEN_ATR:
                        sl = max(sl, entry)
                else:
                    fav = entry - lows[i]
                    if fav >= atr_e * self.TRAIL_LOCK_ATR:
                        sl = min(sl, entry - atr_e * self.TRAIL_LOCK_BUFFER)
                    elif fav >= atr_e * self.TRAIL_BREAKEVEN_ATR:
                        sl = min(sl, entry)
                open_t["trail_sl"] = sl

                exit_p = None
                reason = None
                if d == 1:
                    if lows[i] <= sl:
                        exit_p = sl
                        reason = "sl_hit" if sl < entry else "breakeven"
                    elif highs[i] >= tp:
                        exit_p = tp
                        reason = "tp_hit"
                else:
                    if highs[i] >= sl:
                        exit_p = sl
                        reason = "sl_hit" if sl > entry else "breakeven"
                    elif lows[i] <= tp:
                        exit_p = tp
                        reason = "tp_hit"

                if exit_p is not None:
                    raw = d * (exit_p - entry) * qty
                    fees = (entry + exit_p) * qty * self.FEE_RATE
                    net = raw - fees
                    balance += net
                    equity.append(balance)
                    trades.append(FastTrade(
                        direction=d, entry_price=entry, exit_price=exit_p, quantity=qty,
                        entry_ts=open_t["entry_ts"], exit_ts=df.index[i],
                        pnl_usdt=net, exit_reason=reason, dominant=open_t["dom"],
                    ))
                    open_t = None
                continue

            # --- look for new entry ---
            atr_v = atrs[i]
            adx_v = adxs[i]
            if np.isnan(atr_v) or np.isnan(adx_v) or atr_v <= 0:
                continue
            if atr_v / closes[i] < self.MIN_ATR_PCT:
                continue

            w = df.iloc[i - 5:i + 1]  # small window for cross/pullback lookback
            row = df.iloc[i]

            t_sig = self._trend_signal(w, int(align15_5m.iloc[i]) if not np.isnan(align15_5m.iloc[i]) else 0)
            m_sig = self._mean_rev_signal(row, rsi15_5m.iloc[i])
            srh = sr_high.iloc[i]
            srl = sr_low.iloc[i]
            if np.isnan(srh) or np.isnan(srl):
                b_sig = (0, 0.0)
            else:
                b_sig = self._breakout_signal(w, srh, srl)

            htf = int(bias1h_5m.iloc[i])
            direction, conf, dom = self._combine(t_sig, m_sig, b_sig, adx_v, htf)

            if direction == 0:
                continue

            # Hard gates (mirror backtester.py)
            if adx_v < 20 and dom in ("trend", "breakout"):
                continue
            if htf != 0 and dom in ("trend", "breakout") and direction != htf:
                continue

            entry_price = closes[i] * (1 + self.SLIPPAGE)
            setup = self._risk.build_trade_setup(
                direction=direction, entry_price=entry_price, atr=atr_v,
                balance=balance, leverage=leverage, symbol=self._cfg.exchange.symbol,
            )
            if setup is None:
                continue

            balance -= entry_price * setup.quantity * self.FEE_RATE
            open_t = {
                "dir": direction, "entry": entry_price, "qty": setup.quantity,
                "sl": setup.sl_price, "trail_sl": setup.sl_price, "tp": setup.tp_price,
                "atr_e": atr_v, "entry_ts": df.index[i], "dom": dom,
            }

        return self._result(trades, initial_balance, equity)

    def _result(self, trades, initial_balance, equity) -> FastResult:
        if not trades:
            return FastResult(0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, [], equity)
        pnls = [t.pnl_usdt for t in trades]
        wins = sum(1 for p in pnls if p > 0)
        gp = sum(p for p in pnls if p > 0)
        gl = abs(sum(p for p in pnls if p < 0))
        pf = gp / gl if gl > 0 else float("inf")

        peak = initial_balance
        run = initial_balance
        max_dd = 0.0
        for t in trades:
            run += t.pnl_usdt
            peak = max(peak, run)
            dd = (peak - run) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)

        arr = np.array(pnls)
        sharpe = (arr.mean() / arr.std() * np.sqrt(len(arr))) if arr.std() > 0 else 0.0

        return FastResult(
            total_trades=len(trades), winning_trades=wins,
            win_rate=wins / len(trades), total_pnl_usdt=sum(pnls),
            total_pnl_pct=sum(pnls) / initial_balance, max_drawdown=max_dd,
            profit_factor=pf, sharpe=sharpe, avg_trade_pnl=sum(pnls) / len(trades),
            trades=trades, equity_curve=equity,
        )
