"""
trend_hazirlik/mexc_trend_uctan_uca.py — TREND KOLU, 2. AŞAMA UÇTAN UCA DENEME (MİNİK GERÇEK EMİRLER).

2. aşamada eklenen GERÇEK kod yollarını (exchange.LiveExchange'in yeni yöntemleri ve
trend_canli._teminat_ayarla) botun kullanmadığı bir coinde, en küçük miktarla çalıştırır:
  1) "Trend" girişi: market + ekli stop (%25 aşağı) + uzak TP (fiyat×10); kendi stopu kimlikle bulunuyor mu?
  2) Ek teminat (trend_canli._teminat_ayarla): tasfiye fiyatı stopun altına iniyor mu?
  3) Aynı bacağa ikinci "bot" girişi (stop %8, TP %20): iki ayrı ekli stop mu?
  4) move_stop_loss(order_id=trend, tp_yedek) → YALNIZ trendin stopu değişiyor mu, bot stopu yerinde mi?
  5) move_stop_loss(order_id=bot) → YALNIZ botun stopu değişiyor mu?
  6) Bot kolunu kapat (kısmi azaltma) → MEXC kapanan kolun stopunu kendisi siliyor mu? Ardından
     cancel_attached_stop_for_order(bot) → bot stopu gidiyor, trend stopu ve trend miktarı kalıyor mu?
  7) Tasfiye fiyatı hâlâ trend stopunun altında mı?
  8) Temizlik (her durumda).

GÜVENLİK: Adım 2–4 betikleriyle aynı korumalar ve aynı temizlik (mexc_hedge_deneme.py):
botun coinlerinde çalışmaz; hedge mod, boş coin, okunabilir durum ön-kontrolü; --evet yoksa HİÇBİR yazma
işlemi yok (kaldıraç ayarı dahil); temizlik sinyallere karşı korumalı ayrı görevde; iptaller yalnız bu coinde
ve kimlikle. En fazla 2 adım açık (~0.24 USDT DOT) + küçük ek teminat (temizlikte geri döner).

Kullanım (VPS):
    cd /opt/bot2 && venv/bin/python trend_hazirlik/mexc_trend_uctan_uca.py            # yalnız kontrol
    cd /opt/bot2 && venv/bin/python trend_hazirlik/mexc_trend_uctan_uca.py --evet     # gerçekten çalıştır
Sonuç: ekranda "=== ÖZET ===" ve trend_hazirlik/mexc_trend_uctan_uca_cikti.json (API anahtarı içermez).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
import types
from datetime import datetime, timezone

BURASI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(BURASI))
sys.path.insert(0, BURASI)
from config import load_config   # noqa: E402
import mexc_hedge_deneme as D    # noqa: E402  (aynı korumalar, aynı temizlik)

KALDIRAC = 10
CIKTI = os.path.join(BURASI, "mexc_trend_uctan_uca_cikti.json")


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
    from exchange import LiveExchange
    import trend_canli as TC
    coin = a.coin.strip().upper()
    sym = f"{coin}/USDT:USDT"
    bot_coinleri = {s.split("/")[0].split("_")[0].upper() for s in cfg.exchange.symbols}
    if coin in bot_coinleri:
        D.yaz(f"DUR: {coin} botun coini. Botun kullanmadığı bir coin seç.")
        return
    # Ön-kontrol için ayrı, YAZMAYAN istemci (LiveExchange.initialize kaldıraç ayarlar → yalnız --evet ile)
    okur = ccxtpro.mexc({"apiKey": cfg.exchange.api_key, "secret": cfg.exchange.api_secret,
                         "options": {"defaultType": "swap", "defaultSubType": "linear"}, "enableRateLimit": True})
    okur.has["fetchCurrencies"] = False
    rapor = {"zaman_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ccxt": ccxt.__version__,
             "coin": coin, "adimlar": {}, "ozet": {}}
    ex = None
    t, emir_gitti, temizlikte = None, False, False
    loop, ana = asyncio.get_running_loop(), asyncio.current_task()

    def sessiz():
        try:
            sys.stdout = sys.stderr = open(os.devnull, "w")
        except OSError:
            pass

    try:
        await okur.load_markets()
        if sym not in okur.markets:
            D.yaz(f"DUR: {sym} yok.")
            return
        m = okur.market(sym)
        msym = m["id"]
        if not (m.get("swap") and m.get("linear") and msym == f"{m.get('baseId')}_USDT"
                and str(m.get("baseId", "")).upper() not in bot_coinleri):
            D.yaz(f"DUR: beklenmeyen sözleşme (id={msym}).")
            return
        t = D.Deneme(okur, sym, msym, rapor)
        info = m.get("info") or {}
        cs, mv = float(info.get("contractSize") or 0), float(info.get("minVol") or 1)
        px = float((await okur.fetch_ticker(sym))["last"])
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
        D.yaz(f"\nPLAN ({msym} @ {px}): trend girişi (stop %25, TP ×10) → ek teminat → bot girişi (stop %8) → "
              "kimlikle stop taşımaları → bot kolunu kapat + kendi stopunu iptal → kontroller → temizlik.")
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
        D.KALDIRAC = KALDIRAC
        ex = LiveExchange(cfg.exchange.api_key, cfg.exchange.api_secret, leverage=KALDIRAC, margin_mode="isolated")
        await ex.initialize(sym)                       # DOT için izole 10x (yalnız bu coin)
        t = D.Deneme(ex._exchange, sym, msym, rapor)  # temizlik/okuma LiveExchange'in istemcisiyle
        oz = rapor["ozet"]
        adim = cs * mv                                # baz birim (örn. 0.1 DOT)
        r = lambda k: float(ex._exchange.price_to_precision(sym, px * k))

        async def stoplar():
            s = await ex.list_attached_stops(sym)
            return None if s is None else {str(x.get("orderId")): (x.get("stopLossPrice"), x.get("takeProfitPrice"),
                                                                     x.get("vol")) for x in s}

        # 1) trend girişi
        g1 = await ex.place_market_order(sym, "buy", adim, {"stopLossPrice": r(0.75), "takeProfitPrice": r(10.0)})
        A = g1.order_id
        await asyncio.sleep(2)
        s = await stoplar()
        oz["1_trend_giris"] = {"emir": A, "dolum": g1.filled_price, "kendi_stopu_var": bool(s and A in s), "stoplar": s}
        # 2) ek teminat (gerçek trend_canli fonksiyonu)
        poz = types.SimpleNamespace(symbol=sym, entry_price=g1.filled_price or px)
        mesajlar = []

        async def gonder(mm):
            mesajlar.append(mm)
        ok = await TC._teminat_ayarla(ex, None, poz, r(0.75), gonder)
        leg = await ex.get_leg(sym, "long")
        oz["2_ek_teminat"] = {"basarili": ok, "tasfiye": (leg or {}).get("liquidatePrice"), "stop": r(0.75),
                              "hedef_alti": (TC.TASFIYE_PAYI, "×stop mesafesi"), "mesajlar": mesajlar}
        # 3) aynı bacağa bot girişi
        g2 = await ex.place_market_order(sym, "buy", adim, {"stopLossPrice": r(0.92), "takeProfitPrice": r(1.20)})
        B = g2.order_id
        await asyncio.sleep(2)
        s = await stoplar()
        oz["3_bot_giris"] = {"emir": B, "iki_ayri_stop": bool(s and A in s and B in s), "stoplar": s}
        # 4) trend stopunu kimlikle taşı (TP yedekli)
        ok4 = await ex.move_stop_loss(sym, "long", r(0.80), adim, order_id=A, tp_yedek=r(10.0))
        await asyncio.sleep(1.5)
        s = await stoplar()
        oz["4_trend_stop_tasima"] = {"yanit": ok4, "stoplar": s,
                                     "yalniz_trend_degisti": bool(s and A in s and B in s
                                                                  and abs(float(s[A][0]) - r(0.80)) < 1e-9
                                                                  and abs(float(s[B][0]) - r(0.92)) < 1e-9)}
        # 5) bot stopunu kimlikle taşı
        ok5 = await ex.move_stop_loss(sym, "long", r(0.93), adim, order_id=B)
        await asyncio.sleep(1.5)
        s = await stoplar()
        oz["5_bot_stop_tasima"] = {"yanit": ok5, "stoplar": s,
                                   "yalniz_bot_degisti": bool(s and A in s and B in s
                                                              and abs(float(s[B][0]) - r(0.93)) < 1e-9
                                                              and abs(float(s[A][0]) - r(0.80)) < 1e-9)}
        # 6) bot kolunu kapat (bacak açık kalıyor) → MEXC ne yapıyor? → kendi stopunu kimlikle iptal
        await ex.close_position(sym, "long", adim, "deneme_bot_kapat")
        await asyncio.sleep(2)
        s_once = await stoplar()
        iptal = await ex.cancel_attached_stop_for_order(sym, B)
        await asyncio.sleep(1.5)
        s_sonra = await stoplar()
        leg = await ex.get_leg(sym, "long")
        oz["6_bot_kapat"] = {"kapanistan_hemen_sonra_stoplar": s_once,
                             "mexc_kapanan_stopu_kendisi_sildi_mi": bool(s_once is not None and B not in s_once),
                             "iptal_sonucu": iptal, "iptal_sonrasi_stoplar": s_sonra,
                             "trend_stopu_kaldi": bool(s_sonra and A in s_sonra),
                             "bot_stopu_gitti": bool(s_sonra is not None and B not in s_sonra),
                             "bacak_miktar": (leg or {}).get("holdVol")}
        # 7) tasfiye hâlâ trend stopunun altında mı?
        oz["7_tasfiye_kontrol"] = {"tasfiye": (leg or {}).get("liquidatePrice"), "trend_stop": r(0.80),
                                   "stopun_altinda": bool(leg) and float(leg.get("liquidatePrice") or 0) < r(0.80)}
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
                cli = t.ex
                if hasattr(cli, "init_throttler"):
                    try:
                        cli.init_throttler()
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
                await okur.close()
                if ex is not None:
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
