"""Hesap 309 USDT iken trend %1 riskte MEXC minimum emir kısıtı: kaç işlem açılamaz, getiri ne olur?"""
import json, pandas as pd, numpy as np, warnings; warnings.filterwarnings("ignore")
from research.liquidity_sweep_v1 import config as C
from research.liquidity_sweep_v1.indicators_adapter import atr as atr_fn
from research.trend_takip_v1 import engine as E, run_v5 as V5, run_v6 as V6
from research.trend_takip_v1.run import load, DEF_DATA, DEF_META
from research.trend_takip_v1.run_v7 import D4, D1N, B2
ms = lambda s: int(pd.Timestamp(s, tz="UTC").timestamp() * 1000)
old1 = load(DEF_DATA, DEF_META); reg = E.regime_ma(old1["ETH"])
sets = {"bot12": (old1, V6.load(D4, V6.OLD, "4h")[0]), "diger24": (V5.load(D1N)[0], V6.load(D4, V6.NEW, "4h")[0])}
# 1) bugünkü minimum emir tutarı vs %1 riskli tipik trend notional'ı (309 USDT)
eq = 309.0
rows = []
for k, (s1, s4) in sets.items():
    for n, s in s1.items():
        px = s.c[-1]; mn = s.cs * s.mv * px
        a1 = atr_fn(s.h, s.l, s.c, 20)[-1] / px
        s4n = s4[n]; a4 = atr_fn(s4n.h, s4n.l, s4n.c, 20)[-1] / s4n.c[-1]
        rows.append(dict(kume=k, coin=n, min_emir_usdt=round(mn, 2), notional_1D=round(0.01 * eq / (5 * a1), 1),
                         notional_4H=round(0.01 * eq / (5 * a4), 1)))
t = pd.DataFrame(rows)
t["1D_acilir"] = t.notional_1D >= t.min_emir_usdt; t["4H_acilir"] = t.notional_4H >= t.min_emir_usdt
print(t.to_string(index=False))
print("açılabilir oranı 1D:", round(t["1D_acilir"].mean(), 2), "4H:", round(t["4H_acilir"].mean(), 2))
# 2) motorla: C0=309, risk %1 vs C0=10000 risk %1 (aynı oran) — blok sayıları ve getiri
C.PER_TRADE_RISK_FRAC = 0.01
for k, (s1, s4) in sets.items():
    for c0 in (10000.0, 309.0):
        tot, nb, nt = 0.0, 0, 0
        for N, bar, sy in ((50, C.DAY, s1), (180, V6.H4, s4)):
            tr, bl, eqc, led, op = E.simulate(f"N{N}_X5_L", (ms("2021-01-01"), B2), sy, C.TWIN_MARKET_PROFILE, C0=c0,
                                              early_days=10, bar_ms=bar, regime=reg, pyr_adds=2)
            tot += sum(x["net_PnL"] for x in tr) / c0 * 100; nt += len(tr)
            nb += sum(1 for b in bl if b["reason"] in ("MIN_ORDER_BLOCKED", "PYR_BLOCKED"))
        print(f"{k} C0={c0:.0f}: işlem {nt}, min-emir/piramit engeli {nb}, toplam getiri %{tot:.1f}")
