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
from ikiz import db_yolu
DBP = db_yolu()


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
    b, serbest, marj, upnl = await _equity(M)
    print(f"\n  HESAP DEGERI (equity) $10,000 -> ${b:,.2f}")
    print(f"    serbest ${serbest:,.2f} + kilitli marj ${marj:,.2f} "
          f"+ gerceklesmemis ${upnl:+,.2f}")
    # ⚠ dosya adi KOSUYA OZEL olmali. Sabit adla dort paralel kosu ayni
    # dosyanin uzerine yaziyordu; geriye yalnizca en son bitenin listesi
    # kaliyor, digerlerinin islem dokumu kayboluyordu.
    _etiket = os.path.splitext(os.path.basename(DBP))[0]
    csvp = os.path.join(os.getcwd(), f"{_etiket}_islemler.csv")
    d.to_csv(csvp, index=False)
    print(f"  islem listesi -> {csvp}")
    print(f"{'='*92}")

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
