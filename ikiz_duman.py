"""replay_duman.py — REPLAY kurulumu çalışıyor mu? Kısa pencere (1 ay)."""
import asyncio, sys, os, logging
logging.basicConfig(level=logging.WARNING)
sys.path.insert(0, "/home/user/Bot2")


async def _equity(M):
    """GERCEK hesap degeri = serbest bakiye + kilitli marj + gerceklesmemis PnL.

    get_balance() yalnizca SERBEST nakdi dondurur; acik pozisyonlarin marji
    dusulmus haldedir. Bu yuzden 3 pozisyon acikken ekranda "-%23" gorunuyordu
    ama hesap aslinda +%10 kardaydi (kapanmis 8 islem +$1.028, kilitli marj
    $3.355). Kullaniciyi yaniltmasin diye EQUITY bildiriliyor.
    """
    b = await M.exchange.get_balance()
    try:
        marj = sum(getattr(p, "margin_used", 0.0) for p in M.exchange.get_open_positions())
        upnl = await M.exchange.get_total_unrealized_pnl()
        return b + marj + upnl, b, marj, upnl
    except Exception:
        return b, b, 0.0, 0.0


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
    b1, serbest, marj, upnl = await _equity(M)
    print(f"\n  {n} mum işlendi · HESAP DEĞERİ ${b0:,.2f} → ${b1:,.2f} ({(b1/b0-1)*100:+.2f}%)")
    print(f"    serbest ${serbest:,.2f} + kilitli marj ${marj:,.2f} + gerçekleşmemiş ${upnl:+,.2f}")
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

# ⚠ SÜREÇ KENDİLİĞİNDEN ÇIKMIYOR — bu satır olmadan burada SONSUZA KADAR asılı
# kalır. aiosqlite veritabanı bağlantısını bir ARKA PLAN THREAD'inde koşturuyor
# ve o thread daemon DEĞİL; close() çağrılmadıkça yaşamaya devam ediyor. Python
# çıkarken threading._shutdown içinde onun bitmesini bekler ve asla bitmez.
# (py-spy, 2026-09-19: dört paralel süreç de tam orada, 4 saat, sıfır CPU.)
# Tek koşuda çıktı doğrudan ekrana bastığı için kusur GÖRÜNMÜYORDU; paralel
# koşuda çıktı süreç bitene kadar tutulduğundan koşu HİÇ sonuç vermiyordu.
# İşlemler sur() sonunda zaten WAL'den ana dosyaya aktarıldı, yazılacak bir şey
# kalmadı — o yüzden sert çıkış güvenli.
sys.stdout.flush(); sys.stderr.flush()
os._exit(0)
