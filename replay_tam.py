"""
replay_tam.py — REPLAY'i TAM TARIHTE kosar ve KRONOS ile yan yana koyar.

Bu, iki motorun UZLASIP UZLASMADIGI testidir:
  uzlasirlarsa -> KRONOS hizli on-eleme olarak kullanilabilir (8dk vs 91dk)
  uzlasmazlarsa -> fark KRONOS'un bir sonraki eksigini gosterir; REPLAY kazanir

Isinma: veri basindan baslanir (2023-04-06). Ilk ~43 gun donchian'in 260 adet
4h bari birikene kadar sinyal uretmez — canli bot ilk kurulusunda da oyleydi.
"""
import asyncio, sys, time, json, logging, os
logging.basicConfig(level=logging.ERROR)
sys.path.insert(0, "/home/user/Bot2")
DBP = os.environ.get("REPLAY_DB", "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/replay_trades.db")

async def ana():
    from replay.kos import kur, sur
    t0 = time.time()
    M, saat, feed = await kur("2023-04-06", source="local")
    print(f"kurulum {time.time()-t0:.0f}s · {len(M.symbol_ctxs)} coin", flush=True)
    n = await sur(M, saat, feed, bitis="2026-07-19", ilerleme_her=20000)
    print(f"\n{n} mum · toplam {(time.time()-t0)/60:.0f} dk", flush=True)

    import sqlite3, pandas as pd, numpy as np
    c = sqlite3.connect(f"file:{DBP}?mode=ro", uri=True)
    d = pd.read_sql("SELECT symbol,side,entry_price,exit_price,sl_price,quantity,"
                    "entry_time,exit_time,pnl_usdt,exit_reason,strategy_scores "
                    "FROM trades WHERE exit_time IS NOT NULL", c)
    print(f"\n{'='*92}\n=== REPLAY TAM TARIH ===")
    print(f"  kapanmis islem: {len(d)}")
    if not len(d): return
    d["giris"] = pd.to_datetime(d.entry_time, utc=True, format="mixed")
    d["cikis"] = pd.to_datetime(d.exit_time,  utc=True, format="mixed")
    gun = (d.cikis.max() - d.giris.min()).days
    dd = 1 - 2*(d.side.str.lower().str.startswith("s")).astype(int)
    stop = (d.entry_price - d.sl_price).abs()
    d["R"] = np.where(stop > 0, dd*(d.exit_price - d.entry_price)/stop.replace(0, np.nan), np.nan)
    import json as J
    d["kol"] = d.strategy_scores.apply(lambda s: (J.loads(s or "{}") or {}).get("strategy","?"))
    print(f"  {gun} gun -> gunde {len(d)/gun:.2f} islem   (CANLI 1.46 · KRONOS 1.42)")
    print(f"  ort R {d.R.mean():+.4f} (sigma {d.R.std():.3f})   (KRONOS taban +0.1451)")
    print(f"  kazanma %{(d.R>0).mean()*100:.1f}   toplam PnL ${d.pnl_usdt.sum():+,.2f}")
    print(f"\n  kol dagilimi:")
    for k,g in d.groupby("kol"):
        print(f"    {k:<12s} n={len(g):>5d}  ortR {g.R.mean():+.4f}  PnL ${g.pnl_usdt.sum():+9,.2f}")
    print(f"\n  cikis nedeni: {d.exit_reason.value_counts().to_dict()}")
    b = await M.exchange.get_balance()
    print(f"\n  bakiye $10,000 -> ${b:,.2f}")
    d.to_csv("/home/user/Bot2/replay_tam_islemler.csv", index=False)
    print(f"  islem listesi -> replay_tam_islemler.csv")
    print(f"{'='*92}")

asyncio.run(ana())
