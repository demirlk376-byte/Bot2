from __future__ import annotations

import logging
from typing import Optional

from config import TelegramConfig
from risk import TradeSetup
from strategies.signal_combiner import CombinedSignal

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Telegram bildirimleri + telefondan interaktif kontrol.

    Bildirim modu her zaman çalışır (send_* metodları). Eğer attach_context()
    ile bot bileşenleri verilirse, komut dinleyici de başlar ve kullanıcı
    telefondan şunları yapabilir:
      /status    – bakiye, açık pozisyon, günlük PnL
      /positions – açık pozisyon detayı
      /balance   – bakiye + getiri
      /stats     – performans özeti (trade, WR, PnL)
      /pause     – yeni trade'leri durdur
      /resume    – trade'leri tekrar başlat
      /close     – açık pozisyonu manuel kapat
      /help      – komut listesi

    Güvenlik: yalnızca yapılandırılmış chat_id'den gelen komutlara yanıt verir.
    """

    def __init__(self, config: TelegramConfig):
        self._cfg = config
        self._bot = None
        self._app = None            # telegram.ext.Application (komut modu)
        self._polling = False
        # Bot bileşenleri (attach_context ile set edilir)
        self._exchange = None
        self._portfolio = None
        self._executor = None
        self._db = None
        self._app_config = None
        self._initial_balance = 0.0

    def attach_context(self, *, exchange, portfolio, executor, db,
                       app_config, initial_balance: float) -> None:
        """Komut işleyicilerinin botu sorgulayıp kontrol edebilmesi için
        bileşen referanslarını bağla. initialize()'dan ÖNCE çağrılmalı."""
        self._exchange = exchange
        self._portfolio = portfolio
        self._executor = executor
        self._db = db
        self._app_config = app_config
        self._initial_balance = initial_balance

    async def initialize(self) -> None:
        if not self._cfg.enabled:
            return
        # Komut modu: bileşenler bağlıysa Application kur (hem gönderir hem dinler)
        if self._exchange is not None:
            try:
                await self._init_command_mode()
                return
            except Exception as e:
                logger.warning("Telegram command mode failed, falling back to "
                               "notify-only: %s", e)
        # Bildirim-only mod
        try:
            from telegram import Bot
            self._bot = Bot(token=self._cfg.token)
            await self._bot.get_me()
            await self.send_alert("BTC Trading Bot started", "INFO")
            logger.info("Telegram notifier initialized (notify-only)")
        except Exception as e:
            logger.warning("Telegram init failed: %s", e)
            self._bot = None

    async def _init_command_mode(self) -> None:
        from telegram.ext import Application, CommandHandler

        app = Application.builder().token(self._cfg.token).build()
        app.add_handler(CommandHandler("start", self._cmd_help))
        app.add_handler(CommandHandler("help", self._cmd_help))
        app.add_handler(CommandHandler("status", self._cmd_status))
        app.add_handler(CommandHandler("positions", self._cmd_positions))
        app.add_handler(CommandHandler("balance", self._cmd_balance))
        app.add_handler(CommandHandler("stats", self._cmd_stats))
        app.add_handler(CommandHandler("pause", self._cmd_pause))
        app.add_handler(CommandHandler("resume", self._cmd_resume))
        app.add_handler(CommandHandler("close", self._cmd_close))

        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

        self._app = app
        self._bot = app.bot
        self._polling = True
        await self.send_alert("Bot started — komutlar aktif. /help yaz.", "INFO")
        logger.info("Telegram command mode initialized (polling)")

    async def shutdown(self) -> None:
        if self._app is not None:
            try:
                if self._polling and self._app.updater:
                    try:
                        await self._app.updater.stop()
                    except Exception:
                        pass
                try:
                    await self._app.stop()
                except Exception:
                    pass
                try:
                    await self._app.shutdown()
                except Exception:
                    pass
            except Exception as e:
                logger.debug("Telegram shutdown error: %s", e)

    # ── Güvenlik ──────────────────────────────────────────────────────────────

    def _authorized(self, update) -> bool:
        try:
            chat_id = str(update.effective_chat.id)
        except Exception:
            return False
        return chat_id == str(self._cfg.chat_id)

    # ── Komut işleyiciler ──────────────────────────────────────────────────────

    async def _reply(self, update, text: str) -> None:
        try:
            await update.message.reply_text(text, parse_mode="HTML")
        except Exception as e:
            logger.warning("Telegram reply failed: %s", e)

    async def _cmd_help(self, update, context) -> None:
        if not self._authorized(update):
            return
        await self._reply(update,
            "<b>Komutlar</b>\n"
            "/status – bakiye, pozisyon, günlük PnL\n"
            "/positions – açık pozisyon detayı\n"
            "/balance – bakiye + getiri\n"
            "/stats – performans özeti\n"
            "/pause – yeni trade'leri durdur\n"
            "/resume – trade'leri başlat\n"
            "/close – açık pozisyonu kapat")

    async def _cmd_status(self, update, context) -> None:
        if not self._authorized(update):
            return
        try:
            balance = await self._exchange.get_balance()
            ret = ((balance - self._initial_balance) / self._initial_balance * 100
                   if self._initial_balance > 0 else 0.0)
            n_open = self._portfolio.get_open_position_count()
            upnl = self._portfolio.get_total_unrealized_pnl()
            halted = self._executor.is_halted()
            paper = self._app_config.exchange.paper_mode
            text = (
                f"<b>Durum</b> ({'PAPER' if paper else 'CANLI'})\n"
                f"Bakiye: <code>${balance:,.2f}</code> ({ret:+.1f}%)\n"
                f"Açık pozisyon: <code>{n_open}</code>\n"
                f"Gerçekleşmemiş PnL: <code>${upnl:+.2f}</code>\n"
                f"Trade durumu: <code>{'DURDURULDU' if halted else 'AKTİF'}</code>"
            )
        except Exception as e:
            text = f"status hatası: {e}"
        await self._reply(update, text)

    async def _cmd_positions(self, update, context) -> None:
        if not self._authorized(update):
            return
        positions = list(self._portfolio.get_open_positions())
        if not positions:
            await self._reply(update, "Açık pozisyon yok.")
            return
        lines = ["<b>Açık Pozisyonlar</b>"]
        for p in positions:
            lines.append(
                f"{p.side.upper()} {p.symbol}\n"
                f"  Entry <code>${p.entry_price:,.2f}</code>\n"
                f"  SL <code>${p.sl_price:,.2f}</code>  TP <code>${p.tp_price:,.2f}</code>\n"
                f"  Qty <code>{p.quantity:.4f}</code>"
            )
        await self._reply(update, "\n".join(lines))

    async def _cmd_balance(self, update, context) -> None:
        if not self._authorized(update):
            return
        try:
            balance = await self._exchange.get_balance()
            ret = ((balance - self._initial_balance) / self._initial_balance * 100
                   if self._initial_balance > 0 else 0.0)
            await self._reply(update,
                f"Bakiye: <code>${balance:,.2f}</code>\n"
                f"Başlangıç: <code>${self._initial_balance:,.2f}</code>\n"
                f"Getiri: <code>{ret:+.2f}%</code>")
        except Exception as e:
            await self._reply(update, f"balance hatası: {e}")

    async def _cmd_stats(self, update, context) -> None:
        if not self._authorized(update):
            return
        try:
            perf = await self._db.get_performance_summary()
            wr = (perf.winning_trades / perf.total_trades * 100
                  if perf.total_trades else 0.0)
            await self._reply(update,
                f"<b>Performans</b>\n"
                f"Trade: <code>{perf.total_trades}</code>\n"
                f"Kazanan: <code>{perf.winning_trades}</code> (WR {wr:.0f}%)\n"
                f"Toplam PnL: <code>${perf.total_pnl_usdt:+.2f}</code>\n"
                f"Max DD: <code>{perf.max_drawdown*100:.1f}%</code>")
        except Exception as e:
            await self._reply(update, f"stats hatası: {e}")

    async def _cmd_pause(self, update, context) -> None:
        if not self._authorized(update):
            return
        self._executor.halt_trading("manual pause via Telegram")
        await self._reply(update, "⏸ Yeni trade'ler DURDURULDU. /resume ile aç.")

    async def _cmd_resume(self, update, context) -> None:
        if not self._authorized(update):
            return
        self._executor.resume_trading()
        await self._reply(update, "▶️ Trade'ler tekrar AKTİF.")

    async def _cmd_close(self, update, context) -> None:
        if not self._authorized(update):
            return
        positions = list(self._portfolio.get_open_positions())
        if not positions:
            await self._reply(update, "Kapatılacak açık pozisyon yok.")
            return
        closed = 0
        for p in positions:
            try:
                price = await self._exchange.get_current_price(p.symbol)
                await self._executor.close_position(p, "manual_telegram", price)
                closed += 1
            except Exception as e:
                logger.warning("Telegram close failed for %s: %s", p.id, e)
        await self._reply(update, f"✓ {closed} pozisyon kapatıldı.")

    # ── Bildirimler (her zaman çalışır) ────────────────────────────────────────

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
        sl_pct = (setup.sl_price - setup.entry_price) / setup.entry_price * 100
        tp_pct = (setup.tp_price - setup.entry_price) / setup.entry_price * 100
        text = (
            f"<b>{direction} OPENED</b> - {setup.symbol}\n"
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
        emoji = "🟢" if pnl_usdt >= 0 else "🔴"
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
        text = (
            f"<b>Daily Summary</b>\n"
            f"Trades: <code>{total_trades}</code> | Win Rate: <code>{win_rate:.0%}</code>\n"
            f"Daily PnL: <code>${total_pnl:+.2f}</code>\n"
            f"Balance: <code>${balance:,.2f}</code>"
        )
        await self._send(text)

    async def send_daily_loss_warning(self, loss_pct: float) -> None:
        text = (
            f"⚠️ <b>DAILY LOSS LIMIT HIT</b>\n"
            f"Loss: <code>{loss_pct:.1%}</code>\n"
            f"Trading halted for today."
        )
        await self._send(text)

    async def send_alert(self, message: str, level: str = "INFO") -> None:
        emoji_map = {"INFO": "ℹ️", "WARNING": "⚠️", "ERROR": "🛑"}
        emoji = emoji_map.get(level, "")
        await self._send(f"{emoji} <b>[{level}]</b> {message}")
