"""
trend_kolu.py — YAVAŞ TREND KOLU (araştırma: research/trend_takip_v1, TREND_KOLU_TASARIM.md).

KURALLAR (araştırmadaki dondurulmuş paketle birebir):
  • İki modül, yalnız LONG:
      1D: günlük kapanış > önceki 50 günün en yüksek tepesi → giriş
      4H: 4h kapanış  > önceki 180 mumun en yüksek tepesi → giriş
  • İlk stop = sinyal kapanışı − 5×ATR20 (modülün kendi mumu). İz süren stop = girişten beri en iyi
    kapanış − 5×ATR20, yalnız yukarı taşınır. Mum içinde dokunursa stop fiyatından, açılış stopun
    altındaysa açılıştan çıkılır.
  • Erken çıkış: girişten 10 GÜN sonra en iyi kapanış giriş + 1R'ye hiç ulaşmadıysa sonraki açılışta çık.
  • Piramit: kapanış ilk girişten +2R ve +4R'ye ulaşınca sonraki açılışta ek (en fazla 2), her ek
    güncel ortak stopa göre aynı risk oranıyla.
  • Yeni giriş yalnız ETH günlük kapanışı > ETH SMA200 iken (son tamamlanmış UTC günü).
  • Coin başına tek trend pozisyonu (iki modül arasında ilk gelen).
  • Sinyal mumun KAPANIŞINDA bilinir; işlem bir sonraki mumun AÇILIŞINDA olur.

Bu dosya SAF MANTIKTIR: borsaya emir göndermez. `Defter.mum_isle()` her yeni mumda
araştırma motorunun (engine.simulate) aynı sırasını izler:
  açılış → bekleyen çıkış/ek/giriş → mum içi stop → kapanış güncellemeleri ve yeni sinyal.
Canlı bota bağlantısı `trend_canli.py` içindedir (TREND_MODE=kapali|sinyal; varsayılan KAPALI).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np
import pandas as pd

DAY_MS = 86_400_000
H4_MS = 4 * 3_600_000

MODULLER = {
    # ad: (mum ms, N, ATR k)
    "1D": (DAY_MS, 50, 5.0),
    "4H": (H4_MS, 180, 5.0),
}
ATR_N = 20
ERKEN_GUN = 10
PIRAMIT_ADIM_R = 2.0
PIRAMIT_MAKS = 2
ETH_SMA = 200


def atr_wilder(high, low, close, n: int = ATR_N) -> np.ndarray:
    """Araştırmadaki ATR'nin birebir aynısı (research/liquidity_sweep_v1/indicators_adapter.atr):
    ilk değer ilk TR, sonra tr*k + önceki*(1-k), k=1/n."""
    h, l, c = (np.asarray(x, float) for x in (high, low, close))
    out = np.full(len(c), np.nan)
    prev_atr, prev_c, k = None, None, 1.0 / n
    for i in range(len(c)):
        if not (np.isfinite(h[i]) and np.isfinite(l[i]) and np.isfinite(c[i])):
            continue
        tr = h[i] - l[i] if prev_c is None else max(h[i] - l[i], abs(h[i] - prev_c), abs(l[i] - prev_c))
        prev_atr = tr if prev_atr is None else tr * k + prev_atr * (1 - k)
        out[i] = prev_atr
        prev_c = c[i]
    return out


def gunluk_4h_den(df4: pd.DataFrame) -> pd.DataFrame:
    """4h mumlardan TAMAMLANMIŞ UTC günlük mumlar (gün başına tam 6 mum). İndeks/`t`: gün açılışı (ms)."""
    if df4 is None or not len(df4):
        return pd.DataFrame(columns=["t", "open", "high", "low", "close"])
    t = df4["t"].to_numpy("int64")
    gun = (t // DAY_MS) * DAY_MS
    d = df4.assign(gun=gun).groupby("gun").agg(open=("open", "first"), high=("high", "max"),
                                               low=("low", "min"), close=("close", "last"), n=("t", "size"))
    d = d[d.n == 6].drop(columns="n")
    d.index.name = "t"
    return d.reset_index()


def eth_rejim(eth_gunluk: pd.DataFrame) -> dict:
    """{gün_açılışı_ms: ETH kapanışı > SMA200}; SMA hesaplanamayan günler yok (serbest sayılır)."""
    if eth_gunluk is None or not len(eth_gunluk):
        return {}
    c = eth_gunluk["close"].to_numpy(float)
    m = pd.Series(c).rolling(ETH_SMA).mean().to_numpy()
    return {int(t): bool(x > y) for t, x, y in zip(eth_gunluk["t"], c, m) if np.isfinite(y)}


@dataclass
class Pozisyon:
    sembol: str
    modul: str
    giris_t: int            # ilk dolumun mum açılış zamanı (ms)
    sinyal_t: int
    E0: float               # ilk dolum fiyatı
    D0: float               # ilk risk mesafesi (E0 − S0)
    S0: float
    stop: float
    best: float             # girişten beri en iyi kapanış (sinyal kapanışından başlar)
    mfe: float = 0.0        # en iyi kapanış − E0 (yalnız giriş mumundan itibaren)
    ekler: int = 0
    lotlar: list = field(default_factory=list)   # [{"t":..,"E":..,"risk_birim":..}] ilk giriş dahil
    erken_bayrak: bool = False


@dataclass
class Olay:
    tur: str                # GIRIS_SINYALI | GIRIS | EK_SINYALI | EK | STOP | CIKIS_SINYALI | CIKIS
    sembol: str
    modul: str
    t: int                  # olayın mum zamanı (ms)
    fiyat: float = 0.0
    stop: float = 0.0
    neden: str = ""
    R: float = 0.0          # CIKIS: pozisyonun toplam sonucu, ilk risk birimi cinsinden (maliyetsiz)

    def metin(self) -> str:
        z = pd.to_datetime(self.t, unit="ms", utc=True).strftime("%Y-%m-%d %H:%M")
        if self.tur == "GIRIS_SINYALI":
            return f"📈 TREND {self.modul} {self.sembol}: kırılım ({z} UTC kapanış {self.fiyat:g}), stop {self.stop:g}"
        if self.tur == "GIRIS":
            return f"✅ TREND {self.modul} {self.sembol}: (sanal) giriş {self.fiyat:g}, stop {self.stop:g}"
        if self.tur == "EK":
            return f"➕ TREND {self.modul} {self.sembol}: (sanal) piramit eki {self.fiyat:g}, ortak stop {self.stop:g}"
        if self.tur == "CIKIS":
            return (f"🏁 TREND {self.modul} {self.sembol}: (sanal) çıkış {self.fiyat:g} — {self.neden}, "
                    f"sonuç {self.R:+.2f}R")
        return f"TREND {self.tur} {self.modul} {self.sembol} {self.fiyat:g} {self.neden}"


class Defter:
    """Sanal trend defteri: coin başına tek pozisyon, iki modül. Durum JSON'a yazılabilir."""

    def __init__(self):
        self.poz: dict[str, Pozisyon] = {}
        self.bekleyen: dict[str, dict] = {}      # sembol → {"tur": giris|cikis|ek, ...}
        self.son_bar: dict[str, int] = {}        # "SEMBOL|MODUL" → son işlenen mum açılışı
        self.kapanan: list[dict] = []            # tamamlanan sanal işlemler (rapor)
        self.meta: dict = {}                     # bağlantı katmanının notları (ör. yalnız sanal izlenenler)

    # ── kalıcılık ────────────────────────────────────────────────────────────
    def durum(self) -> dict:
        return {"poz": {k: asdict(v) for k, v in self.poz.items()}, "bekleyen": self.bekleyen,
                "son_bar": self.son_bar, "kapanan": self.kapanan[-500:], "meta": self.meta}

    @classmethod
    def yukle(cls, d: dict) -> "Defter":
        x = cls()
        x.poz = {k: Pozisyon(**v) for k, v in (d.get("poz") or {}).items()}
        x.bekleyen = d.get("bekleyen") or {}
        x.son_bar = {k: int(v) for k, v in (d.get("son_bar") or {}).items()}
        x.kapanan = d.get("kapanan") or []
        x.meta = d.get("meta") or {}
        return x

    # ── çekirdek ─────────────────────────────────────────────────────────────
    def _kapat(self, s: str, fiyat: float, t: int, neden: str, olaylar: list) -> None:
        p = self.poz.pop(s)
        # her lot aynı risk tutarıyla açılır: lot sonucu = (çıkış − E_lot)/D_lot risk birimi
        toplam_R = sum((fiyat - l["E"]) / l["D"] * l["risk_birim"] for l in p.lotlar)
        self.kapanan.append({"sembol": s, "modul": p.modul, "giris_t": p.giris_t, "cikis_t": t, "E0": p.E0,
                             "cikis": fiyat, "neden": neden, "ekler": p.ekler, "R": toplam_R})
        olaylar.append(Olay("CIKIS", s, p.modul, t, fiyat, p.stop, neden, toplam_R))

    def mum_isle(self, sembol: str, modul: str, bars: pd.DataFrame, rejim: dict) -> list[Olay]:
        """`bars`: bu modülün TAMAMLANMIŞ mumları (t, open, high, low, close), zamana göre sıralı.
        Daha önce işlenmemiş her mumu sırayla işler; üretilen olayları döndürür."""
        olaylar: list[Olay] = []
        if bars is None or len(bars) < 2:
            return olaylar
        bar_ms, N, kk = MODULLER[modul]
        t = bars["t"].to_numpy("int64")
        o, h, l, c = (bars[x].to_numpy(float) for x in ("open", "high", "low", "close"))
        hh = pd.Series(h).shift(1).rolling(N).max().to_numpy()
        atr = atr_wilder(h, l, c)
        anahtar = f"{sembol}|{modul}"
        son = self.son_bar.get(anahtar)
        bas = 0 if son is None else int(np.searchsorted(t, son, side="right"))
        for i in range(bas, len(t)):
            self._bir_mum(sembol, modul, i, t, o, h, l, c, hh, atr, kk, bar_ms, rejim, olaylar)
            self.son_bar[anahtar] = int(t[i])
        return olaylar

    def zaman_sirali_isle(self, sembol: str, mumlar: dict, rejim: dict) -> list[Olay]:
        """İki modülün mumlarını KAPANIŞ ZAMANINA göre birlikte işler (aynı kapanışta önce 1D, sonra 4H).
        Önce tüm 1D sonra tüm 4H geçmişini yürütmek, coin başına tek pozisyon kuralını yanlış sırada
        uygular (geçmiş yükleme ↔ mum mum ilerleme farklı durum üretirdi). Toplu yükleme, mum mum ilerleme
        ve kaydet/yükle aynı durumu üretir (testli)."""
        olaylar: list[Olay] = []
        hazir, sira = {}, []
        for oncelik, modul in enumerate(("1D", "4H")):
            bars = mumlar.get(modul)
            if bars is None or len(bars) < 2:
                continue
            bar_ms, N, kk = MODULLER[modul]
            t = bars["t"].to_numpy("int64")
            o, h, l, c = (bars[x].to_numpy(float) for x in ("open", "high", "low", "close"))
            hh = pd.Series(h).shift(1).rolling(N).max().to_numpy()
            atr = atr_wilder(h, l, c)
            hazir[modul] = (t, o, h, l, c, hh, atr, kk, bar_ms)
            son = self.son_bar.get(f"{sembol}|{modul}")
            bas = 0 if son is None else int(np.searchsorted(t, son, side="right"))
            sira += [(int(t[i]) + bar_ms, oncelik, modul, i) for i in range(bas, len(t))]
        for _, _, modul, i in sorted(sira):
            t, o, h, l, c, hh, atr, kk, bar_ms = hazir[modul]
            self._bir_mum(sembol, modul, i, t, o, h, l, c, hh, atr, kk, bar_ms, rejim, olaylar)
            self.son_bar[f"{sembol}|{modul}"] = int(t[i])
        return olaylar

    def _bir_mum(self, s, modul, i, t, o, h, l, c, hh, atr, kk, bar_ms, rejim, olaylar):
        p = self.poz.get(s)
        bk = self.bekleyen.get(s)
        # 1) açılış: boşluk stopu, bekleyen çıkış
        if p is not None and p.modul == modul:
            if o[i] <= p.stop:
                self.bekleyen.pop(s, None)
                self._kapat(s, float(o[i]), int(t[i]), "STOP_BOŞLUK", olaylar)
                p = None
            elif bk and bk.get("tur") == "cikis":
                self.bekleyen.pop(s, None)
                self._kapat(s, float(o[i]), int(t[i]), bk.get("neden", "ÇIKIŞ"), olaylar)
                p = None
            elif bk and bk.get("tur") == "ek":
                self.bekleyen.pop(s, None)
                D = float(o[i]) - p.stop
                if D > 0:
                    p.lotlar.append({"t": int(t[i]), "E": float(o[i]), "D": D, "risk_birim": 1.0})
                    p.ekler += 1
                    olaylar.append(Olay("EK", s, modul, int(t[i]), float(o[i]), p.stop))
        # 2) bekleyen giriş (bu modülün sinyali)
        bk = self.bekleyen.get(s)
        if bk and bk.get("tur") == "giris" and bk.get("modul") == modul:
            self.bekleyen.pop(s, None)
            if s not in self.poz and o[i] > bk["S0"]:
                E = float(o[i])
                self.poz[s] = Pozisyon(s, modul, int(t[i]), int(bk["sinyal_t"]), E, E - bk["S0"], bk["S0"],
                                       bk["S0"], bk["c"], lotlar=[{"t": int(t[i]), "E": E, "D": E - bk["S0"],
                                                                   "risk_birim": 1.0}])
                olaylar.append(Olay("GIRIS", s, modul, int(t[i]), E, bk["S0"]))
        # 3) mum içi stop
        p = self.poz.get(s)
        if p is not None and p.modul == modul and l[i] <= p.stop:
            self._kapat(s, float(p.stop), int(t[i]), "STOP", olaylar)
            p = None
        # 4) kapanış: stop güncelle, erken çıkış, piramit; düzse yeni sinyal
        p = self.poz.get(s)
        if p is not None:
            if p.modul != modul:
                return
            if np.isfinite(atr[i]):
                p.best = max(p.best, float(c[i]))
                p.stop = max(p.stop, p.best - kk * float(atr[i]))
            p.mfe = max(p.mfe, float(c[i]) - p.E0)
            if (int(t[i]) + bar_ms - p.giris_t) >= ERKEN_GUN * DAY_MS and p.mfe < p.D0:
                self.bekleyen[s] = {"tur": "cikis", "neden": "ERKEN_ÇIKIŞ"}
                olaylar.append(Olay("CIKIS_SINYALI", s, modul, int(t[i]), float(c[i]), p.stop, "ERKEN_ÇIKIŞ"))
            elif (p.ekler < PIRAMIT_MAKS and float(c[i]) - p.E0 >= (p.ekler + 1) * PIRAMIT_ADIM_R * p.D0):
                self.bekleyen[s] = {"tur": "ek"}
                olaylar.append(Olay("EK_SINYALI", s, modul, int(t[i]), float(c[i]), p.stop))
            return
        if s in self.bekleyen:                     # diğer modülün bekleyen girişi var
            return
        if not (np.isfinite(hh[i]) and np.isfinite(atr[i]) and atr[i] > 0):
            return
        if not c[i] > hh[i]:
            return
        rv = rejim.get(((int(t[i]) + bar_ms) // DAY_MS) * DAY_MS - DAY_MS)
        if rv is not True:          # rejim kapalı ya da BİLİNMİYOR (ETH geçmişi yetersiz) → giriş yok
            return
        S0 = float(c[i]) - kk * float(atr[i])
        if not (S0 < c[i]):
            return
        self.bekleyen[s] = {"tur": "giris", "modul": modul, "S0": S0, "c": float(c[i]), "sinyal_t": int(t[i])}
        olaylar.append(Olay("GIRIS_SINYALI", s, modul, int(t[i]), float(c[i]), S0))
