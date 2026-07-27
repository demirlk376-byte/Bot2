"""
mfe_anatomy.py — SL'ler NEDEN SL oldu? MFE/MAE + çıkış-sebebi ekonomisi (1421 işlemin tamamı).

ŞİMDİYE KADAR sorduğumuz: "girişte SL'i öngörebilir miyiz?" → HAYIR (OOS AUC 0.509, kanıtlı).
HİÇ SORMADIĞIMIZ: "SL olan işlem, stop'a gitmeden ÖNCE ne kadar lehimize gitti?"

Bu, SL'leri mekanik olarak ayırır (MFE = maximum favorable excursion, R cinsinden):
  MFE < 0.25R  → TEMİZ KAYIP: hiç lehimize gitmedi, giriş baştan yanlış → ÇARE YOK
  0.25-1.0R    → erken dönüş
  1.0-2.0R     → WHIPSAW: ciddi ilerledi sonra tam geri döndü → adreslenebilir mi?
  > 2.0R       → KIL PAYI: TP'ye (2.5R) değmeden döndü → TP fazla uzak olabilir
Oranlar her şeyi belirler. Çoğu temiz kayıpsa → SL'ler tasarım gereği, kapanır.

AYRICA çıkış-sebebi ekonomisi: SL / TP / MAX-HOLD her biri kaç işlem, ort R, toplam $ katkısı.
max-hold ~%26 (donchian) — kâr mı zarar mı getiriyor, hiç ölçülmedi.
+ MAE (maximum adverse excursion) KAZANANLARDA: kazananlar ne kadar dibe gitti (stop'a ne kadar
yaklaştı)? Stop biraz dar mı — yani kazanacak işlemleri erken kesiyor muyuz?

Bar-bar yol takibi (intrabar high/low), muhafazakâr sıra (aynı barda önce stop).
Kullanım:  py mfe_anatomy.py local
"""
import sys
import numpy as np
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAL0 = 190.0; FEE = 0.0001; RISKF = 0.0225; CAP = 1.0
DONCH = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB"]
SQZ = ["XRP", "DOGE", "TRX", "XLM"]
CFG = {"donchian": ("4h", 259, 2.0, 2.5, 30), "squeeze": ("1h", 119, 2.0, 2.5, 48)}


def gen(sleeve, m):
    tf, win, sl_a, rr, mh = CFG[sleeve]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
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
        sg = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)); d_ = sg.direction
        if d_ == 0 or i <= occ: continue
        e = cl[i]; sld = sl_a * a; slp = e - d_ * sld; tp = e + d_ * rr * sld
        ep = None; j = i; reason = "hold"; mfe = 0.0; mae = 0.0
        for j in range(i + 1, min(i + 1 + mh, n)):
            # yol boyunca MFE/MAE (R cinsinden) — çıkıştan ÖNCEKİ tüm barlar
            fav = d_ * (hi[j] - e) / sld if d_ == 1 else d_ * (lo[j] - e) / sld
            adv = d_ * (lo[j] - e) / sld if d_ == 1 else d_ * (hi[j] - e) / sld
            mfe = max(mfe, fav); mae = min(mae, adv)
            if d_ == 1:
                if lo[j] <= slp: ep = slp; reason = "sl"; break
                if hi[j] >= tp: ep = tp; reason = "tp"; break
            else:
                if hi[j] >= slp: ep = slp; reason = "sl"; break
                if lo[j] <= tp: ep = tp; reason = "tp"; break
        if ep is None:
            j = min(i + mh, n - 1); ep = cl[j]; reason = "maxhold"
        R = d_ * (ep - e) / sld - 2 * FEE * e / sld
        out.append({"R": R, "reason": reason, "mfe": mfe, "mae": mae, "bars": j - i,
                    "sl_pct": sld / e, "sleeve": sleeve, "year": idx[i].year}); occ = j
    return out


def dollars(ts):
    r = np.array([t["R"] for t in ts]); eff = np.minimum(RISKF, CAP * np.array([t["sl_pct"] for t in ts]))
    return (r * eff * BAL0).sum()


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    trs = []
    for c in DONCH: trs += gen("donchian", fast_bt.load(c, source=source))
    for c in SQZ: trs += gen("squeeze", fast_bt.load(c, source=source))
    print(f"\n{'='*88}\n=== ÇIKIŞ-SEBEBİ EKONOMİSİ ({len(trs)} işlem, coin-bazlı, canlı boyut) ===")
    print(f"  {'sebep':9s} {'n':>5s} {'pay':>5s} {'ort R':>7s} {'toplam$':>9s} {'ort bar':>8s}")
    for rs in ("tp", "sl", "maxhold"):
        g = [t for t in trs if t["reason"] == rs]
        if not g: continue
        print(f"  {rs:9s} {len(g):>5d} {len(g)/len(trs)*100:>4.0f}% "
              f"{np.mean([t['R'] for t in g]):>7.2f} {dollars(g):>+9.0f} {np.mean([t['bars'] for t in g]):>8.1f}")

    sl = [t for t in trs if t["reason"] == "sl"]
    print(f"\n{'='*88}\n=== SL'LER NEDEN SL OLDU? — stop'a gitmeden ÖNCE ne kadar lehimize gitti (MFE) ===")
    print(f"  {len(sl)} SL işlemi:")
    buckets = [("TEMİZ KAYIP (<0.25R)", 0.0, 0.25), ("erken dönüş (0.25-1R)", 0.25, 1.0),
               ("WHIPSAW (1-2R)", 1.0, 2.0), ("KIL PAYI (>2R)", 2.0, 99.0)]
    for name, lo_, hi_ in buckets:
        g = [t for t in sl if lo_ <= t["mfe"] < hi_]
        print(f"    {name:24s} n={len(g):>4d} ({len(g)/len(sl)*100:>4.1f}%)  "
              f"ort MFE {np.mean([t['mfe'] for t in g]) if g else 0:>4.2f}R  "
              f"kayıp ${dollars(g):>+7.0f}")
    print(f"    → SL'lerin ort MFE'si: {np.mean([t['mfe'] for t in sl]):.2f}R "
          f"(medyan {np.median([t['mfe'] for t in sl]):.2f}R)")

    mh = [t for t in trs if t["reason"] == "maxhold"]
    if mh:
        print(f"\n=== MAX-HOLD ÇIKIŞLARI ({len(mh)}) — süre dolunca ne oluyor ===")
        print(f"    ort R {np.mean([t['R'] for t in mh]):+.2f} | toplam ${dollars(mh):+.0f} | "
              f"ort MFE {np.mean([t['mfe'] for t in mh]):.2f}R | kârla kapanan %{np.mean([t['R']>0 for t in mh])*100:.0f}")
        near = [t for t in mh if t["mfe"] >= 2.0]
        print(f"    2R+ görüp TP'ye değmeden süresi dolan: {len(near)} ({len(near)/len(mh)*100:.0f}%)")

    tp = [t for t in trs if t["reason"] == "tp"]
    print(f"\n=== KAZANANLARIN MAE'si — stop'a ne kadar yaklaştılar (stop dar mı?) ===")
    for name, lo_, hi_ in [("hiç zorlanmadı (>-0.25R)", -0.25, 0.01), ("-0.25..-0.5R", -0.5, -0.25),
                           ("-0.5..-0.75R", -0.75, -0.5), ("stop'a ÇOK yakın (<-0.75R)", -1.0, -0.75)]:
        g = [t for t in tp if lo_ <= t["mae"] < hi_]
        print(f"    {name:26s} n={len(g):>4d} ({len(g)/len(tp)*100:>4.1f}%)")
    print(f"    → TP'ye ulaşanların ort MAE'si: {np.mean([t['mae'] for t in tp]):.2f}R")
    print(f"\n  YORUM: TEMİZ KAYIP payı yüksekse → SL'ler tasarım gereği, çare yok.")
    print(f"         KIL PAYI + max-hold'da 2R+ görenler yüksekse → TP fazla uzak olabilir (rr testi tekrar).")
    print(f"         Kazananların MAE'si -0.75R'ye yığılıysa → stop dar, kazananları kesiyoruz.")


if __name__ == "__main__":
    main()
