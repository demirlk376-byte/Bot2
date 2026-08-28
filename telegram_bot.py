from __future__ import annotations

import logging
from typing import Optional

from config import TelegramConfig
from risk import TradeSetup
from strategies.signal_combiner import CombinedSignal, strategy_label

logger = logging.getLogger(__name__)


def _fmt_price(v: float) -> str:
    """Adaptive price precision so sub-$1 coins (XRP, DOGE) don't collapse to
    $0.00 in notifications. Mirrors the /positions formatter."""
    if v >= 100:
        return f"${v:,.2f}"
    if v >= 1:
        return f"${v:,.4f}"
    return f"${v:,.6f}"


class TelegramNotifier:
    """Telegram bildirimleri + telefondan interaktif kontrol.

    Bildirim modu her zaman çalışır (send_* metodları). Eğer attach_context()
    ile bot bileşenleri verilirse, komut dinleyici de başlar ve kullanıcı
    telefondan şunları yapabilir:
      /status    – bakiye, açık pozisyon, günlük PnL
      /positions – açık pozisyon detayı
      /balance   – bakiye + getiri
      /stats     – performans özeti (trade, WR, PnL)
      /rapor     – ay sonu raporu: sleeve kırılımı, temiz dönem, R:R, açık pozisyon
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
        app.add_handler(CommandHandler("rapor", self._cmd_rapor))
        app.add_handler(CommandHandler("report", self._cmd_rapor))
        app.add_handler(CommandHandler("pause", self._cmd_pause))
        app.add_handler(CommandHandler("resume", self._cmd_resume))
        app.add_handler(CommandHandler("close", self._cmd_close))
        app.add_handler(CommandHandler("strategy", self._cmd_strategy))

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

    async def _invested(self) -> float:
        """Toplam yatırılan sermaye = ilk bakiye + sonradan eklenenler. Getiriyi
        bunun üzerinden hesaplarız ki aylık para eklemeleri sahte 'kâr' gibi
        görünmesin (dashboard ile aynı mantık). DB yoksa ilk bakiyeye düşer."""
        if self._db is None:
            return self._initial_balance
        inception = await self._db.get_meta_float(
            "inception_balance", self._initial_balance
        )
        deposits = await self._db.get_meta_float("total_deposits", 0.0)
        return inception + deposits

    async def _tutarlilik(self, equity: float, invested: float, upnl: float) -> str:
        """İKİ BAĞIMSIZ KAYNAK KARŞILAŞTIRMASI — 28 Ağustos hatasının panzehiri.

        İddia edilen kâr  = equity − yatırılan sermaye        (borsa + meta)
        Defterdeki kâr    = Σ kapanan işlem PnL + açık uPnL   (trades tablosu)

        İkisi uyuşmuyorsa en olası sebep KAYDEDİLMEMİŞ bir para giriş/çıkışıdır:
        para gelir, `total_deposits` değişmez, fark doğrudan "kâr" diye görünür.
        O gün tam bu oldu — $69.76'lık bakiye artışının tamamı kâra yazıldı.

        Boş string döner (uyarı yok) ya da tek satırlık uyarı. DB okunamazsa
        SESSİZ kalır: yanlış alarm, sessizlikten daha kötü.
        """
        if self._db is None:
            return ""
        try:
            perf = await self._db.get_performance_summary(
                is_paper=self._app_config.exchange.paper_mode)
            defter = float(perf.total_pnl_usdt) + upnl
        except Exception:
            return ""
        iddia = equity - invested
        fark = iddia - defter
        # Eşik: ücret/fonlama kayması küçüktür; $5 ve sermayenin %2'sinin büyüğü.
        esik = max(5.0, abs(invested) * 0.02)
        if abs(fark) <= esik:
            return ""
        yon = "GİRİŞ" if fark > 0 else "ÇIKIŞ"
        return (f"\n⚠️ <b>Defter uyuşmuyor</b> (fark <code>${fark:+.2f}</code>)\n"
                f"Defterdeki işlem kârı <code>${defter:+.2f}</code> ama "
                f"equity−yatırılan <code>${iddia:+.2f}</code> diyor.\n"
                f"En olası sebep: KAYDEDİLMEMİŞ para {yon}. Düzelt:\n"
                f"<code>para_ekle.py --tespit</code>")

    async def _equity_and_upnl(self) -> tuple[float, float]:
        """Return (equity, unrealized_pnl) with FRESH per-symbol prices.

        get_balance() returns FREE balance (locked margin excluded) in live mode,
        and the portfolio's cached uPnL is only refreshed on candle close (up to
        1h stale). So we recompute uPnL from live prices and add the locked margin
        back, matching the web dashboard and the executor's daily-loss measure —
        otherwise /status understates equity by the margin and shows stale PnL."""
        free = await self._exchange.get_balance()
        lev = max(getattr(self._app_config.exchange, "leverage", 1), 1)
        upnl = 0.0
        locked = 0.0
        for p in self._portfolio.get_open_positions():
            try:
                price = await self._exchange.get_current_price(p.symbol)
            except Exception:
                price = p.entry_price
            if p.entry_price > 0:
                upnl += p.direction * (price - p.entry_price) * p.quantity
                locked += p.entry_price * p.quantity / lev
        equity = free + locked + upnl
        # BORSA GERÇEĞİ ÖNCE. Yukarıdaki yeniden-kurulum (free+locked+uPnL) bizim
        # TAHMİNİMİZ; kilitli marjı entry_price/leverage ile yaklaşıklıyor ve
        # borsanın kendi equity'sinden sapabilir. execution.current_equity() zaten
        # get_equity()'i tercih ediyor — /status ondan FARKLI bir sayı gösterirse
        # aynı anda iki "bakiye" ortaya çıkar. Bu tam da 28 Ağustos'ta olan şeydi.
        # Borsa okunabiliyorsa onun rakamı kullanılır; okunamazsa tahmine düşer.
        try:
            if hasattr(self._exchange, "get_equity"):
                eq_borsa = await self._exchange.get_equity()
                if eq_borsa and eq_borsa > 0:
                    equity = eq_borsa
        except Exception:
            pass
        # Prefer the exchange's TRUE account equity (cash + locked margin + uPnL).
        # The reconstruction above misses margin locked in positions the portfolio
        # isn't tracking (e.g. orphaned positions still open on MEXC after a failed
        # close): it would then report only the free balance and a false huge loss.
        # get_equity() reads the real figure straight from MEXC. Falls back to the
        # reconstruction if the exchange read fails.
        if hasattr(self._exchange, "get_equity"):
            try:
                exch_eq = await self._exchange.get_equity()
                if exch_eq > 0:
                    equity = exch_eq
            except Exception:
                pass
        return equity, upnl

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
            "/rapor – AY SONU RAPORU (sleeve, temiz dönem, R:R, açık)\n"
            "/strategy – strateji bazlı performans\n"
            "/pause – yeni trade'leri durdur\n"
            "/resume – trade'leri başlat\n"
            "/close BTC – BTC pozisyonunu kapat\n"
            "/close all – tüm pozisyonları kapat")

    async def _cmd_status(self, update, context) -> None:
        if not self._authorized(update):
            return
        try:
            equity, upnl = await self._equity_and_upnl()
            invested = await self._invested()
            true_pnl = equity - invested
            ret = (true_pnl / invested * 100) if invested > 0 else 0.0
            n_open = self._portfolio.get_open_position_count()
            halted = self._executor.is_halted()
            paper = self._app_config.exchange.paper_mode
            text = (
                f"<b>Durum</b> ({'PAPER' if paper else 'CANLI'})\n"
                f"Equity: <code>${equity:,.2f}</code>\n"
                # "Gerçek kâr" tek başına yanıltıcıydı: kaydedilmemiş bir para
                # yatırma doğrudan kâra yazılıyor ve fark GÖRÜNMÜYORDU. Yatırılan
                # sermaye de basılırsa hata anında gözle yakalanır.
                f"Yatırılan sermaye: <code>${invested:,.2f}</code>\n"
                f"Gerçek kâr: <code>${true_pnl:+.2f}</code> ({ret:+.1f}%)\n"
                f"Açık pozisyon: <code>{n_open}</code>\n"
                f"Gerçekleşmemiş PnL: <code>${upnl:+.2f}</code>\n"
                f"Trade durumu: <code>{'DURDURULDU' if halted else 'AKTİF'}</code>"
                + await self._tutarlilik(equity, invested, upnl)
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
        _fp = _fmt_price
        lines = ["<b>Açık Pozisyonlar</b>"]
        for p in positions:
            try:
                price = await self._exchange.get_current_price(p.symbol)
            except Exception:
                price = p.entry_price
            upnl = (p.direction * (price - p.entry_price) * p.quantity
                    if p.entry_price > 0 else 0.0)
            lines.append(
                f"{p.side.upper()} {p.symbol}  <code>${upnl:+.2f}</code>\n"
                f"  Entry {_fp(p.entry_price)}  Now {_fp(price)}\n"
                f"  SL {_fp(p.sl_price)}  TP {_fp(p.tp_price)}\n"
                f"  Qty <code>{p.quantity:.4f}</code>"
            )
        await self._reply(update, "\n".join(lines))

    async def _cmd_balance(self, update, context) -> None:
        if not self._authorized(update):
            return
        try:
            equity, _upnl = await self._equity_and_upnl()
            invested = await self._invested()
            true_pnl = equity - invested
            ret = (true_pnl / invested * 100) if invested > 0 else 0.0
            await self._reply(update,
                f"Equity: <code>${equity:,.2f}</code>\n"
                f"Yatırılan sermaye: <code>${invested:,.2f}</code>\n"
                f"Gerçek kâr: <code>${true_pnl:+.2f}</code> ({ret:+.2f}%)"
                + await self._tutarlilik(equity, invested, _upnl))
        except Exception as e:
            await self._reply(update, f"balance hatası: {e}")

    async def _cmd_stats(self, update, context) -> None:
        if not self._authorized(update):
            return
        try:
            ip = self._app_config.exchange.paper_mode
            perf = await self._db.get_performance_summary(is_paper=ip)
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

    async def _cmd_strategy(self, update, context) -> None:
        if not self._authorized(update):
            return
        try:
            ip = self._app_config.exchange.paper_mode
            breakdown = await self._db.get_strategy_breakdown(is_paper=ip)
            if not breakdown:
                await self._reply(update, "Henüz kapanmış trade yok.")
                return
            lines = ["<b>Strateji Performansı</b>"]
            for s in breakdown:
                wr = s["win"] / s["total"] * 100 if s["total"] > 0 else 0.0
                pnl_sign = "🟢" if s["pnl"] >= 0 else "🔴"
                label = strategy_label(s["strategy"] or "unknown")
                lines.append(
                    f"{pnl_sign} <code>{label:12s}</code> "
                    f"T:{s['total']} W:{s['win']} ({wr:.0f}%) "
                    f"<code>${s['pnl']:+.2f}</code>"
                )
            await self._reply(update, "\n".join(lines))
        except Exception as e:
            await self._reply(update, f"strategy hatası: {e}")

    async def _cmd_rapor(self, update, context) -> None:
        """Ay sonu kontrolünün telefondan tek komutla alınabilir hali.

        VPS'e erişimi olmayan biri için tasarlandı: canlı raporun (live_report.py)
        karar verdiren kısımlarını tek mesaja sığdırır. trades.db SALT-OKUNUR
        açılır ve ayrı bir thread'de okunur — bot aynı dosyaya yazarken kilit
        çekişmesi yaratmasın ve event loop bloklanmasın."""
        if not self._authorized(update):
            return
        import asyncio as _aio, sqlite3, json as _json
        path = getattr(self._db, "_path", "trades.db")

        def _build(live_bal) -> str:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=15)
            try:
                rows = con.execute(
                    "SELECT symbol,side,entry_price,exit_price,sl_price,tp_price,"
                    "pnl_usdt,entry_time,strategy_scores FROM trades WHERE is_paper=0"
                ).fetchall()
                # BAKİYE: borsadan CANLI gelir (live_bal). daily_stats YALNIZCA YEDEK —
                # o satır gün BAŞINDA yazılır ve gün içinde ESKİR. Bu tam olarak /status ile
                # /rapor arasında $4.47'lik sapmaya yol açmıştı (2026-08-02, kullanıcı yakaladı):
                # /status $184.53 (canlı) vs /rapor $180.06 (bayat snapshot). Aynı bayatlık
                # daha önce NEAR'ın +$10.20'lik kapanışında da tespit edilmişti.
                bal = con.execute("SELECT ending_balance FROM daily_stats WHERE is_paper=0 "
                                  "ORDER BY date DESC LIMIT 1").fetchone()
            finally:
                con.close()
            if not rows:
                return "Canlı işlem kaydı yok."

            def sleeve_of(js):
                try:
                    s = _json.loads(js or "{}")
                    for k in ("strategy", "sleeve", "source"):
                        if k in s: return str(s[k])
                except Exception: pass
                return "?"

            DEPLOY = {"donchian", "squeeze", "mean_rev", "bb"}
            CUT = "2026-07-16"          # kapalı sleeve'lerin son işlemi
            closed = [r for r in rows if r[3] is not None]
            openp = [r for r in rows if r[3] is None]
            pnl = sum(r[6] or 0.0 for r in closed)
            wins = [r for r in closed if (r[6] or 0) > 0]
            gp = sum(r[6] for r in wins)
            gl = -sum(r[6] for r in closed if (r[6] or 0) < 0)
            pf = (gp / gl) if gl > 0 else float("inf")
            wr = len(wins) / len(closed) * 100 if closed else 0.0

            per = {}
            for r in rows:
                sv = sleeve_of(r[8])
                key = sv if sv in DEPLOY else "[kapalı]"
                a = per.setdefault(key, [0, 0.0])
                a[0] += 1; a[1] += (r[6] or 0.0)

            temiz = [r for r in closed if str(r[7]) >= CUT]
            tw = [r for r in temiz if (r[6] or 0) > 0]
            tgp = sum(r[6] for r in tw)
            tgl = -sum(r[6] for r in temiz if (r[6] or 0) < 0)
            tpf = (tgp / tgl) if tgl > 0 else float("inf")

            # R:R yapısal kontrol — az işlemle bile anlamlı (giriş=0 olanlar hariç)
            rr = {}
            for r in rows:
                if not r[2] or r[2] <= 0: continue
                risk = abs(r[2] - r[4])
                if risk <= 0: continue
                rr.setdefault(sleeve_of(r[8]), []).append(abs(r[5] - r[2]) / risk)

            L = [f"<b>📋 AY SONU RAPORU</b>"]
            if live_bal is not None:
                L.append(f"Bakiye <code>${live_bal:,.2f}</code> <i>(canlı)</i>")
            elif bal and bal[0]:
                L.append(f"Bakiye <code>${float(bal[0]):,.2f}</code> <i>(DB, bayat olabilir)</i>")
            L.append(f"kapanan <code>{len(closed)}</code> · açık <code>{len(openp)}</code>")
            L.append(f"PnL <code>${pnl:+.2f}</code> · WR <code>%{wr:.0f}</code> · "
                     f"PF <code>{pf:.2f}</code>")
            L.append(f"<i>çıpa: PF 1.45 / WR %44 (backtest)</i>")

            L.append("\n<b>Sleeve</b>")
            for k in sorted(per, key=lambda x: -per[x][1]):
                L.append(f"  {k:9s} n={per[k][0]:<3d} <code>${per[k][1]:+.2f}</code>")

            L.append(f"\n<b>Temiz dönem</b> ({CUT} sonrası)")
            L.append(f"  n=<code>{len(temiz)}</code> · <code>${sum(r[6] or 0 for r in temiz):+.2f}</code>"
                     f" · PF <code>{tpf:.2f}</code>")

            L.append("\n<b>R:R (yapısal)</b>")
            for k in sorted(rr):
                exp = 1.667 if k in ("mean_rev", "bb") else 2.5
                L.append(f"  {k:9s} <code>{sum(rr[k])/len(rr[k]):.2f}</code> (hedef {exp})")

            if openp:
                L.append("\n<b>Açık</b>")
                for r in openp:
                    L.append(f"  {r[0].split('/')[0]:5s} {r[1]:5s} "
                             f"<code>{r[2]:.5g}</code> SL <code>{r[4]:.5g}</code>")

            L.append("\n<i>⚠ n&lt;30 ise PF/WR GÜRÜLTÜ — yön göstergesi, sonuç değil.</i>")
            return "\n".join(L)

        # Bakiyeyi ÖNCE borsadan çek (async), sonra salt-okunur DB işini thread'e ver.
        live_bal = None
        try:
            # /status ve /balance ile AYNI kaynak. Ham get_balance() canlıda SERBEST bakiyeyi
            # döndürür (kilitli marjin HARİÇ) → açık pozisyon varken /rapor ile /status yine
            # ayrışırdı. Tek-doğru-kaynak kuralı: equity her yerde aynı yerden gelir.
            equity, _u = await self._equity_and_upnl()
            live_bal = float(equity)
        except Exception as e:
            logger.debug("rapor: canlı equity alınamadı, DB'ye düşülüyor: %s", e)
        try:
            text = await _aio.to_thread(_build, live_bal)
        except Exception as e:
            text = f"rapor hatası: {e}"
        await self._reply(update, text)

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
        args = context.args if context and context.args else []
        if not args:
            await self._reply(update,
                "Kullanım:\n"
                "/close BTC — sadece BTC pozisyonunu kapat\n"
                "/close all — tüm pozisyonları kapat")
            return
        scope = args[0].upper()
        all_positions = list(self._portfolio.get_open_positions())
        if not all_positions:
            await self._reply(update, "Kapatılacak açık pozisyon yok.")
            return
        if scope == "ALL":
            targets = all_positions
        else:
            # Match by coin name: "BTC" matches "BTC/USDT:USDT"
            targets = [p for p in all_positions if p.symbol.startswith(scope + "/")]
            if not targets:
                syms = ", ".join(p.symbol for p in all_positions)
                await self._reply(update, f"'{scope}' ile eşleşen pozisyon yok. Açık: {syms}")
                return
        closed = 0
        for p in targets:
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
            f"Entry: <code>{_fmt_price(setup.entry_price)}</code>\n"
            f"SL: <code>{_fmt_price(setup.sl_price)}</code> ({sl_pct:+.2f}%)\n"
            f"TP: <code>{_fmt_price(setup.tp_price)}</code> ({tp_pct:+.2f}%)\n"
            f"Qty: <code>{setup.quantity:.4f} {setup.symbol.split('/')[0]}</code> | Risk: <code>${setup.risk_usdt:.2f} ({setup.risk_pct:.1%})</code>\n"
            f"Confidence: <code>{signal.confidence:.0%}</code> | Strategy: <code>{strategy_label(signal.dominant_strategy)}</code>"
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
        pnl_pct: float | None = None,
    ) -> None:
        emoji = "🟢" if pnl_usdt >= 0 else "🔴"
        # Prefer the caller-supplied return-on-margin % (matches the DB stat); fall
        # back to raw price-move % when not provided.
        if pnl_pct is None:
            pnl_pct = (exit_price - entry_price) / entry_price * 100 * (1 if side == "long" else -1)
        text = (
            f"{emoji} <b>TRADE CLOSED</b> - {symbol}\n"
            f"Side: <code>{side.upper()}</code>\n"
            f"Entry: <code>{_fmt_price(entry_price)}</code> → Exit: <code>{_fmt_price(exit_price)}</code>\n"
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
        # ⚠ ETİKET DÜZELTİLDİ: main.py buraya start_equity gönderiyor — YENİ GÜNÜN
        # BAŞLANGIÇ equity'si, "güncel bakiye" DEĞİL. "Balance" diye etiketlenince
        # heartbeat'in serbest bakiyesiyle ve /status'un equity'siyle üç farklı
        # sayı aynı isimle görünüyordu (28 Ağustos).
        text = (
            f"<b>Günlük Özet</b>\n"
            f"İşlem: <code>{total_trades}</code> | Kazanma: <code>{win_rate:.0%}</code>\n"
            f"Günlük PnL: <code>${total_pnl:+.2f}</code>\n"
            f"Yeni günün başlangıç equity'si: <code>${balance:,.2f}</code>"
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
