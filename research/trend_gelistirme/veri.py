"""Veri yükleme: Binance 4h + funding + MEXC metadata (research_data/h4_kirilim_v6/veri)."""
import os, hashlib
import numpy as np
from research.trend_takip_v1 import run_v6 as V6
from research.trend_gelistirme.motor import Coin

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
D4 = os.path.join(KOK, "research_data", "h4_kirilim_v6", "veri")
BOT12 = "SOL ETH ADA NEAR BCH XRP DOGE TRX XLM LTC ICP BNB".split()


def yukle(coinler, kesim=None):
    syms, ex = V6.load(D4, coinler, "4h")
    out = {}
    for n, s in syms.items():
        m = np.ones(len(s.t), bool) if kesim is None else (s.t + 4 * 3_600_000 <= kesim)
        fm = np.ones(len(s.f_t), bool) if kesim is None else (s.f_t <= kesim)
        out[n] = Coin(n, s.t[m], s.o[m], s.h[m], s.l[m], s.c[m], s.tick, s.cs, s.vu, s.mv,
                      s.f_t[fm], s.f_r[fm]).hazirla()
    return out, ex


def hashler(coinler):
    h = {}
    for c in coinler:
        for suf in ("4h", "funding"):
            p = os.path.join(D4, f"{c}_{suf}.csv")
            if os.path.exists(p):
                h[f"{c}_{suf}"] = hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]
    p = os.path.join(D4, "mexc_contract_detail.json")
    h["mexc_meta"] = hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]
    return h
