"""
dolum_tani2.py — fetch_close_fill'in eşleştirme döngüsü NEDEN boş dönüyor?

dolum_tani.py üç ihtimali eledi: kod VAR, süreç GÜNCEL (servis 09-09, dosya
08-30), ccxt fetch_my_trades ÇALIŞIYOR (SOL 14, XRP 19 dolum döndü).
Geriye tek yer kalıyor: exchange.py:744-774'teki eşleştirme döngüsü.

İKİ ŞÜPHELİ:
  A) `side` alanı — döngü `f["side"] == "sell"/"buy"` diye süzüyor. MEXC vadeli
     API'si yönü 1/2/3/4 (aç-long / kapat-short / aç-short / kapat-long) diye
     tutuyor. ccxt bunu "buy"/"sell"e çevirmiyorsa süzgeç HER ŞEYİ eliyor.
  B) MİKTAR BİRİMİ — MEXC vadelide dolum miktarı KONTRAT, botun `pos.quantity`'si
     COIN. %90 eşleşme guard'ı elmayla armudu kıyaslıyor olabilir.

Bu betik tahmin etmiyor: ham dolum sözlüğünü ve defterdeki miktarı yan yana basar.

Kullanım (VPS'te):  cd /opt/bot2 && python3 dolum_tani2.py
"""
import asyncio
import json
import os
import sqlite3
import sys
import time

BOT_DIR = os.path.dirname(os.path.abspath(__file__))


def _env():
    try:
        with open(os.path.join(BOT_DIR, ".env"), encoding="utf-8") as fh:
            for raw in fh:
                s = raw.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                if s.startswith("export "):
                    s = s[7:].lstrip()
                k, v = s.split("=", 1)
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                os.environ[k.strip()] = v
    except FileNotFoundError:
        print("✗ .env yok"); sys.exit(2)


async def main():
    _env()
    print(f"\n{'=' * 80}\n=== EŞLEŞTİRME DÖNGÜSÜ TEŞHİSİ ===\n")

    # ── defterden son kapanmış işlemler ──
    print("  [A] DEFTERDEKİ SON KAPANMIŞ İŞLEMLER (miktar birimi kıyası için)")
    db = os.path.join(BOT_DIR, "trades.db")
    kayit = []
    if os.path.exists(db):
        con = sqlite3.connect(db); con.row_factory = sqlite3.Row
        kayit = con.execute(
            "SELECT symbol, side, quantity, entry_price, exit_price, exit_reason, "
            "exit_time FROM trades WHERE exit_price IS NOT NULL AND is_paper=0 "
            "ORDER BY exit_time DESC LIMIT 5").fetchall()
        for r in kayit:
            print(f"      {r['symbol']:<16s} {r['side']:<6s} miktar={r['quantity']:<10.4f} "
                  f"giriş={r['entry_price']:<10.4f} çıkış={r['exit_price']:<10.4f} "
                  f"{r['exit_reason']} @ {r['exit_time'][:16]}")
    else:
        print(f"      ✗ trades.db yok")

    # ── borsadan ham dolum ──
    print(f"\n  [B] BORSADAN HAM DOLUM — döngünün gördüğü ALANLAR")
    import ccxt.async_support as ccxt
    ex = ccxt.mexc({
        "apiKey": os.environ.get("MEXC_API_KEY", ""),
        "secret": os.environ.get("MEXC_API_SECRET", ""),
        "options": {"defaultType": "swap"}, "enableRateLimit": True, "timeout": 30000,
    })
    semboller = list(dict.fromkeys([r["symbol"] for r in kayit])) or ["SOL/USDT:USDT"]
    try:
        for sym in semboller[:3]:
            since = int(time.time() * 1000) - 45 * 24 * 3600 * 1000
            try:
                fills = await ex.fetch_my_trades(sym, since, 50)
            except Exception as e:
                print(f"      {sym} → ✗ {type(e).__name__}: {str(e)[:90]}"); continue
            print(f"\n      ── {sym} · {len(fills)} dolum ──")
            yonler = {}
            for f in fills:
                yonler[str(f.get("side"))] = yonler.get(str(f.get("side")), 0) + 1
            print(f"      side alanının DEĞERLERİ: {yonler}")
            print(f"      → döngü 'buy'/'sell' bekliyor. Liste bunları içermiyorsa")
            print(f"        SÜZGEÇ HER ŞEYİ ELİYOR ve fonksiyon None döner.")
            for f in sorted(fills, key=lambda x: x.get("timestamp") or 0,
                            reverse=True)[:3]:
                info = f.get("info") or {}
                print(f"        {f.get('datetime')} side={f.get('side')!r} "
                      f"price={f.get('price')} amount={f.get('amount')} "
                      f"cost={f.get('cost')}")
                ilg = {k: info[k] for k in ("side", "vol", "positionMode", "category",
                                            "openType", "positionId")
                       if k in info}
                print(f"          info alt küme: {ilg}")
            # miktar birimi kıyası
            eslesen = [r for r in kayit if r["symbol"] == sym]
            if eslesen and fills:
                q = eslesen[0]["quantity"]
                a = [float(f.get("amount") or 0) for f in fills if f.get("amount")]
                if a:
                    print(f"      MİKTAR KIYASI: defter={q:.4f} · borsa dolumları="
                          f"{sorted(set(round(x,4) for x in a))[:6]}")
                    oran = (sum(a) / q) if q else 0
                    print(f"      → dolum/defter oranı ~{oran:.1f}. 1'e yakın değilse")
                    print(f"        BİRİM FARKI var (kontrat vs coin) ve %90 guard'ı")
                    print(f"        elmayla armudu kıyaslıyor demektir.")
    finally:
        await ex.close()
    print(f"\n{'=' * 80}\n")


if __name__ == "__main__":
    asyncio.run(main())
