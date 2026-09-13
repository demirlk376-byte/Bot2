"""
denetim_kapilar.py — GECICI DENETIM ARACI. Ankorun MODELLEMEDIGI canli kapilari
ve maliyetleri ANKORUN KENDI islem listesi uzerinde olcer:
  K1  donchian gunluk-EMA20 MTF kapisi kac sinyali eliyor? (DONCHIAN_MTF)
  K2  ardisik-zarar cooldown'i (CONSECUTIVE_LOSS_LIMIT=2, COOLDOWN_MINUTES=240)
  K3  gunluk zarar freni (DAILY_MAX_LOSS_PCT=0.35)
  K4  marj fizibilitesi (margin_required > free*0.95 -> islem ATLANIR), LEVERAGE=10
  K5  FUNDING maliyeti (backtest'te HIC YOK)
"""
import pickle, heapq, os
import numpy as np, pandas as pd
import deployed_backtest as DB

SC = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad"
allsig = pickle.load(open(f"{SC}/sig_cache.pkl", "rb"))
import denetim_esdegerlik as DE


def build_raw(**kw):
    tr = []
    for (sl, c), (d, s) in allsig.items():
        tr += DE.simulate(d, s, sl, coin=c, **kw)
    return tr


# ---------- K1: MTF kapisinin bagliyicilig ----------
print("=" * 78)
n_sig = n_block = 0
for (sl, c), (d, s) in allsig.items():
    if sl != "donchian":
        continue
    for g in s:
        n_sig += 1
        if not ((g["dir"] == 1 and g["up"]) or (g["dir"] == -1 and not g["up"])):
            n_block += 1
print(f"K1 donchian ham sinyal {n_sig}, gunluk-EMA20 MTF kapisinin eledigi {n_block} "
      f"({n_block/n_sig*100:.2f}%)")

raw = build_raw(mtf_on=True, win_local=False, bb_close_gate=False)
taken = DE.seat(raw)
print(f"   V0 alinan: {len(taken)}")

# ---------- K2/K3/K4: koltuk + cooldown + gunluk fren + marj, tek gecis ----------
def full_sim(trades, *, cooldown=True, daily_halt=True, margin_gate=True,
             maxpos=7, riskf=0.0225, cap=1.25, bal0=190.0, lev=10,
             cl_limit=2, cd_min=240, daily_max=0.35, fee=0.0001,
             fund=None, compounding=False):
    """Kronolojik olay simulasyonu: giris/cikis akisi, koltuk, cooldown, gunluk
    fren, serbest marj. Sabit-oran (bal0) ya da bilesik."""
    ev = []
    for k, t in enumerate(trades):
        ev.append((t["entry_ns"], 0, k))
    ev.sort()
    openpos = {}          # k -> dict
    exits = []            # heap (exit_ns, k)
    bal = bal0
    realized = bal0
    day = None
    day_start = bal0
    halted_day = None
    streak = {}
    cd_until = {}
    out = []
    blocked = dict(seat=0, cooldown=0, daily=0, margin=0)
    ei = 0
    for entry_ns, _z, k in ev:
        t = trades[k]
        # once bu ana kadar kapanan pozisyonlari isle
        while exits and exits[0][0] <= entry_ns:
            xns, kk = heapq.heappop(exits)
            p = openpos.pop(kk)
            realized += p["pnl"]
            key = f"{p['sleeve']}:{p['coin']}"
            if p["pnl"] < 0:
                streak[key] = streak.get(key, 0) + 1
                if streak[key] >= cl_limit:
                    cd_until[key] = xns + cd_min * 60 * 1_000_000_000
            else:
                streak[key] = 0
        ts = pd.Timestamp(entry_ns)
        d0 = ts.normalize()
        if day != d0:
            day = d0
            day_start = realized + sum(0 for _ in openpos)   # gerceklesmis taban
            halted_day = False
        if daily_halt and halted_day:
            blocked["daily"] += 1
            continue
        # gunluk fren: equity (gerceklesmis + acik pnl yok, muhafazakar) vs gun basi
        if daily_halt and day_start > 0 and (day_start - realized) / day_start >= daily_max:
            halted_day = True
            blocked["daily"] += 1
            continue
        if len(openpos) >= maxpos:
            blocked["seat"] += 1
            continue
        key = f"{t['sleeve']}:{t['coin']}"
        if cooldown and cd_until.get(key, 0) > entry_ns:
            blocked["cooldown"] += 1
            continue
        base = realized if compounding else bal0
        eff = min(riskf, cap * t["slp"])
        notional = eff * base / t["slp"]
        margin = notional / lev
        if margin_gate:
            used = sum(p["margin"] for p in openpos.values())
            free = realized - used
            if margin > free * 0.95:
                blocked["margin"] += 1
                continue
        R = t["Rraw"] - 2 * fee * t["e_over_sld"]
        if fund is not None:
            R -= t["dir"] * fund.get(k, 0.0) / t["slp"]
        pnl = R * eff * base
        openpos[k] = dict(margin=margin, pnl=pnl, sleeve=t["sleeve"], coin=t["coin"])
        heapq.heappush(exits, (pd.Timestamp(t["exit_ts"]).value, k))
        out.append(dict(exit_ns=pd.Timestamp(t["exit_ts"]).value, pnl=pnl, R=R))
    while exits:
        xns, kk = heapq.heappop(exits)
        realized += openpos.pop(kk)["pnl"]
    out.sort(key=lambda r: r["exit_ns"])
    pnl = np.array([r["pnl"] for r in out]); R = np.array([r["R"] for r in out])
    eq = bal0 + np.cumsum(pnl)
    e2 = np.concatenate([[bal0], eq]); peak = np.maximum.accumulate(e2)
    dd = ((peak - e2) / peak).max() * 100
    mon = pd.DataFrame({"pnl": pnl,
                        "m": [pd.Timestamp(r["exit_ns"]).to_period("M") for r in out]}
                       ).groupby("m")["pnl"].sum() / bal0 * 100
    return dict(n=len(out), tot=pnl.sum(), meanR=R.mean(), dd=dd, worst=mon.min(),
                blocked=blocked)


print("\nK2/K3/K4 — canli kapilari ANKOR islem akisina uygulayinca:")
combos = [
    ("hicbiri (= ankor seat_select)", dict(cooldown=False, daily_halt=False, margin_gate=False)),
    ("+ ardisik-zarar cooldown",      dict(cooldown=True,  daily_halt=False, margin_gate=False)),
    ("+ gunluk zarar freni",          dict(cooldown=False, daily_halt=True,  margin_gate=False)),
    ("+ marj fizibilitesi",           dict(cooldown=False, daily_halt=False, margin_gate=True)),
    ("HEPSI",                         dict(cooldown=True,  daily_halt=True,  margin_gate=True)),
]
for nm, kw in combos:
    r = full_sim(raw, **kw)
    print(f"   {nm:32s} n={r['n']:4d} ${r['tot']:+8.2f} ortR {r['meanR']:+.4f} "
          f"maxDD {r['dd']:5.2f}% enkotuay {r['worst']:+6.2f}%  bloke={r['blocked']}")

print("\n   CANLI olcek (cap=1.50 riskf=0.028, lev=10):")
for nm, kw in combos:
    r = full_sim(raw, riskf=DB.CANLI_RISKF, cap=DB.CANLI_CAP, **kw)
    print(f"   {nm:32s} n={r['n']:4d} ${r['tot']:+8.2f} maxDD {r['dd']:5.2f}% "
          f"enkotuay {r['worst']:+6.2f}%  bloke={r['blocked']}")

# ---------- K5: FUNDING ----------
print("\nK5 FUNDING (backtest'te HIC YOK) — Binance 8h oranlari, tam kapsam 2023-2026")
fr = {}
for c in set(t["coin"] for t in raw):
    p = f"data/{c}_funding_bnc.csv"
    if os.path.exists(p):
        d = pd.read_csv(p, parse_dates=["dt"]).sort_values("dt")
        tsn = pd.DatetimeIndex(d["dt"]).tz_convert(None).values.astype("datetime64[ns]").astype(np.int64)
        fr[c] = (tsn, d["rate"].values)
missing = [c for c in set(t["coin"] for t in raw) if c not in fr]
print(f"   funding verisi olmayan coinler: {missing if missing else 'YOK (12/12 var)'}")
fund = {}
for k, t in enumerate(raw):
    ts, rt = fr[t["coin"]]
    a = t["entry_ns"]; b = pd.Timestamp(t["exit_ts"]).value
    m = (ts > a) & (ts <= b)
    fund[k] = float(rt[m].sum())
tot_f = np.array([fund[k] for k in range(len(raw))])
dirs = np.array([t["dir"] for t in raw])
print(f"   islem basina toplam funding orani: ort {tot_f.mean()*100:.4f}% "
      f"(long odedigi/short aldigi), medyan {np.median(tot_f)*100:.4f}%")
print(f"   yon-agirlikli net (long +, short -): ort {(dirs*tot_f).mean()*100:.4f}% notional")
for nm, kw in [("hicbiri", dict(cooldown=False, daily_halt=False, margin_gate=False)),
               ("HEPSI", dict(cooldown=True, daily_halt=True, margin_gate=True))]:
    a = full_sim(raw, **kw)
    b = full_sim(raw, fund=fund, **kw)
    print(f"   {nm:8s} funding YOK ${a['tot']:+8.2f} ortR {a['meanR']:+.4f}  ->  "
          f"funding VAR ${b['tot']:+8.2f} ortR {b['meanR']:+.4f}  "
          f"fark ${b['tot']-a['tot']:+.2f} ({(b['tot']/a['tot']-1)*100:+.1f}%)")
    ac = full_sim(raw, riskf=DB.CANLI_RISKF, cap=DB.CANLI_CAP, **kw)
    bc = full_sim(raw, fund=fund, riskf=DB.CANLI_RISKF, cap=DB.CANLI_CAP, **kw)
    print(f"   {nm:8s} CANLI olcek: ${ac['tot']:+8.2f} -> ${bc['tot']:+8.2f} "
          f"fark ${bc['tot']-ac['tot']:+.2f}")
