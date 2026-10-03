"""İki ayrı hesap: bot hesabı (1-w) %3.5 risk (kendi bakiyesine göre) + trend alt hesabı w, risk = r_top/w (kendi bakiyesine göre).
Trend 36 coin, coin başına tek pozisyon. Giriş-anı bileşik. Dengeleme: yok / aylık. 2023-04 → 2025-08-08."""
import pandas as pd, numpy as np, warnings; warnings.filterwarnings("ignore")
import importlib.util, sys
spec = importlib.util.spec_from_file_location("k", "research/trend_takip_v1/birlesik_kisitsiz.py")
src = open(spec.origin).read().split("for lab, keys in")[0]          # yalnız tanımlar
exec(src)
T = trend(["12", "24"]); Bt = bot[(bot.a >= A) & (bot.z < B2)]; T = T[(T.a >= A) & (T.z < B2)]

def curve(df, r):
    df = df.reset_index(drop=True)
    ev = sorted([(a, 1, i) for i, a in enumerate(df.a)] + [(z, 0, i) for i, z in enumerate(df.z)])
    eq, risk, path = 1.0, {}, [(A, 1.0)]
    for t, typ, i in ev:
        if typ == 1: risk[i] = eq * r
        else: eq += df.R[i] * risk.pop(i); path.append((t, eq))
    s = pd.Series([p for _, p in path], index=pd.to_datetime([t for t, _ in path], unit="ms"))
    return s[~s.index.duplicated(keep="last")]

def stats(s):
    s = s.resample("D").last().ffill()
    m = s.resample("ME").last(); n = len(m)
    return dict(aylik_geo=round(100 * (s.iloc[-1] ** (1 / n) - 1), 1), maxDD=round(100 * (1 - s / s.cummax()).max(), 1), x=round(s.iloc[-1], 1))

b = curve(Bt, 0.035)
print("bot tek (%100 sermaye):", stats(b))
for w, rtop in ((0.2, 0.01), (0.3, 0.01), (0.3, 0.015)):
    t = curve(T, rtop / w)
    ix = b.index.union(t.index)
    bb, tt = b.reindex(ix).ffill(), t.reindex(ix).ffill()
    yok = (1 - w) * bb + w * tt
    # aylık dengeleme: her ay başı ağırlıklar w'ya
    m_b, m_t = bb.resample("ME").last(), tt.resample("ME").last()
    rb, rt = m_b.pct_change().fillna(m_b.iloc[0] - 1), m_t.pct_change().fillna(m_t.iloc[0] - 1)
    eq = np.cumprod(1 + (1 - w) * rb + w * rt)
    print(f"alt hesap %{int(w*100)}, trend riski toplamın %{rtop*100:.1f}'i (hesap içi %{100*rtop/w:.1f}):",
          "dengelemesiz", stats(yok), "| aylık dengeli aylık_geo", round(100 * (eq.iloc[-1] ** (1 / len(eq)) - 1), 1),
          "trend hesabı tek", stats(t))
