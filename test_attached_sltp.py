"""
test_attached_sltp.py — TEK kontrollü canlı test: SL/TP'yi giriş emrine
İLİŞTİREREK MEXC'in kabul edip etmediğini doğrular.

MEXC'in ayrı plan-order endpoint'i (PlanorderPlace) bakımda/boş dönüyor.
Bu test, SL/TP'yi giriş emrinin parametresi olarak (stopLossPrice/takeProfitPrice)
geçip ÇALIŞAN OrderCreate endpoint'ine bırakır ve sonucu okur.

Akış (kendini temizler):
  1. XRP'de minimum boyutta market LONG aç (SL/TP iliştirilmiş)
  2. 3 sn bekle, pozisyonu + trigger/plan emirlerini OKU → SL/TP tuttu mu?
  3. Pozisyonu kapat + kalan plan emirlerini iptal et

UYARI: GERÇEK emir gönderir (çok küçük, ~birkaç sent risk). Onaylı çalıştır.

Kullanim:
    cd /opt/bot2 && venv/bin/python test_attached_sltp.py
"""
from __future__ import annotations
import asyncio

from config import load_config
from exchange import LiveExchange

TEST_SYMBOL = "XRP/USDT:USDT"   # en ucuz notional


async def main() -> None:
    cfg = load_config()
    if cfg.exchange.paper_mode:
        print("PAPER modda — test anlamsiz. .env LIVE olmali.")
        return

    ex = LiveExchange(
        cfg.exchange.api_key, cfg.exchange.api_secret,
        leverage=cfg.exchange.leverage, margin_mode=cfg.exchange.margin_mode,
    )
    await ex.initialize(TEST_SYMBOL)
    inner = ex._exchange
    mexc_sym = TEST_SYMBOL.split(":")[0].replace("/", "_")

    print("=" * 66)
    print("  SL/TP GIRIS-EMRINE-ILISTIRME CANLI TESTI")
    print("=" * 66)

    market = inner.market(TEST_SYMBOL)
    min_amt = (market.get("limits", {}).get("amount", {}).get("min")
               or market.get("contractSize") or 1.0)
    price = await ex.get_current_price(TEST_SYMBOL)
    # minimumun biraz üstü, base-currency
    amount = float(min_amt) * 2
    sl = round(price * 0.97, 4)   # %3 alt
    tp = round(price * 1.06, 4)   # %6 üst
    print(f"\n  {TEST_SYMBOL}  fiyat={price:.4f}  test_qty={amount}  SL={sl}  TP={tp}")

    opened = False
    try:
        print("\n[1] Giris emri (SL/TP ILISTIRILMIS) gonderiliyor…")
        order = await ex.place_market_order(
            TEST_SYMBOL, "buy", amount,
            {"stopLossPrice": sl, "takeProfitPrice": tp},
        )
        opened = True
        print(f"    OK — giris doldu @ {order.filled_price:.4f} (id={order.order_id})")

        await asyncio.sleep(3)

        print("\n[2] Pozisyon ve trigger/plan emirleri okunuyor…")
        pos = await ex.get_position(TEST_SYMBOL)
        if pos:
            print(f"    Pozisyon: {pos.side} qty={pos.contracts} entry={pos.entry_price}")
            # MEXC pozisyon info'sunda SL/TP alanlari
            raw = None
            try:
                poss = await inner.fetch_positions([TEST_SYMBOL])
                raw = poss[0].get("info") if poss else None
            except Exception as e:
                print(f"    fetch_positions hata: {e}")
            if raw:
                for k in ("stopLossPrice", "takeProfitPrice", "slPrice", "tpPrice"):
                    if k in raw and raw[k] not in (None, "", 0, "0"):
                        print(f"    >>> pozisyona ILISTIRILMIS {k} = {raw[k]}")

        # Plan/trigger emir listesi
        found_plan = False
        for method in ("contractPrivateGetPlanorderListOrders",
                       "contractPrivateGetPlanorderListUncompleted",
                       "contractPrivateGetStoporderListOrders"):
            if hasattr(inner, method):
                try:
                    resp = await getattr(inner, method)({"symbol": mexc_sym})
                    data = resp.get("data") if isinstance(resp, dict) else resp
                    if data:
                        found_plan = True
                        print(f"    >>> {method}: {len(data) if isinstance(data,list) else 1} emir bulundu")
                        for d in (data if isinstance(data, list) else [data]):
                            print(f"        {d}")
                except Exception:
                    continue

        print("\n[3] SONUC:")
        # Karar: trigger emir bulundu YA DA pozisyonda SL/TP alani dolu
        if found_plan:
            print("    ✅ SL/TP giris emriyle BASARIYLA olusturuldu.")
            print("       → execution.py bu yontemi kullanacak sekilde duzeltilebilir.")
        else:
            print("    ❌ SL/TP olusmadi gibi — MEXC bu hesapta iliştirmeyi kabul etmiyor.")
            print("       → Farkli yontem (yazilim-tarafi stop) gerekebilir.")

    finally:
        if opened:
            print("\n[temizlik] Pozisyon kapatiliyor + plan emirleri iptal…")
            try:
                await ex.close_position(TEST_SYMBOL, "long", amount, "test_cleanup")
                print("    pozisyon kapatildi.")
            except Exception as e:
                print(f"    KAPATMA HATASI — MEXC'ten MANUEL kapat!: {e}")
            try:
                await ex.cancel_stop_orders(TEST_SYMBOL)
                print("    plan emirleri iptal edildi.")
            except Exception as e:
                print(f"    plan iptal hata: {e}")
        try:
            await inner.close()
        except Exception:
            pass

    print("=" * 66)


if __name__ == "__main__":
    asyncio.run(main())
