"""
trend_hazirlik/mexc_teminat_deneme.py — TREND KOLU HAZIRLIĞI, ADIM 3 (MİNİK GERÇEK EMİRLER).

SORU: Trendin stopu girişten %25'e kadar uzakta olabilir. Botun ayarı izole 10x; o kaldıraçta pozisyon
yaklaşık %9.5 düşüşte TASFİYE olur, yani stop hiç çalışmadan. İki çözümü minik pozisyonla deniyoruz:
  1) Pozisyona EK TEMİNAT eklemek → tasfiye fiyatı stopun altına iniyor mu?
     Ardından ekli stopu %25 aşağıya taşıyabiliyor muyuz (botun kullandığı change_plan_price yolu)?
  2) Açık pozisyonun KALDIRACINI düşürmek (10x → 3x) → izin veriliyor mu, tasfiye fiyatı nereye gidiyor?

GÜVENLİK: Adım 2 betiğiyle (mexc_hedge_deneme.py) aynı korumalar ve aynı temizlik kodu kullanılır:
botun coinlerinde çalışmaz; hedge mod, boş coin, okunabilir durum ön-kontrolü; --evet yoksa hiçbir yazma
işlemi yok; temizlik sinyallere karşı korumalı ayrı görevde; iptaller yalnız bu coinde ve kimlikle.
Açık tutar en fazla 1 adım (~0.12 USDT DOT), eklenen teminat 0.10 USDT.

Kullanım (VPS):
    cd /opt/bot2 && venv/bin/python trend_hazirlik/mexc_teminat_deneme.py            # yalnız kontrol
    cd /opt/bot2 && venv/bin/python trend_hazirlik/mexc_teminat_deneme.py --evet     # gerçekten çalıştır
Sonuç: trend_hazirlik/mexc_teminat_deneme_cikti.json (API anahtarı içermez).
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

KALDIRAC_BOT = 10            # botun canlı ayarı (izole 10x)
EK_TEMINAT = 0.10            # USDT
CIKTI = os.path.join(BURASI, "mexc_teminat_deneme_cikti.json")


async def long_bacak(t):
    d = await t.durum("okuma")
    bacak = D.acik_bacaklar(d["pozisyonlar"], t.msym) or []
    for p in bacak:
        if str(p.get("positionType")) == "1":
            return p, d
    return None, d


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
             "coin": coin, "adimlar": {}}
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
        if pm != 1 or not (cs > 0 and px > 0) or cs * mv * px > 2.0:
            D.yaz("DUR: hedge mod değil / sözleşme bilgisi eksik / bir adım 2 USDT'den büyük.")
            return
        bas = await t.durum("baslangic")
        if D.acik_bacaklar(bas["pozisyonlar"], msym) is None or not D.bos_mu(bas, msym):
            D.yaz("DUR: başlangıç durumu okunamadı ya da coinde pozisyon/emir var.")
            return
        D.yaz(f"\nPLAN ({msym} @ {px}): izole {KALDIRAC_BOT}x long (stop %8 aşağıda) → tasfiye fiyatını oku → "
              f"{EK_TEMINAT} USDT ek teminat → stopu %25 aşağı taşı → kaldıracı 3x'e düşür → temizlik.")
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
        D.KALDIRAC = KALDIRAC_BOT       # temizlikteki kapatma emirleri bu kaldıraçla gider (aşağıda güncellenir)
        try:
            await ex.set_leverage(KALDIRAC_BOT, sym, params={"openType": 1, "positionType": 1})
            t.kaydet("kaldirac_long_10x", "ok")
        except Exception as e:
            t.kaydet("kaldirac_long_10x", f"{type(e).__name__}: {e}")
        fiyat = lambda k: float(ex.price_to_precision(sym, px * k))
        # 1) izole 10x long, stop %8 aşağıda (10x tasfiye bandının içinde)
        await t.emir("long_10x", "buy", mv, {"openType": 1, "leverage": KALDIRAC_BOT, "stopLossPrice": fiyat(0.92)})
        p, d = await long_bacak(t)
        if p is None:
            t.kaydet("sonuc", "long bacak açılmadı — test yarıda")
            return
        pid = p.get("positionId")
        t.kaydet("tasfiye_ilk", {"liquidatePrice": p.get("liquidatePrice"), "leverage": p.get("leverage"),
                                 "oran_fiyata": (float(p["liquidatePrice"]) / px) if p.get("liquidatePrice") else None})
        # 2) ek teminat
        t.kaydet("ek_teminat", await t.ham("contractPrivatePostPositionChangeMargin",
                                           {"positionId": pid, "amount": EK_TEMINAT, "type": "ADD"}))
        await asyncio.sleep(1.5)
        p, d = await long_bacak(t)
        if p is not None:
            t.kaydet("tasfiye_ek_teminat_sonrasi", {"liquidatePrice": p.get("liquidatePrice"), "leverage": p.get("leverage"),
                                                    "oran_fiyata": (float(p["liquidatePrice"]) / px) if p.get("liquidatePrice") else None})
        # 3) ekli stopu %25 aşağı taşı (botun change_plan_price yolu)
        stoplar = [s for s in (d["ekli_stoplar"] if D.liste_mi(d["ekli_stoplar"]) else []) if s.get("symbol") == msym]
        if stoplar and stoplar[0].get("id"):
            t.kaydet("stop_tasi_25", await t.ham("contractPrivatePostStoporderChangePlanPrice",
                                                 {"stopPlanOrderId": stoplar[0]["id"], "stopLossPrice": fiyat(0.75),
                                                  "takeProfitPrice": 0}))
            await asyncio.sleep(1.5)
            await t.durum("stop_tasima_sonrasi")
        else:
            t.kaydet("stop_tasi_25", "ekli stop bulunamadı — taşıma denenmedi")
        # 4) açık pozisyonun kaldıracını 3x'e düşür
        try:
            r = await asyncio.wait_for(ex.set_leverage(3, sym, params={"positionId": int(pid)}), D.ZAMAN_ASIMI)
            t.kaydet("kaldirac_3x", r)
        except Exception as e:
            t.kaydet("kaldirac_3x", f"{type(e).__name__}: {e}")
        await asyncio.sleep(1.5)
        p, d = await long_bacak(t)
        if p is not None:
            t.kaydet("tasfiye_3x_sonrasi", {"liquidatePrice": p.get("liquidatePrice"), "leverage": p.get("leverage"),
                                            "oran_fiyata": (float(p["liquidatePrice"]) / px) if p.get("liquidatePrice") else None})
            try:
                D.KALDIRAC = int(p.get("leverage") or KALDIRAC_BOT)
            except (TypeError, ValueError):
                pass
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
                D.yaz(f"\nAyrıntı: {CIKTI}  (API anahtarı içermez)")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        D.yaz("\nProgram kesildi. Temizlik sonucu yukarıda ve rapor dosyasında.")
