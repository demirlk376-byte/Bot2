"""
Sessizlik görünürlüğü — "neden işlem açılmıyor?" sorusu GÜNLÜKTEN cevaplanabilsin.

NEDEN EKLENDI (2026-09-27): canlıda 4-5 gün işlem açılmadı ve journal'da
NEDENİ yoktu. Donchian filtre gerekçeleri (DONCHIAN_VOL_MULT=2.5 → "hacim
zayif") ve squeeze rejim engeli ("block:rejim=ranging") yalnızca web paneline
gidiyordu; heartbeat de yalnız "Bot çalışıyor" diyordu.

main.py'ye eklenenler YALNIZ log + sayaçtır. Testler şunları kilitliyor:
  1. Donchian: ham kırılım filtreye takıldıysa log + sayaç; "no breakout" gibi
     KIRILIM-YOK gerekçeleri SESSİZ kalır (her 4h barda log basmasın).
     Sınıflandırma strategies/donchian.py'nin GERÇEK gerekçeleriyle sınanır.
  2. Squeeze rejim kapısı: yalnız DURUM DEĞİŞİMİNDE log (her saat her coin DEĞİL).
  3. Heartbeat özeti: saf biçimleyici, 6 gün eşiği, Telegram HTML güvenliği.
  4. Her telemetri istisnası YUTULUR — kol mantığına / emre / heartbeat'e sızmaz.
  5. Telemetri çağrılarının dönüş değeri HİÇBİR karar koşulunda kullanılmaz
     (AST ile: hepsi tek başına ifade-deyimi).

Çalıştır:  python -m pytest tests/test_sessizlik_gorunurluk.py -q
      ya da python tests/test_sessizlik_gorunurluk.py
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
import logging
import os
import re
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import main as M  # noqa: E402
from strategies.donchian import DonchianStrategy  # noqa: E402


# ── yardımcılar ──────────────────────────────────────────────────────────────

class _Yakala(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.kayitlar: list[logging.LogRecord] = []

    def emit(self, record):
        self.kayitlar.append(record)

    def info_mesajlari(self):
        return [r.getMessage() for r in self.kayitlar if r.levelno == logging.INFO]


@contextlib.contextmanager
def _log_yakala():
    lg = logging.getLogger("main")
    h = _Yakala()
    eski = lg.level
    lg.setLevel(logging.DEBUG)
    lg.addHandler(h)
    try:
        yield h
    finally:
        lg.removeHandler(h)
        lg.setLevel(eski)


@contextlib.contextmanager
def _yamala(nesne, **degerler):
    """nesne üzerindeki öznitelikleri geçici olarak değiştir, sonra geri koy."""
    yok = object()
    eski = {k: getattr(nesne, k, yok) for k in degerler}
    for k, v in degerler.items():
        setattr(nesne, k, v)
    try:
        yield
    finally:
        for k, v in eski.items():
            if v is yok:
                delattr(nesne, k)
            else:
                setattr(nesne, k, v)


def _temiz_durum():
    M._sessizlik_sayac.clear()
    M._squeeze_rejim_engelli.clear()


def _4h(close, volume=None, yayilim=0.5):
    close = np.asarray(close, dtype="float64")
    n = len(close)
    idx = pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC")
    op = np.r_[close[0], close[:-1]]
    return pd.DataFrame({
        "open": op,
        "high": np.maximum(op, close) + yayilim,
        "low": np.minimum(op, close) - yayilim,
        "close": close,
        "volume": np.full(n, 1000.0) if volume is None else np.asarray(volume, "float64"),
    }, index=idx)


def _yukari_kirilim(n=300, son_hacim=1000.0):
    """Istikrarli yukari trend (EMA200 altta) + son barda kanal ustune kapanis."""
    c = 100.0 + 0.1 * np.arange(n, dtype="float64")
    c[-1] = c[-2] + 3.0
    v = np.full(n, 1000.0)
    v[-1] = son_hacim
    return _4h(c, v)


# ── 1. Donchian sınıflandırma: GERÇEK strateji gerekçeleriyle ────────────────

def test_donch_hacim_elemesi_gercek_stratejiyle_hacim_sayilir():
    df = _yukari_kirilim(son_hacim=1000.0)          # oran 1.0x < 2.5x
    # sağlık kontrolü: filtresiz aynı bar GERÇEKTEN kırılım
    assert DonchianStrategy(vol_mult=0.0).analyze(df, 1.0).direction == 1
    sig = DonchianStrategy(vol_mult=2.5).analyze(df, 1.0)
    assert sig.direction == 0 and sig.reason.startswith("hacim zayif"), sig.reason
    assert M._donch_elenme_turu(sig.reason) == "hacim"
    # güçlü hacimle filtre geçer -> sinyal (elenme yok)
    assert DonchianStrategy(vol_mult=2.5).analyze(
        _yukari_kirilim(son_hacim=5000.0), 1.0).direction == 1


def test_donch_kirilim_yoksa_elenme_sayilmaz():
    c = 100.0 + 0.3 * np.sin(np.arange(300) / 3.0)   # yatay, kırılım yok
    sig = DonchianStrategy(vol_mult=2.5).analyze(_4h(c), 1.0)
    assert sig.direction == 0 and sig.reason.startswith("no breakout"), sig.reason
    assert M._donch_elenme_turu(sig.reason) is None
    # veri yetersiz / ATR yok da kırılım-yok sayılır
    assert M._donch_elenme_turu(
        DonchianStrategy().analyze(_4h(np.ones(50)), 1.0).reason) is None
    assert M._donch_elenme_turu(
        DonchianStrategy().analyze(_yukari_kirilim(), 0.0).reason) is None


def test_donch_ema200_ve_chase_diger_sayilir():
    # uzun düşüş, dipte yatay kanal, kanal üstüne kapanış AMA EMA200'ün altında
    c = np.r_[200.0 - 0.3 * np.arange(250), np.full(49, 125.0), [128.0]]
    sig = DonchianStrategy().analyze(_4h(c), 1.0)
    assert sig.direction == 0 and sig.reason == "EMA200 trend hizasi yok", sig.reason
    assert M._donch_elenme_turu(sig.reason) == "diger"
    # chase: seviyeden çok uzak kapanış
    sig = DonchianStrategy(chase_atr=0.5).analyze(_yukari_kirilim(), 1.0)
    assert sig.direction == 0 and sig.reason.startswith("cok uzak"), sig.reason
    assert M._donch_elenme_turu(sig.reason) == "diger"


def test_donch_gerekce_listesi_kaynakla_uyumlu():
    """strategies/donchian.py'deki HER gerekçe metni sınıflandırılmış olmalı.
    Yeni bir gerekçe eklenirse bu test düşer: main._DONCH_KIRILIM_YOK'a mı
    (kırılım yoktu) yoksa elenme mi olduğuna KARAR VER."""
    src = (KOK / "strategies" / "donchian.py").read_text(encoding="utf-8")
    filtre = re.findall(r'return False, f?"([^"]*)"', src)
    assert len(filtre) >= 15, filtre
    for r in filtre:
        assert M._donch_elenme_turu(r) is not None, f"filtre gerekçesi sayılmıyor: {r!r}"
    erken = (re.findall(r'DonchianSignal\(0, 0\.0, f?"([^"]*)"', src)
             + re.findall(r'son_sebep = f?"([^"]*)"', src))
    beklenen_elenme = ("EMA200 trend hizasi yok", "retest yok", "teyit yok")
    for r in erken:
        if r.startswith(beklenen_elenme):
            assert M._donch_elenme_turu(r) == "diger", r
        else:
            assert M._donch_elenme_turu(r) is None, \
                f"bilinmeyen Donchian gerekçesi {r!r} — sınıflandır"


# ── 2. Donchian log + sayaç ─────────────────────────────────────────────────

def test_donch_elenme_kaydet_loglar_ve_sayar():
    _temiz_durum()
    with _log_yakala() as h:
        M._donch_elenme_kaydet("SOL/USDT:USDT", "hacim zayif (1.20x < 2.50x)")
        M._donch_elenme_kaydet("SOL/USDT:USDT", "no breakout (close 150)")
        M._donch_elenme_kaydet("ETH/USDT:USDT", "insufficient data (40 < 200)")
        M._donch_elenme_kaydet("ETH/USDT:USDT", "EMA200 trend hizasi yok")
    info = h.info_mesajlari()
    assert info == ["[SOL/USDT:USDT] Donchian elendi: hacim zayif (1.20x < 2.50x)",
                    "[ETH/USDT:USDT] Donchian elendi: EMA200 trend hizasi yok"], info
    assert M._sessizlik_sayac == {"donch_hacim": 1, "donch_diger": 1}
    _temiz_durum()


# ── 3. Squeeze rejim kapısı: yalnız durum değişiminde log ───────────────────

class _SahteSqueeze:
    def __init__(self, yon=0, patla=False):
        self.yon, self.patla, self.cagri = yon, patla, 0

    def analyze(self, df, atr_val):
        self.cagri += 1
        if self.patla:
            raise RuntimeError("gölge analiz patladı")
        return types.SimpleNamespace(direction=self.yon, reason=f"sahte yon={self.yon}")


def _ctx(sym="XRP/USDT:USDT", **k):
    return types.SimpleNamespace(symbol=sym, squeeze_strategy=_SahteSqueeze(**k))


def test_squeeze_rejim_yalniz_durum_degisiminde_loglar():
    _temiz_durum()
    ctx = _ctx()
    with _log_yakala() as h:
        # ilk görülen AÇIK durum sessiz (varsayılan açık kabul edilir)
        M._squeeze_rejim_acik(ctx.symbol, "neutral", 24.0)
        for _ in range(5):                       # 5 saat üst üste engelli
            M._squeeze_rejim_engel(ctx, "ranging", 17.0, None, 1.0)
        M._squeeze_rejim_acik(ctx.symbol, "neutral", 22.0)
        M._squeeze_rejim_acik(ctx.symbol, "trending", 30.0)
        M._squeeze_rejim_engel(ctx, "ranging", 18.5, None, 1.0)
    info = h.info_mesajlari()
    assert len(info) == 3, info
    assert "ENGELLİ" in info[0] and "rejim=ranging" in info[0] and "ADX=17.0" in info[0]
    assert "AÇILDI" in info[1] and "ADX=22.0" in info[1]
    assert "ENGELLİ" in info[2]
    assert M._sessizlik_sayac.get("squeeze_rejim") == 6
    assert "squeeze_rejim_sinyal" not in M._sessizlik_sayac
    assert ctx.squeeze_strategy.cagri == 6        # gölge analiz her engelde
    _temiz_durum()


def test_squeeze_golge_sinyal_engellenince_loglanir_ve_sayilir():
    _temiz_durum()
    ctx = _ctx(yon=1)
    with _log_yakala() as h:
        M._squeeze_rejim_engel(ctx, "ranging", 15.0, None, 1.0)
        M._squeeze_rejim_engel(ctx, "ranging", 15.5, None, 1.0)
    info = h.info_mesajlari()
    takildi = [m for m in info if "rejim kapısına takıldı" in m]
    assert len(takildi) == 2 and "sahte yon=1" in takildi[0], info
    assert M._sessizlik_sayac["squeeze_rejim_sinyal"] == 2
    assert M._sessizlik_sayac["squeeze_rejim"] == 2
    _temiz_durum()


def test_squeeze_coinler_bagimsiz():
    _temiz_durum()
    a, b = _ctx("XRP/USDT:USDT"), _ctx("DOGE/USDT:USDT")
    with _log_yakala() as h:
        M._squeeze_rejim_engel(a, "ranging", 17.0, None, 1.0)
        M._squeeze_rejim_engel(b, "ranging", 16.0, None, 1.0)
        M._squeeze_rejim_engel(a, "ranging", 17.0, None, 1.0)
        M._squeeze_rejim_engel(b, "ranging", 16.0, None, 1.0)
    assert len(h.info_mesajlari()) == 2
    _temiz_durum()


# ── 4. Heartbeat özeti biçimi ────────────────────────────────────────────────

def test_ozet_bicimi_ve_sayaclar():
    s = {"donch_analiz": 42, "donch_hacim": 3, "donch_mtf": 1, "donch_diger": 2,
         "squeeze_rejim": 12, "squeeze_rejim_sinyal": 1, "bb_engel": 4,
         "yurutme_engel": 0}
    o = M._sessizlik_ozeti_bicimle(s, 5 * 86400 + 3 * 3600, 6.0)
    assert o.startswith("Sessizlik (son 6sa): son giriş 5g 3sa önce"), o
    assert "Donch 4h analiz 42, elenen kırılım: hacim 3 / MTF 1 / diğer 2" in o
    assert "Squeeze rejim engeli 12 (engellenen sinyal 1)" in o
    assert "BB engel 4" in o and "yürütme engeli 0" in o
    assert "4h bayat" not in o                      # sıfırsa gösterilmez
    assert "\n" not in o and "saglik_kaniti" not in o   # 6 günden az: ipucu yok
    # Telegram HTML modunda gidiyor: etiket bozacak karakter OLMAMALI
    for kotu in "<>&":
        assert kotu not in o


def test_ozet_bos_sayac_ve_bilinmeyen_son_giris():
    o = M._sessizlik_ozeti_bicimle({}, None, None)
    assert o.startswith("Sessizlik: Donch 4h analiz 0"), o
    assert "son giriş" not in o and "saglik_kaniti" not in o
    assert "hacim 0 / MTF 0 / diğer 0" in o
    o = M._sessizlik_ozeti_bicimle({"donch_4h_bayat": 2, "donch_hacim": "x"}, None)
    assert "4h bayat 2" in o and "hacim 0" in o     # bozuk değer 0 sayılır


def test_ozet_6_gun_esigi():
    ipucu = "⚠ 6+ gün işlem yok — 'venv/bin/python saglik_kaniti.py 7' çalıştır"
    alti = M._sessizlik_ozeti_bicimle({}, 6 * 86400 - 1, 6.0)
    assert ipucu not in alti
    tam = M._sessizlik_ozeti_bicimle({}, 6 * 86400, 6.0)
    assert tam.endswith("\n" + ipucu), tam
    assert ipucu in M._sessizlik_ozeti_bicimle({}, 10.5 * 86400, 6.0)
    for kotu in "<>&":
        assert kotu not in tam


def test_sure_yaz():
    assert M._sure_yaz(0) == "0dk"
    assert M._sure_yaz(40 * 60) == "40dk"
    assert M._sure_yaz(7 * 3600 + 12 * 60) == "7sa 12dk"
    assert M._sure_yaz(5 * 86400 + 3 * 3600 + 59) == "5g 3sa"
    assert M._sure_yaz(-5) == "0dk"


# ── 5. İstisnalar yutulur ────────────────────────────────────────────────────

class _BozukSozluk(dict):
    def get(self, *a, **k):
        raise RuntimeError("sayaç bozuk")

    def __setitem__(self, *a, **k):
        raise RuntimeError("sayaç bozuk")


class _BozukMetin:
    def __str__(self):
        raise RuntimeError("str patladı")


def test_istisnalar_yutulur():
    _temiz_durum()
    with _yamala(M, _sessizlik_sayac=_BozukSozluk()):
        M._sayac_artir("donch_hacim")                          # atmaz
        M._donch_elenme_kaydet("SOL/USDT:USDT", "hacim zayif (1.00x < 2.50x)")
        M._squeeze_rejim_engel(_ctx(yon=1), "ranging", 15.0, None, 1.0)
    M._donch_elenme_kaydet("SOL/USDT:USDT", _BozukMetin())    # atmaz
    M._squeeze_rejim_engel(_ctx(patla=True), "ranging", 15.0, None, 1.0)
    M._squeeze_rejim_engel(types.SimpleNamespace(symbol="X"), "ranging", 15.0, None, 1.0)
    with _yamala(M, _squeeze_rejim_engelli=_BozukSozluk()):
        M._squeeze_rejim_acik("XRP/USDT:USDT", "neutral", 22.0)
    # sayaç engeli gölge analiz patlasa da kaydedildi
    assert M._sessizlik_sayac.get("squeeze_rejim") == 2
    _temiz_durum()


class _SahteDB:
    def __init__(self, giris=None, patla=False):
        self.giris, self.patla = giris, patla

    async def get_all_trades(self, limit=100, is_paper=None):
        if self.patla:
            raise RuntimeError("db kilitli")
        if self.giris is None:
            return []
        return [types.SimpleNamespace(entry_time=self.giris)]

    async def get_meta_float(self, key, default=0.0):
        return default


_CFG = types.SimpleNamespace(exchange=types.SimpleNamespace(paper_mode=False))


def test_ozet_al_db_hatasinda_atmaz_ve_sayaci_sifirlar():
    _temiz_durum()
    M._sayac_artir("donch_hacim", 2)
    with _yamala(M, db=_SahteDB(patla=True), config=_CFG), _log_yakala() as h:
        o = asyncio.run(M._sessizlik_ozeti_al(6.0))
    assert "hacim 2" in o and "son giriş" not in o, o
    assert M._sessizlik_sayac == {}                      # okundu -> sıfırlandı
    assert any(m.startswith("Sessizlik özeti: ") for m in h.info_mesajlari())
    # db hiç yoksa da atmaz
    with _yamala(M, db=None, config=_CFG):
        assert "son giriş" not in asyncio.run(M._sessizlik_ozeti_al(6.0))


def test_ozet_al_son_giris_ve_ipucu():
    _temiz_durum()
    yedi_gun = (datetime.now(timezone.utc) - timedelta(days=7, hours=2)).isoformat()
    with _yamala(M, db=_SahteDB(giris=yedi_gun), config=_CFG), _log_yakala() as h:
        o = asyncio.run(M._sessizlik_ozeti_al(6.0))
    assert "son giriş 7g 2sa önce" in o and "saglik_kaniti.py 7" in o, o
    log = [m for m in h.info_mesajlari() if m.startswith("Sessizlik özeti: ")]
    assert len(log) == 1 and "\n" not in log[0] and " | ⚠ 6+ gün" in log[0], log
    # 'Z' soneki ve saat dilimsiz kayıt da okunur
    iki_saat = (datetime.now(timezone.utc) - timedelta(hours=2, minutes=5))
    for t in (iki_saat.strftime("%Y-%m-%dT%H:%M:%SZ"),
              iki_saat.replace(tzinfo=None).isoformat()):
        with _yamala(M, db=_SahteDB(giris=t), config=_CFG):
            o = asyncio.run(M._sessizlik_ozeti_al(6.0))
        assert "son giriş 2sa 5dk önce" in o and "saglik_kaniti" not in o, o
    # bozuk zaman damgası -> atlanır, atmaz
    with _yamala(M, db=_SahteDB(giris="dün"), config=_CFG):
        assert "son giriş" not in asyncio.run(M._sessizlik_ozeti_al(6.0))


def test_ozet_al_bicimleyici_patlarsa_bos_doner():
    def _patla(*a, **k):
        raise RuntimeError("biçim patladı")
    with _yamala(M, db=None, config=_CFG, _sessizlik_ozeti_bicimle=_patla):
        assert asyncio.run(M._sessizlik_ozeti_al(6.0)) == ""


# ── 6. Heartbeat entegrasyonu: eski mesaj AYNEN + özet ekli ──────────────────

class _SahteTelegram:
    def __init__(self):
        self.mesajlar = []

    async def send_alert(self, msg, level="INFO"):
        self.mesajlar.append((msg, level))


class _SahteExecutor:
    async def current_equity(self):
        return 300.0


class _SahtePortfoy:
    def get_open_position_count(self):
        return 0

    def get_total_unrealized_pnl(self):
        return 0.0


class _Dur(Exception):
    pass


def _heartbeat_bir_tur(db):
    """heartbeat_loop'u TEK tur koştur (sleep'te durdur), /tmp'ye yazma."""
    tg = _SahteTelegram()
    cfg = types.SimpleNamespace(
        heartbeat_hours=0.0,   # tg_every = 300 sn -> ilk turda mesaj gider
        exchange=types.SimpleNamespace(paper_mode=True),
        strategy=types.SimpleNamespace(primary_tf="1h"))

    async def _sleep(*a, **k):
        raise _Dur()

    yazilan = []
    with _yamala(M, config=cfg, telegram=tg, ntfy=None, db=db, exchange=None,
                 executor=_SahteExecutor(), portfolio=_SahtePortfoy(),
                 symbol_ctxs={}), \
            _yamala(asyncio, sleep=_sleep), \
            _yamala(Path, write_text=lambda self, *a, **k: yazilan.append(str(self))):
        try:
            asyncio.run(M.heartbeat_loop())
        except _Dur:
            pass
    return tg


def test_heartbeat_ozeti_ekler_ve_sayaci_sifirlar():
    _temiz_durum()
    M._sayac_artir("donch_hacim", 3)
    M._sayac_artir("squeeze_rejim", 5)
    iki_gun = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    tg = _heartbeat_bir_tur(_SahteDB(giris=iki_gun))
    assert len(tg.mesajlar) == 1, tg.mesajlar
    msg, seviye = tg.mesajlar[0]
    ilk, ikinci = msg.split("\n", 1)
    assert seviye == "INFO"
    assert ilk.startswith("Bot çalışıyor · equity $300.00 · yatırılan"), ilk
    assert ikinci.startswith("Sessizlik (son 0.0833333sa): son giriş 2g 0sa önce"), ikinci
    assert "hacim 3" in ikinci and "Squeeze rejim engeli 5" in ikinci
    assert M._sessizlik_sayac == {}


def test_heartbeat_ozet_patlasa_da_eski_mesaj_gider():
    _temiz_durum()

    def _patla(*a, **k):
        raise RuntimeError("biçim patladı")
    with _yamala(M, _sessizlik_ozeti_bicimle=_patla):
        tg = _heartbeat_bir_tur(_SahteDB(patla=True))
    assert len(tg.mesajlar) == 1
    assert tg.mesajlar[0][0].startswith("Bot çalışıyor · equity $300.00")
    assert "\n" not in tg.mesajlar[0][0]


# ── 7. Karar yolu: telemetri dönüş değeri HİÇBİR koşulda kullanılmıyor ──────

_TELEMETRI = {"_sayac_artir", "_donch_elenme_kaydet", "_squeeze_rejim_acik",
              "_squeeze_rejim_engel"}


def test_telemetri_cagrilari_yalniz_ifade_deyimi():
    src = (KOK / "main.py").read_text(encoding="utf-8")
    agac = ast.parse(src)
    fn = next(n for n in ast.walk(agac)
              if isinstance(n, ast.FunctionDef) and n.name == "make_on_candle_close")
    cagrilar, ifade = [], set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call):
            ifade.add(id(n.value))
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id in _TELEMETRI):
            cagrilar.append(n)
    adlar = sorted(c.func.id for c in cagrilar)
    # BB engel + 3 yürütme engeli + donch bayat/analiz/mtf = 7 sayaç çağrısı
    assert adlar.count("_sayac_artir") == 7, adlar
    for ad in ("_donch_elenme_kaydet", "_squeeze_rejim_acik", "_squeeze_rejim_engel"):
        assert adlar.count(ad) == 1, adlar
    for c in cagrilar:
        assert id(c) in ifade, f"{c.func.id} satır {c.lineno}: dönüş değeri kullanılıyor"
        assert not any(isinstance(a, ast.NamedExpr) for a in ast.walk(c))


def test_main_kaynagi_baglanti_yerleri():
    src = (KOK / "main.py").read_text(encoding="utf-8")
    i = src.index('web_dashboard.add_signal(ctx.symbol, "Donch", 0, dch_sig.reason)')
    assert "_donch_elenme_kaydet(ctx.symbol, dch_sig.reason)" in src[i:i + 400]
    i = src.index('web_dashboard.add_signal(ctx.symbol, "Squeeze", 0, f"block:rejim={regime}")')
    assert "_squeeze_rejim_engel(ctx, regime, adx_val, df, atr_val)" in src[i:i + 300]
    i = src.index("async def heartbeat_loop")
    blok = src[i:src.index("\n\n\n", i)]
    assert "await _sessizlik_ozeti_al(tg_every / 3600)" in blok
    assert 'msg = f"{msg}\\n{ozet}"' in blok


def _tumunu_kos():
    ad_fn = [(k, v) for k, v in globals().items()
             if k.startswith("test_") and callable(v)]
    for ad, fn in ad_fn:
        fn()
        print(f"  ✓ {ad}")
    print(f"✓ sessizlik görünürlüğü: {len(ad_fn)} test geçti")


if __name__ == "__main__":
    _tumunu_kos()
