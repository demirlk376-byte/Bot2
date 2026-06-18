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
    def __init__(
        self, config, *, exchange, portfolio, db, initial_balance: float,
        sleeve_layout: dict | None = None, paper_mode: bool = True,
        leverage: int = 1,
    ):
        self._cfg = config            # WebDashboardConfig
        self._exchange = exchange
        self._portfolio = portfolio
        self._db = db
        self._initial_balance = initial_balance
        self._sleeve_layout = sleeve_layout or {}
        self._paper_mode = paper_mode
        self._leverage = max(1, int(leverage))
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

        # Total account value (equity), not just free balance, so an open
        # position's locked margin isn't mistaken for a loss.
        equity = balance + locked_margin + total_upnl

        # Invested capital = first balance + every deposit the user added later.
        # True profit is equity − invested, so monthly top-ups never look like
        # trading gains. Read from the DB each tick so a new deposit shows up
        # immediately (no restart needed).
        inception = await self._db.get_meta_float(
            "inception_balance", self._initial_balance
        )
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
                "strategy": s["strategy"] or "unknown",
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
                "strategy": (t.strategy_scores or {}).get("strategy", "?"),
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
            "paper_mode": self._paper_mode,
            "balance": balance,
            "equity": equity,
            "invested": invested,
            "true_pnl": true_pnl,
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
            "coins": coins,
            "strategies": strat,
            "equity_curve": [e["eq"] for e in eq_curve],
            "monthly": monthly,
            "trades": trades,
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

  <div class="sec"><span>Son Trade'ler</span></div>
  <div class="card" id="trades"><div class="empty">—</div></div>
</div>

<script>
const TOKEN = new URLSearchParams(location.search).get("token") || "";
const fmt = (n,d=2)=>Number(n).toLocaleString("en-US",{minimumFractionDigits:d,maximumFractionDigits:d});
const compact = n => Math.abs(n)>=1000 ? (n/1000).toFixed(1)+"k" : fmt(n,Math.abs(n)<10?2:0);
const signed = n => (n>=0?"+$":"-$")+compact(Math.abs(n));
const cls = n => n>=0?"g":"r";
const NS = "http://www.w3.org/2000/svg";

async function tick(){
  try{
    const r = await fetch("/api/state"+(TOKEN?("?token="+encodeURIComponent(TOKEN)):""));
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
  document.getElementById("ts").textContent = new Date(d.ts).toLocaleTimeString("tr-TR");
  const mode=document.getElementById("mode");
  mode.textContent = d.paper_mode?"PAPER":"LIVE";
  mode.className = "badge "+(d.paper_mode?"paper":"live");
  document.getElementById("bal").textContent = "$"+fmt(d.equity);
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
      const tpSide=p.side==='long';
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
          background:linear-gradient(90deg,var(--red),${frac>0.5?'var(--green)':'var(--accent)'})"></i></div>
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
        <td class="right sub">${(t.reason||'').replace('_',' ')}</td>
      </tr>`).join("")+`</tbody></table>`;
  }
}

tick();
setInterval(tick, 3000);
window.addEventListener("resize", ()=>{ /* chart redraws on next tick */ });
</script>
</body>
</html>"""
