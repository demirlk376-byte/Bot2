"""ReplayFeed — PaperExchange'in `rest_exchange`'i olarak takılır.

PaperExchange.fetch_ohlcv/watch_ticker bu nesneye devrediyor (exchange.py),
yani ONA HİÇ DOKUNMADAN veri kaynağını geçmişe çevirmiş oluyoruz.
Emirler, SL/TP tetikleme, bakiye — hepsi PaperExchange'in doğrulanmış kodunda kalır.

NEDENSELLİK: `saat.simdi`'den SONRA kapanan hiçbir mum servis edilmez. Bu sınıf
geleceği veremez; `fetch_ohlcv` daima kesim uygular.
"""
from __future__ import annotations
from typing import Optional
import pandas as pd
import fast_bt

_TF_SN = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800,
          "1h": 3600, "4h": 14400, "1d": 86400, "1D": 86400}


class ReplayFeed:
    def __init__(self, saat, semboller, source="local"):
        """semboller: canlı sembol adları ('SOL/USDT:USDT' gibi) → coin ('SOL')."""
        self.saat = saat
        self._ham = {}
        self._cache = {}
        for s in semboller:
            coin = s.split("/")[0]
            try:
                self._ham[s] = fast_bt.load(coin, source=source)
            except Exception as e:
                raise RuntimeError(f"ReplayFeed: {coin} verisi yüklenemedi: {e}")

    def _seri(self, symbol: str, timeframe: str) -> pd.DataFrame:
        k = (symbol, timeframe)
        if k not in self._cache:
            d = self._ham[symbol]
            self._cache[k] = d if timeframe == "1h" else fast_bt.resample(d, timeframe)
        return self._cache[k]

    def kapsam(self, symbol: str):
        d = self._ham[symbol]
        return d.index[0], d.index[-1]

    async def fetch_ohlcv(self, symbol, timeframe, since=None, limit=100):
        """ccxt biçimi: [[ts_ms, o, h, l, c, v], ...].

        ⚠ Gerçek borsa SON satırda HENÜZ KAPANMAMIŞ mumu döndürür ve DataManager
        onu atar (data.py:230 notu). Aynı davranışı taklit ediyoruz: saatin içinde
        bulunduğu OLUŞMAKTA olan mum da eklenir — ama YALNIZ saate kadarki
        bilgisiyle (o ana kadarki high/low/close). Gelecek asla sızmaz."""
        d = self._seri(symbol, timeframe)
        sn = _TF_SN[timeframe]
        simdi = self.saat.simdi
        kapanmis = d[d.index + pd.Timedelta(seconds=sn) <= simdi]
        if len(kapanmis) == 0:
            return []
        out = kapanmis.tail(limit)
        rows = [[int(t.timestamp() * 1000), float(r.open), float(r.high),
                 float(r.low), float(r.close), float(r.volume)]
                for t, r in zip(out.index, out.itertuples())]
        # oluşmakta olan mum (borsa davranışı) — DataManager bunu atar
        olusan = d[(d.index <= simdi) & (d.index + pd.Timedelta(seconds=sn) > simdi)]
        if len(olusan):
            t = olusan.index[-1]; r = olusan.iloc[-1]
            rows.append([int(t.timestamp() * 1000), float(r.open), float(r.high),
                         float(r.low), float(r.close), float(r.volume)])
        return rows

    async def watch_ticker(self, symbol: str) -> dict:
        p = await self.get_current_price(symbol)
        return {"last": p, "close": p, "symbol": symbol}

    async def get_current_price(self, symbol: str) -> float:
        d = self._seri(symbol, "1h")
        m = d[d.index <= self.saat.simdi]
        if len(m) == 0:
            raise RuntimeError(f"ReplayFeed: {symbol} için {self.saat.simdi} öncesi veri yok")
        return float(m["close"].iloc[-1])

    async def close(self): pass
