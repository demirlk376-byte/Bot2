"""
cooldown_test.py — Ardışık-SL cooldown savunması (canlı-doğru, üretimde, MP=7, worst-month).

Sürücü (worst_month): kötü aylar = whipsaw (ardışık sahte-breakout), BTC-çöküşü DEĞİL (corr+0.08).
Girişte sahte breakout ayırt edilemiyor (loser_analysis) → DAVRANIŞTA filtre:
  Bir coinin donchian'ı üst üste N kez SL olursa → sonraki K sinyali ATLA (coini dondur),
  sonra bir "yoklama" trade'iyle geri gir. Küme ortasındaki kesin-kaybeden tekrar-girişleri eler.

Cooldown ÜRETİMDE (atlanan sinyal occ'u meşgul etmez = canlı-doğru). Squeeze dokunulmaz (whipsaw
kurbanı donchian). Portföy MP=7 koltuk + aylık bucket. Baseline vs (N,K) varyantları.

ADAY OLMA ŞARTI: en-kötü-ayı düşür AMA her-yıl toplamı bozMA. Sadece toparlanmayı kesiyorsa RED.

Kullanım:  py cooldown_test.py local
"""
import sys, heapq
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn, ema as ema_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAL0 = 190.0; FEE = 0.0001; RISKF = 0.0225
DONCH = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB"]
SQZ = ["XRP", "DOGE", "TRX", "XLM"]
MAXPOS = 7
DCFG = ("4h", 259, 2.0, 2.5, 30); SCFG = ("1h", 119, 2.0, 2.5, 48)
CONFIGS = [("baseline", 0, 0), ("N2K2", 2, 2), ("N2K3", 2, 3), ("N3K2", 3, 2),
           ("N3K3", 3, 3), ("N2K5", 2, 5), ("N3K5", 3, 5)]


def prep(sleeve, m):
    tf, win, sl_a, rr, mh = DCFG if sleeve == "donchian" else SCFG
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    # CANLI-BİREBİR MTF (lookahead YOK): canlı d1d=df_4h.resample("1D").close.last() +
    # ewm20 dahil-bugün; cebirsel olarak == kapanış > DÜNE kadar tamamlanmış EMA20.
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
    s = (DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve == "donchian" else
         SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    return d, atr_ser, adx_ser, up, s, (tf, win, sl_a, rr, mh)


def simulate_donchian(pk, coin, N, K):
    """Cooldown ÜRETİMDE: coin başına consec_sl izle, dondur, occ atlanan sinyalde ilerlemez."""
    d, atr_ser, adx_ser, up, s, (tf, win, sl_a, rr, mh) = pk
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values; idx = d.index; n = len(cl)
    out = []; occ = -1; consec = 0; skips = 0
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        sg = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)); d_ = sg.direction
        if d_ == 0 or i <= occ: continue
        dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
        if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue
        # ── COOLDOWN (üretimde, occ değişmez) ──
        if N > 0 and skips > 0:
            skips -= 1; continue
        e = cl[i]; sld = sl_a * a; slp = e - d_ * sld; tp = e + d_ * rr * sld; ep = None; j = i; oc = "hold"
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; oc = "sl"; break
                if hi[j] >= tp: ep = tp; oc = "tp"; break
            else:
                if hi[j] >= slp: ep = slp; oc = "sl"; break
                if lo[j] <= tp: ep = tp; oc = "tp"; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]; oc = "sl" if (d_ * (ep - e) < 0) else "tp"
        R = d_ * (ep - e) / sld - 2 * FEE * e / sld
        out.append({"entry_ns": idx[i].value, "exit": idx[j], "R": R, "coin": coin, "sleeve": "donchian"})
        occ = j
        if oc == "sl":
            consec += 1
            if N > 0 and consec >= N: skips = K
        else:
            consec = 0
    return out


def simulate_squeeze(pk, coin):
    d, atr_ser, adx_ser, up, s, (tf, win, sl_a, rr, mh) = pk
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values; idx = d.index; n = len(cl)
    out = []; occ = -1
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        xv = adx_ser[i] if np.isfinite(adx_ser[i]) else 20.0
        if xv <= 20.0: continue
        sg = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)); d_ = sg.direction
        if d_ == 0 or i <= occ: continue
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
        out.append({"entry_ns": idx[i].value, "exit": idx[j], "R": R, "coin": coin, "sleeve": "squeeze"})
        occ = j
    return out


def portfolio_metrics(donch_trades, sqz_trades):
    trades = donch_trades + sqz_trades
    ev = sorted(trades, key=lambda t: t["entry_ns"]); openh = []; taken = []; ctr = 0
    for t in ev:
        while openh and openh[0][0].value <= t["entry_ns"]: heapq.heappop(openh)
        if len(openh) < MAXPOS:
            ctr += 1; heapq.heappush(openh, (t["exit"], ctr, t)); taken.append(t)
    r = np.array([t["R"] for t in taken]); gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    pf = gp / gl if gl > 0 else 9.99
    df = pd.DataFrame([{"pnl": t["R"] * RISKF * BAL0,
                        "year": pd.Timestamp(t["exit"]).year,
                        "m": pd.Timestamp(t["exit"]).to_period("M")} for t in taken])
    total = df["pnl"].sum(); worst = df.groupby("m")["pnl"].sum().min() / BAL0 * 100
    yrs = {y: df[df["year"] == y]["pnl"].sum() for y in sorted(df["year"].unique())}
    return len(taken), pf, total, worst, yrs


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    dpk = {c: prep("donchian", fast_bt.load(c, source=source)) for c in DONCH}
    spk = {c: prep("squeeze", fast_bt.load(c, source=source)) for c in SQZ}
    sqz_trades = [t for c in SQZ for t in simulate_squeeze(spk[c], c)]   # sabit
    print(f"\n{'='*82}\n=== COOLDOWN TESTİ (MP={MAXPOS}, %2.25/işlem) — en-kötü-ayı düşür, toplamı bozma ===")
    print(f"  {'config':9s} {'n':>5s} {'PF':>5s} {'toplam$':>9s} {'enKötüAy%':>9s}  yıl-yıl")
    base_yrs = None
    for name, N, Kk in CONFIGS:
        donch_trades = [t for c in DONCH for t in simulate_donchian(dpk[c], c, N, Kk)]
        n, pf, total, worst, yrs = portfolio_metrics(donch_trades, sqz_trades)
        if name == "baseline": base_yrs = yrs
        flags = ""
        if base_yrs and name != "baseline":
            hurt = [y for y in yrs if yrs[y] < base_yrs.get(y, 0) - 1e-6]
            flags = ("HER-YIL-OK" if not hurt else f"BOZDU:{hurt}")
        yrstr = " ".join(f"{y}:${v:+.0f}" for y, v in yrs.items())
        print(f"  {name:9s} {n:>5d} {pf:>5.2f} {total:>+9.0f} {worst:>+9.1f}  {yrstr}  {flags}")
    print("\n  ARANAN: enKötüAy belirgin ↑ (daha az negatif) VE HER-YIL-OK (hiçbir yıl bozulmadı).")
    print("  Sadece worst düşüp toplam/yıl bozuluyorsa → toparlanmayı kesiyor, RED (overfit).")


if __name__ == "__main__":
    main()
