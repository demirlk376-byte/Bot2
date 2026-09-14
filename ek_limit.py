"""
ek_limit.py — İKİ UÇ: orb/asia/fvg canlıda LİMİT ile SEVİYEDEN girer, KRONOS ise
bar KAPANIŞINDAN. Bu iki modeli aynı sinyal kümesi üzerinde yan yana ölçer.

A) KAPANIŞ (KRONOS modeli, ALEYHTE): giriş = sinyal barının kapanışı, taker iki
   taraf (2×1bp) + 15.85bp giriş kayması. SL/TP seviyeleri stratejinin kendisi.
B) LİMİT (canlı niyet, LEHTE/iyimser): emir SEVİYEDE bekler. i+1 barının aralığı
   seviyeye değdiyse SEVİYEDEN dolar, değmediyse İŞLEM YOK (canlıda piyasa yedeği
   yok — execution.py: fallback_market=False, dolmazsa atlanır). Maker giriş → giriş
   ücreti 0, giriş kayması 0. Çıkış taker 1bp.
   ⚠ İYİMSER: canlıda limit yalnız 600 SANİYE bekler; burada TAM BİR SAAT bekliyor
   → gerçekte dolum oranı bundan DÜŞÜK olur.

İkisinde de: kol başına tek pozisyon (canlıdaki kendi slotu), koltuk yarışı YOK.
sr_breakout canlıda force_market → A ve B aynıdır, kıyas için A ile raporlanır.

Kullanım: py ek_limit.py local
"""
import sys, math
import numpy as np, pandas as pd
import kollar_ek as EK

SRC = sys.argv[1] if len(sys.argv) > 1 else "local"
RISKF, CAP, BAL0, FEE, KAYMA = 0.028, 1.50, 190.0, 0.0001, 15.85 / 1e4
BOL = pd.Timestamp("2025-01-01", tz="UTC")


def kos(k, model):
    """model 'kapanis' | 'limit'  → işlem listesi (giris_ts, R, pnl, sl_pct)."""
    b = k.besleme
    n = b.n
    hi = b._hi; lo = b._lo; cl = b._cl
    out = []
    occ = -1
    dolmadi = 0
    for i in range(260, n - 1):
        s = k._sig[i]
        if s is None or i <= occ:
            continue
        yon, sld_c, rr_c, mh, slp, tpp, sev = s
        if model == "kapanis":
            e = cl[i]; i0 = i
            sld = sld_c; tp = tpp; sl = slp
            ucret = 2 * FEE * e / sld
            kay = KAYMA / (sld / e)
        else:
            if i + 1 >= n:
                continue
            L = sev
            if not (lo[i + 1] <= L <= hi[i + 1]):
                dolmadi += 1
                continue
            e = L; i0 = i + 1
            sld = yon * (L - slp)
            if sld <= 0:
                continue
            tp = tpp; sl = slp
            if yon * (tp - L) <= 0:
                continue
            ucret = 1 * FEE * e / sld       # maker giriş 0 + taker çıkış
            kay = 0.0
        ep = None
        j = i0
        for j in range(i0 + 1, min(i0 + 1 + mh, n)):
            if yon == 1:
                if lo[j] <= sl: ep = sl; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= sl: ep = sl; break
                if lo[j] <= tp: ep = tp; break
        if ep is None:
            j = min(i0 + mh, n - 1); ep = cl[j]
        R = yon * (ep - e) / sld - ucret - kay
        sl_pct = sld / e
        eff = min(RISKF, CAP * sl_pct)
        out.append((b.zaman(i0), b.zaman(j), R, R * eff * BAL0, sl_pct))
        occ = j
    return out, dolmadi


def ozet(ts, etiket, ek=""):
    if not ts:
        print(f"  {etiket:<28s} n=0"); return
    R = np.array([t[2] for t in ts]); usd = sum(t[3] for t in ts)
    se = R.std(ddof=1) / math.sqrt(len(R))
    print(f"  {etiket:<28s} n={len(R):5d}  ${usd:+9.2f}  ortR {R.mean():+.4f}"
          f"  SE {se:.4f}  z {R.mean()/se:+5.2f}  WR %{100*(R>0).mean():4.1f} {ek}")


print(f"{'='*104}\nİKİ UÇ: kapanış-girişi (KRONOS, aleyhte) vs limit-girişi (canlı niyet, iyimser)")
print(f"canlı ölçek riskf {RISKF} cap {CAP} bal0 ${BAL0:.0f} · koltuk yarışı YOK, kol başına tek pozisyon")
print(f"{'='*104}")

import deployed_backtest as A
COINLER = A.DONCH + A.SQZ + A.BB_COINS
for ad in ["orb", "asia_bo", "fvg", "sr_breakout"]:
    kollar = EK.ek_kollar([ad], COINLER, SRC)
    for model in (("kapanis",) if ad == "sr_breakout" else ("kapanis", "limit")):
        hep = []; dm = 0
        for k in kollar:
            t, d = kos(k, model)
            hep += t; dm += d
        ek = f"· dolmayan sinyal {dm}" if model == "limit" else ""
        ozet(hep, f"{ad} [{model}]", ek)
        # yıl-yıl
        yl = {}
        for t in hep: yl.setdefault(t[1].year, []).append(t)
        print("      yıl-yıl: " + " | ".join(
            f"{y} n={len(g):4d} ${sum(x[3] for x in g):+7.1f} R{np.mean([x[2] for x in g]):+.3f}"
            for y, g in sorted(yl.items())))
        tr = [t for t in hep if t[0] < BOL]; te = [t for t in hep if t[0] >= BOL]
        for nm, g in (("TRAIN<2025", tr), ("TEST>=2025", te)):
            if not g: continue
            R = np.array([x[2] for x in g]); se = R.std(ddof=1)/math.sqrt(len(R))
            print(f"      {nm}: n={len(g):5d} ${sum(x[3] for x in g):+8.2f} ortR {R.mean():+.4f} z {R.mean()/se:+5.2f}")
    print()
