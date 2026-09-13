"""KRONOS çekirdeği: Besleme (nedensellik zırhı) + olay döngüsü + kapılar."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import pandas as pd


# ═══════════════════════════ NEDENSELLİK ZIRHI ═══════════════════════════
class Besleme:
    """Veriyi tutar ama YALNIZCA `i` barına kadar gösterir.

    Strateji ham seriye erişemez — `_d` isim-karartmalı ve `pencere()` dışında
    hiçbir yol yok. `i+1` ve sonrası fiziksel olarak dilime giremez.
    """
    __slots__ = ("_d", "_hi", "_lo", "_cl", "_idx", "n")

    def __init__(self, d: pd.DataFrame):
        self._d = d
        self._hi = d["high"].values
        self._lo = d["low"].values
        self._cl = d["close"].values
        self._idx = d.index
        self.n = len(d)

    def pencere(self, i: int, geriye: Optional[int] = None) -> pd.DataFrame:
        """i DAHİL, i+1 ASLA. geriye=None → baştan i'ye kadar."""
        if i < 0 or i >= self.n:
            raise IndexError(f"pencere({i}) sınır dışı (n={self.n})")
        bas = 0 if geriye is None else max(0, i - geriye + 1)
        return self._d.iloc[bas:i + 1]

    # ── bar ölçümü: AÇIK pozisyonun o bardaki yolu. Gelecek değil, ŞİMDİ. ──
    def bar(self, i: int):
        return self._hi[i], self._lo[i], self._cl[i]

    def zaman(self, i: int) -> pd.Timestamp:
        return self._idx[i]

    def damgalar(self) -> np.ndarray:
        return self._idx.asi8


# ═══════════════════════════ AYAR ve İŞLEM ═══════════════════════════
@dataclass
class Ayar:
    """Canlı botun kapıları. Varsayılanlar deployed_backtest ankoruyla aynı;
    gerçek canlı değerler .env'den gelmeli (VPS)."""
    maxpos: int = 7
    fee: float = 0.0001                    # taraf başına
    riskf: float = 0.028                   # canlı RISK_PER_TRADE x RISK_SCALE
    cap: float = 1.50                      # POSITION_CAP_FRACTION
    bal0: float = 190.0
    kayma_bp: float = 0.0                  # 15.85 → giriş kayması uygula
    # canlı kapılar (ankorda YOK)
    ardisik_zarar_limiti: int = 0          # 0 = kapalı; canlı 2
    cooldown_dk: int = 240
    gunluk_zarar_pct: float = 0.0          # 0 = kapalı; canlı 0.35
    # ankor uyumu için
    ayni_bar_giris: bool = True            # False = ankorun `i <= occ` kuralı
    hayalet_blokaj: bool = False           # True = ankor taklidi
    bilesik_boyut: bool = False            # True = canlı equity'den boyutla


@dataclass
class Islem:
    kol: str
    coin: str
    yon: int
    giris_ts: pd.Timestamp
    cikis_ts: pd.Timestamp
    giris: float
    cikis: float
    sld: float                              # stop mesafesi (fiyat)
    R: float
    sl_pct: float
    neden: str
    eff: float = 0.0
    pnl: float = 0.0


# ═══════════════════════════ MOTOR ═══════════════════════════
class Kronos:
    """Tek zaman çizgisi. Her damgada: ÖNCE çıkışlar (koltuk boşalır),
    SONRA girişler (koltuk O AN sorulur) — canlı botun sırası."""

    def __init__(self, kollar, ayar: Ayar = None):
        self.kollar = list(kollar)
        self.a = ayar or Ayar()

    # ── olay çizelgesi: (damga, kol_önceliği, coin_sırası, kol_no, bar_no) ──
    def _cizelge(self):
        ol = []
        for ki, k in enumerate(self.kollar):
            ns = k.besleme.damgalar()
            oc = (k.oncelik, k.sira)
            for i in range(len(ns)):
                ol.append((ns[i], oc[0], oc[1], ki, i))
        ol.sort(key=lambda x: (x[0], x[1], x[2]))
        return ol

    def kos(self):
        a = self.a
        kayma = a.kayma_bp / 1e4
        ol = self._cizelge()
        acik: dict[int, dict] = {}
        engel: dict[int, int] = {}
        # canlı kapı durumu
        seri_zarar: dict[str, int] = {}
        cooldown: dict[str, pd.Timestamp] = {}
        gun_durdu: set = set()
        gun_pnl: dict = {}
        equity = a.bal0
        islemler: list[Islem] = []

        j, N = 0, len(ol)
        while j < N:
            ts = ol[j][0]; e = j
            while e < N and ol[e][0] == ts: e += 1
            grup = ol[j:e]
            simdi = pd.Timestamp(ts, tz="UTC")
            gun = simdi.date()

            # ─── 1) ÇIKIŞLAR ───
            cikan = set()
            for _ns, _p, _s, ki, i in grup:
                p = acik.get(ki)
                if p is None or i <= p["i0"]: continue
                k = self.kollar[ki]
                hi, lo, cl = k.besleme.bar(i)
                ep, neden = None, ""
                if p["yon"] == 1:
                    if lo <= p["slp"]: ep, neden = p["slp"], "sl"
                    elif hi >= p["tp"]: ep, neden = p["tp"], "tp"
                else:
                    if hi >= p["slp"]: ep, neden = p["slp"], "sl"
                    elif lo <= p["tp"]: ep, neden = p["tp"], "tp"
                if ep is None and i >= p["i0"] + p["mh"]: ep, neden = cl, "sure"
                if ep is None: continue

                R = p["yon"] * (ep - p["e"]) / p["sld"] - 2 * a.fee * p["e"] / p["sld"]
                if kayma: R -= kayma / p["sl_pct"]
                eff = min(a.riskf, a.cap * p["sl_pct"])
                taban = equity if a.bilesik_boyut else a.bal0
                pnl = R * eff * taban
                equity += pnl
                gun_pnl[gun] = gun_pnl.get(gun, 0.0) + pnl
                islemler.append(Islem(k.ad, k.coin, p["yon"], k.besleme.zaman(p["i0"]),
                                      k.besleme.zaman(i), p["e"], ep, p["sld"], R,
                                      p["sl_pct"], neden, eff, pnl))
                del acik[ki]; cikan.add(ki)

                # canlı kapı: ardışık zarar → cooldown
                if a.ardisik_zarar_limiti > 0:
                    anah = f"{k.ad}:{k.coin}"
                    if pnl < 0:
                        seri_zarar[anah] = seri_zarar.get(anah, 0) + 1
                        if seri_zarar[anah] >= a.ardisik_zarar_limiti:
                            cooldown[anah] = simdi + pd.Timedelta(minutes=a.cooldown_dk)
                    else:
                        seri_zarar[anah] = 0

            # canlı kapı: günlük zarar freni
            if a.gunluk_zarar_pct > 0 and gun not in gun_durdu:
                if gun_pnl.get(gun, 0.0) <= -a.gunluk_zarar_pct * a.bal0:
                    gun_durdu.add(gun)

            # ─── 2) GİRİŞLER ───
            for _ns, _p, _s, ki, i in grup:
                if ki in acik: continue
                if (not a.ayni_bar_giris) and ki in cikan: continue
                if a.hayalet_blokaj and i <= engel.get(ki, -1): continue
                if gun in gun_durdu: continue
                k = self.kollar[ki]
                anah = f"{k.ad}:{k.coin}"
                cd = cooldown.get(anah)
                if cd is not None and simdi < cd: continue

                sg = k.sinyal(i)                      # ← pencere(i) DIŞINA çıkamaz
                if sg is None: continue
                yon, sld, rr, mh = sg
                if len(acik) >= a.maxpos:
                    if a.hayalet_blokaj:
                        engel[ki] = min(i + mh, k.besleme.n - 1)
                    continue
                _h, _l, cl = k.besleme.bar(i)
                acik[ki] = dict(yon=yon, e=cl, sld=sld, slp=cl - yon * sld,
                                tp=cl + yon * rr * sld, i0=i, mh=mh, sl_pct=sld / cl)
                if a.hayalet_blokaj: engel[ki] = min(i + mh, k.besleme.n - 1)
            j = e

        # veri bitiminde açık kalanlar
        for ki, p in acik.items():
            k = self.kollar[ki]
            i = min(p["i0"] + p["mh"], k.besleme.n - 1)
            _h, _l, cl = k.besleme.bar(i)
            R = p["yon"] * (cl - p["e"]) / p["sld"] - 2 * a.fee * p["e"] / p["sld"]
            if kayma: R -= kayma / p["sl_pct"]
            eff = min(a.riskf, a.cap * p["sl_pct"])
            taban = equity if a.bilesik_boyut else a.bal0
            islemler.append(Islem(k.ad, k.coin, p["yon"], k.besleme.zaman(p["i0"]),
                                  k.besleme.zaman(i), p["e"], cl, p["sld"], R,
                                  p["sl_pct"], "veri_sonu", eff, R * eff * taban))
        islemler.sort(key=lambda t: (t.cikis_ts.value, t.giris_ts.value, t.kol, t.coin))
        return islemler
