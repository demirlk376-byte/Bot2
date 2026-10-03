"""B0–B3 koşucusu: `PYTHONPATH=. python3 -m research.trend_gelistirme.kos [--evren bot12|diger24]`
Çıktı: research_outputs/trend_gelistirme/<run_id>/ (işlem kayıtları, hesap değeri serileri, özet JSON)."""
from __future__ import annotations

import argparse, json, os, subprocess
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from research.liquidity_sweep_v1 import config as C
from research.trend_gelistirme.motor import Motor, DAY
from research.trend_gelistirme.veri import yukle, hashler, BOT12, KOK
from research.trend_takip_v1 import run_v5 as V5

ms = lambda s: int(pd.Timestamp(s, tz="UTC").timestamp() * 1000)
T0, B1, B2 = ms("2021-01-01"), ms("2024-06-14"), ms("2025-08-08")
DONEM = {"KESIF": (T0, B1), "DOGRULAMA": (B1, B2), "TUMU": (T0, B2)}
VARY = ["B0", "B1", "B2", "B3"]
MAL = {"NORMAL": C.TWIN_MARKET_PROFILE, "STRESS": C.TWIN_MARKET_PROFILE.stress()}


def donem_olc(seri: pd.DataFrame, a, b):
    s = seri[(seri.t > a) & (seri.t <= b)]
    if s.empty:
        return {}
    bas = seri[seri.t <= a].deger.iloc[-1] if (seri.t <= a).any() else 10_000.0
    v = np.r_[bas, s.deger.to_numpy()]
    tepe = np.maximum.accumulate(v)
    mdd = float(((tepe - v) / tepe).max() * 100)
    ret = float((v[-1] / bas - 1) * 100)
    return dict(getiri=ret, mdd=mdd, oran=ret / mdd if mdd > 0 else float("inf"))


def yillik(seri):
    s = seri.set_index(pd.to_datetime(seri.t, unit="ms")).deger
    y = s.groupby(s.index.year).last()
    onceki = y.shift(1).fillna(10_000.0)
    return {int(k): round(float(v), 1) for k, v in ((y / onceki - 1) * 100).items()}


def kos_hepsi(evren):
    coinler = BOT12 if evren == "bot12" else V5.COINS
    veri, dis = yukle(sorted(set(coinler) | {"ETH"}))
    sonuc = {}
    for mal, prof in MAL.items():
        for v in VARY:
            m = Motor(veri, "ETH", v, prof, t_bas=T0, t_bit=B2)
            if "ETH" not in coinler:          # ETH yalnız rejim için; işlem evrenine katılmaz
                m.coins = {k: c for k, c in veri.items() if k != "ETH"}
            m.kos()
            sonuc[(v, mal)] = m
    return sonuc, veri, dis


def eslestir(a: pd.DataFrame, b: pd.DataFrame):
    return a.merge(b, on=["coin", "giris_t"], how="outer", suffixes=("_b0", "_v"))


def rapor_verisi(sonuc, evren):
    ozet = {}
    for (v, mal), m in sonuc.items():
        seri = pd.DataFrame(m.seri, columns=["t", "deger", "acik_poz", "acik_risk", "teminat"])
        tr = pd.DataFrame(m.islemler)
        d = {k: donem_olc(seri, *ab) for k, ab in DONEM.items()}
        for k, (a, b) in DONEM.items():
            tt = tr[(tr.cikis_t > a) & (tr.cikis_t <= b)] if len(tr) else tr
            d[k].update(islem=int(len(tt)), net=float(tt.pnl.sum()) if len(tt) else 0.0,
                        ilk=float(tt.pnl_ilk.sum()) if len(tt) else 0.0, ek1=float(tt.pnl_ek1.sum()) if len(tt) else 0.0,
                        ek2=float(tt.pnl_ek2.sum()) if len(tt) else 0.0,
                        geri_verilen=float((tt.tepe_acik - tt.pnl).clip(lower=0).sum()) if len(tt) else 0.0)
        d["yillik"] = yillik(seri)
        d["olaylar"] = pd.Series([o["tur"] for o in m.olaylar]).value_counts().to_dict() if m.olaylar else {}
        ozet[f"{v}|{mal}"] = d
    # varyanta özgü teşhisler (NORMAL)
    b0 = pd.DataFrame(sonuc[("B0", "NORMAL")].islemler)
    ek = {}
    top = b0.nlargest(10, "pnl")[["coin", "giris_t", "pnl"]]
    for v in VARY[1:]:
        tv = pd.DataFrame(sonuc[(v, "NORMAL")].islemler)
        e = eslestir(b0, tv)
        tt = top.merge(tv[["coin", "giris_t", "pnl"]], on=["coin", "giris_t"], how="left", suffixes=("_b0", "_v"))
        bilgi = {"en_buyuk10_b0": float(tt.pnl_b0.sum()), "en_buyuk10_varyant": float(tt.pnl_v.fillna(0).sum()),
                 "en_buyuk10_eslesen": int(tt.pnl_v.notna().sum())}
        if v == "B1":
            dv = tv[tv.devir_t.notna()]
            m = dv.merge(b0[["coin", "giris_t", "pnl", "cikis_t", "tepe_acik"]], on=["coin", "giris_t"], how="left",
                         suffixes=("", "_b0"))
            bilgi.update(devir=int(len(dv)), devir_pnl=float(dv.pnl.sum()), devir_pnl_b0=float(m.pnl_b0.sum()),
                         devir_fark=float((m.pnl - m.pnl_b0).sum()), devir_eslesen=int(m.pnl_b0.notna().sum()),
                         devir_kazanan_iyilesen=int(((m.pnl - m.pnl_b0) > 0).sum()),
                         devir_kotulesen=int(((m.pnl - m.pnl_b0) < 0).sum()),
                         devir_gun_ort=float(dv.gun.mean()) if len(dv) else 0.0,
                         devir_gun_ort_b0=float(((m.cikis_t_b0 - m.giris_t) / DAY).mean()) if len(m) else 0.0)
        if v == "B2":
            aff = tv[tv.ek_engel > 0]
            m = aff.merge(b0[["coin", "giris_t", "pnl", "pnl_ek1", "pnl_ek2"]], on=["coin", "giris_t"], how="left",
                          suffixes=("", "_b0"))
            bilgi.update(engellenen_ek=int(aff.ek_engel.sum()), etkilenen_islem=int(len(aff)),
                         b0_ek_katki=float((m.pnl_ek1_b0.fillna(0) + m.pnl_ek2_b0.fillna(0)).sum()),
                         etkilenen_fark=float((m.pnl - m.pnl_b0).sum()),
                         b0_buyuk_kazanan_etkilenen=int((m.pnl_b0 > 5 * m.ilk_risk).sum()))
        if v == "B3":
            ex = tv[tv.neden == "B3_BASARISIZ_KIRILIM"]
            m = ex.merge(b0[["coin", "giris_t", "pnl", "neden"]], on=["coin", "giris_t"], how="left", suffixes=("", "_b0"))
            bilgi.update(b3_cikis=int(len(ex)), b3_pnl=float(ex.pnl.sum()), b3_pnl_b0=float(m.pnl_b0.sum()),
                         b0da_kazanan=int((m.pnl_b0 > 0).sum()), b0da_kaybeden=int((m.pnl_b0 <= 0).sum()),
                         b0da_kazanan_toplam=float(m.loc[m.pnl_b0 > 0, "pnl_b0"].sum()),
                         b0da_kaybeden_toplam=float(m.loc[m.pnl_b0 <= 0, "pnl_b0"].sum()))
        # eşleşen işlemlerde fark için basit önyükleme (belirsizlik)
        f = (e.pnl_v.fillna(0) - e.pnl_b0.fillna(0)).to_numpy()
        f = f[np.abs(f) > 1e-9]
        if len(f):
            rng = np.random.default_rng(20261004)
            bs = [rng.choice(f, len(f)).sum() for _ in range(5000)]
            bilgi.update(fark_islem=int(len(f)), fark_toplam=float(f.sum()),
                         fark_ci95=[float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))])
        ek[v] = bilgi
    return ozet, ek


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--evren", default="bot12", choices=["bot12", "diger24"])
    a = ap.parse_args(argv)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=KOK).stdout.strip()
    rid = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{a.evren}_{commit[:8]}"
    out = os.path.join(KOK, "research_outputs", "trend_gelistirme", rid)
    os.makedirs(out, exist_ok=True)
    sonuc, veri, dis = kos_hepsi(a.evren)
    for (v, mal), m in sonuc.items():
        pd.DataFrame(m.islemler).to_csv(os.path.join(out, f"islemler_{v}_{mal}.csv"), index=False)
        pd.DataFrame(m.seri, columns=["t", "deger", "acik_poz", "acik_risk", "teminat"]).to_csv(
            os.path.join(out, f"hesap_degeri_{v}_{mal}.csv"), index=False)
    ozet, ek = rapor_verisi(sonuc, a.evren)
    manif = dict(run_id=rid, commit=commit, evren=a.evren, coinler=sorted(k for k in sonuc[("B0", "NORMAL")].coins),
                 donemler={k: [str(pd.to_datetime(x, unit="ms").date()) for x in v] for k, v in DONEM.items()},
                 sermaye=10_000, risk=0.01, acik_risk_tavani=0.24, notional_cap=2.5, kaldirac=10,
                 maliyet={k: v.as_dict() for k, v in MAL.items()}, veri_hash=hashler(sorted(veri)), dislanan=dis)
    json.dump(dict(manifest=manif, ozet=ozet, varyant_teshis=ek), open(os.path.join(out, "ozet.json"), "w"),
              indent=1, ensure_ascii=False, default=str)
    print(out)


if __name__ == "__main__":
    main()
