"""Bize-özel canlı web dashboard (aiohttp — ekstra paket yok).

Botun aynı process'inde paralel çalışır; trading'e hiç dokunmaz, sadece
mevcut durumu okuyup tarayıcıya servis eder. Telefonun tarayıcısından
http://<vps-ip>:<port> açılır, ana ekrana kısayol eklenince uygulama gibi durur.

Gösterir:
  • Bakiye + toplam getiri + günlük PnL
  • Açık pozisyonlar (yön, entry, SL, TP, canlı PnL)
  • Performans: trade, WR, profit factor, max DD
  • Strateji bazlı kırılım
  • Son kapanan trade'ler

Güvenlik: WEB_TOKEN ayarlanırsa sayfa ?token=... ister. Boşsa herkese açık
(sadece okunur — kontrol endpoint'i yok).
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from strategies.signal_combiner import strategy_label

logger = logging.getLogger(__name__)


class WebDashboard:
    def __init__(
        self, config, *, exchange, portfolio, db, initial_balance: float,
        sleeve_layout: dict | None = None, paper_mode: bool = True,
        leverage: int = 1, daily_max_loss: float = 0.0,
    ):
        self._cfg = config            # WebDashboardConfig
        self._exchange = exchange
        self._portfolio = portfolio
        self._db = db
        self._initial_balance = initial_balance
        self._sleeve_layout = sleeve_layout or {}
        self._paper_mode = paper_mode
        self._leverage = max(1, int(leverage))
        self._daily_max_loss = float(daily_max_loss)   # e.g. 0.35 → -35% günlük halt
        self._start_ts = datetime.now(timezone.utc)    # uptime için (bot başlangıcı)
        self._runner = None
        self._site = None
        # Canlı sinyal akışı — son 25 olayı tut (thread-safe değil, ama asyncio single-thread OK)
        self._activity: list = []        # [{"t","sym","strat","dir","reason","action"}, ...]
        self._regime: dict = {}          # {symbol: {"label","adx"}} — her coin için ayrı

    # ── Sinyal akışı güncellemeleri (main.py tarafından çağrılır) ────────────
    def update_regime(self, regime: str, adx: float, symbol: str = "") -> None:
        """ADX değerini ve rejim etiketini depola (her coin için ayrı)."""
        _lbl = {"trending": "Trend", "ranging": "Sıkışma", "neutral": "Nötr"}.get(regime, regime)
        key = symbol.split("/")[0] if symbol else "BTC"
        self._regime[key] = {"label": _lbl, "adx": round(float(adx), 1)}

    def add_signal(
        self, symbol: str, strategy: str,
        direction: int, reason: str, action: str = "",
    ) -> None:
        """Son sinyali aktivite listesine ekle (max 25)."""
        entry = {
            # Türkiye saati (UTC+3) — kullanıcıya göre göster; backend mantığı UTC
            "t": (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%H:%M"),
            "sym": symbol.split("/")[0],
            "strat": strategy,
            "dir": direction,
            "reason": reason,
            "action": action,   # "": sinyal yok | "exec": emir verildi | "block": engellendi
        }
        self._activity.insert(0, entry)
        if len(self._activity) > 25:
            self._activity.pop()

    async def start(self) -> None:
        if not self._cfg.enabled:
            return
        try:
            from aiohttp import web
        except Exception as e:
            logger.warning("Web dashboard disabled (aiohttp missing): %s", e)
            return
        try:
            app = web.Application()
            app.router.add_get("/", self._handle_index)
            app.router.add_get("/api/state", self._handle_state)
            app.router.add_post("/api/restart", self._handle_restart)
            self._runner = web.AppRunner(app)
            await self._runner.setup()
            self._site = web.TCPSite(
                self._runner, self._cfg.host, self._cfg.port, reuse_address=True
            )
            await self._site.start()
            logger.info(
                "Web dashboard running on http://%s:%d", self._cfg.host, self._cfg.port
            )
        except Exception as e:
            logger.warning("Web dashboard failed to start: %s", e)
            self._runner = None

    async def stop(self) -> None:
        try:
            if self._runner is not None:
                await self._runner.cleanup()
        except Exception:
            pass

    # ── Routes ─────────────────────────────────────────────────────────────────

    async def _handle_index(self, request):
        from aiohttp import web
        return web.Response(text=_INDEX_HTML, content_type="text/html")

    async def _handle_state(self, request):
        from aiohttp import web
        try:
            data = await self._build_state()
            return web.json_response(data)
        except Exception as e:
            logger.debug("dashboard state error: %s", e)
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_restart(self, request):
        """git pull + botu yeniden başlat.

        Mekanizma: servis 'botuser' olarak çalışır (systemctl yetkisi yok) ama
        repo'nun sahibidir, yani git pull yapabilir; ardından process sıfırdan-
        farklı kodla çıkar ve systemd (Restart=on-failure) onu otomatik geri
        başlatır — yeni kodla. Açık pozisyonlar DB'den geri yüklenir, MEXC'teki
        SL/TP server-side olduğu için restart onları etkilemez."""
        from aiohttp import web

        repo = str(Path(__file__).resolve().parent)
        pull_out = ""
        try:
            r = subprocess.run(
                ["git", "pull", "--ff-only"], cwd=repo,
                capture_output=True, text=True, timeout=30,
            )
            pull_out = (r.stdout + r.stderr).strip()[-400:]
            logger.warning("Dashboard restart: git pull → %s", pull_out)
        except Exception as e:
            pull_out = f"git pull atlandı/başarısız: {e}"
            logger.warning("Dashboard restart: %s", pull_out)

        # Yanıtı gönderdikten ~1.5s sonra çık (systemd geri başlatır).
        async def _bye():
            await asyncio.sleep(1.5)
            logger.warning("Dashboard-triggered restart: exiting for systemd respawn")
            os._exit(1)   # non-zero → Restart=on-failure devreye girer
        asyncio.create_task(_bye())
        return web.json_response({"ok": True, "pull": pull_out or "—"})

    # ── State ──────────────────────────────────────────────────────────────────

    async def _build_state(self) -> dict:
        balance = await self._exchange.get_balance()

        # Açık pozisyonlar — her birinin güncel fiyatıyla canlı PnL
        positions = []
        total_upnl = 0.0
        locked_margin = 0.0
        for p in self._portfolio.get_open_positions():
            try:
                price = await self._exchange.get_current_price(p.symbol)
            except Exception:
                price = p.entry_price
            # Guard against a missing entry price (e.g. an exchange fill that came
            # back as 0): without this the upnl would be direction*price*qty — a
            # huge bogus number that misrepresents the whole account on the page.
            if p.entry_price <= 0:
                upnl = 0.0
            else:
                upnl = p.direction * (price - p.entry_price) * p.quantity
            total_upnl += upnl
            # Live get_balance() returns FREE balance (margin locked out). Add the
            # initial margin back so equity reflects the whole account, otherwise
            # opening a position would read as an instant loss on the dashboard.
            locked_margin += (p.entry_price * p.quantity) / self._leverage
            pnl_pct = (
                (price - p.entry_price) / p.entry_price * 100 * p.direction
                if p.entry_price else 0.0
            )
            age_h = (
                datetime.now(timezone.utc) - p.entry_time
            ).total_seconds() / 3600.0
            positions.append({
                "symbol": p.symbol.split("/")[0],
                "side": p.side,
                "strategy": strategy_label(p.strategy_scores.get("strategy", "?")),
                "entry": p.entry_price,
                "current": price,
                "sl": p.sl_price,
                "tp": p.tp_price,
                "qty": p.quantity,
                "upnl": upnl,
                "pnl_pct": pnl_pct,
                "age_h": age_h,
            })

        # Total account value (equity), not just free balance, so an open
        # position's locked margin isn't mistaken for a loss. Prefer the
        # exchange's authoritative equity (free + locked + uPnL straight from
        # MEXC) — it stays correct even if the bot's portfolio is momentarily
        # empty (e.g. an orphaned position after a restart). Only if that read
        # fails do we fall back to the portfolio-based reconstruction, which
        # reads locked margin as a loss when the portfolio is empty.
        equity = balance + locked_margin + total_upnl
        if hasattr(self._exchange, "get_equity"):
            try:
                exch_eq = await self._exchange.get_equity()
                if exch_eq > 0:
                    equity = exch_eq
            except Exception:
                pass

        # Invested capital = first balance + every deposit the user added later.
        # True profit is equity − invested, so monthly top-ups never look like
        # trading gains. Read from the DB each tick so a new deposit shows up
        # immediately (no restart needed).
        inception = await self._db.get_meta_float(
            "inception_balance", self._initial_balance
        )
        # Bogus inception (< $1): written during a bad startup with expired key
        # or empty account. Fall back to current equity so return shows 0% until
        # main.py rewrites the value on next restart.
        if inception < 1.0:
            inception = equity
        deposits = await self._db.get_meta_float("total_deposits", 0.0)
        invested = inception + deposits
        true_pnl = equity - invested
        ret_pct = (true_pnl / invested * 100) if invested > 0 else 0.0

        # Only show trades from the CURRENT mode. The same trades.db can hold
        # earlier paper-test rows; without this filter a live $48 account would
        # show the old paper PnL (e.g. -$91), which is meaningless and alarming.
        ip = self._paper_mode

        today = datetime.now(timezone.utc).date().isoformat()
        daily_pnl = await self._db.get_daily_pnl(today, is_paper=ip)

        perf = await self._db.get_performance_summary(is_paper=ip)
        pf = perf.profit_factor
        pf_out = None if pf == float("inf") else round(pf, 2)

        breakdown = await self._db.get_strategy_breakdown(is_paper=ip)
        strat = []
        for s in breakdown:
            wr = s["win"] / s["total"] * 100 if s["total"] else 0.0
            strat.append({
                "strategy": strategy_label(s["strategy"] or "unknown"),
                "total": s["total"], "win": s["win"],
                "wr": wr, "pnl": s["pnl"],
            })

        recent = await self._db.get_all_trades(limit=15, is_paper=ip)
        trades = []
        for t in recent:
            if t.exit_time is None:
                continue
            trades.append({
                "symbol": t.symbol.split("/")[0],
                "side": t.side,
                "strategy": strategy_label((t.strategy_scores or {}).get("strategy", "?")),
                "entry": t.entry_price,
                "exit": t.exit_price,
                "pnl": t.pnl_usdt or 0.0,
                "reason": t.exit_reason or "",
                "exit_time": t.exit_time,
            })

        # Per-coin breakdown (now that 5 coins trade with different sleeve sets).
        coin_rows = await self._db.get_coin_breakdown(is_paper=ip)
        coins = []
        for c in coin_rows:
            wr = c["win"] / c["total"] * 100 if c["total"] else 0.0
            sym = c["symbol"].split("/")[0]
            coins.append({
                "symbol": sym, "total": c["total"], "win": c["win"],
                "wr": wr, "pnl": c["pnl"],
                "sleeves": self._sleeve_layout.get(sym, []),
            })
        # Include coins that are configured but have no closed trades yet, so the
        # sleeve map is complete from the first boot.
        seen = {c["symbol"] for c in coins}
        for sym, sleeves in self._sleeve_layout.items():
            if sym not in seen:
                coins.append({"symbol": sym, "total": 0, "win": 0,
                              "wr": 0.0, "pnl": 0.0, "sleeves": sleeves})

        # Equity curve anchored at invested capital so it starts where the money
        # came in and grows with realised trades; the final live point folds in
        # open unrealized PnL so the line tip matches current equity.
        eq_curve = await self._db.get_equity_curve(invested, is_paper=ip)
        monthly = await self._db.get_monthly_pnl(limit=12, is_paper=ip)
        if eq_curve:
            eq_curve = eq_curve + [{"t": None, "eq": eq_curve[-1]["eq"] + total_upnl}]

        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "uptime_seconds": (
                datetime.now(timezone.utc) - self._start_ts
            ).total_seconds(),
            "paper_mode": self._paper_mode,
            "balance": balance,
            "equity": equity,
            "invested": invested,
            "true_pnl": true_pnl,
            "initial_balance": self._initial_balance,
            "return_pct": ret_pct,
            "daily_pnl": daily_pnl,
            "daily_max_loss": self._daily_max_loss,
            # Fraction of today's loss budget consumed (0 = none, 1 = halt). Only
            # counts losses; a green day reads as 0 risk used. Approximated on
            # current equity since the exact daily-start equity isn't surfaced here.
            "daily_risk_used": (
                max(0.0, -daily_pnl) / (self._daily_max_loss * equity)
                if self._daily_max_loss > 0 and equity > 0 else 0.0
            ),
            "unrealized_pnl": total_upnl,
            "open_count": len(positions),
            "positions": positions,
            "perf": {
                "total": perf.total_trades,
                "wins": perf.winning_trades,
                "win_rate": perf.win_rate * 100,
                "total_pnl": perf.total_pnl_usdt,
                "profit_factor": pf_out,
                "max_dd": perf.max_drawdown * 100,
            },
            "coins": coins,
            "strategies": strat,
            "equity_curve": [e["eq"] for e in eq_curve],
            "monthly": monthly,
            "trades": trades,
            "regime": dict(self._regime),
            "activity": list(self._activity[:15]),
        }


_INDEX_HTML = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#070a10">
<title>Trading Bot</title>
<style>
  :root{
    --bg:#070a10; --bg2:#0b0f17; --card:#121826cc;
    --card2:#171f2e; --line:#26304399; --txt:#eaf1f8; --dim:#7e8aa0;
    --green:#21d180; --red:#ff5470; --accent:#5b8cff; --gold:#f5c451;
    --glow:0 0 24px rgba(91,140,255,.18);
  }
  *{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
  html,body{margin:0}
  body{background:
      radial-gradient(1200px 600px at 80% -10%, rgba(91,140,255,.12), transparent 60%),
      radial-gradient(900px 500px at -10% 10%, rgba(33,209,128,.08), transparent 55%),
      var(--bg);
    color:var(--txt);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Inter,sans-serif;
    padding:16px 13px 48px;font-size:15px;min-height:100vh}
  .wrap{max-width:680px;margin:0 auto}
  .top{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}
  h1{font-size:16px;margin:0;font-weight:700;letter-spacing:.2px;display:flex;align-items:center;gap:8px}
  .dot{width:8px;height:8px;border-radius:50%;background:var(--green);
    box-shadow:0 0 10px var(--green);animation:pulse 2s infinite}
  @keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.4;transform:scale(.8)}}
  .badge{font-size:10px;font-weight:700;letter-spacing:.5px;padding:3px 8px;
    border-radius:6px;text-transform:uppercase}
  .live{background:rgba(255,84,112,.16);color:var(--red);border:1px solid rgba(255,84,112,.3)}
  .paper{background:rgba(91,140,255,.16);color:var(--accent);border:1px solid rgba(91,140,255,.3)}
  .sub{color:var(--dim);font-size:12px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:18px;
    padding:16px;margin-bottom:13px;backdrop-filter:blur(12px);
    box-shadow:0 8px 30px rgba(0,0,0,.35)}
  .hero{background:
      linear-gradient(135deg, rgba(91,140,255,.14), rgba(33,209,128,.06) 60%, transparent),
      var(--card)}
  .balrow{display:flex;align-items:flex-end;justify-content:space-between;gap:10px}
  .bal{font-size:38px;font-weight:800;letter-spacing:-1px;line-height:1;
    font-variant-numeric:tabular-nums}
  .pill{font-size:14px;font-weight:700;padding:5px 11px;border-radius:10px;
    font-variant-numeric:tabular-nums}
  .pill.g{background:rgba(33,209,128,.15);color:var(--green)}
  .pill.r{background:rgba(255,84,112,.15);color:var(--red)}
  .bal{transition:color .3s ease}
  /* günlük risk göstergesi (zarar limitine yakınlık) */
  .gauge{margin-top:14px}
  .gauge .gh{display:flex;justify-content:space-between;align-items:center;
    font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.6px;margin-bottom:6px}
  .gtrack{height:8px;border-radius:5px;background:var(--card2);overflow:hidden;position:relative}
  .gtrack>i{display:block;height:100%;border-radius:5px;width:0;
    transition:width .6s cubic-bezier(.22,.61,.36,1)}
  /* trade sebep rozetleri */
  .rb{font-size:10px;font-weight:700;padding:2px 7px;border-radius:6px;letter-spacing:.2px;white-space:nowrap}
  .rb.tp{background:rgba(33,209,128,.16);color:var(--green)}
  .rb.sl{background:rgba(255,84,112,.16);color:var(--red)}
  .rb.mh{background:rgba(245,196,81,.16);color:var(--gold)}
  .rb.x{background:rgba(126,138,160,.16);color:var(--dim)}
  /* pozisyon ilerleme çubuğunda giriş işareti */
  .prog>.mk{position:absolute;top:-2px;bottom:-2px;width:2px;background:var(--txt);opacity:.55}
  .row{display:flex;gap:9px;margin-top:14px}
  .row .box{flex:1;background:var(--card2);border:1px solid var(--line);
    border-radius:12px;padding:11px 12px}
  .box .k{color:var(--dim);font-size:10px;text-transform:uppercase;letter-spacing:.6px}
  .box .v{font-size:17px;font-weight:700;margin-top:4px;font-variant-numeric:tabular-nums}
  .sec{font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.8px;
    margin:20px 6px 9px;font-weight:700;display:flex;justify-content:space-between}
  /* equity chart */
  .chartwrap{position:relative}
  svg.chart{width:100%;height:140px;display:block;overflow:visible}
  .chip{display:inline-block;font-size:10px;font-weight:700;padding:2px 7px;
    border-radius:6px;background:var(--card2);color:var(--dim);margin-left:5px}
  /* coins */
  .coins{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:9px}
  .coin{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px}
  .coin .ch{display:flex;justify-content:space-between;align-items:center;margin-bottom:7px}
  .coin .sym{font-weight:800;font-size:15px;letter-spacing:.3px}
  .coin .cp{font-weight:700;font-size:14px;font-variant-numeric:tabular-nums}
  .sleeves{display:flex;flex-wrap:wrap;gap:4px;margin-top:8px}
  .sl{font-size:9px;font-weight:700;padding:2px 6px;border-radius:5px;
    background:rgba(91,140,255,.13);color:#9fbcff;letter-spacing:.3px}
  .coin .cstat{font-size:11px;color:var(--dim);font-variant-numeric:tabular-nums}
  /* positions */
  .pos{background:var(--card);border:1px solid var(--line);border-radius:15px;
    padding:13px;margin-bottom:10px;position:relative;overflow:hidden}
  .pos::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px}
  .pos.long-b::before{background:var(--green);box-shadow:0 0 12px var(--green)}
  .pos.short-b::before{background:var(--red);box-shadow:0 0 12px var(--red)}
  .pos .h{display:flex;justify-content:space-between;align-items:center;margin-bottom:9px}
  .tag{font-size:11px;font-weight:800;padding:3px 9px;border-radius:7px;letter-spacing:.3px}
  .long{background:rgba(33,209,128,.16);color:var(--green)}
  .short{background:rgba(255,84,112,.16);color:var(--red)}
  .strat{color:var(--dim);font-size:11px}
  .grid{display:grid;grid-template-columns:repeat(2,1fr);gap:6px 14px;font-size:13px}
  .grid .k{color:var(--dim)}
  .grid span:nth-child(even){text-align:right;font-variant-numeric:tabular-nums}
  /* progress bar entry->sl/tp */
  .prog{height:5px;border-radius:3px;background:var(--card2);margin-top:10px;position:relative;overflow:hidden}
  .prog>i{position:absolute;top:0;bottom:0;border-radius:3px}
  .pnl{font-size:20px;font-weight:800;font-variant-numeric:tabular-nums}
  .g{color:var(--green)} .r{color:var(--red)}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th{color:var(--dim);font-weight:600;text-align:left;font-size:10px;
    text-transform:uppercase;letter-spacing:.5px;padding:6px 4px;border-bottom:1px solid var(--line)}
  td{padding:9px 4px;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}
  tr:last-child td{border-bottom:none}
  .right{text-align:right}
  .empty{color:var(--dim);text-align:center;padding:20px;font-size:13px}
  .strat-row{display:flex;justify-content:space-between;align-items:center;padding:9px 0;
    border-bottom:1px solid var(--line);font-size:13px}
  .strat-row:last-child{border-bottom:none}
  .sbar{height:6px;border-radius:3px;background:var(--card2);flex:1;margin:0 10px;overflow:hidden}
  .sbar>i{display:block;height:100%;border-radius:3px}
  /* monthly bars */
  .months{display:flex;align-items:flex-end;gap:6px;height:90px;padding-top:6px}
  .mb{flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;height:100%;justify-content:flex-end}
  .mb .bar{width:100%;border-radius:5px 5px 0 0;min-height:3px;transition:height .5s ease}
  .mb .lbl{font-size:9px;color:var(--dim)}
  .fade{animation:fade .4s ease}
  @keyframes fade{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
  /* restart butonu */
  .footer{display:flex;flex-direction:column;align-items:center;gap:8px;margin:26px 0 8px}
  .rbtn{display:inline-flex;align-items:center;gap:8px;font-size:13px;font-weight:700;
    color:var(--dim);background:var(--card);border:1px solid var(--line);
    border-radius:12px;padding:11px 18px;cursor:pointer;transition:all .2s ease;
    -webkit-user-select:none;user-select:none}
  .rbtn:hover,.rbtn:active{color:var(--gold);border-color:rgba(245,196,81,.4);
    box-shadow:0 0 16px rgba(245,196,81,.12)}
  .rbtn.busy{opacity:.6;pointer-events:none}
  .rbtn .ic{font-size:15px}
  .rmsg{font-size:11px;color:var(--dim);text-align:center;min-height:14px}
  /* aktivite listesi */
  .act{padding:7px 0;border-bottom:1px solid var(--line);display:flex;align-items:flex-start;gap:8px;font-size:12px}
  .act:last-child{border-bottom:none}
  .act .at{color:var(--dim);white-space:nowrap;font-size:11px;min-width:36px}
  .act .ab{font-weight:700;min-width:28px;font-size:10px;padding:2px 5px;border-radius:5px;text-align:center}
  .act .ab.up{background:rgba(33,209,128,.18);color:var(--green)}
  .act .ab.dn{background:rgba(255,84,112,.18);color:var(--red)}
  .act .ab.no{background:rgba(126,138,160,.1);color:var(--dim)}
  .act .ar{flex:1;color:var(--dim);line-height:1.4;word-break:break-word}
  .act .ar b{color:var(--txt);font-weight:700}
  .act .ac{font-size:10px;padding:2px 5px;border-radius:5px;white-space:nowrap;font-weight:700}
  .act .ac.exec{background:rgba(33,209,128,.15);color:var(--green)}
  .act .ac.block{background:rgba(245,196,81,.15);color:var(--gold)}
  /* yeni işlem açılınca kısa parıltı */
  @keyframes flash{0%{box-shadow:0 8px 30px rgba(0,0,0,.35)}
    35%{box-shadow:0 0 0 2px var(--accent),0 0 34px rgba(91,140,255,.55)}
    100%{box-shadow:0 8px 30px rgba(0,0,0,.35)}}
  .flash{animation:flash 1.1s ease}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <h1><span class="dot"></span>Trading Bot <span class="badge" id="mode"></span></h1>
    <span class="sub" id="ts">…</span>
  </div>

  <div class="card hero">
    <div class="sub">Toplam Bakiye</div>
    <div class="balrow">
      <div class="bal" id="bal">$—</div>
      <div class="pill g" id="ret">—</div>
    </div>
    <div class="row">
      <div class="box"><div class="k">Gerçek Kâr</div><div class="v" id="truepnl">—</div></div>
      <div class="box"><div class="k">Yatırılan</div><div class="v" id="invested">—</div></div>
    </div>
    <div class="row">
      <div class="box"><div class="k">Bugün</div><div class="v" id="daily">—</div></div>
      <div class="box"><div class="k">Açık PnL</div><div class="v" id="upnl">—</div></div>
    </div>
    <div class="gauge" id="gauge" style="display:none">
      <div class="gh"><span>Günlük Risk</span><span id="gtxt">—</span></div>
      <div class="gtrack"><i id="gbar"></i></div>
    </div>
  </div>

  <div class="sec"><span>Equity Eğrisi</span><span class="sub" id="eqinfo"></span></div>
  <div class="card chartwrap"><svg class="chart" id="chart" preserveAspectRatio="none"></svg></div>

  <div class="sec"><span>Coinler & Aktif Stratejiler</span></div>
  <div class="coins" id="coins"></div>

  <div class="sec"><span>Açık Pozisyonlar</span><span class="chip" id="oc">0</span></div>
  <div id="positions"></div>

  <div class="sec"><span>Performans</span></div>
  <div class="card">
    <div class="row">
      <div class="box"><div class="k">Trade</div><div class="v" id="p_total">—</div></div>
      <div class="box"><div class="k">Kazanma</div><div class="v" id="p_wr">—</div></div>
      <div class="box"><div class="k">Profit F.</div><div class="v" id="p_pf">—</div></div>
    </div>
    <div class="row">
      <div class="box"><div class="k">Max DD</div><div class="v" id="p_dd">—</div></div>
      <div class="box" style="flex:2"><div class="k">Toplam PnL</div><div class="v" id="p_pnl">—</div></div>
    </div>
  </div>

  <div class="sec"><span>Aylık P&amp;L</span></div>
  <div class="card"><div class="months" id="months"><div class="empty">—</div></div></div>

  <div class="sec"><span>Strateji Kırılımı</span></div>
  <div class="card" id="strats"><div class="empty">—</div></div>

  <div class="sec"><span>Son Aktivite</span><span id="regbadge" class="sub"></span></div>
  <div class="card" id="activity"><div class="empty">sinyal bekleniyor…</div></div>

  <div class="sec"><span>Son Trade'ler</span></div>
  <div class="card" id="trades"><div class="empty">—</div></div>

  <div class="footer">
    <div class="rbtn" id="rbtn" onclick="doRestart()">
      <span class="ic">⟳</span><span>Botu Yeniden Başlat</span>
    </div>
    <div class="rmsg" id="rmsg"></div>
  </div>
</div>

<script>
const fmt = (n,d=null)=>{const a=Math.abs(Number(n));const dp=d!==null?d:(a>=100?2:a>=1?4:6);return Number(n).toLocaleString("en-US",{minimumFractionDigits:dp,maximumFractionDigits:dp});};
const compact = n => Math.abs(n)>=1000 ? (n/1000).toFixed(1)+"k" : fmt(n,Math.abs(n)<10?2:0);
const signed = n => (n>=0?"+$":"-$")+compact(Math.abs(n));
const cls = n => n>=0?"g":"r";
const NS = "http://www.w3.org/2000/svg";

// bakiye sayaç animasyonu (önceki değerden yenisine yumuşak geçiş)
let _bal = null;
function animateBal(to){
  const el = document.getElementById("bal");
  const from = (_bal==null) ? to : _bal;
  _bal = to;
  if(from===to){ el.textContent="$"+fmt(to); return; }
  const t0 = performance.now(), dur = 600;
  function step(t){
    const k = Math.min(1,(t-t0)/dur);
    const e = 1-Math.pow(1-k,3);            // easeOutCubic
    el.textContent = "$"+fmt(from+(to-from)*e);
    if(k<1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

// uptime → "3g 4s" / "4s 12d" / "12d"
function fmtUptime(sec){
  sec=Math.floor(sec||0);
  const d=Math.floor(sec/86400), h=Math.floor(sec%86400/3600), m=Math.floor(sec%3600/60);
  if(d>0) return d+"g "+h+"s";
  if(h>0) return h+"s "+m+"d";
  return m+"d";
}
let _lastOpen=null;   // yeni pozisyon tespiti için

// trade çıkış sebebi → renkli rozet
function reasonBadge(r){
  r = (r||"").toLowerCase();
  if(r.includes("tp")) return '<span class="rb tp">TP</span>';
  if(r.includes("sl")) return '<span class="rb sl">SL</span>';
  if(r.includes("hold")||r.includes("maxhold")) return '<span class="rb mh">SÜRE</span>';
  if(r.includes("trail")) return '<span class="rb tp">TRAIL</span>';
  if(r.includes("manual")) return '<span class="rb x">MANUEL</span>';
  if(r.includes("daily")||r.includes("limit")) return '<span class="rb sl">LİMİT</span>';
  if(r.includes("external")||r.includes("recon")) return '<span class="rb x">DIŞ</span>';
  return '<span class="rb x">'+(r.replace(/_/g," ")||"—")+'</span>';
}

async function tick(){
  try{
    const r = await fetch("/api/state");
    if(!r.ok){throw new Error("HTTP "+r.status)}
    render(await r.json());
    document.querySelector(".dot").style.background="var(--green)";
  }catch(e){
    document.getElementById("ts").textContent = "bağlantı yok";
    document.querySelector(".dot").style.background="var(--red)";
  }
}

function drawChart(eq){
  const svg = document.getElementById("chart");
  svg.innerHTML="";
  if(!eq || eq.length<2){
    svg.innerHTML='<text x="50%" y="50%" fill="#7e8aa0" font-size="12" text-anchor="middle">veri birikiyor…</text>';
    return;
  }
  const W=svg.clientWidth||320, H=140, pad=6;
  let mn=Math.min(...eq), mx=Math.max(...eq);
  if(mn===mx){mn-=1;mx+=1;}
  const rng=mx-mn;
  const X=i=>pad+(W-2*pad)*i/(eq.length-1);
  const Y=v=>pad+(H-2*pad)*(1-(v-mn)/rng);
  const up = eq[eq.length-1]>=eq[0];
  const col = up?"#21d180":"#ff5470";
  let dline="", darea="";
  eq.forEach((v,i)=>{const x=X(i).toFixed(1),y=Y(v).toFixed(1);
    dline+=(i?"L":"M")+x+" "+y+" "; });
  darea = dline + "L"+X(eq.length-1).toFixed(1)+" "+H+" L"+X(0).toFixed(1)+" "+H+" Z";
  const gid="grad";
  svg.innerHTML=`
    <defs>
      <linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="${col}" stop-opacity=".28"/>
        <stop offset="1" stop-color="${col}" stop-opacity="0"/>
      </linearGradient>
    </defs>
    <path d="${darea}" fill="url(#${gid})"/>
    <path d="${dline}" fill="none" stroke="${col}" stroke-width="2.4"
      stroke-linejoin="round" stroke-linecap="round" style="filter:drop-shadow(0 0 6px ${col}66)"/>
    <circle cx="${X(eq.length-1).toFixed(1)}" cy="${Y(eq[eq.length-1]).toFixed(1)}" r="4" fill="${col}"/>
  `;
  document.getElementById("eqinfo").textContent =
    "$"+fmt(mn,0)+" → $"+fmt(mx,0);
}

function render(d){
  document.getElementById("ts").textContent =
    new Date(d.ts).toLocaleTimeString("tr-TR") + " · ⏱ " + fmtUptime(d.uptime_seconds);
  // yeni pozisyon açıldıysa: titreşim + hero kartı parıltısı (telefon bildirimi gibi)
  if(_lastOpen!==null && d.open_count>_lastOpen){
    if(navigator.vibrate) navigator.vibrate([60,40,60]);
    const hero=document.querySelector(".hero");
    if(hero){ hero.classList.remove("flash"); void hero.offsetWidth; hero.classList.add("flash"); }
  }
  _lastOpen=d.open_count;
  const mode=document.getElementById("mode");
  mode.textContent = d.paper_mode?"PAPER":"LIVE";
  mode.className = "badge "+(d.paper_mode?"paper":"live");
  animateBal(d.equity);
  document.getElementById("invested").textContent = "$"+compact(d.invested);
  const tp=document.getElementById("truepnl");
  tp.textContent=signed(d.true_pnl); tp.className="v "+cls(d.true_pnl);
  const ret=document.getElementById("ret");
  ret.textContent=(d.return_pct>=0?"▲ ":"▼ ")+fmt(Math.abs(d.return_pct),1)+"%";
  ret.className="pill "+cls(d.return_pct);
  const dl=document.getElementById("daily");
  dl.textContent=signed(d.daily_pnl); dl.className="v "+cls(d.daily_pnl);
  const up=document.getElementById("upnl");
  up.textContent=signed(d.unrealized_pnl); up.className="v "+cls(d.unrealized_pnl);
  document.getElementById("oc").textContent=d.open_count;

  // günlük risk göstergesi (zarar limitine ne kadar yakın)
  const g=document.getElementById("gauge");
  if(d.daily_max_loss>0){
    g.style.display="block";
    const used=Math.max(0,Math.min(1,d.daily_risk_used||0));
    const bar=document.getElementById("gbar");
    bar.style.width=(used*100).toFixed(0)+"%";
    // yeşil → sarı → kırmızı (limite yaklaştıkça)
    const col = used<0.5?"var(--green)":used<0.8?"var(--gold)":"var(--red)";
    bar.style.background=col; bar.style.boxShadow="0 0 8px "+col+"66";
    document.getElementById("gtxt").textContent=
      (used*100).toFixed(0)+"% / "+(d.daily_max_loss*100).toFixed(0)+"% limit";
  } else { g.style.display="none"; }

  drawChart(d.equity_curve);

  // coins + sleeve map
  const cc=document.getElementById("coins");
  if(!d.coins||!d.coins.length){
    cc.innerHTML='<div class="card"><div class="empty">coin yok</div></div>';
  }else{
    cc.innerHTML=d.coins.map(c=>`
      <div class="coin fade">
        <div class="ch">
          <span class="sym">${c.symbol}</span>
          <span class="cp ${cls(c.pnl)}">${c.total?signed(c.pnl):"—"}</span>
        </div>
        <div class="cstat">${c.total?(c.win+"/"+c.total+" · "+fmt(c.wr,0)+"%"):"trade yok"}</div>
        <div class="sleeves">${(c.sleeves||[]).map(s=>`<span class="sl">${s}</span>`).join("")||'<span class="cstat">kapalı</span>'}</div>
      </div>`).join("");
  }

  // positions
  const pc=document.getElementById("positions");
  if(!d.positions.length){
    pc.innerHTML='<div class="card"><div class="empty">Açık pozisyon yok — sinyal bekleniyor</div></div>';
  }else{
    pc.innerHTML=d.positions.map(p=>{
      // entry konumunu SL→TP aralığında göster
      const lo=Math.min(p.sl,p.tp), hi=Math.max(p.sl,p.tp);
      const frac=hi>lo?Math.max(0,Math.min(1,(p.current-lo)/(hi-lo))):0.5;
      // giriş fiyatının SL→TP aralığındaki konumu (işaret çizgisi)
      const efrac=hi>lo?Math.max(0,Math.min(1,(p.entry-lo)/(hi-lo))):0.5;
      return `
      <div class="pos ${p.side}-b fade">
        <div class="h">
          <div><span class="tag ${p.side}">${p.side.toUpperCase()} ${p.symbol}</span>
            <span class="strat">  ${p.strategy}</span></div>
          <div class="pnl ${cls(p.upnl)}">${signed(p.upnl)}</div>
        </div>
        <div class="grid">
          <span class="k">Giriş</span><span>$${fmt(p.entry)}</span>
          <span class="k">Şimdi</span><span class="${cls(p.pnl_pct)}">$${fmt(p.current)} (${p.pnl_pct>=0?"+":""}${fmt(p.pnl_pct,2)}%)</span>
          <span class="k">SL</span><span class="r">$${fmt(p.sl)}</span>
          <span class="k">TP</span><span class="g">$${fmt(p.tp)}</span>
          <span class="k">Süre</span><span>${fmt(p.age_h,1)}h</span>
          <span class="k">Miktar</span><span>${fmt(p.qty,4)}</span>
        </div>
        <div class="prog"><i style="left:0;width:${(frac*100).toFixed(0)}%;
          background:linear-gradient(90deg,var(--red),${frac>0.5?'var(--green)':'var(--accent)'})"></i>
          <span class="mk" style="left:${(efrac*100).toFixed(0)}%"></span></div>
      </div>`;}).join("");
  }

  // perf
  const P=d.perf;
  document.getElementById("p_total").textContent=P.total;
  document.getElementById("p_wr").textContent=fmt(P.win_rate,0)+"%";
  document.getElementById("p_pf").textContent=P.profit_factor===null?"∞":fmt(P.profit_factor,2);
  document.getElementById("p_dd").textContent=fmt(P.max_dd,1)+"%";
  const pp=document.getElementById("p_pnl");
  pp.textContent=signed(P.total_pnl); pp.className="v "+cls(P.total_pnl);

  // monthly bars
  const mc=document.getElementById("months");
  if(!d.monthly||!d.monthly.length){
    mc.innerHTML='<div class="empty">aylık veri yok</div>';
  }else{
    const peak=Math.max(...d.monthly.map(m=>Math.abs(m.pnl)),1);
    mc.innerHTML=d.monthly.map(m=>{
      const h=Math.max(3,Math.abs(m.pnl)/peak*70);
      const c=m.pnl>=0?"var(--green)":"var(--red)";
      const lbl=m.month?m.month.slice(5):"?";
      return `<div class="mb" title="${m.month}: ${signed(m.pnl)}">
        <div class="bar" style="height:${h}px;background:${c};box-shadow:0 0 8px ${c}55"></div>
        <div class="lbl">${lbl}</div></div>`;
    }).join("");
  }

  // strategies (with relative bar)
  const sc=document.getElementById("strats");
  if(!d.strategies.length){
    sc.innerHTML='<div class="empty">Henüz kapanan trade yok</div>';
  }else{
    const peak=Math.max(...d.strategies.map(s=>Math.abs(s.pnl)),1);
    sc.innerHTML=d.strategies.map(s=>{
      const w=(Math.abs(s.pnl)/peak*100).toFixed(0);
      const c=s.pnl>=0?"var(--green)":"var(--red)";
      return `<div class="strat-row">
        <span style="min-width:64px">${s.strategy}</span>
        <span class="sbar"><i style="width:${w}%;background:${c}"></i></span>
        <span class="sub" style="min-width:52px;text-align:right">${fmt(s.wr,0)}%</span>
        <b class="${cls(s.pnl)}" style="min-width:62px;text-align:right">${signed(s.pnl)}</b>
      </div>`;}).join("");
  }

  // regime badges (per-coin)
  const rb=document.getElementById("regbadge");
  if(d.regime && Object.keys(d.regime).length){
    rb.textContent = Object.entries(d.regime).map(([sym,r])=>
      `${sym} ${r.label} ADX ${r.adx}`).join(" · ");
  }

  // activity feed
  const ac=document.getElementById("activity");
  if(!d.activity||!d.activity.length){
    ac.innerHTML='<div class="empty">sinyal bekleniyor…</div>';
  }else{
    ac.innerHTML=d.activity.map(a=>{
      const dirCls = a.dir>0?"up":a.dir<0?"dn":"no";
      const dirTxt = a.dir>0?"▲":a.dir<0?"▼":"—";
      const acHtml = a.action==="exec"?'<span class="ac exec">GİRDİ</span>':
                     a.action.startsWith("block")?'<span class="ac block" title="'+a.action+'">BLOK</span>':"";
      return `<div class="act">
        <span class="at">${a.t}</span>
        <span class="ab ${dirCls}">${dirTxt}</span>
        <span class="ar"><b>${a.sym} ${a.strat}</b> ${a.reason}</span>
        ${acHtml}</div>`;
    }).join("");
  }

  // trades
  const tc=document.getElementById("trades");
  if(!d.trades.length){
    tc.innerHTML='<div class="empty">Henüz kapanan trade yok</div>';
  }else{
    tc.innerHTML=`<table><thead><tr>
      <th>Coin</th><th>Yön</th><th>Strateji</th><th class="right">PnL</th><th class="right">Sebep</th>
      </tr></thead><tbody>`+d.trades.map(t=>`
      <tr>
        <td><b>${t.symbol}</b></td>
        <td class="${t.side==='long'?'g':'r'}">${t.side==='long'?'L':'S'}</td>
        <td class="sub">${t.strategy}</td>
        <td class="right ${cls(t.pnl)}">${signed(t.pnl)}</td>
        <td class="right">${reasonBadge(t.reason)}</td>
      </tr>`).join("")+`</tbody></table>`;
  }
}

async function doRestart(){
  if(!confirm("Botu yeniden başlat? Önce git pull yapılır, sonra bot yeni kodla sıfırdan başlar. Açık pozisyonlar korunur.")) return;
  const btn=document.getElementById("rbtn"), msg=document.getElementById("rmsg");
  btn.classList.add("busy"); btn.querySelector("span:last-child").textContent="Başlatılıyor…";
  msg.textContent="git pull + restart isteniyor…";
  try{
    const r=await fetch("/api/restart",{method:"POST"});
    const j=await r.json();
    if(!r.ok){ throw new Error(j.error||("HTTP "+r.status)); }
    msg.textContent="✓ "+(j.pull&&j.pull!=="—"?j.pull.split("\\n").pop():"yeniden başlatılıyor")+" — bağlantı bekleniyor…";
    let tries=0;
    const wait=setInterval(async()=>{
      tries++;
      try{
        const s=await fetch("/api/state");
        if(s.ok){ clearInterval(wait); msg.textContent="✓ Bot ayakta — sayfa yenileniyor"; setTimeout(()=>location.reload(),800); }
      }catch(e){}
      if(tries>40){ clearInterval(wait); msg.textContent="Bot hâlâ gelmedi — logları kontrol et"; btn.classList.remove("busy"); btn.querySelector("span:last-child").textContent="Botu Yeniden Başlat"; }
    },1500);
  }catch(e){
    msg.textContent="✗ "+e.message;
    btn.classList.remove("busy"); btn.querySelector("span:last-child").textContent="Botu Yeniden Başlat";
  }
}

tick();
setInterval(tick, 3000);
window.addEventListener("resize", ()=>{ /* chart redraws on next tick */ });
</script>
</body>
</html>"""
