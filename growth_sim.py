"""
growth_sim.py — Deploy portföyünün BÜYÜME-OPTIMAL riskini bul (bileşik, koltuk-kısıtlı).

Soru: 2%/işlem fazla tutucu mu? Kelly: çok az risk=büyüme bırakırsın, çok fazla=vol
sürüklemesi/iflas → bir optimum var. Bu araç deploy portföyünü (7 donchian + 4 squeeze)
GERÇEK işlem dizisiyle BİLEŞİK simüle eder (canlı gibi: her işlem MEVCUT equity'nin
%f'ini riske atar), MAX_POSITIONS=7 koltuk kısıtıyla, farklı f seviyelerinde.

Çıktı: her f için terminal equity, CAGR, maxDD%. Büyüme-optimal f (Kelly tepesi) +
yarı-Kelly (robust öneri, in-sample tepe overfit'tir → fraksiyonu kullan).

DÜRÜST: bu in-sample; Kelly tepesi geleceği garantilemez, DD gerçekte daha kötü olabilir
(korelasyon kümelenmesi). Öneri hep yarı-Kelly veya kullanıcı DD-tavanına göre.

Kullanım:  py growth_sim.py local
"""
import sys, heapq
import numpy as np
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn, ema as ema_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAL0 = 190.0; FEE = 0.0001
DONCH = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB"]
SQZ = ["XRP", "DOGE", "TRX", "XLM"]
MAXPOS = 7
CFG = {"donchian": ("4h", 259, 2.0, 2.5, 30), "squeeze": ("1h", 119, 2.0, 2.5, 48)}


def gen(sleeve, m):
    tf, win, sl_a, rr, mh = CFG[sleeve]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    dd = fast_bt.resample(m, "1d"); dema = ema_fn(dd["close"], 20)
    up = (dd["close"] > dema).reindex(d.index, method="ffill").values
    s = (DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve == "donchian" else
         SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values; idx = d.index; n = len(cl)
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
        e = cl[i]; sld = sl_a * a; slp = e - d_ * sld; tp = e + d_ * rr * sld; ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * FEE * e / sld   # R = risk-birimi cinsinden kazanç
        out.append((idx[i].value, idx[j].value, R)); occ = j   # ns epoch (sıralanabilir)
    return out


def simulate(trades, f):
    """Bileşik equity, MAX_POSITIONS koltuk, her giriş MEVCUT equity'nin f'ini riske atar."""
    ev = sorted(trades, key=lambda t: t[0])   # entry_ns
    eq = BAL0; peak = BAL0; maxdd = 0.0
    openh = []   # min-heap (exit_ns, R, risk_$)
    def realize_until(t):
        nonlocal eq, peak, maxdd
        while openh and openh[0][0] <= t:
            _, R, risk = heapq.heappop(openh)
            eq += R * risk
            if eq > peak: peak = eq
            dd = (peak - eq) / peak
            if dd > maxdd: maxdd = dd
    for entry_ns, exit_ns, R in ev:
        realize_until(entry_ns)
        if len(openh) < MAXPOS and eq > 0:
            risk = f * eq
            heapq.heappush(openh, (exit_ns, R, risk))
    realize_until(float("inf"))
    return eq, maxdd


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    trades = []
    for c in DONCH:
        try: trades += gen("donchian", fast_bt.load(c, source=source))
        except Exception as e: print(f"  donchian {c}: {e}")
    for c in SQZ:
        try: trades += gen("squeeze", fast_bt.load(c, source=source))
        except Exception as e: print(f"  squeeze {c}: {e}")
    span_ns = max(t[1] for t in trades) - min(t[0] for t in trades)
    years = span_ns / (365.25 * 24 * 3600 * 1e9)
    print(f"\n{'='*70}\n{len(trades)} işlem, ~{years:.1f} yıl, MAX_POSITIONS={MAXPOS}, başlangıç ${BAL0:.0f}")
    print(f"  (BİLEŞİK: her işlem mevcut equity'nin f'ini riske atar — canlı gibi)")
    print(f"\n  {'risk/işlem':>10s} {'RISK_SCALE':>10s} {'terminal$':>11s} {'CAGR':>7s} {'maxDD%':>7s}")
    rows = []
    for f in [0.01, 0.015, 0.02, 0.025, 0.03, 0.035, 0.04, 0.05, 0.06, 0.08, 0.10]:
        eq, mdd = simulate(trades, f)
        cagr = (eq / BAL0) ** (1 / years) - 1 if eq > 0 else -1
        rows.append((f, eq, cagr, mdd))
        flag = " ← CANLI" if abs(f - 0.02) < 1e-9 else ""
        print(f"  {f*100:>9.1f}% {f/0.02:>10.2f} {eq:>11.0f} {cagr*100:>6.0f}% {mdd*100:>6.0f}%{flag}")
    best = max(rows, key=lambda r: r[1])   # terminal serveti maks (Kelly tepesi)
    print(f"\n  Kelly tepesi (maks terminal): risk={best[0]*100:.1f}%/işlem → ${best[1]:.0f}, maxDD {best[3]*100:.0f}%")
    print(f"  YARI-Kelly (robust öneri): ~{best[0]*50:.1f}%/işlem (tepe in-sample overfit, DD gerçekte daha kötü).")
    print(f"  Kullanıcı DD-tavanına (%50) göre: DD≤%50 kalan en yüksek risk seçilir.")
    ok = [r for r in rows if r[3] <= 0.50]
    if ok:
        pick = max(ok, key=lambda r: r[1])
        print(f"  → DD≤%50 sınırında en iyi: risk={pick[0]*100:.1f}% (RISK_SCALE={pick[0]/0.02:.2f}) "
              f"→ ${pick[1]:.0f}, CAGR {pick[2]*100:.0f}%, maxDD {pick[3]*100:.0f}%")


if __name__ == "__main__":
    main()
