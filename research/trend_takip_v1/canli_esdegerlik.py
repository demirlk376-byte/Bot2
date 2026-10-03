"""Canlı bot trend_kolu.py ↔ araştırma motoru (engine.simulate) eşdeğerlik testi.
Her modül ayrı, tek coin, maliyetsiz, büyük sermaye; giriş/çıkış zamanı, sebep ve ek sayısı karşılaştırılır.
Kullanım: PYTHONPATH=. python3 research/trend_takip_v1/canli_esdegerlik.py /yol/trend_kolu.py"""
import sys, importlib.util, pandas as pd, numpy as np
from research.liquidity_sweep_v1 import config as C
from research.trend_takip_v1 import engine as E, run_v6 as V6
from research.trend_takip_v1.run import load, DEF_DATA, DEF_META
from research.trend_takip_v1.run_v7 import D4
spec = importlib.util.spec_from_file_location("tk", sys.argv[1]); tk = importlib.util.module_from_spec(spec); sys.modules["tk"] = tk; spec.loader.exec_module(tk)
ms = lambda s: int(pd.Timestamp(s, tz="UTC").timestamp() * 1000)
ZERO = C.CostProfile("Z", 0, 0, 0, 0, "t")
old1 = load(DEF_DATA, DEF_META); old4 = V6.load(D4, V6.OLD, "4h")[0]; reg = E.regime_ma(old1["ETH"])
W = (ms("2021-01-01"), ms("2025-08-08"))
neden = {"STOP": "STOP", "STOP_GAP": "STOP_BOŞLUK", "EXIT_SIGNAL": "ERKEN_ÇIKIŞ"}
toplam = farkli = 0
for modul, sets, vid in (("1D", old1, "N50_X5_L"), ("4H", old4, "N180_X5_L")):
    bar = C.DAY if modul == "1D" else V6.H4
    for n, s in sets.items():
        tr = E.simulate(vid, W, {n: s}, ZERO, C0=1e9, early_days=10, bar_ms=bar, regime=reg, pyr_adds=2)[0]
        ref = [(int(x["fill_time"]), int(x["exit_time"]), neden.get(x["exit_reason"], x["exit_reason"])) for x in tr
               if x["exit_reason"] != "PARTITION_END"]
        # canlı mantık: araştırmanın ısınmasıyla aynı başlangıç (ilk 200 gün sinyal yok) → o güne kadarki mumları
        # durum üretmeden "işlenmiş" say, sonra pencere boyunca işle
        bars = pd.DataFrame({"t": s.t, "open": s.o, "high": s.h, "low": s.l, "close": s.c})
        warm_t = s.t[int(np.searchsorted(s.t, s.t[0] + 200 * C.DAY))]
        bars = bars[bars.t < W[1]].reset_index(drop=True)
        d = tk.Defter()
        on = bars[bars.t < max(W[0], warm_t)]
        if len(on):
            d.son_bar[f"{n}|{modul}"] = int(on.t.iloc[-1])
        d.mum_isle(n, modul, bars, reg)
        got = [(int(k["giris_t"]), int(k["cikis_t"]), k["neden"]) for k in d.kapanan]
        ref_w = [r for r in ref if r[0] >= max(W[0], warm_t)]
        toplam += len(ref_w)
        if got != ref_w:
            farkli += 1
            a, b = set(got), set(ref_w)
            print(f"FARK {modul} {n}: canlı {len(got)} araştırma {len(ref_w)} | yalnız canlı {sorted(a-b)[:3]} | yalnız araştırma {sorted(b-a)[:3]}")
print(f"karşılaştırılan araştırma işlemi: {toplam}; farklı (modül,coin) çifti: {farkli}")
