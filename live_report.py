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
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="trades.db")
    ap.add_argument("--paper", action="store_true", help="report paper trades (default: live)")
    ap.add_argument("--days", type=int, default=0, help="only trades closed in the last N days (0=all)")
    args = ap.parse_args()

    is_paper = 1 if args.paper else 0
    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM trades WHERE is_paper=? AND exit_time IS NOT NULL AND exit_time!=''",
        (is_paper,),
    ).fetchall()

    if args.days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
        rows = [r for r in rows if (_parse_time(r["exit_time"]) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]

    mode = "PAPER" if args.paper else "LIVE"
    print("=" * 74)
    print(f"  REALIZED {mode} PERFORMANCE — {args.db}"
          + (f"  (last {args.days}d)" if args.days else "  (all time)"))
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


if __name__ == "__main__":
    main()
