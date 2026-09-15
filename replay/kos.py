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

BITTI = "__replay_kurulum_bitti__"


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
    os.environ.update(CANLI_ENV)
    os.environ.update({
        "PAPER_MODE": "true", "DRY_RUN": "false",
        "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": "",
        "NTFY_TOPIC": "", "WEB_DASHBOARD": "false",
        "DB_PATH": os.environ.get("REPLAY_DB", "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/replay_trades.db"),
    })
    if coinler:
        os.environ["SYMBOLS"] = ",".join(coinler)


async def kur(baslangic, coinler=None, source="local", env_ek=None):
    """main()'i kurulum bitene kadar koşturur. Döner: (main_modulu, saat, feed)."""
    from replay.saat import SanalSaat, sanal_datetime
    from replay.besleme import ReplayFeed

    _ortam(coinler)
    if env_ek: os.environ.update(env_ek)
    if os.path.exists("/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/replay_trades.db"): os.remove("/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/replay_trades.db")

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
    for mod in (M, E, R, data_mod):
        if hasattr(mod, "datetime"): mod.datetime = SD

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
    if "f" not in feed_kutu and "hata" not in feed_kutu and getattr(M, "exchange", None) is not None:
        # symbol_ctxs main()'in GERCEKTEN kurdugu semboller — en guvenilir kaynak
        semb = list(M.symbol_ctxs.keys()) or list(M.config.exchange.symbols or [])
        f = ReplayFeed(saat, semb, source=source)
        _asil_set(M.exchange, f)
        feed_kutu["f"] = f

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
    import time as _t
    from data import DataManager
    DataManager.staleness_seconds = lambda self: 0.0
    DataManager.price_age_seconds = lambda self: 0.0

    ctxs = M.symbol_ctxs
    tf = M.config.strategy.primary_tf
    ctf = M.config.strategy.confirm_tf
    SN = {"1m":60,"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400,"1d":86400}
    sn = SN[tf]

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

    n = 0
    for ns, sym in olay:
        t = pd.Timestamp(ns, tz="UTC")
        saat.ayarla((t + pd.Timedelta(seconds=sn)).to_pydatetime())
        ctx = ctxs[sym]
        dm = ctx.data_mgr
        try:
            px = await feed.get_current_price(sym)
            dm._current_price = px
            dm._last_price_ts = _t.monotonic()
            if hasattr(M.exchange, "update_price"):
                await M.exchange.update_price(px, sym)
            if hasattr(M.exchange, "check_sl_tp_tick"):
                await M.exchange.check_sl_tp_tick(sym, px)
            await dm._poll_once(ctf)          # 4h ONCE (donchian onu okuyor)
            await dm._poll_once(tf)           # 1h → on_candle_close tetikler
        except Exception as e:
            print(f"    ⚠ {t} {sym}: {type(e).__name__}: {e}")
        n += 1
        if ilerleme_her and n % ilerleme_her == 0:
            b = await M.exchange.get_balance()
            print(f"    {t.date()} · {n}/{len(olay)} · bakiye ${b:,.2f} · "
                  f"acik {len(M.portfolio.get_open_positions())}")
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
