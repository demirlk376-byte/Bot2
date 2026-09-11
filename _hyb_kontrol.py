"""_hyb_kontrol.py — KRITIK KONTROL: fade mi ise yariyor, yoksa sadece RISK AZALTMA mi?
   + tam kitapla (BB dahil, canli boyut) korelasyon + ay-karistirma null'u."""
import pickle, heapq
import numpy as np, pandas as pd
import deployed_backtest as DB
exec(open("/home/user/Bot2/_hyb_ana.py").read().split("# ---------- 1)")[0])
CELLS = [(a, rr) for a in (15, 20, 25) for rr in (1.0, 1.5, 2.5)]
fade_taken, union_taken, oncelik_taken = {}, {}, {}
for (a, rr) in CELLS:
    ft = sorted([(x[0], x[1], x[2], x[3], "fade") for c in FREE for x in D["fade"][(a, rr, c)]],
                key=lambda t: t[0])
    fade_taken[(a, rr)] = ft
    union_taken[(a, rr)] = seat(BOOK_T + ft)
    oncelik_taken[(a, rr)] = seat_oncelikli(BOOK_T, ft)

# ---------- 4) KONTROL: SADECE KUCULT (fade yerine NAKIT) ----------
print("[4] KONTROL — riski fade'e degil NAKDE kaydir (kitap x (1-k), baska hicbir sey).")
print("    Bilesik maxDD zaten kendiliginden duser; fade'in 'faydasi' bunun uzerinde mi?")
tk0 = seat(BOOK_T)
print(f"  {'k':>5s} {'kar $':>9s} {'D$':>8s} {'sabitDD':>8s} {'bilesikDD':>10s} {'kotu ay':>8s} "
      f"{'Dkotu':>7s} {'Sharpe':>7s} {'DSh':>7s}")
NAKIT = {}
for k in (0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40):
    m = metr(tk0, {"kitap": 1 - k})
    NAKIT[k] = m
    print(f"  {k:>5.2f} {m['kar']:>+9.2f} {m['kar']-BASE['kar']:>+8.2f} {m['dd']:>7.2f}% "
          f"{m['ddc']:>9.2f}% {m['kotu_ay']:>7.2f}% {m['kotu_ay']-BASE['kotu_ay']:>+7.2f} "
          f"{m['sharpe']:>7.3f} {m['sharpe']-BASE['sharpe']:>+7.3f}")

print("\n[4b] FADE vs NAKIT — ayni k'da fade NAKDIN USTUNE ne katiyor?")
print(f"  {'hucre':>14s} {'k':>5s} {'D$ (fade-nakit)':>16s} {'DbilesikDD':>11s} {'Dkotu ay':>9s} {'DSharpe':>8s}")
for (a, rr) in [(15,1.0),(15,1.5),(15,2.5),(20,2.5),(25,1.0),(25,1.5),(25,2.5)]:
    for k in (0.05, 0.10, 0.20):
        tk = oncelik_taken[(a, rr)]
        sb = sum(min(RF,CP*t[2]) for t in tk if t[3]=="kitap")
        sf = sum(min(RF,CP*t[2]) for t in tk if t[3]=="fade")
        m = metr(tk, {"kitap": (1-k)*BASE["risk"]/sb, "fade": k*BASE["risk"]/sf})
        c = NAKIT[k]
        print(f"  ADX<{a} rr{rr:<4.1f} {k:>5.2f} {m['kar']-c['kar']:>+16.2f} "
              f"{m['ddc']-c['ddc']:>+11.2f} {m['kotu_ay']-c['kotu_ay']:>+9.2f} "
              f"{m['sharpe']-c['sharpe']:>+8.3f}")

# ---------- 5) TAM KITAPLA KORELASYON (BB dahil, canli boyut) ----------
print("\n[5] AYLIK KORELASYON — TAM kitap (BB/LTC dahil, canli %2.80/cap1.50) ile.")
print("    (fade_test.book_monthly BB kolunu DISARIDA birakiyor + ankor boyutu kullaniyor)")
bmon = BASE["mon"]
print(f"  {'hucre':>14s} {'korr':>6s} {'ort-ay $':>9s} {'kitap kayip aylarinda':>22s} {'poz/toplam':>11s}")
for (a, rr) in CELLS:
    ft = fade_taken[(a, rr)]
    pnl = np.array([t[2]*min(RF,CP*t[3])*B0 for t in ft])
    mo = pd.Series(pnl, index=[pd.Timestamp(t[1]).tz_localize(None).to_period("M")
                               for t in ft]).groupby(level=0).sum()/B0*100
    j = pd.concat({"f": mo, "b": bmon}, axis=1).dropna()
    bad = j[j["b"] < 0]
    print(f"  ADX<{a} rr{rr:<4.1f} {j['f'].corr(j['b']):>+6.2f} {j['f'].mean()*B0/100:>+9.2f} "
          f"{bad['f'].sum()*B0/100:>+21.2f}$ {(bad['f']>0).sum():>5d}/{len(bad):<5d}")
