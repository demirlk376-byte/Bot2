"""
check_mexc_stopmove.py — MEXC stop-taşıma (plan-order place + targeted cancel)
endpoint'i SAĞLIKLI mı? BE/trailing'i canlıda açmadan önce koşulacak probe.

Neden: Canlıda SL taşımak = yeni plan emri yerleştir + eskisini iptal et.
MEXC'in planorder/place endpoint'i geçmişte sessizce reddetti (200 dönüp emir
koymuyordu). Bot bu yüzden canlı stop taşımayı STOP_MOVE_ENABLED=false ile
kapalı tutar. Bu script endpoint'in BUGÜN çalışıp çalışmadığını kanıtlar.

Güvenlik: Aktif probe yalnızca AÇIK POZİSYON + YERLEŞİK SL varken çalışır ve
mevcut SL'den kesinlikle DAHA UZAK (long'da daha aşağı, short'ta daha yukarı)
reduce-only bir tetik emri koyar → gerçek SL her zaman önce tetiklenir, probe
emri hiçbir koşulda pozisyonu etkileyemez. Test bitince emir hedefli iptal
edilir; iptal başarısız olsa bile emir reduce-only'dir ve 24 saatte kendisi
düşer (executeCycle=1).

Kullanım (VPS):
    cd /opt/bot2 && venv/bin/python check_mexc_stopmove.py          # read-only
    cd /opt/bot2 && venv/bin/python check_mexc_stopmove.py --probe  # aktif test

Sonuç "PROBE BAŞARILI" ise: .env'e STOP_MOVE_ENABLED=true ekle ve botu
yeniden başlat → ORB+IFVG BE@1R + sr_breakout trailing canlıda aktifleşir.
"""
from __future__ import annotations

import asyncio
import sys

from config import load_config
from exchange import LiveExchange


def _mexc_sym(symbol: str) -> str:
    return symbol.split(":")[0].replace("/", "_")


async def list_plan_orders(ex: LiveExchange, symbol: str) -> list[dict]:
    resp = await ex._exchange.contractPrivateGetPlanorderListOrders(
        {"symbol": _mexc_sym(symbol), "states": "1"})
    data = resp.get("data") if isinstance(resp, dict) else resp
    return list(data or [])


async def probe_symbol(ex: LiveExchange, symbol: str, do_probe: bool) -> bool | None:
    """None = bu sembolde probe koşulamadı (pozisyon/SL yok); True/False = sonuç."""
    pos = await ex.get_position(symbol)
    if pos is None:
        print(f"  {symbol}: pozisyon yok — probe atlanıyor")
        return None

    orders = await list_plan_orders(ex, symbol)
    sl_trigger = 2 if pos.side == "long" else 1
    resting_sl = [o for o in orders if int(o.get("triggerType", 0)) == sl_trigger]
    print(f"  {symbol}: {pos.side} {pos.contracts} @ {pos.entry_price:.4f} | "
          f"{len(orders)} plan emri ({len(resting_sl)} SL yönlü)")
    if not resting_sl:
        print("    yerleşik SL plan emri yok — probe güvenli değil, atlanıyor")
        return None
    if not do_probe:
        print("    (aktif test için --probe ile çalıştır)")
        return None

    # Mevcut SL'den %1 DAHA UZAK bir probe tetiği: gerçek SL her zaman önce vurur.
    cur_sl = min((float(o.get("triggerPrice") or 0) for o in resting_sl),
                 default=0.0) if pos.side == "long" else \
             max((float(o.get("triggerPrice") or 0) for o in resting_sl), default=0.0)
    if cur_sl <= 0:
        print("    SL tetik fiyatı okunamadı — atlanıyor")
        return None
    probe_price = cur_sl * (0.99 if pos.side == "long" else 1.01)
    probe_price = float(ex._exchange.price_to_precision(symbol, probe_price))

    print(f"    PROBE: {probe_price} tetikli reduce-only plan emri yerleştiriliyor "
          f"(mevcut SL {cur_sl} — probe kesinlikle daha uzak)")

    # place → listede doğrula → hedefli cancel → doğrula
    inner = ex._exchange
    close_side = "sell" if pos.side == "long" else "buy"
    open_type = 1 if ex._margin_mode == "isolated" else 2
    params = {"orderType": 5, "executeCycle": 1, "openType": open_type,
              "reduceOnly": True, "triggerPrice": probe_price,
              "triggerType": sl_trigger}
    if open_type == 1:
        params["leverage"] = ex._leverage
    contracts = ex._to_contracts(symbol, pos.contracts, round_up=False)

    try:
        resp = await inner.create_order(symbol, "market", close_side,
                                        contracts, None, params)
    except Exception as e:
        print(f"    ✗ PLACE başarısız (exception): {e}")
        return False
    new_id = None
    if resp:
        new_id = resp.get("id") or (resp.get("info") or {}).get("orderId")
    if not new_id:
        print(f"    ✗ PLACE sessiz reject (200 ama id yok): {resp}")
        return False
    print(f"    ✓ PLACE ok — emir id {new_id}")

    await asyncio.sleep(1.5)
    after = await list_plan_orders(ex, symbol)
    listed = any(str(o.get("id") or o.get("orderId")) == str(new_id) for o in after)
    print(f"    {'✓' if listed else '✗'} LIST doğrulama: emir {'listede' if listed else 'LİSTEDE YOK'}")

    cancel_ok = False
    try:
        await inner.contractPrivatePostPlanorderCancel(
            [{"symbol": _mexc_sym(symbol), "orderId": str(new_id)}])
        cancel_ok = True
    except Exception as e:
        print(f"    ✗ HEDEFLİ CANCEL başarısız: {e}")
        try:
            # Temizlik: probe emrini asılı bırakma (SL/TP dahil hepsini
            # süpürmemek için önce hedefli denedik; bu son çare de hedefli
            # olmayan cancel_all DEĞİL — sadece uyarı basar).
            print("    ! probe emri asılı kaldı — 24 saatte kendisi düşer "
                  "(executeCycle=1) veya MEXC arayüzünden elle iptal edin")
        except Exception:
            pass
    if cancel_ok:
        await asyncio.sleep(1.5)
        final = await list_plan_orders(ex, symbol)
        gone = not any(str(o.get("id") or o.get("orderId")) == str(new_id) for o in final)
        print(f"    {'✓' if gone else '✗'} CANCEL doğrulama: emir {'silindi' if gone else 'HÂLÂ listede'}")
        return bool(listed and gone)
    return False


async def main() -> None:
    do_probe = "--probe" in sys.argv
    cfg = load_config()
    if cfg.exchange.paper_mode:
        print("PAPER modda — MEXC probe'u anlamsız. .env'de PAPER_MODE=false gerekli.")
        return

    ex = LiveExchange(cfg.exchange.api_key, cfg.exchange.api_secret,
                      leverage=cfg.exchange.leverage,
                      margin_mode=cfg.exchange.margin_mode)
    try:
        await ex.initialize(cfg.exchange.symbols[0])
    except Exception as e:
        print(f"initialize uyarı: {e}")

    print("=" * 70)
    print("  MEXC STOP-TAŞIMA PROBE" + ("  [AKTİF]" if do_probe else "  [read-only]"))
    print("=" * 70)

    results: list[bool] = []
    try:
        for sym in cfg.exchange.symbols:
            try:
                r = await probe_symbol(ex, sym, do_probe)
                if r is not None:
                    results.append(r)
            except Exception as e:
                print(f"  {sym}: hata: {e}")
    finally:
        await ex.close()

    print("\n" + "=" * 70)
    if not results:
        print("  SONUÇ YOK — probe koşulacak açık pozisyon + yerleşik SL bulunamadı.")
        print("  Bot bir pozisyon açtığında tekrar deneyin: --probe")
    elif all(results):
        print("  ✓ PROBE BAŞARILI — plan-order place + hedefli cancel çalışıyor.")
        print("  .env'e STOP_MOVE_ENABLED=true ekleyip botu yeniden başlatabilirsin:")
        print("    ORB+IFVG BE@1R + sr_breakout trailing canlıda aktifleşir (~+%3-4).")
    else:
        print("  ✗ PROBE BAŞARISIZ — STOP_MOVE_ENABLED=false KALMALI.")
        print("  Pozisyonlar giriş anındaki sabit SL/TP ile korunmaya devam eder.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
