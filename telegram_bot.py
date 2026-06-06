from __future__ import annotations

import logging
from typing import Optional

from config import TelegramConfig
from risk import TradeSetup
from strategies.signal_combiner import CombinedSignal

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, config: TelegramConfig):
        self._cfg = config
        self._bot = None

    async def initialize(self) -> None:
        if not self._cfg.enabled:
            return
        try:
            from telegram import Bot
            self._bot = Bot(token=self._cfg.token)
            await self._bot.get_me()
            await self.send_alert("BTC Trading Bot started", "INFO")
            logger.info("Telegram notifier initialized")
        except Exception as e:
            logger.warning("Telegram init failed: %s", e)
            self._bot = None

    async def _send(self, text: str) -> None:
        if not self._bot or not self._cfg.enabled:
            return
        try:
            await self._bot.send_message(
                chat_id=self._cfg.chat_id,
                text=text,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning("Telegram send failed: %s", e)

    async def send_trade_opened(self, setup: TradeSetup, signal: CombinedSignal) -> None:
        direction = "LONG" if setup.direction == 1 else "SHORT"
        emoji = "" if setup.direction == 1 else ""
        sl_pct = (setup.sl_price - setup.entry_price) / setup.entry_price * 100
        tp_pct = (setup.tp_price - setup.entry_price) / setup.entry_price * 100
        text = (
            f"{emoji} <b>{direction} OPENED</b> - {setup.symbol}\n"
            f"Entry: <code>${setup.entry_price:,.2f}</code>\n"
            f"SL: <code>${setup.sl_price:,.2f}</code> ({sl_pct:+.2f}%)\n"
            f"TP: <code>${setup.tp_price:,.2f}</code> ({tp_pct:+.2f}%)\n"
            f"Qty: <code>{setup.quantity:.4f} BTC</code> | Risk: <code>${setup.risk_usdt:.2f} ({setup.risk_pct:.1%})</code>\n"
            f"Confidence: <code>{signal.confidence:.0%}</code> | Strategy: <code>{signal.dominant_strategy}</code>"
        )
        await self._send(text)

    async def send_trade_closed(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        pnl_usdt: float,
        reason: str,
    ) -> None:
        emoji = "" if pnl_usdt >= 0 else ""
        pnl_pct = (exit_price - entry_price) / entry_price * 100 * (1 if side == "long" else -1)
        text = (
            f"{emoji} <b>TRADE CLOSED</b> - {symbol}\n"
            f"Side: <code>{side.upper()}</code>\n"
            f"Entry: <code>${entry_price:,.2f}</code> → Exit: <code>${exit_price:,.2f}</code>\n"
            f"PnL: <code>${pnl_usdt:+.2f} ({pnl_pct:+.2f}%)</code>\n"
            f"Reason: <code>{reason}</code>"
        )
        await self._send(text)

    async def send_daily_summary(
        self,
        total_trades: int,
        winning_trades: int,
        total_pnl: float,
        balance: float,
    ) -> None:
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
        emoji = "" if total_pnl >= 0 else ""
        text = (
            f"{emoji} <b>Daily Summary</b>\n"
            f"Trades: <code>{total_trades}</code> | Win Rate: <code>{win_rate:.0%}</code>\n"
            f"Daily PnL: <code>${total_pnl:+.2f}</code>\n"
            f"Balance: <code>${balance:,.2f}</code>"
        )
        await self._send(text)

    async def send_daily_loss_warning(self, loss_pct: float) -> None:
        text = (
            f" <b>DAILY LOSS LIMIT HIT</b>\n"
            f"Loss: <code>{loss_pct:.1%}</code>\n"
            f"Trading halted for today."
        )
        await self._send(text)

    async def send_alert(self, message: str, level: str = "INFO") -> None:
        emoji_map = {"INFO": "", "WARNING": "⚠️", "ERROR": ""}
        emoji = emoji_map.get(level, "")
        await self._send(f"{emoji} <b>[{level}]</b> {message}")
