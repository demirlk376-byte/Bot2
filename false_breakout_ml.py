"""
false_breakout_ml.py — Sahte breakout ÖNGÖRÜLEBİLİR mi? (çok-değişkenli + genişletilmiş, dürüst OOS)

Kullanıcı sezgisi: "sahte breakout'u anlamanın bir yolu olmalı." loser_analysis TEK özellik
baktı (ayrışma yok). Bu araç: (1) GENİŞLETİLMİŞ özellikler (breakout yapısı + BTC teyidi),
(2) ÇOK-DEĞİŞKENLİ logistic regression (elle, numpy), (3) DÜRÜST train/test (2023-24 eğit,
2025-26 TEST) → out-of-sample AUC. In-sample her zaman iyi görünür; SADECE OOS önemli.

Yeni özellikler (girişte, nedensel):
  clearance   : kanalı kaç ATR aştı (kararlılık) | close_in_bar: mum güçlü mü kapandı (0-1)
  bar_range   : breakout barı kaç ATR (patlama) | opp_wick: ters fitil (reddediş, ATR)
  btc_aligned : BTC kendi EMA200'ünün trade yönünde mi (çapraz-teyit) | btc_mom: BTC momentum
  hour        : günün hangi 4h barı (0-5)
+ eski: adx, atr_pct, ema200_dist, ema50_gt_200, mtf_aligned, mom10

OOS AUC>0.57 → sinyal var (filtre kur, canlı-doğru test et). ≤0.55 → çok-değişkenli ML BİLE
öngöremiyor = sahte breakout girişte gerçekten öngörülemez (kesin kanıt, sezgi ne yazık ki hayır).

Kullanım:  py false_breakout_ml.py local
"""
import sys
import numpy as np
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn, ema as ema_fn
from strategies.donchian import DonchianStrategy

DONCH = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB"]
WIN, SL_A, RR, MH = 259, 2.0, 2.5, 30
FEATS = ["adx", "atr_pct", "ema200_dist", "ema50_gt_200", "mtf_aligned", "mom10",
         "clearance", "close_in_bar", "bar_range", "opp_wick", "btc_aligned", "btc_mom", "hour"]


def btc_frame():
    d = fast_bt.resample(fast_bt.load("BTC", source=SOURCE), "4h")
    return d.index.values, ema_fn(d["close"], 200).values, d["close"].values


def gen(coin, m, btc_idx, btc_ema, btc_cl):
    d = fast_bt.resample(m, "4h")
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    ema50 = ema_fn(d["close"], 50).values; ema200 = ema_fn(d["close"], 200).values
    dd = fast_bt.resample(m, "1d"); dema = ema_fn(dd["close"], 20)
    up = (dd["close"] > dema).reindex(d.index, method="ffill").values
    ch_hi = d["high"].rolling(40).max().shift(1).values     # prior-40 kanal (excl current)
    ch_lo = d["low"].rolling(40).min().shift(1).values
    # BTC hizalama: coin barına en yakın (<=) BTC bar indeksi
    bpos = np.searchsorted(btc_idx, d.index.values, side="right") - 1
    s = DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values; idx = d.index; n = len(cl)
    rows = []; occ = -1
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        sg = s.analyze(d.iloc[max(0, i - WIN):i + 1], float(a)); d_ = sg.direction
        if d_ == 0 or i <= occ: continue
        dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
        if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue
        if np.isnan(ema200[i]) or np.isnan(ema50[i]) or np.isnan(ch_hi[i]) or np.isnan(ch_lo[i]): continue
        e = cl[i]; sld = SL_A * a; slp = e - d_ * sld; tp = e + d_ * RR * sld; ep = None; j = i
        for j in range(i + 1, min(i + 1 + MH, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + MH, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * FEE * e / sld
        bp = bpos[i]; btc_al = 0.0; btc_mm = 0.0
        if bp >= 10 and np.isfinite(btc_ema[bp]):
            btc_up = btc_cl[bp] > btc_ema[bp]
            btc_al = 1.0 if ((d_ == 1 and btc_up) or (d_ == -1 and not btc_up)) else 0.0
            btc_mm = (btc_cl[bp] - btc_cl[bp - 10]) / btc_cl[bp - 10] * 100 * d_
        rng = hi[i] - lo[i]
        clr = (e - ch_hi[i]) / a if d_ == 1 else (ch_lo[i] - e) / a
        cib = (e - lo[i]) / rng if (d_ == 1 and rng > 0) else ((hi[i] - e) / rng if rng > 0 else 0.5)
        owick = (hi[i] - e) / a if d_ == 1 else (e - lo[i]) / a
        rows.append({
            "win": 1 if R > 0 else 0, "year": idx[i].year,
            "adx": adx_ser[i] if np.isfinite(adx_ser[i]) else 20.0,
            "atr_pct": a / e * 100, "ema200_dist": (e - ema200[i]) / a * d_,
            "ema50_gt_200": 1.0 if ema50[i] > ema200[i] else 0.0,
            "mtf_aligned": 1.0 if dup == (d_ == 1) else (1.0 if (d_ == -1 and not dup) else 0.0),
            "mom10": (e - cl[i - 10]) / cl[i - 10] * 100 * d_,
            "clearance": clr, "close_in_bar": cib, "bar_range": rng / a, "opp_wick": owick,
            "btc_aligned": btc_al, "btc_mom": btc_mm, "hour": idx[i].hour,
        }); occ = j
    return rows


def auc(y, s):
    order = np.argsort(s); ranks = np.empty(len(s)); ranks[order] = np.arange(1, len(s) + 1)
    npos = y.sum(); nneg = len(y) - npos
    if npos == 0 or nneg == 0: return 0.5
    return (ranks[y == 1].sum() - npos * (npos + 1) / 2) / (npos * nneg)


def train_logistic(X, y, iters=2000, lr=0.1, l2=1e-3):
    w = np.zeros(X.shape[1]); b = 0.0
    for _ in range(iters):
        z = X @ w + b; p = 1 / (1 + np.exp(-np.clip(z, -30, 30))); g = p - y
        w -= lr * (X.T @ g / len(y) + l2 * w); b -= lr * g.mean()
    return w, b


def main():
    global SOURCE, FEE; SOURCE = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"; FEE = 0.0001
    bi, be, bc = btc_frame()
    rows = []
    for c in DONCH:
        try: rows += gen(c, fast_bt.load(c, source=SOURCE), bi, be, bc)
        except Exception as e: print(f"  {c}: {e}")
    import numpy as _np
    Y = _np.array([r["win"] for r in rows]); YR = _np.array([r["year"] for r in rows])
    X = _np.array([[r[f] for f in FEATS] for r in rows], dtype=float)
    print(f"\n{'='*74}\n=== SAHTE BREAKOUT ÖNGÖRÜ TESTİ — {len(rows)} işlem (kazanan {Y.mean()*100:.0f}%) ===")
    # 1) univariate ayrışma (yeni özellikler dahil)
    print(f"\n  --- tek-özellik ayrışma (kazanan vs kaybeden ort, σ) ---")
    for k, f in enumerate(FEATS):
        tv = X[Y == 1, k].mean(); sv = X[Y == 0, k].mean(); sd = X[:, k].std() + 1e-9
        gap = abs(tv - sv) / sd
        mark = "*BUYUK" if gap > 0.4 else ("orta" if gap > 0.2 else "yok")
        print(f"    {f:13s} kaz{tv:+8.3f} kayb{sv:+8.3f}  {mark:>7s} ({gap:.2f}σ)")
    # 2) çok-değişkenli logistic — DÜRÜST train/test (2023-24 eğit, 2025-26 TEST)
    tr = (YR <= 2024); te = (YR >= 2025)
    mu = X[tr].mean(0); sg = X[tr].std(0) + 1e-9
    Xtr = (X[tr] - mu) / sg; Xte = (X[te] - mu) / sg
    w, b = train_logistic(Xtr, Y[tr].astype(float))
    auc_in = auc(Y[tr], Xtr @ w + b); auc_oos = auc(Y[te], Xte @ w + b)
    print(f"\n  --- çok-değişkenli logistic (elle) ---")
    print(f"    in-sample AUC (2023-24): {auc_in:.3f}   ← her zaman iyimser")
    print(f"    OUT-OF-SAMPLE AUC (2025-26): {auc_oos:.3f}   ← SADECE BU ÖNEMLİ")
    print(f"    en güçlü katsayılar:")
    for k in np.argsort(-np.abs(w))[:5]:
        print(f"      {FEATS[k]:13s} w={w[k]:+.3f}")
    print(f"\n  YORUM: OOS AUC>0.57 → sinyal VAR (filtre kur, canlı-doğru test et).")
    print(f"         0.53-0.57 → zayıf/sınırda. ≤0.53 → çok-değişkenli ML BİLE öngöremiyor")
    print(f"         = sahte breakout girişte ÖNGÖRÜLEMEZ (kesin). 0.5=yazı-tura.")


if __name__ == "__main__":
    main()
