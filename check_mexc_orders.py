"""
check_mexc_orders.py — MEXC'teki açık EMİRLERİ, pozisyonları ve CANLI fiyatı
listeler (read-only, hiçbir emir göndermez/iptal etmez).

Amaç:
  • "Open Orders(10)" gerçekte ne? (artık/stale SL-TP plan emirleri mi?)
  • Bot hangi fiyatı görüyor? (veri akışı doğru mu — fiyat anomalisi kontrolü)
  • Açık pozisyonlar ve marginleri

Kullanim:
    cd /opt/bot2 && venv/bin/python check_mexc_orders.py
"""
from __future__ import annotations
import asyncio

from config import load_config
from exchange import LiveExchange


async def main() -> None:
    cfg = load_config()
    if cfg.exchange.paper_mode:
        print("PAPER modda — MEXC sorgusu yok.")
        return

    ex = LiveExchange(
        cfg.exchange.api_key, cfg.exchange.api_secret,
        leverage=cfg.exchange.leverage, margin_mode=cfg.exchange.margin_mode,
    )
    try:
        await ex.initialize(cfg.exchange.symbols[0])
    except Exception as e:
        print(f"initialize uyari: {e}")
    inner = ex._exchange

    print("=" * 70)
    print("  MEXC ACIK EMIRLER + FIYAT + POZISYON (read-only)")
    print("=" * 70)

    print("\n[Bakiye]")
    free = await ex.get_balance()
    try:
        eq = await ex.get_equity()
    except Exception:
        eq = -1.0
    print(f"  Serbest: ${free:,.2f}   Equity: ${eq:,.2f}")

    print("\n[Canli fiyat — bot ne goruyor]")
    for sym in cfg.exchange.symbols:
        try:
            px = await ex.get_current_price(sym)
            print(f"  {sym:16} {px:>12.4f}")
        except Exception as e:
            print(f"  {sym:16} fiyat hatasi: {e}")

    print("\n[Acik pozisyonlar]")
    for sym in cfg.exchange.symbols:
        try:
            pos = await ex.get_position(sym)
        except Exception as e:
            print(f"  {sym:16} hata: {e}")
            continue
        if pos and abs(float(pos.contracts)) > 0:
            print(f"  {sym:16} {pos.side.upper():5} qty={pos.contracts:.4f} "
                  f"entry={pos.entry_price:.4f} uPnL=${pos.unrealized_pnl:+.2f}")
        else:
            print(f"  {sym:16} —")

    print("\n[Standart acik emirler (limit vb.)]")
    total_regular = 0
    for sym in cfg.exchange.symbols:
        try:
            orders = await inner.fetch_open_orders(sym)
        except Exception as e:
            print(f"  {sym:16} fetch_open_orders hata: {e}")
            continue
        for o in orders:
            total_regular += 1
            print(f"  {sym:16} {o.get('side','?'):4} {o.get('type','?'):8} "
                  f"amt={o.get('amount')} px={o.get('price')} id={o.get('id')}")
    if total_regular == 0:
        print("  (standart acik emir yok)")

    print("\n[Plan/Trigger emirleri (SL-TP — MEXC plan orders)]")
    total_plan = 0
    for sym in cfg.exchange.symbols:
        mexc_sym = sym.split(":")[0].replace("/", "_")
        # MEXC plan order listesi: uncompleted plan orders
        for method in ("contractPrivateGetPlanorderListOrders",
                       "contractPrivateGetPlanorderListUncompleted"):
            if hasattr(inner, method):
                try:
                    resp = await getattr(inner, method)({"symbol": mexc_sym})
                    data = resp.get("data") if isinstance(resp, dict) else resp
                    if data:
                        for d in (data if isinstance(data, list) else [data]):
                            total_plan += 1
                            print(f"  {sym:16} {d}")
                    break
                except Exception as e:
                    continue
    if total_plan == 0:
        print("  (plan emir bulunamadi veya endpoint yok — MEXC app'te 'Open Orders'a bak)")

    print("\n" + "=" * 70)
    print(f"  Toplam standart emir: {total_regular}  |  plan emir: {total_plan}")
    print("  NOT: Pozisyon sayisindan fazla emir varsa, kapatilan")
    print("       pozisyonlardan kalan ARTIK SL-TP emirleridir.")
    print("=" * 70)

    try:
        await inner.close()
    except Exception:
        pass


if __name__ == "__main__":
    asyncio.run(main())
