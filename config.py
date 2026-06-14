from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _get(key: str, default: str | None = None) -> str:
    val = os.getenv(key, default)
    if val is None:
        raise ValueError(f"Missing required env var: {key}")
    return val


def _getfloat(key: str, default: float | None = None) -> float:
    raw = os.getenv(key)
    if raw is None:
        if default is not None:
            return default
        raise ValueError(f"Missing required env var: {key}")
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"Invalid float for {key}: {raw!r}")


def _getint(key: str, default: int | None = None) -> int:
    raw = os.getenv(key)
    if raw is None:
        if default is not None:
            return default
        raise ValueError(f"Missing required env var: {key}")
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"Invalid int for {key}: {raw!r}")


def _getbool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("true", "1", "yes")


def _normalize_symbol(sym: str) -> str:
    """Normalise a coin/symbol into the MEXC linear-perp form BASE/USDT:USDT.
    Accepts 'BTC', 'BTC/USDT', or already-correct 'BTC/USDT:USDT'."""
    s = sym.strip().upper()
    if ":" in s:
        return s
    if "/" in s:
        return f"{s}:USDT"
    return f"{s}/USDT:USDT"


@dataclass
class ExchangeConfig:
    api_key: str
    api_secret: str
    paper_mode: bool
    leverage: int
    margin_mode: str
    symbol: str                       # primary symbol (kept for backward compat)
    symbols: list[str] | None = None  # full list when trading multiple coins
    base_currency: str = "USDT"
    maker_entry: bool = True   # use post-only limit entries (0% maker fee vs 0.01% taker)


@dataclass
class RiskConfig:
    max_risk_per_trade: float
    atr_sl_multiplier: float
    rr_ratio: float
    max_positions: int
    daily_max_loss: float
    max_hold_candles: int = 48  # force-close after N candles (48h on 1h timeframe)
    # Confidence sizing: scale position size DOWN on weaker signals (never above
    # the validated full risk). Opt-in so it can't disturb the proven edge.
    confidence_sizing: bool = False
    # position_cap_fraction: max notional as a fraction of balance (1.0 = full
    # balance, 0.5 = old default). Raising this together with max_risk_per_trade
    # unlocks higher position sizes; backtest shows 8% risk + 1.0 cap ≈ +3.2%/mo
    # at DD 20.5% — the best risk-adjusted step up from the 3% default.
    position_cap_fraction: float = 1.0
    # fixed_margin_usdt: when > 0, caps margin per trade at this fixed dollar
    # amount regardless of balance growth. Produces better Calmar than percentage-
    # based sizing because losses stay bounded even as balance compounds up.
    # Backtest: $200 fixed @ 10x lev → +14.9%/mo DD 55%, Calmar 0.27 (best found).
    # Set to 0 to use percentage-based sizing (position_cap_fraction).
    fixed_margin_usdt: float = 0.0
    # Day trading sleeves (ORB, Asia BO): use a smaller per-trade risk and a
    # shorter max-hold so they don't lock up capital overnight. Each sleeve has
    # its own risk % (validated separately): ORB carries more weight than Asia BO.
    day_risk_pct: float = 0.01        # fallback day-trade risk if per-sleeve unset
    orb_risk_pct: float = 0.05        # ORB risk per trade (% of free balance)
    asia_risk_pct: float = 0.03       # Asia BO risk per trade (% of free balance)
    day_max_hold_candles: int = 6     # force-close after 6h (intraday only)
    # Trailing stop: move SL to breakeven after breakeven_atr_mult×ATR profit,
    # then trail at trailing_atr_mult×ATR below peak price.
    trailing_stop_enabled: bool = True
    breakeven_atr_mult: float = 1.0   # after 1×ATR profit → SL to entry
    trailing_atr_mult: float = 2.0    # trail SL at 2×ATR below peak
    # Market regime filter: ADX-based strategy routing.
    # Trending (ADX>28) → suppress BB mean-reversion (counter-trend trades fail).
    # Ranging  (ADX<20) → suppress ORB/S/R breakouts (false-breakout rate spikes).
    regime_filter_enabled: bool = True
    adx_trending_threshold: float = 28.0
    adx_ranging_threshold: float = 20.0
    # Consecutive loss cooldown: after N back-to-back losses pause new entries.
    consecutive_loss_limit: int = 2
    cooldown_minutes: int = 240


@dataclass
class StrategyConfig:
    ema_fast: int = 9
    ema_slow: int = 21
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bb_period: int = 20
    bb_std: float = 2.0
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    atr_period: int = 14
    adx_period: int = 14
    sr_lookback: int = 50
    sr_min_touches: int = 2
    volume_spike_mult: float = 1.5
    vol_filter_enabled: bool = True   # require above-avg volume on BB extreme candle
    primary_tf: str = "1h"            # validated edge is on the 1h timeframe
    confirm_tf: str = "4h"
    # Funding rate / open interest monitoring (live-only — not in historical CSVs,
    # so it cannot be backtested). Ships disabled; "monitor" logs alongside every
    # signal to build a real dataset before it is allowed to affect trades.
    funding_enabled: bool = False
    funding_mode: str = "monitor"     # "monitor" (log only) | "filter" (skip contrarian) | "boost"
    funding_extreme: float = 0.0005   # |funding| above this per interval = crowded positioning
    sniper_min_grade: int = 0         # 0=off, 1/2/3 = min confluence score to trade
    # Order-flow collector (live-only, monitor-first). Uses watchTrades +
    # fetchOrderBook to log taker delta + depth imbalance alongside each signal.
    # Cannot be backtested → ships OFF; never affects trades, only builds a
    # forward dataset to validate before any future order-flow rule.
    orderflow_enabled: bool = False
    orderflow_mode: str = "monitor"
    orderflow_window_min: float = 15.0
    # Intraday breakout strategies (validated edge: ORB PF 1.44, Asia BO PF 2.15)
    orb_enabled: bool = True
    asia_bo_enabled: bool = True
    # S/R breakout (swing momentum, validated: lb80 touch3 SL3ATR RR3.0 PF 1.72).
    # Uses the normal 48h max-hold + full risk (it's a swing trade, not intraday).
    sr_breakout_enabled: bool = True


@dataclass
class TelegramConfig:
    token: str
    chat_id: str
    enabled: bool


@dataclass
class AppConfig:
    exchange: ExchangeConfig
    risk: RiskConfig
    strategy: StrategyConfig
    telegram: TelegramConfig
    db_path: str
    log_level: str
    paper_initial_balance: float
    heartbeat_hours: float = 6.0


def load_config() -> AppConfig:
    # SYMBOLS (comma-separated) enables multi-coin trading; falls back to the
    # single SYMBOL. Each entry is normalised to the MEXC perp form BASE/USDT:USDT.
    # Accepts "BTC", "BTC/USDT", or "BTC/USDT:USDT".
    primary_symbol = _get("SYMBOL", "BTC/USDT:USDT")
    raw_symbols = os.getenv("SYMBOLS", "").strip()
    if raw_symbols:
        symbols = [_normalize_symbol(s) for s in raw_symbols.split(",") if s.strip()]
    else:
        symbols = [_normalize_symbol(primary_symbol)]

    exchange = ExchangeConfig(
        api_key=_get("MEXC_API_KEY", ""),
        api_secret=_get("MEXC_API_SECRET", ""),
        paper_mode=_getbool("PAPER_MODE", True),
        leverage=_getint("LEVERAGE", 10),
        margin_mode=_get("MARGIN_MODE", "isolated"),
        symbol=symbols[0],
        symbols=symbols,
        maker_entry=_getbool("MAKER_ENTRY", True),
    )

    risk = RiskConfig(
        max_risk_per_trade=_getfloat("MAX_RISK_PCT", 0.02),
        atr_sl_multiplier=_getfloat("ATR_SL_MULT", 3.0),   # validated: 3x ATR stop
        rr_ratio=_getfloat("RR_RATIO", 1.667),             # TP = 5x ATR (3.0 * 1.667)
        max_positions=_getint("MAX_POSITIONS", 1),
        daily_max_loss=_getfloat("DAILY_MAX_LOSS_PCT", 0.05),
        max_hold_candles=_getint("MAX_HOLD_CANDLES", 48),
        confidence_sizing=_getbool("CONFIDENCE_SIZING", False),
        position_cap_fraction=_getfloat("POSITION_CAP_FRACTION", 1.0),
        fixed_margin_usdt=_getfloat("FIXED_MARGIN_USDT", 0.0),
        day_risk_pct=_getfloat("DAY_RISK_PCT", 0.01),
        orb_risk_pct=_getfloat("ORB_RISK_PCT", 0.05),
        asia_risk_pct=_getfloat("ASIA_RISK_PCT", 0.03),
        day_max_hold_candles=_getint("DAY_MAX_HOLD_CANDLES", 6),
        trailing_stop_enabled=_getbool("TRAILING_STOP_ENABLED", True),
        breakeven_atr_mult=_getfloat("BREAKEVEN_ATR_MULT", 1.0),
        trailing_atr_mult=_getfloat("TRAILING_ATR_MULT", 2.0),
        regime_filter_enabled=_getbool("REGIME_FILTER_ENABLED", True),
        adx_trending_threshold=_getfloat("ADX_TRENDING_THRESHOLD", 28.0),
        adx_ranging_threshold=_getfloat("ADX_RANGING_THRESHOLD", 20.0),
        consecutive_loss_limit=_getint("CONSECUTIVE_LOSS_LIMIT", 2),
        cooldown_minutes=_getint("COOLDOWN_MINUTES", 240),
    )

    strategy = StrategyConfig(
        primary_tf=_get("PRIMARY_TF", "1h"),
        confirm_tf=_get("CONFIRM_TF", "4h"),
        vol_filter_enabled=_getbool("VOL_FILTER_ENABLED", True),
        funding_enabled=_getbool("FUNDING_ENABLED", False),
        funding_mode=_get("FUNDING_MODE", "monitor"),
        funding_extreme=_getfloat("FUNDING_EXTREME", 0.0005),
        sniper_min_grade=_getint("SNIPER_MIN_GRADE", 0),
        orderflow_enabled=_getbool("ORDERFLOW_ENABLED", False),
        orderflow_mode=_get("ORDERFLOW_MODE", "monitor"),
        orderflow_window_min=_getfloat("ORDERFLOW_WINDOW_MIN", 15.0),
        orb_enabled=_getbool("ORB_ENABLED", True),
        asia_bo_enabled=_getbool("ASIA_BO_ENABLED", True),
        sr_breakout_enabled=_getbool("SR_BREAKOUT_ENABLED", True),
    )

    telegram = TelegramConfig(
        enabled=_getbool("TELEGRAM_ENABLED", False),
        token=_get("TELEGRAM_TOKEN", ""),
        chat_id=_get("TELEGRAM_CHAT_ID", ""),
    )

    if not exchange.paper_mode and (not exchange.api_key or not exchange.api_secret):
        raise ValueError("MEXC_API_KEY and MEXC_API_SECRET required for live trading")

    return AppConfig(
        exchange=exchange,
        risk=risk,
        strategy=strategy,
        telegram=telegram,
        db_path=_get("DB_PATH", "./trades.db"),
        log_level=_get("LOG_LEVEL", "INFO"),
        paper_initial_balance=_getfloat("PAPER_INITIAL_BALANCE", 10000.0),
        heartbeat_hours=_getfloat("HEARTBEAT_HOURS", 6.0),
    )
