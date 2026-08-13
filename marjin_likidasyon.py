"""
marjin_likidasyon.py — ANKORUN GÖRMEDİĞİ ŞEY: likidasyon toparlanmayı öldürüyor.

marjin_kapasite.py şunu ölçtü: 10x kaldıraçta likidasyon hareketi ~%9.50, ve işlemlerin
%2.31'inin STOP MESAFESİ bundan daha geniş. O işlemlerde fiyat %9.5 aleyhe gidince
pozisyon likide olur — stop hiç çalışmaz.

⚠️ PARA AÇISINDAN BU KÖTÜ DEĞİL: geniş stoplu işlemde pozisyon KÜÇÜKTÜR (risk sabit
tutulduğu için), marjin de küçüktür, ve izole marjinde kayıp o marjinle sınırlıdır.
    slp %12.00 → stop kaybı $4.57 · likidasyon kaybı $3.62
    slp %18.58 → stop kaybı $4.57 · likidasyon kaybı $2.34
Yani likidasyon, tam stopa gitmekten DAHA UCUZ.

ASIL SORUN: likidasyon işlemi KAPATIR. %9.5 düşüp sonra toparlanıp hedefe giden bir
işlem, stop yerinde dursa KAZANAN olacakken likide olup KAYBEDEN oluyor.
ANKOR BUNU HİÇ MODELLEMİYOR — o işlemleri "dayandı ve toparlandı" diye kazanç sayıyor.

BU BETİK: bar döngüsünün İÇİNE likidasyon kontrolü koyar. Stop mesafesi likidasyon
hareketinden genişse, etkin stop LİKİDASYON mesafesine çekilir (fiyat olarak daha
yakın olduğu için önce ona değer). R o noktadan hesaplanır ve işlem orada BİTER.

⚠️ EŞDEĞERLİK: kaldıraç sonsuz alınınca (likidasyon devre dışı) betik ankoru BİREBİR
üretmeli. Üretmiyorsa hiçbir sayı okunmaz.

Kullanım:  py marjin_likidasyon.py local
"""
import heapq
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAKIM = 0.005
CAP_YENI = 1.50


def gen_lik(sleeve, m, lik):
    """A.gen + bar döngüsünde LİKİDASYON kontrolü. lik=None → likidasyon yok (=ankor)."""
    tf, win, sl_a, rr, mh = A.CFG[sleeve]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
    s = (DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve == "donchian" else
         SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    out = []; occ = -1; likide = 0
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        if sleeve == "squeeze":
            xv = adx_ser[i] if np.isfinite(adx_ser[i]) else 20.0
            if xv <= 20.0: continue
        sg = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)); d_ = sg.direction
        if d_ == 0 or i <= occ: continue
        if sleeve == "donchian":
            dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
            if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue
        e = cl[i]; sld = sl_a * a; slp_o = e - d_ * sld; tp = e + d_ * rr * sld
        # LİKİDASYON: stop mesafesi likidasyondan genişse etkin stop öne çekilir
        etkin = slp_o; lik_oldu = False
        if lik is not None and (sld / e) > lik:
            etkin = e - d_ * lik * e
            lik_oldu = True
        ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= etkin: ep = etkin; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= etkin: ep = etkin; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        if lik_oldu and abs(ep - etkin) < 1e-12:
            likide += 1
        R = d_ * (ep - e) / sld - 2 * A.FEE * e / sld
        out.append((idx[i].value, idx[j].value, R, sld / e)); occ = j
    return out, likide


def koltuk(ham):
    ham = sorted(ham, key=lambda z: z[0])
    oh = []; ctr = 0; al = []
    for e, x, R, slp in ham:
        while oh and oh[0][0] <= e: heapq.heappop(oh)
        if len(oh) < A.MAXPOS:
            ctr += 1; heapq.heappush(oh, (x, ctr)); al.append((x, R, slp))
    return al


def olc(al, cap=CAP_YENI):
    r = np.array([a[1] for a in al]); sp = np.array([a[2] for a in al])
    pnl = r * np.minimum(A.RISKF, cap * sp) * A.BAL0
    eq = A.BAL0 + np.cumsum(pnl)
    ex = [pd.Timestamp(a[0]) for a in al]
    mon = pd.Series(pnl).groupby([x.to_period("M") for x in ex]).sum() / A.BAL0 * 100
    kaz = pnl[pnl > 0].sum(); kay = -pnl[pnl < 0].sum()
    return dict(n=len(al), tot=float(pnl.sum()),
                pf=float(kaz / kay) if kay > 0 else float("inf"),
                wr=float((r > 0).mean() * 100), ortR=float(r.mean()),
                dd=float(A.maxdd(np.concatenate([[A.BAL0], eq]))), worst=float(mon.min()))


def topla(source, lik):
    ham = []; lk = 0
    for kol, coins in (("donchian", A.DONCH), ("squeeze", A.SQZ)):
        for c in coins:
            o, k = gen_lik(kol, fast_bt.load(c, source=source), lik)
            ham += o; lk += k
    for c in A.BB_COINS:
        for t in A.gen_bb(fast_bt.load(c, source=source)):
            ham.append((t[0], t[1].value, t[2], t[3]))
    return ham, lk


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    print(f"\n{'=' * 104}")
    print("=== LİKİDASYON: ankorun görmediği kayıp ===")
    ham0, _ = topla(source, None)
    a0 = koltuk(ham0); v0 = olc(a0, cap=A.CAP)
    ok = len(a0) == 1579 and abs(v0["tot"] - 1420.66) < 0.01
    print(f"  EŞDEĞERLİK (likidasyon KAPALI = ankor): {len(a0)} işlem / "
          f"${v0['tot']:+.2f} → {'✓ BİREBİR' if ok else '✗ SAPMA'}")
    if not ok:
        print("  HİÇBİR SAYI OKUNMAZ."); return
    taban = olc(koltuk(ham0))
    print(f"\n  {'kaldıraç':>9s} {'likid.hareketi':>15s} {'likide olan':>12s} "
          f"{'işlem':>6s} {'netPnL$':>9s} {'Δ$':>7s} {'PF':>6s} {'WR%':>6s} "
          f"{'ortR':>7s} {'maxDD%':>7s} {'kötü ay%':>9s}")
    print(f"  {'—':>9s} {'yok (ankor)':>15s} {0:>12d} {taban['n']:>6d} "
          f"{taban['tot']:>+9.0f} {0:>+7.0f} {taban['pf']:>6.2f} {taban['wr']:>6.1f} "
          f"{taban['ortR']:>+7.3f} {taban['dd']:>7.1f} {taban['worst']:>+9.1f}")
    for lev in (5, 10, 15, 20):
        lik = 1.0 / lev - BAKIM
        ham, lk = topla(source, lik)
        v = olc(koltuk(ham))
        mark = "  ← ŞU AN" if lev == 10 else ""
        print(f"  {lev:>8d}x {lik*100:>14.2f}% {lk:>12d} {v['n']:>6d} "
              f"{v['tot']:>+9.0f} {v['tot']-taban['tot']:>+7.0f} {v['pf']:>6.2f} "
              f"{v['wr']:>6.1f} {v['ortR']:>+7.3f} {v['dd']:>7.1f} "
              f"{v['worst']:>+9.1f}{mark}")
    print(f"\n{'=' * 104}\n=== NASIL OKUNUR ===")
    print("  · 'likide olan' = stop yerine likidasyonla kapanan işlem sayısı.")
    print("  · Δ$ negatifse ANKOR OLDUĞUNDAN İYİ görünüyor demektir: o işlemleri")
    print("    'dayandı ve toparlandı' diye kazanç sayıyor ama canlıda likide olurlardı.")
    print("  · 10x satırındaki Δ$, BUGÜN canlıda taşıdığımız ölçülmemiş maliyettir.")


if __name__ == "__main__":
    main()
