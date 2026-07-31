"""
dispersion_regime.py — GOREV B: KESITSEL DAGILIM (dispersion) bir rejim gostergesi mi?

Simdiye kadar denenen her rejim olcusu TEK COIN'in kendi verisinden geldi (ADX, ATR,
kanal genisligi) ve hepsi anti-persistent cikti (ADX ay-ay otokorelasyon -0.379).
Kesitsel dagilim FARKLI bir bilgi kaynagi: coinler BIRBIRINDEN ne kadar ayrisiyor?

Olculen 3 sey (11 deploy coininin GUNLUK getirilerinden, kayan 20-gunluk pencere):
  (a) avgcorr : ortalama ikili korelasyon (dusuk = ayrisma = trend olabilir)
  (b) xsdisp  : kesitsel getiri dagilimi (gunluk getirilerin coinler-arasi std'si)
  (c) pc1     : ilk ozdeger orani (lambda1 / toplam) = "tek faktor" hakimiyeti

LOOKAHEAD YOK: gun D icin gecerli deger, D-1 kapanisina kadarki getirilerden hesaplanir
(.shift(1)). Sinyal anindaki karar bu degeri kullanir.

Kabul sarti (gorevde verilen): ONCEKI ay sonu degeri ile SONRAKI ay PnL'i arasinda
|kor| > 0.35 VE gostergenin kendi otokorelasyonu > +0.2.

Kullanim: python dispersion_regime.py
"""
from __future__ import annotations
import heapq
import numpy as np
import pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

# ---- deployed_backtest.py ile BIREBIR config ----
BAL0 = 190.0; FEE = 0.0001; RISKF = 0.0225; MAXPOS = 7; CAP = 1.25
DONCH = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB"]
SQZ = ["XRP", "DOGE", "TRX", "XLM"]
ALL = DONCH + SQZ
CFG = {"donchian": ("4h", 259, 2.0, 2.5, 30), "squeeze": ("1h", 119, 2.0, 2.5, 48)}
WIN = 20          # kayan pencere (gun)
SRC = "local"


# ======================================================================
# 1) SINYAL URETIMI (deployed_backtest.gen ile birebir; ek olarak entry ts saklanir
#    ve opsiyonel SINYAL-ANI filtresi -- elenen sinyal occ'u ILERLETMEZ)
# ======================================================================
def raw_signals(sleeve, m, coin):
    """occ UYGULANMADAN tum ham sinyaller + her birinin cikis bari.
    occ zinciri sinyal kumesini ETKILEMEZ (analyze her barda cagriliyor, occ testi
    sonra geliyor) ve bir sinyalin cikis bari j de occ'tan bagimsiz -> once hepsini
    hesapla, sonra her filtre varyantinda occ zincirini ucuza yeniden oynat.
    Bu, deployed_backtest.gen ile MATEMATIKSEL OLARAK AYNI sonucu verir (asagida
    _selftest ile taban uzerinde dogrulanir)."""
    tf, win, sl_a, rr, mh = CFG[sleeve]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    # CANLI-BIREBIR MTF (lookahead YOK)
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
    s = (DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve == "donchian" else
         SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    out = []
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        if sleeve == "squeeze":
            xv = adx_ser[i] if np.isfinite(adx_ser[i]) else 20.0
            if xv <= 20.0: continue
        sg = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)); d_ = sg.direction
        if d_ == 0: continue
        if sleeve == "donchian":
            dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
            if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue
        e = cl[i]; sld = sl_a * a; slp = e - d_ * sld; tp = e + d_ * rr * sld; ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * FEE * e / sld
        # i, j = bar indeksleri (occ zinciri icin); ts'ler raporlama icin
        out.append((i, j, idx[i], idx[j], R, sld / e, coin, sleeve, d_))
    return out


def chain(sigs, keep=None):
    """Ham sinyaller uzerinde occ=j zincirini oynat. keep=None -> taban.
    KURAL 3: append sonrasi occ=j. KURAL 7: elenen sinyal occ'u ILERLETMEZ."""
    out = []; occ = -1
    for i, j, ts_i, ts_j, R, slp, coin, sleeve, d_ in sigs:
        if i <= occ: continue
        if keep is not None and not keep(ts_i):
            continue                      # elenen sinyal occ'u ILERLETMEZ
        out.append((ts_i.value, ts_j, R, slp, coin, sleeve, d_)); occ = j
    return out


def seat_select(trades):
    """deployed_backtest.seat_select — ek olarak entry ts korunur."""
    ev = sorted(trades, key=lambda t: t[0]); openh = []; taken = []; ctr = 0
    for entry_ns, exit_ts, R, slp, coin, sleeve, dr in ev:
        while openh and openh[0][0].value <= entry_ns: heapq.heappop(openh)
        if len(openh) < MAXPOS:
            ctr += 1; heapq.heappush(openh, (exit_ts, ctr, R))
            taken.append((pd.Timestamp(entry_ns, tz="UTC"), exit_ts, R, slp, coin, sleeve, dr))
    return sorted(taken, key=lambda t: t[1])


RAW = {}
RAWCACHE = "/tmp/_disp_raw.pkl"


def load_raw(cache):
    import os, pickle
    if os.path.exists(RAWCACHE):
        with open(RAWCACHE, "rb") as f: RAW.update(pickle.load(f))
    else:
        for c in DONCH: RAW[c] = raw_signals("donchian", cache[c], c)
        for c in SQZ: RAW[c] = raw_signals("squeeze", cache[c], c)
        with open(RAWCACHE, "wb") as f: pickle.dump(RAW, f)
    print(f"  ham sinyal (occ oncesi): {sum(len(v) for v in RAW.values())}")


def build(keep=None):
    trades = []
    for c in ALL:
        trades += chain(RAW[c], keep)
    taken = seat_select(trades)
    df = pd.DataFrame(taken, columns=["entry", "exit", "R", "slp", "coin", "sleeve", "dir"])
    df["eff"] = np.minimum(RISKF, CAP * df["slp"])
    df["pnl"] = df["R"] * df["eff"] * BAL0
    return df


def summarize(df, label):
    r = df["R"].values; pnl = df["pnl"].values
    gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    yr = df["exit"].dt.year.values
    per = {y: pnl[yr == y].sum() for y in sorted(set(yr))}
    s = "  ".join(f"{y}:${v:+.0f}" for y, v in per.items())
    print(f"  {label:34s} n={len(df):4d}  toplam ${pnl.sum():+7.0f}  "
          f"PF{gp/max(gl,1e-9):4.2f} WR{(r>0).mean()*100:3.0f}%  | {s}")
    return pnl.sum(), per


# ======================================================================
# 2) KESITSEL OLCULER (hepsi .shift(1) -> gun D degeri D-1'e kadarki veriden)
# ======================================================================
def dispersion_measures(cache, win=WIN):
    dc = {}
    for c in ALL:
        m = cache[c]
        s = m["close"].resample("1D").last().dropna()
        s.index = s.index.tz_localize(None).normalize()
        dc[c] = s
    px = pd.DataFrame(dc).dropna()
    ret = np.log(px).diff().dropna()          # gunluk log getiri
    dates = ret.index
    A = ret.values
    n = len(A)
    avgcorr = np.full(n, np.nan); pc1 = np.full(n, np.nan)
    for t in range(win - 1, n):
        W = A[t - win + 1:t + 1]              # D dahil pencere
        C = np.corrcoef(W, rowvar=False)
        iu = np.triu_indices_from(C, 1)
        avgcorr[t] = np.nanmean(C[iu])
        ev = np.linalg.eigvalsh(C)
        pc1[t] = ev[-1] / ev.sum()
    xs_daily = ret.std(axis=1, ddof=1)        # gunluk kesitsel dagilim
    xsdisp = xs_daily.rolling(win).mean()
    # ek: coin-ici ortalama volatilite (dagilimin "toplam vol"dan ayrilmasi icin)
    avgvol = ret.rolling(win).std(ddof=1).mean(axis=1)
    out = pd.DataFrame({"avgcorr": avgcorr, "pc1": pc1,
                        "xsdisp": xsdisp.values, "avgvol": avgvol.values}, index=dates)
    # dagilim / vol : "saf ayrisma" (toplam vol etkisi cikarilmis)
    out["disp_ratio"] = out["xsdisp"] / out["avgvol"]
    # LOOKAHEAD KORUMASI: gun D'de karar verirken sadece D-1 sonuna kadarki deger
    return out.shift(1)


def acf1(x):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    if len(x) < 5: return np.nan
    return float(np.corrcoef(x[:-1], x[1:])[0, 1])


def main():
    import sys
    cache = {c: fast_bt.load(c, source=SRC) for c in ALL}
    print()
    load_raw(cache)
    base = build()
    print("=" * 96)
    print("TABAN (deploy config, occ=j, MP=7) — deployed_backtest.py ile ayni olmali")
    tot0, per0 = summarize(base, "TABAN")
    sys.stdout.flush()

    meas = dispersion_measures(cache)
    MEAS = ["avgcorr", "xsdisp", "pc1", "disp_ratio", "avgvol"]

    # ---- aylik ortalamalar + aylik PnL (GIRIS ayina gore: karar zamani) ----
    base["mE"] = base["entry"].dt.tz_localize(None).dt.to_period("M")
    mpnl = base.groupby("mE")["pnl"].sum()
    mn = base.groupby("mE")["R"].size()
    md = meas.copy(); md["m"] = md.index.to_period("M")
    m_avg = md.groupby("m")[MEAS].mean()          # ayin ORTALAMASI (ayni-ay, ongoru degil)
    m_end = md.groupby("m")[MEAS].last()          # ay SONU degeri -> sonraki ayin karari

    months = mpnl.index
    m_avg = m_avg.reindex(months); m_end = m_end.reindex(months)
    prev_end = m_end.shift(1)                      # ONCEKI ay sonu = ay basinda BILINEN

    print("\n" + "=" * 96)
    print(f"AYLIK PANEL — {len(months)} ay ({months[0]} .. {months[-1]}), "
          f"toplam {mn.sum()} islem")
    print("=" * 96)
    print(f"{'ay':>8} {'n':>3} {'PnL$':>8} " + " ".join(f"{k:>10}" for k in MEAS))
    for m in months:
        print(f"{str(m):>8} {mn[m]:>3d} {mpnl[m]:>8.1f} " +
              " ".join(f"{m_avg.loc[m, k]:>10.4f}" for k in MEAS))

    # ---- korelasyonlar ----
    print("\n" + "=" * 96)
    print("KORELASYONLAR (aylik PnL ile)")
    print("=" * 96)
    print(f"{'olcu':>12} {'ayni-ay r':>11} {'onceki-ay-sonu r':>18} "
          f"{'spearman(onceki)':>18} {'olcu ACF(1)':>13} {'ACF(1) PnL':>11}")
    from scipy import stats as st
    y = mpnl.values.astype(float)
    rows = {}
    for k in MEAS:
        a = m_avg[k].values.astype(float)
        p = prev_end[k].values.astype(float)
        ok = np.isfinite(a) & np.isfinite(y)
        r_same = np.corrcoef(a[ok], y[ok])[0, 1]
        ok2 = np.isfinite(p) & np.isfinite(y)
        r_prev = np.corrcoef(p[ok2], y[ok2])[0, 1]
        sp = st.spearmanr(p[ok2], y[ok2]).statistic
        ac = acf1(m_end[k].values.astype(float))
        rows[k] = (r_same, r_prev, sp, ac)
        print(f"{k:>12} {r_same:>11.3f} {r_prev:>18.3f} {sp:>18.3f} {ac:>13.3f}"
              f" {acf1(y) if k == MEAS[0] else float('nan'):>11.3f}")
    print(f"  (referans: gorevdeki ADX ay-ay ACF -0.379, aylik PnL ACF -0.345)")
    print(f"  aylik PnL ACF(1) bu veride: {acf1(y):+.3f}")

    # --- SORU 4'UN DOGRU OLCUMU: gostergenin AYLIK ORTALAMASININ otokorelasyonu
    #     (ADX'in -0.379'u da aylik ortalamadan geliyor; ay-SONU tek 20-gunluk pencere
    #      cok gurultulu ve ardisik aylarda ortusmuyor -> ACF'i yapay olarak sifirliyor)
    print("\n  --- AYLIK ORTALAMA serinin persistence'i (ADX -0.379 ile karsilastirilabilir) ---")
    print(f"  {'olcu':>12} {'ACF(1) aylik-ort':>18} {'ACF(2)':>9} {'ACF(3)':>9} "
          f"{'r(onceki ay ORT -> PnL)':>26}")
    def acfk(x, lag):
        x = np.asarray(x, float)
        return float(np.corrcoef(x[:-lag], x[lag:])[0, 1])

    prev_avg = m_avg.shift(1)
    for k in MEAS:
        a = m_avg[k].values.astype(float)
        p = prev_avg[k].values.astype(float)
        ok = np.isfinite(p) & np.isfinite(y)
        rp = np.corrcoef(p[ok], y[ok])[0, 1]
        # ADAY testini EN CÖMERT olcumle yap: ACF = ay-sonu ve aylik-ort'un iyisi,
        # ongoru r = onceki-ay-sonu ve onceki-ay-ort'un mutlak degerce buyugu.
        best_r = rows[k][1] if abs(rows[k][1]) >= abs(rp) else rp
        rows[k] = (rows[k][0], best_r, rows[k][2], max(rows[k][3], acfk(a, 1)))
        print(f"  {k:>12} {acfk(a,1):>18.3f} {acfk(a,2):>9.3f} {acfk(a,3):>9.3f} {rp:>26.3f}")
    print(f"  {'aylik PnL':>12} {acfk(y,1):>18.3f} {acfk(y,2):>9.3f} {acfk(y,3):>9.3f}")

    # --- PENCERE UZUNLUGU DUYARLILIGI ---
    print("\n  --- PENCERE UZUNLUGU DUYARLILIGI (ongoru: onceki ay ORT -> bu ay PnL) ---")
    print(f"  {'pencere':>8} " + " ".join(f"{k:>22}" for k in MEAS))
    for w in (10, 20, 40, 60):
        mw = dispersion_measures(cache, win=w)
        mw["m"] = mw.index.to_period("M")
        aw = mw.groupby("m")[MEAS].mean().reindex(months).shift(1)
        cells = []
        for k in MEAS:
            p = aw[k].values.astype(float); ok = np.isfinite(p) & np.isfinite(y)
            rp = np.corrcoef(p[ok], y[ok])[0, 1]
            ac = acf1(mw.groupby("m")[k].mean().reindex(months).values.astype(float))
            cells.append(f"r{rp:+.2f}/ACF{ac:+.2f}")
        print(f"  {w:>8} " + " ".join(f"{c:>22}" for c in cells))

    # p-degerleri
    print("\n  onceki-ay-sonu korelasyonun p-degeri (n={}):".format(int(np.isfinite(y).sum())))
    for k in MEAS:
        p = prev_end[k].values.astype(float)
        ok = np.isfinite(p) & np.isfinite(y)
        rr, pv = st.pearsonr(p[ok], y[ok])
        print(f"    {k:>12}  r={rr:+.3f}  p={pv:.3f}  n={ok.sum()}")

    # ---- TESHIS: kesitsel dagilim GERCEKTEN yeni bilgi mi, yoksa vol'un vekili mi? ----
    print("\n" + "=" * 96)
    print("TESHIS — olculer birbirinden bagimsiz mi? (aylik ort, Pearson)")
    print("=" * 96)
    print(m_avg[MEAS].corr().round(3).to_string())
    # xsdisp'in PnL ile korelasyonu, avgvol kontrol edildiginde ne kaliyor?
    px_ = m_avg.shift(1)
    ok = np.isfinite(px_["xsdisp"].values) & np.isfinite(px_["avgvol"].values) & np.isfinite(y)
    xd = px_["xsdisp"].values[ok]; av = px_["avgvol"].values[ok]; yy = y[ok]
    b = np.polyfit(av, xd, 1); xd_res = xd - np.polyval(b, av)      # vol'dan arindirilmis dagilim
    c = np.polyfit(av, yy, 1); yy_res = yy - np.polyval(c, av)
    print(f"\n  r(xsdisp, avgvol) aylik = {np.corrcoef(xd, av)[0,1]:+.3f}  "
          f"-> xsdisp buyuk olcude TOPLAM VOL'un vekili")
    print(f"  KISMI korelasyon r(xsdisp, PnL | avgvol) = "
          f"{np.corrcoef(xd_res, yy_res)[0,1]:+.3f}   (ham r = {np.corrcoef(xd, yy)[0,1]:+.3f})")
    print(f"  disp_ratio (=xsdisp/avgvol, 'saf ayrisma') onceki-ay r = "
          f"{np.corrcoef(px_['disp_ratio'].values[np.isfinite(px_['disp_ratio'].values)&np.isfinite(y)], y[np.isfinite(px_['disp_ratio'].values)&np.isfinite(y)])[0,1]:+.3f}")

    # ---- tercil analizi (onceki ay sonu degerine gore) ----
    print("\n" + "=" * 96)
    print("TERCIL ANALIZI — onceki ay sonu degerine gore aylari 3'e bol (ONGORULEBILIR bolme)")
    print("=" * 96)
    for k in MEAS:
        p = prev_end[k].values.astype(float)
        ok = np.isfinite(p)
        q = np.quantile(p[ok], [1 / 3, 2 / 3])
        buckets = np.digitize(p, q)
        line = []
        for b, nm in [(0, "dusuk"), (1, "orta"), (2, "yuksek")]:
            msk = ok & (buckets == b)
            line.append(f"{nm}(n{msk.sum():2d}) ${y[msk].sum():+6.0f}")
        print(f"  {k:>12}: " + "  |  ".join(line))

    # ---- ISLEM BAZLI: sinyal anindaki olcu vs R (n cok daha buyuk) ----
    print("\n" + "=" * 96)
    print("ISLEM BAZLI — sinyal gunundeki (shift'li) olcu vs islem R'i")
    print("=" * 96)
    ed = base["entry"].dt.tz_localize(None).dt.normalize()
    sig = meas.reindex(ed.values)
    R = base["R"].values; P = base["pnl"].values
    for k in MEAS:
        v = sig[k].values.astype(float)
        ok = np.isfinite(v)
        rr, pv = st.pearsonr(v[ok], R[ok])
        q = np.quantile(v[ok], [1 / 3, 2 / 3])
        b = np.digitize(v, q)
        parts = []
        for bi, nm in [(0, "dusuk"), (1, "orta"), (2, "yuksek")]:
            msk = ok & (b == bi)
            parts.append(f"{nm} n{msk.sum():3d} WR{(R[msk]>0).mean()*100:3.0f}% ${P[msk].sum():+6.0f}")
        print(f"  {k:>12} r(R)={rr:+.3f} p={pv:.2f} | " + " | ".join(parts))

    # ---- ADAY FILTRE TESTI: en umut verici olcuyu SINYAL ANINDA uygula ----
    print("\n" + "=" * 96)
    print("FILTRE TESTI (sinyal aninda, elenen sinyal occ'u ILERLETMEZ)")
    print("  NOT: esikler TUM ORNEKTEN secildi -> IYIMSER (in-sample). Yine de yil-yil bar var.")
    print("=" * 96)
    print(f"  TABAN: ${tot0:+.0f}  | " + "  ".join(f"{y_}:${v:+.0f}" for y_, v in per0.items()))
    results = []
    for k in MEAS:
        v = meas[k].dropna()
        for qlo in (0.25, 0.33, 0.5):
            for side in ("ust", "alt"):     # ust: yuksek degerde islem yap; alt: dusukte
                thr = v.quantile(qlo if side == "ust" else 1 - qlo)
                lut = (v > thr) if side == "ust" else (v < thr)
                lut = lut.to_dict()

                def keep(ts, lut=lut):
                    return bool(lut.get(pd.Timestamp(ts).tz_localize(None).normalize(), True))

                df = build(keep=keep)
                tot, per = summarize(df, f"{k} {side} (q={qlo:.2f})")
                allyr = all(per.get(y_, 0) > per0.get(y_, 0) for y_ in per0)
                results.append((k, side, qlo, tot, allyr))
                if tot > tot0 and allyr:
                    print("      *** TOPLAM ARTTI VE HER YIL ARTTI ***")

    print("\n" + "=" * 96)
    print("SONUC")
    print("=" * 96)
    win_any = [x for x in results if x[3] > tot0]
    win_all = [x for x in results if x[3] > tot0 and x[4]]
    print(f"  {len(results)} varyant denendi. Toplami gecen: {len(win_any)}. "
          f"Toplami VE her yili gecen: {len(win_all)}.")
    for k in MEAS:
        r_same, r_prev, sp, ac = rows[k]
        pas = (abs(r_prev) > 0.35) and (ac > 0.2)
        print(f"  {k:>12}: EN IYI onceki-ay r={r_prev:+.3f} (|r|>0.35? {abs(r_prev)>0.35}) "
              f"EN IYI ACF={ac:+.3f} (>0.2? {ac>0.2}) -> ADAY: {pas}")


if __name__ == "__main__":
    main()
