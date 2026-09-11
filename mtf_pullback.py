"""
mtf_pullback.py — ÇOK ZAMAN DİLİMLİ PULLBACK GİRİŞİ (yeni GİRİŞ MEKANİZMASI).

REDDEDİLEN "MTF FİLTRESİ"NDEN FARKI: orada donchian KIRILIMINA üst-zaman kapısı
konuyordu (1017 sinyalin 0'ını bloklayan no-op). Burada kırılım YOK: üst zaman
diliminde (4h) trend varken ALT zaman diliminde (1h) GERİ ÇEKİLMEDE giriliyor.

LOOKAHEAD KİLİDİ (kanıtlı): bir 4h barı, ancak KAPANIŞ zamanı 1h barının kapanış
zamanına eşit/önceyse görülebilir.  T4 + 4h <= T1 + 1h.  Uygulama: 4h serisinin
indeksi +4h kaydırılıp (kapanış zamanı) 1h kapanış zamanlarına ffill ile eşlenir.
`dogrula_lookahead()` bunu ZORLA denetler; başarısızsa AssertionError.

Çıkış makinesi A.gen ile BİREBİR: intrabar SL/TP taraması (SL önce), maxhold'da
kapanış, R = d*(ep-e)/sld - 2*FEE*e/sld, per-coin occ (i <= occ ise atla).

Kullanım:  py mtf_pullback.py        # self-test / lookahead denetimi
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
from indicators import atr as atr_fn, ema as ema_fn, rsi as rsi_fn

_RS = {}          # resample önbelleği (coin başına bir kez)
UST_TF = "4h"
ALT_TF = "1h"


# ---------------------------------------------------------------- MTF eşleme
def ust_e_alt(ser4: pd.Series, idx1: pd.DatetimeIndex) -> np.ndarray:
    """4h serisini 1h indeksine LOOKAHEAD'SİZ eşle.

    ser4 4h bar AÇILIŞ etiketleriyle indeksli. Kapanış = etiket + 4h.
    1h barı t'nin kapanışı t + 1h. Görülebilirlik: etiket + 4h <= t + 1h.
    """
    s = ser4.copy()
    s.index = ser4.index + pd.Timedelta(UST_TF)          # kapanış zamanı
    return s.reindex(idx1 + pd.Timedelta(ALT_TF), method="ffill").values


def dogrula_lookahead(d4: pd.DataFrame, d1: pd.DataFrame) -> None:
    """Eşlemenin gerçekten geçmişe baktığını KANITLA (assert, öneri değil).

    ⚠ ARAÇ HATASI #1 (yakalandı): ilk sürümde 4h etiketleri ns tamsayısı olarak
    eşlendi; reindex NaN üretince float64'e yükseltti ve 1.7e18 ns float64'te
    ~190 ns çözünürlükte YUVARLANDI → sahte "lookahead" alarmı. Şimdi KONUM
    indeksi (0..len-1, küçük tamsayı) eşleniyor, yuvarlanma yok.
    """
    s = pd.Series(np.arange(len(d4), dtype=float), index=d4.index + pd.Timedelta(UST_TF))
    pos = s.reindex(d1.index + pd.Timedelta(ALT_TF), method="ffill").values
    ok = np.isfinite(pos)
    lab = d4.index[pos[ok].astype(int)]
    kap = lab + pd.Timedelta(UST_TF)
    alt = (d1.index + pd.Timedelta(ALT_TF))[ok]
    assert (kap <= alt).all(), "LOOKAHEAD: 4h barı 1h barından SONRA kapanıyor"
    gec = (alt - kap)
    assert gec.max() <= pd.Timedelta("6h"), f"eşleme çok geride: {gec.max()}"
    assert set(pd.Series(gec).unique()) <= {pd.Timedelta(h, "h") for h in range(4)}, \
        "gecikme 0-3 saat DIŞINDA — veri boşluğu ya da eşleme hatası"


# ---------------------------------------------------------------- üretici
def uret(coin, m, trend="T1", tetik="ema20", stop=("atr", 2.0), rr=2.5,
         mh=48, rsi_esik=40.0, swing_k=10, min_atr=0.5, max_atr=4.0,
         rnd=None, gun_kapi=False):
    """MTF-pullback sinyalleri.

    trend : 'T1' = close4>ema200_4 ve ema50_4>ema200_4
            'T2' = close4>ema200_4
            'T3' = T1 + ema50_4 eğimi yukarı (son 6 4h barı)
    tetik : 'ema20' / 'ema50' = 1h EMA'ya DOKUNUP kapanışta geri dönüş
            'rsi'             = RSI(14) esikten aşağı sarkıp kapanışta geri üstüne
    stop  : ('atr', k) → k×ATR(1h);  ('swing', k) → son k barın dibi (ATR ile
            kırpılır: min_atr..max_atr × ATR) — ikisi de brief'te isteniyor.
    rnd   : numpy Generator verilirse TETİK YOK SAYILIR; trend-uygun barlardan
            aynı SAYIDA bar RASTGELE seçilir (permütasyon kontrolü).
    """
    key = id(m)
    if key in _RS:
        d1, d4 = _RS[key]
    else:
        d1 = fast_bt.resample(m, ALT_TF); d4 = fast_bt.resample(m, UST_TF)
        _RS[key] = (d1, d4)
    if len(d4) < 300 or len(d1) < 300:
        return []

    c4 = d4["close"]
    e200_4 = ema_fn(c4, 200); e50_4 = ema_fn(c4, 50)
    up4_raw = (c4 > e200_4) & (e50_4 > e200_4)
    dn4_raw = (c4 < e200_4) & (e50_4 < e200_4)
    if trend == "T2":
        up4_raw = c4 > e200_4; dn4_raw = c4 < e200_4
    elif trend == "T3":
        sl50 = e50_4.diff(6)
        up4_raw = up4_raw & (sl50 > 0); dn4_raw = dn4_raw & (sl50 < 0)
    hazir = e200_4.notna() & (np.arange(len(c4)) >= 200)
    up4_raw = up4_raw & hazir; dn4_raw = dn4_raw & hazir

    idx = d1.index
    up = ust_e_alt(up4_raw.astype(float), idx)
    dn = ust_e_alt(dn4_raw.astype(float), idx)
    up = np.nan_to_num(up) > 0.5; dn = np.nan_to_num(dn) > 0.5

    hi = d1["high"].values; lo = d1["low"].values; cl = d1["close"].values
    n = len(cl)
    a1 = atr_fn(d1["high"], d1["low"], d1["close"], 14).values

    # günlük EMA20 kapısı (ankorun MTF'si) — opsiyonel ek kapı
    if gun_kapi:
        _dc = d1["close"].resample("1D").last().dropna()
        _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(idx.normalize()).values
        gup = cl > _dprev
        gup = np.where(np.isnan(_dprev), True, gup)
    else:
        gup = None

    # tetik dizileri
    if tetik in ("ema20", "ema50"):
        p = 20 if tetik == "ema20" else 50
        ev = ema_fn(d1["close"], p).values
        # LONG: bar dibi EMA'ya DOKUNDU ama kapanış EMA ÜSTÜNDE; önceki bar da üstünde
        prev_ust = np.concatenate([[False], cl[:-1] > ev[:-1]])
        prev_alt = np.concatenate([[False], cl[:-1] < ev[:-1]])
        tl = (lo <= ev) & (cl > ev) & prev_ust
        ts = (hi >= ev) & (cl < ev) & prev_alt
    elif tetik == "stoch":
        # Stochastic %K(14) 3-bar SMA yumuşatma; aşırı satım 20 / aşırı alım 80
        ll = d1["low"].rolling(14).min(); hh = d1["high"].rolling(14).max()
        k = (100 * (d1["close"] - ll) / (hh - ll).replace(0, np.nan)).rolling(3).mean().values
        prev = np.concatenate([[np.nan], k[:-1]])
        tl = (prev < 20.0) & (k >= 20.0)
        ts = (prev > 80.0) & (k <= 80.0)
    elif tetik == "rsi":
        rv = rsi_fn(d1["close"], 14).values
        prev = np.concatenate([[np.nan], rv[:-1]])
        tl = (prev < rsi_esik) & (rv >= rsi_esik)
        ts = (prev > 100 - rsi_esik) & (rv <= 100 - rsi_esik)
    else:
        raise ValueError(tetik)
    tl = np.nan_to_num(tl.astype(float)) > 0.5
    ts = np.nan_to_num(ts.astype(float)) > 0.5

    sig_l = tl & up
    sig_s = ts & dn
    if gup is not None:
        sig_l = sig_l & gup; sig_s = sig_s & (~gup)

    if rnd is not None:
        # PERMÜTASYON: aynı sayıda sinyal, trend-uygun barlardan RASTGELE
        havuz_l = np.where(up)[0]; havuz_s = np.where(dn)[0]
        kl = min(int(sig_l.sum()), len(havuz_l)); ks = min(int(sig_s.sum()), len(havuz_s))
        sig_l = np.zeros(n, bool); sig_s = np.zeros(n, bool)
        if kl: sig_l[rnd.choice(havuz_l, kl, replace=False)] = True
        if ks: sig_s[rnd.choice(havuz_s, ks, replace=False)] = True

    styp, sk = stop
    if styp == "swing":
        swl = pd.Series(lo).rolling(swing_k).min().values
        swh = pd.Series(hi).rolling(swing_k).max().values

    out = []; occ = -1
    cand = np.where(sig_l | sig_s)[0]
    for i in cand:
        i = int(i)
        if i < 260 or i >= n - 1 or i <= occ: continue
        a = a1[i]
        if not np.isfinite(a) or a <= 0: continue
        d_ = 1 if sig_l[i] else -1
        e = cl[i]
        if styp == "atr":
            sld = sk * a
        else:
            ref = swl[i] if d_ == 1 else swh[i]
            if not np.isfinite(ref): continue
            sld = (e - ref) if d_ == 1 else (ref - e)
            sld = float(np.clip(sld, min_atr * a, max_atr * a))
        if sld <= 0: continue
        slp_ = e - d_ * sld; tp = e + d_ * rr * sld
        ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp_: ep = slp_; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp_: ep = slp_; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * A.FEE * e / sld
        out.append((idx[i].value, idx[j], R, sld / e)); occ = j
    return out


if __name__ == "__main__":
    m = fast_bt.load("SOL", source="local")
    d1 = fast_bt.resample(m, ALT_TF); d4 = fast_bt.resample(m, UST_TF)
    dogrula_lookahead(d4, d1)
    print("  ✓ lookahead denetimi GEÇTİ (4h→1h eşlemesi kapanış-zamanı kilitli)")
    for tt in ("ema20", "ema50", "rsi"):
        t = uret("SOL", m, tetik=tt)
        R = np.array([x[2] for x in t])
        print(f"  SOL {tt:6s}: n={len(t):4d}  ortR {R.mean():+.4f}  WR %{(R>0).mean()*100:.1f}")
