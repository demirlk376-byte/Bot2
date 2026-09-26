"""Aylik $150 katki ham-equity dususunu maskeliyor mu? $340 + $150/ay, 24 ay."""
import numpy as np, pandas as pd
d = pd.read_pickle("islemler3.pkl").sort_values("cikis").reset_index(drop=True)
R = (d.ret / d.risk_pct).values; risk = d.risk_pct.values; mR = R.mean()
ay_id = pd.factorize(d.ay)[0]; AY = ay_id.max() + 1
ay_idx = [np.where(ay_id == a)[0] for a in range(AY)]
rng = np.random.default_rng(5); YOL = 3000; H = 24
for ad, e in (("edge %100", 1.0), ("edge %75", 0.75), ("edge %0 (olu)", 0.0), ("edge -0.10R", None)):
    Rw = R - (1 - e) * mR if e is not None else R - mR - 0.10
    ham_alarm, nav_alarm, ham_dd, nav_dd, kayip = [], [], [], [], []
    for _ in range(YOL):
        eq, nav, tepe_e, tepe_n = 340.0, 1.0, 340.0, 1.0; a_h = a_n = np.inf; mdd_h = mdd_n = 0.0
        for m, a in enumerate(rng.integers(0, AY, H)):
            for j in ay_idx[a]:
                r = Rw[j] * risk[j]
                eq *= 1 + r; nav *= 1 + r
                tepe_e = max(tepe_e, eq); tepe_n = max(tepe_n, nav)
                mdd_h = max(mdd_h, 1 - eq / tepe_e); mdd_n = max(mdd_n, 1 - nav / tepe_n)
                if a_h == np.inf and eq < 0.4 * tepe_e: a_h = m + 1
                if a_n == np.inf and nav < 0.4 * tepe_n: a_n = m + 1
            eq += 150.0                                   # ay sonu katki (NAV'i degistirmez)
        ham_alarm.append(a_h); nav_alarm.append(a_n); ham_dd.append(mdd_h); nav_dd.append(mdd_n)
        kayip.append(eq - (340 + 150 * H))
    ha, na = np.array(ham_alarm), np.array(nav_alarm)
    print(f"{ad:<14s} tepeden -%60 alarmi 24 ayda: HAM equity %{np.mean(ha<=24)*100:4.0f} (medyan ay {np.median(ha[np.isfinite(ha)]) if np.isfinite(ha).any() else float('nan'):4.0f}) | "
          f"BIRIM DEGER (NAV) %{np.mean(na<=24)*100:4.0f} (medyan ay {np.median(na[np.isfinite(na)]) if np.isfinite(na).any() else float('nan'):4.0f}) | "
          f"medyan maxDD ham %{np.median(ham_dd)*100:.0f} vs NAV %{np.median(nav_dd)*100:.0f} | 24 ay sonu yatirilana gore medyan ${np.median(kayip):+,.0f}")
