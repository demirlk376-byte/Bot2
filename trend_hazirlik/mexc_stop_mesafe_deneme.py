"""
trend_hazirlik/mexc_stop_mesafe_deneme.py — TREND KOLU HAZIRLIĞI, ADIM 4 (MİNİK GERÇEK EMİRLER).

SORU: Adım 3'te pozisyona bağlı (ekli) stopu fiyatın %25 altına taşıma isteği MEXC'te
"5003 The price of stop-limit order error" ile reddedildi. Ek teminat sonrası tasfiye fiyatı çok aşağıdaydı.
Trendin stopu %20-25 uzakta olmalı; sınırın ne olduğunu ve hangi yolun çalıştığını bulmak için:
  1) Ekli stopu kademeli taşı: %12, %15, %20, %25 (kâr al = 0). Hangisi kabul ediliyor?
  2) %25 reddedilirse aynı taşımayı kâr al = fiyatın 3 katı ile ve botun ikinci yolu
     (change_price, giriş emri kimliğiyle) ile dene.
  3) İkinci bir minik long'u doğrudan %25 aşağıda ekli stopla aç (girişte geniş stop kabul ediliyor mu?).
  4) Ayrı, miktarlı plan-emir stopunu %25 aşağıya koy (7 gün geçerli) — kabul ediliyor mu?

GÜVENLİK: Adım 2/3 betikleriyle aynı korumalar ve aynı temizlik (mexc_hedge_deneme.py):
botun coinlerinde çalışmaz; hedge mod, boş coin, okunabilir durum ön-kontrolü; --evet yoksa hiçbir yazma
işlemi yok; temizlik sinyallere karşı korumalı ayrı görevde; iptaller yalnız bu coinde ve kimlikle.
En fazla 2 adım açık (~0.24 USDT DOT) + 0.10 USDT ek teminat.

Kullanım (VPS):
    cd /opt/bot2 && venv/bin/python trend_hazirlik/mexc_stop_mesafe_deneme.py            # yalnız kontrol
    cd /opt/bot2 && venv/bin/python trend_hazirlik/mexc_stop_mesafe_deneme.py --evet     # gerçekten çalıştır
Sonuç: trend_hazirlik/mexc_stop_mesafe_deneme_cikti.json (API anahtarı içermez).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
from datetime import datetime, timezone

BURASI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(BURASI))
sys.path.insert(0, BURASI)
from config import load_config  # noqa: E402
import mexc_hedge_deneme as D   # noqa: E402  (aynı korumalar, aynı temizlik)

KALDIRAC_BOT = 10
EK_TEMINAT = 0.10
KADEMELER = (0.88, 0.85, 0.80, 0.75)
CIKTI = os.path.join(BURASI, "mexc_stop_mesafe_deneme_cikti.json")


def basarili(r):
    return isinstance(r, dict) and "hata" not in r and r.get("success") is not False


async def stoplar(t):
    d = await t.durum("okuma")
    s = [x for x in (d["ekli_stoplar"] if D.liste_mi(d["ekli_stoplar"]) else []) if x.get("symbol") == t.msym]
    p = [x for x in (D.acik_bacaklar(d["pozisyonlar"], t.msym) or []) if str(x.get("positionType")) == "1"]
    return s, (p[0] if p else None)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coin", default="DOT")
    ap.add_argument("--evet", action="store_true")
    a = ap.parse_args()
    cfg = load_config()
    if cfg.exchange.paper_mode:
        D.yaz("PAPER modda — çalıştırılmadı.")
        return
    import ccxt
    import ccxt.pro as ccxtpro
    coin = a.coin.strip().upper()
    sym = f"{coin}/USDT:USDT"
    bot_coinleri = {s.split("/")[0].split("_")[0].upper() for s in cfg.exchange.symbols}
    if coin in bot_coinleri:
        D.yaz(f"DUR: {coin} botun coini. Botun kullanmadığı bir coin seç.")
        return
    ex = ccxtpro.mexc({"apiKey": cfg.exchange.api_key, "secret": cfg.exchange.api_secret,
                       "options": {"defaultType": "swap", "defaultSubType": "linear"}, "enableRateLimit": True})
    ex.has["fetchCurrencies"] = False
    rapor = {"zaman_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ccxt": ccxt.__version__,
             "coin": coin, "adimlar": {}, "ozet": {}}
    t, emir_gitti, temizlikte = None, False, False
    loop, ana = asyncio.get_running_loop(), asyncio.current_task()

    def sessiz():
        try:
            sys.stdout = sys.stderr = open(os.devnull, "w")
        except OSError:
            pass

    try:
        await ex.load_markets()
        if sym not in ex.markets:
            D.yaz(f"DUR: {sym} yok.")
            return
        m = ex.market(sym)
        msym = m["id"]
        if not (m.get("swap") and m.get("linear") and msym == f"{m.get('baseId')}_USDT"
                and str(m.get("baseId", "")).upper() not in bot_coinleri):
            D.yaz(f"DUR: beklenmeyen sözleşme (id={msym}).")
            return
        t = D.Deneme(ex, sym, msym, rapor)
        info = m.get("info") or {}
        cs, mv = float(info.get("contractSize") or 0), float(info.get("minVol") or 1)
        px = float((await ex.fetch_ticker(sym))["last"])
        pm = D.veri(await t.ham("contractPrivateGetPositionPositionMode"))
        try:
            pm = int(pm)
        except (TypeError, ValueError):
            pass
        t.kaydet("on_kontrol", {"sozlesme": msym, "fiyat": px, "bir_adim_usdt": cs * mv * px, "pozisyon_modu": pm})
        if pm != 1 or not (cs > 0 and px > 0) or 2 * cs * mv * px > 2.0:
            D.yaz("DUR: hedge mod değil / sözleşme bilgisi eksik / tutar 2 USDT'den büyük.")
            return
        bas = await t.durum("baslangic")
        if D.acik_bacaklar(bas["pozisyonlar"], msym) is None or not D.bos_mu(bas, msym):
            D.yaz("DUR: başlangıç durumu okunamadı ya da coinde pozisyon/emir var.")
            return
        D.yaz(f"\nPLAN ({msym} @ {px}): 10x long (stop %8) → {EK_TEMINAT} USDT ek teminat → ekli stopu %12/%15/%20/%25'e "
              "taşı → gerekirse kâr al ile ve change_price ile dene → %25 ekli stoplu 2. long → %25 plan stop → temizlik.")
        if not a.evet:
            D.yaz("Yalnız kontrol yapıldı, HİÇBİR emir/ayar gönderilmedi. Gerçekten çalıştırmak için: --evet")
            return

        def iptal_et():
            if not temizlikte:
                ana.cancel()

        def kopma():
            sessiz()
            iptal_et()
        loop.add_signal_handler(signal.SIGINT, iptal_et)
        loop.add_signal_handler(signal.SIGHUP, kopma)
        loop.add_signal_handler(signal.SIGTERM, iptal_et)
        emir_gitti = True
        D.KALDIRAC = KALDIRAC_BOT
        try:
            await ex.set_leverage(KALDIRAC_BOT, sym, params={"openType": 1, "positionType": 1})
            t.kaydet("kaldirac_long_10x", "ok")
        except Exception as e:
            t.kaydet("kaldirac_long_10x", f"{type(e).__name__}: {e}")
        fiyat = lambda k: float(ex.price_to_precision(sym, px * k))
        oz = rapor["ozet"]

        # Hazırlık: 10x long, ekli stop %8 aşağıda; ardından ek teminat (tasfiye engelini kaldırmak için)
        g1 = await t.emir("long1", "buy", mv, {"openType": 1, "leverage": KALDIRAC_BOT, "stopLossPrice": fiyat(0.92)})
        s, p = await stoplar(t)
        if p is None or not s:
            t.kaydet("sonuc", "long ya da ekli stopu görünmedi — test yarıda")
            return
        oz["tasfiye_ilk"] = p.get("liquidatePrice")
        r = await t.ham("contractPrivatePostPositionChangeMargin",
                        {"positionId": p.get("positionId"), "amount": EK_TEMINAT, "type": "ADD"})
        t.kaydet("ek_teminat", r)
        await asyncio.sleep(1.5)
        s, p = await stoplar(t)
        oz["tasfiye_ek_teminat_sonrasi"] = p.get("liquidatePrice") if p else None
        stop_id = s[0].get("id")
        ana_emir = s[0].get("orderId")

        # 1) kademeli taşıma (kâr al = 0)
        kabul = {}
        for k in KADEMELER:
            r = await t.ham("contractPrivatePostStoporderChangePlanPrice",
                            {"stopPlanOrderId": stop_id, "stopLossPrice": fiyat(k), "takeProfitPrice": 0})
            t.kaydet(f"tasi_{int(round((1 - k) * 100))}yuzde_tp0", r)
            await asyncio.sleep(1.2)
            s2, _ = await stoplar(t)
            kabul[f"%{int(round((1 - k) * 100))}"] = {"yanit_basarili": basarili(r),
                                                      "borsadaki_stop": [x.get("stopLossPrice") for x in s2]}
        oz["kademeli_tasima_tp0"] = kabul

        # 2) %25 başka yollarla
        r = await t.ham("contractPrivatePostStoporderChangePlanPrice",
                        {"stopPlanOrderId": stop_id, "stopLossPrice": fiyat(0.75), "takeProfitPrice": fiyat(3.0)})
        t.kaydet("tasi_25_tp_uzak", r)
        await asyncio.sleep(1.2)
        s2, _ = await stoplar(t)
        oz["tasi_25_tp_uzak"] = {"yanit_basarili": basarili(r), "borsadaki": [(x.get("stopLossPrice"), x.get("takeProfitPrice")) for x in s2]}
        if ana_emir:
            r = await t.ham("contractPrivatePostStoporderChangePrice",
                            {"orderId": ana_emir, "stopLossPrice": fiyat(0.75), "takeProfitPrice": 0})
            t.kaydet("tasi_25_change_price", r)
            await asyncio.sleep(1.2)
            s2, _ = await stoplar(t)
            oz["tasi_25_change_price"] = {"yanit_basarili": basarili(r), "borsadaki": [x.get("stopLossPrice") for x in s2]}

        # 3) girişte doğrudan %25 ekli stop (2. minik long)
        g2 = await t.emir("long2_stop25", "buy", mv, {"openType": 1, "leverage": KALDIRAC_BOT, "stopLossPrice": fiyat(0.75)})
        s2, p2 = await stoplar(t)
        oz["giriste_stop25"] = {"emir_basarili": g2.get("basarili"), "hata": g2.get("hata"),
                                "borsadaki_stoplar": [(x.get("stopLossPrice"), x.get("vol")) for x in s2],
                                "long_bacak_miktar": p2.get("holdVol") if p2 else None}

        # 4) ayrı plan stop %25 aşağıda, 1 adım, 7 gün
        g3 = await t.emir("plan_stop25", "sell", mv, {"openType": 1, "leverage": KALDIRAC_BOT, "reduceOnly": True,
                                                       "triggerPrice": fiyat(0.75), "triggerType": 2, "orderType": 5,
                                                       "executeCycle": 2})
        d = await t.durum("plan_sonrasi")
        oz["plan_stop25"] = {"emir_basarili": g3.get("basarili"), "hata": g3.get("hata"),
                             "borsadaki_plan": [(x.get("triggerPrice"), x.get("vol"), x.get("executeCycle"))
                                                for x in (d["plan_emirleri"] if D.liste_mi(d["plan_emirleri"]) else [])]}
    finally:
        try:
            if emir_gitti and t is not None:
                temizlikte = True
                try:
                    loop.add_signal_handler(signal.SIGINT, lambda: D.yaz("(Temizlik sürüyor — Ctrl+C yok sayıldı)"))
                    loop.add_signal_handler(signal.SIGHUP, sessiz)
                    loop.add_signal_handler(signal.SIGTERM, lambda: None)
                except (ValueError, OSError, RuntimeError):
                    pass
                if hasattr(ex, "init_throttler"):
                    try:
                        ex.init_throttler()
                    except Exception:
                        pass
                gorev = asyncio.ensure_future(D.temizle(t))
                while not gorev.done():
                    try:
                        await asyncio.shield(gorev)
                    except asyncio.CancelledError:
                        continue
                gorev.result()
        finally:
            try:
                await ex.close()
            finally:
                with open(CIKTI, "w") as f:
                    json.dump(rapor, f, indent=1, ensure_ascii=False, default=str)
                D.yaz("\n=== ÖZET ===\n" + json.dumps(rapor.get("ozet"), indent=1, ensure_ascii=False, default=str))
                D.yaz(f"temizlik: {rapor.get('temizlik')}")
                D.yaz(f"\nAyrıntı: {CIKTI}  (API anahtarı içermez)")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        D.yaz("\nProgram kesildi. Temizlik sonucu yukarıda ve rapor dosyasında.")
