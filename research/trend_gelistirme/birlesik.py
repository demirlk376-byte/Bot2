"""Trend B0–B3 + canlı bot (ikiz işlemleri) AYNI HESAPTA: ortak sermaye, ortak teminat.
`PYTHONPATH=. python3 -m research.trend_gelistirme.birlesik --ikiz-db <ikiz_trades.db>`

Bot işlemleri: canlı-birebir ikizin işlem listesi (937). Her bot işlemi:
  - risk = %3.5 × ortak hesap değeri (önceki kapanış), sonuç = R × risk (R ikizdeki net sonuç / ilk risk);
  - teminat = (ikizdeki notional / ikizin o andaki kapanmış-işlem bakiyesi) × ortak hesap değeri / 10;
  - toplam teminat (bot + trend) > 0.95 × hesap değeri olacaksa işlem ATLANIR (sayılır).
Bot pozisyonlarının açık PnL'i ikizde yok → hesap değeri kesitinde yalnız trendin açık PnL'i var
(bot kısmının düşüşü eksik ölçülür; raporda sınırlama olarak yazılır).
Netted çakışma: hesap hedge modda, girişler kendi stoplarıyla (VPS denemeleri) → coin çakışması engel değil.
Pencere: ikiz başlangıcı 2023-04-07 → 2025-08-08 (final kapalı)."""
from __future__ import annotations

import argparse, json, os, sqlite3, subprocess
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from research.liquidity_sweep_v1 import config as C
from research.trend_gelistirme.motor import Motor, H4
from research.trend_gelistirme.veri import yukle, BOT12, KOK
from research.trend_gelistirme.kos import donem_olc, yillik, MAL

ms = lambda s: int(pd.Timestamp(s, tz="UTC").timestamp() * 1000)
A, B2 = ms("2023-04-07"), ms("2025-08-08")
BOT_RISK = 0.035


def bot_islemleri(db):
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = c.execute("select symbol,side,entry_price,quantity,entry_time,exit_time,pnl_usdt,strategy_scores "
                     "from trades order by entry_time").fetchall()
    f = lambda s: int(pd.Timestamp(s).timestamp() * 1000)
    out = []
    for sym, side, E, q, et, xt, pnl, sc in rows:
        sl0 = float(json.loads(sc or "{}").get("sl0") or 0)
        risk = abs(E - sl0) * q
        if risk <= 0 or pnl is None:
            continue
        out.append(dict(a=f(et), z=f(xt), R=pnl / risk, notional=E * q, pnl=pnl))
    df = pd.DataFrame(out).sort_values("a").reset_index(drop=True)
    # ikizin giriş anındaki kapanmış-işlem bakiyesi (10.000'den)
    kap = df.sort_values("z")[["z", "pnl"]].to_numpy()
    df["ikiz_bakiye"] = [10_000 + kap[kap[:, 0] <= a, 1].sum() for a in df.a]
    df["teminat_oran"] = (df.notional / df.ikiz_bakiye) / 10.0
    return df[(df.a >= A) & (df.z < B2)].reset_index(drop=True)


class MotorBirlesik(Motor):
    def __init__(self, *a, bot=None, trend_kapali=False, **k):
        super().__init__(*a, **k)
        self.bot = bot
        self.bi = 0
        self.bot_acik = []          # (z, risk, teminat, R)
        self.bot_atlanan = 0
        self.bot_alinan = 0
        self.trend_kapali = trend_kapali

    def _toplam_teminat(self):
        return super()._toplam_teminat() + sum(x[2] for x in self.bot_acik)

    def _sinyal(self, *a, **k):
        if not self.trend_kapali:
            super()._sinyal(*a, **k)

    def _adim(self, t):
        T = t + H4
        deger0 = self.son_deger
        while self.bi < len(self.bot) and self.bot.a[self.bi] < T:
            r = self.bot.iloc[self.bi]
            self.bi += 1
            if r.a < t:
                continue
            tem = r.teminat_oran * deger0
            if self._toplam_teminat() + tem > 0.95 * deger0:
                self.bot_atlanan += 1
                continue
            self.bot_acik.append((int(r.z), BOT_RISK * deger0, tem, float(r.R)))
            self.bot_alinan += 1
        super()._adim(t)
        gercek = 0.0
        kalan = []
        for z, risk, tem, R in self.bot_acik:
            if z < T:
                gercek += R * risk
            else:
                kalan.append((z, risk, tem, R))
        self.bot_acik = kalan
        if gercek:
            self.cuzdan += gercek
            self.son_deger += gercek
            if self.seri and self.seri[-1][0] == T:
                s = self.seri[-1]
                self.seri[-1] = (s[0], s[1] + gercek) + tuple(s[2:])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--ikiz-db", required=True)
    a = ap.parse_args(argv)
    bot = bot_islemleri(a.ikiz_db)
    veri, _ = yukle(BOT12)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=KOK).stdout.strip()
    rid = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_birlesik_{commit[:8]}"
    out = os.path.join(KOK, "research_outputs", "trend_gelistirme", rid)
    os.makedirs(out, exist_ok=True)
    sonuc = {}
    for mal, prof in MAL.items():
        for v in ["YALNIZ_BOT", "B0", "B1", "B2", "B3"]:
            m = MotorBirlesik(veri, "ETH", "B0" if v == "YALNIZ_BOT" else v, prof, t_bas=A, t_bit=B2,
                              bot=bot, trend_kapali=(v == "YALNIZ_BOT")).kos()
            seri = pd.DataFrame(m.seri, columns=["t", "deger", "acik_poz", "acik_risk", "teminat"])
            seri.to_csv(os.path.join(out, f"hesap_degeri_{v}_{mal}.csv"), index=False)
            pd.DataFrame(m.islemler).to_csv(os.path.join(out, f"islemler_trend_{v}_{mal}.csv"), index=False)
            ay = len(pd.to_datetime(seri.t, unit="ms").dt.to_period("M").unique())
            son = seri.deger.iloc[-1] / 10_000
            sonuc[f"{v}|{mal}"] = dict(
                tumu=donem_olc(seri, A, B2), dogrulama=donem_olc(seri, ms("2024-06-14"), B2),
                aylik_geo=float((son ** (1 / ay) - 1) * 100), son_x=float(son), yillik=yillik(seri),
                bot_alinan=m.bot_alinan, bot_atlanan_teminat=m.bot_atlanan, trend_islem=len(m.islemler),
                trend_pnl=float(sum(x["pnl"] for x in m.islemler)),
                olaylar=pd.Series([o["tur"] for o in m.olaylar]).value_counts().to_dict() if m.olaylar else {})
    json.dump(dict(pencere=["2023-04-07", "2025-08-08"], bot_islem=len(bot), ozet=sonuc),
              open(os.path.join(out, "ozet.json"), "w"), indent=1, ensure_ascii=False, default=str)
    print(out)


if __name__ == "__main__":
    main()
