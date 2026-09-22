"""
REPLAY sürücüsü — main()'i KURAR, sonra mumları elle sürer.

NEDEN BÖYLE: main() sonsuz döngülerle (poll 30sn, mutabakat 120sn, heartbeat
300sn) çalışıyor. 3.3 yılı o döngülerle oynatmak milyonlarca boş iterasyon
demek. Onun yerine: main()'in KURULUMUNU aynen çalıştırıp (tüm nesneler
modül-global: exchange/executor/portfolio/symbol_ctxs/...), sonra her tarihsel
mum için `main.on_candle_close` handler'ını ÇAĞIRIYORUZ — poll döngüsünün
yapacağı şeyin tam olarak kendisi.

Yani KARAR YOLU gerçek botun kendisi: aynı strateji sınıfları, aynı
ExecutionEngine, aynı RiskManager, aynı kapılar, aynı PaperExchange dolumları.
Simüle edilen tek şey mumun HABER VERİLME biçimi.

NEDENSELLİK: ReplayFeed saatten sonra kapanan mumu SERVİS ETMEZ. Handler
çağrılmadan önce saat o mumun KAPANIŞINA ayarlanır — yani handler tam olarak
canlıda göreceği bilgiyi görür.
"""
from __future__ import annotations
import asyncio, os, sys, contextlib
from datetime import timezone
import pandas as pd

from . import db_yolu as _db

BITTI = "__ikiz_kurulum_bitti__"


class _Dur(Exception):
    """main()'i kurulum bittiği anda durdurmak için."""


async def _kurulumda_dur(*a, **k):
    raise _Dur(BITTI)


# CANLI .env (VPS /opt/bot2/.env, 2026-09-14 okundu) — yerelde .env YOK, o yüzden
# canlı değerler BURADA açıkça veriliyor. Bir tanesi bile yanlışsa replay canlıyı
# taklit etmez; bu blok `ayar_dogrula.py` ile karşılaştırılmalı.
CANLI_ENV = {
    "SYMBOLS": "SOL,ETH,ADA,NEAR,BCH,ICP,BNB,XRP,DOGE,TRX,XLM,LTC",
    "DONCHIAN_SYMBOLS": "SOL,ETH,ADA,NEAR,BCH,ICP,BNB",
    "BB_SYMBOLS": "LTC",
    # ⚠ 2026-09-15'te EKSİK oldukları ölçüldü: yokken kod varsayılanlarına
    # düşülüyordu (squeeze → BTC+SOL yani yalnız SOL, BB → hafta içi de açık).
    # Sonuç: squeeze 404 yerine 98, mean_rev 175 yerine 482 işlem.
    "SQUEEZE_SYMBOLS": "XRP,DOGE,TRX,XLM",
    "BB_WEEKDAY_ENABLED": "false",
    "MAX_POSITIONS": "7", "POSITION_CAP_FRACTION": "1.5",
    "MAX_RISK_PCT": "0.02", "RISK_SCALE": "1.4",
    "DAILY_MAX_LOSS_PCT": "0.35", "LEVERAGE": "10",
    "CONSECUTIVE_LOSS_LIMIT": "2", "COOLDOWN_MINUTES": "240",
    "DONCHIAN_MTF": "true", "STOP_MOVE_ENABLED": "true",
    "MAKER_ENTRY": "true", "DONCHIAN_MAKER_ENTRY": "false",   # 2026-09-14 market girişe geçildi
    "ORB_ENABLED": "false", "FVG_ENABLED": "false",
    "SR_BREAKOUT_ENABLED": "false", "IFVG_ENABLED": "false",
    "ASIA_BO_ENABLED": "false", "WHALE_ENABLED": "false",
}


def _ortam(coinler):
    """Ortamı kur.

    EN SAĞLAM YOL: gerçek `.env` dosyasını çalışma dizinine koymak. config.py
    `load_dotenv()` ile onu okur ve ELLE YAZILMIŞ LİSTEYE GEREK KALMAZ.
    (2026-09-15 dersi: elle yazdığım listede SQUEEZE_SYMBOLS ve
    BB_WEEKDAY_ENABLED eksikti; kod varsayılanlarına düşüldü ve kol dağılımı
    bozuldu. Elle kopyalanan konfigürasyon er geç eksik kalır.)

    `.env` yoksa CANLI_ENV yedeği kullanılır — ama eksik olabileceği UYARILIR."""
    gercek = os.path.exists(os.path.join(os.getcwd(), ".env"))
    if gercek:
        print("  konfigürasyon: GERÇEK .env dosyası bulundu ve kullanılacak ✓")
    else:
        print("  ⚠ konfigürasyon: .env YOK → elle yazılmış CANLI_ENV yedeği.")
        print("    Tam sadakat için VPS'teki .env'i bu klasöre kopyala.")
        # ⚠ update() DEĞİL, setdefault(). update() ÇAĞIRANIN verdiği değeri
        # EZİYORDU: ikiz_paralel.py dört alt sürece RISK_SCALE 1.00/1.40/
        # 1.75/2.00 gönderiyordu, bu satır dördünü de 1.4'e çeviriyordu ve
        # tarama SESSİZCE aynı koşuyu dört kez yapıyordu (2026-09-19: dört
        # satır da 1778 işlem / +0.1581 / MAR 3.29 çıktı, 5 saat boşa gitti).
        # CANLI_ENV bir YEDEK; zaten verilmiş bir değişkene dokunmamalı.
        for _k, _v in CANLI_ENV.items():
            os.environ.setdefault(_k, _v)
    os.environ.update({
        # ⚠ CANLI NETTED KISITI ZORLANIR. MEXC one-way modda bir coin = BIR net
        # pozisyon; uretim muhafizi eskiden yalnizca canlida calisiyordu ve
        # IKIZ kagit modda kostugu icin o kisit BACKTEST'TE YOKTU.
        "ONE_PER_SYMBOL": "true",
        "PAPER_MODE": "true", "DRY_RUN": "false",
        "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": "",
        "NTFY_TOPIC": "", "WEB_DASHBOARD": "false",
        "DB_PATH": _db(),
    })
    if coinler:
        os.environ["SYMBOLS"] = ",".join(coinler)

    # ⚠ KOŞU KENDİ AYARINI BİLDİRSİN. Yukarıdaki hata SESSİZ olduğu için
    # 5 saat sürdü: tablo geldi, dört satır aynıydı, sebebi ancak sonradan
    # anlaşıldı. Artık her koşu hangi ayarla koştuğunu BAŞTA yazıyor.
    # ⚠ SABIT LISTE YETMEZ. Once yalniz risk ayarlari yaziliyordu; geri-verme
    # taramasi TRAILING_ATR_MULT / BREAKEVEN_ATR_MULT / DONCHIAN_RR gibi
    # anahtarlari degistirince dokuz kosunun satiri AYNI gorundu ve "tum
    # kosular ayni ayarda" YANLIS ALARMI verdi (2026-09-20). Kosucu hangi
    # anahtarlari taradigini IKIZ_IZLE ile bildiriyor; onlar da yaziliyor.
    _izle = ["RISK_SCALE", "MAX_RISK_PCT", "MAX_POSITIONS",
             "POSITION_CAP_FRACTION", "DAILY_MAX_LOSS_PCT", "LEVERAGE"]
    for _k in os.environ.get("IKIZ_IZLE", "").split(","):
        _k = _k.strip()
        if _k and _k not in _izle:
            _izle.append(_k)
    print("  ETKİN AYAR · " + " · ".join(
        f"{k}={os.environ.get(k, '(yok)')}" for k in _izle))
    print(f"  veritabanı: {os.environ['DB_PATH']}")


async def kur(baslangic, coinler=None, source="local", env_ek=None):
    """main()'i kurulum bitene kadar koşturur. Döner: (main_modulu, saat, feed)."""
    from ikiz.saat import SanalSaat, sanal_datetime
    from ikiz.besleme import ReplayFeed

    # Kurulumda `PaperExchange: rest_exchange not set` / `Failed to load initial
    # candles` uyarilari BEKLENEN: besleme main() offline moda dustukten SONRA
    # takiliyor. Ekrani kirletmesinler; gercek hatalar gorunur kalsin.
    import logging as _lg
    _susturulan = {}
    for _ad in ("data", "ccxt", "aiosqlite", "asyncio"):
        _lgr = _lg.getLogger(_ad); _susturulan[_ad] = _lgr.level
        _lgr.setLevel(_lg.CRITICAL)

    _ortam(coinler)
    if env_ek: os.environ.update(env_ek)
    _y = _db()
    _d = os.path.dirname(_y)
    if _d: os.makedirs(_d, exist_ok=True)
    # ⚠ WAL ve SHM DE SILINMELI. database.py `PRAGMA journal_mode=WAL` kullanıyor;
    # yalnız .db silinince bir sonraki koşu BAYAT -wal dosyasını miras alıyor ve
    # SQLite "database or disk is full" veriyor (Windows) / "disk I/O error"
    # (Linux). İşlemler sessizce yazılamıyor.
    # ⚠ SILME, YEDEKLE. Eski surum dosyayi DOGRUDAN siliyordu; bir tarama
    # baslatilip bitmeden kapatilirsa onceki kosunun sonucu yerine YENISI
    # KONMADAN yok oluyordu. 2026-09-20'de tam bu oldu: dort dusuk-risk
    # veritabani (1778'er islem) 28 KB bos semaya dondu, cunku F_DUSUK_TARAMA
    # baslatilip erken kapatilmisti. Simdi son saglam kosu bir nesil saklaniyor.
    _yedek = (_y[:-3] if _y.endswith(".db") else _y) + ".yedek.db"
    for _ek in ("", "-wal", "-shm"):
        if os.path.exists(_yedek + _ek):
            try: os.remove(_yedek + _ek)
            except OSError: pass
    for _ek in ("", "-wal", "-shm"):
        if os.path.exists(_y + _ek):
            try: os.replace(_y + _ek, _yedek + _ek)
            except OSError:
                try: os.remove(_y + _ek)
                except OSError: pass

    # ⚠ ÜRETİM KUSURU TELAFİSİ (exchange.py'ye DOKUNULMADAN):
    # execution.py maker limit emrini `timeout=` ve `poll=` ile çağırıyor
    # (LiveExchange.place_limit_order bunları alıyor, satır 1006-1010) ama
    # PaperExchange.place_limit_order ALMIYOR (satır 204-207). Sonuç: PAPER
    # MODDA maker girişi olan HER kol TypeError alıp sessizce düşüyor
    # ("BB skipped: got an unexpected keyword argument 'timeout'").
    # Bu canlıyı etkilemez ama paper demo koşuları eksik çalışıyor demektir.
    # İkiz'de sadakat için parametreleri YUTAN bir sarmalayıcı takılır;
    # üretim dosyası değiştirilmez.
    import exchange as _X
    if "timeout" not in _X.PaperExchange.place_limit_order.__code__.co_varnames:
        _asil_limit = _X.PaperExchange.place_limit_order
        async def _limit_shim(self, symbol, side, amount, limit_price, params,
                              timeout=45.0, poll=3.0, fallback_market=True):
            return await _asil_limit(self, symbol, side, amount, limit_price,
                                     params, fallback_market=fallback_market)
        _X.PaperExchange.place_limit_order = _limit_shim

    import data as data_mod
    saat = SanalSaat(pd.Timestamp(baslangic, tz="UTC").to_pydatetime())
    SD = sanal_datetime(saat)

    # ccxt.pro'yu SAHTE modulle degistir: gercek MEXC'e baglanmasin. main()
    # except dalina duser ve "offline mode" der; feed'i biz elle takariz.
    import types
    sahte = types.ModuleType("ccxt.pro")
    def _yok(*a, **k): raise RuntimeError("replay: ag erisimi kapali")
    sahte.mexc = _yok
    sys.modules["ccxt.pro"] = sahte

    import main as M
    import execution as E, risk as R

    # ⚠ ZAMANI SANALLAŞTIRMA — TEK TEK MODÜL SAYMA.
    # İlk sürümde main/execution/risk/data sayılmıştı ve portfolio.py atlanmıştı;
    # sonuç: `entry_time` GERÇEK tarihten (2026), karşılaştırma SANAL tarihten
    # (2023) geliyordu → yaş negatif → MAX-HOLD ÇIKIŞI HİÇ TETİKLENMEDİ.
    # Ankorda max_hold çıkışları işlemlerin %23'ü ve KÂRLI (+0.56R); yokluğunda
    # o pozisyonlar stoplarına kadar gidiyordu (ort R −0.17, kazanma %29).
    # Artık: yüklü TÜM proje modülleri taranır. İleride eklenen modül de kapsanır.
    import os as _os, sys as _sys
    _kok = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    _yamali = []
    for _ad, _m in list(_sys.modules.items()):
        if _m is None or _ad.startswith("ikiz"): continue
        _dosya = getattr(_m, "__file__", None)
        if not _dosya or not _os.path.abspath(_dosya).startswith(_kok): continue
        if isinstance(getattr(_m, "datetime", None), type):
            _m.datetime = SD; _yamali.append(_ad)
    print(f"  sanal saat: {len(_yamali)} modül yamalandı → {sorted(_yamali)}")

    def _saati_yay():
        """main() importlarını tetikledikten SONRA tekrar tara (portfolio,
        database, signal_combiner gibi geç yüklenen modüller için)."""
        yeni_ = []
        for ad_, m_ in list(_sys.modules.items()):
            if m_ is None or ad_.startswith("ikiz"): continue
            d_ = getattr(m_, "__file__", None)
            if not d_ or not _os.path.abspath(d_).startswith(_kok): continue
            dt_ = getattr(m_, "datetime", None)
            if isinstance(dt_, type) and dt_ is not SD:
                m_.datetime = SD; yeni_.append(ad_)
        if yeni_: print(f"  sanal saat (2. tur): {sorted(yeni_)}")
    _saati_yay()

    # feed'i PaperExchange'e taktırmak için: main set_rest_exchange(rest_ex) çağırıyor.
    # O çağrının argümanını BİZİMKİYLE değiştiriyoruz.
    feed_kutu = {}
    import exchange as X
    _asil_set = X.PaperExchange.set_rest_exchange
    def _yakala(self, ex):
        # ⚠ main() bu çağrıyı try/except içinde yapıyor; burada bir istisna
        # SESSİZCE "MEXC'e bağlanamadı" diye yutulur. O yüzden hatayı KUTUYA
        # yazıyoruz ki kur() sonunda görünür olsun.
        try:
            semboller = list(M.config.exchange.symbols or [])
            f = ReplayFeed(saat, semboller, source=source)
            feed_kutu["f"] = f
            _asil_set(self, f)
        except Exception as e:
            feed_kutu["hata"] = f"{type(e).__name__}: {e}"
            raise
    X.PaperExchange.set_rest_exchange = _yakala

    # ⚠ CANLI EKRANI (Rich Live) KAPAT: monitor.Dashboard.start() terminali ele
    # geçiriyor ve İkiz'in sonuç satırları onun altında kalıyor ("burada durdu
    # sanırım" — aslında bitmişti). Replay'de görsel panel gereksiz; kapatmak
    # karar mantığına DOKUNMAZ, yalnız çizimi engeller.
    try:
        import monitor as _mon
        _mon.Dashboard.start = lambda self: None
        _mon.Dashboard.stop = lambda self: None
    except Exception:
        pass

    # kurulum biter bitmez dur: start_feeds ilk çağrıldığında
    _asil_start = data_mod.DataManager.start_feeds
    data_mod.DataManager.start_feeds = _kurulumda_dur

    try:
        await M.main()
    except _Dur:
        pass
    finally:
        X.PaperExchange.set_rest_exchange = _asil_set
        data_mod.DataManager.start_feeds = _asil_start

    # offline moda dusulduyse feed hic takilmamis olur → ELLE tak
    _saati_yay()   # main() sirasinda gec yuklenen moduller icin son tur

    if "f" not in feed_kutu and "hata" not in feed_kutu and getattr(M, "exchange", None) is not None:
        # symbol_ctxs main()'in GERCEKTEN kurdugu semboller — en guvenilir kaynak
        semb = list(M.symbol_ctxs.keys()) or list(M.config.exchange.symbols or [])
        f = ReplayFeed(saat, semb, source=source)
        _asil_set(M.exchange, f)
        feed_kutu["f"] = f

    for _ad, _lv in _susturulan.items():
        _lg.getLogger(_ad).setLevel(_lv)

    if "f" not in feed_kutu:
        h = feed_kutu.get("hata", "set_rest_exchange hiç çağrılmadı")
        raise RuntimeError(f"ReplayFeed takılamadı → {h}")
    return M, saat, feed_kutu["f"]


async def sur(M, saat, feed, bitis=None, ilerleme_her=2000):
    """Tarihsel mumları sırayla sürer — canlı `start_feeds`'in yaptığının aynısı.

    start_feeds ÜÇ döngü başlatır (data.py:172): ticker, poll(primary_tf),
    poll(confirm_tf). Sürücü her mumda üçünü de elle yapar:
      1) saat o mumun KAPANIŞINA ayarlanır (handler geleceği göremez)
      2) ticker fiyatı tazelenir (_current_price + _last_price_ts)
      3) primary_tf ve confirm_tf tamponları _poll_once ile beslenir → callback

    ⚠ BAYATLIK MUHAFIZI DEVRE DIŞI: `staleness_seconds()` ve `price_age_seconds()`
    GERÇEK duvar saatini kullanıyor (data.py:306 `import time`), mumlar ise
    geçmişten. Replay'de bu ölçüm anlamsız büyür ve main.py:236'daki giriş kapısı
    HER mumu reddeder (ilk denemede sıfır işlem çıkmasının sebebi buydu).
    Muhafızın amacı ÖLÜ BESLEME yakalamak; replay'de besleme yapısal olarak taze,
    o yüzden 0 döndürmek SADIK olan davranıştır.
    """
    # RUTIN gurultuyu ele, GERCEK uyarilari birak. "BB skipped: regime=..." her
    # mumda her coin icin basiliyor ve ilerleme cubugunu bozuyor; ama
    # "Trading halted (Daily loss limit reached)" gibi satirlar TESHIS icin
    # kritik (125-gun hatasini o satir ele vermisti) — onlar korunuyor.
    import logging as _lg

    class _Gurultu(_lg.Filter):
        _ELE = ("BB skipped: regime=", "skipped: Slot", "already occupied",
                "BB skipped: low volume", "Donchian skipped: Slot")
        def filter(self, kayit):
            m = kayit.getMessage()
            return not any(x in m for x in self._ELE)

    _f = _Gurultu()
    for _ad in ("main", "execution"):
        _lg.getLogger(_ad).addFilter(_f)

    import time as _t
    _bas = _t.time()

    def _dk(sn):
        sn = max(0, int(sn))
        return f"{sn//60}dk {sn%60:02d}sn" if sn < 3600 else f"{sn//3600}sa {(sn%3600)//60:02d}dk"

    from data import DataManager
    DataManager.staleness_seconds = lambda self: 0.0
    DataManager.price_age_seconds = lambda self: 0.0

    ctxs = M.symbol_ctxs
    tf = M.config.strategy.primary_tf
    ctf = M.config.strategy.confirm_tf
    SN = {"1m":60,"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400,"1d":86400}
    sn = SN[tf]
    _ctf_sn = SN.get(ctf, 0) if ctf != tf else 0

    bas = pd.Timestamp(saat.simdi)
    olay = []
    for sym in ctxs:
        d = feed._seri(sym, tf)
        d = d[d.index + pd.Timedelta(seconds=sn) > bas]
        if bitis is not None: d = d[d.index <= pd.Timestamp(bitis, tz="UTC")]
        for t in d.index:
            olay.append((t.value, sym))
    olay.sort()
    print(f"  {len(olay)} mum olayi · {len(ctxs)} coin · tf={tf} confirm={ctf}")

    # ⚠ GÜNLÜK SIFIRLAMA. Canlıda `daily_reset_loop` her gece yarısı
    # executor.reset_daily() çağırıyor ve o da _trading_halted.clear() yapıyor
    # (execution.py:224). Sürücü o döngüyü çalıştırmadığı için GÜNLÜK ZARAR
    # FRENİ bir kez düşünce KALICI oluyordu: 3.3 yıllık koşuda bot 125. günde
    # durup bir daha hiç işlem açmadı (93 işlem, ort R −0.17).
    # Burada sanal gün değişiminde aynı iki çağrı yapılır.
    son_gun = None
    _son_ns = None

    n = 0
    for ns, sym in olay:
        t = pd.Timestamp(ns, tz="UTC")
        saat.ayarla((t + pd.Timedelta(seconds=sn)).to_pydatetime())

        # ⚠ MUTABAKAT DONGUSU'nun karar etkisi olan parcasi: canlida
        # position_reconciliation_loop her 2 dakikada executor.enforce_daily_loss()
        # cagiriyor (main.py:1622) — gunluk zarar freni boylece POZISYON ACIKKEN de
        # tetiklenip emergency_close_all yapabiliyor. Surucu o donguyu
        # calistirmadigi icin fren yalnizca YENI GIRIS denemesinde bakiliyordu.
        # Damga basina bir kez cagiriyoruz (canliya gore seyrek ama yon ayni).
        if ns != _son_ns:
            _son_ns = ns
            try:
                await M.executor.enforce_daily_loss()
            except Exception:
                pass

        _g = saat.simdi.date()
        if son_gun is not None and _g != son_gun:
            try:
                await M.executor.capture_daily_start()
                M.executor.reset_daily()
            except Exception as _e:
                print(f"    ⚠ günlük sıfırlama: {type(_e).__name__}: {_e}")
        son_gun = _g
        ctx = ctxs[sym]
        dm = ctx.data_mgr
        try:
            px = await feed.get_current_price(sym)
            dm._current_price = px
            dm._last_price_ts = _t.monotonic()
            if hasattr(M.exchange, "update_price"):
                await M.exchange.update_price(px, sym)
            # ⚠ check_sl_tp_tick BILEREK CAGRILMIYOR (2026-09-20).
            # Canlida o kontrol saniyede bir GERCEK tick'le calisiyor. Replay'de
            # elimizdeki tek fiyat mumun KAPANISI; onunla cagirmak, AYNI mumun
            # high/low kontrolunden ONCE calisiyordu. Sonuc: fitille stop'a
            # degip kapanista hedefi gecen bir mum HEDEF yaziyordu -- canlida
            # MEXC'in stop-market'i fitilde tetiklenir ve ZARAR yazilir.
            # Dogru kontrol zaten uretim kodunda: main.py:205
            # check_sl_tp(candle.high, candle.low) -- mum ici dokunuslari
            # yakaliyor ve kapanis da [low, high] araliginda oldugu icin
            # tick kontrolu ZATEN GEREKSIZ.
            # ⚠ 4h poll'u SEYRELTMEYİ DENEDİM, GERİ ALDIM (2026-09-15).
            # "Çağrıların %75'i boşa gidiyor, seyreltmek risksiz" demiştim —
            # ÖLÇÜM ÇÜRÜTTÜ: 16 işlem → 11 işlem, bakiye değişti. Sebep: 4h
            # tamponu İLK beslendiğinde 49 mumu birden alıyor; seyrek çağırınca
            # o ilk dolum farklı anda oluyor, donchian'ın analiz ettiği ilk 4h
            # bar kayıyor ve diziler oradan ayrışıyor.
            # Ayrıca CANLIDA o poll döngüsü 30 SANİYEDE BİR çalışıyor → sık
            # çağırmak canlıya daha sadık. Hız için sadakat feda edilmez.
            await dm._poll_once(ctf)          # 4h ONCE (donchian onu okuyor)
            await dm._poll_once(tf)           # 1h → on_candle_close tetikler
        except Exception as e:
            print(f"    ⚠ {t} {sym}: {type(e).__name__}: {e}")
        n += 1
        if n % 500 == 0 or n == len(olay):
            _gecen = _t.time() - _bas
            _oran = n / len(olay)
            _kalan = (_gecen / _oran - _gecen) if _oran > 0 else 0
            _dolu = int(_oran * 28)
            _cubuk = "█" * _dolu + "░" * (28 - _dolu)
            b = await M.exchange.get_balance()
            _ap = len(M.portfolio.get_open_positions())
            sys.stdout.write(
                f"\r  [{_cubuk}] %{_oran*100:5.1f}  {t.date()}  "
                f"{n//1000}k/{len(olay)//1000}k  "
                f"gecen {_dk(_gecen)}  kalan ~{_dk(_kalan)}  "
                f"${b:,.0f}  acik {_ap}   ")
            sys.stdout.flush()

    sys.stdout.write("\n"); sys.stdout.flush()

    # ⚠ WAL → ANA DOSYA. Sürücü main()'i aniden durdurduğu için bağlantı düzgün
    # kapanmıyor ve SQLite hiç checkpoint yapmıyor: işlemler .db'de değil
    # -wal dosyasında kalıyor (ölçüldü: .db 12 KB, -wal 264 KB). Okuyucu da
    # "1 işlem" görüyordu. Koşu bitince açıkça aktar.
    # ⚠ TRUNCATE kipi WAL dosyasını sıfırlamak için TAM kilit ister; koşu
    # sonunda hâlâ açık bir okuyucu varsa "database table is locked" verip
    # HİÇBİR ŞEY aktarmıyor (2026-09-19'da dört koşuda da oldu). PASSIVE kipi
    # kilit beklemez, elinden geldiği kadarını aktarır — veri güvenliği için
    # yeterli. Önce TRUNCATE dene, olmazsa PASSIVE'e düş.
    for _kip in ("TRUNCATE", "PASSIVE"):
        try:
            await M.db._db.execute(f"PRAGMA wal_checkpoint({_kip})")
            await M.db._db.commit()
            print(f"  WAL → ana veritabanına aktarıldı ({_kip})")
            break
        except Exception as _e:
            print(f"  ⚠ WAL aktarımı ({_kip}) başarısız: {_e}")

    # ⚠ BAGLANTIYI KAPAT — yoksa islemler KALICI OLARAK KAYBOLABILIR.
    # Surucu sonunda os._exit(0) var (aiosqlite'in daemon olmayan thread'i
    # yuzunden surec aksi halde hic cikmiyor). Ama sert cikis SQLite'in kapanis
    # yordamini da atliyor: TRUNCATE kilitlenip PASSIVE'e dustuyse -- ki dort
    # kosuda dustu -- PASSIVE kilit beklemedigi icin HIC aktarmamis olabilir ve
    # islemler yalnizca -wal dosyasinda kalir. 2026-09-20: dort dusuk-risk
    # veritabani boyle bosaldi (ozet 1778 islem gordu, bir sonraki arac 0).
    # close() son bir checkpoint yapar, -wal'i ana dosyaya yedirir ve siler.
    # ⚠ MOTOR PARMAK IZI. Farkli motor surumlerinin sonuclari YAN YANA
    # KONULAMAZ: 2026-09-20'de gelecek sizintisi duzeltilince taban 1778
    # islem/+0.1581'den 1752/+0.1675'e tasindi. Ama eski kosularin .db
    # dosyalari klasorde duruyor ve ozet tablosu hepsini tek listede
    # basiyordu -- eski bir satirin "en iyi" cikmasi mumkundu. Her kosu artik
    # kendi kod surumunu yaziyor; rapor farkli surumleri AYIRIYOR.
    try:
        import hashlib as _h
        _kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _oz = _h.sha256()
        for _d in ("ikiz/besleme.py", "ikiz/kos.py", "ikiz/saat.py", "main.py",
                   "execution.py", "exchange.py", "indicators.py", "data.py",
                   "portfolio.py", "config.py", "strategies/donchian.py",
                   "strategies/mean_reversion.py", "strategies/squeeze.py"):
            try:
                with open(os.path.join(_kok, _d), "rb") as _f:
                    _oz.update(_f.read())
            except OSError:
                _oz.update(b"?")
        await M.db.set_meta("motor_surum", _oz.hexdigest()[:12])
        # ⚠ MALIYET AYARI DA DAMGALANIR. Farkli surtunme ayarlariyla kosmus
        # konfigurasyonlar KARSILASTIRILAMAZ: maliyetsiz bir tabana gore
        # maliyetli her kosu "kotu" cikar ve hukum YANILTICI olur
        # (2026-09-21 maliyet taramasinda tam bu oldu). Rapor bu damgaya gore
        # GRUPLAYIP grup ICINDE karsilastirir.
        _mal = "|".join(f"{k}={os.environ.get(k, '')}" for k in (
            "PAPER_SLIP_GIRIS_BP", "PAPER_SLIP_CIKIS_BP",
            "PAPER_MAKER_DOLUM", "PAPER_FUNDING", "DONCHIAN_MAKER_ENTRY"))
        await M.db.set_meta("maliyet_ayari", _mal)
        if os.environ.get("IKIZ_TABAN") == "1":
            await M.db.set_meta("taban", "1")
    except Exception as _e:
        print(f"  ⚠ motor surumu yazilamadi: {type(_e).__name__}: {_e}")

    try:
        await M.db.close()
        print("  veritabanı bağlantısı kapatıldı (WAL kalıcılaştı)")
    except Exception as _e:
        print(f"  ⚠ veritabanı kapatılamadı: {type(_e).__name__}: {_e}")
    return n


async def _elle_besle(ctx, tf, feed, sym, t):
    """_poll_once yoksa: feed'den çek, buffer'a koy, callback'i ateşle."""
    from data import Candle
    rows = await feed.fetch_ohlcv(sym, tf, None, 2)
    if not rows: return
    r = rows[-2] if len(rows) >= 2 else rows[-1]
    c = Candle(timestamp=r[0], open=r[1], high=r[2], low=r[3], close=r[4],
               volume=r[5], is_closed=True)
    buf = ctx.data_mgr._buffers[tf]
    if await buf.update(c):
        ctx.data_mgr._last_closed_ts[tf] = c.timestamp
        await ctx.data_mgr._fire_callbacks(tf, c)
