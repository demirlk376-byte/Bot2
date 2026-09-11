"""
mtf_pb_koltuk.py — KOLTUK REKABETİNİN MALİYETİ, işlem işlem.

Aday kol havuza girince MEVCUT kolların kaç işlemi DÜŞÜYOR ve o işlemler ne
değerindeydi? (7 koltuk ortak; yeni kol eskisini BLOKLAR.)
Ayrıca: gürültü eşiği hesabı (sigma*sqrt(2 ln N)).
"""
import numpy as np, pandas as pd
import deployed_backtest as A
from mtf_pb_taban import ham_taban, strip, olc
from mtf_pb_tara import veri, kol_uret, tek_basina

ADAYLAR = [("T2/rsi/atr1.5/rr3.0  (Δ$ argmax)", dict(trend="T2", tetik="rsi", stop=("atr",1.5), rr=3.0)),
           ("T1/rsi/swing10/rr2.5 (tek-başına argmax)", dict(trend="T1", tetik="rsi", stop=("swing",10), rr=2.5))]


def etiketli(d):
    o = []
    for kol in ("donch", "sqz", "bb"):
        for c, e, x, R, sp in d[kol]:
            o.append((e, x, R, sp, kol, c))
    return o


def sec(ev):
    import heapq
    ev = sorted(ev, key=lambda t: t[0]); oh = []; tk = []; ctr = 0
    for t in ev:
        e, x = t[0], t[1]
        while oh and oh[0][0].value <= e: heapq.heappop(oh)
        if len(oh) < A.MAXPOS:
            ctr += 1; heapq.heappush(oh, (x, ctr, 0)); tk.append(t)
    return tk


def main():
    V = veri(); d = ham_taban()
    tb = etiketli(d)
    T0 = sec(tb)
    kar = lambda ts: float(sum(R * min(A.CANLI_RISKF, A.CANLI_CAP * sp) * A.BAL0
                               for _, _, R, sp, *_ in ts))
    print(f"  TABAN: {len(T0)} işlem ${kar(T0):+.2f}")
    for ad, kw in ADAYLAR:
        aday = [(e, x, R, sp, "mtfpb", "-") for e, x, R, sp in kol_uret(V, **kw)]
        C = sec(tb + aday)
        eski = [t for t in C if t[4] != "mtfpb"]; yeni = [t for t in C if t[4] == "mtfpb"]
        s0 = set(map(id, T0))
        dusen = [t for t in T0 if id(t) not in set(map(id, eski))]
        print(f"\n  {ad}")
        print(f"    aday HAM sinyal {len(aday)} → koltuk alan {len(yeni)} (%{len(yeni)/len(aday)*100:.0f})")
        print(f"    mevcut kollar: {len(T0)} → {len(eski)} işlem  (DÜŞEN {len(dusen)})")
        d_kol = {}
        for t in dusen: d_kol[t[4]] = d_kol.get(t[4], 0) + 1
        print(f"    düşen işlemlerin kol dağılımı: {d_kol}")
        print(f"    DÜŞEN işlemlerin değeri      : ${kar(dusen):+.2f}")
        print(f"    yeni kolun kattığı           : ${kar(yeni):+.2f}")
        print(f"    net (birleşik − taban)       : ${kar(C)-kar(T0):+.2f}")

    # gürültü eşiği
    print("\n  --- ÇOKLU KARŞILAŞTIRMA EŞİĞİ ---")
    t = kol_uret(V, **ADAYLAR[1][1])
    sp = np.array([x[3] for x in t]); n = len(t)
    dpr = np.minimum(A.CANLI_RISKF, A.CANLI_CAP * sp).mean() * A.BAL0
    sig_R = 1.465
    se_usd = sig_R * np.sqrt(n) * dpr
    for N in (108, 113):
        esik = np.sqrt(2 * np.log(N))
        print(f"    N={N} hücre: beklenen en iyi ≈ {esik:.2f}σ ; σ(toplam $) ≈ ${se_usd:.0f} "
              f"(n={n}, $/R={dpr:.2f}) → saf gürültü taramasının beklenen en iyisi ≈ ${esik*se_usd:.0f}")
    print(f"    GÖZLENEN en iyi tek-başına: +$139  → tek hücre için bile {139/se_usd:.2f}σ")


if __name__ == "__main__":
    main()
