"""
deployed_backtest.py — Canlı config'in TAM backtest raporu (düzeltilmiş occ, MP=7).

Deploy: donchian 7 (SOL,ETH,ADA,NEAR,BCH,ICP,BNB) + squeeze 4 (XRP,DOGE,TRX,XLM),
MAX_POSITIONS=7, %2.25/işlem. (BB/LTC hafta-sonu küçük ek katkı — burada yok, ~%3-5.)

İKİ görünüm:
  A) SABİT-ORAN (compounding YOK, taban $190) — edge'in taşınabilir ölçüsü, dürüst.
  B) BİLEŞİK (canlı gibi, mevcut equity'nin %'i) — ama küçük hesapta patlar = fantezi, uyarılı.

Metrikler: toplam getiri, CAGR, gerçek max drawdown (tepe-dip equity), PF, WR, yıl-yıl, en kötü ay.

Kullanım:  py deployed_backtest.py local
"""
import sys, heapq
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn, ema as ema_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAL0 = 190.0; FEE = 0.0001; RISKF = 0.0225; MAXPOS = 7
DONCH = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB"]
SQZ = ["XRP", "DOGE", "TRX", "XLM"]
CFG = {"donchian": ("4h", 259, 2.0, 2.5, 30), "squeeze": ("1h", 119, 2.0, 2.5, 48)}


def gen(sleeve, m):
    tf, win, sl_a, rr, mh = CFG[sleeve]
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
        R = d_ * (ep - e) / sld - 2 * FEE * e / sld
        out.append((idx[i].value, idx[j], R)); occ = j
    return out


def seat_select(trades):
    ev = sorted(trades, key=lambda t: t[0]); openh = []; taken = []; ctr = 0
    for entry_ns, exit_ts, R in ev:
        while openh and openh[0][0].value <= entry_ns: heapq.heappop(openh)
        if len(openh) < MAXPOS:
            ctr += 1; heapq.heappush(openh, (exit_ts, ctr, R)); taken.append((exit_ts, R))
    return sorted(taken, key=lambda t: t[0])   # exit sırası


def maxdd(equity):
    peak = np.maximum.accumulate(equity); return ((peak - equity) / peak).max() * 100


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    trades = []
    for c in DONCH: trades += gen("donchian", fast_bt.load(c, source=source))
    for c in SQZ: trades += gen("squeeze", fast_bt.load(c, source=source))
    taken = seat_select(trades)
    r = np.array([R for _, R in taken]); exits = [pd.Timestamp(x) for x, _ in taken]
    years = (exits[-1] - exits[0]).days / 365.25
    gp = r[r > 0].sum(); gl = -r[r < 0].sum(); pf = gp / gl
    wr = (r > 0).mean() * 100
    print(f"\n{'='*70}\n=== CANLI CONFIG BACKTEST (düzeltilmiş occ, MP={MAXPOS}, %2.25/işlem) ===")
    print(f"  {len(taken)} işlem, ~{years:.1f} yıl ({exits[0].date()} → {exits[-1].date()})")
    print(f"  PF {pf:.2f} | WR {wr:.0f}% | ortalama işlem {r.mean():+.3f}R")

    # A) SABİT-ORAN
    pnl = r * RISKF * BAL0; eq = BAL0 + np.cumsum(pnl)
    tot = eq[-1] - BAL0; dd = maxdd(np.concatenate([[BAL0], eq]))
    print(f"\n  --- A) SABİT-ORAN (compounding YOK, taban ${BAL0:.0f}) ---")
    print(f"    Toplam kâr: ${tot:+.0f}  ({tot/BAL0*100:+.0f}%, {tot/BAL0*100/years:+.0f}%/yıl basit)")
    print(f"    Gerçek max drawdown (tepe-dip): {dd:.1f}%")
    dfm = pd.DataFrame({"pnl": pnl, "m": [x.to_period("M") for x in exits]})
    mon = dfm.groupby("m")["pnl"].sum() / BAL0 * 100
    print(f"    Aylık: ort {mon.mean():+.1f}% | en kötü ay {mon.min():+.1f}% | poz-ay {(mon>0).mean()*100:.0f}%")
    print(f"    Yıl-yıl kâr:")
    for y in sorted(set(x.year for x in exits)):
        ry = np.array([R for (x, R) in taken if pd.Timestamp(x).year == y])
        print(f"      {y}: ${ry.sum()*RISKF*BAL0:+7.0f}  (n{len(ry)}, PF{ry[ry>0].sum()/max(-ry[ry<0].sum(),1e-9):.2f})")

    # B) BİLEŞİK (canlı gibi) — uyarılı
    eqc = BAL0
    peakc = BAL0; ddc = 0.0
    for R in r:
        eqc *= (1 + R * RISKF)
        peakc = max(peakc, eqc); ddc = max(ddc, (peakc - eqc) / peakc * 100)
    cagr = (eqc / BAL0) ** (1 / years) - 1
    print(f"\n  --- B) BİLEŞİK (canlı gibi, mevcut equity'nin %2.25'i) ---")
    print(f"    ${BAL0:.0f} → ${eqc:,.0f}  (CAGR {cagr*100:.0f}%, max DD {ddc:.0f}%)")
    print(f"    ⚠ Bu FANTEZİ: küçük hesap sıfır-sürtünmeyle bileşiklenince patlar. Edge ileriye")
    print(f"      zayıflar + slippage/min-notional ısırır → gerçek bunun ÇOK altında. A) daha dürüst.")
    print(f"\n  NOT: BB/LTC hafta-sonu kolu burada YOK (~%3-5 ek). Bu ~%95 aktivite.")


if __name__ == "__main__":
    main()
