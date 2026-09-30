"""
FAILED_PULLBACK_V1 davranış testleri. Testlerin geçmesi stratejinin kârlı olduğunu
KANITLAMAZ; yalnız kuralların yazıldığı gibi uygulandığını gösterir.

Çalıştır (repo kökünden):  python3 -m pytest -q arastirma/failed_pullback_v1/test_fpb.py
"""
import asyncio
import os
import sys

import numpy as np
import pandas as pd
import pytest

BURA = os.path.dirname(os.path.abspath(__file__))
KOK = os.path.dirname(os.path.dirname(BURA))
sys.path.insert(0, KOK)
sys.path.insert(0, BURA)
os.environ.setdefault("MOD", "B")
os.environ.setdefault("AD", "test")
import fpb_aday as F  # noqa: E402

H = F.SAAT_MS
T0 = 1_700_000_000_000 // H * H
COINLER = "SOL ETH ADA NEAR BCH XRP DOGE TRX XLM LTC ICP BNB".split()


# ───────────────────────── senaryo altyapısı ─────────────────────────────────
class SenaryoGosterge:
    """Her mumda senaryodaki (ema, atr, adx) değerini verir — kural mantığını
    gösterge hesabından ayırarak sınamak için."""

    def __init__(self, degerler):
        self._d = list(degerler)
        self.n = 0
        self.ema = self.atr = self.adx = None

    def guncelle(self, h, l, c):
        self.ema, self.atr, self.adx = self._d[self.n]
        self.n += 1


def isinma(n=100):
    """ADX 20, EMA 100 sabit, fiyat EMA üstünde (short tarafı için nötr)."""
    return [dict(h=102.0, l=100.5, c=101.0, ema=100.0, atr=1.0, adx=20.0) for _ in range(n)]


def kos(mumlar, bas=T0, sembol="X", atla=()):
    g = SenaryoGosterge([(m["ema"], m["atr"], m["adx"]) for m in mumlar])
    d = F.FPBDurum(sembol, gosterge=g)
    olaylar = []
    onceki_c = mumlar[0]["c"]
    for k, m in enumerate(mumlar):
        if k in atla:
            continue
        olaylar += d.isle(bas + k * H, onceki_c, m["h"], m["l"], m["c"])
        onceki_c = m["c"]
    return olaylar, d


def tur(olaylar, t):
    return [o for o in olaylar if o.tur == t]


def short_senaryo():
    """a=100, p=103, f=105, q=107 → short sinyali."""
    m = isinma()
    m.append(dict(h=104, l=102.5, c=103.5, ema=100.6, atr=1.0, adx=35))      # 100 a
    m.append(dict(h=105, l=103.0, c=104.5, ema=101.0, atr=1.0, adx=36))      # 101
    m.append(dict(h=106, l=104.0, c=105.5, ema=101.5, atr=1.0, adx=37))      # 102
    m.append(dict(h=105.8, l=101.8, c=104.0, ema=102.0, atr=1.0, adx=36))    # 103 p: dip ≤ EMA, kapanış üstünde → P=101.8
    m.append(dict(h=104.2, l=102.3, c=102.8, ema=102.2, atr=1.0, adx=35))    # 104
    m.append(dict(h=103.0, l=100.9, c=101.2, ema=102.1, atr=1.0, adx=34))    # 105 f: kapanış < P ve < EMA
    m.append(dict(h=101.5, l=100.4, c=100.8, ema=101.9, atr=1.0, adx=33))    # 106 tepe < P
    m.append(dict(h=102.3, l=100.6, c=101.0, ema=101.7, atr=1.0, adx=32))    # 107 q: tepe ≥ P, kapanış < P, < EMA
    m.append(dict(h=101.0, l=99.0, c=99.5, ema=101.4, atr=1.0, adx=31))      # 108
    return m


def aynala(mumlar, eksen=200.0):
    """Fiyatları eksene göre yansıtır: short senaryosu → long senaryosu."""
    out = []
    for m in mumlar:
        out.append(dict(h=eksen - m["l"], l=eksen - m["h"], c=eksen - m["c"],
                        ema=eksen - m["ema"], atr=m["atr"], adx=m["adx"]))
    return out


# ───────────────────────── kural testleri ────────────────────────────────────
def test_temel_short_sinyali_ve_seviyeler():
    ol, _ = kos(short_senaryo())
    s = tur(ol, "sinyal")
    assert len(s) == 1
    s = s[0]
    assert s.yon == -1
    assert (s.a_ts, s.p_ts, s.f_ts, s.q_ts) == (T0 + 100 * H, T0 + 103 * H, T0 + 105 * H, T0 + 107 * H)
    assert s.P == pytest.approx(101.8)
    assert s.E_plan == pytest.approx(101.0)
    # S = f+1..q en yüksek tepe (106: 101.5, 107: 102.3) + 0.1*ATR[q]
    assert s.S == pytest.approx(102.3 + 0.1)
    assert s.T == pytest.approx(101.0 - 2 * (102.4 - 101.0))
    assert s.S > s.E_plan > s.T
    assert s.kimlik == f"X|{T0 + 100 * H}"


def test_long_kurallari_ayna():
    ol, _ = kos(aynala(short_senaryo()))
    s = tur(ol, "sinyal")
    assert len(s) == 1
    s = s[0]
    assert s.yon == 1
    assert s.P == pytest.approx(200 - 101.8)             # p mumunun TEPESİ
    assert s.E_plan == pytest.approx(99.0)
    assert s.S == pytest.approx((200 - 102.3) - 0.1)     # f+1..q en düşük dip − 0.1 ATR
    assert s.T == pytest.approx(99.0 + 2 * (99.0 - s.S))
    assert s.T > s.E_plan > s.S


def test_long_a_kosulu_ema_egimi_ve_kapanis_yonu():
    # Long hazırlığı: kapanış EMA altında VE EMA üç mum öncesinden düşük olmalı.
    m = aynala(isinma())
    m.append(dict(h=97, l=95, c=96, ema=100.0, atr=1, adx=35))   # EMA düz (100 = 100) → hazırlık YOK
    ol, _ = kos(m)
    assert tur(ol, "hazirlik") == []
    m[-1]["ema"] = 99.5
    ol, _ = kos(m)
    assert [o.yon for o in tur(ol, "hazirlik")] == [1]


def test_ilk_temas_ema_altinda_kapanirsa_iptal_sonraki_temas_secilmez():
    m = short_senaryo()
    m[103]["c"] = 101.9                     # ilk temas mumu EMA (102.0) ALTINDA kapanıyor
    # sonraki mumlar kendi başına geçerli bir temas + kayıp + teyit dizisi olsa da
    m[104] = dict(h=103.5, l=102.1, c=103.0, ema=102.0, atr=1, adx=35)
    m += [dict(h=103.2, l=101.9, c=102.6, ema=102.0, atr=1, adx=34),     # 109 "ikinci temas"
          dict(h=102.5, l=100.5, c=100.8, ema=101.8, atr=1, adx=33),     # 110
          dict(h=102.2, l=100.4, c=100.6, ema=101.6, atr=1, adx=32)]     # 111
    ol, _ = kos(m)
    ip = tur(ol, "iptal")
    assert [(o.neden, o.ts) for o in ip] == [("ilk_temas_ema_otesinde_kapandi", T0 + 103 * H)]
    assert tur(ol, "sinyal") == []


@pytest.mark.parametrize("temas_k, beklenen", [(12, "sinyal_yolu"), (13, "p_zaman_asimi")])
def test_p_penceresi_iki_uc_dahil(temas_k, beklenen):
    m = isinma()
    m.append(dict(h=104, l=102.5, c=103.5, ema=100.6, atr=1, adx=35))            # a=100
    for k in range(1, 15):
        m.append(dict(h=106, l=104, c=105, ema=101 + 0.1 * k, atr=1, adx=35))    # temas yok
    j = 100 + temas_k
    m[j] = dict(h=106, l=101.0, c=104, ema=101 + 0.1 * temas_k, atr=1, adx=35)
    ol, _ = kos(m)
    ip = tur(ol, "iptal")
    if beklenen == "p_zaman_asimi":
        assert [(o.neden, o.ts) for o in ip] == [("p_zaman_asimi", T0 + 112 * H)]
    else:
        assert ip == [] or ip[0].neden != "p_zaman_asimi"


def _pfq_senaryo(f_k=None, q_k=None, geri_alma_k=None):
    """a=100, p=101 (P=100.7), sonra f ve q istenen mumda."""
    m = isinma()
    m.append(dict(h=104, l=102.5, c=103.5, ema=100.6, atr=1, adx=35))   # a=100
    m.append(dict(h=104, l=100.7, c=103.0, ema=101.0, atr=1, adx=35))   # p=101, P=100.7
    for k in range(1, 14):                                              # 102..114: kayıp yok
        m.append(dict(h=103, l=101.5, c=102.0, ema=101.0, atr=1, adx=35))
    if f_k is not None:
        m[101 + f_k] = dict(h=101.5, l=99.5, c=100.0, ema=100.9, atr=1, adx=34)
        for k in range(1, 8):                                           # f sonrası: tepe P altında
            j = 101 + f_k + k
            if j < len(m):
                m[j] = dict(h=100.5, l=99.0, c=99.6, ema=100.8, atr=1, adx=33)
        if q_k is not None:
            m[101 + f_k + q_k] = dict(h=100.9, l=99.2, c=99.8, ema=100.5, atr=1, adx=32)
        if geri_alma_k is not None:
            m[101 + f_k + geri_alma_k] = dict(h=101.2, l=99.8, c=100.7, ema=100.5, atr=1, adx=32)
    return m


@pytest.mark.parametrize("f_k, iptal", [(6, None), (7, "f_zaman_asimi")])
def test_f_penceresi_iki_uc_dahil(f_k, iptal):
    ol, _ = kos(_pfq_senaryo(f_k=f_k))
    ip = [o.neden for o in tur(ol, "iptal")]
    if iptal:
        assert ip == ["f_zaman_asimi"] and tur(ol, "iptal")[0].ts == T0 + 107 * H
    else:
        assert "f_zaman_asimi" not in ip


@pytest.mark.parametrize("q_k, sonuc", [(6, "sinyal"), (7, "q_zaman_asimi")])
def test_q_penceresi_iki_uc_dahil(q_k, sonuc):
    ol, _ = kos(_pfq_senaryo(f_k=1, q_k=q_k))
    if sonuc == "sinyal":
        s = tur(ol, "sinyal")
        assert len(s) == 1 and s[0].q_ts == T0 + (102 + 6) * H
    else:
        assert tur(ol, "sinyal") == []
        assert [(o.neden, o.ts) for o in tur(ol, "iptal")] == [("q_zaman_asimi", T0 + 108 * H)]


def test_teyitten_once_P_uzerinde_kapanis_iptal():
    ol, _ = kos(_pfq_senaryo(f_k=1, q_k=4, geri_alma_k=2))    # 2. mum P'de/üstünde kapanıyor
    assert tur(ol, "sinyal") == []
    assert [o.neden for o in tur(ol, "iptal")] == ["P_geri_alindi"]
    # tam P'de kapanış da iptal
    m = _pfq_senaryo(f_k=1, q_k=4, geri_alma_k=2)
    m[104]["c"] = 100.7
    ol, _ = kos(m)
    assert [o.neden for o in tur(ol, "iptal")] == ["P_geri_alindi"]


def test_q_mumu_ema_ustunde_kapanirsa_teyit_degil():
    m = short_senaryo()
    m[107]["ema"] = 100.9                    # kapanış 101.0 > EMA → q değil
    ol, _ = kos(m)
    assert tur(ol, "sinyal") == []


def test_eksik_mum_aktif_kurulumu_iptal_eder_yapay_mum_yok():
    ol, _ = kos(short_senaryo(), atla={104})
    assert tur(ol, "sinyal") == []
    e = tur(ol, "eksik_mum")
    assert len(e) == 1 and e[0].ts == T0 + 105 * H
    assert [o.neden for o in tur(ol, "iptal")] == ["eksik_mum"]


def test_bosluktan_sonra_dort_ardisik_mum_olmadan_hazirlik_yok():
    m = isinma(110)
    m[105] = dict(h=104, l=102.5, c=103.5, ema=100.6, atr=1, adx=35)
    m[104]["adx"] = 20
    ol, _ = kos(m, atla={103})               # 102 → 104 boşluk; 105 yalnız 2. ardışık mum
    assert tur(ol, "hazirlik") == []
    ol, _ = kos(m)                           # boşluk yokken aynı mum hazırlıktır
    assert len(tur(ol, "hazirlik")) == 1


def test_ayni_mum_tekrar_islenmez():
    m = short_senaryo()
    g = SenaryoGosterge([(x["ema"], x["atr"], x["adx"]) for x in m])
    d = F.FPBDurum("X", gosterge=g)
    ol = []
    for k, x in enumerate(m):
        ol += d.isle(T0 + k * H, x["c"], x["h"], x["l"], x["c"])
        if k == 105:                          # f mumu ikinci kez gelir
            tekrar = d.isle(T0 + k * H, x["c"], x["h"], x["l"], x["c"])
            assert [o.tur for o in tekrar] == ["tekrar_mum"]
            eski = d.isle(T0 + (k - 3) * H, x["c"], x["h"], x["l"], x["c"])
            assert [o.tur for o in eski] == ["tekrar_mum"]
    assert g.n == len(m)                      # göstergeler tekrar mumda güncellenmedi
    assert len(tur(ol, "sinyal")) == 1


def test_isinma_100_mumdan_once_hazirlik_yok():
    m = isinma(99)
    m.append(dict(h=104, l=102.5, c=103.5, ema=100.6, atr=1, adx=35))   # i=99
    ol, _ = kos(m)
    assert tur(ol, "hazirlik") == []
    m = isinma(100)
    m.append(dict(h=104, l=102.5, c=103.5, ema=100.6, atr=1, adx=35))   # i=100
    ol, _ = kos(m)
    assert len(tur(ol, "hazirlik")) == 1


def test_aktif_kurulumda_yeni_hazirlik_yok_ve_bitis_mumunda_da_yok():
    m = short_senaryo()
    # p aşamasında ADX düşüp yeniden 30'u geçiyor → yeni hazırlık OLMAMALI
    m[101]["adx"] = 28
    m[102]["adx"] = 33
    ol, _ = kos(m)
    assert len(tur(ol, "hazirlik")) == 1
    # kurulumun iptal edildiği mumda ADX geçişi: o mum da hazırlık başlatmaz
    m = short_senaryo()
    m[103]["c"] = 101.9          # 103'te iptal
    m[102]["adx"] = 29
    m[103]["adx"] = 31
    ol, _ = kos(m)
    assert [o.ts for o in tur(ol, "hazirlik")] == [T0 + 100 * H]


def test_bir_hazirliktan_en_fazla_bir_sinyal():
    m = short_senaryo()
    # sinyalden sonra aynı kalıbı tekrar eden mumlar: yeni ADX geçişi yok → ikinci sinyal yok
    m += [dict(h=102.4, l=100.0, c=100.5, ema=101.2, atr=1, adx=31) for _ in range(5)]
    ol, _ = kos(m)
    assert len(tur(ol, "sinyal")) == 1


def test_gecersiz_seviye_sinyal_sayilmaz():
    m = short_senaryo()
    m[107]["atr"] = -50.0        # yapay: S E'nin altına düşer → geçersiz
    ol, _ = kos(m)
    assert tur(ol, "sinyal") == []
    g = tur(ol, "gecersiz")
    assert len(g) == 1 and g[0].neden


# ───────────────────────── gerçek veri testleri ──────────────────────────────
def _veri(coin):
    d = pd.read_csv(os.path.join(KOK, "data", f"{coin}_fut_1h.csv"))
    t = pd.to_datetime(d["ts"], utc=True)
    ts = (t.astype("int64") // (10**6 if t.dt.unit == "ns" else 10**3)).to_numpy()
    return ts, d


def test_akis_gostergeleri_indicators_py_ile_ayni():
    import indicators as I
    for coin in ("SOL", "XRP", "LTC"):
        ts, d = _veri(coin)
        g = F.AkisGosterge()
        e, a, x = [], [], []
        for k in range(len(d)):
            g.guncelle(d["high"].iat[k], d["low"].iat[k], d["close"].iat[k])
            e.append(g.ema); a.append(g.atr); x.append(np.nan if g.adx is None else g.adx)
        ref_e = I.ema(d["close"], 20).to_numpy()
        ref_a = I.atr(d["high"], d["low"], d["close"], 14).to_numpy()
        ref_x = I.adx(d["high"], d["low"], d["close"], 14).to_numpy()
        assert np.allclose(e, ref_e, rtol=1e-9, atol=0)
        assert np.allclose(a, ref_a, rtol=1e-9, atol=0)
        assert np.allclose(np.array(x)[100:], ref_x[100:], rtol=1e-7, atol=1e-9)


def test_kesme_gelecek_mumlar_gecmis_sinyalleri_degistirmez():
    """Veriyi bir tarihte kesip hesaplanan sinyaller = tam veri koşusunun o tarihe
    kadarki sinyalleri (tüm coinler, üç kesme noktası)."""
    for coin in COINLER:
        ts, d = _veri(coin)
        tam = F.seriyi_isle(coin, ts, d.open, d.high, d.low, d.close)
        for oran in (0.31, 0.57, 0.83):
            n = int(len(ts) * oran)
            kesik = F.seriyi_isle(coin, ts[:n], d.open[:n], d.high[:n], d.low[:n], d.close[:n])
            sinir = ts[n - 1]
            a = [o.sozluk() for o in tam if o.ts <= sinir and o.tur in ("sinyal", "hazirlik", "iptal", "gecersiz")]
            b = [o.sozluk() for o in kesik if o.tur in ("sinyal", "hazirlik", "iptal", "gecersiz")]
            assert a == b, (coin, oran)
            assert any(o["tur"] == "sinyal" for o in a)


# ───────────────────────── ikiz kanca testleri ───────────────────────────────
class _Seri:
    def __init__(self, ts_ms, o, h, l, c):
        self.ts_ns = np.asarray(ts_ms, dtype="int64") * 1_000_000
        self.kapanis_ns = self.ts_ns + H * 1_000_000
        self.o, self.h, self.l, self.c = map(lambda v: np.asarray(v, dtype="float64"), (o, h, l, c))


class _Feed:
    def __init__(self, seriler):
        self.seriler = seriler
        self.simdi_ns = 0

    def _s(self, sym, tf):
        return self.seriler[sym]

    def _simdi_ns(self):
        return self.simdi_ns


class _Res:
    def __init__(self, ok, error=None, position=None):
        self.success, self.error, self.position = ok, error, position


class _Executor:
    def __init__(self, hata="X/USDT:USDT already holds a position (one-per-symbol in netted mode)"):
        self.cagrilar = []
        self.hata = hata
        self.feed = None

    async def execute_signal(self, sig, atr):
        self.cagrilar.append((self.feed.simdi_ns // 1_000_000, sig))
        return _Res(False, error=self.hata)


class _Poz:
    def __init__(self, sym, d, st):
        self.symbol, self.direction, self.strategy_scores = sym, d, {"strategy": st}


class _PF:
    def __init__(self, poz=()):
        self.poz = list(poz)

    def get_open_positions(self):
        return self.poz


class _Ex:
    def __init__(self, fiyat):
        self.fiyat = fiyat
        self._balance = 1000.0

    def _price_for(self, sym):
        return self.fiyat[sym]

    def get_open_positions(self):
        return []


class _M:
    def __init__(self, syms, feed, pf, ex, exe):
        self.symbol_ctxs = {s: None for s in syms}
        self.portfolio, self.exchange, self.executor = pf, ex, exe


def _gercek_sinyal_ve_seri(coin="SOL"):
    ts, d = _veri(coin)
    ol = F.seriyi_isle(coin, ts, d.open, d.high, d.low, d.close)
    s = [o for o in ol if o.tur == "sinyal"][0]
    q = int(np.where(ts == s.q_ts)[0][0])
    return s, ts, d, q


def test_kanca_sinyal_q_kapanisinda_bir_kez_denenir_engellenen_tekrar_denenmez():
    import fpb_kos as K
    s, ts, d, q = _gercek_sinyal_ve_seri()
    sym = "SOL/USDT:USDT"
    seri = _Seri(ts, d.open, d.high, d.low, d.close)
    feed = _Feed({sym: seri})
    exe = _Executor()
    exe.feed = feed
    M = _M([sym], feed, _PF([_Poz(sym, 1, "donchian")]), _Ex({sym: float(d.close.iat[q])}), exe)
    k = K.Kancalar(M, None, feed, "B", {sym: {"long": 0.00875, "short": 0.00875}}, kayit_ozsermaye=False)
    for j in range(0, q + 20):                          # q'dan sonra 19 mum daha
        feed.simdi_ns = int(seri.kapanis_ns[j])
        M.exchange.fiyat[sym] = float(d.close.iat[j])
        k.aday_guncelle(sym, int(ts[j]))
        asyncio.run(k.ts_sonu(int(ts[j])))
    assert len(exe.cagrilar) == 1                      # engellendi, YENİDEN denenmedi
    zaman, sig = exe.cagrilar[0]
    assert zaman == int(ts[q]) + H                     # q KAPANIŞINDA (q+1 açılışı), önce değil
    assert sig.entry_price == pytest.approx(float(d.close.iat[q]))
    assert (sig.sl_price, sig.tp_price) == (pytest.approx(s.S), pytest.approx(s.T))
    assert sig.direction == s.yon and sig.force_market
    kayit = [r for r in k.sinyaller if r["a_ts"] == s.a_ts]
    assert len(kayit) == 1 and kayit[0]["sonuc"] == "engellendi"
    beklenen = "SEMBOLDE_TERS_POZISYON" if s.yon == -1 else "SEMBOLDE_AYNI_YON_POZISYON"
    assert kayit[0]["neden_kodu"] == beklenen
    assert kayit[0]["mevcut_pozisyon"] == "donchian:long"


def test_kanca_acilis_stop_hedef_arasinda_degilse_iptal():
    import fpb_kos as K
    s, ts, d, q = _gercek_sinyal_ve_seri()
    sym = "SOL/USDT:USDT"
    seri = _Seri(ts, d.open, d.high, d.low, d.close)
    feed = _Feed({sym: seri})
    exe = _Executor()
    exe.feed = feed
    M = _M([sym], feed, _PF(), _Ex({sym: s.S + (1 if s.yon == -1 else -1)}), exe)  # fiyat stopun ötesinde
    k = K.Kancalar(M, None, feed, "B", {sym: {"long": 0.00875, "short": 0.00875}}, kayit_ozsermaye=False)
    for j in range(0, q + 1):
        feed.simdi_ns = int(seri.kapanis_ns[j])
        k.aday_guncelle(sym, int(ts[j]))
    asyncio.run(k.ts_sonu(int(ts[q])))
    assert exe.cagrilar == []
    assert k.sinyaller[-1]["neden_kodu"] == "ACILIS_SEVIYE_DISI"


def test_kanca_ayni_damgada_bot_once_adaylar_sembol_sirasiyla():
    import fpb_kos as K

    class _Kayit(_Executor):
        async def execute_signal(self, sig, atr):
            self.cagrilar.append(sig.symbol)
            return _Res(False, error="Max positions (7) reached")

    exe = _Kayit()
    k = K.Kancalar.__new__(K.Kancalar)
    k.M = _M([], None, _PF(), _Ex({"B/USDT:USDT": 10.0, "A/USDT:USDT": 10.0}), exe)
    k.mod, k.harita, k.sinyaller, k.kuyruk = "B", {"A/USDT:USDT": {"short": 0.01}, "B/USDT:USDT": {"short": 0.01}}, [], []
    k.kayit_ozsermaye, k.aktif_risk = False, None
    for sym in ("B/USDT:USDT", "A/USDT:USDT"):
        k.kuyruk.append(dict(sembol=sym, yon=-1, S=11.0, T=8.0, E_plan=10.0, atr_q=0.5,
                             a_ts=0, q_ts=0, kimlik=sym))
    asyncio.run(k.ts_sonu(0))
    assert exe.cagrilar == ["A/USDT:USDT", "B/USDT:USDT"]
    assert all(r["neden_kodu"] == "MAX_POZISYON" for r in k.sinyaller)


@pytest.fixture
def kancali_borsa():
    """Gerçek PaperExchange + fpb_kos kancaları; test sonunda sınıflar geri yüklenir."""
    import data as D
    import exchange as EX
    import risk as RK
    import portfolio as PF
    import fpb_kos as K
    yedek = (D.DataManager._fire_callbacks, RK.RiskManager.build_trade_setup_from_levels,
             PF.Portfolio.create_position, EX.PaperExchange.check_sl_tp,
             EX.PaperExchange._close_paper_position)
    yield K, EX, PF
    (D.DataManager._fire_callbacks, RK.RiskManager.build_trade_setup_from_levels,
     PF.Portfolio.create_position, EX.PaperExchange.check_sl_tp,
     EX.PaperExchange._close_paper_position) = yedek


def _borsa_ve_kanca(K, EX, acilis):
    sym = "SOL/USDT:USDT"
    seri = _Seri([T0], [acilis], [acilis + 1], [acilis - 1], [acilis])
    feed = _Feed({sym: seri})
    feed.simdi_ns = int(seri.kapanis_ns[0])
    ex = EX.PaperExchange(10_000.0, leverage=10)
    M = _M([sym], feed, _PF(), ex, None)
    k = K.Kancalar(M, None, feed, "B", {}, kayit_ozsermaye=False)
    k.tak()
    return k, ex, sym


def test_dolum_q_kapanisi_artı_kayma_hedef_yeniden_2R_yapilmaz(kancali_borsa):
    K, EX, _ = kancali_borsa
    k, ex, sym = _borsa_ve_kanca(K, EX, 100.0)
    asyncio.run(ex.update_price(100.0, sym))
    S, T = 101.0, 98.0
    o = asyncio.run(ex.place_market_order(sym, "sell", 2.0, {"stopLossPrice": S, "takeProfitPrice": T}))
    assert o.filled_price == pytest.approx(100.0 * (1 - EX.PaperExchange.SLIP_GIRIS_BP / 1e4))
    p = ex._positions[o.order_id]
    assert (p.sl_price, p.tp_price) == (S, T)           # kötü dolum seviyeleri değiştirmez


def test_bosluk_stop_otesinde_acilis_acilistan_kapanir(kancali_borsa):
    K, EX, _ = kancali_borsa
    k, ex, sym = _borsa_ve_kanca(K, EX, 101.8)          # mum stopun (101.0) ÜSTÜNDE açıldı
    asyncio.run(ex.update_price(100.0, sym))
    o = asyncio.run(ex.place_market_order(sym, "sell", 2.0, {"stopLossPrice": 101.0, "takeProfitPrice": 98.0}))
    k.aday_ids.add(o.order_id)
    asyncio.run(ex.check_sl_tp(102.8, 100.8, sym))
    p = ex._positions[o.order_id]
    assert p.closed and p.exit_reason == "sl_gap"
    assert p.exit_price == pytest.approx(101.8 * (1 + EX.PaperExchange.SLIP_CIKIS_BP / 1e4))
    assert p.exit_price > 101.0                          # stop fiyatından kusursuz dolum YOK


def test_bosluk_kancasi_aday_disi_pozisyona_dokunmaz(kancali_borsa):
    K, EX, _ = kancali_borsa
    k, ex, sym = _borsa_ve_kanca(K, EX, 101.8)
    asyncio.run(ex.update_price(100.0, sym))
    o = asyncio.run(ex.place_market_order(sym, "sell", 2.0, {"stopLossPrice": 101.0, "takeProfitPrice": 98.0}))
    asyncio.run(ex.check_sl_tp(102.8, 100.8, sym))       # bot pozisyonu: mevcut davranış (stoptan)
    p = ex._positions[o.order_id]
    assert p.exit_reason == "sl_hit"
    assert p.exit_price == pytest.approx(101.0 * (1 + EX.PaperExchange.SLIP_CIKIS_BP / 1e4))


def test_ayni_mumda_stop_ve_hedef_stop_once_ve_isaretlenir(kancali_borsa):
    import fpb_analiz as A
    K, EX, _ = kancali_borsa
    k, ex, sym = _borsa_ve_kanca(K, EX, 100.0)
    asyncio.run(ex.update_price(100.0, sym))
    o = asyncio.run(ex.place_market_order(sym, "sell", 2.0, {"stopLossPrice": 101.0, "takeProfitPrice": 98.0}))
    k.aday_ids.add(o.order_id)
    asyncio.run(ex.check_sl_tp(101.5, 97.5, sym))        # tek mum ikisine de değdi
    assert ex._positions[o.order_id].exit_reason == "sl_hit"
    assert A.ayni_mum_belirsiz("short", 101.0, 98.0, 101.5, 97.5)
    assert not A.ayni_mum_belirsiz("short", 101.0, 98.0, 101.5, 98.5)
    assert A.ayni_mum_belirsiz("long", 99.0, 102.0, 102.5, 98.5)


def test_max_hold_12_yalniz_aday_pozisyonuna_yazilir(kancali_borsa):
    K, EX, PF = kancali_borsa
    k, ex, sym = _borsa_ve_kanca(K, EX, 100.0)
    pf = PF.Portfolio(is_paper=True)
    p = pf.create_position(symbol=sym, direction=-1, entry_price=100, sl_price=101, tp_price=98,
                           quantity=1, strategy_scores={"strategy": F.STRATEJI})
    assert p.strategy_scores["max_hold"] == 12
    p2 = pf.create_position(symbol="ETH/USDT:USDT", direction=1, entry_price=100, sl_price=99,
                            tp_price=102, quantity=1, strategy_scores={"strategy": "donchian"})
    assert "max_hold" not in p2.strategy_scores


def test_R_hesabi_dolum_ve_ilk_stoptan():
    import fpb_analiz as A
    # short: E_fill 99.8, stop 101, miktar 2 → R0 = 1.2*2 = 2.4 USDT
    assert A.r0_usdt(99.8, 101.0, 2.0) == pytest.approx(2.4)
    assert A.net_r(-2.6, 99.8, 101.0, 2.0) == pytest.approx(-2.6 / 2.4)
    assert np.isnan(A.net_r(1.0, 101.0, 101.0, 2.0))    # sıfır risk → geçersiz, işaretlenir
