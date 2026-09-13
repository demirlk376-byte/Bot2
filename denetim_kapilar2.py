"""denetim_kapilar2.py — GECICI. K3 (gunluk fren ust-sinir), K4 (marj, sabit sermaye),
K5 (funding) ve ucret/kayma R bedeli."""
import pickle, heapq, os
import numpy as np, pandas as pd
import deployed_backtest as DB
import denetim_esdegerlik as DE

SC = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad"
allsig = pickle.load(open(f"{SC}/sig_cache.pkl", "rb"))
raw = []
for (sl, c), (d, s) in allsig.items():
    raw += DE.simulate(d, s, sl, coin=c, mtf_on=True, win_local=False, bb_close_gate=False)
taken = DE.seat(raw)
print(f"V0 alinan {len(taken)}")

RISKF, CAP, BAL0, LEV = DB.CANLI_RISKF, DB.CANLI_CAP, 190.0, 10

eff = np.array([min(RISKF, CAP * t["slp"]) for t in taken])
R = np.array([t["Rraw"] - 2 * 0.0001 * t["e_over_sld"] for t in taken])
pnl = R * eff * BAL0
exits = pd.DatetimeIndex([pd.Timestamp(t["exit_ts"]) for t in taken])
dayp = pd.Series(pnl, index=exits).groupby(exits.normalize()).sum() / BAL0 * 100
print(f"\nK3 GUNLUK ZARAR FRENI (DAILY_MAX_LOSS_PCT=0.35, equity tabanli)")
print(f"   en kotu GERCEKLESMIS gun: {dayp.min():+.2f}%  (2. {dayp.nsmallest(2).iloc[-1]:+.2f}%, "
      f"3. {dayp.nsmallest(3).iloc[-1]:+.2f}%)")
print(f"   acik pozisyonlarin ES ZAMANLI en kotu gerceklesmemis katkisi <= "
      f"7 x {RISKF*100:.1f}% = {7*RISKF*100:.1f}%")
print(f"   ust sinir gunluk dusus = {abs(dayp.min())+7*RISKF*100:.1f}%  vs fren esigi 35.0%  "
      f"-> fren {'ASLA TETIKLENMEZ' if abs(dayp.min())+7*RISKF*100 < 35 else 'TETIKLENEBILIR'}")

# ---- K4: marj, SABIT sermaye (olcek-degismez) ----
print(f"\nK4 MARJ FIZIBILITESI (LEVERAGE={LEV}, margin_required > free*0.95 -> ATLA)")
mfrac = eff / (np.array([t["slp"] for t in taken]) * LEV)
print(f"   islem basina marj / sermaye: ort {mfrac.mean()*100:.2f}%  "
      f"medyan {np.median(mfrac)*100:.2f}%  max {mfrac.max()*100:.2f}%  "
      f"(cap-bagli islemlerde tavan {CAP/LEV*100:.1f}%)")
ev = sorted(range(len(raw)), key=lambda k: raw[k]["entry_ns"])
openp = {}; exq = []; used = 0.0; blocked = 0; taken2 = []; conc_margin = []
for k in ev:
    t = raw[k]
    while exq and exq[0][0] <= t["entry_ns"]:
        _x, kk = heapq.heappop(exq); used -= openp.pop(kk)
    if len(openp) >= 7:
        continue
    e = min(RISKF, CAP * t["slp"]); m = e / (t["slp"] * LEV)
    if m > (1.0 - used) * 0.95:
        blocked += 1
        continue
    openp[k] = m; used += m; conc_margin.append(used)
    heapq.heappush(exq, (pd.Timestamp(t["exit_ts"]).value, k))
    taken2.append(t)
cm = np.array(conc_margin)
print(f"   es zamanli kullanilan marj / sermaye: ort {cm.mean()*100:.1f}%  "
      f"medyan {np.median(cm)*100:.1f}%  p95 {np.percentile(cm,95)*100:.1f}%  max {cm.max()*100:.1f}%")
print(f"   marj yetersizligi yuzunden ATLANAN islem: {blocked}  "
      f"(alinan {len(taken2)} vs ankor {len(taken)})")

# ---- K5: FUNDING ----
print(f"\nK5 FUNDING (ankorda HIC YOK) — Binance 8h oranlari")
fr = {}
for c in set(t["coin"] for t in raw):
    p = f"data/{c}_funding_bnc.csv"
    d = pd.read_csv(p, parse_dates=["dt"]).sort_values("dt")
    fr[c] = (pd.DatetimeIndex(d["dt"]).tz_convert(None).values.astype("datetime64[ns]").astype(np.int64),
             d["rate"].values)
cost_R = []; cost_frac = []
for t in taken:
    ts, rt = fr[t["coin"]]
    a = t["entry_ns"]; b = pd.Timestamp(t["exit_ts"]).value
    s = float(rt[(ts > a) & (ts <= b)].sum())
    cost_frac.append(t["dir"] * s)
    cost_R.append(t["dir"] * s / t["slp"])
cost_R = np.array(cost_R); cost_frac = np.array(cost_frac)
print(f"   islem basina odenen funding (notional orani): ort {cost_frac.mean()*100:+.4f}%  "
      f"medyan {np.median(cost_frac)*100:+.4f}%")
print(f"   R cinsinden: ort {cost_R.mean():+.5f}R  (ankor ort R {R.mean():+.4f} -> "
      f"funding sonrasi {R.mean()-cost_R.mean():+.4f}R, {cost_R.mean()/R.mean()*100:+.1f}%)")
pnl_f = (R - cost_R) * eff * BAL0
print(f"   CANLI olcek toplam: ${pnl.sum():+.2f} -> funding dahil ${pnl_f.sum():+.2f}  "
      f"fark ${pnl_f.sum()-pnl.sum():+.2f} ({(pnl_f.sum()/pnl.sum()-1)*100:+.1f}%)")
for sl in ("donchian", "squeeze", "bb"):
    m = np.array([t["sleeve"] == sl for t in taken])
    print(f"     {sl:9s} n={m.sum():4d} ort funding {cost_R[m].mean():+.5f}R "
          f"(ort tutma {np.mean([t['hours'] for t,x in zip(taken,m) if x]):.0f}h)")
# MEXC vs Binance oran karsilastirmasi (ortusen donem)
print("   MEXC vs Binance funding (ortusen donem, ayni coinler):")
for c in ["SOL", "XRP", "DOGE"]:
    a = pd.read_csv(f"data/{c}_funding.csv", parse_dates=["dt"])
    b = pd.read_csv(f"data/{c}_funding_bnc.csv", parse_dates=["dt"])
    b = b[b.dt >= a.dt.min()]
    print(f"     {c}: MEXC ort {a.rate.mean()*100:+.5f}%  Binance ort {b.rate.mean()*100:+.5f}%")

# ---- ucret ----
print(f"\nUCRET: 1bp -> 2bp -> 4bp (tek taraf), CANLI olcek")
for f in (0.0, 0.0001, 0.0002, 0.0004):
    Rf = np.array([t["Rraw"] - 2 * f * t["e_over_sld"] for t in taken])
    print(f"   {f*1e4:.0f}bp: ortR {Rf.mean():+.4f}  ${np.sum(Rf*eff*BAL0):+.2f}")
