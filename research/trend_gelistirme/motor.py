"""
Trend kolu ORTAK SAATLİ portföy motoru (ONKAYIT.md). Varyantlar: B0 (düzeltilmiş taban), B1, B2, B3.

Motor yalnız o ana kadar kapanmış veriyi kullanır (gelecek sızıntısı testle denetlenir) ve durumu
pickle ile kaydedilip kaldığı yerden sürdürülebilir (toplu ↔ adım adım ↔ kaydet/yükle eşdeğerliği testli).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from research.liquidity_sweep_v1 import config as C
from research.liquidity_sweep_v1.accounting import entry_fill, exit_fill, floor_step

DAY = 86_400_000
H4 = 4 * 3_600_000
ATR_N = 20
K_ATR = 5.0
N_GUN = 50
N_4H = 180
ERKEN_GUN = 10
PIR_ADIM = 2.0
PIR_MAKS = 2
ETH_SMA = 200
ISINMA_GUN = 200


def atr_wilder(h, l, c, n=ATR_N):
    out = np.full(len(c), np.nan)
    pa, pc, k = None, None, 1.0 / n
    for i in range(len(c)):
        tr = h[i] - l[i] if pc is None else max(h[i] - l[i], abs(h[i] - pc), abs(l[i] - pc))
        pa = tr if pa is None else tr * k + pa * (1 - k)
        out[i] = pa
        pc = c[i]
    return out


@dataclass
class Coin:
    ad: str
    t: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    tick: float
    cs: float
    vu: float
    mv: float
    f_t: np.ndarray
    f_r: np.ndarray

    def hazirla(self):
        self.idx = {int(x): i for i, x in enumerate(self.t)}
        self.hh4 = pd.Series(self.h).shift(1).rolling(N_4H).max().to_numpy()
        self.atr4 = atr_wilder(self.h, self.l, self.c)
        gun = (self.t // DAY) * DAY
        d = pd.DataFrame({"g": gun, "o": self.o, "h": self.h, "l": self.l, "c": self.c})
        d = d.groupby("g").agg(o=("o", "first"), h=("h", "max"), l=("l", "min"), c=("c", "last"), n=("o", "size"))
        d = d[d.n == 6]
        self.dg = d.index.to_numpy("int64")
        self.do, self.dh, self.dl, self.dc = (d[x].to_numpy(float) for x in ("o", "h", "l", "c"))
        self.didx = {int(x): j for j, x in enumerate(self.dg)}
        self.hhd = pd.Series(self.dh).shift(1).rolling(N_GUN).max().to_numpy()
        self.atrd = atr_wilder(self.dh, self.dl, self.dc)
        self.ilk = int(self.t[0]) if len(self.t) else 0
        return self


@dataclass
class Lot:
    tur: str            # "ilk" | "ek1" | "ek2"
    t: int
    E: float
    q: float
    ucret: float
    teminat: float
    pnl: float = 0.0    # kapanınca net (ücretler ve funding payı dahil)


@dataclass
class Poz:
    coin: str
    modul: str          # giriş modülü
    yonetim: str        # stop yönetimi: "4H" | "1D" (B1 devriyle 4H→1D)
    sinyal_t: int
    giris_t: int
    E0: float
    D0: float
    S0: float
    stop: float
    best: float         # yönetim modülünün kapanışlarıyla en iyi
    seviye: float       # B3: sinyalin dayandığı kanal tepesi (sabit)
    lots: list = field(default_factory=list)
    ulasti_1R: bool = False
    b3_sayac: int = 0
    bekleyen: dict = field(default_factory=dict)   # {"cikis": neden} | {"ek": n}
    funding: float = 0.0
    tepe_acik: float = 0.0
    devir_t: int | None = None
    ek_engel: int = 0                               # engellenen FARKLI ek hakları (n) sayısı
    engel_set: set = field(default_factory=set)


class Motor:
    def __init__(self, coins: dict, eth: str, varyant: str, maliyet, C0=10_000.0, t_bas=None, t_bit=None,
                 risk=0.01, acik_risk_tavan=0.24, cap=2.5, lev=10.0):
        self.coins = coins
        self.eth = eth
        self.v = varyant
        self.m = maliyet
        self.C0, self.risk, self.tavan, self.cap, self.lev = C0, risk, acik_risk_tavan, cap, lev
        self.t_bas, self.t_bit = t_bas, t_bit
        self.cuzdan = C0
        self.poz: dict[str, Poz] = {}
        self.bek_giris: dict[str, dict] = {}
        self.islemler: list = []
        self.olaylar: list = []
        self.seri: list = []
        self.son_deger = C0
        saat = sorted({int(x) for c in coins.values() for x in c.t if (t_bit is None or x + H4 <= t_bit)})
        self.saat = saat
        self.adim = 0
        e = coins[eth]
        sma = pd.Series(e.dc).rolling(ETH_SMA).mean().to_numpy()
        self.rejim = {int(g): bool(c > s) for g, c, s in zip(e.dg, e.dc, sma) if np.isfinite(s)}

    # ── yardımcılar ─────────────────────────────────────────────────────────
    def _rejim(self, karar_t):
        """karar anındaki SON TAMAMLANMIŞ UTC günü; bilinmiyorsa None."""
        return self.rejim.get((karar_t // DAY) * DAY - DAY)

    def _teminat(self, notional, E, stop):
        s = max(E - stop, 0.0) / E
        return notional * max(1.0 / self.lev, 1.5 * s + 0.005)

    def _acik_risk(self):
        return sum(max(l.E - p.stop, 0.0) * l.q for p in self.poz.values() for l in p.lots)

    def _toplam_teminat(self):
        return sum(l.teminat for p in self.poz.values() for l in p.lots)

    def _miktar(self, coin: Coin, E, stop, deger):
        d = E - stop
        if d <= 0:
            return 0.0, "MESAFE"
        q = self.risk * deger / d
        q = min(q, self.cap * deger / E)
        n = floor_step(q / coin.cs, coin.vu)
        if n < coin.mv - 1e-12:
            return 0.0, "MIN_EMIR"
        q = n * coin.cs
        if self._acik_risk() + d * q > self.tavan * deger + 1e-9:
            return 0.0, "RISK_TAVANI"
        if self._toplam_teminat() + self._teminat(E * q, E, stop) > 0.95 * deger + 1e-9:
            return 0.0, "TEMINAT"
        return q, "OK"

    def _lot_ac(self, p: Poz, coin: Coin, tur, t, O, deger):
        E = entry_fill(O, 1, self.m.entry_slip_bp, coin.tick)
        q, neden = self._miktar(coin, E, p.stop, deger)
        if q <= 0:
            return None, neden
        ucret = E * q * self.m.entry_fee_rate
        self.cuzdan -= ucret
        lot = Lot(tur, t, E, q, ucret, self._teminat(E * q, E, p.stop))
        p.lots.append(lot)
        return lot, "OK"

    def _kapat(self, k: str, ref: float, t: int, neden: str):
        p = self.poz.pop(k)
        coin = self.coins[k]
        xf = exit_fill(ref, 1, self.m.exit_slip_bp, coin.tick)
        top_q = sum(l.q for l in p.lots)
        net = 0.0
        for l in p.lots:
            brut = (xf - l.E) * l.q
            uc = xf * l.q * self.m.exit_fee_rate
            fpay = p.funding * (l.q / top_q) if top_q else 0.0
            l.pnl = brut - l.ucret - uc + fpay
            self.cuzdan += brut - uc
            net += l.pnl
        self.cuzdan += 0.0  # funding zaten cüzdana işlendi
        R0 = p.D0 * p.lots[0].q if p.lots else 0.0
        self.islemler.append(dict(
            coin=k, modul=p.modul, yonetim=p.yonetim, sinyal_t=p.sinyal_t, giris_t=p.giris_t, cikis_t=t,
            neden=neden, E0=p.E0, D0=p.D0, S0=p.S0, cikis=xf, ekler=len(p.lots) - 1,
            pnl=net, pnl_ilk=sum(l.pnl for l in p.lots if l.tur == "ilk"),
            pnl_ek1=sum(l.pnl for l in p.lots if l.tur == "ek1"), pnl_ek2=sum(l.pnl for l in p.lots if l.tur == "ek2"),
            funding=p.funding, ucret=sum(l.ucret for l in p.lots) + xf * top_q * self.m.exit_fee_rate,
            ilk_risk=R0, tepe_acik=p.tepe_acik, devir_t=p.devir_t, ek_engel=p.ek_engel,
            gun=(t - p.giris_t) / DAY))

    # ── ana döngü ───────────────────────────────────────────────────────────
    def kos(self, kadar: int | None = None):
        son = len(self.saat) if kadar is None else min(kadar, len(self.saat))
        while self.adim < son:
            self._adim(self.saat[self.adim])
            self.adim += 1
        return self

    def _adim(self, t):
        T = t + H4
        deger0 = self.son_deger
        aktif = self.t_bas is None or t >= self.t_bas
        coins = self.coins
        # 1) açılış
        for k in sorted(coins):
            coin = coins[k]
            i = coin.idx.get(t)
            if i is None:
                continue
            O = coin.o[i]
            p = self.poz.get(k)
            if p is not None:
                if O <= p.stop:
                    self._kapat(k, O, t, "STOP_BOSLUK")
                    p = None
                elif "cikis" in p.bekleyen:
                    self._kapat(k, O, t, p.bekleyen["cikis"])
                    p = None
                elif "ek" in p.bekleyen:
                    n = p.bekleyen.pop("ek")
                    if self.v == "B2" and self._rejim(t) is not True:
                        if n not in p.engel_set:
                            p.engel_set.add(n)
                            p.ek_engel += 1
                        self.olaylar.append(dict(t=t, coin=k, tur="EK_ENGEL_B2_DOLUM", n=n))
                    else:
                        lot, neden = self._lot_ac(p, coin, f"ek{n}", t, O, deger0)
                        if lot is None:
                            self.olaylar.append(dict(t=t, coin=k, tur=f"EK_ATLANDI_{neden}", n=n))
            bg = self.bek_giris.pop(k, None)
            if bg is not None:
                if k in self.poz or not aktif or not (O > bg["S0"]):
                    self.olaylar.append(dict(t=t, coin=k, tur="GIRIS_IPTAL", neden="PLAN_DISI" if O <= bg["S0"] else "DOLU"))
                else:
                    p = Poz(k, bg["modul"], bg["modul"], bg["sinyal_t"], t, 0.0, 0.0, bg["S0"], bg["S0"], bg["c"], bg["seviye"])
                    lot, neden = self._lot_ac(p, coin, "ilk", t, O, deger0)
                    if lot is None:
                        self.olaylar.append(dict(t=t, coin=k, tur=f"GIRIS_ATLANDI_{neden}"))
                    else:
                        p.E0, p.D0 = lot.E, lot.E - p.S0
                        self.poz[k] = p
        # 2) mum içi stop
        for k in sorted(list(self.poz)):
            coin = coins[k]
            i = coin.idx.get(t)
            if i is not None and coin.l[i] <= self.poz[k].stop:
                self._kapat(k, self.poz[k].stop, t, "STOP")
        # 3) funding (t, T]
        for k, p in self.poz.items():
            coin = coins[k]
            i = coin.idx.get(t)
            if i is None:
                continue
            a, b = np.searchsorted(coin.f_t, t, "right"), np.searchsorted(coin.f_t, T, "right")
            if b > a:
                q = sum(l.q for l in p.lots)
                cf = float(sum(-q * coin.o[i] * r for r in coin.f_r[a:b]))
                p.funding += cf
                self.cuzdan += cf
        # 4) kapanış: 4H yönetimi
        for k in sorted(list(self.poz)):
            p, coin = self.poz[k], coins[k]
            i = coin.idx.get(t)
            if i is None or p.modul != "4H":
                continue
            self._yonet(p, coin.c[i], coin.atr4[i], T, guncelle_stop=(p.yonetim == "4H"))
        # 5) gün sonu: 1D yönetimi + B1 devri
        gun_sonu = T % DAY == 0
        if gun_sonu:
            g = T - DAY
            for k in sorted(list(self.poz)):
                p, coin = self.poz[k], coins[k]
                j = coin.didx.get(g)
                if j is None:
                    continue
                if p.modul == "1D":
                    self._yonet(p, coin.dc[j], coin.atrd[j], T, guncelle_stop=True)
                elif p.yonetim == "1D":       # devredilmiş 4H: stop yalnız günlük kapanışta
                    p.best = max(p.best, coin.dc[j])
                    if np.isfinite(coin.atrd[j]):
                        p.stop = max(p.stop, p.best - K_ATR * coin.atrd[j])
                elif self.v == "B1" and np.isfinite(coin.hhd[j]) and coin.dc[j] > coin.hhd[j] \
                        and self._rejim(T) is True:
                    p.yonetim, p.devir_t = "1D", T
                    jj = coin.didx.get((p.giris_t // DAY) * DAY, j)
                    p.best = float(np.max(coin.dc[jj:j + 1]))
                    if np.isfinite(coin.atrd[j]):
                        p.stop = max(p.stop, p.best - K_ATR * coin.atrd[j])
                    self.olaylar.append(dict(t=T, coin=k, tur="DEVIR_4H_1D"))
        # 6) yeni sinyaller (önce 1D, sonra 4H)
        if aktif:
            if gun_sonu:
                g = T - DAY
                for k in sorted(coins):
                    coin = coins[k]
                    j = coin.didx.get(g)
                    if j is not None:
                        self._sinyal(k, coin, "1D", coin.dc[j], coin.hhd[j], coin.atrd[j], T)
            for k in sorted(coins):
                coin = coins[k]
                i = coin.idx.get(t)
                if i is not None:
                    self._sinyal(k, coin, "4H", coin.c[i], coin.hh4[i], coin.atr4[i], T)
        # 7) hesap değeri (ortak kapanış fiyatlarıyla)
        acik = 0.0
        for k, p in self.poz.items():
            coin = coins[k]
            i = coin.idx.get(t)
            px = coin.c[i] if i is not None else p.lots[-1].E
            ap = sum((px - l.E) * l.q for l in p.lots)
            acik += ap
            p.tepe_acik = max(p.tepe_acik, ap + p.funding - sum(l.ucret for l in p.lots))
        self.son_deger = self.cuzdan + acik
        if aktif:
            self.seri.append((T, self.son_deger, len(self.poz), self._acik_risk(), self._toplam_teminat()))

    def _yonet(self, p: Poz, c, atr, T, guncelle_stop: bool):
        if guncelle_stop and np.isfinite(atr):
            p.best = max(p.best, c)
            p.stop = max(p.stop, p.best - K_ATR * atr)
        if c - p.E0 >= p.D0:
            p.ulasti_1R = True
        if (T - p.giris_t) >= ERKEN_GUN * DAY and not p.ulasti_1R:
            p.bekleyen = {"cikis": "ERKEN_CIKIS"}
            return
        if self.v == "B3" and not p.ulasti_1R:
            p.b3_sayac = p.b3_sayac + 1 if c < p.seviye else 0
            if p.b3_sayac >= 2:
                p.bekleyen = {"cikis": "B3_BASARISIZ_KIRILIM"}
                return
        n = len(p.lots)              # ilk + mevcut ekler
        if n - 1 < PIR_MAKS and c - p.E0 >= n * PIR_ADIM * p.D0:
            if self.v == "B2" and self._rejim(T) is not True:
                if n not in p.engel_set:
                    p.engel_set.add(n)
                    p.ek_engel += 1
                    self.olaylar.append(dict(t=T, coin=p.coin, tur="EK_ENGEL_B2_TETIK", n=n))
            else:
                p.bekleyen = {"ek": n}

    def _sinyal(self, k, coin: Coin, modul, c, hh, atr, T):
        if k in self.poz or k in self.bek_giris:
            return
        if T - coin.ilk < ISINMA_GUN * DAY:
            return
        if not (np.isfinite(hh) and np.isfinite(atr) and atr > 0 and c > hh):
            return
        rv = self._rejim(T)
        if rv is not True:                     # rejim kapalı ya da BİLİNMİYOR → giriş yok
            if rv is None:
                self.olaylar.append(dict(t=T, coin=k, tur="REJIM_BILINMIYOR"))
            return
        S0 = c - K_ATR * atr
        if not S0 < c:
            return
        self.bek_giris[k] = dict(modul=modul, S0=float(S0), c=float(c), sinyal_t=int(T - (H4 if modul == "4H" else DAY)),
                                 seviye=float(hh))
