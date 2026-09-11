"""_hyb_gercek.py — surtunme (15.85bp giris kaymasi), berabere-sirali bilesik DD duyarliligi,
   yuruyen-ileri OOS, fade'in SL mesafesi dagilimi."""
import pickle, heapq
import numpy as np, pandas as pd
import deployed_backtest as DB
exec(open("/home/user/Bot2/_hyb_ana.py").read().split("# ---------- 1)")[0])
CELLS = [(a, rr) for a in (15, 20, 25) for rr in (1.0, 1.5, 2.5)]
SLIP = 0.001585        # 15.85 bp giris kaymasi (DURUM'da olculmus, backtest MODELLEMIYOR)

print("[6] SURTUNME — 15.85bp giris kaymasi eklenince fade ne oluyor? (kitap da ayni vergiyi oder)")
r = np.array([t[1] for t in seat(BOOK_T)]); sl = np.array([t[2] for t in seat(BOOK_T)])
eff = np.minimum(RF, CP*sl)
print(f"  KITAP: ort SL mesafesi %{sl.mean()*100:.2f} · kayma maliyeti {SLIP/sl.mean():.4f}R/islem")
print(f"    ${(r*eff*B0).sum():+.2f} -> ${((r-SLIP/sl)*eff*B0).sum():+.2f} "
      f"({((r-SLIP/sl)*eff*B0).sum()/(r*eff*B0).sum()*100:.0f}%)")
print(f"  {'hucre':>14s} {'n':>5s} {'ortSL%':>7s} {'kayma R':>8s} {'kaymasiz$':>10s} {'kaymali$':>9s}")
for (a, rr) in CELLS:
    ft = [x for c in FREE for x in D["fade"][(a, rr, c)]]
    r2 = np.array([t[2] for t in ft]); s2 = np.array([t[3] for t in ft])
    e2 = np.minimum(RF, CP*s2)
    print(f"  ADX<{a} rr{rr:<4.1f} {len(r2):>5d} {s2.mean()*100:>7.2f} {SLIP/s2.mean():>8.4f} "
          f"{(r2*e2*B0).sum():>+10.0f} {((r2-SLIP/s2)*e2*B0).sum():>+9.0f}")

print("\n[7] BERABERE-SIRALI DUYARLILIK — bilesik maxDD ayni-cikis islemlerinin sirasina bagli mi?")
tk = seat(BOOK_T)
ex = [pd.Timestamp(t[0]) for t in tk]
print(f"  kitapta ayni cikis damgasini paylasan islem: {len(ex)-len(set(ex))} cift-fazlasi")
rng = np.random.default_rng(7)
for nm, tkx in (("kitap", tk),):
    vals = []
    for _ in range(60):
        arr = sorted(tkx, key=lambda t: (pd.Timestamp(t[0]), rng.random()))
        rr_ = np.array([t[1] for t in arr]); ss = np.array([t[2] for t in arr])
        ee = np.minimum(RF, CP*ss)
        eqc = B0; pk = B0; dd = 0.0
        for R_, e_ in zip(rr_, ee):
            eqc *= (1+R_*e_); pk = max(pk, eqc); dd = max(dd, (pk-eqc)/pk*100)
        vals.append(dd)
    print(f"  {nm}: bilesik maxDD 60 rastgele berabere-sirasi -> "
          f"ort %{np.mean(vals):.2f} min %{np.min(vals):.2f} max %{np.max(vals):.2f} "
          f"(deterministik sira: %{BASE['ddc']:.2f})")

print("\n[8] YURUYEN-ILERI OOS — (hucre,k) YALNIZ egitimde secilir, testte olculur.")
fade_taken, onc = {}, {}
for (a, rr) in CELLS:
    ft = sorted([(x[0], x[1], x[2], x[3], "fade") for c in FREE for x in D["fade"][(a, rr, c)]],
                key=lambda t: t[0])
    onc[(a, rr)] = seat_oncelikli(BOOK_T, ft)
KS = [0.05, 0.10, 0.15, 0.20, 0.30]

def kesit(tkx, a0, a1):
    return [t for t in tkx if a0 <= pd.Timestamp(t[0]).tz_localize(None).to_period("M") < a1]

aylar = sorted({pd.Timestamp(t[0]).tz_localize(None).to_period("M") for t in seat(BOOK_T)})
for bol in (0.5, 0.6, 0.7):
    kk = int(len(aylar)*bol); sinir = aylar[kk]
    egt_b = kesit(seat(BOOK_T), aylar[0], sinir); tst_b = kesit(seat(BOOK_T), sinir, aylar[-1]+1)
    def olc(tkx, w):
        r_ = np.array([t[1] for t in tkx]); s_ = np.array([t[2] for t in tkx])
        e_ = np.array([min(RF, CP*t[2])*w[t[3]] for t in tkx])
        pnl = r_*e_*B0
        mon = pd.Series(pnl, index=[pd.Timestamp(t[0]).tz_localize(None).to_period("M")
                                    for t in tkx]).groupby(level=0).sum()/B0*100
        eqc = B0; pk = B0; dd = 0.0
        for R_, ee in zip(r_, e_):
            eqc *= (1+R_*ee); pk = max(pk, eqc); dd = max(dd, (pk-eqc)/pk*100)
        return pnl.sum(), mon.min(), dd, mon.mean()/mon.std()*np.sqrt(12)
    tb_e = olc(egt_b, {"kitap": 1.0}); tb_t = olc(tst_b, {"kitap": 1.0})
    best, bs = None, -9e9
    for (a, rr) in CELLS:
        for k in KS:
            eg = kesit(onc[(a, rr)], aylar[0], sinir)
            sb = sum(min(RF, CP*t[2]) for t in eg if t[3] == "kitap")
            sf = sum(min(RF, CP*t[2]) for t in eg if t[3] == "fade")
            if sf <= 0: continue
            w = {"kitap": (1-k), "fade": k*sb/sf}
            m = olc(eg, w)
            skor = (m[1]-tb_e[1]) - max(0.0, (tb_e[0]-m[0])/55.0)   # kol_agirlik ile ayni skor
            if skor > bs: bs, best = skor, (a, rr, k)
    a, rr, k = best
    ts = kesit(onc[(a, rr)], sinir, aylar[-1]+1)
    sb = sum(min(RF, CP*t[2]) for t in ts if t[3] == "kitap")
    sf = sum(min(RF, CP*t[2]) for t in ts if t[3] == "fade")
    mt = olc(ts, {"kitap": (1-k), "fade": k*sb/sf})
    print(f"  %{bol*100:.0f} egitim (sinir {sinir}) -> secilen ADX<{a} rr{rr} k={k:.2f}")
    print(f"    OOS: D$ {mt[0]-tb_t[0]:+8.2f} · Dkotu ay {mt[1]-tb_t[1]:+6.2f} puan · "
          f"DbilesikDD {mt[2]-tb_t[2]:+6.2f} · DSharpe {mt[3]-tb_t[3]:+6.3f}")
