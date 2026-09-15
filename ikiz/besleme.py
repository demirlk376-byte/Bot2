"""ReplayFeed — PaperExchange'in `rest_exchange`'i olarak takılır.

PaperExchange.fetch_ohlcv/watch_ticker bu nesneye devrediyor (exchange.py),
yani ONA HİÇ DOKUNMADAN veri kaynağını geçmişe çevirmiş oluyoruz.
Emirler, SL/TP tetikleme, bakiye — hepsi PaperExchange'in doğrulanmış kodunda kalır.

NEDENSELLİK: `saat.simdi`'den SONRA kapanan hiçbir mum servis edilmez.

⚡ HIZ: ilk sürüm her çağrıda 28.800 satırlık seriye TAM BOOLEAN MASKE uyguluyordu
   (`d[d.index + pd.Timedelta(...) <= simdi]`), üstelik her seferinde yeni bir
   indeks dizisi tahsis ederek. Olay başına 3 böyle işlem × 345 bin olay =
   milyarlarca satır karşılaştırması → 64 olay/sn.
   Artık: kapanış damgaları BİR KEZ numpy dizisine çevriliyor, konum
   `np.searchsorted` ile O(log n) bulunuyor, satırlar dilimden okunuyor.
   Bu, botun kendi işini (gösterge + strateji) değiştirmez; yalnız benim
   beslemedeki israfı kaldırır.
"""
from __future__ import annotations
from typing import Optional
import numpy as np
import pandas as pd
import fast_bt

_TF_SN = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800,
          "1h": 3600, "4h": 14400, "1d": 86400, "1D": 86400}


class _Seri:
    """Tek (sembol, zaman dilimi) için numpy'a düzleştirilmiş seri."""
    __slots__ = ("ts_ns", "kapanis_ns", "o", "h", "l", "c", "v", "n", "df")

    def __init__(self, df: pd.DataFrame, sn: int):
        self.df = df
        self.ts_ns = df.index.asi8.astype("int64")
        # pandas 3.0'da asi8 MİKROSANİYE olabilir — birimi indeksten al.
        birim = getattr(df.index, "unit", "ns")
        carp = {"s": 1_000_000_000, "ms": 1_000_000, "us": 1_000, "ns": 1}[birim]
        self.ts_ns = self.ts_ns * carp
        self.kapanis_ns = self.ts_ns + sn * 1_000_000_000
        self.o = df["open"].to_numpy(dtype="float64")
        self.h = df["high"].to_numpy(dtype="float64")
        self.l = df["low"].to_numpy(dtype="float64")
        self.c = df["close"].to_numpy(dtype="float64")
        self.v = df["volume"].to_numpy(dtype="float64")
        self.n = len(df)


class ReplayFeed:
    def __init__(self, saat, semboller, source="local"):
        self.saat = saat
        self._ham = {}
        self._seriler = {}
        for s in semboller:
            coin = s.split("/")[0]
            try:
                self._ham[s] = fast_bt.load(coin, source=source)
            except Exception as e:
                raise RuntimeError(f"ReplayFeed: {coin} verisi yüklenemedi: {e}")

    def _s(self, symbol: str, timeframe: str) -> _Seri:
        k = (symbol, timeframe)
        if k not in self._seriler:
            d = self._ham[symbol]
            if timeframe != "1h":
                d = fast_bt.resample(d, timeframe)
            self._seriler[k] = _Seri(d, _TF_SN[timeframe])
        return self._seriler[k]

    def _seri(self, symbol: str, timeframe: str) -> pd.DataFrame:
        """Eski API (sürücü olay listesi için) — DataFrame döndürür."""
        return self._s(symbol, timeframe).df

    def _simdi_ns(self) -> int:
        return int(self.saat.simdi.timestamp() * 1_000_000_000)

    def kapsam(self, symbol: str):
        d = self._ham[symbol]
        return d.index[0], d.index[-1]

    async def fetch_ohlcv(self, symbol, timeframe, since=None, limit=100):
        """ccxt biçimi: [[ts_ms, o, h, l, c, v], ...].

        Gerçek borsa SON satırda HENÜZ KAPANMAMIŞ mumu döndürür ve DataManager
        onu atar (data.py:230). Aynı davranış: kapanmışların ardına, saatin
        içinde bulunduğu oluşmakta olan mum eklenir. Gelecek asla sızmaz."""
        s = self._s(symbol, timeframe)
        now = self._simdi_ns()
        k = int(np.searchsorted(s.kapanis_ns, now, side="right"))   # kapanmış sayısı
        if k <= 0:
            return []
        i0 = max(0, k - limit)
        rows = [[int(s.ts_ns[i] // 1_000_000), s.o[i], s.h[i], s.l[i], s.c[i], s.v[i]]
                for i in range(i0, k)]
        # oluşmakta olan mum: açılışı <= şimdi, kapanışı > şimdi → tam k indeksi
        if k < s.n and s.ts_ns[k] <= now:
            rows.append([int(s.ts_ns[k] // 1_000_000), s.o[k], s.h[k], s.l[k], s.c[k], s.v[k]])
        return rows

    async def watch_ticker(self, symbol: str) -> dict:
        p = await self.get_current_price(symbol)
        return {"last": p, "close": p, "symbol": symbol}

    async def get_current_price(self, symbol: str) -> float:
        s = self._s(symbol, "1h")
        i = int(np.searchsorted(s.ts_ns, self._simdi_ns(), side="right")) - 1
        if i < 0:
            raise RuntimeError(f"ReplayFeed: {symbol} için {self.saat.simdi} öncesi veri yok")
        return float(s.c[i])

    async def close(self): pass
