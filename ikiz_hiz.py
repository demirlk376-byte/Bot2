"""replay_hiz.py — REPLAY tam tarihte ne kadar surer? KRONOS'a gerek var mi sorusu
buna baglı. 60 gunluk olculu kosu -> tam tarihe (1200 gun) ekstrapolasyon."""
import asyncio, sys, time, logging, os
logging.basicConfig(level=logging.ERROR)
sys.path.insert(0, "/home/user/Bot2")

async def ana():
    from ikiz.kos import kur, sur
    t0 = time.time()
    M, saat, feed = await kur("2025-04-01", source="local")
    t_kur = time.time() - t0
    print(f"kurulum: {t_kur:.1f}s · {len(M.symbol_ctxs)} coin")

    t1 = time.time()
    n = await sur(M, saat, feed, bitis="2025-06-01", ilerleme_her=0)
    t_sur = time.time() - t1
    hiz = n / t_sur
    print(f"\n{n} mum olayi · {t_sur:.1f}s · {hiz:.0f} olay/sn")

    # tam tarih: 2023-04-06 -> 2026-07-19 = 1200 gun x 12 coin x 24 mum
    tam = 1200 * 12 * 24
    tah = tam / hiz
    print(f"\nTAM TARIH tahmini: {tam:,} olay / {hiz:.0f} = {tah/60:.0f} dk ({tah/3600:.1f} saat)")
    print(f"KRONOS ayni isi ~8 dk'da yapiyor -> REPLAY {tah/60/8:.0f}x yavas")
    print(f"\n270 hucrelik aile testi REPLAY ile: {270*tah/3600:.0f} saat -> "
          f"{'YAPILAMAZ' if 270*tah/3600 > 24 else 'yapilabilir'}")
    b = await M.exchange.get_balance()
    import sqlite3
    DBP=os.environ.get("REPLAY_DB","/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/replay_trades.db")
    c = sqlite3.connect(f"file:{DBP}?mode=ro", uri=True)
    nt = c.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    nk = c.execute("SELECT COUNT(*) FROM trades WHERE exit_time IS NOT NULL").fetchone()[0]
    print(f"\n60 gunde {nt} islem ({nk} kapanmis) · bakiye ${b:,.2f}")
    print(f"  gunde {nt/60:.2f} islem  (CANLI 1.46 · KRONOS 1.42)")

asyncio.run(ana())
