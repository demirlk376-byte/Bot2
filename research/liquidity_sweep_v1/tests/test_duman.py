"""Duman testi: sentetik evrende 32 varyantın uçtan uca koşması ve defter uzlaşması."""
import numpy as np
from research.liquidity_sweep_v1 import config as C, cli
from research.liquidity_sweep_v1.tests.sentetik import sentetik_evren


def test_32_varyant_sentetik_uzlasir():
    W = cli.World(universe=sentetik_evren(n_days=90))
    for vid in C.VARIANT_IDS:
        m, res = cli.run_variant(W, vid, "DISCOVERY", C.TWIN_MARKET_PROFILE, 10_000.0)
        assert m["metrics_valid"], vid
        assert abs(m["reconciliation_gap"]) < 1e-6
