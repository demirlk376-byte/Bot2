"""
ON ELEME — yalnizca SINYAL seviyesinde, 4h barlarda ileri yuruyus.

⚠ BU BIR KARAR ARACI DEGIL. Karar her zaman IKIZ'dendir.
Burada OLMAYAN seyler: sermaye/bilesik getiri, pozisyon boyutlandirma,
sembol basina tek-pozisyon kisiti, soguma (cooldown), diger kollar, gunluk
kayip limiti, maker/taker yonlendirme, funding. Yani buradaki R ortalamasi
IKIZ'in ureteceginin yerine GECMEZ.

NE ISE YARAR: bir modun R ortalamasi acikca negatifse ya da islem sayisi
tespit tabaninin altindaysa, o modu IKIZ'de 50 dakika kosturmanin anlami
yoktur. Amac saatleri bosa harcamamak.

MEKANIK (canliyla ayni):
  giris  = kapanis, 15.85bp kayma ile (olculdu, n=54)
  SL     = 2.0 x ATR(14,4h),  TP = RR 2.0 x SL mesafesi
  max tut= 120 saat = 30 x 4h bar
  ayni barda hem SL hem TP goruldu ise SL sayilir (muhafazakar) ve orani
  ayrica raporlanir.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strategies.donchian import DonchianStrategy

KAYMA_BP = 15.85          # olculdu 2026-09-22, n=54
MAX_BAR = 30              # 30 x 4h = 120h
# ⚠ DUZELTILDI 2026-09-22. Once 8.0bp yazmistim ("taker gidis-donus %0.08");
# MEXC VADELI oyle degil: exchange.py:140-141 -> taker %0.01 (1bp), MAKER %0.
# Sabit terim oldugu icin bugunku KARSILASTIRMALARI bozmadi (tum satirlarda
# ayni, siralama degismez) ama dar stoplu kurulumlarda olumcul olurdu:
# 6bp fazla / %0.55 stop = 0.109R -- edge'in yarisi kadar hayali maliyet.
KOMISYON_TAKER_BP = 1.0   # exchange.py:140  FEE_RATE
KOMISYON_MAKER_BP = 0.0   # exchange.py:141  FEE_MAKER (MEXC vadeli maker %0)
CIKIS_KAYMA_BP = 0.24     # olculdu n=67, 2026-09-22
KOMISYON_BP = 2.0         # piyasa giris + piyasa cikis (eski isim korundu)


def _dortsaat(sembol: str) -> pd.DataFrame | None:
    yol = os.path.join("data", f"{sembol}_fut_1h.csv")
    if not os.path.exists(yol):
        return None
    d = pd.read_csv(yol)
    d.index = pd.to_datetime(d["ts"], utc=True)
    d = d[["open", "high", "low", "close", "volume"]].astype("float64")
    return d.resample("4h").agg({"open": "first", "high": "max", "low": "min",
                                 "close": "last", "volume": "sum"}).dropna()


def _atr(d4: pd.DataFrame) -> pd.Series:
    tr = pd.concat([d4.high - d4.low,
                    (d4.high - d4.close.shift(1)).abs(),
                    (d4.low - d4.close.shift(1)).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / 14, adjust=False).mean()


def kos(sembol: str, mod: str, ters_trend: bool, **kw):
    d4 = _dortsaat(sembol)
    if d4 is None or len(d4) < 300:
        return []
    atr = _atr(d4)
    s = DonchianStrategy(mod=mod, ters_trend=ters_trend, **kw)
    h, l = d4.high.values, d4.low.values
    islemler = []
    i = 260
    while i < len(d4) - 1:
        sig = s.analyze(d4.iloc[: i + 1], float(atr.iloc[i]))
        if not sig.direction:
            i += 1
            continue
        yon = sig.direction
        giris = sig.entry_price * (1 + yon * KAYMA_BP / 1e4)   # kayma HEP aleyhe
        sl, tp = sig.sl_price, sig.tp_price
        risk = abs(giris - sl)
        if risk <= 0:
            i += 1
            continue
        cikis_r, sebep, ikili = None, "", False
        for j in range(i + 1, min(i + 1 + MAX_BAR, len(d4))):
            sl_var = (l[j] <= sl) if yon > 0 else (h[j] >= sl)
            tp_var = (h[j] >= tp) if yon > 0 else (l[j] <= tp)
            if sl_var and tp_var:
                ikili = True
            if sl_var:
                cikis_r, sebep = -1.0, "sl"
                break
            if tp_var:
                cikis_r, sebep = abs(tp - giris) / risk, "tp"
                break
        else:
            j = min(i + MAX_BAR, len(d4) - 1)
            cikis_r = yon * (d4.close.values[j] - giris) / risk
            sebep = "max_hold"
        islemler.append({"ts": d4.index[i], "yon": yon, "r": cikis_r - KOMISYON_BP / 1e4 * giris / risk,
                         "sebep": sebep, "ikili": ikili, "bar": j - i})
        i = j + 1      # pozisyon kapanana kadar yeni sinyal alinmaz
    return islemler


def ozet(ad, islemler):
    if not islemler:
        return f"  {ad:34s}  SINYAL YOK"
    r = np.array([t["r"] for t in islemler])
    n = len(r)
    kazanc, kayip = r[r > 0], r[r <= 0]
    pf = (kazanc.sum() / -kayip.sum()) if len(kayip) and kayip.sum() < 0 else float("inf")
    hata = r.std(ddof=1) / np.sqrt(n) if n > 1 else float("nan")
    tp = 100 * sum(t["sebep"] == "tp" for t in islemler) / n
    sl = 100 * sum(t["sebep"] == "sl" for t in islemler) / n
    ikili = 100 * sum(t["ikili"] for t in islemler) / n
    return (f"  {ad:34s}  n={n:5d}  WR={100*(r>0).mean():5.1f}%  PF={pf:5.2f}  "
            f"R/islem={r.mean():+.4f} ±{1.96*hata:.4f}  netR={r.sum():+8.1f}  "
            f"TP={tp:4.1f}% SL={sl:4.1f}%  ayni-bar={ikili:4.1f}%")


if __name__ == "__main__":
    semboller = sys.argv[1:] or ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "XLM", "TRX"]
    kurulum = [("kirilim", True), ("basarisiz", True), ("basarisiz", False),
               ("supurme", True), ("supurme", False)]
    print(f"\n=== DONCHIAN GIRIS MODU ON ELEMESI · {', '.join(semboller)}")
    print("=== ⚠ KARAR ARACI DEGIL: sermaye/kisit/diger kollar YOK. Karar IKIZ'den.\n")
    for mod, tt in kurulum:
        hepsi = []
        for s in semboller:
            hepsi += kos(s, mod, tt)
        ad = f"{mod} ters_trend={'acik' if tt else 'kapali'}"
        print(ozet(ad + ("  <- BUGUNKU" if mod == "kirilim" else ""), hepsi))
    print()


# ==========================================================================
#  SQUEEZE giris modu on elemesi (1h)
# ==========================================================================
SQ_MAX_BAR = 48           # MAX_HOLD_CANDLES = 48 x 1h


def _birsaat(sembol: str):
    yol = os.path.join("data", f"{sembol}_fut_1h.csv")
    if not os.path.exists(yol):
        return None
    d = pd.read_csv(yol)
    d.index = pd.to_datetime(d["ts"], utc=True)
    return d[["open", "high", "low", "close", "volume"]].astype("float64")


def kos_squeeze(sembol: str, **kw):
    from strategies.squeeze import SqueezeStrategy
    d = _birsaat(sembol)
    if d is None or len(d) < 400:
        return []
    tr = pd.concat([d.high - d.low, (d.high - d.close.shift(1)).abs(),
                    (d.low - d.close.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    s = SqueezeStrategy(**kw)
    h, l = d.high.values, d.low.values
    pencere = 400
    out, i = pencere, pencere
    out = []
    while i < len(d) - 1:
        sig = s.analyze(d.iloc[i - pencere + 1: i + 1], float(atr.iloc[i]))
        if not sig.direction:
            i += 1
            continue
        yon = sig.direction
        giris = sig.entry_price * (1 + yon * KAYMA_BP / 1e4)
        sl, tp = sig.sl_price, sig.tp_price
        risk = abs(giris - sl)
        if risk <= 0:
            i += 1
            continue
        r, sb, ikili = None, "", False
        for j in range(i + 1, min(i + 1 + SQ_MAX_BAR, len(d))):
            slv = (l[j] <= sl) if yon > 0 else (h[j] >= sl)
            tpv = (h[j] >= tp) if yon > 0 else (l[j] <= tp)
            if slv and tpv:
                ikili = True
            if slv:
                r, sb = -1.0, "sl"
                break
            if tpv:
                r, sb = abs(tp - giris) / risk, "tp"
                break
        else:
            j = min(i + SQ_MAX_BAR, len(d) - 1)
            r = yon * (d.close.values[j] - giris) / risk
            sb = "max_hold"
        out.append({"r": r - KOMISYON_BP / 1e4 * giris / risk, "sebep": sb,
                    "yon": yon, "bar": j - i, "ikili": ikili})
        i = j + 1
    return out


# ==========================================================================
#  YAPI ZINCIRI on elemesi (1h):  supurme -> MSS -> [FVG] -> limit retest
# ==========================================================================
YAPI_MAX_BAR = 48         # MAX_HOLD_CANDLES = 48 x 1h


def kos_yapi(sembol: str, dolum_payi_atr: float = 0.0, **kw):
    """⚠ LIMIT GIRISTE KAYMA YOK. Bu varsayim degil, bu depoda CANLIDA
    olculdu: limitle giren kollar (fvg/orb/sr) 0.0bp, piyasa emriyle giren
    donchian +13.4bp. Zincirin en guclu argumani bu -- o yuzden dolum
    modeli MUHAFAZAKAR: emir ancak fiyat seviyeye DEGERSE dolar, dolum
    barinda SL de gorulduyse SL sayilir."""
    from strategies.yapi import kurulumlari_bul
    d = _birsaat(sembol)
    if d is None or len(d) < 500:
        return []
    tr = pd.concat([d.high - d.low, (d.high - d.close.shift(1)).abs(),
                    (d.low - d.close.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean().to_numpy()
    h, l, c = d.high.values, d.low.values, d.close.values
    kurulumlar = kurulumlari_bul(h, l, c, atr, **kw)

    out, mesgul_bitis, gorulen = [], -1, set()
    for K in sorted(kurulumlar, key=lambda x: (x.mss_bar, x.supurme_bar)):
        if (K.mss_bar, K.yon) in gorulen:     # ayni MSS'i iki kez alma
            continue
        gorulen.add((K.mss_bar, K.yon))
        if K.mss_bar <= mesgul_bitis:          # sembol basina TEK pozisyon
            continue

        # --- dolum
        if K.limit_mi:
            # ⚠ DEGMEK DOLMAK DEGILDIR. `dolum_payi_atr` fiyatin seviyeyi
            # GECMESINI sart kosar. Sifir birakmak iyimser bir varsayimdir ve
            # tam da en derin retest'te (fiyatin ucundan degdigi yerde) en cok
            # sisirir -- yani "derin retest daha iyi" sonucunu KENDI YANLILIGI
            # uretebilir. Duyarlilik bu parametreyle olculur.
            pay = dolum_payi_atr * (atr[K.mss_bar] if atr[K.mss_bar] > 0 else 0.0)
            esik = K.giris - pay if K.yon > 0 else K.giris + pay
            gi = None
            for t in range(K.mss_bar + 1, K.gecerlilik_bar + 1):
                deger = (l[t] <= esik) if K.yon > 0 else (h[t] >= esik)
                if deger:
                    gi = t
                    break
            if gi is None:
                continue                        # emir dolmadi -> islem YOK
            giris = K.giris                     # dinlenen limit: kayma yok
        else:
            gi = K.mss_bar
            giris = K.giris * (1 + K.yon * KAYMA_BP / 1e4)

        risk = abs(giris - K.sl)
        if risk <= 0:
            continue
        tp = giris + K.yon * VARS_RR * risk if not K.limit_mi else K.tp
        r, sb, ikili = None, "", False
        # dolum barinin KENDISI de kontrol edilir (limit dolduktan sonra
        # ayni barda stop gorulmus olabilir)
        for j in range(gi, min(gi + 1 + YAPI_MAX_BAR, len(d))):
            slv = (l[j] <= K.sl) if K.yon > 0 else (h[j] >= K.sl)
            tpv = (h[j] >= tp) if K.yon > 0 else (l[j] <= tp)
            if j == gi and not K.limit_mi:
                continue                        # giris bari: piyasa girisinde atla
            if slv and tpv:
                ikili = True
            if slv:
                r, sb = -1.0, "sl"
                break
            if tpv:
                r, sb = abs(tp - giris) / risk, "tp"
                break
        else:
            j = min(gi + YAPI_MAX_BAR, len(d) - 1)
            r = K.yon * (c[j] - giris) / risk
            sb = "max_hold"
        # giris: limit -> maker (%0), piyasa -> taker. cikis: her zaman taker.
        # TP dinlenen bir limittir -> cikis kaymasi yalnizca SL/max_hold'da.
        maliyet_bp = (KOMISYON_MAKER_BP if K.limit_mi else KOMISYON_TAKER_BP) \
                     + KOMISYON_TAKER_BP \
                     + (0.0 if sb == "tp" else CIKIS_KAYMA_BP)
        out.append({"r": r - maliyet_bp / 1e4 * giris / risk, "sebep": sb,
                    "yon": K.yon, "bar": j - gi, "ikili": ikili,
                    "limit": K.limit_mi, "stop_pct": 100 * risk / giris,
                    "maliyet_r": maliyet_bp / 1e4 * giris / risk})
        mesgul_bitis = j
    return out


VARS_RR = 2.0
