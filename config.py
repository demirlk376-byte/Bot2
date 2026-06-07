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
    )

    strategy = StrategyConfig(
        primary_tf=_get("PRIMARY_TF", "1h"),
        confirm_tf=_get("CONFIRM_TF", "4h"),
        vol_filter_enabled=_getbool("VOL_FILTER_ENABLED", True),
        funding_enabled=_getbool("FUNDING_ENABLED", False),
        funding_mode=_get("FUNDING_MODE", "monitor"),
        funding_extreme=_getfloat("FUNDING_EXTREME", 0.0005),
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
    )
