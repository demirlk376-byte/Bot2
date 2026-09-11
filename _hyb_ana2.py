"""_hyb_ana2.py — marjinal ADX bandi (doz-yanit) + karisim + risk-esitlemeli k suprumu."""
import pickle, heapq
import numpy as np, pandas as pd
import deployed_backtest as DB
exec(open("/home/user/Bot2/_hyb_ana.py").read().split("# ---------- 1)")[0])
CELLS = [(a, rr) for a in (15, 20, 25) for rr in (1.0, 1.5, 2.5)]
fade_taken, union_taken, oncelik_taken = {}, {}, {}
for (a, rr) in CELLS:
    ft = sorted([(x[0], x[1], x[2], x[3], "fade") for c in FREE for x in D["fade"][(a, rr, c)]], key=lambda t: t[0])
    fade_taken[(a, rr)] = ft
    union_taken[(a, rr)] = seat(BOOK_T + ft)
    oncelik_taken[(a, rr)] = seat_oncelikli(BOOK_T, ft)


# ---------- 0) MARJINAL ADX BANDI: gercek doz-yanit ----------
print("[0] MARJINAL ADX BANDI (kumulatif degil) — mekanizma monoton mu?")
print(f"  {'band':>10s} {'rr':>4s} {'n':>5s} {'WR':>4s} {'PF':>5s} {'ortR':>7s} {'canli$':>8s}")
for rr in (1.0, 1.5, 2.5):
    prev = set()
    for a in (15, 20, 25):
        cur = [(c, x) for c in FREE for x in D["fade"][(a, rr, c)]]
        curset = {(c, x[0]) for c, x in cur}
        band = [x for c, x in cur if (c, x[0]) not in prev]
        prev = curset
        if not band: continue
        r = np.array([t[2] for t in band]); slp = np.array([t[3] for t in band])
        gp = r[r > 0].sum(); gl = -r[r < 0].sum()
        lab = f"ADX<15" if a == 15 else f"[{a-5},{a})"
        print(f"  {lab:>10s} {rr:>4.1f} {len(r):>5d} {(r>0).mean()*100:>3.0f}% {gp/max(gl,1e-9):>5.2f} "
              f"{r.mean():>+7.3f} {(r*np.minimum(RF,CP*slp)*B0).sum():>+8.0f}")

# ---------- 3) KARISIM: risk-esitlemeli k suprumu ----------
def karisim(taken, k):
    """k = fade'in TOPLAM RISK BUTCESINDEKI payi. Sabit: Sigma eff == taban Sigma eff."""
    sb = sum(min(RF, CP*t[2]) for t in taken if t[3] == "kitap")
    sf = sum(min(RF, CP*t[2]) for t in taken if t[3] == "fade")
    if sf <= 0: return None
    return {"kitap": (1-k)*BASE["risk"]/sb, "fade": k*BASE["risk"]/sf}

print(f"\n[3] RISK-ESITLEMELI KARISIM — Sigma eff SABIT ({BASE['risk']:.2f}), k = fade'in risk payi")
KS = [0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40]
for mod, TK in (("FIFO (fade kitabi bloklar)", union_taken),
                ("KITAP-ONCELIKLI (fade artik koltuk)", oncelik_taken)):
    print(f"\n  --- {mod} ---")
    for (a, rr) in [(15, 1.0), (15, 1.5), (15, 2.5), (20, 2.5), (25, 2.5)]:
        tk = TK[(a, rr)]
        print(f"   ADX<{a} rr{rr}:")
        print(f"     {'k':>5s} {'kar $':>9s} {'D$':>7s} {'sabitDD':>8s} {'bilesikDD':>10s} "
              f"{'kotu ay':>8s} {'Dkotu':>7s} {'Sharpe':>7s} {'DSh':>7s} {'maxeff':>7s} {'enkotuyil%':>10s}")
        for k in KS:
            if k == 0.0:
                m = BASE
                print(f"     {k:>5.2f} {m['kar']:>+9.2f} {0.0:>+7.2f} {m['dd']:>7.2f}% "
                      f"{m['ddc']:>9.2f}% {m['kotu_ay']:>7.2f}% {0.0:>+7.2f} {m['sharpe']:>7.3f} "
                      f"{0.0:>+7.3f} {RF:>7.4f} {'-':>10s}")
                continue
            w = karisim(tk, k)
            m = metr(tk, w)
            yb = BASE["yil"].reindex(m["yil"].index).fillna(0)
            eky = ((m["yil"] - yb) / yb.abs().replace(0, np.nan) * 100).min()
            print(f"     {k:>5.2f} {m['kar']:>+9.2f} {m['kar']-BASE['kar']:>+7.2f} {m['dd']:>7.2f}% "
                  f"{m['ddc']:>9.2f}% {m['kotu_ay']:>7.2f}% {m['kotu_ay']-BASE['kotu_ay']:>+7.2f} "
                  f"{m['sharpe']:>7.3f} {m['sharpe']-BASE['sharpe']:>+7.3f} {m['maxeff']:>7.4f} "
                  f"{eky:>+10.1f}")
