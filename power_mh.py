"""
power_mh.py — MAX-HOLD ekseni, 88 hücreli bağımsız ölçüm (22 coin × 4 tf).

NEDEN: ankor taramasında beklenmedik bir hücre çıktı — rr2.5 sabitken maxhold 30→40
toplamı +$101 artırdı, HER YIL kuralını geçti, en kötü ayı -%21 → -%17.8'e İYİLEŞTİRDİ
ve maxDD'yi neredeyse hiç bozmadı. Üstelik mh ekseni rr2.5'te monoton: 1170 → 1326 →
1421 → 1522.

AMA BU BİR IZGARA HÜCRESİ. Kendi ön-kaydım: "tek hücrenin geçmesi hiçbir şey ifade
etmez". Ve gerçekten de şüphelenmek için somut bir sebep var: monotonluk SADECE rr2.5'te
görülüyor; rr3.5/4.5/6.0'ın üçünde de mh eğrisi 30'da tepe yapıp düşüyor. Bir etkinin
yalnızca tek bir rr değerinde ortaya çıkması, tipik gürültü imzasıdır.

Bu yüzden aynı bağımsız yöntem: koltuk seçimi YOK, 22 coin, 4 zaman dilimi, işlem bazlı.
H1 ve H2'yi kapatan, rr'yi "gerçek ama taşınamaz" diye doğru teşhis eden yöntem bu.

ÜÇ SAHTELİK TESTİ (rr'dekiyle aynı):
 1. DOZ-YANIT: mh 10 → 60 monoton mu?
 2. YÖN AYRIMI: etki hem long hem short'ta mı? (sadece long ise beta)
 3. DÖNEM: TRAIN ve TEST aynı işaret mi?
Ayrıca R/bar — uzun tutuş koltuğu daha çok işgal eder, canlıda bedeli var.

Kullanım:  py power_mh.py local
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
SL_A, RR = 2.0, 2.5
BASE_MH = 30
MHS = [10, 15, 20, 25, 30, 40, 50, 60]
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")


def trig_donchian(d, n=40):
    hi = d["high"].rolling(n).max().shift(1).values
    lo = d["low"].rolling(n).min().shift(1).values
    c = d["close"].values
    return c > hi, c < lo


def run(d, mh):
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
        slp = c - d_ * sld; tp = c + d_ * RR * sld
        ep = None; w = 2; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep, w = slp, 0; break
                if hi[j] >= tp: ep, w = tp, 1; break
            else:
                if hi[j] >= slp: ep, w = slp, 0; break
                if lo[j] <= tp: ep, w = tp, 1; break
        if ep is None:
            j = min(i + mh, n - 1); ep = cl[j]; w = 2
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
    print(f"=== MAX-HOLD: DOZ-YANIT + YÖN AYRIMI ({len(raw)} coin × {len(TFS)} tf) ===")
    print(f"  giriş donchian-40 + EMA200, stop 2×ATR, hedef rr{RR} SABİT. Sadece maxhold değişiyor.")

    cells = {mh: {} for mh in MHS}
    pool = {mh: {"R": [], "T": [], "B": [], "D": [], "W": []} for mh in MHS}
    for tf in TFS:
        for c, m in raw.items():
            d = fast_bt.resample(m, tf)
            if len(d) < 400: continue
            out = {mh: run(d, mh) for mh in MHS}
            if any(len(out[mh][0]) < 20 for mh in MHS): continue
            for mh in MHS:
                R, T, B, D, W = out[mh]
                cells[mh][(tf, c)] = float(R.mean())
                for k, v in zip("RTBDW", (R, T, B, D, W)):
                    pool[mh][k].append(v)

    ncell = len(cells[BASE_MH])
    if ncell == 0:
        print("  hücre yok"); return

    P = {}
    for mh in MHS:
        Ts = pool[mh]["T"]
        P[mh] = (np.concatenate(pool[mh]["R"]),
                 Ts[0].append(Ts[1:]) if len(Ts) > 1 else Ts[0],
                 np.concatenate(pool[mh]["B"]),
                 np.concatenate(pool[mh]["D"]),
                 np.concatenate(pool[mh]["W"]))
    Rb = P[BASE_MH][0]
    print(f"\n  ÖRNEKLEM: {ncell} hücre × {len(MHS)} maxhold | taban(mh{BASE_MH}) {len(Rb)} işlem")

    print(f"\n  --- DOZ-YANIT (taban = mh{BASE_MH}) ---")
    hdr = (f"  {'mh':>4s} {'işlem':>6s} {'ort R':>9s} {'fark':>8s} {'z':>6s} {'hücre':>9s} "
           f"{'p':>8s} {'bar':>5s} {'R/bar':>9s} | {'SL%':>5s} {'TP%':>5s} {'süre%':>6s}")
    print(hdr); print("  " + "-" * (len(hdr) - 2))
    for mh in MHS:
        R, T, B, D, W = P[mh]
        se = np.sqrt(R.var(ddof=1) / len(R) + Rb.var(ddof=1) / len(Rb))
        diff = R.mean() - Rb.mean()
        z = diff / se if se > 0 and mh != BASE_MH else 0.0
        w = sum(1 for k in cells[mh] if cells[mh][k] > cells[BASE_MH][k])
        p = sign_p(w, ncell) if mh != BASE_MH else 1.0
        print(f"  {mh:>4d} {len(R):>6d} {R.mean():>+9.4f} {diff:>+8.4f} {z:>+6.2f} "
              f"{w:>5d}/{ncell:<3d} {p:>8.4f} {B.mean():>5.1f} {R.mean() / B.mean():>+9.5f} | "
              f"{100 * (W == 0).mean():>5.1f} {100 * (W == 1).mean():>5.1f} "
              f"{100 * (W == 2).mean():>6.1f}" + ("  ← TABAN/CANLI" if mh == BASE_MH else ""))

    print(f"\n  --- YÖN AYRIMI (sadece LONG'da varsa beta, edge değil) ---")
    print(f"  {'mh':>4s} {'LONG ort R':>12s} {'Δ taban':>9s} | {'SHORT ort R':>12s} {'Δ taban':>9s}")
    Db = P[BASE_MH][3]
    for mh in MHS:
        R, _T, _B, D, _W = P[mh]
        row = f"  {mh:>4d}"
        for s in (1, -1):
            v = R[D == s]; b = Rb[Db == s]
            row += f" {v.mean():>+12.4f} {v.mean() - b.mean():>+9.4f}" + (" |" if s == 1 else "")
        print(row + ("  ← TABAN" if mh == BASE_MH else ""))

    print(f"\n  --- DÖNEM (TRAIN < 2025-01-01 ≤ TEST) ---")
    print(f"  {'mh':>4s} {'TRAIN Δ':>10s} {'TEST Δ':>10s} {'işaret':>8s}")
    Tb = P[BASE_MH][1]
    for mh in MHS:
        if mh == BASE_MH: continue
        R, T = P[mh][0], P[mh][1]
        ds = []
        for mv, mb in ((T < TRAIN_END, Tb < TRAIN_END), (T >= TRAIN_END, Tb >= TRAIN_END)):
            rv, rb = R[mv], Rb[mb]
            ds.append(rv.mean() - rb.mean() if len(rv) >= 50 and len(rb) >= 50 else np.nan)
        same = np.isfinite(ds[0]) and np.isfinite(ds[1]) and np.sign(ds[0]) == np.sign(ds[1])
        print(f"  {mh:>4d} {ds[0]:>+10.4f} {ds[1]:>+10.4f} {'AYNI' if same else 'FARKLI':>8s}")

    print(f"\n  OKUMA: mh40 ankorda tek hücreydi. Burada doz-yanıt monoton + iki yönde de")
    print(f"  pozitif + dönem işareti aynı çıkarsa gerçek; aksi halde ızgara gürültüsüydü.")


if __name__ == "__main__":
    main()
