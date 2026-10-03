"""
trend_hazirlik/mexc_hedge_deneme.py — TREND KOLU HAZIRLIĞI, ADIM 2 (MİNİK GERÇEK EMİRLER).

AMAÇ: Trend kolunun botun coinlerinde, botu ENGELLEMEDEN çalışabilmesi için borsanın üç
davranışını gerçek ama minik emirlerle doğrulamak:
  A) Aynı coinde aynı yönde (long) iki ayrı giriş, her biri kendi "ekli" stopuyla açılınca:
     ikinci giriş birincinin stopunu EZİYOR mu, yoksa iki ayrı stop mu oluşuyor?
  B) Hedge modda aynı coinde long ve short AYNI ANDA ayrı bacak olarak duruyor mu?
  C) Pozisyonun yalnız bir kısmını kapatan plan-emir stopu 7 gün geçerlilikle
     (executeCycle=2) kabul ediliyor mu, listeleniyor mu, kimliğiyle iptal edilebiliyor mu?

GÜVENLİK:
  • BOTUN COİNLERİNDE ÇALIŞMAZ: .env SYMBOLS listesindeki bir coin verilirse durur. Varsayılan DOT.
  • Hesap hedge modda değilse, coinde açık pozisyon ya da (stop/plan/normal) emir varsa, ya da durum
    okunamazsa durur.
  • Her emir borsanın izin verdiği EN KÜÇÜK miktardır (1 adım). Toplam açık tutar 5 USDT'yi geçecekse durur.
  • --evet verilmezse HİÇBİR YAZMA İŞLEMİ YAPMAZ (kaldıraç ayarı dahil), yalnız kontrol edip planı yazar.
  • Emir gönderildiyse: hata, Ctrl+C, SSH kopması (SIGHUP) ya da SIGTERM olsa bile temizlik çalışır.
    Temizlik ayrı bir görevde koşar, sırasında gelen sinyaller yok sayılır, her borsa isteği 30 sn
    zaman aşımlıdır (asılı kalmaz). Önce bacaklar kapatılır; stoplar ancak bacakların kapandığı
    OKUNARAK doğrulandıktan sonra iptal edilir. İptaller yalnız bu coindeki emirlere, KİMLİKLE yapılır.
    Hesap genelinde iptal eden uç noktalar KULLANILMAZ.
  • Stoplar 5x izole kaldıracın tasfiye fiyatının İÇİNDE tutulur (long %10-12 aşağıda, short %12 yukarıda).
  • ccxt'nin `hedged=True` yolu KULLANILMAZ (ccxt 4.5.x'te kapanış yön kodları ters eşleniyor).
    Bot gibi açık yön kodlu varsayılan yol kullanılır: buy=1 long aç, sell=3 short aç,
    sell+reduceOnly=4 long kapat, buy+reduceOnly=2 short kapat.

Kullanım (VPS; bot çalışırken de olur, bot bu coine dokunmaz). SSH koparsa diye screen/tmux önerilir:
    cd /opt/bot2 && venv/bin/python trend_hazirlik/mexc_hedge_deneme.py            # yalnız kontrol + plan
    cd /opt/bot2 && venv/bin/python trend_hazirlik/mexc_hedge_deneme.py --evet     # gerçekten çalıştır

Sonuç ekrana ve trend_hazirlik/mexc_hedge_deneme_cikti.json'a yazılır (API anahtarı içermez).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import load_config  # noqa: E402

ALAN = ("symbol", "positionType", "openType", "leverage", "holdVol", "holdAvgPrice", "liquidatePrice",
        "state", "vol", "price", "stopLossPrice", "takeProfitPrice", "triggerPrice", "triggerType",
        "executeCycle", "side", "orderType", "positionId", "orderId", "id", "lossTrend", "profitTrend")
KALDIRAC = 5
MAKS_TOPLAM_USDT = 5.0
ZAMAN_ASIMI = 30.0          # her borsa isteği en fazla bu kadar bekler (asılı kalan istek → hata kaydı)
CIKTI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mexc_hedge_deneme_cikti.json")


def yaz(metin):
    """Terminal koptuysa (SSH) print OSError verir; temizliği bozmasın."""
    try:
        print(metin, flush=True)
    except (OSError, ValueError):
        pass


def kirp(d):
    return {k: d.get(k) for k in ALAN if k in d} if isinstance(d, dict) else d


def veri(resp):
    """MEXC ham yanıtından 'data'yı çıkar. Okunamayan yanıt {'hata': ...} döner (asla boş liste SANILMAZ)."""
    if isinstance(resp, dict) and "hata" in resp:
        return resp
    if isinstance(resp, dict) and "data" in resp:
        d = resp["data"]
        if d is None:
            return [] if resp.get("success") is True else {"hata": "data=null", "ham": resp}
        if isinstance(d, dict):
            for k in ("resultList", "list"):
                if k in d:
                    return d[k] or []
        return d
    return {"hata": "beklenmeyen yanıt", "ham": resp}


def liste_mi(x):
    return isinstance(x, list)


def bu_coin(kayitlar, msym):
    """Okunabilir listeyse yalnız bu coinin kayıtları (symbol alanı yoksa güvenli tarafta: dahil)."""
    if not liste_mi(kayitlar):
        return None
    return [k for k in kayitlar if isinstance(k, dict) and k.get("symbol", msym) == msym]


def acik_bacaklar(poz, msym):
    """Okunabilir listeyse açık bacaklar; holdVol tam 0 değilse (ya da okunamıyorsa) AÇIK sayılır."""
    kay = bu_coin(poz, msym)
    if kay is None:
        return None
    acik = []
    for p in kay:
        try:
            if float(p.get("holdVol")) == 0.0:
                continue
        except (TypeError, ValueError):
            pass
        acik.append(p)
    return acik


class Deneme:
    def __init__(self, ex, sym, msym, rapor):
        self.ex, self.sym, self.msym, self.r = ex, sym, msym, rapor
        self.adim = 0

    def kaydet(self, ad, deger):
        self.adim += 1
        anahtar = f"{self.adim:02d}_{ad}"
        self.r["adimlar"][anahtar] = deger
        yaz(f"\n[{anahtar}]\n{json.dumps(deger, indent=1, ensure_ascii=False, default=str)[:1500]}")

    async def ham(self, ad, params=None):
        fn = getattr(self.ex, ad, None)
        if fn is None:
            return {"hata": f"ccxt'de {ad} yok"}
        try:
            return await asyncio.wait_for(fn(params if params is not None else {}), ZAMAN_ASIMI)
        except Exception as e:
            return {"hata": f"{type(e).__name__}: {e}"}

    async def durum(self, etiket):
        poz = veri(await self.ham("contractPrivateGetPositionOpenPositions", {"symbol": self.msym}))
        so = veri(await self.ham("contractPrivateGetStoporderOpenOrders", {"symbol": self.msym}))
        po = veri(await self.ham("contractPrivateGetPlanorderListOrders", {"symbol": self.msym, "states": "1"}))
        no = veri(await self.ham("contractPrivateGetOrderListOpenOrdersSymbol", {"symbol": self.msym}))
        d = {}
        for ad, x in (("pozisyonlar", poz), ("ekli_stoplar", so), ("plan_emirleri", po), ("normal_emirler", no)):
            k = bu_coin(x, self.msym)
            d[ad] = [kirp(i) for i in k] if k is not None else x
        self.kaydet(f"durum_{etiket}", d)
        await asyncio.sleep(1.0)
        return d

    async def emir(self, etiket, side, vol, params):
        try:
            o = await asyncio.wait_for(
                self.ex.create_order(self.sym, "market", side, vol, None, dict(params)), ZAMAN_ASIMI)
            ham = getattr(self.ex, "last_http_response", None)
            try:
                ham = json.loads(ham) if isinstance(ham, str) else ham
            except ValueError:
                pass
            ok = isinstance(ham, dict) and (ham.get("success") is True or ham.get("code") in (0, 200)) \
                and ham.get("data") is not None
            sonuc = {"id": o.get("id"), "borsa_yaniti": ham, "basarili": ok}
        except Exception as e:
            sonuc = {"hata": f"{type(e).__name__}: {e}", "basarili": False}
        self.kaydet(f"emir_{etiket}", {"side": side, "vol": vol, "params": params, "sonuc": sonuc})
        await asyncio.sleep(1.5)
        return sonuc

    async def kimlikle_iptal(self, d):
        """Yalnız BU coinde listelenen plan, ekli-stop ve normal emirleri kimlikleriyle iptal et.
        İptal hedefi olmak için kaydın symbol alanı TAM bu coin olmalı (alansız kayıt hedef olmaz)."""
        tam = lambda xs: [o for o in (xs if liste_mi(xs) else []) if isinstance(o, dict) and o.get("symbol") == self.msym]
        d = {k: tam(d.get(k)) for k in ("plan_emirleri", "ekli_stoplar", "normal_emirler")}
        plan = [str(o.get("id") or o.get("orderId")) for o in d["plan_emirleri"] if (o.get("id") or o.get("orderId"))]
        if plan:
            self.kaydet("plan_iptal", await self.ham("contractPrivatePostPlanorderCancel",
                                                       [{"symbol": self.msym, "orderId": i} for i in plan]))
        stop = [str(o.get("id")) for o in d["ekli_stoplar"] if o.get("id")]
        if stop:
            self.kaydet("ekli_stop_iptal", await self.ham("contractPrivatePostStoporderCancel",
                                                            [{"stopPlanOrderId": i} for i in stop]))
        normal = [str(o.get("orderId") or o.get("id")) for o in d["normal_emirler"] if (o.get("orderId") or o.get("id"))]
        if normal:
            self.kaydet("normal_emir_iptal", await self.ham("contractPrivatePostOrderCancel", normal))
        await asyncio.sleep(1.5)


def bos_mu(d, msym):
    bacak = acik_bacaklar(d["pozisyonlar"], msym)
    okunabilir = bacak is not None and all(liste_mi(d[k]) for k in ("ekli_stoplar", "plan_emirleri", "normal_emirler"))
    return okunabilir and not bacak and not d["ekli_stoplar"] and not d["plan_emirleri"] and not d["normal_emirler"]


async def temizle(t: Deneme):
    """Önce bacakları kapat; stopları ancak kapandığı OKUNDUKTAN sonra iptal et; boşluğu doğrula."""
    t.r["temizlik"] = "EKSİK — MEXC'te elle kontrol et!"
    yaz("\n=== TEMİZLİK (Ctrl+C bu sırada yok sayılır) ===")
    try:
        for deneme in range(4):
            d = await t.durum(f"temizlik_{deneme}_once")
            bacak = acik_bacaklar(d["pozisyonlar"], t.msym)
            if bacak is None:                       # okunamadı: körlemesine hiçbir şey iptal etme
                await asyncio.sleep(3.0)
                continue
            if liste_mi(d["plan_emirleri"]) and d["plan_emirleri"]:   # ek plan stop: her an iptal edilebilir
                await t.kimlikle_iptal({"plan_emirleri": d["plan_emirleri"], "ekli_stoplar": [], "normal_emirler": []})
            for p in bacak:
                try:
                    long_mu = int(p.get("positionType")) == 1          # MEXC: 1=long, 2=short
                    vol = float(p.get("holdVol"))
                except (TypeError, ValueError):
                    t.kaydet(f"bacak_okunamadi_{deneme}", p)            # atla; diğer bacaklar kapanmaya devam
                    continue
                await t.emir(f"kapat_{'long' if long_mu else 'short'}_{deneme}", "sell" if long_mu else "buy", vol,
                             {"reduceOnly": True, "openType": 1, "leverage": KALDIRAC})
            await asyncio.sleep(2.0)
            d2 = await t.durum(f"temizlik_{deneme}_kapatma_sonrasi")
            if acik_bacaklar(d2["pozisyonlar"], t.msym) == []:      # bacaklar KAPANDI (okunarak doğrulandı)
                await t.kimlikle_iptal(d2)                            # artık kalan stop/emirleri temizle
                d3 = await t.durum(f"temizlik_{deneme}_son")
                if bos_mu(d3, t.msym):
                    t.r["temizlik"] = "TAMAM — coin boş, emir yok"
                    yaz("\nTemizlik TAMAM: coin boş, emir yok.")
                    return
            await asyncio.sleep(3.0)
        yaz(f"\n!!! TEMİZLİK DOĞRULANAMADI: MEXC uygulamasında {t.msym} pozisyon ve emirlerini ELLE kontrol et/kapat !!!")
    except BaseException:
        yaz(f"\n!!! TEMİZLİK YARIDA KESİLDİ: MEXC uygulamasında {t.msym} pozisyon ve emirlerini ELLE kontrol et/kapat !!!")
        raise


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coin", default="DOT")
    ap.add_argument("--evet", action="store_true", help="gerçekten emir gönder")
    a = ap.parse_args()
    cfg = load_config()
    if cfg.exchange.paper_mode:
        yaz("PAPER modda — çalıştırılmadı (canlı .env gerekli).")
        return
    import ccxt
    import ccxt.pro as ccxtpro
    coin = a.coin.strip().upper()
    sym = f"{coin}/USDT:USDT"
    bot_coinleri = {s.split("/")[0].split("_")[0].upper() for s in cfg.exchange.symbols}
    if coin in bot_coinleri:
        yaz(f"DUR: {coin} botun coini ({sorted(bot_coinleri)}). Botun kullanmadığı bir coin seç.")
        return
    ex = ccxtpro.mexc({"apiKey": cfg.exchange.api_key, "secret": cfg.exchange.api_secret,
                       "options": {"defaultType": "swap", "defaultSubType": "linear"}, "enableRateLimit": True})
    ex.has["fetchCurrencies"] = False
    rapor = {"zaman_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ccxt": ccxt.__version__,
             "coin": coin, "adimlar": {}}
    t = None
    emir_gitti = False
    temizlikte = False
    loop, ana = asyncio.get_running_loop(), asyncio.current_task()

    def sessiz():
        try:                                  # SSH koptuysa ölü terminale yazmak OSError verir
            sys.stdout = sys.stderr = open(os.devnull, "w")
        except OSError:
            pass

    try:
        await ex.load_markets()
        if sym not in ex.markets:
            yaz(f"DUR: {sym} MEXC vadeli piyasasında yok.")
            return
        m = ex.market(sym)
        msym = m["id"]
        if not (m.get("swap") and m.get("linear") and msym == f"{m.get('baseId')}_USDT"
                and str(m.get("baseId", "")).upper() not in bot_coinleri):
            yaz(f"DUR: {sym} beklenen USDT vadeli sözleşmesi değil ya da botun coinine eşleniyor (id={msym}).")
            return
        t = Deneme(ex, sym, msym, rapor)
        info = m.get("info") or {}
        cs = float(info.get("contractSize") or m.get("contractSize") or 0)
        mv = float(info.get("minVol") or 1)
        px = float((await ex.fetch_ticker(sym))["last"])
        adim_usdt = cs * mv * px
        pm = veri(await t.ham("contractPrivateGetPositionPositionMode"))
        try:
            pm = int(pm)
        except (TypeError, ValueError):
            pass
        t.kaydet("on_kontrol", {"sozlesme": msym, "fiyat": px, "contractSize": cs, "minVol": mv,
                                "bir_adim_usdt": adim_usdt, "pozisyon_modu": pm, "en_fazla_acik_usdt": 3 * adim_usdt})
        if pm != 1:
            yaz(f"DUR: hesap hedge modda değil ya da okunamadı (mod={pm}).")
            return
        if not (cs > 0 and px > 0) or 3 * adim_usdt > MAKS_TOPLAM_USDT:
            yaz(f"DUR: toplam {3 * adim_usdt:.4f} USDT > {MAKS_TOPLAM_USDT} ya da sözleşme bilgisi eksik. "
                "Daha ucuz bir coin seç (örn. --coin XTZ).")
            return
        bas = await t.durum("baslangic")
        if acik_bacaklar(bas["pozisyonlar"], msym) is None or not all(
                liste_mi(bas[k]) for k in ("ekli_stoplar", "plan_emirleri", "normal_emirler")):
            yaz("DUR: başlangıç durumu okunamadı (yukarıdaki 'hata' alanlarına bak).")
            return
        if not bos_mu(bas, msym):
            yaz(f"DUR: {coin} üzerinde zaten pozisyon ya da emir var.")
            return
        yaz(f"\nPLAN ({msym} @ {px}, adım {adim_usdt:.4f} USDT): long+long (ayrı ekli stoplar) → short → "
            "long bacağın 1 adımını kapatan 7 günlük plan stop → kimlikle iptal → temizlik.")
        if not a.evet:
            yaz("Yalnız kontrol yapıldı, HİÇBİR emir/ayar gönderilmedi. Gerçekten çalıştırmak için: --evet")
            return

        def iptal_et():
            if not temizlikte:                # temizlik başladıysa hiçbir sinyal onu kesemez
                ana.cancel()

        def kopma():
            sessiz()
            iptal_et()
        # Üç sinyal de YALNIZ ana görevi iptal eder → finally → temizlik. (Python ≤3.10'da varsayılan Ctrl+C,
        # asyncio.run'ın tüm görevleri iptal etmesine ve ccxt hız sınırlayıcısının ölmesine yol açıyordu.)
        loop.add_signal_handler(signal.SIGINT, iptal_et)
        loop.add_signal_handler(signal.SIGHUP, kopma)
        loop.add_signal_handler(signal.SIGTERM, iptal_et)
        emir_gitti = True
        for pt in (1, 2):   # izole kaldıraç: 1=long bacak, 2=short bacak
            try:
                await ex.set_leverage(KALDIRAC, sym, params={"openType": 1, "positionType": pt})
                t.kaydet(f"kaldirac_bacak{pt}", "ok")
            except Exception as e:
                t.kaydet(f"kaldirac_bacak{pt}", f"{type(e).__name__}: {e}")
        base = {"openType": 1, "leverage": KALDIRAC}
        fiyat = lambda k: float(ex.price_to_precision(sym, px * k))
        # Stoplar 5x izole tasfiye bandının (~±%19) İÇİNDE ve fiyattan uzak.
        # A) iki ayrı long giriş, her biri kendi ekli stopuyla
        await t.emir("long1", "buy", mv, {**base, "stopLossPrice": fiyat(0.88)})
        await t.durum("long1_sonrasi")
        await t.emir("long2", "buy", mv, {**base, "stopLossPrice": fiyat(0.90)})
        await t.durum("long2_sonrasi")
        # B) aynı coinde short (ayrı bacak bekleniyor)
        await t.emir("short1", "sell", mv, {**base, "stopLossPrice": fiyat(1.12)})
        await t.durum("short1_sonrasi")
        # C) long bacağın YALNIZ 1 adımını kapatan, 7 gün geçerli plan stop (fiyat ≤ tetik → piyasa emri)
        await t.emir("plan_stop_long_1adim", "sell", mv,
                     {**base, "reduceOnly": True, "triggerPrice": fiyat(0.87), "triggerType": 2,
                      "orderType": 5, "executeCycle": 2})
        d = await t.durum("plan_sonrasi")
        if liste_mi(d["plan_emirleri"]) and d["plan_emirleri"]:
            await t.kimlikle_iptal({"plan_emirleri": d["plan_emirleri"], "ekli_stoplar": [], "normal_emirler": []})
            await t.durum("plan_iptal_sonrasi")
        else:
            t.kaydet("plan_kimlikle_iptal", "plan emri listede görünmedi — iptal denenmedi")
    finally:
        try:
            if emir_gitti and t is not None:
                temizlikte = True                                    # kuyrukta bekleyen eski sinyaller de etkisiz
                try:
                    loop.add_signal_handler(signal.SIGINT, lambda: yaz("(Temizlik sürüyor — Ctrl+C yok sayıldı)"))
                    loop.add_signal_handler(signal.SIGHUP, sessiz)
                    loop.add_signal_handler(signal.SIGTERM, lambda: None)
                except (ValueError, OSError, RuntimeError):
                    pass
                if hasattr(ex, "init_throttler"):                    # iptal edilen bir istek sınırlayıcıyı kilitlemiş olabilir
                    try:
                        ex.init_throttler()
                    except Exception:
                        pass
                gorev = asyncio.ensure_future(temizle(t))            # ayrı görev + kalkan: ana görevin
                while not gorev.done():                              # iptali temizliğe ulaşamaz
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
                yaz(f"\nAyrıntı: {CIKTI}  (API anahtarı içermez; paylaşabilirsin)")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        yaz("\nProgram kesildi. Temizliğin sonucu yukarıda ('Temizlik TAMAM' ya da 'ELLE kontrol et') "
            "ve rapor dosyasında yazıyor.")
