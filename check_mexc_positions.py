"""
check_mexc_positions.py — MEXC'teki GERCEK durumu okur (read-only).

Hicbir emir gondermez. Sadece:
  • Her coin icin MEXC'te acik pozisyon var mi (yon, miktar, giris, uPnL)
  • Serbest bakiye (free)  ve  toplam equity (free + kilitli margin)

DB'ye veya botun portfolyosuna bakmaz — dogrudan borsaya sorar.
Yetim (orphaned) pozisyonlari tespit etmenin tek guvenilir yolu budur.

Kullanim:
    cd /opt/bot2 && venv/bin/python check_mexc_positions.py
"""
from __future__ import annotations
import asyncio

from config import load_config
from exchange import LiveExchange


async def main() -> None:
    cfg = load_config()
    if cfg.exchange.paper_mode:
        print("PAPER modda — MEXC sorgusu yok. .env LIVE olmali.")
        return

    ex = LiveExchange(
        cfg.exchange.api_key,
        cfg.exchange.api_secret,
        leverage=cfg.exchange.leverage,
        margin_mode=cfg.exchange.margin_mode,
    )
    # ccxt istemcisini ayaga kaldir (load_markets). initialize() bir symbol ister;
    # ilk coin ile cagiriyoruz — set_leverage idempotent (zaten 10x), zarar vermez.
    try:
        await ex.initialize(cfg.exchange.symbols[0])
    except Exception as e:
        print(f"initialize uyari: {e}")

    print("=" * 64)
    print("  MEXC GERCEK DURUM (read-only)")
    print("=" * 64)

    print("\n[Bakiye]")
    free = await ex.get_balance()
    try:
        eq = await ex.get_equity()
    except Exception as e:
        eq = -1.0
        print(f"  get_equity hatasi: {e}")
    print(f"  Serbest (free)        : ${free:,.2f}")
    print(f"  Toplam equity         : ${eq:,.2f}")
    print(f"  Kilitli margin (fark) : ${max(eq - free, 0):,.2f}")

    print("\n[Acik pozisyonlar — MEXC'e gore]")
    any_open = False
    for sym in cfg.exchange.symbols:
        try:
            pos = await ex.get_position(sym)
        except Exception as e:
            print(f"  {sym:16} sorgu hatasi: {e}")
            continue
        qty = float(pos.contracts) if pos else 0.0
        if pos is not None and abs(qty) > 0:
            any_open = True
            side = getattr(pos, "side", "?")
            entry = getattr(pos, "entry_price", 0.0)
            upnl = getattr(pos, "unrealized_pnl", None)
            upnl_s = f" uPnL=${float(upnl):+.2f}" if upnl is not None else ""
            print(f"  {sym:16} {str(side).upper():5} qty={qty:.4f} "
                  f"entry={entry:.4f}{upnl_s}  <-- ACIK")
        else:
            print(f"  {sym:16} —  (pozisyon yok)")

    print("\n" + "=" * 64)
    if any_open:
        print("  MEXC'te ACIK pozisyon(lar) var. Bot DB'sinde KAPALI gorunuyorlar")
        print("  (yetim). Bunlari MEXC'ten manuel kapatmak en guvenli yol.")
    else:
        print("  MEXC'te ACIK pozisyon YOK. Kilitli margin yok demektir —")
        print("  serbest bakiye = toplam equity olmali. Bot temiz, trade bekliyor.")
    print("=" * 64)

    inner = getattr(ex, "_exchange", None)
    if inner is not None and hasattr(inner, "close"):
        try:
            await inner.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
