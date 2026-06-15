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

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class WebDashboard:
    def __init__(self, config, *, exchange, portfolio, db, initial_balance: float):
        self._cfg = config            # WebDashboardConfig
        self._exchange = exchange
        self._portfolio = portfolio
        self._db = db
        self._initial_balance = initial_balance
        self._runner = None
        self._site = None

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
            self._runner = web.AppRunner(app)
            await self._runner.setup()
            self._site = web.TCPSite(self._runner, self._cfg.host, self._cfg.port)
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

    # ── Güvenlik ───────────────────────────────────────────────────────────────

    def _authorized(self, request) -> bool:
        if not self._cfg.token:
            return True
        return request.query.get("token", "") == self._cfg.token

    # ── Routes ─────────────────────────────────────────────────────────────────

    async def _handle_index(self, request):
        from aiohttp import web
        if not self._authorized(request):
            return web.Response(status=401, text="Unauthorized — ?token= gerekli")
        return web.Response(text=_INDEX_HTML, content_type="text/html")

    async def _handle_state(self, request):
        from aiohttp import web
        if not self._authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            data = await self._build_state()
            return web.json_response(data)
        except Exception as e:
            logger.debug("dashboard state error: %s", e)
            return web.json_response({"error": str(e)}, status=500)

    # ── State ──────────────────────────────────────────────────────────────────

    async def _build_state(self) -> dict:
        balance = await self._exchange.get_balance()
        ret_pct = (
            (balance - self._initial_balance) / self._initial_balance * 100
            if self._initial_balance > 0 else 0.0
        )

        # Açık pozisyonlar — her birinin güncel fiyatıyla canlı PnL
        positions = []
        total_upnl = 0.0
        for p in self._portfolio.get_open_positions():
            try:
                price = await self._exchange.get_current_price(p.symbol)
            except Exception:
                price = p.entry_price
            upnl = p.direction * (price - p.entry_price) * p.quantity
            total_upnl += upnl
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
                "strategy": p.strategy_scores.get("strategy", "?"),
                "entry": p.entry_price,
                "current": price,
                "sl": p.sl_price,
                "tp": p.tp_price,
                "qty": p.quantity,
                "upnl": upnl,
                "pnl_pct": pnl_pct,
                "age_h": age_h,
            })

        today = datetime.now(timezone.utc).date().isoformat()
        daily_pnl = await self._db.get_daily_pnl(today)

        perf = await self._db.get_performance_summary()
        pf = perf.profit_factor
        pf_out = None if pf == float("inf") else round(pf, 2)

        breakdown = await self._db.get_strategy_breakdown()
        strat = []
        for s in breakdown:
            wr = s["win"] / s["total"] * 100 if s["total"] else 0.0
            strat.append({
                "strategy": s["strategy"] or "unknown",
                "total": s["total"], "win": s["win"],
                "wr": wr, "pnl": s["pnl"],
            })

        recent = await self._db.get_all_trades(limit=15)
        trades = []
        for t in recent:
            if t.exit_time is None:
                continue
            trades.append({
                "symbol": t.symbol.split("/")[0],
                "side": t.side,
                "strategy": (t.strategy_scores or {}).get("strategy", "?"),
                "entry": t.entry_price,
                "exit": t.exit_price,
                "pnl": t.pnl_usdt or 0.0,
                "reason": t.exit_reason or "",
                "exit_time": t.exit_time,
            })

        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "balance": balance,
            "initial_balance": self._initial_balance,
            "return_pct": ret_pct,
            "daily_pnl": daily_pnl,
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
            "strategies": strat,
            "trades": trades,
        }


_INDEX_HTML = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#0b0e14">
<title>BTC Bot</title>
<style>
  :root{
    --bg:#0b0e14; --card:#151a23; --card2:#1c222e; --line:#272f3d;
    --txt:#e6edf3; --dim:#8b97a8; --green:#26d07c; --red:#ff5c5c;
    --accent:#3b82f6;
  }
  *{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
  body{margin:0;background:var(--bg);color:var(--txt);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    padding:14px 12px 40px;font-size:15px}
  h1{font-size:17px;margin:0;font-weight:600;letter-spacing:.3px}
  .top{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}
  .dot{width:9px;height:9px;border-radius:50%;background:var(--green);
    display:inline-block;margin-right:6px;animation:pulse 2s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
  .sub{color:var(--dim);font-size:12px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;
    padding:14px;margin-bottom:12px}
  .bal{font-size:34px;font-weight:700;letter-spacing:-.5px}
  .row{display:flex;gap:10px;margin-top:10px}
  .row .box{flex:1;background:var(--card2);border-radius:10px;padding:10px 12px}
  .box .k{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.5px}
  .box .v{font-size:18px;font-weight:600;margin-top:3px}
  .sec{font-size:12px;color:var(--dim);text-transform:uppercase;letter-spacing:.6px;
    margin:18px 4px 8px;font-weight:600}
  .pos{background:var(--card);border:1px solid var(--line);border-radius:12px;
    padding:12px;margin-bottom:10px}
  .pos .h{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
  .tag{font-size:11px;font-weight:700;padding:3px 9px;border-radius:7px}
  .long{background:rgba(38,208,124,.16);color:var(--green)}
  .short{background:rgba(255,92,92,.16);color:var(--red)}
  .strat{color:var(--dim);font-size:11px}
  .grid{display:grid;grid-template-columns:repeat(2,1fr);gap:6px 14px;font-size:13px}
  .grid .k{color:var(--dim)}
  .grid span:nth-child(even){text-align:right;font-variant-numeric:tabular-nums}
  .pnl{font-size:20px;font-weight:700;font-variant-numeric:tabular-nums}
  .pos.long-b{border-left:3px solid var(--green)}
  .pos.short-b{border-left:3px solid var(--red)}
  .g{color:var(--green)} .r{color:var(--red)}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th{color:var(--dim);font-weight:500;text-align:left;font-size:11px;
    text-transform:uppercase;padding:6px 4px;border-bottom:1px solid var(--line)}
  td{padding:8px 4px;border-bottom:1px solid var(--line);
    font-variant-numeric:tabular-nums}
  tr:last-child td{border-bottom:none}
  .right{text-align:right}
  .empty{color:var(--dim);text-align:center;padding:18px;font-size:13px}
  .strat-row{display:flex;justify-content:space-between;padding:8px 0;
    border-bottom:1px solid var(--line);font-size:13px}
  .strat-row:last-child{border-bottom:none}
  .err{color:var(--red);text-align:center;padding:20px}
</style>
</head>
<body>
  <div class="top">
    <h1><span class="dot"></span>BTC Trading Bot</h1>
    <span class="sub" id="ts">…</span>
  </div>

  <div class="card">
    <div class="sub">Bakiye</div>
    <div class="bal" id="bal">$—</div>
    <div class="row">
      <div class="box"><div class="k">Getiri</div><div class="v" id="ret">—</div></div>
      <div class="box"><div class="k">Bugün</div><div class="v" id="daily">—</div></div>
      <div class="box"><div class="k">Açık PnL</div><div class="v" id="upnl">—</div></div>
    </div>
  </div>

  <div class="sec">Açık Pozisyonlar (<span id="oc">0</span>)</div>
  <div id="positions"></div>

  <div class="sec">Performans</div>
  <div class="card">
    <div class="row">
      <div class="box"><div class="k">Trade</div><div class="v" id="p_total">—</div></div>
      <div class="box"><div class="k">WR</div><div class="v" id="p_wr">—</div></div>
    </div>
    <div class="row">
      <div class="box"><div class="k">Profit Factor</div><div class="v" id="p_pf">—</div></div>
      <div class="box"><div class="k">Max DD</div><div class="v" id="p_dd">—</div></div>
    </div>
    <div class="row">
      <div class="box"><div class="k">Toplam PnL</div><div class="v" id="p_pnl">—</div></div>
    </div>
  </div>

  <div class="sec">Strateji Kırılımı</div>
  <div class="card" id="strats"><div class="empty">—</div></div>

  <div class="sec">Son Trade'ler</div>
  <div class="card" id="trades"><div class="empty">—</div></div>

<script>
const TOKEN = new URLSearchParams(location.search).get("token") || "";
const fmt = (n,d=2)=>Number(n).toLocaleString("en-US",{minimumFractionDigits:d,maximumFractionDigits:d});
const money = n => (n>=0?"$":"-$")+fmt(Math.abs(n));
const signed = n => (n>=0?"+":"-")+"$"+fmt(Math.abs(n));
const cls = n => n>=0?"g":"r";

async function tick(){
  try{
    const r = await fetch("/api/state"+(TOKEN?("?token="+encodeURIComponent(TOKEN)):""));
    if(!r.ok){throw new Error("HTTP "+r.status)}
    const d = await r.json();
    render(d);
  }catch(e){
    document.getElementById("ts").textContent = "bağlantı yok";
  }
}

function render(d){
  const t = new Date(d.ts);
  document.getElementById("ts").textContent = t.toLocaleTimeString("tr-TR");
  document.getElementById("bal").textContent = "$"+fmt(d.balance);
  const ret = document.getElementById("ret");
  ret.textContent = (d.return_pct>=0?"+":"")+fmt(d.return_pct,1)+"%";
  ret.className = "v "+cls(d.return_pct);
  const dl = document.getElementById("daily");
  dl.textContent = signed(d.daily_pnl); dl.className = "v "+cls(d.daily_pnl);
  const up = document.getElementById("upnl");
  up.textContent = signed(d.unrealized_pnl); up.className = "v "+cls(d.unrealized_pnl);
  document.getElementById("oc").textContent = d.open_count;

  // positions
  const pc = document.getElementById("positions");
  if(!d.positions.length){
    pc.innerHTML = '<div class="card"><div class="empty">Açık pozisyon yok — beklemede</div></div>';
  }else{
    pc.innerHTML = d.positions.map(p=>`
      <div class="pos ${p.side}-b">
        <div class="h">
          <div><span class="tag ${p.side}">${p.side.toUpperCase()} ${p.symbol}</span>
            <span class="strat">  ${p.strategy}</span></div>
          <div class="pnl ${cls(p.upnl)}">${signed(p.upnl)}</div>
        </div>
        <div class="grid">
          <span class="k">Entry</span><span>$${fmt(p.entry)}</span>
          <span class="k">Şimdi</span><span class="${cls(p.pnl_pct)}">$${fmt(p.current)} (${p.pnl_pct>=0?"+":""}${fmt(p.pnl_pct,2)}%)</span>
          <span class="k">SL</span><span class="r">$${fmt(p.sl)}</span>
          <span class="k">TP</span><span class="g">$${fmt(p.tp)}</span>
          <span class="k">Süre</span><span>${fmt(p.age_h,1)}h</span>
          <span class="k">Qty</span><span>${fmt(p.qty,4)}</span>
        </div>
      </div>`).join("");
  }

  // perf
  const P = d.perf;
  document.getElementById("p_total").textContent = P.total;
  document.getElementById("p_wr").textContent = fmt(P.win_rate,0)+"% ("+P.wins+"/"+P.total+")";
  document.getElementById("p_pf").textContent = P.profit_factor===null?"∞":fmt(P.profit_factor,2);
  document.getElementById("p_dd").textContent = fmt(P.max_dd,1)+"%";
  const pp = document.getElementById("p_pnl");
  pp.textContent = signed(P.total_pnl); pp.className = "v "+cls(P.total_pnl);

  // strategies
  const sc = document.getElementById("strats");
  if(!d.strategies.length){
    sc.innerHTML = '<div class="empty">Henüz kapanan trade yok</div>';
  }else{
    sc.innerHTML = d.strategies.map(s=>`
      <div class="strat-row">
        <span>${s.strategy}</span>
        <span><span class="sub">${s.win}/${s.total} · ${fmt(s.wr,0)}%</span>
          &nbsp;<b class="${cls(s.pnl)}">${signed(s.pnl)}</b></span>
      </div>`).join("");
  }

  // trades
  const tc = document.getElementById("trades");
  if(!d.trades.length){
    tc.innerHTML = '<div class="empty">Henüz kapanan trade yok</div>';
  }else{
    tc.innerHTML = `<table><thead><tr>
      <th>Coin</th><th>Yön</th><th>Strateji</th><th class="right">PnL</th><th class="right">Sebep</th>
      </tr></thead><tbody>` + d.trades.map(t=>`
      <tr>
        <td>${t.symbol}</td>
        <td class="${t.side==='long'?'g':'r'}">${t.side==='long'?'L':'S'}</td>
        <td class="sub">${t.strategy}</td>
        <td class="right ${cls(t.pnl)}">${signed(t.pnl)}</td>
        <td class="right sub">${(t.reason||'').replace('_',' ')}</td>
      </tr>`).join("") + `</tbody></table>`;
  }
}

tick();
setInterval(tick, 3000);
</script>
</body>
</html>"""
