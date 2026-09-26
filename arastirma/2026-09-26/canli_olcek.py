import sys, numpy as np, pandas as pd
sys.path.insert(0, "/home/user/Bot2")
import yil_projeksiyon as Y, deployed_backtest as A
taken = Y.cipa_islemler("local")
r = np.array([R for _, R, _ in taken]); sp = np.array([s for _, _, s in taken])
ay = [pd.Timestamp(x).tz_localize(None).to_period("M") for x, _, _ in taken]
def olc(riskf, cap):
    pnl = r * np.minimum(riskf, cap * sp) * A.BAL0
    eq = np.concatenate([[A.BAL0], A.BAL0 + np.cumsum(pnl)])
    kotu = (pd.Series(pnl).groupby(ay).sum() / A.BAL0 * 100).min()
    return pnl.sum(), A.maxdd(eq), kotu
for ad, rf, cap in (("cipa", 0.0225, 1.25), ("eski canli", 0.028, 1.5), ("YENI canli", 0.035, 2.5)):
    k, dd, ka = olc(rf, cap)
    print(f"{ad:<11s} risk {rf} cap {cap}: kar ${k:+.2f}  maxDD %{dd:.2f}  en kotu ay %{ka:.2f}  olcek {k/1420.66:.4f}")
