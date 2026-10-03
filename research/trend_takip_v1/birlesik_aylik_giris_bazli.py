"""Doğru bileşik: risk tutarı işlemin AÇILDIĞI andaki (gerçekleşmiş) bakiyeden; PnL kapanışta gerçekleşir."""
import pandas as pd, numpy as np, warnings; warnings.filterwarnings("ignore")
from research.liquidity_sweep_v1 import config as C
from research.trend_takip_v1 import engine as E, run_v6 as V6
from research.trend_takip_v1.run import load, DEF_DATA, DEF_META
from research.trend_takip_v1.run_v7 import D4
ms = lambda s: int(pd.Timestamp(s, tz="UTC").timestamp() * 1000)
old1 = load(DEF_DATA, DEF_META); old4 = V6.load(D4, V6.OLD, "4h")[0]; reg = E.regime_ma(old1["ETH"])
trs = []
for N, bar, sy in ((50, C.DAY, old1), (180, V6.H4, old4)):
    trs += E.simulate(f"N{N}_X5_L", (ms("2021-01-01"), ms("2026-10-01")), sy, C.TWIN_MARKET_PROFILE,
                      early_days=10, bar_ms=bar, regime=reg, pyr_adds=2)[0]
tr = pd.DataFrame(trs)
tr = pd.DataFrame(dict(a=tr.fill_time, z=tr.exit_time, R=tr.net_PnL / 25.0, k="trend"))
bot = pd.read_csv("/home/user/fpb/ikiz_y_taban_islemler.csv")
f = lambda s: (pd.to_datetime(s).map(lambda x: x.timestamp()) * 1000).astype("int64")
bot = pd.DataFrame(dict(a=f(bot.entry_time), z=f(bot.exit_time), R=bot.R, k="bot"))
END = bot.z.max()                       # ikiz verisi sonu (2026-07-18)
df = pd.concat([bot, tr]); df = df[(df.a >= bot.a.min()) & (df.z <= END)].reset_index(drop=True)

def run(rb, rt, eq0=10000.0):
    ev = sorted([(r.a, 1, i) for i, r in df.iterrows()] + [(r.z, 0, i) for i, r in df.iterrows()])  # aynı anda önce kapanış
    eq, risk, path = eq0, {}, []
    for t, typ, i in ev:
        r = df.loc[i]; rr = rb if r.k == "bot" else rt
        if typ == 1:
            risk[i] = eq * rr
        else:
            eq += r.R * risk.pop(i, 0.0)
            path.append((t, eq))
    s = pd.Series([p for _, p in path], index=pd.to_datetime([t for t, _ in path], unit="ms"))
    return s

for nm, rb, rt in (("bot", 0.035, 0), ("birlikte", 0.035, 0.01)):
    s = run(rb, rt)
    m = s.resample("ME").last().ffill()
    prev = m.shift(1); prev.iloc[0] = 10000.0
    ret = (m / prev - 1) * 100
    print(nm, "toplam x", round(s.iloc[-1] / 10000, 1), "aylık geo %", round(100 * ((s.iloc[-1] / 10000) ** (1 / len(m)) - 1), 1),
          "maxDD %", round(100 * (1 - s / s.cummax()).max(), 1))
    if nm == "birlikte":
        out = pd.DataFrame({"getiri": ret.round(1), "bakiye": m.round(-1)})
        out.index = out.index.strftime("%Y-%m")
        print(out.to_string())
        y = m.groupby(m.index.year).last(); yp = y.shift(1).fillna(10000)
        print("yıllık %", ((y / yp - 1) * 100).round(0).to_dict())
    else:
        y = m.groupby(m.index.year).last(); yp = y.shift(1).fillna(10000); print("bot yıllık %", ((y / yp - 1) * 100).round(0).to_dict())
