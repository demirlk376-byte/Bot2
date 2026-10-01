"""Sentetik rastgele-yürüyüş evreni (testler ve G6 yanlılık kapısı için)."""
import numpy as np
from research.liquidity_sweep_v1 import config as C, data_contract as D
def sentetik_evren(n_days=120, syms=("AAA","BBB","CCC"), seed=1):
    rng = np.random.default_rng(seed)
    g0 = 1_672_531_200_000  # 2023-01-01
    n5 = n_days * C.GRID_PER_DAY
    out = {}
    for i, s in enumerate(syms):
        r = rng.standard_t(4, n5) * 0.0015
        c = 100 * np.exp(np.cumsum(r))
        o = np.r_[100, c[:-1]]
        h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.0008, n5)))
        l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.0008, n5)))
        o, h, l, c = [np.round(x, 2) for x in (o, h, l, c)]
        h = np.maximum.reduce([h, o, c]); l = np.minimum.reduce([l, o, c])
        ft = np.arange(g0, g0 + n_days * C.DAY, 8 * C.H1)
        out[s] = D.SymbolData(symbol=s, source="SENTETIK", g0=g0, o=o, h=h, l=l, c=c, v=np.ones(n5),
                              valid5=np.ones(n5, bool), tick=0.01, contract_size=1.0, vol_unit=0.1, min_vol=0.1,
                              meta_source="test", funding_t=ft, funding_rate=np.full(len(ft), 0.0001),
                              funding_on_grid=np.ones(len(ft), bool), funding_source="TEST")
    return dict(symbols=out, excluded={}, quality={}, source="SENTETIK", source_report={}, g0=g0,
                g1=g0 + n_days * C.DAY, raw_hashes={}, download_summary_created=None)
