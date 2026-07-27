"""
coin_expand.py — Deploy-dışı coin'leri mevcut sleeve'lerde test et (canlı-doğru, yıl-yıl).
Amaç: filtre yolu kapandı → çeşitlendirme (ledger: "doğru büyüme düğmesi"). Aynı edge'i
daha çok ROBUST coin'de koşturarak mutlak karı büyüt, per-trade riski artırmadan.

Kural (MEXC netted = coin başına tek pozisyon): yeni coin TEK bir sleeve'e atanır.
Mevcut coinlere DOKUNULMAZ. Aday = HER YIL pozitif (robust), tek-yıl taşıması REDDEDİLİR.

Sleeve config = DEPLOY (canlı):
  donchian: 4h, channel40, EMA200, SL2×ATR, rr2.5, +MTF (günlük EMA20 hizası), maxhold30
  squeeze : 1h, KC1.5/coil5, ADX>20, SL2×ATR, rr2.5, MTF(içeride), maxhold48

Kullanım:  py coin_expand.py local
"""
import sys
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn, ema as ema_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAL = 190.0; FEE = 0.0001; RISK = 0.02
DEPLOYED = {"SOL", "ETH", "ADA", "NEAR", "BCH", "XRP", "DOGE", "TRX", "XLM"}
CANDIDATES = ["AAVE", "ALGO", "ATOM", "AVAX", "BNB", "BTC", "DOT", "ETC", "ICP", "LINK", "LTC", "VET", "XMR"]
CFG = {  # tf, win, sl_a, rr, maxhold
    "donchian": ("4h", 259, 2.0, 2.5, 30),
    "squeeze":  ("1h", 119, 2.0, 2.5, 48),
}


def run(sleeve, m):
    tf, win, sl_a, rr, mh = CFG[sleeve]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    # donchian MTF: günlük EMA20 hizası (deploy'daki filtre)
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
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        if sleeve == "squeeze":
            xv = adx_ser[i] if np.isfinite(adx_ser[i]) else 20.0
            if xv <= 20.0: continue
        sg = s.analyze(d.iloc[max(0, i - win):i + 1], float(a))
        d_ = sg.direction
        if d_ == 0 or i <= occ: continue
        if sleeve == "donchian":   # MTF gate (deploy'da var)
            dup = bool(up_daily[i]) if not (isinstance(up_daily[i], float) and np.isnan(up_daily[i])) else True
            if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue
        e = cl[i]; sld = sl_a * a; slp = e - d_ * sld; tp = e + d_ * rr * sld; ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        out.append({"R": d_ * (ep - e) / sld - 2 * FEE * e / sld, "year": idx[i].year}); occ = j
    return out


def dollars(tr, y=None):
    r = np.array([t["R"] for t in tr if (y is None or t["year"] == y)])
    return r.sum() * BAL * RISK


def summ(tr):
    if not tr: return "yok", []
    r = np.array([t["R"] for t in tr]); gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    pf = gp / gl if gl > 0 else 9.99
    ys = sorted(set(t["year"] for t in tr))
    yv = [(y, dollars(tr, y)) for y in ys]
    every_pos = all(v > 0 for _, v in yv)
    s = f"n={len(r):>4d} WR{(r>0).mean():>3.0%} PF{pf:4.2f} ${r.sum()*BAL*RISK:+8.2f}"
    return s, yv, every_pos


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    winners = {"donchian": [], "squeeze": []}
    for c in CANDIDATES:
        try: m = fast_bt.load(c, source=source)
        except Exception as e: print(f"  {c}: yüklenemedi {e}"); continue
        print(f"\n{'='*72}\n{c}")
        best = None
        for sleeve in ("donchian", "squeeze"):
            tr = run(sleeve, m)
            s, yv, every_pos = summ(tr)
            tag = "✅HER-YIL+" if every_pos else "  karışık"
            yrs = " ".join(f"{y}:${v:+.0f}" for y, v in yv)
            print(f"  {sleeve:9s} {tag}: {s}   [{yrs}]")
            tot = dollars(tr)
            if every_pos and tot > 0:
                winners[sleeve].append((c, tot))
                if best is None or tot > best[2]: best = (sleeve, c, tot)
    print(f"\n{'='*72}\n=== ROBUST ADAYLAR (HER YIL pozitif) ===")
    for sleeve in ("donchian", "squeeze"):
        ws = sorted(winners[sleeve], key=lambda x: -x[1])
        print(f"  {sleeve}: " + (", ".join(f"{c}(${t:+.0f})" for c, t in ws) if ws else "— yok"))
    print("\n  Bir coin İKİ sleeve'de de robustsa → tek sleeve'e ata (çakışma yok, netted).")
    print("  Aday deploy öncesi: filter_test'te de doğrula + sleeve dağılımını dengele.")


if __name__ == "__main__":
    main()
