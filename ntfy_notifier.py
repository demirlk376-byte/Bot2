"""Ntfy push notification channel (https://ntfy.sh).

Her trade açılış/kapanışında, günlük özette ve uyarılarda telefona
push bildirimi gönderir. NTFY_TOPIC env değişkeni ile konfigüre edilir.
Telegram ile paralel çalışır — biri başarısız olsa diğeri devam eder.

Kurulum (telefon):
  1. ntfy uygulamasını indir (iOS / Android).
  2. NTFY_TOPIC için rastgele bir isim seç (ör. btc-bot-abc123).
  3. Uygulamada o topic'e subscribe ol.
  4. .env'e NTFY_ENABLED=true ve NTFY_TOPIC=btc-bot-abc123 ekle.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class NtfyConfig:
    enabled: bool
    topic: str
    server: str = "https://ntfy.sh"   # self-host için değiştir


class NtfyNotifier:
    """Ntfy push bildirimleri. TelegramNotifier ile aynı public arayüz."""

    def __init__(self, config: NtfyConfig):
        self._cfg = config
        self._session = None

    async def initialize(self) -> None:
        if not self._cfg.enabled:
            return
        try:
            import aiohttp
            self._session = aiohttp.ClientSession()
            await self._post(
                title="Bot Başladı",
                message="BTC trading botu çalışıyor.",
                tags="white_check_mark",
                priority=3,
            )
            logger.info("Ntfy notifier initialized (topic=%s)", self._cfg.topic)
        except Exception as e:
            logger.warning("Ntfy init failed: %s", e)
            self._session = None

    async def shutdown(self) -> None:
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _post(
        self,
        title: str,
        message: str,
        tags: str = "",
        priority: int = 3,
    ) -> None:
        if not self._cfg.enabled or self._session is None:
            return
        url = f"{self._cfg.server.rstrip('/')}/{self._cfg.topic}"
        headers = {
            "Title": title,
            "Priority": str(priority),
        }
        if tags:
            headers["Tags"] = tags
        try:
            async with self._session.post(url, data=message.encode(), headers=headers,
                                          timeout=8) as resp:
                if resp.status >= 400:
                    logger.warning("Ntfy POST failed: HTTP %d", resp.status)
        except Exception as e:
            logger.warning("Ntfy send failed: %s", e)

    # ── Bildirimler ────────────────────────────────────────────────────────────

    async def send_trade_opened(self, setup, signal) -> None:
        direction = "LONG" if setup.direction == 1 else "SHORT"
        sl_pct = (setup.sl_price - setup.entry_price) / setup.entry_price * 100
        tp_pct = (setup.tp_price - setup.entry_price) / setup.entry_price * 100
        tag = "chart_with_upwards_trend" if setup.direction == 1 else "chart_with_downwards_trend"
        body = (
            f"Entry ${setup.entry_price:,.2f}\n"
            f"SL ${setup.sl_price:,.2f} ({sl_pct:+.1f}%)\n"
            f"TP ${setup.tp_price:,.2f} ({tp_pct:+.1f}%)\n"
            f"Risk ${setup.risk_usdt:.2f} | {signal.dominant_strategy}"
        )
        await self._post(
            title=f"BTC {direction} AÇILDI",
            message=body,
            tags=tag,
            priority=4,
        )

    async def send_trade_closed(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        pnl_usdt: float,
        reason: str,
        pnl_pct: float | None = None,
    ) -> None:
        is_win = pnl_usdt >= 0
        # Prefer the caller-supplied return-on-margin % (matches the DB stat); fall
        # back to raw price-move % when not provided.
        if pnl_pct is None:
            pnl_pct = (exit_price - entry_price) / entry_price * 100 * (1 if side == "long" else -1)
        tag = "white_check_mark" if is_win else "x"
        priority = 3 if is_win else 5
        reason_upper = reason.upper().replace("_", " ")
        title = f"{reason_upper} {pnl_usdt:+.2f}$"
        body = (
            f"{side.upper()} {symbol}\n"
            f"${entry_price:,.2f} → ${exit_price:,.2f}\n"
            f"PnL ${pnl_usdt:+.2f} ({pnl_pct:+.2f}%)"
        )
        await self._post(title=title, message=body, tags=tag, priority=priority)

    async def send_daily_summary(
        self,
        total_trades: int,
        winning_trades: int,
        total_pnl: float,
        balance: float,
    ) -> None:
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
        tag = "bar_chart"
        body = (
            f"Trade: {total_trades} | WR: {win_rate:.0%}\n"
            f"Günlük PnL: ${total_pnl:+.2f}\n"
            f"Bakiye: ${balance:,.2f}"
        )
        await self._post(title="Günlük Özet", message=body, tags=tag, priority=3)

    async def send_daily_loss_warning(self, loss_pct: float) -> None:
        await self._post(
            title="LOSS LİMİT AŞILDI",
            message=f"Kayıp: {loss_pct:.1%}\nBugün trading durduruldu.",
            tags="rotating_light",
            priority=5,
        )

    async def send_alert(self, message: str, level: str = "INFO") -> None:
        priority_map = {"INFO": 3, "WARNING": 4, "ERROR": 5}
        tag_map = {"INFO": "information_source", "WARNING": "warning", "ERROR": "rotating_light"}
        await self._post(
            title=f"[{level}] Bot",
            message=message,
            tags=tag_map.get(level, "information_source"),
            priority=priority_map.get(level, 3),
        )
