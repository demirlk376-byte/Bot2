"""
live_report.py — realized live-performance & slippage report from trades.db.

Read-only evidence tool for the data-collection period: it never touches the
exchange or the running bot, just summarizes what ACTUALLY happened so the
"grow / widen / adjust risk" decisions later rest on live numbers, not backtests.

Per-sleeve it reports realized PF / win-rate / net PnL / avg-hold / exit-reason
mix, and — once trades carry strategy_scores.intended_entry — the realized entry
SLIPPAGE (actual fill vs the signal's intended level), which is the key number
for validating the live-vs-backtest discount (ORB/Donchian fill ~level; FVG/IFVG
at the zone edge). Also weekly/monthly PnL and max drawdown on closed trades.

Usage (on the VPS, in the bot dir):
    venv/bin/python live_report.py                 # live (real-money) trades
    venv/bin/python live_report.py --paper         # paper trades
    venv/bin/python live_report.py --db trades.db --days 30
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone, timedelta


def _parse_time(s: str):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None
    # Normalize to UTC-aware so naive inputs (e.g. a "2026-06-28" epoch) compare
    # cleanly against the tz-aware entry/exit timestamps.
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _sleeve(scores_json: str) -> str:
    try:
        return (json.loads(scores_json or "{}") or {}).get("strategy", "?") or "?"
    except Exception:
        return "?"


def _intended(scores_json: str) -> float:
    try:
        return float((json.loads(scores_json or "{}") or {}).get("intended_entry", 0.0) or 0.0)
    except Exception:
        return 0.0


def _pf(pnls):
    gp = sum(p for p in pnls if p > 0)
    gl = -sum(p for p in pnls if p < 0)
    return (gp / gl) if gl > 0 else (float("inf") if gp > 0 else 0.0)


def _fmt_pf(pf):
    return "inf" if pf == float("inf") else f"{pf:.2f}"


def _compact_summary(rows, mode, days) -> str:
    """Phone-friendly one-glance summary for push notifications."""
    if not rows:
        return f"📊 {mode} {'%dg' % days if days else 'tüm'}: kapanan işlem yok (henüz)."
    p = [r["pnl_usdt"] or 0.0 for r in rows]
    w = sum(1 for v in p if v > 0)
    head = (f"📊 {mode} {'%dg' % days if days else 'tüm'} | {len(rows)}t "
            f"WR{w/len(rows):.0%} PF{_fmt_pf(_pf(p))} {sum(p):+.2f}U")
    bys = defaultdict(list)
    for r in rows:
        bys[_sleeve(r["strategy_scores"])].append(r["pnl_usdt"] or 0.0)
    legs = " | ".join(
        f"{s} {len(v)}t {sum(v):+.1f}"
        for s, v in sorted(bys.items(), key=lambda kv: -sum(kv[1]))
    )
    return head + "\n" + legs


def _send_ntfy(cfg, text: str) -> bool:
    import requests
    if not getattr(cfg.ntfy, "enabled", False) or not cfg.ntfy.topic:
        return False
    url = f"{cfg.ntfy.server.rstrip('/')}/{cfg.ntfy.topic}"
    try:
        r = requests.post(url, data=text.encode("utf-8"),
                          headers={"Title": "Haftalik Rapor", "Priority": "default"},
                          timeout=15)
        return r.status_code < 300
    except Exception as e:
        print(f"  ntfy send failed: {e}")
        return False


def _send_telegram(cfg, text: str) -> bool:
    import requests
    if not getattr(cfg.telegram, "enabled", False) or not cfg.telegram.token:
        return False
    url = f"https://api.telegram.org/bot{cfg.telegram.token}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": cfg.telegram.chat_id, "text": text},
                          timeout=15)
        return r.status_code < 300
    except Exception as e:
        print(f"  telegram send failed: {e}")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="trades.db")
    ap.add_argument("--paper", action="store_true", help="report paper trades (default: live)")
    ap.add_argument("--days", type=int, default=0, help="only trades closed in the last N days (0=all)")
    ap.add_argument("--since", default="",
                    help="only trades OPENED on/after this UTC date/time (e.g. 2026-06-28). "
                         "Overrides the stored epoch for this run.")
    ap.add_argument("--set-epoch", default="",
                    help="persist a clean-start epoch ('now' or an ISO date) so all future "
                         "reports ignore dev-era trades opened before it, then exit.")
    ap.add_argument("--notify", action="store_true",
                    help="push a compact summary to ntfy/Telegram (uses the bot's .env config)")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")

    # --set-epoch: record the clean-start cutoff and exit. Everything before it
    # (the unstable development period) is then excluded from every report.
    if args.set_epoch:
        when = (datetime.now(timezone.utc).isoformat() if args.set_epoch.lower() == "now"
                else args.set_epoch)
        con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('report_epoch', ?)", (when,))
        con.commit()
        print(f"✓ report epoch set to {when}\n  Future reports count only trades opened on/after this.")
        return

    is_paper = 1 if args.paper else 0
    rows = con.execute(
        "SELECT * FROM trades WHERE is_paper=? AND exit_time IS NOT NULL AND exit_time!=''",
        (is_paper,),
    ).fetchall()

    # Clean-start cutoff: explicit --since wins, else the persisted epoch. Filters
    # by ENTRY time (when the CURRENT code opened the trade), so a dev-era trade
    # that closed after the epoch is still excluded.
    epoch_row = con.execute("SELECT value FROM meta WHERE key='report_epoch'").fetchone()
    cutoff_src = args.since or (epoch_row["value"] if epoch_row else "")
    epoch_cut = _parse_time(cutoff_src) if cutoff_src else None
    if epoch_cut is not None:
        rows = [r for r in rows
                if (_parse_time(r["entry_time"]) or datetime.min.replace(tzinfo=timezone.utc)) >= epoch_cut]

    if args.days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
        rows = [r for r in rows if (_parse_time(r["exit_time"]) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]

    mode = "PAPER" if args.paper else "LIVE"
    win = (f"  (last {args.days}d)" if args.days else "  (all time)")
    if epoch_cut is not None:
        win += f"  since {cutoff_src[:16]}"
    print("=" * 74)
    print(f"  REALIZED {mode} PERFORMANCE — {args.db}{win}")
    if epoch_cut is not None:
        print(f"  (clean epoch active — dev-era trades before {cutoff_src[:16]} excluded)")
    print("=" * 74)
    if not rows:
        print("  No closed trades yet. (Bot may still be warming up / no exits.)")
        # Show any OPEN positions so it isn't mistaken for 'nothing happening'.
        opn = con.execute(
            "SELECT symbol, side, entry_price, json_extract(strategy_scores,'$.strategy') s, entry_time "
            "FROM trades WHERE is_paper=? AND (exit_time IS NULL OR exit_time='')", (is_paper,)).fetchall()
        if opn:
            print(f"\n  {len(opn)} OPEN position(s):")
            for o in opn:
                print(f"    {o['symbol']:16s} {o['side']:5s} {str(o['s']):9s} @ {o['entry_price']:.4f}  ({o['entry_time']})")
        if args.notify:
            _do_notify(rows, mode, args.days)
        return

    pnls_all = [r["pnl_usdt"] or 0.0 for r in rows]
    wins = sum(1 for p in pnls_all if p > 0)
    n = len(rows)
    print(f"  closed trades : {n}")
    print(f"  win rate      : {wins/n:.0%}  ({wins}W / {n-wins}L)")
    print(f"  profit factor : {_fmt_pf(_pf(pnls_all))}")
    print(f"  net PnL       : {sum(pnls_all):+.2f} USDT")
    print(f"  fees paid     : {sum((r['fees_usdt'] or 0.0) for r in rows):.2f} USDT")

    # equity curve + max drawdown on realized PnL (chronological by exit time)
    ordered = sorted(rows, key=lambda r: _parse_time(r["exit_time"]) or datetime.min.replace(tzinfo=timezone.utc))
    eq = 0.0; peak = 0.0; mdd = 0.0
    for r in ordered:
        eq += r["pnl_usdt"] or 0.0
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    print(f"  max drawdown  : {mdd:.2f} USDT (realized, peak-to-trough of cum PnL)")

    # ── per-sleeve ────────────────────────────────────────────────────────────
    bys = defaultdict(list)
    for r in rows:
        bys[_sleeve(r["strategy_scores"])].append(r)
    print("\n  SLEEVE      n    WR    PF      netPnL    avgHold  slippage(bps)  exits")
    print("  " + "-" * 70)
    for s in sorted(bys, key=lambda k: -sum((x["pnl_usdt"] or 0.0) for x in bys[k])):
        rs = bys[s]
        p = [x["pnl_usdt"] or 0.0 for x in rs]
        w = sum(1 for v in p if v > 0)
        # avg hold (hours)
        holds = []
        for x in rs:
            t0, t1 = _parse_time(x["entry_time"]), _parse_time(x["exit_time"])
            if t0 and t1:
                holds.append((t1 - t0).total_seconds() / 3600)
        avg_hold = (sum(holds) / len(holds)) if holds else 0.0
        # realized entry slippage in bps: signed adverse (positive = paid worse)
        slips = []
        for x in rs:
            intended = _intended(x["strategy_scores"])
            if intended > 0 and x["entry_price"]:
                d = 1 if x["side"] == "long" else -1
                slips.append(d * (x["entry_price"] - intended) / intended * 1e4)
        slip = (sum(slips) / len(slips)) if slips else None
        slip_s = f"{slip:+.1f}" if slip is not None else "n/a"
        exits = defaultdict(int)
        for x in rs:
            exits[x["exit_reason"] or "?"] += 1
        exits_s = " ".join(f"{k}:{v}" for k, v in sorted(exits.items()))
        print(f"  {s:9s} {len(rs):>3d}  {w/len(rs):>3.0%}  {_fmt_pf(_pf(p)):>5s}  "
              f"{sum(p):>+9.2f}  {avg_hold:>6.1f}h  {slip_s:>12s}  {exits_s}")

    # ── per-coin ──────────────────────────────────────────────────────────────
    # Budamanın ikinci ekseni: sleeve iyi olsa da belirli bir coin sürüklüyor
    # olabilir (paper scanner'da XRP ❌ örneği). Coin satırının altında o coinin
    # sleeve kırılımı — "SOL kaybediyor" değil "SOL'da squeeze kaybediyor" denir.
    byc = defaultdict(list)
    for r in rows:
        byc[(r["symbol"] or "?").split("/")[0]].append(r)
    print("\n  COIN        n    WR    PF      netPnL   sleeves")
    print("  " + "-" * 70)
    for c in sorted(byc, key=lambda k: -sum((x["pnl_usdt"] or 0.0) for x in byc[k])):
        rs = byc[c]
        p = [x["pnl_usdt"] or 0.0 for x in rs]
        w = sum(1 for v in p if v > 0)
        bysl = defaultdict(float)
        for x in rs:
            bysl[_sleeve(x["strategy_scores"])] += x["pnl_usdt"] or 0.0
        sl_s = " ".join(f"{k}:{v:+.2f}" for k, v in
                        sorted(bysl.items(), key=lambda kv: -kv[1]))
        print(f"  {c:9s} {len(rs):>3d}  {w/len(rs):>3.0%}  {_fmt_pf(_pf(p)):>5s}  "
              f"{sum(p):>+9.2f}   {sl_s}")

    # ── signal capture (sansür ölçümü) ───────────────────────────────────────
    # Bir sleeve'in canlı WR/PF'i ancak sinyallerinin çoğunu ALABİLDİYSE onun
    # ölçümüdür; one-per-symbol/slot blokları örneklemi sansürler. Bu tablo
    # sleeve başına "üretilen vs alınan" oranını ve blok sebeplerini gösterir.
    import csv as _csv
    from pathlib import Path as _Path
    sig_f = _Path("signals_log.csv")
    if sig_f.exists():
        caps = defaultdict(lambda: {"n": 0, "ok": 0, "reasons": defaultdict(int)})
        with open(sig_f) as fh:
            for srow in _csv.DictReader(fh):
                st = _parse_time(srow.get("ts", ""))
                if epoch_cut is not None and (st is None or st < epoch_cut):
                    continue
                c = caps[srow.get("strategy", "?")]
                c["n"] += 1
                if srow.get("executed") == "1":
                    c["ok"] += 1
                else:
                    c["reasons"][(srow.get("reason") or "?")[:36]] += 1
        if caps:
            print("\n  SİNYAL YAKALAMA (sleeve: alınan/üretilen — blok sebepleri)")
            print("  " + "-" * 70)
            for st in sorted(caps, key=lambda k: -caps[k]["n"]):
                c = caps[st]
                rate = c["ok"] / c["n"] if c["n"] else 0.0
                top = sorted(c["reasons"].items(), key=lambda kv: -kv[1])[:2]
                top_s = "  ".join(f"[{k}]x{v}" for k, v in top)
                print(f"  {st:9s} {c['ok']:>3d}/{c['n']:<3d} ({rate:4.0%})  {top_s}")

    # ── weekly PnL ────────────────────────────────────────────────────────────
    byw = defaultdict(list)
    for r in rows:
        t = _parse_time(r["exit_time"])
        if t:
            byw[t.strftime("%Y-W%W")].append(r["pnl_usdt"] or 0.0)
    print("\n  WEEK        n    netPnL")
    print("  " + "-" * 30)
    cum = 0.0
    for wk in sorted(byw):
        wl = byw[wk]; cum += sum(wl)
        print(f"  {wk:9s} {len(wl):>3d}  {sum(wl):>+9.2f}   (cum {cum:>+9.2f})")

    if not args.paper:
        print("\n  NOTE: slippage is 'n/a' for trades opened before intended_entry logging")
        print("        was added — it populates going forward. Re-run after more trades.")

    if args.notify:
        _do_notify(rows, mode, args.days)


def _do_notify(rows, mode, days):
    """Build the compact summary and push it to whatever channels are enabled."""
    try:
        from config import load_config
        cfg = load_config()
    except Exception as e:
        print(f"  notify: could not load config ({e}) — skipping push")
        return
    text = _compact_summary(rows, mode, days)
    sent = []
    if _send_ntfy(cfg, text):
        sent.append("ntfy")
    if _send_telegram(cfg, text):
        sent.append("telegram")
    print(f"\n  notify: sent to {', '.join(sent) if sent else 'nothing (no channel enabled/reachable)'}")


if __name__ == "__main__":
    main()
