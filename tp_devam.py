"""
tp_devam.py — YENİ STRATEJİ: kazanan çıkıştan sonra YENİDEN GİR.

ÖLÇÜMDEN ÇIKAN FİKİR (2026-09-10, MFE analizi):
  TP ile çıkan 418 işlem, çıkıştan SONRAKİ 30 barda ortalama **+4.90R**'ye
  gidiyor (medyan 3.94), ve **%62'si 0.5R'den fazla devam ediyor**.
  Yani hedef, kazananları erken kesiyor.

İKİ BİLİNEN ÇÖZÜM DE DÜŞTÜ:
  · TP'yi kaldırmak (rr=5) → en kötü ay −%21 → −%29.7
  · trailing → 10/10 düştü, OOS −$365 (kırılımlar pullback'te atıyor)

BU FARKLI: pozisyonu açık TUTMUYORUZ. TP'de kârı alıyoruz, sonra TAZE bir
stop'la YENİDEN giriyoruz. Fark kritik — trailing'de geri çekilme kazancı
yer, burada kazanç ZATEN CEBE GİRMİŞ oluyor ve yeni pozisyonun kendi −1R
tavanı var.

⚠ DEPODA STOP SONRASI yeniden giriş test edilmişti (5 bar −$112, 10 bar −$96).
   Bu ONUN TERSİ: kaybeden değil KAZANAN çıkıştan sonra.

⚠ KOLTUK MALİYETİ: yeniden giriş coini işgal eder ve sıradaki doğal sinyali
   bloklar. Ölçüm ORTAK 7 koltukta (A.seat_select) yapılıyor.

Kullanım:  py tp_devam.py local
"""
import heapq
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
from indicators import atr as atr_fn
from strategies.donchian import DonchianStrategy

KAYMA = 15.85 / 1e4


def uret(coin, m, devam=0, rr_devam=2.5):
    """devam = TP sonrası kaç kez yeniden girilecek (0 = ankor)."""
    tf, win, sl_a, rr, mh = A.CFG["donchian"]
    d = fast_bt.resample(m, tf)
    atr = atr_fn(d["high"], d["low"], d["close"], 14).values
    _dc = d["close"].resample("1D").last().dropna()
    _dp = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dp
    s = DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
    hi, lo, cl, idx, n = d["high"].values, d["low"].values, d["close"].values, d.index, len(d)
    out = []; occ = -1

    def sur(i0, e, d_, sld, rr_):
        """i0 barından sonra bir pozisyonu yürüt → (cikis_i, R, tp_mi)"""
        slp_ = e - d_ * sld; tp = e + d_ * rr_ * sld
        for j in range(i0 + 1, min(i0 + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp_: return j, d_ * (slp_ - e) / sld, False
                if hi[j] >= tp:   return j, d_ * (tp - e) / sld, True
            else:
                if hi[j] >= slp_: return j, d_ * (slp_ - e) / sld, False
                if lo[j] <= tp:   return j, d_ * (tp - e) / sld, True
        j = min(i0 + mh, n - 1)
        return j, d_ * (cl[j] - e) / sld, False

    for i in range(260, n - 1):
        a = atr[i]
        if not np.isfinite(a) or a <= 0: continue
        sg = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)); d_ = sg.direction
        if d_ == 0 or i <= occ: continue
        u = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
        if not ((d_ == 1 and u) or (d_ == -1 and not u)): continue
        sld = sl_a * a; e = cl[i]
        j, R, tp_mi = sur(i, e, d_, sld, rr)
        out.append((idx[i].value, idx[j], R - 2 * A.FEE * e / sld, sld / e)); occ = j
        # ── TP SONRASI YENİDEN GİRİŞ ──
        k = 0
        while tp_mi and k < devam and j < n - 1:
            a2 = atr[j]
            if not np.isfinite(a2) or a2 <= 0: break
            e2 = cl[j]; sld2 = sl_a * a2
            j2, R2, tp_mi = sur(j, e2, d_, sld2, rr_devam)
            out.append((idx[j].value, idx[j2], R2 - 2 * A.FEE * e2 / sld2, sld2 / e2))
            j = j2; occ = j2; k += 1
    return out


def portfoy(donch):
    sabit = []
    for c in A.SQZ: sabit += A.gen("squeeze", fast_bt.load(c, source="local"))
    for c in A.BB_COINS: sabit += A.gen_bb(fast_bt.load(c, source="local"))
    ev = sorted(donch + sabit, key=lambda t: t[0])
    oh = []; tk = []; ctr = 0
    for e, x, R, sp in ev:
        while oh and oh[0][0].value <= e: heapq.heappop(oh)
        if len(oh) < A.MAXPOS:
            ctr += 1; heapq.heappush(oh, (x, ctr, R)); tk.append((x, R, sp))
    return sorted(tk, key=lambda t: t[0])


def olc(tk, kayma=False):
    R = np.array([r for _, r, _ in tk]); sp = np.array([s for _, _, s in tk])
    ex = pd.to_datetime([x for x, _, _ in tk])
    if kayma: R = R - KAYMA / sp
    eff = np.minimum(A.CANLI_RISKF, A.CANLI_CAP * sp); pnl = R * eff * A.BAL0
    eq = A.BAL0 + np.cumsum(pnl)
    ay = pd.Series(pnl, index=ex.tz_localize(None).to_period("M")).groupby(level=0).sum() / A.BAL0 * 100
    return {"n": len(tk), "kar": pnl.sum(), "dd": A.maxdd(np.concatenate([[A.BAL0], eq])),
            "kotu": ay.min(), "wr": (R > 0).mean() * 100, "ortR": R.mean()}


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "local"
    veri = {c: fast_bt.load(c, source=src) for c in A.DONCH}
    ham0 = []
    for c in A.DONCH: ham0 += uret(c, veri[c], devam=0)
    t = olc(portfoy(ham0)); tk_ = olc(portfoy(ham0), kayma=True)
    print(f"\n{'=' * 100}\n=== TP SONRASI YENİDEN GİRİŞ ===")
    print(f"  TABAN {t['n']} işlem · kaymasız ${t['kar']:+.2f} · KAYMALI ${tk_['kar']:+.2f} · "
          f"maxDD %{t['dd']:.2f} · en kötü ay %{t['kotu']:.2f}")
    if t["n"] != 1579:
        print(f"  ⚠ taban 1579 değil ({t['n']}) — kıyas kendi tabanına göre geçerli.")
    print(f"\n  {'varyant':<26s} {'n':>5s} {'WR':>6s} {'ortR':>8s} {'kaymasız Δ$':>12s} "
          f"{'KAYMALI Δ$':>11s} {'ΔmaxDD':>7s} {'Δkötüay':>8s}  BAR")
    for dv, rrd in ((1, 2.5), (1, 2.0), (1, 1.5), (2, 2.5), (3, 2.5)):
        ham = []
        for c in A.DONCH: ham += uret(c, veri[c], devam=dv, rr_devam=rrd)
        p = portfoy(ham); m = olc(p); mk = olc(p, kayma=True)
        gec = (mk["kar"] - tk_["kar"] >= 36 and m["kotu"] >= t["kotu"]
               and m["dd"] - t["dd"] <= 2.0)
        print(f"  {f'{dv}x devam · rr {rrd}':<26s} {m['n']:>5d} {m['wr']:>5.1f}% "
              f"{m['ortR']:>+8.4f} {m['kar']-t['kar']:>+12.2f} {mk['kar']-tk_['kar']:>+11.2f} "
              f"{m['dd']-t['dd']:>+7.2f} {m['kotu']-t['kotu']:>+8.2f}  {'✓ GEÇTİ' if gec else '✗'}")
    print(f"{'=' * 100}\n")


if __name__ == "__main__":
    main()
