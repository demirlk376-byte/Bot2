"""
kollar_ek.py — ANKOR DIŞI DÖRT KOL için KRONOS Kol'ları (orb / asia_bo / fvg / sr).

Üretim sınıfları AYNEN import edilir (strategies/*.py OKUNMADI DEĞİŞTİRİLMEDİ):
    strategies.orb.OrbStrategy
    strategies.asia_bo.AsiaBoStrategy
    strategies.fvg.FvgStrategy
    strategies.sr_breakout.SrBreakoutStrategy

CANLI BİREBİRLİK (main.py make_on_candle_close):
  df       = get_candles(primary_tf="1h", 120)              → pencere(i, 120)
  df_long  = get_candles("1h", 250)   (YALNIZ fvg)          → pencere(i, 250)
  atr_val  = atr(df,14).iloc[-1]      ← 120 BARLIK df'ten (fvg de bunu alır)
  adx_val  = adx(df,14).iloc[-1]      ← 120 BARLIK df'ten
  atr NaN/<=0 → main.py `return` eder: O BAR HİÇBİR KOL analyze() ÇAĞIRMAZ.
  regime   = _get_regime(adx): >=28 trending, <=20 ranging, arası neutral
  bo_allowed = not (REGIME_FILTER_ENABLED and regime=="ranging")
             → orb / asia_bo / sr_breakout BU KAPIYA TABİ. fvg DEĞİL.
  max_hold : orb/asia 6 (day_max_hold_candles) · fvg 24 · sr 48 (max_hold_candles)

DURUM (KOL DURUMU, stateful):
  OrbStrategy._traded_dates ve FvgStrategy._active canlıda HER MUM KAPANIŞINDA
  ilerler. Bu yüzden sinyaller ÖN-HESAPLANIR: i = 119..n-1 sırayla dolaşılır,
  analyze() canlıdaki sırayla ÇAĞRILIR, sonuç diziye yazılır. sinyal(i) yalnız
  diziyi okur. Böylece sonuç KOLTUK DOLULUĞUNDAN BAĞIMSIZ ve nedenseldir:
  i barındaki karar yalnız pencere(i)'ye bağlı → veri T'de kesilince T öncesi
  kararlar değişmez (kronos_test_ek.py T2 bunu sınar).

⚠ BİLİNEN MODELLEME FARKI — GİRİŞ FİYATI (abartmamak için burada yazılı):
  KRONOS motoru girişi HER ZAMAN bar KAPANIŞINA çakar (motor.py: e=cl).
    · sr_breakout : canlıda force_market=True → giriş = kırılım kapanışı. BİREBİR.
    · orb/asia/fvg: canlıda post-only LİMİT, SEVİYEDEN (600 sn, piyasa yedeği YOK;
      dolmazsa işlem ATLANIR). Kapanıştan girmek bu üç kol için ALEYHTE bir
      modeldir (giriş daha kötü, stop daha uzak, hedef daha yakın) VE canlıda
      dolmayacak sinyalleri de alır. Yani KRONOS bu üç kolu OolduğundanKÖTÜ
      gösterir → "kapat" sonucunu ŞİŞİRİR. Bu yüzden ek_olc.py ayrıca
      "limit-dolum" (iyimser) modelini de ölçer ve iki uç birlikte raporlanır.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import fast_bt
from kronos.motor import Besleme
from kronos.kollar import Kol, _ham

WIN_KISA = 120        # main.py get_candles(primary_tf, 120)
WIN_FVG = 250         # main.py get_candles(primary_tf, 250)
ATR_P = 14
ADX_P = 14
ADX_RANGING = 20.0    # config.risk.adx_ranging_threshold
ADX_TRENDING = 28.0   # config.risk.adx_trending_threshold
MAX_SL_PCT = 0.20     # saçma stop koruması (kapali_kollar.py ile aynı eşik)


# ══════════════════ 120-BARLIK PENCEREDE ATR / ADX (hızlı, birebir) ══════════════════
def rolling_atr_adx(h, l, c, win=WIN_KISA, period=ATR_P):
    """Her i için, [i-win+1 .. i] DİLİMİ üzerinde indicators.atr/adx'in son değeri.

    Canlı get_candles(120) tam olarak bu dilimi verir; ewm o dilimin başında
    YENİDEN BAŞLAR, bu yüzden global ewm ile birebir aynı değildir. Burada
    pencereler i üzerinde vektörleştirilerek AYNI özyineleme koşulur.
    Doğrulama: `python3 kollar_ek.py dogrula <COIN>` pandas ile karşılaştırır.
    """
    n = len(c)
    a = 1.0 / period
    b_ = 1.0 - a
    ph = np.concatenate(([np.nan], h[:-1]))
    pl = np.concatenate(([np.nan], l[:-1]))
    pc = np.concatenate(([np.nan], c[:-1]))
    with np.errstate(invalid="ignore"):
        tr_full = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
        up = h - ph
        dn = pl - l
        pdm = np.where((up > dn) & (up > 0), up, 0.0)
        mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr_first = h - l

    atr_out = np.full(n, np.nan)
    adx_out = np.full(n, np.nan)
    if n < win:
        return atr_out, adx_out

    tgt = np.arange(win - 1, n)
    bas = tgt - win + 1
    atr_e = tr_first[bas].astype(float).copy()
    pdm_e = np.zeros(len(tgt))
    mdm_e = np.zeros(len(tgt))
    adx_e = np.full(len(tgt), np.nan)
    gordu = np.zeros(len(tgt), dtype=bool)

    for k in range(1, win):
        j = bas + k
        atr_e = b_ * atr_e + a * tr_full[j]
        pdm_e = b_ * pdm_e + a * pdm[j]
        mdm_e = b_ * mdm_e + a * mdm[j]
        with np.errstate(invalid="ignore", divide="ignore"):
            pdi = 100.0 * pdm_e / atr_e
            mdi = 100.0 * mdm_e / atr_e
            s = pdi + mdi
            dx = np.where(s == 0, np.nan, 100.0 * np.abs(pdi - mdi) / np.where(s == 0, 1.0, s))
        v = ~np.isnan(dx)
        yeni = v & ~gordu
        guncel = v & gordu
        adx_e = np.where(yeni, dx, np.where(guncel, b_ * adx_e + a * dx, adx_e))
        gordu = gordu | v

    atr_out[tgt] = atr_e
    adx_out[tgt] = adx_e
    return atr_out, adx_out


# ══════════════════ coin başına paylaşılan veri (4 kol aynı diziyi kullanır) ══════════════════
_VERI = {}


def _coin_veri(coin, src, kadar):
    anah = (coin, src, None if kadar is None else pd.Timestamp(kadar).value)
    v = _VERI.get(anah)
    if v is None:
        d = fast_bt.resample(_ham(coin, src, kadar), "1h")
        h = d["high"].values.astype(float)
        l = d["low"].values.astype(float)
        c = d["close"].values.astype(float)
        atr_a, adx_a = rolling_atr_adx(h, l, c)
        v = (d, atr_a, adx_a)
        _VERI[anah] = v
    return v


def veri_onbellek_temizle():
    _VERI.clear()


# ══════════════════ ORTAK TABAN ══════════════════
class EkKol(Kol):
    """4 ankor-dışı kolun ortak iskeleti: canlı pencere + rejim kapısı + ön-hesap."""

    win = WIN_KISA
    mh = 48
    rejim_kapisi = True      # bo_allowed (ranging'te sus) — fvg'de False
    atr_gerekli = True       # analyze(df, atr) mi analyze(df) mi

    def __init__(self, coin, src="local", sira=0, kadar=None, rejim_filtre=True):
        super().__init__(coin, sira)
        d, atr_a, adx_a = _coin_veri(coin, src, kadar)
        self.besleme = Besleme(d)
        self._atr = atr_a
        self._adx = adx_a
        self._rejim_filtre = bool(rejim_filtre)
        self.s = self._strateji()
        self._sig = self._on_hesap()

    def _strateji(self):
        raise NotImplementedError

    # ── canlı main.py'nin bar akışı ──
    def _on_hesap(self):
        n = self.besleme.n
        out = [None] * n
        self.dusen = dict(sld=0, rr=0, genis=0)
        for i in range(WIN_KISA - 1, n):
            a = self._atr[i]
            if not np.isfinite(a) or a <= 0:
                continue                          # main.py: return → analyze ÇAĞRILMAZ
            if self.rejim_kapisi and self._rejim_filtre:
                x = self._adx[i]
                adx_v = float(x) if np.isfinite(x) else 20.0
                if adx_v <= ADX_RANGING:
                    continue                      # bo_allowed=False → analyze ÇAĞRILMAZ
            sub = self.besleme.pencere(i, self.win)   # ← i DAHİL, i+1 ASLA
            try:
                sg = self.s.analyze(sub, float(a)) if self.atr_gerekli else self.s.analyze(sub)
            except Exception:
                continue
            yon = int(getattr(sg, "direction", 0))
            if yon == 0:
                continue
            cl = float(self.besleme.bar(i)[2])
            slp = float(getattr(sg, "sl_price", 0.0) or 0.0)
            tpp = float(getattr(sg, "tp_price", 0.0) or 0.0)
            if slp <= 0 or tpp <= 0:
                continue
            sld = yon * (cl - slp)
            if sld <= 0:
                self.dusen["sld"] += 1
                continue
            rr = yon * (tpp - cl) / sld
            if rr <= 0:
                self.dusen["rr"] += 1
                continue
            if sld / cl > MAX_SL_PCT:
                self.dusen["genis"] += 1
                continue
            out[i] = (yon, sld, rr, self.mh, slp, tpp, self._seviye(sg, cl, yon))
        return out

    def _seviye(self, sg, cl, yon):
        """Canlıda CombinedSignal.entry_price'a konan fiyat (limit emrin durduğu yer)."""
        return cl

    def sinyal(self, i):
        if i < 260 or i >= self.besleme.n - 1:
            return None
        s = self._sig[i]
        if s is None:
            return None
        return s[0], s[1], s[2], s[3]

    # ölçüm araçları için: seviye tabanlı ham sinyal (limit-dolum modeli)
    def ham(self, i):
        if i < 260 or i >= self.besleme.n - 1:
            return None
        return self._sig[i]


class OrbKol(EkKol):
    ad = "orb"; oncelik = 3
    win = WIN_KISA; mh = 6; rejim_kapisi = True; atr_gerekli = False

    def _strateji(self):
        from strategies.orb import OrbStrategy
        return OrbStrategy()

    def _seviye(self, sg, cl, yon):     # main.py: trigger = orb_high/orb_low
        return float(sg.orb_high if yon == 1 else sg.orb_low)


class AsiaKol(EkKol):
    ad = "asia_bo"; oncelik = 4
    win = WIN_KISA; mh = 6; rejim_kapisi = True; atr_gerekli = True

    def _strateji(self):
        from strategies.asia_bo import AsiaBoStrategy
        return AsiaBoStrategy()

    def _seviye(self, sg, cl, yon):     # main.py: trigger = asia_high/asia_low
        return float(sg.asia_high if yon == 1 else sg.asia_low)


class FvgKol(EkKol):
    ad = "fvg"; oncelik = 5
    win = WIN_FVG; mh = 24; rejim_kapisi = False; atr_gerekli = True

    def _strateji(self):
        from strategies.fvg import FvgStrategy
        from config import load_config
        cfg = load_config().strategy
        return FvgStrategy(min_gap_atr=cfg.fvg_min_gap_atr, rr=cfg.fvg_rr)

    def _seviye(self, sg, cl, yon):     # main.py: entry_price = fvg_sig.entry_price
        return float(sg.entry_price)


class SrKol(EkKol):
    ad = "sr_breakout"; oncelik = 6
    win = WIN_KISA; mh = 48; rejim_kapisi = True; atr_gerekli = True

    def _strateji(self):
        from strategies.sr_breakout import SrBreakoutStrategy
        return SrBreakoutStrategy()


EK_SINIF = {"orb": OrbKol, "asia_bo": AsiaKol, "fvg": FvgKol, "sr_breakout": SrKol}


def ek_kollar(adlar=None, coinler=None, src="local", kadar=None, rejim_filtre=True):
    """Ankor DIŞI kollar. Varsayılan: dördü de, canlı 12 coinin HEPSİNDE
    (orb/asia/fvg/sr için .env'de coin allowlist YOK → tüm SYMBOLS)."""
    import deployed_backtest as A
    if coinler is None:
        coinler = A.DONCH + A.SQZ + A.BB_COINS
    if adlar is None:
        adlar = ["orb", "asia_bo", "fvg", "sr_breakout"]
    ks = []
    for ad in adlar:
        C = EK_SINIF[ad]
        for n, c in enumerate(coinler):
            ks.append(C(c, src, n, kadar, rejim_filtre))
    return ks


def tum_kollar(src="local", kadar=None, adlar=None, rejim_filtre=True):
    """ankor (donchian7+squeeze4+bb1) + ankor dışı dört kol."""
    from kronos.kollar import canli_kollar
    return canli_kollar(src, kadar) + ek_kollar(adlar, None, src, kadar, rejim_filtre)


# ══════════════════ ÖZ-DOĞRULAMA ══════════════════
if __name__ == "__main__":
    import sys
    from indicators import atr as atr_fn, adx as adx_fn
    coin = sys.argv[2] if len(sys.argv) > 2 else "SOL"
    src = sys.argv[3] if len(sys.argv) > 3 else "local"
    d = fast_bt.resample(_ham(coin, src, None), "1h")
    h = d["high"].values.astype(float); l = d["low"].values.astype(float)
    c = d["close"].values.astype(float)
    A_, X_ = rolling_atr_adx(h, l, c)
    rng = np.random.default_rng(7)
    ors = rng.choice(np.arange(WIN_KISA - 1, len(c)), size=400, replace=False)
    da, dx = 0.0, 0.0
    for i in ors:
        sub = d.iloc[i - WIN_KISA + 1:i + 1]
        pa = float(atr_fn(sub["high"], sub["low"], sub["close"], ATR_P).iloc[-1])
        px = adx_fn(sub["high"], sub["low"], sub["close"], ADX_P).iloc[-1]
        da = max(da, abs(pa - A_[i]) / max(pa, 1e-12))
        if np.isfinite(px) and np.isfinite(X_[i]):
            dx = max(dx, abs(float(px) - X_[i]) / max(abs(float(px)), 1e-12))
        elif np.isfinite(px) != np.isfinite(X_[i]):
            dx = 9e9
    print(f"{coin}: 400 rastgele barda 120-pencere ATR bağıl fark maks {da:.3e}")
    print(f"{coin}: 400 rastgele barda 120-pencere ADX bağıl fark maks {dx:.3e}")
    print("→", "✓ BİREBİR" if (da < 1e-9 and dx < 1e-9) else "⛔ FARK VAR")


# ══════════════════ LİMİT-DOLUM VARYANTI (canlı orb/asia/fvg gerçeği) ══════════════════
#
# execution.py:596-640 — orb/asia_bo/fvg canlıda POST-ONLY LİMİT ile SEVİYEDEN girer,
# 600 sn bekler, PİYASA YEDEĞİ YOKTUR (fallback_market=False): dolmazsa işlem ATLANIR.
# Dolayısıyla canlı gerçeği: (1) sinyallerin bir kısmı hiç işleme dönüşmez,
# (2) dolanların girişi bar kapanışı DEĞİL SEVİYEDİR, (3) maker → giriş ücreti 0 ve
# giriş KAYMASI 0 (limit emri fiyatından kötüye dolamaz).
#
# Motor girişi her zaman bar kapanışına çakıyor. Bunu BOZMADAN modellemenin yolu:
# kolun Beslemesi SENTETİK bir kapanış sütunuyla kurulur — yalnız DOLUM BARLARINDA
# close := seviye. Böylece motorun e=cl'si tam olarak limit dolum fiyatı olur ve
# slp/tp motorun formülünden stratejinin KENDİ seviyelerine BİREBİR oturur.
# high/low HİÇ DEĞİŞMEZ (çıkış yolu gerçek). Sinyaller GERÇEK veriden önceden
# hesaplandığı için strateji sentetik kapanışı ASLA görmez.
#
# Kalan iki sapma (ölçülüp raporlanır):
#   · süre-çıkışı sentetik bir bara denk gelirse çıkış fiyatı seviyeden alınır
#   · ücret/kayma motorda genel; limit kolları için `limit_duzelt()` ile geri eklenir
def limit_varyant(k):
    """Bir EkKol'dan canlı limit-dolum varyantı üret (sinyal ön-hesabını PAYLAŞIR)."""
    y = object.__new__(type(k))
    y.coin = k.coin; y.sira = k.sira
    y.ad = k.ad + "_L"; y.oncelik = k.oncelik
    y._atr = k._atr; y._adx = k._adx
    y._rejim_filtre = k._rejim_filtre
    y.s = k.s
    y.dolum = "limit"
    d = k.besleme._d
    n = k.besleme.n
    hi = k.besleme._hi; lo = k.besleme._lo
    cl_syn = d["close"].values.astype(float).copy()
    yeni = [None] * n
    say = dict(sinyal=0, dolmadi=0, cakisma=0, geometri=0)
    for i in range(260, n - 1):
        s = k._sig[i]
        if s is None:
            continue
        say["sinyal"] += 1
        yon, _sc, _rc, mh, slp, tpp, L = s
        j = i + 1
        if j >= n - 1:
            continue
        if not (lo[j] <= L <= hi[j]):
            say["dolmadi"] += 1
            continue
        sld = yon * (L - slp)
        rr = (yon * (tpp - L) / sld) if sld > 0 else -1.0
        if sld <= 0 or rr <= 0 or sld / L > MAX_SL_PCT:
            say["geometri"] += 1
            continue
        if yeni[j] is not None:
            say["cakisma"] += 1
            continue
        yeni[j] = (yon, sld, rr, mh, slp, tpp, L)
        cl_syn[j] = L
    d2 = d.copy()
    d2["close"] = cl_syn
    y.besleme = Besleme(d2)
    y._sig = yeni
    y.dusen = say
    y.sentetik = np.array([x is not None for x in yeni])
    return y


def limit_kollar(adlar=None, coinler=None, src="local", kadar=None, rejim_filtre=True):
    return [limit_varyant(k) for k in ek_kollar(adlar, coinler, src, kadar, rejim_filtre)]


def limit_duzelt(islemler, kayma_bp=15.85, fee=0.0001, cap=1.50, bal0=190.0,
                 riskf_kol=None):
    """Limit (maker) kollarının R'sinden motorun HAKSIZ yere düştüğü giriş kayması
    ve giriş ücretini GERİ EKLE. Motor: R = yön(ep−e)/sld − 2·fee·e/sld − kayma/sl_pct.
    Maker girişte doğrusu: R = yön(ep−e)/sld − 1·fee·e/sld.
    → düzeltme = + kayma/sl_pct + fee·e/sld.  Yalnız adı '_L' ile biten kollara uygulanır."""
    ky = kayma_bp / 1e4
    riskf_kol = riskf_kol or {}
    out = []
    for t in islemler:
        R = t.R
        if t.kol.endswith("_L"):
            R = R + ky / t.sl_pct + fee * t.giris / t.sld
        rf = riskf_kol.get(t.kol.replace("_L", ""), 0.028)
        eff = min(rf, cap * t.sl_pct)
        out.append((t.kol, t.coin, t.giris_ts, t.cikis_ts, R, R * eff * bal0, t.sl_pct))
    return out
