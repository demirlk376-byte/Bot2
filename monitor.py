from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from portfolio import Portfolio
from strategies.signal_combiner import CombinedSignal


class Dashboard:
    REFRESH_INTERVAL = 2.0

    def __init__(self, portfolio: Portfolio):
        self._portfolio = portfolio
        self._console = Console()
        self._live: Optional[Live] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

        self._current_price: float = 0.0
        self._balance: float = 0.0
        self._daily_pnl: float = 0.0
        self._total_trades: int = 0
        self._win_rate: float = 0.0
        self._recent_signals: deque = deque(maxlen=5)
        self._recent_trades: deque = deque(maxlen=10)
        self._log_messages: deque = deque(maxlen=20)
        self._lock = threading.Lock()

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def update_price(self, price: float) -> None:
        with self._lock:
            self._current_price = price

    def update_balance(self, balance: float) -> None:
        with self._lock:
            self._balance = balance

    def update_daily_pnl(self, pnl: float) -> None:
        with self._lock:
            self._daily_pnl = pnl

    def update_stats(self, total_trades: int, win_rate: float) -> None:
        with self._lock:
            self._total_trades = total_trades
            self._win_rate = win_rate

    def update_signal(self, signal: CombinedSignal) -> None:
        with self._lock:
            self._recent_signals.append({
                "time": datetime.utcnow().strftime("%H:%M:%S"),
                "score": f"{signal.confidence:.2f}",
                "dir": "LONG" if signal.direction == 1 else ("SHORT" if signal.direction == -1 else "NONE"),
                "strategy": signal.dominant_strategy,
                "action": "TRADE" if signal.direction != 0 else "SKIP",
            })

    def add_trade(self, side: str, entry: float, exit_p: float, pnl: float, reason: str) -> None:
        with self._lock:
            self._recent_trades.append({
                "time": datetime.utcnow().strftime("%H:%M"),
                "side": side.upper(),
                "entry": f"{entry:.2f}",
                "exit": f"{exit_p:.2f}",
                "pnl": pnl,
                "reason": reason,
            })

    def log_message(self, message: str, level: str = "INFO") -> None:
        with self._lock:
            ts = datetime.utcnow().strftime("%H:%M:%S")
            self._log_messages.append(f"[{ts}] [{level}] {message}")

    def _run(self) -> None:
        with Live(self._build_layout(), refresh_per_second=1 / self.REFRESH_INTERVAL,
                  console=self._console, screen=True) as live:
            self._live = live
            while self._running:
                with self._lock:
                    layout = self._build_layout()
                live.update(layout)
                time.sleep(self.REFRESH_INTERVAL)

    def _build_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main", ratio=1),
            Layout(name="signals", size=9),
            Layout(name="trades", size=14),
            Layout(name="log", size=8),
        )

        layout["header"].update(self._header_panel())
        layout["main"].split_row(
            Layout(self._account_panel(), name="account"),
            Layout(self._position_panel(), name="position"),
        )
        layout["signals"].update(self._signals_table())
        layout["trades"].update(self._trades_table())
        layout["log"].update(self._log_panel())
        return layout

    def _header_panel(self) -> Panel:
        price_text = Text(f"BTC/USDT:USDT  ${self._current_price:,.2f}", style="bold cyan")
        mode = Text("  [PAPER]", style="bold yellow") if True else Text("  [LIVE]", style="bold red")
        return Panel(price_text + mode, style="bold")

    def _account_panel(self) -> Panel:
        pnl_color = "green" if self._daily_pnl >= 0 else "red"
        t = Table.grid(padding=1)
        t.add_row("Balance:", f"${self._balance:,.2f}")
        t.add_row("Daily PnL:", Text(f"${self._daily_pnl:+,.2f}", style=pnl_color))
        t.add_row("Total Trades:", str(self._total_trades))
        t.add_row("Win Rate:", f"{self._win_rate:.1%}")
        return Panel(t, title="Account")

    def _position_panel(self) -> Panel:
        positions = self._portfolio.get_open_positions()
        if not positions:
            return Panel(Text("No open positions", style="dim"), title="Position")

        pos = positions[0]
        pnl_color = "green" if pos.unrealized_pnl >= 0 else "red"
        dir_color = "green" if pos.direction == 1 else "red"
        t = Table.grid(padding=1)
        t.add_row("Direction:", Text(pos.side.upper(), style=dir_color))
        t.add_row("Entry:", f"${pos.entry_price:,.2f}")
        t.add_row("Unrealized PnL:", Text(f"${pos.unrealized_pnl:+,.2f}", style=pnl_color))
        t.add_row("SL:", f"${pos.sl_price:,.2f}")
        t.add_row("TP:", f"${pos.tp_price:,.2f}")
        t.add_row("Qty:", f"{pos.quantity:.4f} BTC")
        return Panel(t, title="Open Position")

    def _signals_table(self) -> Panel:
        tbl = Table(show_header=True, header_style="bold magenta", box=None)
        tbl.add_column("Time", width=10)
        tbl.add_column("Score", width=8)
        tbl.add_column("Dir", width=8)
        tbl.add_column("Strategy", width=14)
        tbl.add_column("Action", width=8)
        for s in reversed(list(self._recent_signals)):
            action_style = "green" if s["action"] == "TRADE" else "dim"
            tbl.add_row(
                s["time"], s["score"], s["dir"], s["strategy"],
                Text(s["action"], style=action_style),
            )
        return Panel(tbl, title="Recent Signals (last 5)")

    def _trades_table(self) -> Panel:
        tbl = Table(show_header=True, header_style="bold blue", box=None)
        tbl.add_column("Time", width=8)
        tbl.add_column("Side", width=7)
        tbl.add_column("Entry", width=10)
        tbl.add_column("Exit", width=10)
        tbl.add_column("PnL", width=10)
        tbl.add_column("Reason", width=12)
        for tr in reversed(list(self._recent_trades)):
            pnl_style = "green" if tr["pnl"] >= 0 else "red"
            tbl.add_row(
                tr["time"], tr["side"], tr["entry"], tr["exit"],
                Text(f"${tr['pnl']:+.2f}", style=pnl_style),
                tr["reason"],
            )
        return Panel(tbl, title="Recent Trades (last 10)")

    def _log_panel(self) -> Panel:
        msgs = list(self._log_messages)[-6:]
        text = "\n".join(msgs) if msgs else "No log messages"
        return Panel(text, title="Log")
