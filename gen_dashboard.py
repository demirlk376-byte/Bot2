"""
gen_dashboard.py — paper_state.json + paper_trades.csv → dashboard.html

GitHub Actions'da çalışır; her saat sonuçları güzel bir HTML'e çevirir.
GitHub Pages etkinleştirilirse https://<user>.github.io/Bot2/ adresinden açılır.
"""
from __future__ import annotations

import csv
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE    = Path("paper_state.json")
TRADES_CSV    = Path("paper_trades.csv")
STATE_FILE_V2 = Path("paper_state_v2.json")
TRADES_CSV_V2 = Path("paper_trades_v2.csv")
OUT_HTML      = Path("index.html")
DB_PATH       = Path(os.getenv("DB_PATH", "./trades.db"))
INIT_BALANCE  = float(os.getenv("PAPER_INITIAL_BALANCE", "10000"))


def load_from_db(db_path: Path):
    """Build (coins, trades) from the live bot's trades.db. The engine uses ONE
    shared account balance, so per-coin 'balance' here is INIT + that coin's pnl
    contribution (for comparison only); the real account balance is the sum."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM trades").fetchall()]
    conn.close()

    coins: dict[str, dict] = {}
    trades: list[dict] = []
    for r in rows:
        coin = (r["symbol"] or "?").split("/")[0]
        c = coins.setdefault(coin, {
            "balance": INIT_BALANCE, "n_trades": 0, "n_wins": 0,
            "total_pnl": 0.0, "position": None,
        })
        if r["exit_time"]:  # closed trade
            pnl = float(r["pnl_usdt"] or 0)
            c["n_trades"] += 1
            c["total_pnl"] += pnl
            c["balance"] += pnl
            if pnl > 0:
                c["n_wins"] += 1
            trades.append({
                "coin": coin,
                "side": "BUY" if r["side"] == "long" else "SELL",
                "entry_price": r["entry_price"],
                "exit_price": r["exit_price"] or 0,
                "pnl_usdt": pnl,
                "exit_reason": r["exit_reason"] or "?",
                "exit_time": r["exit_time"] or "",
            })
        else:  # open position
            c["position"] = {
                "side": "BUY" if r["side"] == "long" else "SELL",
                "entry_price": r["entry_price"],
                "sl_price": r["sl_price"], "tp_price": r["tp_price"],
            }
    trades.sort(key=lambda t: t["exit_time"])
    return coins, trades

COIN_ICONS = {
    "BTC": "₿", "ETH": "Ξ", "SOL": "◎", "BNB": "B", "XRP": "✕",
}


def load_state(path=STATE_FILE) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {"coins": {}}


def load_trades(path=TRADES_CSV) -> list[dict]:
    if not path.exists():
        return []
    with open(path) as f:
        return list(csv.DictReader(f))


def pct(val: float, init: float = 10_000.0) -> str:
    p = (val - init) / init * 100
    sign = "+" if p >= 0 else ""
    return f"{sign}{p:.2f}%"


def color_class(val: float, init: float = 10_000.0) -> str:
    return "pos" if val >= init else "neg"


def candidate_badge(data: dict) -> str:
    n = data.get("n_trades", 0)
    bal = data.get("balance", 10_000)
    wins = data.get("n_wins", 0)
    wr = wins / n if n > 0 else 0
    if n < 3:
        return '<span class="badge wait">⏳ Veri bekleniyor</span>'
    if bal > 10_000 and wr >= 0.45:
        return '<span class="badge ok">✅ Canlı aday</span>'
    if bal < 9_500:
        return '<span class="badge bad">❌ Edge yok</span>'
    return '<span class="badge wait">⏳ İzleniyor</span>'


def build_coin_cards(coins: dict) -> str:
    cards = []
    for coin, data in coins.items():
        bal = data.get("balance", 10_000)
        n   = data.get("n_trades", 0)
        wins = data.get("n_wins", 0)
        wr  = f"{wins/n*100:.0f}%" if n > 0 else "—"
        pos = data.get("position")
        pos_html = ""
        if pos:
            side = pos.get("side", "?").upper()
            ep   = pos.get("entry_price", 0)
            sl   = pos.get("sl_price", 0)
            tp   = pos.get("tp_price", 0)
            pos_html = f"""
            <div class="open-pos">
                <span class="pos-side {'long' if side=='BUY' else 'short'}">{side}</span>
                <span>Giriş: <b>${ep:,.2f}</b></span>
                <span>SL: ${sl:,.2f}</span>
                <span>TP: ${tp:,.2f}</span>
            </div>"""

        icon = COIN_ICONS.get(coin, coin[0])
        cc   = color_class(bal)
        cards.append(f"""
        <div class="card">
            <div class="card-header">
                <span class="coin-icon">{icon}</span>
                <span class="coin-name">{coin}</span>
                {candidate_badge(data)}
            </div>
            <div class="card-body">
                <div class="stat-row">
                    <div class="stat">
                        <div class="stat-label">Bakiye</div>
                        <div class="stat-val {cc}">${bal:,.2f}</div>
                    </div>
                    <div class="stat">
                        <div class="stat-label">Getiri</div>
                        <div class="stat-val {cc}">{pct(bal)}</div>
                    </div>
                    <div class="stat">
                        <div class="stat-label">Trade</div>
                        <div class="stat-val">{n}</div>
                    </div>
                    <div class="stat">
                        <div class="stat-label">Kazanma</div>
                        <div class="stat-val">{wr}</div>
                    </div>
                </div>
                {pos_html}
            </div>
        </div>""")
    return "\n".join(cards)


def build_trades_table(trades: list[dict]) -> str:
    if not trades:
        return '<p class="no-data">Henüz kapanan trade yok.</p>'

    recent = trades[-30:][::-1]
    rows = []
    for t in recent:
        pnl = float(t.get("pnl_usdt", 0))
        cc  = "pos" if pnl >= 0 else "neg"
        sign = "+" if pnl >= 0 else ""
        rows.append(f"""
        <tr>
            <td>{t.get('coin','?')}</td>
            <td class="{'long' if t.get('side','').upper()=='BUY' else 'short'}">{t.get('side','?').upper()}</td>
            <td>${float(t.get('entry_price',0)):,.2f}</td>
            <td>${float(t.get('exit_price',0)):,.2f}</td>
            <td class="{cc}">{sign}${pnl:.2f}</td>
            <td>{t.get('exit_reason','?')}</td>
            <td>{t.get('exit_time','?')[:16]}</td>
        </tr>""")

    return f"""
    <table>
        <thead>
            <tr>
                <th>Coin</th><th>Yön</th><th>Giriş</th>
                <th>Çıkış</th><th>PnL</th><th>Sebep</th><th>Zaman</th>
            </tr>
        </thead>
        <tbody>
            {"".join(rows)}
        </tbody>
    </table>"""


def build_compare_table(coins_v1: dict, coins_v2: dict) -> str:
    if not coins_v1 and not coins_v2:
        return ""
    rows = []
    all_coins = sorted(set(list(coins_v1.keys()) + list(coins_v2.keys())))
    for coin in all_coins:
        d1 = coins_v1.get(coin, {})
        d2 = coins_v2.get(coin, {})
        def fmt(d):
            bal = d.get("balance", 10_000)
            n   = d.get("n_trades", 0)
            wr  = d.get("n_wins", 0) / n * 100 if n else 0
            ret = (bal - 10_000) / 10_000 * 100
            cc  = "pos" if bal >= 10_000 else "neg"
            skp = d.get("skipped", 0)
            return f'<span class="{cc}">{ret:+.1f}%</span> ({n}t, {wr:.0f}% WR, {skp} atl.)'
        rows.append(f"<tr><td><b>{coin}</b></td><td>{fmt(d1)}</td><td>{fmt(d2)}</td></tr>")
    return f"""
    <table>
        <thead><tr><th>Coin</th><th>V1 — Saf Teknik</th><th>V2 — Teknik + Makro</th></tr></thead>
        <tbody>{"".join(rows)}</tbody>
    </table>"""


def main() -> None:
    # Prefer the live bot's trades.db (real source of truth on the VPS). Fall
    # back to the old GitHub paper_scanner JSON files if the DB isn't present.
    if DB_PATH.exists():
        coins, trades = load_from_db(DB_PATH)
        coins_v2 = {}
    else:
        state    = load_state()
        state_v2 = load_state(STATE_FILE_V2)
        trades   = load_trades()
        coins    = state.get("coins", {})
        coins_v2 = state_v2.get("coins", {})
    now      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    total_trades = sum(c.get("n_trades", 0) for c in coins.values())
    total_pnl    = sum(c.get("balance", 10_000) - 10_000 for c in coins.values())
    pnl_sign     = "+" if total_pnl >= 0 else ""
    pnl_color    = "pos" if total_pnl >= 0 else "neg"

    coin_cards    = build_coin_cards(coins)
    trades_table  = build_trades_table(trades)
    compare_table = build_compare_table(coins, coins_v2) if coins_v2 else ""

    html = f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="300">
<title>Paper Trading Dashboard</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0d1117; color: #e6edf3; min-height: 100vh;
  }}
  header {{
    background: #161b22; border-bottom: 1px solid #30363d;
    padding: 16px 24px; display: flex; align-items: center; gap: 12px;
  }}
  header h1 {{ font-size: 1.25rem; font-weight: 600; }}
  .subtitle {{ color: #8b949e; font-size: 0.85rem; margin-left: auto; }}
  .container {{ max-width: 1100px; margin: 0 auto; padding: 24px 16px; }}

  /* Summary bar */
  .summary {{
    background: #161b22; border: 1px solid #30363d; border-radius: 8px;
    padding: 16px 24px; margin-bottom: 24px;
    display: flex; gap: 32px; flex-wrap: wrap; align-items: center;
  }}
  .summary .s-item {{ display: flex; flex-direction: column; gap: 2px; }}
  .summary .s-label {{ color: #8b949e; font-size: 0.8rem; }}
  .summary .s-val   {{ font-size: 1.2rem; font-weight: 600; }}

  /* Cards grid */
  .cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px,1fr)); gap: 16px; margin-bottom: 32px; }}
  .card {{
    background: #161b22; border: 1px solid #30363d; border-radius: 8px;
    overflow: hidden;
  }}
  .card-header {{
    display: flex; align-items: center; gap: 10px;
    padding: 12px 16px; border-bottom: 1px solid #21262d;
    background: #1c2128;
  }}
  .coin-icon {{ font-size: 1.3rem; }}
  .coin-name {{ font-weight: 700; font-size: 1.05rem; }}
  .card-body  {{ padding: 14px 16px; }}
  .stat-row   {{ display: flex; gap: 20px; flex-wrap: wrap; }}
  .stat       {{ display: flex; flex-direction: column; gap: 2px; }}
  .stat-label {{ color: #8b949e; font-size: 0.75rem; text-transform: uppercase; letter-spacing: .5px; }}
  .stat-val   {{ font-size: 1.05rem; font-weight: 600; }}

  .open-pos {{
    margin-top: 10px; padding: 8px 10px;
    background: #1c2128; border-radius: 6px;
    display: flex; gap: 12px; flex-wrap: wrap; font-size: 0.85rem;
    border-left: 3px solid #388bfd;
  }}

  /* Badges */
  .badge {{ border-radius: 20px; padding: 2px 10px; font-size: 0.75rem; font-weight: 600; margin-left: auto; }}
  .badge.ok   {{ background: #1a4731; color: #3fb950; }}
  .badge.bad  {{ background: #3d1c1c; color: #f85149; }}
  .badge.wait {{ background: #2d2a1f; color: #d29922; }}

  /* Colors */
  .pos  {{ color: #3fb950; }}
  .neg  {{ color: #f85149; }}
  .long  {{ color: #3fb950; font-weight: 600; }}
  .short {{ color: #f85149; font-weight: 600; }}

  /* Trades table */
  h2 {{ font-size: 1rem; font-weight: 600; margin-bottom: 12px; color: #c9d1d9; }}
  table {{
    width: 100%; border-collapse: collapse;
    background: #161b22; border: 1px solid #30363d; border-radius: 8px;
    overflow: hidden; font-size: 0.88rem;
  }}
  th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #21262d; }}
  th {{ background: #1c2128; color: #8b949e; font-weight: 600; text-transform: uppercase; font-size: 0.75rem; letter-spacing: .5px; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #1c2128; }}
  .no-data {{ color: #8b949e; padding: 24px; text-align: center; }}

  /* Footer */
  footer {{ text-align: center; color: #8b949e; font-size: 0.8rem; padding: 24px; }}
  footer a {{ color: #58a6ff; text-decoration: none; }}

  @media (max-width: 600px) {{
    .summary {{ gap: 16px; }}
    .stat-row {{ gap: 14px; }}
  }}
</style>
</head>
<body>
<header>
  <span style="font-size:1.4rem">📊</span>
  <h1>Paper Trading Dashboard</h1>
  <span class="subtitle">Son güncelleme: {now} &nbsp;·&nbsp; 5 dk'da bir yenilenir</span>
</header>

<div class="container">
  <!-- Özet bar -->
  <div class="summary">
    <div class="s-item">
      <span class="s-label">Toplam Trade</span>
      <span class="s-val">{total_trades}</span>
    </div>
    <div class="s-item">
      <span class="s-label">Toplam PnL</span>
      <span class="s-val {pnl_color}">{pnl_sign}${total_pnl:,.2f}</span>
    </div>
    <div class="s-item">
      <span class="s-label">İzlenen Coin</span>
      <span class="s-val">{len(coins)}</span>
    </div>
    <div class="s-item">
      <span class="s-label">Mod</span>
      <span class="s-val" style="color:#d29922">Paper (Sanal)</span>
    </div>
    <div style="margin-left:auto; color:#8b949e; font-size:0.82rem; max-width:300px">
      Gerçek para yok. Amaç: edge hangi coinde var?
      ✅ = pozitif + kazanma&nbsp;>&nbsp;%45 → canlı aday.
    </div>
  </div>

  <!-- Coin kartları -->
  <div class="cards">
    {coin_cards}
  </div>

  <!-- Trade geçmişi -->
  <!-- V1 vs V2 karşılaştırma -->
  <h2 style="margin-bottom:12px">V1 (Saf Teknik) vs V2 (Teknik + Makro Filtre)</h2>
  <p style="color:#8b949e;font-size:0.85rem;margin-bottom:12px">
    V2'de makro filtre (Fear &amp; Greed + funding rate) sinyali onaylamak için gerekli.
    Hangisi 4-8 haftada daha iyi sonuç verirse o stratejiyle devam.
  </p>
  {compare_table}

  <h2 style="margin-top:32px;margin-bottom:12px">Son 30 Kapanan Trade (V1)</h2>
  {trades_table}
</div>

<footer>
  Strateji: 1H Bollinger Band Mean Reversion · SL=3×ATR · TP=5×ATR · Risk=%3 &nbsp;|&nbsp;
  <a href="https://github.com/demirlk376-byte/Bot2" target="_blank">GitHub</a>
</footer>
</body>
</html>"""

    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"[{now}] dashboard.html oluşturuldu — {len(coins)} coin, {total_trades} trade")


if __name__ == "__main__":
    main()
