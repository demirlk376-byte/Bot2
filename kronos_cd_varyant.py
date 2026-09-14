"""
kronos_cd_varyant.py — KRONOS motorunun cooldown SEMANTIGINI parametrelestiren
AYRI bir varyant motoru.  kronos/ ALTINA DOKUNULMAZ.

kos() gövdesi kronos/motor.py'den BIREBIR kopyalanmistir; TEK fark cooldown
bloklarinin parametrelenmesi ve iç sayaçlarin genisletilmesidir.  Denklik
`cd_olcum.py` icinde VaryantKronos(varsayilan ayar) == Kronos(ayni ayar)
karsilastirmasiyla KOSARAK dogrulanir.

Parametreler (VAyar):
  anahtar_kapsam : "kol_coin" (canlinin/kronos'un hali) | "kol" | "coin" | "genel"
  sifirla_tetikte: True  -> cooldown tetiklenince ardisik-zarar sayaci 0'lanir
                   False -> (mevcut hal) sayac kalir, HER sonraki kayip
                            cooldown'u yeniden kurar ("cirnik/ratchet")
  yeniden_baslat_gun : >0 ise her N gunde bir cooldown+streak sozlukleri
                       SIFIRLANIR (systemd Restart=always benzetimi).
                       Canlida bu sozlukler yalnizca BELLEKTE.
  zaman_birimi   : "auto"  -> damgalar()'in i8 degeri indeksin GERCEK biriminden
                             (pandas 3'te 'us') Timestamp'e cevrilir. DOGRU.
                   "bozuk" -> kronos/motor.py'deki gibi pd.Timestamp(ts, tz="UTC")
                             yani i8 NANOSANIYE sanilir.  pandas 3.0'da indeks
                             birimi MIKROSANIYE oldugu icin butun zaman ekseni
                             1000x SIKISIR: 3.3 yil -> 1.2 gun, 240dk cooldown ->
                             166 GERCEK GUN, gun=simdi.date() -> 2 farkli gun.
                             Yalniz A/B kaniti icin var.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd

from kronos.motor import Ayar, Islem, k_sig_var


@dataclass
class VAyar(Ayar):
    anahtar_kapsam: str = "kol_coin"
    sifirla_tetikte: bool = False
    yeniden_baslat_gun: float = 0.0
    zaman_birimi: str = "auto"        # "auto" = DOGRU · "bozuk" = motor.py taklidi


class VaryantKronos:
    """kronos.Kronos ile ayni; cooldown semantigi parametreli."""

    def __init__(self, kollar, ayar: VAyar = None):
        self.kollar = list(kollar)
        self.a = ayar or VAyar()

    def _cizelge(self):
        ol = []
        for ki, k in enumerate(self.kollar):
            ns = k.besleme.damgalar()
            oc = (k.oncelik, k.sira)
            for i in range(len(ns)):
                ol.append((ns[i], oc[0], oc[1], ki, i))
        ol.sort(key=lambda x: (x[0], x[1], x[2]))
        return ol

    def _anahtar(self, k):
        m = self.a.anahtar_kapsam
        if m == "kol_coin":
            return f"{k.ad}:{k.coin}"
        if m == "kol":
            return k.ad
        if m == "coin":
            return k.coin
        return "GENEL"

    def _birim(self):
        """damgalar() i8'inin GERCEK birimi. pandas 3'te 'us'."""
        if self.a.zaman_birimi != "auto":
            return None                       # None = motor.py'nin (bozuk) yolu
        u = getattr(self.kollar[0].besleme._idx, "unit", "ns")
        for k in self.kollar:                 # tum kollar ayni birimde olmali
            if getattr(k.besleme._idx, "unit", "ns") != u:
                raise ValueError("kollar farkli zaman biriminde")
        return u

    def kos(self):
        a = self.a
        BIRIM = self._birim()
        kayma = a.kayma_bp / 1e4
        ol = self._cizelge()
        acik: dict[int, dict] = {}
        engel: dict[int, int] = {}
        seri_zarar: dict[str, int] = {}
        cooldown: dict[str, pd.Timestamp] = {}
        gun_durdu: set = set()
        gun_pnl: dict = {}
        gun_bas: dict = {}
        equity = a.bal0
        islemler: list[Islem] = []
        self.sayac = dict(sinyal=0, cd_engel=0, gun_engel=0, koltuk_engel=0, acildi=0,
                          cd_tetik=0, restart=0)
        self.tetikler = []       # (ts, anahtar, streak)
        self.engeller = []       # (ts, anahtar)
        son_restart = None

        j, N = 0, len(ol)
        while j < N:
            ts = ol[j][0]; e = j
            while e < N and ol[e][0] == ts: e += 1
            grup = ol[j:e]
            simdi = (pd.Timestamp(ts, tz="UTC") if BIRIM is None
                     else pd.Timestamp(ts, unit=BIRIM, tz="UTC"))
            gun = simdi.date()
            if gun not in gun_bas: gun_bas[gun] = equity

            # ── systemd Restart benzetimi: bellek-ici kapi durumu ucar ──
            if a.yeniden_baslat_gun > 0:
                if son_restart is None:
                    son_restart = simdi
                elif (simdi - son_restart).total_seconds() >= a.yeniden_baslat_gun * 86400:
                    seri_zarar.clear(); cooldown.clear()
                    son_restart = simdi
                    self.sayac["restart"] += 1

            # ─── 1) CIKISLAR ───
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

                if a.ardisik_zarar_limiti > 0:
                    anah = self._anahtar(k)
                    if pnl < 0:
                        seri_zarar[anah] = seri_zarar.get(anah, 0) + 1
                        if seri_zarar[anah] >= a.ardisik_zarar_limiti:
                            cooldown[anah] = simdi + pd.Timedelta(minutes=a.cooldown_dk)
                            self.sayac["cd_tetik"] += 1
                            self.tetikler.append((simdi, anah, seri_zarar[anah]))
                            if a.sifirla_tetikte:
                                seri_zarar[anah] = 0
                    else:
                        seri_zarar[anah] = 0

            if a.gunluk_zarar_pct > 0 and gun not in gun_durdu:
                if gun_pnl.get(gun, 0.0) <= -a.gunluk_zarar_pct * gun_bas[gun]:
                    gun_durdu.add(gun)

            # ─── 2) GIRISLER ───
            for _ns, _p, _s, ki, i in grup:
                if ki in acik: continue
                if (not a.ayni_bar_giris) and ki in cikan: continue
                if a.hayalet_blokaj and i <= engel.get(ki, -1): continue
                if gun in gun_durdu:
                    if k_sig_var(self.kollar[ki], i): self.sayac["gun_engel"] += 1
                    continue
                k = self.kollar[ki]
                anah = self._anahtar(k)
                cd = cooldown.get(anah)
                if cd is not None and simdi < cd:
                    if k.sinyal(i) is not None:
                        self.sayac["cd_engel"] += 1
                        self.engeller.append((simdi, f"{k.ad}:{k.coin}"))
                    continue

                sg = k.sinyal(i)
                if sg is None: continue
                self.sayac["sinyal"] += 1
                yon, sld, rr, mh = sg
                if len(acik) >= a.maxpos:
                    self.sayac["koltuk_engel"] += 1
                    if a.hayalet_blokaj:
                        engel[ki] = min(i + mh, k.besleme.n - 1)
                    continue
                _h, _l, cl = k.besleme.bar(i)
                self.sayac["acildi"] += 1
                acik[ki] = dict(yon=yon, e=cl, sld=sld, slp=cl - yon * sld,
                                tp=cl + yon * rr * sld, i0=i, mh=mh, sl_pct=sld / cl)
                if a.hayalet_blokaj: engel[ki] = min(i + mh, k.besleme.n - 1)
            j = e

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
