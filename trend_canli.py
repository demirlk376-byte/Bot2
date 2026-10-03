"""
trend_canli.py — trend kolunun canlı bota bağlantısı.

  TREND_MODE=kapali (varsayılan) → hiçbir şey çalışmaz; bot davranışı bit bit aynı.
  TREND_MODE=sinyal              → her 4 saatlik kapanışta trend kolu sanal defteri günceller ve
                                   giriş / piramit / çıkış olaylarını Telegram'a yazar. Borsaya YALNIZ
                                   mum verisi okumak için gidilir (fetch_ohlcv). Emir, stop, teminat YOK.
  TREND_MODE=canli               → (2. aşama) sanal defterin kararları GERÇEK emirle uygulanır:
                                   giriş/piramit = market + ekli stop + uzak TP, ardından bacağa ek teminat;
                                   erken çıkış ve senkron farkı = kapatma; iz süren stop = kolun KENDİ ekli
                                   stopunu taşıma. Önkoşul: HEDGE_AWARE_RECON=true (bot short + trend long
                                   aynı coinde iken mutabakat bacak bazında yapılmalı). Önkoşul yoksa
                                   canlı yol çalışmaz, sinyal moduna düşülür ve uyarı gönderilir.

Diğer ayarlar:
  TREND_COINS          virgüllü liste (boşsa botun SYMBOLS listesi)
  TREND_RISK_PCT       mesajlarda gösterilen risk tutarı için (varsayılan 0.01)
  TREND_DURUM_DOSYASI  sanal defterin JSON dosyası (varsayılan: trend_durum.json, bot klasöründe)

Tasarım: research/trend_takip_v1/TREND_KOLU_TASARIM.md. Mantık: trend_kolu.py (araştırma motoruyla
birebir eşdeğerliği research/trend_takip_v1/canli_esdegerlik.py ile doğrulandı: 441/441 işlem).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time

import pandas as pd

import trend_kolu as TK

logger = logging.getLogger(__name__)

MOD = os.environ.get("TREND_MODE", "kapali").strip().lower()
AKTIF = MOD in ("sinyal", "canli")
CANLI = MOD == "canli"
MAKS_ACIK_RISK = float(os.environ.get("TREND_MAKS_ACIK_RISK", "0.24") or 0.24)   # özsermaye oranı
TP_KAT = 10.0            # ekli stopun yanına konan uzak kâr al (TP=0 ile stop taşıma MEXC'te reddediliyor)
TASFIYE_PAYI = float(os.environ.get("TREND_TASFIYE_PAYI", "0.5") or 0.5)   # tasfiye ≥ stop − pay × stop mesafesi
RISK_PCT = float(os.environ.get("TREND_RISK_PCT", "0.01") or 0.01)
DURUM_DOSYASI = os.environ.get("TREND_DURUM_DOSYASI",
                               os.path.join(os.path.dirname(os.path.abspath(__file__)), "trend_durum.json"))
GECMIS_GUN = 95          # her sembol için çekilen 4h geçmişi (1D: 50 gün + ATR ısınması; 4H: 180 mum)
# ETH SMA200, işlenen EN ESKİ mumun karar gününde de hesaplanabilmeli: geçmiş + 200 gün + pay.
# (Yetmezse o günlerin rejimi "bilinmiyor" sayılır ve giriş açılmaz — trend_kolu.)
ETH_GECMIS_GUN = GECMIS_GUN + TK.ETH_SMA + 25

_kilit = asyncio.Lock()
_son_tetik: int | None = None
_gorevler: set = set()


def _coinler(bot_semboller: list[str]) -> list[str]:
    ham = os.environ.get("TREND_COINS", "").strip()
    if ham:
        return [f"{c.strip().upper()}/USDT:USDT" for c in ham.split(",") if c.strip()]
    return list(bot_semboller)


async def _mumlar_4h(exchange, sembol: str, gun: int) -> pd.DataFrame:
    """Tamamlanmış 4h mumları (t, open, high, low, close); sayfalı çekim."""
    simdi = int(time.time() * 1000)
    since = simdi - gun * TK.DAY_MS
    satirlar: list = []
    for _ in range(6):
        parca = await exchange.fetch_ohlcv(sembol, "4h", since, 1000)
        if not parca:
            break
        satirlar.extend(parca)
        son = int(parca[-1][0])
        if son + TK.H4_MS >= simdi or len(parca) < 2:
            break
        since = son + TK.H4_MS
        await asyncio.sleep(0.3)
    if not satirlar:
        return pd.DataFrame(columns=["t", "open", "high", "low", "close"])
    df = pd.DataFrame([r[:5] for r in satirlar], columns=["t", "open", "high", "low", "close"])
    df = df.astype({"t": "int64", "open": float, "high": float, "low": float, "close": float})
    df = df.drop_duplicates("t").sort_values("t")
    df = df[df.t + TK.H4_MS <= simdi]                     # yalnız kapanmış mumlar
    return df.reset_index(drop=True)


def _yukle() -> "TK.Defter | None":
    try:
        with open(DURUM_DOSYASI) as f:
            return TK.Defter.yukle(json.load(f))
    except FileNotFoundError:
        return None
    except Exception as e:
        logger.error("trend: durum dosyası okunamadı (%s) — yedeklenip sıfırdan başlanıyor", e)
        try:
            os.replace(DURUM_DOSYASI, DURUM_DOSYASI + f".bozuk.{int(time.time())}")
        except OSError:
            pass
        return None


def _kaydet(d: "TK.Defter") -> None:
    gecici = DURUM_DOSYASI + ".tmp"
    with open(gecici, "w") as f:
        json.dump(d.durum(), f, ensure_ascii=False)
    os.replace(gecici, DURUM_DOSYASI)


async def _canli_onkosul(exchange, executor) -> "str | None":
    """Canlı yol için önkoşul eksikse açıklaması; tamamsa None."""
    try:
        from exchange import HEDGE_AWARE_RECON
    except Exception:
        HEDGE_AWARE_RECON = False
    if not HEDGE_AWARE_RECON:
        return "HEDGE_AWARE_RECON=true değil (bacak bazında mutabakat şart)"
    for m in ("list_attached_stops", "move_stop_loss", "get_leg", "add_leg_margin",
              "cancel_attached_stop_for_order", "get_position_mode"):
        if not hasattr(exchange, m):
            return f"borsa katmanında {m} yok"
    try:
        if float(getattr(executor._config.risk, "fixed_margin_usdt", 0.0) or 0.0) > 0:
            return "FIXED_MARGIN_USDT > 0 (trend riski yüzdeyle boyutlanmalı)"
    except Exception:
        pass
    mod = await exchange.get_position_mode()
    if mod != 1:
        return f"hesap hedge modda değil ya da okunamadı (mod={mod})"
    return None


def _trend_mi(p) -> bool:
    return (p.strategy_scores or {}).get("strategy") == "trend_kolu"


def _trend_pozlar(executor, kisa: str) -> list:
    return [p for p in executor._portfolio.get_open_positions()
            if _trend_mi(p) and p.symbol.split("/")[0] == kisa]


async def _bacak_tam_mi(exchange, executor, sembol: str) -> "bool | None":
    """Long bacaktaki gerçek miktar, iç long kolların toplamını karşılıyor mu? (Karşılamıyorsa bir stop
    zaten tetiklenmiştir; kapatma emri öbür kolun sözleşmelerini satar → mutabakata bırakılır.)"""
    leg = await exchange.get_leg(sembol, "long")
    ic = sum(p.quantity for p in executor._portfolio.get_open_positions()
             if p.symbol == sembol and p.side == "long")
    if leg is None:
        return False if ic > 0 else True
    try:
        gercek = float(leg.get("holdVol") or 0) * exchange._contract_size(sembol)
    except Exception:
        return None
    return gercek + max(ic * 0.01, 1e-9) >= ic


async def _guvenli_kapat(exchange, executor, p, neden: str, gonder) -> bool:
    """Trend kolunu YALNIZ bacak tamken kapatır; değilse dokunmaz (mutabakat halleder)."""
    tam = await _bacak_tam_mi(exchange, executor, p.symbol)
    if tam is not True:
        logger.warning("trend: %s bacak eksik/okunamadı (%s) — %s kapatması mutabakata bırakıldı", p.symbol, tam, neden)
        return False
    fiyat = await exchange.get_current_price(p.symbol)
    return bool(await executor.close_position(p, neden, fiyat))


async def _teminat_ayarla(exchange, executor, p, stop: float, gonder) -> bool:
    """İzole long bacağın tasfiye fiyatını stopun (TASFIYE_PAYI × stop mesafesi) altına iter.
    Başarısızsa False (çağıran kolu kapatır — güvenli taraf)."""
    sembol = p.symbol
    hedef = stop - TASFIYE_PAYI * max(p.entry_price - stop, 0.0)
    son_liq = None
    for _ in range(4):
        leg = await exchange.get_leg(sembol, "long")
        if not leg:
            await gonder(f"⚠️ TREND {sembol}: bacak okunamadı, tasfiye fiyatı doğrulanamadı")
            return False
        try:
            liq = float(leg.get("liquidatePrice") or 0)
            miktar = float(leg.get("holdVol") or 0) * exchange._contract_size(sembol)
        except Exception:
            return False
        if liq <= hedef:                 # 0 / negatif: tasfiye fiyatı yok (tam teminatlı) → güvenli
            return True
        if son_liq is not None and abs(liq - son_liq) < 1e-12:
            await asyncio.sleep(2.0)                 # tasfiye fiyatı henüz güncellenmemiş: bekle, tekrar oku
            continue
        if miktar <= 0:
            return False
        ek = (liq - hedef) * miktar * 1.15 + 0.01
        if not await exchange.add_leg_margin(sembol, "long", ek):
            await gonder(f"⚠️ TREND {sembol}: ek teminat eklenemedi (tasfiye {liq:g} > hedef {hedef:g})")
            return False
        son_liq = liq
        await asyncio.sleep(2.0)
    leg = await exchange.get_leg(sembol, "long")
    try:
        return bool(leg) and float(leg.get("liquidatePrice") or 0) <= hedef
    except Exception:
        return False


def _sinyal(kisa: str, slot_ek: str, fiyat: float, stop: float, bilgi: dict):
    from strategies.signal_combiner import CombinedSignal
    sig = CombinedSignal(direction=1, confidence=1.0, trend_score=1.0, mean_rev_score=0.0, breakout_score=1.0,
                         dominant_strategy="trend_kolu", reasons=[f"trend {bilgi.get('trend_modul')} {slot_ek}"],
                         entry_price=fiyat, sl_price=stop, tp_price=fiyat * TP_KAT,
                         symbol=f"{kisa}/USDT:USDT", position_slot=f"{kisa}/USDT:USDT:trend{slot_ek}",
                         force_market=True, anchor_is_level=False)
    sig.trend_bilgi = bilgi
    return sig


async def _canli_uygula(defter, olaylar, exchange, executor, gonder, son_bar: "dict | None" = None,
                        izinli: "set | None" = None) -> None:
    """Sanal defterin bu turdaki kararlarını gerçek emirle uygular ve canlı/sanal farkını kapatır.
    son_bar: {(sembol, modül): son tamamlanmış mumun t'si} → yalnız EN SON mumdaki olaylara işlem yapılır
    (kesintiden sonra yakalanan eski sinyaller canlıda uygulanmaz; farkı senkron kapatır).
    izinli: canlıda işlem yapılabilecek coinler (botun SYMBOLS'u)."""
    yalniz_sanal = set(defter.meta.get("yalniz_sanal") or [])
    eq = await executor.current_equity()
    for o in olaylar:
        if o.sembol in yalniz_sanal or (izinli is not None and o.sembol not in izinli):
            continue
        if son_bar is not None and son_bar.get((o.sembol, o.modul)) != o.t:
            continue
        sembol = f"{o.sembol}/USDT:USDT"
        try:
            if o.tur in ("GIRIS_SINYALI", "EK_SINYALI"):
                if not eq:
                    await gonder(f"⚠️ TREND {o.sembol}: özsermaye okunamadı, giriş atlandı")
                    continue
                acik_risk = sum(max(p.entry_price - p.sl_price, 0) * p.quantity
                                for p in executor._portfolio.get_open_positions() if _trend_mi(p))
                if (acik_risk + eq * RISK_PCT) / eq > MAKS_ACIK_RISK:
                    await gonder(f"TREND {o.sembol}: açık trend riski tavanı (%{MAKS_ACIK_RISK*100:.0f}) — atlandı")
                    continue
                mevcut = _trend_pozlar(executor, o.sembol)
                sanal = defter.poz.get(o.sembol)
                if o.tur == "EK_SINYALI":
                    if not mevcut or sanal is None or len(mevcut) > TK.PIRAMIT_MAKS:
                        continue
                    slot_ek = f":ek{sanal.ekler + 1}"      # defterden: aynı ek iki kez açılamaz (slot dolu)
                else:
                    if mevcut:
                        continue
                    slot_ek = ""
                fiyat = await exchange.get_current_price(sembol)
                stop = o.stop
                if not (fiyat > stop > 0):
                    await gonder(f"TREND {o.sembol}: fiyat {fiyat:g} stopun ({stop:g}) üstünde değil — atlandı")
                    continue
                bilgi = {"trend_modul": o.modul, "trend_sinyal_t": o.t, "trend_lot": slot_ek or "ana"}
                res = await executor.execute_signal(_sinyal(o.sembol, slot_ek, fiyat, stop, bilgi), 0.0)
                if res.success and res.position:
                    if not await _teminat_ayarla(exchange, executor, res.position, stop, gonder):
                        kapandi = await _guvenli_kapat(exchange, executor, res.position, "trend_teminat_yok", gonder)
                        await gonder(f"🛑 TREND {o.sembol}: tasfiye fiyatı stopun altına itilemedi → "
                                     f"{'kapatıldı' if kapandi else 'KAPATILAMADI, MEXC’te kontrol et'}")
                        continue
                    await gonder(f"🟢 TREND {o.modul} {o.sembol}: GERÇEK {'giriş' if not slot_ek else 'piramit eki'} "
                                 f"{res.position.entry_price:g}, stop {stop:g}, miktar {res.position.quantity:g}")
                else:
                    await gonder(f"⚠️ TREND {o.modul} {o.sembol}: emir açılamadı — {res.error}")
            elif o.tur == "CIKIS_SINYALI":
                kapanan = 0
                for p in _trend_pozlar(executor, o.sembol):
                    kapanan += await _guvenli_kapat(exchange, executor, p, "trend_erken_cikis", gonder)
                if kapanan:
                    await gonder(f"🔴 TREND {o.modul} {o.sembol}: GERÇEK erken çıkış ({kapanan} kol)")
        except Exception as e:
            logger.error("trend canlı uygulama hatası %s: %s", o.sembol, e, exc_info=True)
            await gonder(f"⚠️ TREND {o.sembol}: canlı uygulama hatası — {e}")

    # Senkron: iz süren stop, canlı/sanal farkı, koruma ve teminat kontrolü
    for kisa in {p.symbol.split("/")[0] for p in executor._portfolio.get_open_positions() if _trend_mi(p)} \
            | set(defter.poz):
        if kisa in yalniz_sanal:
            continue
        sembol = f"{kisa}/USDT:USDT"
        sanal = defter.poz.get(kisa)
        canli = _trend_pozlar(executor, kisa)
        bekleyen_giris = (defter.bekleyen.get(kisa) or {}).get("tur") == "giris"
        try:
            if canli and sanal is None and not bekleyen_giris:
                kapanan = 0
                for p in canli:
                    kapanan += await _guvenli_kapat(exchange, executor, p, "trend_senkron", gonder)
                if kapanan:
                    await gonder(f"🔴 TREND {kisa}: sanal pozisyon kapandı → {kapanan} gerçek kol kapatıldı")
                continue
            if sanal is not None and not canli:
                defter.poz.pop(kisa, None)          # canlı stop önce çalıştı ya da giriş açılamadı
                defter.bekleyen.pop(kisa, None)
                await gonder(f"TREND {kisa}: gerçek pozisyon yok → sanal pozisyon da kapatıldı (senkron)")
                continue
            if sanal is None:
                continue
            stoplar = await exchange.list_attached_stops(sembol)
            for p in canli:
                if stoplar is not None and not any(str(x.get("orderId")) == str(p.id) for x in stoplar):
                    # Stop yok: ya tetiklendi (bacak eksik → mutabakat kapatır) ya da gerçekten kayboldu.
                    if await _bacak_tam_mi(exchange, executor, sembol) is True:
                        kapandi = await _guvenli_kapat(exchange, executor, p, "trend_stopsuz", gonder)
                        await gonder(f"🛑 TREND {kisa}: kolun kendi stopu borsada YOK → "
                                     f"{'güvenlik için kapatıldı' if kapandi else 'KAPATILAMADI, MEXC’te kontrol et'}")
                    continue
                if sanal.stop > p.sl_price * 1.0005:
                    async with executor._symbol_lock(sembol):
                        ok = await exchange.move_stop_loss(sembol, "long", sanal.stop, p.quantity,
                                                           order_id=p.id, tp_yedek=p.tp_price)
                    if ok:
                        p.sl_price = sanal.stop
                        try:
                            await executor._db.update_trade_sl(p.id, sanal.stop)
                        except Exception:
                            pass
            for p in _trend_pozlar(executor, kisa):     # tasfiye fiyatı hâlâ stopun altında mı?
                if not await _teminat_ayarla(exchange, executor, p, p.sl_price, gonder):
                    await gonder(f"⚠️ TREND {kisa}: tasfiye fiyatı stopun altında tutulamıyor — kontrol et")
                break
        except Exception as e:
            logger.error("trend senkron hatası %s: %s", kisa, e, exc_info=True)


async def _calistir(exchange, bot_semboller, gonder, ozsermaye, executor=None) -> None:
    async with _kilit:
        defter = _yukle()
        ilk_kurulum = defter is None
        if ilk_kurulum:
            defter = TK.Defter()
        eth = await _mumlar_4h(exchange, "ETH/USDT:USDT", ETH_GECMIS_GUN)
        rejim = TK.eth_rejim(TK.gunluk_4h_den(eth))
        olaylar: list = []
        son_barlar: dict = {}
        for s in _coinler(bot_semboller):
            kisa = s.split("/")[0]
            try:
                df4 = eth if kisa == "ETH" else await _mumlar_4h(exchange, s, GECMIS_GUN)
            except Exception as e:
                logger.warning("trend: %s mumları alınamadı: %s", s, e)
                continue
            if len(df4) < 300:
                logger.info("trend: %s yetersiz geçmiş (%d mum)", s, len(df4))
                continue
            d1 = TK.gunluk_4h_den(df4)
            if len(d1):
                son_barlar[(kisa, "1D")] = int(d1["t"].iloc[-1])
            son_barlar[(kisa, "4H")] = int(df4["t"].iloc[-1])
            # iki modül ORTAK ZAMANDA işlenir (aynı kapanışta önce 1D, sonra 4H)
            olaylar += defter.zaman_sirali_isle(kisa, {"1D": d1, "4H": df4}, rejim)
            await asyncio.sleep(0.2)
        canli_yol = False
        if CANLI and executor is not None:
            neden = await _canli_onkosul(exchange, executor)
            if ilk_kurulum and any(_trend_mi(p) for p in executor._portfolio.get_open_positions()):
                neden = ("trend durum dosyası yok/okunamadı ama açık gerçek trend pozisyonları var — canlı yol "
                         "DURDURULDU (pozisyonlar kendi stoplarıyla duruyor); dosyayı geri yükle ya da elle karar ver")
            if neden:
                if defter.meta.get("onkosul_uyari") != neden:
                    defter.meta["onkosul_uyari"] = neden
                    await gonder(f"⚠️ TREND canlı mod ÇALIŞMADI: {neden}. Sinyal modunda devam ediliyor.")
            else:
                canli_yol = True
                defter.meta.pop("onkosul_uyari", None)
                if not defter.meta.get("canli_basladi"):
                    # Canlıya geçişte o an sanal açık olanlar GERÇEĞE TAŞINMAZ (eski sinyal); kapanana kadar
                    # yalnız sanal izlenir. Canlı yalnız bundan sonraki girişleri uygular.
                    defter.meta["canli_basladi"] = True
                    defter.meta["yalniz_sanal"] = sorted(defter.poz)
                    olaylar = [] if ilk_kurulum else olaylar
                    await gonder("TREND canlı mod başladı. Sanal açık olanlar yalnız sanal izlenecek: "
                                 + (", ".join(defter.meta["yalniz_sanal"]) or "yok"))
                defter.meta["yalniz_sanal"] = [k for k in defter.meta.get("yalniz_sanal", []) if k in defter.poz]
                if not ilk_kurulum:
                    _kaydet(defter)                 # önce kaydet: yarıda kesilirse olaylar TEKRAR uygulanmaz
                    izinli = {x.split("/")[0] for x in bot_semboller}
                    await _canli_uygula(defter, olaylar, exchange, executor, gonder, son_barlar, izinli)
        _kaydet(defter)
    if ilk_kurulum:
        acik = ", ".join(f"{k}({p.modul})" for k, p in defter.poz.items()) or "yok"
        await gonder(f"TREND (sinyal modu) başladı. Geçmişten kurulan sanal açık pozisyonlar: {acik}")
        return
    if not olaylar:
        return
    try:
        eq = await ozsermaye()
    except Exception:
        eq = None
    for o in olaylar:
        if o.tur in ("GIRIS_SINYALI", "GIRIS", "EK", "CIKIS"):
            ek = ""
            if o.tur == "GIRIS_SINYALI" and eq:
                ek = f" — gerçek modda %{RISK_PCT * 100:.2f} risk ≈ {eq * RISK_PCT:.2f} USDT"
            await gonder(o.metin() + ek)


def tetikle(son_mum_acilis: pd.Timestamp, exchange, bot_semboller, gonder, ozsermaye, executor=None) -> None:
    """on_candle_close'tan çağrılır. YALNIZ TREND_MODE=sinyal iken ve bir 4h kapanışında (1h mumu
    saat%4==3) bir kez arka plan görevi başlatır; hatalar loglanır, bot akışını ASLA bozmaz."""
    global _son_tetik
    if not AKTIF:
        return
    try:
        if son_mum_acilis.hour % 4 != 3:
            return
        anahtar = int(son_mum_acilis.timestamp())
        if _son_tetik == anahtar:
            return
        _son_tetik = anahtar

        async def _gorev():
            await asyncio.sleep(45)            # borsanın 4h mumu kesinleşsin
            try:
                await _calistir(exchange, bot_semboller, gonder, ozsermaye, executor)
            except Exception as e:
                logger.error("trend sinyal turu hatası: %s", e, exc_info=True)

        g = asyncio.get_running_loop().create_task(_gorev())
        _gorevler.add(g)
        g.add_done_callback(_gorevler.discard)
    except Exception as e:
        logger.error("trend tetikleme hatası: %s", e)
