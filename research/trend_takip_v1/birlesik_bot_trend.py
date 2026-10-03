import pandas as pd, numpy as np, warnings; warnings.filterwarnings("ignore")
from research.liquidity_sweep_v1 import config as C
from research.trend_takip_v1 import engine as E, run_v5 as V5, run_v6 as V6
from research.trend_takip_v1.run import load, DEF_DATA, DEF_META
from research.trend_takip_v1.run_v7 import D4, D1N, B2
A = int(pd.Timestamp("2023-04-07", tz="UTC").timestamp() * 1000)        # ikiz başlangıcı
old1 = load(DEF_DATA, DEF_META); reg = E.regime_ma(old1["ETH"])
sets = {"bot_coinleri_12": (old1, V6.load(D4, V6.OLD, "4h")[0]),
        "diger_24": (V5.load(D1N)[0], V6.load(D4, V6.NEW, "4h")[0])}
WARM_FROM = int(pd.Timestamp("2021-01-01", tz="UTC").timestamp() * 1000)
bot = pd.read_csv("/home/user/fpb/ikiz_y_taban_islemler.csv")
bot["t"] = (pd.to_datetime(bot.exit_time).map(lambda x: x.timestamp()) * 1000).astype("int64")
bot = bot[(bot.t >= A) & (bot.t < B2)][["t", "R"]].assign(k="bot")

def trend_units(s1, s4):
    trs = []
    for N, bar, sy in ((50, C.DAY, s1), (180, V6.H4, s4)):
        # 2021'den koşulur (açık pozisyon/ısınma doğal), yalnız A sonrası kapananlar alınır
        trs += E.simulate(f"N{N}_X5_L", (WARM_FROM, B2), sy, C.TWIN_MARKET_PROFILE, early_days=10,
                          bar_ms=bar, regime=reg, pyr_adds=2)[0]
    t = pd.DataFrame(trs); t = t[t.exit_time >= A]
    return pd.DataFrame(dict(t=t.exit_time.values, R=(t.net_PnL / 25.0).values, k="trend"))

def path(df, rb, rt):
    df = df.sort_values("t")
    g = np.where(df.k == "bot", df.R * rb, df.R * rt)
    eq = np.cumprod(1 + g)
    s = pd.Series(eq, index=pd.to_datetime(df.t, unit="ms"))
    m = s.resample("ME").last().ffill()
    mr = m.pct_change(); mr.iloc[0] = m.iloc[0] - 1
    months = len(m)
    geo = eq[-1] ** (1 / months) - 1
    dd = (1 - s / s.cummax()).max()
    return dict(aylik_ort=round(100 * geo, 1), medyan_ay=round(100 * mr.median(), 1), en_kotu_ay=round(100 * mr.min(), 1),
                negatif_ay=round(100 * (mr < 0).mean()), maxDD_kapanis=round(100 * dd, 1), toplam_x=round(eq[-1], 1), ay=months)

for name, (s1, s4) in sets.items():
    tr = trend_units(s1, s4)
    df = pd.concat([bot, tr])
    print("\n== trend evreni:", name, "| bot işlem", len(bot), "trend işlem", len(tr))
    for rb, rt in ((0.035, 0), (0, 0.0025), (0, 0.01), (0.035, 0.005), (0.035, 0.01), (0.035, 0.015), (0.035, 0.02),
                   (0.025, 0.01), (0.025, 0.015)):
        print(f"bot %{rb*100:.2f} + trend %{rt*100:.2f}:", path(df, rb, rt))
