"""
ay_veri.py — kötü ay araştırmasının ORTAK VERİ TABANI.

Ankorun 1579 işlemini, her birinin GİRİŞ ANINDAKİ piyasa koşullarıyla birlikte
tek bir CSV'ye yazar. Sonraki her analiz bu dosyayı okur — böylece hepsi
BİREBİR AYNI işlem kümesine bakar ve "farklı sonuç mu, farklı veri mi"
sorusu ortadan kalkar.

⚠ LOOKAHEAD YOK: her özellik yalnız i barına KADAR olan veriden hesaplanıyor.
   Bir özellik i+1'i görürse tüm araştırma çöp olur. Her pencere i'de bitiyor.

⚠ seat_select BURADA YENİDEN YAZILDI çünkü orijinali kimliği (hangi coin,
   hangi kol) kaybediyor. Replika BİREBİR aynı olmalı:
     · sorted(key=t[0]) STABLE → eşit girişte liste sırası belirleyici
     · liste sırası DONCH → SQZ → BB (deployed_backtest.main ile aynı)
     · heap anahtarı (exit_ts, ctr, R) — ctr eşitliği kırar
   Doğrulama: seçilen R dizisi ankorunkiyle BİREBİR eşit olmalı, yoksa çöker.

Kullanım:  py ay_veri.py local
Çıktı:     data/ay_analiz.csv
"""
import heapq
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
from indicators import atr as atr_fn, adx as adx_fn

CIKTI = "data/ay_analiz.csv"


# ─────────────────────────── özellikler ───────────────────────────
def ozellikler(d):
    """Bar bazında, i'ye kadar olan veriden. Hepsi hizalı np dizileri döner."""
    hi, lo, cl = d["high"].values, d["low"].values, d["close"].values
    n = len(cl)
    o = {}
    o["adx14"] = adx_fn(d["high"], d["low"], d["close"], 14).values
    atr14 = atr_fn(d["high"], d["low"], d["close"], 14).values
    o["atr_pct"] = atr14 / cl

    # ATR'nin kendi normuna oranı — "bugün normalden oynak mı"
    atr_ort = pd.Series(atr14).rolling(100, min_periods=50).mean().values
    o["atr_norm"] = atr14 / atr_ort

    # Kaufman verimlilik oranı: |net yol| / |toplam yol|. 1=düz trend, 0=testere.
    for w in (20, 50):
        net = np.abs(cl - np.roll(cl, w))
        yol = pd.Series(np.abs(np.diff(cl, prepend=cl[0]))).rolling(w).sum().values
        er = np.divide(net, yol, out=np.full(n, np.nan), where=yol > 0)
        er[:w] = np.nan
        o[f"er{w}"] = er

    # Donchian kanalı (40) ve bar konumu
    ch_hi = pd.Series(hi).rolling(40).max().values
    ch_lo = pd.Series(lo).rolling(40).min().values
    gen = ch_hi - ch_lo
    o["kanal_konum"] = np.divide(cl - ch_lo, gen, out=np.full(n, np.nan), where=gen > 0)
    o["kanal_atr"] = np.divide(gen, atr14, out=np.full(n, np.nan), where=atr14 > 0)

    # Sıkışma: son 40 barın kaçı ÖNCEKİ 40-bar kanalının içinde kapandı.
    # Ledger'ın "chop" tarifi buydu. shift(1) ile kendi barını görmüyor.
    ph = pd.Series(hi).rolling(40).max().shift(1)
    pl = pd.Series(lo).rolling(40).min().shift(1)
    icinde = ((pd.Series(cl) <= ph) & (pd.Series(cl) >= pl)).astype(float)
    o["ic_oran40"] = icinde.rolling(40).mean().values

    # Gerçekleşen oynaklık (log getiri std, 20 bar)
    lr = np.log(cl / np.roll(cl, 1)); lr[0] = np.nan
    o["rvol20"] = pd.Series(lr).rolling(20).std().values

    # EMA200'e uzaklık, ATR cinsinden — trendin neresindeyiz
    ema200 = pd.Series(cl).ewm(span=200, adjust=False).mean().values
    o["ema200_atr"] = np.divide(cl - ema200, atr14, out=np.full(n, np.nan), where=atr14 > 0)

    # Son 20 bar getirisi (momentum bağlamı)
    o["get20"] = cl / np.roll(cl, 20) - 1.0
    o["get20"][:20] = np.nan
    return o


def btc_baglam(tf, source):
    """BTC aynı zaman diliminde: rejimin piyasa geneli hâli."""
    b = fast_bt.resample(fast_bt.load("BTC", source=source), tf)
    bo = ozellikler(b)
    return pd.DataFrame({"btc_adx": bo["adx14"], "btc_er20": bo["er20"],
                         "btc_get20": bo["get20"], "btc_atr_pct": bo["atr_pct"],
                         "btc_ic40": bo["ic_oran40"]}, index=b.index)


# ─────────────────────── kimlikli sinyal üretimi ───────────────────────
def uret(sleeve, coin, m, source):
    """A.gen ile BİREBİR aynı mekanik + giriş anı özellikleri."""
    tf, win, sl_a, rr, mh = A.CFG[sleeve]
    d = fast_bt.resample(m, tf)
    o = ozellikler(d)
    btc = btc_baglam(tf, source).reindex(d.index, method="ffill")
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = o["adx14"]
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
    from strategies.donchian import DonchianStrategy
    from strategies.squeeze import SqueezeStrategy
    s = (DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve == "donchian" else
         SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    hi, lo, cl, idx, n = d["high"].values, d["low"].values, d["close"].values, d.index, len(d)
    out = []; occ = -1
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        if sleeve == "squeeze":
            xv = adx_ser[i] if np.isfinite(adx_ser[i]) else 20.0
            if xv <= 20.0: continue
        sg = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)); d_ = sg.direction
        if d_ == 0 or i <= occ: continue
        if sleeve == "donchian":
            dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
            if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue
        e = cl[i]; sld = sl_a * a; slp_ = e - d_ * sld; tp = e + d_ * rr * sld; ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp_: ep = slp_; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp_: ep = slp_; break
                if lo[j] <= tp: ep = tp; break
        cikis = "tp" if ep is not None and ((d_ == 1 and ep == tp) or (d_ == -1 and ep == tp)) else None
        if ep is None:
            j = min(i + mh, n - 1); ep = cl[j]; cikis = "sure"
        elif cikis is None:
            cikis = "sl"
        R = d_ * (ep - e) / sld - 2 * A.FEE * e / sld
        meta = {"coin": coin, "kol": sleeve, "yon": d_, "cikis": cikis,
                "bar": int(j - i), "giris": idx[i], "tf": tf}
        for k, v in o.items():
            meta[k] = float(v[i]) if np.isfinite(v[i]) else np.nan
        for k in btc.columns:
            val = btc[k].values[i]
            meta[k] = float(val) if np.isfinite(val) else np.nan
        out.append((idx[i].value, idx[j], R, sld / e, meta)); occ = j
    return out


def uret_bb(coin, m, source):
    """A.gen_bb ile birebir + özellikler."""
    from indicators import bollinger_bands
    from strategies.mean_reversion import MeanReversionStrategy
    from config import load_config
    s = MeanReversionStrategy(load_config().strategy)
    d = fast_bt.resample(m, A.BB_TF)
    o = ozellikler(d)
    btc = btc_baglam(A.BB_TF, source).reindex(d.index, method="ffill")
    hi, lo, cl, idx, n = d["high"].values, d["low"].values, d["close"].values, d.index, len(d)
    up_b, _mid, lo_b = bollinger_bands(d["close"], 20, 2.0)
    outside = (cl < lo_b.values) | (cl > up_b.values)
    volma = d["volume"].rolling(20).mean().values
    volok = ~(np.isfinite(volma) & (d["volume"].values < volma))
    out = []; occ = -1
    for i in np.where(outside & volok)[0]:
        i = int(i)
        if i < 260 or i >= n - 1 or i <= occ: continue
        if idx[i].weekday() < 5: continue
        sub = d.iloc[max(0, i - 119):i + 1]
        av = atr_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if not np.isfinite(av) or av <= 0: continue
        adxr = adx_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if (float(adxr) if np.isfinite(adxr) else 20.0) >= A.BB_ADX_MAX: continue
        d_ = s.analyze(sub).direction
        if d_ == 0: continue
        a = float(av); sld = A.BB_SL_ATR * a
        e = cl[i]; slp_ = e - d_ * sld; tp = e + d_ * A.BB_RR * sld; ep = None; j = i
        for j in range(i + 1, min(i + 1 + A.BB_MH, n)):
            if d_ == 1:
                if lo[j] <= slp_: ep = slp_; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp_: ep = slp_; break
                if lo[j] <= tp: ep = tp; break
        cikis = "tp" if ep is not None and ep == tp else None
        if ep is None:
            j = min(i + A.BB_MH, n - 1); ep = cl[j]; cikis = "sure"
        elif cikis is None:
            cikis = "sl"
        R = d_ * (ep - e) / sld - 2 * A.FEE * e / sld
        meta = {"coin": coin, "kol": "bb", "yon": d_, "cikis": cikis,
                "bar": int(j - i), "giris": idx[i], "tf": A.BB_TF}
        for k, v in o.items():
            meta[k] = float(v[i]) if np.isfinite(v[i]) else np.nan
        for k in btc.columns:
            val = btc[k].values[i]
            meta[k] = float(val) if np.isfinite(val) else np.nan
        out.append((idx[i].value, idx[j], R, sld / e, meta)); occ = j
    return out


def koltuk_sec(ham):
    """A.seat_select'in KİMLİK KORUYAN replikası. Mekanik birebir aynı olmalı."""
    ev = sorted(ham, key=lambda t: t[0])       # STABLE — eşitlikte liste sırası
    openh = []; taken = []; ctr = 0
    for entry_ns, exit_ts, R, slp, meta in ev:
        while openh and openh[0][0].value <= entry_ns: heapq.heappop(openh)
        if len(openh) < A.MAXPOS:
            ctr += 1
            heapq.heappush(openh, (exit_ts, ctr, R))
            taken.append((exit_ts, R, slp, meta))
    return sorted(taken, key=lambda t: t[0])


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    ham = []
    for c in A.DONCH: ham += uret("donchian", c, fast_bt.load(c, source=source), source)
    for c in A.SQZ:   ham += uret("squeeze",  c, fast_bt.load(c, source=source), source)
    for c in A.BB_COINS: ham += uret_bb(c, fast_bt.load(c, source=source), source)

    taken = koltuk_sec(ham)
    if len(taken) != 1579:
        print(f"✗ ÇIPA BOZUK: {len(taken)} işlem, 1579 bekleniyordu. YAZMIYORUM.")
        sys.exit(2)

    # ── ankora karşı BİREBİR doğrulama ──
    ref = []
    for c in A.DONCH: ref += A.gen("donchian", fast_bt.load(c, source=source))
    for c in A.SQZ:   ref += A.gen("squeeze",  fast_bt.load(c, source=source))
    for c in A.BB_COINS: ref += A.gen_bb(fast_bt.load(c, source=source))
    ref_t = A.seat_select(ref)
    r_ref = np.array([R for _, R, _ in ref_t])
    r_mine = np.array([t[1] for t in taken])
    if not np.allclose(r_ref, r_mine, rtol=0, atol=1e-12):
        kac = int((~np.isclose(r_ref, r_mine, rtol=0, atol=1e-12)).sum())
        print(f"✗ REPLİKA SAPTI: {kac}/1579 R değeri farklı. Özellik tablosu GÜVENİLMEZ.")
        sys.exit(2)

    sat = []
    for exit_ts, R, slp, meta in taken:
        row = dict(meta)
        row["R"] = R; row["slp"] = slp; row["cikis_ts"] = exit_ts
        row["eff"] = min(A.CANLI_RISKF, A.CANLI_CAP * slp)
        row["pnl_pct"] = R * row["eff"] * 100
        row["ay"] = str(pd.Timestamp(exit_ts).tz_localize(None).to_period("M"))
        sat.append(row)
    df = pd.DataFrame(sat)
    df.to_csv(CIKTI, index=False)
    print(f"\n  ✓ {len(df)} işlem · R dizisi ankorla BİREBİR eşit · → {CIKTI}")
    print(f"  kolonlar ({len(df.columns)}): {', '.join(df.columns)}")
    ay = df.groupby("ay")["pnl_pct"].sum()
    print(f"  {len(ay)} ay · artı {int((ay > 0).sum())} · eksi {int((ay < 0).sum())} · "
          f"toplam %{ay.sum():.1f}")


if __name__ == "__main__":
    main()
