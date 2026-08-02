"""
power_rr.py — HEDEF BÜYÜKLÜĞÜ: doz-yanıt + YÖN AYRIMI (beta tuzağı testi).

NEDEN: power_exit.py'de tek yapısal sinyal hedef ekseninde çıktı —
  rr1.5 → 32/88 hücre (p=0.0138, 4/4 tf uyumu, NEGATİF yönde)
  rr2.5 → taban
  rr3.5 → 59/88 hücre (p=0.0018, 4/4 tf uyumu, POZİTİF yönde)
İki uç da aynı yönü gösteriyor: hedefler DAR. Bu, gürültünün üretmesi zor bir desen.

AMA ÜÇ ŞEKİLDE SAHTE OLABİLİR — üçünü de burada test ediyorum:

 1. BETA TUZAĞI (en tehlikelisi). Kripto 2020-2026 yukarı sürüklendi. Geniş hedef =
    long'ları daha uzun tutmak = piyasa betasına daha çok maruz kalmak. Bu bir EDGE
    DEĞİL, kaldıraçlı yön bahsi. AYIRT EDİCİ TEST: long ve short'u AYRI ölç.
    Etki iki tarafta da varsa gerçek (hedefler dar). Sadece long'da varsa BETA →
    canlıya alınırsa sadece long riskini büyütür, bu sistemin işi değil.

 2. DEJENERASYON. rr büyüdükçe TP'ye ulaşan işlem azalır; bir yerden sonra varyant
    "maxhold'da kapat" (zaman bazlı çıkış) haline gelir — hedef testi olmaktan çıkar.
    Bu oturumda iki kez dejenere varyant yakaladım. Bu yüzden her rr için
    TP% / SL% / maxhold% dağılımını basıyorum. maxhold payı %50'yi geçtiyse o nokta
    artık hedefi ölçmüyor.

 3. DOZ-YANIT YOKLUĞU. Gerçek bir etki monoton olmalı (bir yere kadar). rr'yi
    1.5→6.0 taradım. Zikzak çıkarsa iki uç noktanın uyumu tesadüftür.

KOLTUK MALİYETİ: geniş hedef daha uzun tutar → 7 koltuğu daha uzun işgal eder.
Her rr için R/bar da basılıyor; canlıda önemli olan bu.

Kullanım:  py power_rr.py local
"""
import sys
from math import comb

import numpy as np
import pandas as pd

import fast_bt
from indicators import atr as atr_fn, ema as ema_fn

COINS = ["AAVE", "ADA", "ALGO", "ATOM", "AVAX", "BCH", "BNB", "BTC", "DOGE", "DOT", "ETC",
         "ETH", "ICP", "LINK", "LTC", "NEAR", "SOL", "TRX", "VET", "XLM", "XMR", "XRP"]
TFS = ["2h", "4h", "6h", "12h"]
FEE = 0.0001
SL_A, MH = 2.0, 30
BASE_RR = 2.5
RRS = [1.5, 2.0, 2.5, 3.0, 3.5, 4.5, 6.0]
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")


def trig_donchian(d, n=40):
    hi = d["high"].rolling(n).max().shift(1).values
    lo = d["low"].rolling(n).min().shift(1).values
    c = d["close"].values
    return c > hi, c < lo


def run(d, rr):
    """occ'lu üretim, koltuk seçimi YOK.
    Dönüş: R, giriş zamanları, tutulan bar, yön (+1/-1), çıkış sebebi (0=SL 1=TP 2=maxhold)."""
    a_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    e200 = ema_fn(d["close"], 200).values
    L, S = trig_donchian(d)
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    Rs = []; ts = []; bars = []; dirs = []; why = []; occ = -1
    for i in range(260, n - 1):
        a = a_ser[i]
        if not np.isfinite(a) or a <= 0 or i <= occ or not np.isfinite(e200[i]):
            continue
        c = cl[i]; d_ = 0
        if L[i] and c > e200[i]: d_ = 1
        elif S[i] and c < e200[i]: d_ = -1
        if d_ == 0: continue
        sld = SL_A * a
        if not np.isfinite(sld) or sld <= 0: continue
        slp = c - d_ * sld; tp = c + d_ * rr * sld
        ep = None; w = 2; j = i
        for j in range(i + 1, min(i + 1 + MH, n)):
            if d_ == 1:
                if lo[j] <= slp: ep, w = slp, 0; break
                if hi[j] >= tp: ep, w = tp, 1; break
            else:
                if hi[j] >= slp: ep, w = slp, 0; break
                if lo[j] <= tp: ep, w = tp, 1; break
        if ep is None:
            j = min(i + MH, n - 1); ep = cl[j]; w = 2
        Rs.append(d_ * (ep - c) / sld - 2 * FEE * c / sld)
        ts.append(idx[i]); bars.append(j - i); dirs.append(d_); why.append(w); occ = j
    return (np.array(Rs), pd.DatetimeIndex(ts) if ts else pd.DatetimeIndex([]),
            np.array(bars, float), np.array(dirs, int), np.array(why, int))


def sign_p(w, n):
    if n == 0: return 1.0
    p = (2 * sum(comb(n, k) for k in range(w, n + 1)) / 2 ** n) if w >= n / 2 else \
        (2 * sum(comb(n, k) for k in range(0, w + 1)) / 2 ** n)
    return min(1.0, p)


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    raw = {}
    for c in COINS:
        try:
            raw[c] = fast_bt.load(c, source=source)
        except SystemExit:
            pass

    print(f"\n{'=' * 100}")
    print(f"=== HEDEF BÜYÜKLÜĞÜ: DOZ-YANIT + YÖN AYRIMI ({len(raw)} coin × {len(TFS)} tf) ===")
    print(f"  stop 2×ATR sabit, giriş donchian-40 + EMA200 sabit. SADECE hedef değişiyor.")

    cells = {rr: {} for rr in RRS}
    pool = {rr: {"R": [], "T": [], "B": [], "D": [], "W": []} for rr in RRS}
    for tf in TFS:
        for c, m in raw.items():
            d = fast_bt.resample(m, tf)
            if len(d) < 400: continue
            out = {rr: run(d, rr) for rr in RRS}
            if any(len(out[rr][0]) < 20 for rr in RRS): continue
            for rr in RRS:
                R, T, B, D, W = out[rr]
                cells[rr][(tf, c)] = float(R.mean())
                pool[rr]["R"].append(R); pool[rr]["T"].append(T)
                pool[rr]["B"].append(B); pool[rr]["D"].append(D); pool[rr]["W"].append(W)

    ncell = len(cells[BASE_RR])
    if ncell == 0:
        print("  hücre yok"); return

    P = {}
    for rr in RRS:
        Ts = pool[rr]["T"]
        P[rr] = (np.concatenate(pool[rr]["R"]),
                 Ts[0].append(Ts[1:]) if len(Ts) > 1 else Ts[0],
                 np.concatenate(pool[rr]["B"]),
                 np.concatenate(pool[rr]["D"]),
                 np.concatenate(pool[rr]["W"]))
    Rb = P[BASE_RR][0]
    print(f"\n  ÖRNEKLEM: {ncell} hücre × {len(RRS)} hedef | taban(rr{BASE_RR}) {len(Rb)} işlem")

    # ── 3. DEJENERASYON + 2. DOZ-YANIT ──
    print(f"\n  --- DOZ-YANIT (taban = rr{BASE_RR}) ---")
    hdr = (f"  {'rr':>5s} {'ort R':>9s} {'fark':>8s} {'z':>6s} {'hücre':>9s} {'p':>8s} "
           f"{'bar':>5s} {'R/bar':>9s} | {'SL%':>5s} {'TP%':>5s} {'süre%':>6s}")
    print(hdr); print("  " + "-" * (len(hdr) - 2))
    for rr in RRS:
        R, T, B, D, W = P[rr]
        se = np.sqrt(R.var(ddof=1) / len(R) + Rb.var(ddof=1) / len(Rb))
        diff = R.mean() - Rb.mean()
        z = diff / se if se > 0 and rr != BASE_RR else 0.0
        w = sum(1 for k in cells[rr] if cells[rr][k] > cells[BASE_RR][k])
        p = sign_p(w, ncell) if rr != BASE_RR else 1.0
        sl_p = 100 * (W == 0).mean(); tp_p = 100 * (W == 1).mean(); mh_p = 100 * (W == 2).mean()
        deg = "  ← DEJENERE (çoğu maxhold)" if mh_p > 50 else ""
        tag = "  ← TABAN" if rr == BASE_RR else ""
        print(f"  {rr:>5.1f} {R.mean():>+9.4f} {diff:>+8.4f} {z:>+6.2f} {w:>5d}/{ncell:<3d} "
              f"{p:>8.4f} {B.mean():>5.1f} {R.mean() / B.mean():>+9.5f} | "
              f"{sl_p:>5.1f} {tp_p:>5.1f} {mh_p:>6.1f}{tag}{deg}")

    # ── 1. BETA TUZAĞI ──
    print(f"\n  --- YÖN AYRIMI: etki beta mı, gerçek mi? ---")
    print(f"      (sadece LONG'da varsa BETA = kaldıraçlı yön bahsi, edge değil)")
    print(f"  {'rr':>5s} {'LONG ort R':>12s} {'Δ taban':>9s} {'n':>6s} | "
          f"{'SHORT ort R':>12s} {'Δ taban':>9s} {'n':>6s}")
    Db = P[BASE_RR][3]
    for rr in RRS:
        R, T, B, D, W = P[rr]
        row = f"  {rr:>5.1f}"
        for s in (1, -1):
            v = R[D == s]; b = Rb[Db == s]
            dl = v.mean() - b.mean() if len(b) else np.nan
            row += f" {v.mean():>+12.4f} {dl:>+9.4f} {len(v):>6d} |" if s == 1 else \
                   f" {v.mean():>+12.4f} {dl:>+9.4f} {len(v):>6d}"
        print(row + ("  ← TABAN" if rr == BASE_RR else ""))

    # ── DÖNEM ──
    print(f"\n  --- DÖNEM (TRAIN < 2025-01-01 ≤ TEST) ---")
    print(f"  {'rr':>5s} {'TRAIN Δ':>10s} {'TEST Δ':>10s} {'işaret':>8s}")
    Tb = P[BASE_RR][1]
    for rr in RRS:
        if rr == BASE_RR: continue
        R, T = P[rr][0], P[rr][1]
        ds = []
        for mv, mb in ((T < TRAIN_END, Tb < TRAIN_END), (T >= TRAIN_END, Tb >= TRAIN_END)):
            rv, rb = R[mv], Rb[mb]
            ds.append(rv.mean() - rb.mean() if len(rv) >= 50 and len(rb) >= 50 else np.nan)
        same = np.isfinite(ds[0]) and np.isfinite(ds[1]) and np.sign(ds[0]) == np.sign(ds[1])
        print(f"  {rr:>5.1f} {ds[0]:>+10.4f} {ds[1]:>+10.4f} {'AYNI' if same else 'FARKLI':>8s}")

    print(f"\n  OKUMA: doz-yanıt MONOTON + etki HEM long HEM short'ta + dönem işareti AYNI")
    print(f"  + dejenere değil → hedefler gerçekten dar demektir. Aksi halde tesadüf/beta.")


if __name__ == "__main__":
    main()
