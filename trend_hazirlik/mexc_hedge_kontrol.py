"""
trend_hazirlik/mexc_hedge_kontrol.py — TREND KOLU HAZIRLIĞI, ADIM 1 (YALNIZ OKUR).

HİÇBİR EMİR GÖNDERMEZ, HİÇBİR AYARI DEĞİŞTİRMEZ (set_leverage bile çağrılmaz).
Trend kolunu botun coinlerinde, botu engellemeden çalıştırmak için gereken üç bilgiyi okur:

  1. Hesabın pozisyon modu: HEDGE (çift yönlü: aynı coinde long ve short ayrı) mi,
     TEK YÖNLÜ mü (aynı coinde tek net pozisyon)?
  2. Açık pozisyonların teminat modu (izole/çapraz), kaldıracı ve tasfiye fiyatı.
  3. Dinlenen stop emirlerinin yapısı:
     - "ekli" stoplar (stoporder): pozisyona bağlı;
     - plan emirleri (planorder): miktara özel, süreli.

Kullanım (VPS):
    cd /opt/bot2 && venv/bin/python trend_hazirlik/mexc_hedge_kontrol.py

Çıktı ekrana yazılır ve trend_hazirlik/mexc_hedge_kontrol_cikti.json dosyasına kaydedilir.
API anahtarı ya da sır İÇERMEZ. Ekran görüntüsü ya da dosya içeriği paylaşılabilir.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import load_config  # noqa: E402

ALAN = ("symbol", "positionType", "openType", "leverage", "holdVol", "holdAvgPrice", "liquidatePrice",
        "im", "oim", "state", "vol", "stopLossPrice", "takeProfitPrice", "triggerPrice", "triggerType",
        "executeCycle", "side", "orderType", "positionId", "orderId", "id", "lossTrend", "profitTrend",
        "createTime", "updateTime")


def kirp(d: dict) -> dict:
    return {k: d.get(k) for k in ALAN if k in d}


async def cagir(inner, ad: str, params: dict | None = None):
    fn = getattr(inner, ad, None)
    if fn is None:
        return {"hata": f"ccxt'de {ad} yok"}
    try:
        return await fn(params or {})
    except Exception as e:  # okuma hatası: raporla, devam et
        return {"hata": f"{type(e).__name__}: {e}"}


def veri(resp):
    if isinstance(resp, dict) and "data" in resp:
        d = resp["data"]
        if isinstance(d, dict):
            d = d.get("resultList") or d.get("list") or d
        return d
    return resp


async def main() -> None:
    cfg = load_config()
    if cfg.exchange.paper_mode:
        print("PAPER modda — MEXC sorgusu yapılmadı. Canlı .env gerekli.")
        return
    import ccxt.pro as ccxtpro
    ex = ccxtpro.mexc({"apiKey": cfg.exchange.api_key, "secret": cfg.exchange.api_secret,
                       "options": {"defaultType": "swap", "defaultSubType": "linear"}, "enableRateLimit": True})
    ex.has["fetchCurrencies"] = False
    rapor: dict = {"zaman_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "bot_margin_mode_env": cfg.exchange.margin_mode, "bot_leverage_env": cfg.exchange.leverage}
    try:
        await ex.load_markets()

        # 1) Pozisyon modu: MEXC 1 = hedge (çift yönlü), 2 = tek yönlü
        pm = await cagir(ex, "contractPrivateGetPositionPositionMode")
        rapor["pozisyon_modu_ham"] = pm
        kod = veri(pm)
        rapor["pozisyon_modu"] = {1: "HEDGE (çift yönlü)", 2: "TEK YÖNLÜ"}.get(kod, f"bilinmiyor ({kod})")

        # 2) Açık pozisyonlar (ham MEXC alanları)
        op = await cagir(ex, "contractPrivateGetPositionOpenPositions")
        poz = veri(op) if not (isinstance(op, dict) and "hata" in op) else op
        rapor["acik_pozisyonlar"] = [kirp(p) for p in poz] if isinstance(poz, list) else poz

        # 3) Stop yapısı: her bot coini için ekli stoplar ve plan emirleri
        stoplar, planlar = {}, {}
        for sym in cfg.exchange.symbols:
            msym = sym.split(":")[0].replace("/", "_")
            so = veri(await cagir(ex, "contractPrivateGetStoporderOpenOrders", {"symbol": msym}))
            po = veri(await cagir(ex, "contractPrivateGetPlanorderListOrders", {"symbol": msym, "states": "1"}))
            if so:
                stoplar[msym] = [kirp(o) for o in so] if isinstance(so, list) else so
            if po:
                planlar[msym] = [kirp(o) for o in po] if isinstance(po, list) else po
            await asyncio.sleep(0.3)
        rapor["ekli_stoplar"] = stoplar
        rapor["plan_emirleri"] = planlar

        # 4) Bakiye (yalnız USDT toplamları)
        bal = await ex.fetch_balance({"type": "swap"})
        u = bal.get("USDT") or {}
        rapor["usdt"] = {"free": u.get("free"), "used": u.get("used"), "total": u.get("total")}
    finally:
        await ex.close()

    print("=" * 66)
    print("  TREND HAZIRLIK — MEXC HESAP YAPISI (yalnız okuma)")
    print("=" * 66)
    print(f"  Pozisyon modu          : {rapor['pozisyon_modu']}")
    print(f"  Bot .env teminat/kaldıraç: {rapor['bot_margin_mode_env']} / {rapor['bot_leverage_env']}x")
    print(f"  USDT                   : {rapor['usdt']}")
    ap = rapor["acik_pozisyonlar"]
    print(f"  Açık pozisyon sayısı   : {len(ap) if isinstance(ap, list) else ap}")
    if isinstance(ap, list):
        for p in ap:
            print("   -", {k: p.get(k) for k in ("symbol", "positionType", "openType", "leverage", "holdVol",
                                                 "holdAvgPrice", "liquidatePrice")})
    print(f"  Ekli stop olan coinler : {list(rapor['ekli_stoplar'])}")
    print(f"  Plan emri olan coinler : {list(rapor['plan_emirleri'])}")
    yol = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mexc_hedge_kontrol_cikti.json")
    with open(yol, "w") as f:
        json.dump(rapor, f, indent=1, ensure_ascii=False, default=str)
    print(f"\n  Ayrıntı: {yol}")
    print("  (Bu dosyada API anahtarı yok; içeriği paylaşabilirsin.)")


if __name__ == "__main__":
    asyncio.run(main())
