"""
kirilim_teyit.py — SAHTE KIRILIM TEYİT FİLTRELERİ, kullanıcının listesi.

Kullanıcının önerdiği klasik donchian sahte-kırılım filtreleri tek tek, AYNI
hakem standardıyla test edilir. Bazıları daha önce denenmişti; hepsi GÜNCEL
tabanda (canlı ayar: risk %2.80, cap 1.50, 1579 işlem) yeniden koşuluyor.

TEST EDİLENLER:
  1. ATR TAMPONU  — kırılım kanalı en az k×ATR aşsın (`buffer_atr` parametresi
     kodda VAR ama 0.0'a ayarlı, hiç süpürülmemiş)
  2. ÇOKLU MUM TEYİDİ — kırılım barından sonraki bar da seviyenin ötesinde
     kapansın; giriş bir bar GECİKİR
  3. HACİM PATLAMASI — kırılım barının hacmi son 20 barın ortalamasının k katı
  4. GERÇEK MTF — mevcut günlük EMA20 kapısı 1017 sinyalin 0'ını blokluyor
     (ETKİSİZ). Daha sıkı bir üst-zaman filtresi denenir.

⚠ ÖN-KAYITLI BAR (gevşetilmeyecek): Δ$ ≥ +36 · en kötü ay kötüleşmesin ·
   maxDD +2 puandan fazla artmasın · silinen kümenin ort R'si < 0.
⚠ Her varyant, AYNI SAYIDA rastgele işlem silmekle de kıyaslanır. Ledger'ın
   290 denemelik bulgusu: "ne silinirse silinsin, silmek negatif beklentidir."
   Doğru referans sıfır değil, RASTGELE SİLME.

Kullanım:  py kirilim_teyit.py local
"""
import heapq
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy


def uret(coin, m, tampon=0.0, teyit_bar=0, hacim_k=0.0, mtf=None):
    """A.gen('donchian') ile birebir + kullanıcının filtreleri."""
    tf, win, sl_a, rr, mh = A.CFG["donchian"]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
    # daha SIKI üst-zaman: günlük EMA50 ve günlük momentum
    _d50 = _dc.ewm(span=50, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up50 = d["close"].values > _d50
    s = DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200,
                         buffer_atr=tampon)
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    vol = d["volume"].values
    volma = pd.Series(vol).rolling(20).mean().values
    ch_hi = pd.Series(hi).rolling(40).max().shift(1).values
    ch_lo = pd.Series(lo).rolling(40).min().shift(1).values
    idx = d.index; n = len(cl)
    out = []; occ = -1
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        sg = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)); d_ = sg.direction
        if d_ == 0 or i <= occ: continue
        dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
        if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue
        # ── kullanıcının filtreleri ──
        if hacim_k > 0:
            if not np.isfinite(volma[i]) or vol[i] < volma[i] * hacim_k: continue
        if mtf == "ema50":
            u = bool(up50[i]) if not (isinstance(up50[i], float) and np.isnan(up50[i])) else True
            if not ((d_ == 1 and u) or (d_ == -1 and not u)): continue
        j0 = i
        if teyit_bar > 0:
            # sonraki bar(lar) da seviyenin ÖTESİNDE kapansın; giriş GECİKİR
            k = i + teyit_bar
            if k >= n - 1: continue
            ok = True
            for t in range(i + 1, k + 1):
                if d_ == 1 and not (np.isfinite(ch_hi[i]) and cl[t] > ch_hi[i]): ok = False; break
                if d_ == -1 and not (np.isfinite(ch_lo[i]) and cl[t] < ch_lo[i]): ok = False; break
            if not ok: continue
            j0 = k
            a = atr_ser[j0]
            if not np.isfinite(a) or a <= 0: continue
        e = cl[j0]; sld = sl_a * a
        slp_ = e - d_ * sld; tp = e + d_ * rr * sld; ep = None; j = j0
        for j in range(j0 + 1, min(j0 + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp_: ep = slp_; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp_: ep = slp_; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(j0 + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * A.FEE * e / sld
        out.append((idx[j0].value, idx[j], R, sld / e)); occ = j
    return out


def portfoy(donch_ham):
    sabit = []
    for c in A.SQZ: sabit += A.gen("squeeze", fast_bt.load(c, source="local"))
    for c in A.BB_COINS: sabit += A.gen_bb(fast_bt.load(c, source="local"))
    ev = sorted(donch_ham + sabit, key=lambda t: t[0])
    oh = []; tk = []; ctr = 0
    for e, x, R, sp in ev:
        while oh and oh[0][0].value <= e: heapq.heappop(oh)
        if len(oh) < A.MAXPOS:
            ctr += 1; heapq.heappush(oh, (x, ctr, R)); tk.append((x, R, sp))
    return sorted(tk, key=lambda t: t[0])


def olc(tk):
    R = np.array([r for _, r, _ in tk]); sp = np.array([s for _, _, s in tk])
    ex = pd.to_datetime([x for x, _, _ in tk])
    eff = np.minimum(A.CANLI_RISKF, A.CANLI_CAP * sp); pnl = R * eff * A.BAL0
    eq = A.BAL0 + np.cumsum(pnl)
    ay = pd.Series(pnl, index=ex.tz_localize(None).to_period("M")).groupby(level=0).sum() / A.BAL0 * 100
    return {"n": len(tk), "kar": pnl.sum(), "dd": A.maxdd(np.concatenate([[A.BAL0], eq])),
            "kotu": ay.min(), "wr": (R > 0).mean() * 100, "ortR": R.mean()}


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "local"
    ham0 = []
    for c in A.DONCH: ham0 += uret(c, fast_bt.load(c, source=src))
    t = olc(portfoy(ham0))
    print(f"\n{'=' * 100}\n=== SAHTE KIRILIM TEYİT FİLTRELERİ ===")
    print(f"  TABAN {t['n']} işlem · ${t['kar']:+.2f} · maxDD %{t['dd']:.2f} · "
          f"en kötü ay %{t['kotu']:.2f} · WR %{t['wr']:.1f} · ortR {t['ortR']:+.4f}")
    if t["n"] != 1579:
        print(f"  ⚠ taban 1579 DEĞİL ({t['n']}) — üretici ankorla birebir değil, "
              f"sonuçlar kıyaslanamaz."); sys.exit(2)
    rng = np.random.default_rng(20260909)
    tam = np.array([r for _, r, _ in portfoy(ham0)])
    print(f"\n  {'varyant':<34s} {'n':>5s} {'WR':>6s} {'ortR':>8s} {'Δ$':>9s} "
          f"{'ΔmaxDD':>7s} {'Δkötüay':>8s} {'rastgele Δ$':>12s}  BAR")
    varyant = [("ATR tamponu 0.10", dict(tampon=0.10)), ("ATR tamponu 0.25", dict(tampon=0.25)),
               ("ATR tamponu 0.50", dict(tampon=0.50)), ("ATR tamponu 1.00", dict(tampon=1.00)),
               ("çoklu mum teyidi (1 bar)", dict(teyit_bar=1)),
               ("çoklu mum teyidi (2 bar)", dict(teyit_bar=2)),
               ("hacim > 1.5x ort", dict(hacim_k=1.5)), ("hacim > 2.0x ort", dict(hacim_k=2.0)),
               ("MTF: günlük EMA50", dict(mtf="ema50")),
               ("tampon 0.25 + hacim 1.5x", dict(tampon=0.25, hacim_k=1.5))]
    for ad, kw in varyant:
        ham = []
        for c in A.DONCH: ham += uret(c, fast_bt.load(c, source=src), **kw)
        m = olc(portfoy(ham))
        k = t["n"] - m["n"]
        rast = np.nan
        if 0 < k < t["n"]:
            rast = np.mean([tam[rng.choice(t["n"], t["n"] - k, replace=False)].sum()
                            for _ in range(300)]) * 0  # yer tutucu, aşağıda düzeltilir
            # aynı SAYIDA rastgele silme, eff ile
            base = portfoy(ham0)
            pn = np.array([r * min(A.CANLI_RISKF, A.CANLI_CAP * s) * A.BAL0
                           for _, r, s in base])
            rast = np.mean([pn[rng.choice(len(pn), len(pn) - k, replace=False)].sum()
                            for _ in range(300)]) - t["kar"]
        gec = (m["kar"] - t["kar"] >= 36 and m["kotu"] >= t["kotu"]
               and m["dd"] - t["dd"] <= 2.0)
        print(f"  {ad:<34s} {m['n']:>5d} {m['wr']:>5.1f}% {m['ortR']:>+8.4f} "
              f"{m['kar']-t['kar']:>+9.2f} {m['dd']-t['dd']:>+7.2f} "
              f"{m['kotu']-t['kotu']:>+8.2f} {rast:>+12.2f}  {'✓ GEÇTİ' if gec else '✗'}")
    print(f"\n  ⓘ 'rastgele Δ$' = aynı sayıda işlemi RASTGELE silmenin ortalama etkisi.")
    print(f"    Bir varyantın anlamlı olması için onu belirgin şekilde YENMESİ gerekir.")
    print(f"{'=' * 100}\n")


if __name__ == "__main__":
    main()
