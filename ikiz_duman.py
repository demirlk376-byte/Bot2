"""replay_duman.py — REPLAY kurulumu çalışıyor mu? Kısa pencere (1 ay)."""
import asyncio, sys, logging
logging.basicConfig(level=logging.WARNING)
sys.path.insert(0, "/home/user/Bot2")

async def ana():
    from ikiz.kos import kur, sur
    print("=== 1) main() kurulumu ===")
    M, saat, feed = await kur("2025-06-01", source="local")
    print(f"  ✓ kuruldu · coin sayısı {len(M.symbol_ctxs)} · borsa {type(M.exchange).__name__}")
    print(f"  config: MAX_POSITIONS={M.config.risk.max_positions} "
          f"risk={M.config.risk.max_risk_per_trade:.4f} "
          f"cap={getattr(M.config.risk,'position_cap_fraction','?')}")
    for s, c in list(M.symbol_ctxs.items())[:3]:
        print(f"    {s}: kollar {M.active_sleeves_for(c, M.config)}")
    b0 = await M.exchange.get_balance()
    print(f"  başlangıç bakiye ${b0:,.2f}")

    print("\n=== 2) mumları sür (2025-06-01 → 2025-07-01) ===")
    n = await sur(M, saat, feed, bitis="2025-07-01", ilerleme_her=2000)
    # ⚠ get_balance() SERBEST bakiye — acik pozisyonlarin marji dusulmus halde.
    # Gercek olcut EQUITY: serbest + kilitli marj + gerceklesmemis PnL.
    b1 = await M.exchange.get_balance()
    try:
        b1 = b1 + sum(getattr(p_, "margin_used", 0.0) for p_ in M.exchange.get_open_positions())              + await M.exchange.get_total_unrealized_pnl()
    except Exception:
        pass
    acik = M.portfolio.get_open_positions()
    print(f"\n  {n} mum işlendi · bakiye ${b0:,.2f} → ${b1:,.2f} ({(b1/b0-1)*100:+.2f}%)")
    print(f"  açık pozisyon {len(acik)}")
    import sqlite3, os
    from ikiz import db_yolu; DBP = db_yolu()
    if os.path.exists(DBP):
        c = sqlite3.connect(f"file:{DBP}?mode=ro", uri=True)
        n_t = c.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        n_k = c.execute("SELECT COUNT(*) FROM trades WHERE exit_time IS NOT NULL").fetchone()[0]
        print(f"  DB: {n_t} işlem ({n_k} kapanmış)")
        for r in c.execute("SELECT symbol,side,entry_price,exit_price,pnl_usdt,exit_reason FROM trades LIMIT 5"):
            print(f"    {r}")

asyncio.run(ana())
