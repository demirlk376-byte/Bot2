"""Kısıt kaldırılmış (ayrı alt hesap): trend 36 coin (botun 12'si + 24 diğer), coin başına tek trend pozisyonu,
bot ile hiç etkileşim yok. Giriş-anı bileşik, toplam sermayeye göre risk. 2023-04 → 2025-08-08."""
import pandas as pd, numpy as np, warnings; warnings.filterwarnings("ignore")
from research.liquidity_sweep_v1 import config as C
from research.trend_takip_v1 import engine as E, run_v5 as V5, run_v6 as V6
from research.trend_takip_v1.run import load, DEF_DATA, DEF_META
from research.trend_takip_v1.run_v7 import D4, D1N, B2
ms = lambda s: int(pd.Timestamp(s, tz="UTC").timestamp() * 1000)
old1 = load(DEF_DATA, DEF_META); reg = E.regime_ma(old1["ETH"])
sets = {"12": (old1, V6.load(D4, V6.OLD, "4h")[0]), "24": (V5.load(D1N)[0], V6.load(D4, V6.NEW, "4h")[0])}
def trend(keys):
    mods = []
    for k in keys:
        s1, s4 = sets[k]
        for N, bar, sy in ((50, C.DAY, s1), (180, V6.H4, s4)):
            mods.append(pd.DataFrame(E.simulate(f"N{N}_X5_L", (ms("2021-01-01"), B2), sy, C.TWIN_MARKET_PROFILE,
                                                early_days=10, bar_ms=bar, regime=reg, pyr_adds=2)[0]))
    tr = pd.concat(mods).sort_values("fill_time").reset_index(drop=True)
    keep, busy = [], {}
    for i, r in tr.iterrows():
        if busy.get(r.symbol, -1) > r.fill_time:
            continue
        keep.append(i); busy[r.symbol] = r.exit_time
    t = tr.loc[keep]
    return pd.DataFrame(dict(a=t.fill_time.values, z=t.exit_time.values, R=(t.net_PnL / 25.0).values, k="trend"))
bot = pd.read_csv("/home/user/fpb/ikiz_y_taban_islemler.csv")
f = lambda s: (pd.to_datetime(s).map(lambda x: x.timestamp()) * 1000).astype("int64")
bot = pd.DataFrame(dict(a=f(bot.entry_time), z=f(bot.exit_time), R=bot.R, k="bot")); A = bot.a.min()
def run(df, rb, rt):
    df = df[(df.a >= A) & (df.z < B2)].reset_index(drop=True)
    ev = sorted([(a, 1, i) for i, a in enumerate(df.a)] + [(z, 0, i) for i, z in enumerate(df.z)])
    eq, risk, path, open_risk_max = 1e4, {}, [], 0.0
    for t, typ, i in ev:
        if typ == 1:
            risk[i] = eq * (rb if df.k[i] == "bot" else rt)
            tr_open = sum(v for j, v in risk.items() if df.k[j] == "trend") / eq
            open_risk_max = max(open_risk_max, tr_open)
        else:
            eq += df.R[i] * risk.pop(i, 0.0); path.append((t, eq))
    s = pd.Series([p for _, p in path], index=pd.to_datetime([t for t, _ in path], unit="ms"))
    m = s.resample("ME").last().ffill(); prev = m.shift(1); prev.iloc[0] = 1e4; r = m / prev - 1
    return dict(aylik_geo=round(100 * ((s.iloc[-1] / 1e4) ** (1 / len(m)) - 1), 1), maxDD=round(100 * (1 - s / s.cummax()).max(), 1),
                en_kotu_ay=round(100 * r.min(), 1), x=round(s.iloc[-1] / 1e4, 1), trend_acik_risk_max=round(100 * open_risk_max, 1))
for lab, keys in (("24 diğer coin", ["24"]), ("36 coin (kısıtsız)", ["12", "24"]), ("yalnız botun 12 coini (iyimser)", ["12"])):
    t = trend(keys)
    for rt in (0.0, 0.01, 0.015):
        print(lab, f"bot %3.5 + trend %{rt*100:.1f}", run(pd.concat([bot, t]), 0.035, rt))
