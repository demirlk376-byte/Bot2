"""
pro_donchian.py — kullanıcının "kurum seviyesi" donchian fikirleri.

ÜÇÜ DE GERÇEKTEN DENENMEMİŞ:
  1. UYARLAMALI PERİYOT — kanal uzunluğu oynaklığa göre değişir. Düşük
     oynaklıkta KISALIR (kırılımı erken yakala), yüksek oynaklıkta UZAR
     (sahte kırılımdan kaçın). Çoklu-horizon testi SABİT kanalları (20..120)
     denemişti; UYARLAMALI geçiş hiç denenmedi.
  2. BANT SIKIŞMASI — kanal genişliği son 50 barın en dar %X'inde değilse
     işlem AÇMA. "Zaten patlamış kanalda kırıntı toplamak" hipotezi.
  3. ZAMAN STOPU — N bar içinde k×ATR ilerleme yoksa başa başa kapat.
     early_exit_test ZARARDAYSA çıkmayı denemişti (13/13 düştü); bu farklı:
     İLERLEME YOKSA çıkmak.

⚠ Üretici DonchianStrategy.analyze ile BİREBİR kopyalandı (kanal önceki
   `channel` barından, kapanan bar HARİÇ; EMA200 hizası; günlük EMA20 MTF).
   Varsayılan ayarda taban 1579 işlem ÜRETMELİ, yoksa kıyas geçersiz.

Kullanım:  py pro_donchian.py local
"""
import heapq
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
from indicators import atr as atr_fn, ema as ema_fn


def uret(coin, m, kanal=40, uyarlamali=None, bw_p=None, zaman=None):
    tf, win, sl_a, rr, mh = A.CFG["donchian"]
    d = fast_bt.resample(m, tf)
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    n = len(cl)
    atr = atr_fn(d["high"], d["low"], d["close"], 14).values
    ema200 = ema_fn(d["close"], 200).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = cl > _dprev

    # oynaklık durumu: ATR'nin kendi 100-bar ortalamasına oranı
    atr_ort = pd.Series(atr).rolling(100, min_periods=50).mean().values
    anorm = atr / atr_ort

    # her bar için kanal uzunluğu
    if uyarlamali is None:
        kanal_i = np.full(n, kanal, dtype=int)
    else:
        kisa, uzun = uyarlamali
        q = pd.Series(anorm).rolling(250, min_periods=100).rank(pct=True).values
        kanal_i = np.where(q < 0.33, kisa, np.where(q > 0.67, uzun, kanal)).astype(int)
        kanal_i = np.where(np.isfinite(q), kanal_i, kanal)

    # bant genişliği (sabit 40'lık referans kanaldan — gate için)
    ch40h = pd.Series(hi).rolling(40).max().shift(1).values
    ch40l = pd.Series(lo).rolling(40).min().shift(1).values
    bw = (ch40h - ch40l) / cl
    bw_q = pd.Series(bw).rolling(50, min_periods=50).rank(pct=True).values

    out = []; occ = -1
    kmax = int(kanal_i.max())
    for i in range(max(260, kmax + 1), n - 1):
        a = atr[i]
        if not np.isfinite(a) or a <= 0: continue
        k = int(kanal_i[i])
        ch_h = float(np.max(hi[i - k:i])); ch_l = float(np.min(lo[i - k:i]))
        if ch_h <= ch_l: continue
        e200 = ema200[i]
        if not np.isfinite(e200): continue
        c = cl[i]
        d_ = 1 if (c > ch_h and c > e200) else (-1 if (c < ch_l and c < e200) else 0)
        if d_ == 0 or i <= occ: continue
        dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
        if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue
        if bw_p is not None:
            if not np.isfinite(bw_q[i]) or bw_q[i] > bw_p: continue
        sld = sl_a * a
        e = c; slp_ = e - d_ * sld; tp = e + d_ * rr * sld; ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp_: ep = slp_; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp_: ep = slp_; break
                if lo[j] <= tp: ep = tp; break
            if zaman is not None:
                zb, zk = zaman
                if j - i >= zb:
                    mfe = ((hi[i+1:j+1].max() - e) if d_ == 1 else (e - lo[i+1:j+1].min()))
                    if mfe < zk * a:
                        ep = cl[j]; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * A.FEE * e / sld
        out.append((d.index[i].value, d.index[j], R, sld / e)); occ = j
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
    veri = {c: fast_bt.load(c, source=src) for c in A.DONCH}
    ham0 = []
    for c in A.DONCH: ham0 += uret(c, veri[c])
    t = olc(portfoy(ham0))
    print(f"\n{'=' * 104}\n=== PRO DONCHIAN — uyarlamalı periyot · bant sıkışması · zaman stopu ===")
    print(f"  TABAN {t['n']} işlem · ${t['kar']:+.2f} · maxDD %{t['dd']:.2f} · "
          f"en kötü ay %{t['kotu']:.2f} · WR %{t['wr']:.1f} · ortR {t['ortR']:+.4f}")
    if t["n"] != 1579:
        print(f"  ⚠ taban 1579 DEĞİL ({t['n']}) — üretici ankorla birebir değil.")
        print(f"    Kıyas yine de kendi tabanına göre geçerli, ama ankor rakamlarıyla")
        print(f"    karşılaştırılamaz. SEBEBİ ARAŞTIRILMALI.")
    print(f"\n  {'varyant':<36s} {'n':>5s} {'WR':>6s} {'ortR':>8s} {'kâr $':>10s} "
          f"{'Δ$':>9s} {'ΔmaxDD':>7s} {'Δkötüay':>8s}  BAR")
    VAR = [("uyarlamalı 20/40/60 (kullanıcı)", dict(uyarlamali=(20, 60))),
           ("uyarlamalı 30/40/50", dict(uyarlamali=(30, 50))),
           ("uyarlamalı TERS 60/40/20", dict(uyarlamali=(60, 20))),
           ("bant sıkışma: en dar %25", dict(bw_p=0.25)),
           ("bant sıkışma: en dar %50", dict(bw_p=0.50)),
           ("zaman stopu 6 bar / 1.0 ATR", dict(zaman=(6, 1.0))),
           ("zaman stopu 10 bar / 1.0 ATR", dict(zaman=(10, 1.0))),
           ("uyarlamalı + sıkışma %50", dict(uyarlamali=(20, 60), bw_p=0.50))]
    for ad, kw in VAR:
        ham = []
        for c in A.DONCH: ham += uret(c, veri[c], **kw)
        m = olc(portfoy(ham))
        gec = (m["kar"] - t["kar"] >= 36 and m["kotu"] >= t["kotu"]
               and m["dd"] - t["dd"] <= 2.0)
        print(f"  {ad:<36s} {m['n']:>5d} {m['wr']:>5.1f}% {m['ortR']:>+8.4f} "
              f"{m['kar']:>+10.2f} {m['kar']-t['kar']:>+9.2f} {m['dd']-t['dd']:>+7.2f} "
              f"{m['kotu']-t['kotu']:>+8.2f}  {'✓ GEÇTİ' if gec else '✗'}")
    print(f"{'=' * 104}\n")


if __name__ == "__main__":
    main()
