"""_hyb_null.py — AY-KARISTIRMA NULL'U (2026-09-09 ile ayni protokol) fade karisimina.

Iki null:
  A) paket_null.py stili: TUM islemlerin ay etiketleri karistirilir.
  B) hedefli: kitabin ay etiketleri GERCEK kalir, YALNIZ fade'in etiketleri karistirilir.
     -> dogrudan "fade'in kitapla ZAMANLAMASI (negatif korelasyon) gercek mi" sorusu.
Kiyas tabani NAKIT kontrolu (kitap x (1-k)), cunku fade'in savunmasi "nakde gore ustunluk".
5 istatistik -> Bonferroni p<0.010.
"""
import pickle, heapq, sys
import numpy as np, pandas as pd
import deployed_backtest as DB
import rejim_hibrit as H
D = __import__("pickle").load(open(H.ONBELLEK, "rb"))
FREE = H.FREE; RF, CP, B0 = H.RF, H.CP, H.B0
seat, seat_oncelikli = H.seat, H.seat_oncelikli
BOOK_T = [(a, b, c, d, "kitap") for v in D["book"].values() for (a, b, c, d) in v]
BASE = H.olc(seat(BOOK_T), {"kitap": 1.0})

N = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
TOHUM = 20260911
ADAYLAR = [((25, 2.5), 0.20), ((25, 2.5), 0.10), ((15, 2.5), 0.10), ((20, 2.5), 0.10)]

for (a, rr), K in ADAYLAR:
    ft = sorted([(x[0], x[1], x[2], x[3], "fade") for c in FREE for x in D["fade"][(a, rr, c)]],
                key=lambda t: t[0])
    tk = seat_oncelikli(BOOK_T, ft)          # kitap-oncelikli: 1579 kitap islemi korunur
    nb = sum(1 for t in tk if t[3] == "kitap")
    assert nb == 1579, nb
    R = np.array([t[1] for t in tk])
    base_eff = np.array([min(RF, CP*t[2]) for t in tk])
    is_f = np.array([t[3] == "fade" for t in tk])
    sf = base_eff[is_f].sum()
    e_nakit = np.where(is_f, 0.0, base_eff*(1-K))
    e_fade  = np.where(is_f, base_eff*K*BASE["risk"]/sf, base_eff*(1-K))
    ay = np.array([pd.Timestamp(t[0]).tz_localize(None).to_period("M") for t in tk])

    def stats(e, ay_k, order):
        pnl = R*e*100.0
        g = pd.Series(pnl, index=ay_k).groupby(level=0).sum()
        eq = B0 + np.cumsum((R*e*B0)[order])
        dd = DB.maxdd(np.concatenate([[B0], eq]))
        return g.min(), dd, g.std(), g.quantile(.10), g.mean()/g.std()

    idn = np.arange(len(tk))
    s_n = stats(e_nakit, ay, idn); s_f = stats(e_fade, ay, idn)
    isim = ["en kotu ay", "maxDD", "aylik std", "%10 dilim", "Sharpe"]
    yon  = [+1, -1, -1, +1, +1]
    gercek = [f-n for f, n in zip(s_f, s_n)]
    rng = np.random.default_rng(TOHUM)
    nulls = {"A": [[] for _ in isim], "B": [[] for _ in isim]}
    fidx = np.where(is_f)[0]
    for _ in range(N):
        # A) tum etiketler
        p = rng.permutation(len(tk))
        d = [f-n for f, n in zip(stats(e_fade, ay[p], p), stats(e_nakit, ay[p], p))]
        for i, v in enumerate(d): nulls["A"][i].append(v)
        # B) yalniz fade etiketleri
        ayb = ay.copy(); ayb[fidx] = ay[rng.permutation(fidx)]
        ob = idn.copy(); ob[fidx] = fidx[rng.permutation(len(fidx))]
        d = [f-n for f, n in zip(stats(e_fade, ayb, ob), stats(e_nakit, ayb, ob))]
        for i, v in enumerate(d): nulls["B"][i].append(v)

    print(f"\n{'='*96}\n=== ADX<{a} rr{rr} · k={K:.2f} (kitap-oncelikli) vs NAKIT kontrolu — "
          f"{N:,} tekrar, Bonferroni p<0.010")
    print(f"  fade islem {int(is_f.sum())} · nakit: ${(R*e_nakit*B0).sum():+.2f} · "
          f"fade: ${(R*e_fade*B0).sum():+.2f} · fark ${(R*(e_fade-e_nakit)*B0).sum():+.2f}")
    for lab in ("A", "B"):
        print(f"  --- null {lab} ({'tum etiketler' if lab=='A' else 'yalniz fade etiketleri'}) ---")
        print(f"    {'istatistik':<12s} {'gercek':>9s} {'null ort':>9s} {'null %5-95':>20s} {'ham p':>7s}  hukum")
        gecen = 0
        for i, nm in enumerate(isim):
            arr = np.array(nulls[lab][i]); v = gercek[i]
            p = (arr >= v).mean() if yon[i] > 0 else (arr <= v).mean()
            lo, hi = np.percentile(arr, [5, 95])
            h = "OK Bonferroni" if p < 0.010 else ("~ ham p<0.05" if p < 0.05 else "X null da uretiyor")
            gecen += p < 0.010
            print(f"    {nm:<12s} {v:>+9.3f} {arr.mean():>+9.3f}  [{lo:>+8.3f},{hi:>+8.3f}] {p:>7.4f}  {h}")
        print(f"    -> Bonferroni'yi gecen: {gecen}/5")
