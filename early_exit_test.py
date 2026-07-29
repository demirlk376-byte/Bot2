"""
early_exit_test.py — Sahte kırılımın BEDELİNİ azaltmak (girişini engellemek DEĞİL).

NEDEN BU AÇI: sahte kırılımı GİRİŞ ANINDA ayırt etmek erişilebilir hiçbir veriyle mümkün değil
(13 özellik, çok-değişkenli, dürüst OOS → AUC 0.509; yapısal özelliklerde ayrışma <0.4σ; funding
hiçbir eşikte çalışmadı; OI backtest edilemiyor). Bu SORU KAPANDI.

Kapanmayan soru: girişten SONRA gelen bilgi. mfe_anatomy'ye göre SL işlemlerinin %76.5'i 1R'ye
BİLE ulaşmadan sönüyor — yani çoğu kaybeden kendini ERKEN ele veriyor. Öyleyse öngörüye gerek yok:
"k bar geçti ve hâlâ eşiğin altındayız" bir TAHMİN değil, bir GÖZLEM.

KARŞI RİSK (test edilen asıl şey): aynı kural yavaş başlayan KAZANANLARI da keser. Kazananların
MAE'si biliniyor — dibe gidip dönenler var. Net etki ancak ölçülünce bilinir; "mantıklı geliyor"
bu oturumda 20 kez yanıldı.

KURAL: giriş barından k bar sonra, o barın KAPANIŞINDA gerçekleşmemiş R < eşik ise piyasadan çık.
  - Bar içinde önce SL/TP kontrol edilir (muhafazakâr), erken-çıkış ancak ikisi de değmediyse.
  - Erken çıkış koltuğu ERKEN BOŞALTIR → başka sinyal girebilir. Koltuk modeli bunu yakalar
    (ikinci mertebeden fayda; post-hoc filtreleme bunu kaçırırdı).
  - occ per-coin, canlı-birebir MTF (lookahead yok), cap-aware boyut — deployed_backtest ile aynı.

KABUL BARI: toplam ARTACAK **ve** HER YIL artacak. Biri bozulursa RET.
(Bu oturumda -MonTue, partial-TP, XS-momentum, long-only hepsi toplamda kazanıp yıl-yıl testinde öldü.)

Kullanım:  py early_exit_test.py local
"""
import sys, heapq
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAL0 = 190.0; FEE = 0.0001; RISKF = 0.0225; CAP = 1.25; MAXPOS = 7
DONCH = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB"]
SQZ = ["XRP", "DOGE", "TRX", "XLM"]
CFG = {"donchian": ("4h", 259, 2.0, 2.5, 30), "squeeze": ("1h", 119, 2.0, 2.5, 48)}
# (k bar, eşik R) — k bar sonra hâlâ eşiğin altındaysak çık. None = kural yok (taban).
VARIANTS = [None,
            (2, 0.0), (3, 0.0), (4, 0.0), (6, 0.0),
            (2, -0.25), (3, -0.25), (4, -0.25), (6, -0.25),
            (3, 0.25), (4, 0.25), (6, 0.25),
            (8, 0.0), (12, 0.0)]


def gen(sleeve, m, rule):
    """rule=None → taban. rule=(k,thr) → giriş+k barında kapanış R'si thr altındaysa çık."""
    tf, win, sl_a, rr, mh = CFG[sleeve]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
    s = (DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve == "donchian" else
         SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values; idx = d.index; n = len(cl)
    out = []; occ = -1
    k_bar, thr = (rule if rule else (None, None))
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
        e = cl[i]; sld = sl_a * a; slp = e - d_ * sld; tp = e + d_ * rr * sld
        ep = None; j = i; reason = "hold"
        for j in range(i + 1, min(i + 1 + mh, n)):
            # bar içi: önce stop, sonra hedef (muhafazakâr sıra)
            if d_ == 1:
                if lo[j] <= slp: ep = slp; reason = "sl"; break
                if hi[j] >= tp: ep = tp; reason = "tp"; break
            else:
                if hi[j] >= slp: ep = slp; reason = "sl"; break
                if lo[j] <= tp: ep = tp; reason = "tp"; break
            # erken çıkış: SL/TP değmediyse, k bar dolduysa, kapanış eşiğin altındaysa
            if k_bar is not None and (j - i) >= k_bar:
                r_now = d_ * (cl[j] - e) / sld
                if r_now < thr:
                    ep = cl[j]; reason = "early"; break
        if ep is None:
            j = min(i + mh, n - 1); ep = cl[j]; reason = "maxhold"
        R = d_ * (ep - e) / sld - 2 * FEE * e / sld
        out.append((idx[i], idx[j], R, sld / e, reason)); occ = j
    return out


def seat_select(trades):
    ev = sorted(trades, key=lambda t: t[0]); openh = []; taken = []; ctr = 0
    for entry, exit_ts, R, slp, rsn in ev:
        while openh and openh[0][0] <= entry: heapq.heappop(openh)
        if len(openh) < MAXPOS:
            ctr += 1; heapq.heappush(openh, (exit_ts, ctr, R)); taken.append((exit_ts, R, slp, rsn))
    return taken


def summarize(taken):
    r = np.array([t[1] for t in taken]); slp = np.array([t[2] for t in taken])
    yrs_a = np.array([pd.Timestamp(t[0]).year for t in taken])
    pnl = r * np.minimum(RISKF, CAP * slp) * BAL0
    gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    eq = np.concatenate([[BAL0], BAL0 + np.cumsum(pnl)])
    peak = np.maximum.accumulate(eq)
    return dict(n=len(r), pf=gp / max(gl, 1e-9), wr=(r > 0).mean() * 100, tot=pnl.sum(),
                dd=((peak - eq) / peak).max() * 100,
                yrs={int(y): float(pnl[yrs_a == y].sum()) for y in sorted(set(yrs_a.tolist()))},
                reasons=pd.Series([t[3] for t in taken]).value_counts().to_dict())


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    ms = {c: fast_bt.load(c, source=source) for c in set(DONCH + SQZ)}
    print(f"\n{'='*112}\n=== ERKEN ÇIKIŞ: sahte kırılımın BEDELİNİ kes (girişini değil) ===")
    print(f"  kural: giriş+k barında kapanış R'si eşiğin ALTINDAysa piyasadan çık")
    print(f"\n  {'kural':>14s} {'n':>5s} {'WR':>4s} {'PF':>5s} {'toplam$':>9s} {'Δ':>8s} "
          f"{'maxDD%':>7s}  yıl-yıl                                    bayrak")
    base = None
    results = []
    for rule in VARIANTS:
        trades = []
        for c in DONCH: trades += gen("donchian", ms[c], rule)
        for c in SQZ: trades += gen("squeeze", ms[c], rule)
        s = summarize(seat_select(trades))
        label = "TABAN (kural yok)" if rule is None else f"k={rule[0]} eşik{rule[1]:+.2f}R"
        if base is None:
            base = s
            delta = ""; flag = "◄ referans"
        else:
            delta = f"{s['tot']-base['tot']:+8.0f}"
            dy = {y: s["yrs"].get(y, 0) - base["yrs"].get(y, 0) for y in base["yrs"]}
            every = all(v > 0 for v in dy.values())
            flag = "★ KABUL" if (every and s["tot"] > base["tot"]) else \
                   ("(toplam+ ama yıl bozuk)" if s["tot"] > base["tot"] else "")
        ys = " ".join(f"{y}:${v:+.0f}" for y, v in s["yrs"].items())
        print(f"  {label:>14s} {s['n']:>5d} {s['wr']:>3.0f}% {s['pf']:>5.2f} {s['tot']:>+9.0f} "
              f"{delta:>8s} {s['dd']:>7.1f}  {ys}  {flag}")
        results.append((label, rule, s))

    # En umut verici varyantın anatomisi: neyi kesti, ne kadarını kurtardı
    print(f"\n  --- ÇIKIŞ SEBEBİ DAĞILIMI (kural neyi değiştiriyor) ---")
    for label, rule, s in results:
        if rule is None or s["tot"] < base["tot"] * 0.9:
            if rule is not None: continue
        tot_n = sum(s["reasons"].values())
        mix = " ".join(f"{k}:{v}({v/tot_n*100:.0f}%)" for k, v in sorted(s["reasons"].items()))
        print(f"  {label:>14s}  {mix}")

    print(f"\n  ARANAN: toplam ARTACAK **ve** HER YIL artacak. İkisi birden olmazsa RET.")
    print(f"  Beklenti düşük: erken çıkış kaybı azaltırken yavaş başlayan KAZANANLARI da keser.")
    print(f"  Ama bu, 'girişte öngör' sorusundan farklı bir soru — ölçmeden kapatılmaz.")


if __name__ == "__main__":
    main()
