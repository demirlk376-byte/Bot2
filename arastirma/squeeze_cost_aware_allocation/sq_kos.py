"""
sq_kos.py — SQUEEZE_COST_AWARE_ALLOCATION için tek ikiz koşusu (gerçek kronolojik replay).

Production dosyaları DEĞİŞMEZ. Kancalar yalnız bu sürecin belleğinde:
  1) SQZ_SLIP_BP  : squeeze coinlerinin (XRP/DOGE/XLM — başka kol bu coinlerde işlem yapmaz)
                    PİYASA girişine özel kayma. Diğer coinler PAPER_SLIP_GIRIS_BP (15.85) ile kalır.
  2) FIX_FUNDING=1: (a) exchange._simdi_ts sanal saati kullanır (Codex bulgusu #1: fonksiyon içindeki
                    yerel `from datetime import datetime` ikizin saat yamasını atlıyor → funding
                    penceresi duvar saatinden ~0 sn → funding fiilen SIFIR);
                    (b) funding zaman damgaları doğru birimle (sn) önbelleğe alınır (bulgu #3:
                    exchange._funding_toplami `astype("int64")/1e9` yapıyor; pandas 3'te seri
                    datetime64[us] → değerler 1000 kat küçük → hiçbir oran eşleşmiyor).
                    0 = eski referans davranışı (funding yok).
Kol ağırlıkları mevcut env ile: DONCHIAN_RISK_PCT, SQUEEZE_RISK_PCT, MAX_RISK_PCT (BB), RISK_SCALE.

Kullanım:  AD=A5 REPLAY_DB=... SQZ_SLIP_BP=5.13 FIX_FUNDING=1 [DONCHIAN_RISK_PCT=..] python3 sq_kos.py
Çıktı (cwd): {AD}_islemler.csv, {AD}_tum.csv, signals_log.csv (execution'ın kendi defteri), {AD}_ozet.json
"""
import asyncio
import json
import logging
import os
import sys
import time

logging.basicConfig(level=logging.ERROR)
KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, KOK)
import fast_bt  # noqa: E402

fast_bt.CACHE_DIR = os.path.join(KOK, "data")          # salt-okunur source='local'
AD = os.environ["AD"]
SQZ_COINS = ("XRP", "DOGE", "XLM")
SQZ_SLIP = os.environ.get("SQZ_SLIP_BP")
FIX_FUNDING = os.environ.get("FIX_FUNDING", "0") == "1"
BURA = os.getcwd()


def funding_onbellek_duzelt():
    """_funding_toplami ile AYNI dosya seçimi, doğru birimle (epoch saniye)."""
    import numpy as np
    import pandas as pd
    import exchange as EX
    for coin in ("SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB", "XRP", "DOGE", "TRX", "XLM", "LTC"):
        seri = None
        for ad in (f"{coin}_funding_bnc.csv", f"{coin}_funding.csv"):
            y = os.path.join(KOK, "data", ad)
            if not os.path.exists(y):
                continue
            d = pd.read_csv(y)
            k = "dt" if "dt" in d.columns else d.columns[0]
            t = pd.to_datetime(d[k], utc=True, format="mixed")
            yeni = (np.array([x.timestamp() for x in t]), d["rate"].to_numpy(dtype="float64"))
            if seri is None or len(yeni[0]) > len(seri[0]):
                seri = yeni
        EX._FUNDING_ONBELLEK[coin] = seri


def kanca_kayma():
    import exchange as EX
    if SQZ_SLIP is None:
        return
    orj = EX.PaperExchange.place_market_order
    sq = float(SQZ_SLIP)

    async def sarmal(self, symbol, side, amount, params):
        coin = str(symbol).split("/")[0].upper()
        if coin in SQZ_COINS:
            self.SLIP_GIRIS_BP = sq                       # yalnız bu örnek/çağrı için
            try:
                return await orj(self, symbol, side, amount, params)
            finally:
                del self.SLIP_GIRIS_BP                    # sınıf değerine (15.85) geri dön
        return await orj(self, symbol, side, amount, params)
    EX.PaperExchange.place_market_order = sarmal


async def ana():
    from ikiz.kos import kur, sur
    from ikiz import db_yolu
    kanca_kayma()
    t0 = time.time()
    M, saat, feed = await kur("2023-04-06", source="local")
    if FIX_FUNDING:
        import exchange as EX
        EX._simdi_ts = lambda: saat.simdi.timestamp()
        funding_onbellek_duzelt()
    import exchange as EX
    r = M.config.risk
    ayar = dict(AD=AD, SQZ_SLIP_BP=SQZ_SLIP, FIX_FUNDING=FIX_FUNDING,
                slip_giris=EX.PaperExchange.SLIP_GIRIS_BP, slip_cikis=EX.PaperExchange.SLIP_CIKIS_BP,
                funding=EX.PaperExchange.FUNDING_ACIK, risk_scale=r.risk_scale,
                donchian_risk_pct=r.donchian_risk_pct, squeeze_risk_pct=r.squeeze_risk_pct,
                max_risk_per_trade=r.max_risk_per_trade, cap=getattr(r, "position_cap_fraction", None),
                max_positions=r.max_positions, leverage=M.config.exchange.leverage)
    print("AYAR", json.dumps(ayar, default=str), flush=True)
    n = await sur(M, saat, feed, bitis="2026-07-19", ilerleme_her=40000)
    print(f"{n} mum · {(time.time() - t0) / 60:.1f} dk", flush=True)
    import sqlite3
    import pandas as pd
    c = sqlite3.connect(f"file:{db_yolu()}?mode=ro", uri=True)
    d = pd.read_sql("SELECT symbol,side,entry_price,exit_price,sl_price,quantity,entry_time,exit_time,"
                    "pnl_usdt,exit_reason,strategy_scores,fees_usdt FROM trades WHERE exit_time IS NOT NULL", c)
    tum = pd.read_sql("SELECT * FROM trades", c)
    d.to_csv(os.path.join(BURA, f"{AD}_islemler.csv"), index=False)
    tum.to_csv(os.path.join(BURA, f"{AD}_tum.csv"), index=False)
    with open(os.path.join(BURA, f"{AD}_ozet.json"), "w") as f:
        json.dump(dict(ayar=ayar, kapanmis=len(d), tum=len(tum), dk=(time.time() - t0) / 60), f, default=str)


asyncio.run(ana())
sys.stdout.flush(); sys.stderr.flush()
os._exit(0)
