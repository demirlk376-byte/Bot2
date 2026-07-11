"""
check_mexc_stopmove.py — MEXC stop-taşıma endpoint'leri SAĞLIKLI mı?
BE/trailing'i canlıda açmadan (STOP_MOVE_ENABLED=true) önce koşulacak probe.

Canlı girişler korumayı GİRİŞE İLİŞTİRİLMİŞ (position-attached) SL/TP olarak
koyar — bu, plan-order listesinde DEĞİL stoporder ailesinde durur. Bot SL
taşırken de öncelikle bu iliştirilmiş stopu stoporder/change_price ile yerinde
değiştirir (atomik; ekstra emir yok, TP aynen korunur). İliştirilmiş stop
yoksa plan-order place+cancel yedeğine düşer. Bu script iki mekanizmayı da
gerçek pozisyon üzerinde SIFIR riskle test eder:

  Probe A (change_price): SL'yi mevcut yerinden %0.5 DAHA UZAĞA taşı (long'da
  aşağı, short'ta yukarı — asla tetiklenme yönüne değil), borsadan doğrula,
  sonra AYNEN eski fiyatına geri al. Pozisyon hiçbir anda korumasız kalmaz.

  Probe B (plan place+cancel, yalnız iliştirilmiş stop yoksa): gerçek SL'den
  kesinlikle daha uzak reduce-only bir tetik koy, listede doğrula, hedefli
  iptal et. Gerçek SL her zaman önce tetiklenir.

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


async def probe_change_price(ex: LiveExchange, symbol: str, side: str,
                             attached: dict) -> bool:
    """İliştirilmiş stopun SL'ini %0.5 uzağa taşı → doğrula → geri al.

    Taşımayı ÜRETİM kod yolu (_change_attached_sl: change_plan_price →
    change_price fallback + borsadan re-read doğrulaması) yapar — probe neyi
    test ediyorsa bot canlıda AYNISINI çalıştırır."""
    cur_sl = float(attached.get("stopLossPrice") or 0)
    if cur_sl <= 0:
        print(f"    SL okunamadı ({attached.get('id')}) — atlanıyor")
        return False

    away = cur_sl * (0.995 if side == "long" else 1.005)   # tetiklenme yönünün TERSİ
    away = float(ex._exchange.price_to_precision(symbol, away))
    print(f"    PROBE A (attached SL modify): SL {cur_sl} → {away} (uzağa) → geri {cur_sl}")

    moved = await ex._change_attached_sl(symbol, attached, away)
    print(f"    {'✓' if moved else '✗'} taşıma: {'borsa onayladı' if moved else 'başarısız'}")

    # Her durumda eski SL'e dönmeyi dene (taşıma başarısızsa zaten yerinde;
    # attached dict'i tazele ki id'ler değiştiyse doğru stopu hedefleyelim).
    fresh = await ex._get_attached_stop(symbol) or attached
    restored = await ex._change_attached_sl(symbol, fresh, cur_sl)
    print(f"    {'✓' if restored else '✗'} geri alma: SL {cur_sl}")
    if not restored:
        print(f"    ! SL {cur_sl} değerine GERİ ALINAMADI — MEXC arayüzünden "
              f"elle kontrol edin (şu an {'daha uzak/güvenli' if moved else 'değişmemiş'} olmalı)")
    return moved and restored


async def probe_plan_orders(ex: LiveExchange, symbol: str, side: str,
                            sl_level: float, contracts_base: float) -> bool:
    """Plan-order place + hedefli cancel testi (gerçek SL'den daha uzak tetik)."""
    inner = ex._exchange
    sl_trigger = 2 if side == "long" else 1
    probe_price = sl_level * (0.99 if side == "long" else 1.01)
    probe_price = float(inner.price_to_precision(symbol, probe_price))
    print(f"    PROBE B (plan place+cancel): tetik {probe_price} "
          f"(gerçek SL {sl_level} — probe kesinlikle daha uzak)")

    close_side = "sell" if side == "long" else "buy"
    open_type = 1 if ex._margin_mode == "isolated" else 2
    params = {"orderType": 5, "executeCycle": 1, "openType": open_type,
              "reduceOnly": True, "triggerPrice": probe_price,
              "triggerType": sl_trigger}
    if open_type == 1:
        params["leverage"] = ex._leverage
    contracts = ex._to_contracts(symbol, contracts_base, round_up=False)

    try:
        resp = await inner.create_order(symbol, "market", close_side,
                                        contracts, None, params)
    except Exception as e:
        print(f"    ✗ PLACE başarısız (exception): {e}")
        return False
    new_id = (resp or {}).get("id") or ((resp or {}).get("info") or {}).get("orderId")
    if not new_id:
        print(f"    ✗ PLACE sessiz reject (yanıtta id yok): {resp}")
        return False
    print(f"    ✓ PLACE ok — emir id {new_id}")

    await asyncio.sleep(1.5)
    after = await list_plan_orders(ex, symbol)
    listed = any(str(o.get("id") or o.get("orderId")) == str(new_id) for o in after)
    print(f"    {'✓' if listed else '✗'} LIST doğrulama: emir {'listede' if listed else 'LİSTEDE YOK'}")

    try:
        await inner.contractPrivatePostPlanorderCancel(
            [{"symbol": _mexc_sym(symbol), "orderId": str(new_id)}])
    except Exception as e:
        print(f"    ✗ HEDEFLİ CANCEL başarısız: {e}")
        print("    ! probe emri asılı kaldı — reduce-only + gerçek SL'den uzak "
              "(zararsız); 24 saatte kendisi düşer veya MEXC arayüzünden iptal edin")
        return False
    await asyncio.sleep(1.5)
    final = await list_plan_orders(ex, symbol)
    gone = not any(str(o.get("id") or o.get("orderId")) == str(new_id) for o in final)
    print(f"    {'✓' if gone else '✗'} CANCEL doğrulama: emir {'silindi' if gone else 'HÂLÂ listede'}")
    return bool(listed and gone)


async def probe_symbol(ex: LiveExchange, symbol: str, do_probe: bool) -> bool | None:
    """None = bu sembolde probe koşulamadı; True/False = sonuç."""
    pos = await ex.get_position(symbol)
    if pos is None:
        print(f"  {symbol}: pozisyon yok — probe atlanıyor")
        return None

    attached = await ex._get_attached_stop(symbol)
    plans = await list_plan_orders(ex, symbol)
    sl_trigger = 2 if pos.side == "long" else 1
    plan_sl = [o for o in plans if int(o.get("triggerType", 0)) == sl_trigger]

    att_sl = float((attached or {}).get("stopLossPrice") or 0)
    att_tp = float((attached or {}).get("takeProfitPrice") or 0)
    print(f"  {symbol}: {pos.side} {pos.contracts} @ {pos.entry_price:.4f}")
    if attached is not None:
        print(f"    iliştirilmiş koruma: SL={att_sl} TP={att_tp}  ✓ (stoporder)")
    if plans:
        print(f"    plan emirleri: {len(plans)} ({len(plan_sl)} SL yönlü)")
    if attached is None and not plan_sl:
        print("    ⚠ NE İLİŞTİRİLMİŞ NE PLAN SL BULUNDU — pozisyon korumasız "
              "görünüyor, botun reconciliation logunu kontrol edin!")
        return None
    if not do_probe:
        print("    (aktif test için --probe ile çalıştır)")
        return None

    # move_stop_loss'un GERÇEKTE kullanacağı mekanizmayı test et:
    if attached is not None:
        return await probe_change_price(ex, symbol, pos.side, attached)
    sl_level = min((float(o.get("triggerPrice") or 0) for o in plan_sl)) \
        if pos.side == "long" else \
        max((float(o.get("triggerPrice") or 0) for o in plan_sl))
    if sl_level <= 0:
        print("    SL tetik fiyatı okunamadı — atlanıyor")
        return None
    return await probe_plan_orders(ex, symbol, pos.side, sl_level, pos.contracts)


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
        print("  ✓ PROBE BAŞARILI — stop-taşıma mekanizması çalışıyor.")
        print("  .env'e STOP_MOVE_ENABLED=true ekleyip botu yeniden başlatabilirsin:")
        print("    ORB+IFVG BE@1R + sr_breakout trailing canlıda aktifleşir (~+%3-4).")
    else:
        print("  ✗ PROBE BAŞARISIZ — STOP_MOVE_ENABLED=false KALMALI.")
        print("  Pozisyonlar giriş anındaki sabit SL/TP ile korunmaya devam eder.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
