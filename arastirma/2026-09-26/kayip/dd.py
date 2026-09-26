import numpy as np, pandas as pd
d = pd.read_pickle("islemler2.pkl")
btc = pd.read_csv("/home/user/Bot2/data/BTC_fut_1h.csv")
tcol = [c for c in btc.columns if c.lower() in ("timestamp", "time", "date", "open_time", "ts")][0]
btc["t"] = pd.to_datetime(btc[tcol], utc=True) if not pd.api.types.is_numeric_dtype(btc[tcol]) else pd.to_datetime(btc[tcol], utc=True, unit="ms")
btc = btc.set_index("t")["close"]
def btc_ret(a, b):
    try: return btc.asof(b) / btc.asof(a) - 1
    except Exception: return np.nan
# --- gerceklesen ozsermaye egrisi ve DD epizotlari (log ile, bilesik)
eq = np.concatenate([[10000.0], d.eq_sonra.values]); t = np.concatenate([[d.cikis.iloc[0] - pd.Timedelta("1h")], d.cikis.values])
peak = np.maximum.accumulate(eq); dd = 1 - eq / peak
epi = []; i = 0; n = len(eq)
while i < n:
    if dd[i] > 0:
        j = i
        while j < n and dd[j] > 0: j += 1
        seg = slice(i, j); k = i + int(np.argmax(dd[seg]))
        pk = i - 1
        epi.append((dd[k], pk, k, j if j < n else None)); i = j
    else: i += 1
epi.sort(reverse=True)
print("=== EN BUYUK 6 DUSUS (gerceklesen, bilesik) ===")
for derin, pk, dip, bitis in epi[:6]:
    tr = d.iloc[pk:dip]            # tepe->dip arasinda kapanan islemler
    sure = (pd.Timestamp(t[dip]) - pd.Timestamp(t[pk])).days
    geri = (pd.Timestamp(t[bitis]) - pd.Timestamp(t[dip])).days if bitis else None
    sl = tr[tr.exit_reason == "sl_hit"]
    print(f"\n-%{derin*100:.1f}  {pd.Timestamp(t[pk]).date()} -> {pd.Timestamp(t[dip]).date()}  ({sure} gun, toparlanma {geri} gun)  "
          f"islem {len(tr)}  WR %{(tr.R>0).mean()*100:.0f}  SL {len(sl)}  TP {(tr.exit_reason=='tp_hit').sum()}  BTC %{btc_ret(t[pk], t[dip])*100:+.1f}")
    print("   kol katkisi (ret%):", tr.groupby("kol").ret.sum().mul(100).round(1).to_dict(),
          "| yon:", tr.groupby("side").ret.sum().mul(100).round(1).to_dict())
    # ardisik SL serisi
    s = (tr.R < 0).astype(int).values; best = cur = 0
    for v in s: cur = cur + 1 if v else 0; best = max(best, cur)
    print(f"   en uzun ardisik kayip {best}  | long/short SL: {sl.side.value_counts().to_dict()}")
# --- kayip serileri (tum donem)
s = (d.R < 0).astype(int).values; seri = []; cur = 0
for v in s:
    if v: cur += 1
    else:
        if cur: seri.append(cur)
        cur = 0
seri = np.array(seri)
print(f"\n=== KAYIP SERILERI: en uzun {seri.max()}, >=6: {(seri>=6).sum()} kez, >=8: {(seri>=8).sum()} kez ===")
# bagimsizlik varsayimiyla beklenen en uzun seri (WR sabit) -- karistirma testi
rng = np.random.default_rng(1); sim = []
for _ in range(2000):
    x = rng.permutation(s); b = c = 0
    for v in x: c = c + 1 if v else 0; b = max(b, c)
    sim.append(b)
print(f"   karistirilmis (bagimsiz) en uzun seri medyan {np.median(sim):.0f}, %95 {np.percentile(sim,95):.0f}")
# --- aylar
print("\n=== EN KOTU 8 AY (bilesik ay getirisi) ===")
ay = d.groupby("ay").agg(n=("R", "size"), WR=("R", lambda x: (x > 0).mean()*100), ortR=("R", "mean"),
                         getiri=("ret", lambda x: np.prod(1 + x) - 1))
for p in ay.index:
    a, b = p.start_time.tz_localize("UTC"), p.end_time.tz_localize("UTC")
    ay.loc[p, "btc%"] = btc_ret(a, b) * 100
ay["getiri%"] = ay.getiri * 100
print(ay.sort_values("getiri").head(8)[["n", "WR", "ortR", "getiri%", "btc%"]].round(1).to_string())
print(f"\n  negatif ay: {(ay.getiri<0).sum()}/{len(ay)}  | aylik islem sayisi ile getiri korelasyonu {ay.n.corr(ay.getiri):+.2f}"
      f" | |BTC| ile {ay['btc%'].abs().corr(ay.getiri):+.2f} | BTC ile {ay['btc%'].corr(ay.getiri):+.2f}")
# kotu aylarin WR'i: TP azligi mi SL cokluga mi?
kotu = ay[ay.getiri < 0]; iyi = ay[ay.getiri >= 0]
print(f"  kotu aylar: ort WR %{kotu.WR.mean():.0f}, ort n {kotu.n.mean():.1f} | iyi aylar: WR %{iyi.WR.mean():.0f}, n {iyi.n.mean():.1f}")
ay.to_pickle("aylar.pkl")
