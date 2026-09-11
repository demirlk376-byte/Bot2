"""_hyb_ana.py — REJIM-HIBRIT: fade kolunu koltuk rekabeti + risk-esitlemeli karisimda olcer."""
import pickle, heapq, sys
import numpy as np, pandas as pd
import deployed_backtest as DB

P = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/raw.pkl"
D = pickle.load(open(P, "rb"))
BOOK = [t for v in D["book"].values() for t in v]
FREE = D["free"]
RF, CP, B0, MP = 0.028, 1.50, 190.0, 7      # CANLI ayar


def seat(trades, maxpos=MP):
    """deployed_backtest.seat_select ile birebir, ama etiket tasir.
       trades: (entry_ns, exit_ts, R, slp, tag)"""
    ev = sorted(trades, key=lambda t: (t[0], t[4]))   # kararli: etiketle tie-break
    openh = []; taken = []; ctr = 0
    for entry_ns, exit_ts, R, slp, tag in ev:
        while openh and openh[0][0].value <= entry_ns: heapq.heappop(openh)
        if len(openh) < maxpos:
            ctr += 1; heapq.heappush(openh, (exit_ts, ctr, R))
            taken.append((exit_ts, R, slp, tag))
    return sorted(taken, key=lambda t: (t[0], t[3]))


def seat_oncelikli(book_t, fade_t, maxpos=MP):
    """KITAP ONCELIKLI: fade yalnizca kitabin bosalttigi koltugu doldurur.
       Once kitap FIFO ile yerlestirilir; sonra fade ayni anda-acik sayisina bakip
       bos koltuk varsa girer."""
    bt = seat(book_t, maxpos)                         # kitap kendi basina
    # kitabin her an kac koltuk doldurdugunu bul
    intervals = []
    ev = sorted(book_t, key=lambda t: t[0]); openh = []; ctr = 0
    for entry_ns, exit_ts, R, slp, tag in ev:
        while openh and openh[0][0].value <= entry_ns: heapq.heappop(openh)
        if len(openh) < maxpos:
            ctr += 1; heapq.heappush(openh, (exit_ts, ctr, R))
            intervals.append((entry_ns, exit_ts.value))
    iv = np.array(intervals) if intervals else np.zeros((0, 2))
    # fade: FIFO, kitabin dolulugu + kendi doluluguna bak
    out = list(bt); openf = []
    for entry_ns, exit_ts, R, slp, tag in sorted(fade_t, key=lambda t: t[0]):
        while openf and openf[0][0].value <= entry_ns: heapq.heappop(openf)
        busy = int(((iv[:, 0] <= entry_ns) & (iv[:, 1] > entry_ns)).sum()) if len(iv) else 0
        if busy + len(openf) < maxpos:
            heapq.heappush(openf, (exit_ts, len(openf), R))
            out.append((exit_ts, R, slp, tag))
    return sorted(out, key=lambda t: (t[0], t[3]))


def metr(taken, eff_map):
    """taken: (exit_ts, R, slp, tag); eff_map: tag -> carpan (risk esitleme)"""
    r = np.array([t[1] for t in taken])
    eff = np.array([min(RF, CP * t[2]) * eff_map[t[3]] for t in taken])
    pnl = r * eff * B0
    eq = B0 + np.cumsum(pnl)
    dd = DB.maxdd(np.concatenate([[B0], eq]))
    eqc = B0; pk = B0; ddc = 0.0
    for R_, e_ in zip(r, eff):
        eqc *= (1 + R_ * e_); pk = max(pk, eqc); ddc = max(ddc, (pk - eqc) / pk * 100)
    mon = pd.Series(pnl, index=[pd.Timestamp(t[0]).tz_localize(None).to_period("M")
                                for t in taken]).groupby(level=0).sum() / B0 * 100
    yil = pd.Series(pnl, index=[pd.Timestamp(t[0]).year for t in taken]).groupby(level=0).sum()
    return dict(n=len(r), kar=pnl.sum(), dd=dd, ddc=ddc, kotu_ay=mon.min(),
                sharpe=mon.mean() / mon.std() * np.sqrt(12), mon=mon, yil=yil,
                risk=eff.sum(), maxeff=eff.max(), bilesik=eqc,
                poz_ay=(mon > 0).mean() * 100)


BOOK_T = [(a, b, c, d, "kitap") for (a, b, c, d) in BOOK]
BASE = metr(seat(BOOK_T), {"kitap": 1.0})
print(f"{'='*100}")
print(f"TABAN (kitap tek basina, CANLI ayar): n={BASE['n']} kar ${BASE['kar']:+.2f} "
      f"sabitDD %{BASE['dd']:.2f} bilesikDD %{BASE['ddc']:.2f} kotu-ay %{BASE['kotu_ay']:.2f} "
      f"Sharpe {BASE['sharpe']:.3f} Srisk {BASE['risk']:.2f}")
print(f"{'='*100}\n")

# ---------- 1) FADE STANDALONE, CANLI BOYUTTA (fade_test 2.25%/cap1.0 kullanmisti) ----------
print("[1] FADE STANDALONE — fade_test'in ayarina (%2.25, cap 1.0) KARSI canli ayar (%2.80, cap 1.50)")
print(f"  {'ADX<':>5s} {'rr':>4s} {'n':>5s} {'WR':>4s} {'PF':>5s} {'ft$(2.25/1.0)':>14s} "
      f"{'canli$(2.8/1.5)':>16s} {'Srisk':>7s}   yil-yil (cikis yili)")
CELLS = [(a, rr) for a in (15, 20, 25) for rr in (1.0, 1.5, 2.5)]
fade_taken = {}
for (a, rr) in CELLS:
    ft = [(x[0], x[1], x[2], x[3], "fade") for c in FREE for x in D["fade"][(a, rr, c)]]
    ft = sorted(ft, key=lambda t: t[0])
    fade_taken[(a, rr)] = ft
    r = np.array([t[2] for t in ft]); slp = np.array([t[3] for t in ft])
    ex = [pd.Timestamp(t[1]) for t in ft]
    pnl_ft = r * np.minimum(0.0225, 1.0 * slp) * B0
    pnl_lv = r * np.minimum(RF, CP * slp) * B0
    yil = pd.Series(pnl_lv, index=[x.year for x in ex]).groupby(level=0).sum()
    gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    ys = " ".join(f"{y}:${v:+.0f}" for y, v in yil.items())
    print(f"  {a:>5d} {rr:>4.1f} {len(r):>5d} {(r>0).mean()*100:>3.0f}% {gp/max(gl,1e-9):>5.2f} "
          f"{pnl_ft.sum():>+14.0f} {pnl_lv.sum():>+16.0f} "
          f"{np.minimum(RF,CP*slp).sum():>7.2f}   {ys}")

# ---------- 2) KOLTUK REKABETI ----------
print(f"\n[2] KOLTUK REKABETI — 7 koltuk ORTAK. Fade eklendiginde kitap kac islem kaybediyor?")
print(f"  {'ADX<':>5s} {'rr':>4s} | {'FIFO: kitap n':>13s} {'kayip':>6s} {'fade n':>7s} "
      f"{'fade alinan%':>12s} | {'ONCELIK: fade n':>15s} {'fade alinan%':>12s}")
union_taken = {}
oncelik_taken = {}
for (a, rr) in CELLS:
    ft = fade_taken[(a, rr)]
    u = seat(BOOK_T + ft)
    nb = sum(1 for t in u if t[3] == "kitap"); nf = len(u) - nb
    union_taken[(a, rr)] = u
    o = seat_oncelikli(BOOK_T, ft)
    nbo = sum(1 for t in o if t[3] == "kitap"); nfo = len(o) - nbo
    oncelik_taken[(a, rr)] = o
    print(f"  {a:>5d} {rr:>4.1f} | {nb:>13d} {nb-BASE['n']:>+6d} {nf:>7d} "
          f"{nf/len(ft)*100:>11.0f}% | {nbo:>15d}/{nfo:<5d} {nfo/len(ft)*100:>11.0f}%")
