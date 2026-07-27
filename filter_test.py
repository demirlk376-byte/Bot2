"""
filter_test.py — CANLI-DOĞRU filtre testi (filtre ÜRETİM SIRASINDA uygulanır).
Post-hoc filtreleme (işlem üretildikten sonra elemek) YANLIŞ: canlıda filtre bir
sinyali elerse slot boş kalır, sonraki sinyal işlem açabilir. Bu araç filtreyi
sinyal anında uygular (elenen slotu meşgul etmez) → gerçek canlı davranış.

Filtreler: baseline / +MTF (günlük trend) / +EMA200 / +EMA50-200 (golden).
Her sleeve, PF/total + yıl-yıl. baseline faithful_bt ile birebir olmalı (doğrulama).

Kullanım:  py filter_test.py local
"""
import sys
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn, ema as ema_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAL = 190.0; FEE = 0.0001; RISK = 0.02
DEPLOY = {   # donchian rr 2.0→2.5 DEPLOY EDİLDİ → MTF'i yeni rr'nin ÜSTÜNDE test et
    "donchian": (["SOL", "ETH", "ADA", "NEAR", "BCH"], "4h", 259, 2.0, 2.5, 30),
    "squeeze":  (["XRP", "DOGE", "TRX", "XLM"], "1h", 119, 2.0, 2.5, 48),
}
FILTERS = ["baseline", "+MTF"]   # rr2.5 üstünde sadece MTF'i doğrula (diğerleri elendi)


def run(sleeve, coin, m, which):
    """Tek filtre ile TAM üretim (filtre sinyal anında, elenen slotu meşgul etmez)."""
    _, tf, win, sl_a, rr, mh = DEPLOY[sleeve]
    d = fast_bt.resample(m, tf)
    ema50 = ema_fn(d["close"], 50).values
    ema200 = ema_fn(d["close"], 200).values
    # CANLI-BİREBİR MTF (lookahead YOK): canlı d1d=df_4h.resample("1D").close.last() +
    # ewm20 dahil-bugün; cebirsel olarak == kapanış > DÜNE kadar tamamlanmış EMA20.
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up_daily = d["close"].values > _dprev
    s = (DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve == "donchian" else
         SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values; idx = d.index; n = len(cl)
    out = []; occ = -1
    for i in range(260, n):
        sub = d.iloc[max(0, i - win):i + 1]
        a = atr_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if np.isnan(a) or a <= 0: continue
        adxv = adx_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        adxv = float(adxv) if np.isfinite(adxv) else 20.0
        if sleeve == "squeeze" and adxv <= 20.0: continue
        sg = s.analyze(sub, float(a))
        if sg.direction == 0 or i <= occ or i >= n - 1: continue
        d_ = sg.direction; e = cl[i]
        # ── FİLTRE (sinyal anında; geçmezse HİÇ üretme, occ değişmez) ──
        if which != "baseline" and (np.isnan(ema200[i]) or np.isnan(ema50[i])):
            pass  # ema yoksa filtre uygulanamaz → baseline gibi geç
        elif which == "+MTF":
            dup = bool(up_daily[i]) if not (isinstance(up_daily[i], float) and np.isnan(up_daily[i])) else True
            if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue
        elif which == "+EMA200":
            if not ((d_ == 1 and e > ema200[i]) or (d_ == -1 and e < ema200[i])): continue
        elif which == "+EMA50/200":
            if not ((d_ == 1 and ema50[i] > ema200[i]) or (d_ == -1 and ema50[i] < ema200[i])): continue
        elif which == "+PxBoth":   # fiyat hem EMA50 hem EMA200 trend tarafında (çift onay)
            if d_ == 1 and not (e > ema50[i] and e > ema200[i]): continue
            if d_ == -1 and not (e < ema50[i] and e < ema200[i]): continue
        elif which == "+MTF+E50/200":   # kazanan MTF + golden-cross birlikte
            dup = bool(up_daily[i]) if not (isinstance(up_daily[i], float) and np.isnan(up_daily[i])) else True
            mtf_ok = (d_ == 1 and dup) or (d_ == -1 and not dup)
            gold_ok = (d_ == 1 and ema50[i] > ema200[i]) or (d_ == -1 and ema50[i] < ema200[i])
            if not (mtf_ok and gold_ok): continue
        sld = sl_a * a; slp = e - d_ * sld; tp = e + d_ * rr * sld; ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * FEE * e / sld
        out.append({"R": R, "year": idx[i].year}); occ = j
    return out


def st(tr):
    if not tr: return "yok"
    r = np.array([t["R"] for t in tr]); gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    pf = gp / gl if gl > 0 else 9.99
    return f"n={len(r):>4d} WR{(r>0).mean():>3.0%} PF{pf:4.2f} ${r.sum()*BAL*RISK:+8.2f}"


def yrbits(tr):
    return " ".join(f"{y}:${np.array([t['R'] for t in tr if t['year']==y]).sum()*BAL*RISK:+.0f}"
                    for y in sorted(set(t["year"] for t in tr)))


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    grand = {f: [] for f in FILTERS}
    for sleeve, (coins, *_) in DEPLOY.items():
        per = {f: [] for f in FILTERS}
        ms = {}
        for coin in coins:
            try: ms[coin] = fast_bt.load(coin, source=source)
            except Exception as e: print(f"  {coin}: {e}")
        for f in FILTERS:
            for coin, m in ms.items():
                per[f] += run(sleeve, coin, m, f)
            grand[f] += per[f]
        print(f"\n{'='*70}\n=== {sleeve.upper()} (filtre ÜRETİMDE — canlı-doğru) ===")
        for f in FILTERS:
            print(f"  {f:11s}: {st(per[f])}")
        for f in FILTERS:
            print(f"     {f:11s} yıl-yıl: {yrbits(per[f])}")
    print(f"\n{'='*70}\n=== TOPLAM ===")
    for f in FILTERS:
        print(f"  {f:11s}: {st(grand[f])}")
    print("\n  baseline faithful_bt/faithful_all ile birebir olmalı (doğrulama).")
    print("  Bir filtre PF+total'i HER YIL koruyup artırıyorsa GERÇEK kazanç; yoksa geç.")


if __name__ == "__main__":
    main()
