"""_hyb_taban.py — TABAN DOGRULAMA: ankor yeniden uretiliyor mu?"""
import pickle, heapq
import numpy as np, pandas as pd
import deployed_backtest as DB

P = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/raw.pkl"
D = pickle.load(open(P, "rb"))
book = [t for v in D["book"].values() for t in v]
print(f"ham kitap sinyali: {len(book)}")

def seat(trades, maxpos=7):
    ev = sorted(trades, key=lambda t: t[0]); openh = []; taken = []; ctr = 0
    for entry_ns, exit_ts, R, slp in ev:
        while openh and openh[0][0].value <= entry_ns: heapq.heappop(openh)
        if len(openh) < maxpos:
            ctr += 1; heapq.heappush(openh, (exit_ts, ctr, R)); taken.append((exit_ts, R, slp))
    return sorted(taken, key=lambda t: t[0])

taken = seat(book)
print(f"koltuk sonrasi: {len(taken)}")
r = np.array([R for _, R, _ in taken]); slp = np.array([s for _, _, s in taken])
ex = [pd.Timestamp(x) for x, _, _ in taken]

for nm, RF, CP in (("ANKOR 1.25/2.25%", 0.0225, 1.25), ("CANLI 1.50/2.80%", 0.028, 1.50)):
    eff = np.minimum(RF, CP * slp)
    pnl = r * eff * DB.BAL0
    eq = DB.BAL0 + np.cumsum(pnl)
    dd = DB.maxdd(np.concatenate([[DB.BAL0], eq]))
    mon = pd.Series(pnl, index=[x.tz_localize(None).to_period("M") for x in ex]).groupby(level=0).sum()/DB.BAL0*100
    # bilesik
    eqc = DB.BAL0; pk = DB.BAL0; ddc = 0.0
    for R_, e_ in zip(r, eff):
        eqc *= (1 + R_*e_); pk = max(pk, eqc); ddc = max(ddc, (pk-eqc)/pk*100)
    eqc2 = DB.BAL0; pk2 = DB.BAL0; ddc2 = 0.0
    for R_ in r:
        eqc2 *= (1 + R_*RF); pk2 = max(pk2, eqc2); ddc2 = max(ddc2, (pk2-eqc2)/pk2*100)
    print(f"\n{nm}: kar ${pnl.sum():+.2f} | sabit-oran maxDD %{dd:.2f} | en kotu ay %{mon.min():.2f}")
    print(f"   bilesik(eff) ${eqc:,.0f} maxDD %{ddc:.2f} | bilesik(RISKF duz) ${eqc2:,.0f} maxDD %{ddc2:.2f}")
    print(f"   aylik ort %{mon.mean():+.2f} std %{mon.std():.2f} Sharpe(ay) {mon.mean()/mon.std():.3f} "
          f"yillik {mon.mean()/mon.std()*np.sqrt(12):.3f} | poz-ay %{(mon>0).mean()*100:.0f} | {len(mon)} ay")

# ay_analiz.csv ile karsilastir
df = pd.read_csv("data/ay_analiz.csv")
print(f"\nay_analiz.csv: {len(df)} islem, kar ${(df.R*df.eff*190).sum():+.2f}, "
      f"eff==min(.028,1.5*slp)? {np.allclose(df.eff, np.minimum(0.028,1.5*df.slp))}")
