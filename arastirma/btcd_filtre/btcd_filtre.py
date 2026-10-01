"""
btcd_filtre.py — BTC dominans filtresi, AŞAMA 1 (kurallar: MANIFEST.md, sonuçlardan önce).

Adımlar:
  indir  : Binance USDⓈ-M BTCDOMUSDT 1h mumlarını indirir (data.binance.vision aylık/günlük
           zip; eksik kalanlar için fapi/v1/klines). ÇIKTI klasörüne yazar; data/'ya DOKUNMAZ.
  asama1 : 936 referans işleme giriş anındaki dominans rejimini atar, önceden kayıtlı
           istatistikleri ve geçiş kapısını hesaplar.

VPS (salt okur; emir yok, bota dokunmaz, .env okunmaz):
  cd /opt/bot2 && git pull
  venv/bin/python arastirma/btcd_filtre/btcd_filtre.py indir  --cikti /tmp/btcd
  venv/bin/python arastirma/btcd_filtre/btcd_filtre.py asama1 --cikti /tmp/btcd
Yerel kuru deneme (repo kökündeki 13 aylık 4h dosyalarla; kapsam yetersiz olur):
  python3 arastirma/btcd_filtre/btcd_filtre.py asama1 --cikti /tmp/btcd_yerel --btcd-glob 'BTCDOMUSDT-4h-*.csv'
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import math
import os
import sys
import time
import zipfile

import numpy as np
import pandas as pd

BURA = os.path.dirname(os.path.abspath(__file__))
KOK = os.path.dirname(os.path.dirname(BURA))
REF = os.path.join(KOK, "arastirma", "paylasim_paketi_2026-09-26", "ikiz", "ikiz_k25_cap25_islemler.csv")
SEED = 20261001
BOOT = 5000
YARI_SINIR = pd.Timestamp("2024-12-01", tz="UTC")
BAYAT = pd.Timedelta(hours=2)
BANT = 0.02
PLASEBO_N = 200

# ───────────────────────────── veri ──────────────────────────────────────────
VISION = "https://data.binance.vision/data/futures/um"
FAPI = "https://fapi.binance.com/fapi/v1/klines"


def _zip_csv(icerik: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(icerik)) as z:
        ham = z.read(z.namelist()[0]).decode()
    ilk = ham.split("\n", 1)[0]
    basliksiz = ilk.split(",")[0].strip().isdigit()
    d = pd.read_csv(io.StringIO(ham), header=None if basliksiz else 0)
    d = d.iloc[:, :5]
    d.columns = ["open_time", "open", "high", "low", "close"]
    return d


def _ms(seri: pd.Series) -> pd.Series:
    s = seri.astype("int64")
    return s.where(s < 10**14, s // 1000)        # µs → ms (yeni dosyalar µs olabilir)


def indir(a):
    import requests
    os.makedirs(a.cikti, exist_ok=True)
    ses = requests.Session()
    ses.headers.update({"User-Agent": "bot2-btcd/1.0"})
    bas = pd.Timestamp(a.bas, tz="UTC")
    simdi = pd.Timestamp.now(tz="UTC")
    parcalar, kaynak = [], []

    def gunluk(gun):
        r = ses.get(f"{VISION}/daily/klines/BTCDOMUSDT/1h/BTCDOMUSDT-1h-{gun.date()}.zip", timeout=60)
        if r.status_code == 200:
            parcalar.append(_zip_csv(r.content))
            kaynak.append((str(gun.date()), "vision-gunluk"))
        time.sleep(0.05)

    ay, bu_ay = bas.tz_localize(None).to_period("M"), simdi.tz_localize(None).to_period("M")
    while ay < bu_ay:                                   # tamamlanmış aylar: aylık zip, yoksa günlük
        r = ses.get(f"{VISION}/monthly/klines/BTCDOMUSDT/1h/BTCDOMUSDT-1h-{ay}.zip", timeout=60)
        if r.status_code == 200:
            parcalar.append(_zip_csv(r.content))
            kaynak.append((str(ay), "vision-aylik"))
        else:
            kaynak.append((str(ay), f"vision-aylik YOK ({r.status_code}) → günlük"))
            for gun in pd.date_range(ay.start_time, ay.end_time.floor("D"), freq="D", tz="UTC"):
                gunluk(gun)
        ay += 1
        time.sleep(0.1)
    for gun in pd.date_range(bu_ay.start_time, (simdi.floor("D") - pd.Timedelta(days=1)).tz_localize(None),
                             freq="D", tz="UTC"):
        gunluk(gun)
    d = pd.concat(parcalar, ignore_index=True) if parcalar else pd.DataFrame(
        columns=["open_time", "open", "high", "low", "close"])
    d["open_time"] = _ms(d["open_time"])
    # boşluklar ve son saatler → fapi ile tamamla
    beklenen = pd.date_range(bas, simdi.floor("h") - pd.Timedelta(hours=1), freq="h", tz="UTC")
    mevcut = set(pd.to_datetime(d["open_time"], unit="ms", utc=True))
    eksik = [t for t in beklenen if t not in mevcut]
    if eksik:
        ek, cur, son = [], int(min(eksik).timestamp() * 1000), int(simdi.timestamp() * 1000)
        while cur < son:
            try:
                r = ses.get(FAPI, params={"symbol": "BTCDOMUSDT", "interval": "1h",
                                          "startTime": cur, "limit": 1500}, timeout=30)
                r.raise_for_status()
                k = r.json()
            except Exception as e:
                kaynak.append(("fapi", f"HATA {e}"))
                break
            if not k:
                break
            ek += [row[:5] for row in k]
            cur = int(k[-1][0]) + 3_600_000
            time.sleep(0.2)
        if ek:
            e = pd.DataFrame(ek, columns=["open_time", "open", "high", "low", "close"])
            d = pd.concat([d, e], ignore_index=True)
            kaynak.append(("fapi", f"{len(ek)} mum"))
    d["open_time"] = _ms(d["open_time"])
    d = d.astype({"open": float, "high": float, "low": float, "close": float})
    d = d.drop_duplicates("open_time").sort_values("open_time")
    t = pd.to_datetime(d["open_time"], unit="ms", utc=True)
    d = d[t + pd.Timedelta(hours=1) <= simdi]                    # oluşmakta olan mumu at
    d.to_csv(os.path.join(a.cikti, "btcdom_1h.csv"), index=False)
    t = pd.to_datetime(d["open_time"], unit="ms", utc=True)
    bosluk = t.diff()
    ozet = dict(mum=len(d), ilk=str(t.min()), son=str(t.max()),
                bosluk_1sa_ustu=int((bosluk > pd.Timedelta(hours=1)).sum()),
                en_buyuk_bosluk=str(bosluk.max()), kapanis_min=float(d["close"].min()),
                kapanis_max=float(d["close"].max()),
                kaynak_ozet={k: sum(1 for _, x in kaynak if x.startswith(k))
                             for k in ("vision-aylik", "vision-gunluk", "fapi")},
                eksik_aylar=[a_ for a_, x in kaynak if "YOK" in x])
    with open(os.path.join(a.cikti, "btcdom_indirme.json"), "w") as f:
        json.dump(ozet, f, indent=1)
    print(json.dumps(ozet, indent=1, ensure_ascii=False))


def btcd_yukle(yol=None, desen=None) -> pd.Series:
    """Kapanış zamanına göre indeksli dominans serisi (interval verinin kendisinden)."""
    if desen:
        dosyalar = sorted(glob.glob(os.path.join(KOK, desen)))
        d = pd.concat([pd.read_csv(f).iloc[:, :5] for f in dosyalar], ignore_index=True)
        d.columns = ["open_time", "open", "high", "low", "close"]
    else:
        d = pd.read_csv(yol)
    d["open_time"] = _ms(d["open_time"])
    d = d.drop_duplicates("open_time").sort_values("open_time")
    acilis = pd.to_datetime(d["open_time"], unit="ms", utc=True)
    adim = acilis.diff().median()
    kapanis = acilis + adim
    return pd.Series(d["close"].astype(float).to_numpy(), index=kapanis)


def deger(seri: pd.Series, t: pd.Series) -> np.ndarray:
    """Her t için kapanışı ≤ t olan son değer; 2 saatten bayatsa NaN."""
    idx = pd.DatetimeIndex(seri.index).as_unit("ns").asi8
    tv = pd.DatetimeIndex(t).as_unit("ns").asi8
    k = np.searchsorted(idx, tv, side="right") - 1
    out = np.full(len(tv), np.nan)
    ok = k >= 0
    kk = k[ok]
    yas = tv[ok] - idx[kk]
    v = np.asarray(seri.values, dtype=float)[kk]
    v[yas > BAYAT.value] = np.nan
    out[ok] = v
    return out


# ───────────────────────────── aşama 1 ───────────────────────────────────────
def islemler(yol=REF) -> pd.DataFrame:
    d = pd.read_csv(yol)
    d["giris"] = pd.to_datetime(d["entry_time"], utc=True, format="mixed")
    sc = d["strategy_scores"].apply(json.loads)
    d["kol"] = sc.apply(lambda x: x.get("strategy", "mean_rev"))
    d["sl0"] = [float(x.get("sl0") or s) for x, s in zip(sc, d["sl_price"])]
    risk = (d["entry_price"] - d["sl0"]).abs() * d["quantity"]
    d["net_R"] = d["pnl_usdt"] / risk.where(risk > 0)
    d["yon"] = d["side"].map({"long": 1, "short": -1})
    d["hafta"] = d["giris"].dt.tz_localize(None).dt.to_period("W").astype(str)
    return d


def etiketle(d: pd.DataFrame, seri: pd.Series, kaydir=pd.Timedelta(0)) -> pd.DataFrame:
    t = d["giris"] - kaydir
    d0 = deger(seri, t)
    d7 = np.log(d0 / deger(seri, t - pd.Timedelta(hours=168)))
    d3 = np.log(d0 / deger(seri, t - pd.Timedelta(hours=72)))
    out = d.copy()
    out["d7"], out["d3"] = d7, d3
    y = out["yon"].to_numpy()
    out["F1"] = ((y == 1) & (d7 > 0)) | ((y == -1) & (d7 < 0))
    out["F2"] = ((y == 1) & (d7 > BANT)) | ((y == -1) & (d7 < -BANT))
    out["F3"] = ((y == 1) & (d3 > 0)) | ((y == -1) & (d3 < 0))
    out["kapsamda"] = np.isfinite(d7) & np.isfinite(d3)
    return out


def boot(x, hafta, seed=SEED, n=BOOT):
    df = pd.DataFrame({"x": x, "w": hafta}).dropna()
    if len(df) < 5:
        return [float("nan"), float("nan")]
    gr = [g["x"].to_numpy() for _, g in df.groupby("w")]
    rng = np.random.default_rng(seed)
    m = len(gr)
    ort = np.array([np.concatenate([gr[i] for i in rng.integers(0, m, m)]).mean() for _ in range(n)])
    return [float(np.percentile(ort, 2.5)), float(np.percentile(ort, 97.5))]


def grup(d, maske):
    x = d.loc[maske, "net_R"]
    return dict(n=int(maske.sum()), ort_R=float(x.mean()) if len(x) else float("nan"),
                toplam_R=float(x.sum()), kazanma=float((x > 0).mean()) if len(x) else float("nan"))


def plasebo(d, seri, gercek):
    span = seri.index.max() - seri.index.min()
    if span < pd.Timedelta(days=120):
        return dict(durum="seri plasebo için kısa")
    lo, hi = pd.Timedelta(days=30), span - pd.Timedelta(days=30)
    kaydirmalar = [lo + (hi - lo) * i / (PLASEBO_N - 1) for i in range(PLASEBO_N)]
    # dairesel kaydırma: seriyi kendi süresi kadar ileri/geri kopyalayarak sar
    sar = pd.concat([pd.Series(seri.values, index=seri.index - span - pd.Timedelta(hours=1)), seri])
    sar = sar[~sar.index.duplicated()].sort_index()
    ortlar = []
    for s in kaydirmalar:
        e = etiketle(d, sar, kaydir=s)
        m = e["kapsamda"] & e["F1"]
        ortlar.append(float(e.loc[m, "net_R"].mean()))
    ortlar = np.array(ortlar)
    return dict(kaydirma=PLASEBO_N, gercek=gercek,
                yuzdelik=float((ortlar <= gercek).mean() * 100),
                plasebo_ort=float(np.nanmean(ortlar)), plasebo_p05=float(np.nanpercentile(ortlar, 5)),
                plasebo_p95=float(np.nanpercentile(ortlar, 95)))


def asama1(a):
    os.makedirs(a.cikti, exist_ok=True)
    seri = btcd_yukle(desen=a.btcd_glob) if a.btcd_glob else btcd_yukle(os.path.join(a.cikti, "btcdom_1h.csv"))
    d = etiketle(islemler(a.islemler), seri)
    kap = d["kapsamda"]
    k = d[kap]
    s = dict(veri=dict(ilk=str(seri.index.min()), son=str(seri.index.max()), mum=len(seri)),
             islem=len(d), kapsamda=int(kap.sum()), kapsam_yuzde=float(kap.mean() * 100),
             taban=grup(k, pd.Series(True, index=k.index)))
    for f in ("F1", "F2", "F3"):
        m = k[f]
        s[f] = dict(engellenen=grup(k, m), kalan=grup(k, ~m),
                    engellenen_pay=float(m.mean() * 100),
                    engellenen_GA95=boot(k.loc[m, "net_R"], k.loc[m, "hafta"]),
                    kalan_GA95=boot(k.loc[~m, "net_R"], k.loc[~m, "hafta"]))
    m1 = k["F1"]
    s["F1_kirilim"] = {
        "kol": {kol: dict(engellenen=grup(k, m1 & (k["kol"] == kol)), kalan=grup(k, ~m1 & (k["kol"] == kol)))
                for kol in sorted(k["kol"].unique())},
        "yon": {ad: dict(engellenen=grup(k, m1 & (k["yon"] == y)), kalan=grup(k, ~m1 & (k["yon"] == y)))
                for ad, y in (("long", 1), ("short", -1))},
        "yari": {ad: dict(engellenen=grup(k, m1 & msk), kalan=grup(k, ~m1 & msk))
                 for ad, msk in (("1_ilk", k["giris"] < YARI_SINIR), ("2_son", k["giris"] >= YARI_SINIR))},
    }
    # betimsel: dominans "arka rüzgârı" (−yön×d7) ile net R sıra korelasyonu (karar dışı)
    s["betimsel_spearman_ruzgar_R"] = float(pd.Series(-k["yon"] * k["d7"]).rank().corr(k["net_R"].rank()))
    gercek = s["F1"]["engellenen"]["ort_R"]
    s["plasebo_F1"] = plasebo(d, seri, gercek)
    p = s["plasebo_F1"]
    yari = s["F1_kirilim"]["yari"]
    kapi = {
        "a_kapsam>=95": s["kapsam_yuzde"] >= 95,
        "b_F1_engellenen_ort<0_ve_GA_ust<0": gercek < 0 and s["F1"]["engellenen_GA95"][1] < 0,
        "c_iki_yarida_engellenen<0": all(yari[x]["engellenen"]["n"] > 0 and
                                         yari[x]["engellenen"]["ort_R"] < 0 for x in yari),
        "d_F2_ve_F3_engellenen<0": s["F2"]["engellenen"]["ort_R"] < 0 and s["F3"]["engellenen"]["ort_R"] < 0,
        "e_plasebo_yuzdelik<=5": isinstance(p.get("yuzdelik"), float) and p["yuzdelik"] <= 5,
    }
    s["kapi"] = kapi
    if not kapi["a_kapsam>=95"]:
        s["HUKUM"] = "KANIT YETERSİZ (dominans verisi işlemlerin %95'ini kapsamıyor)"
    elif all(kapi.values()):
        s["HUKUM"] = "AŞAMA 1 GEÇTİ → Aşama 2 (ikiz portföy testi)"
    else:
        s["HUKUM"] = "REDDEDİLDİ (Aşama 1 kapısı geçilemedi)"
    d.to_csv(os.path.join(a.cikti, "islemler_etiketli.csv"), index=False)
    with open(os.path.join(a.cikti, "asama1_sonuc.json"), "w") as f:
        json.dump(s, f, indent=1, ensure_ascii=False, default=str)
    yaz(s)


def yaz(s):
    r = lambda x: "—" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x:+.3f}"
    print(f"\nBTC DOMİNANS FİLTRESİ — AŞAMA 1   veri {s['veri']['ilk'][:10]} → {s['veri']['son'][:10]}")
    print(f"işlem {s['islem']}, kapsamda {s['kapsamda']} (%{s['kapsam_yuzde']:.1f})   "
          f"taban ort R {r(s['taban']['ort_R'])} (toplam {s['taban']['toplam_R']:+.1f}R)")
    for f in ("F1", "F2", "F3"):
        x = s[f]
        e, k = x["engellenen"], x["kalan"]
        print(f"  {f}: engellenen {e['n']:4d} (%{x['engellenen_pay']:.0f})  ort R {r(e['ort_R'])} "
              f"GA[{r(x['engellenen_GA95'][0])},{r(x['engellenen_GA95'][1])}] toplam {e['toplam_R']:+.1f}R"
              f"  |  kalan {k['n']:4d} ort R {r(k['ort_R'])} toplam {k['toplam_R']:+.1f}R")
    for b in ("kol", "yon", "yari"):
        for ad, v in s["F1_kirilim"][b].items():
            print(f"    F1 {b:4s} {ad:9s} engellenen n={v['engellenen']['n']:3d} ort {r(v['engellenen']['ort_R'])}"
                  f" | kalan n={v['kalan']['n']:3d} ort {r(v['kalan']['ort_R'])}")
    p = s["plasebo_F1"]
    if "yuzdelik" in p:
        print(f"  plasebo (200 kaydırma): gerçek {r(p['gercek'])}, yüzdelik %{p['yuzdelik']:.1f}, "
              f"plasebo %5–%95 [{r(p['plasebo_p05'])}, {r(p['plasebo_p95'])}]")
    else:
        print(f"  plasebo: {p.get('durum')}")
    for k_, v in s["kapi"].items():
        print(f"  kapı {k_}: {'✓' if v else '✗'}")
    print(f"HÜKÜM: {s['HUKUM']}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("adim", choices=["indir", "asama1"])
    p.add_argument("--cikti", default="/tmp/btcd")
    p.add_argument("--bas", default="2023-03-01")
    p.add_argument("--islemler", default=REF)
    p.add_argument("--btcd-glob", default=None, help="yerel deneme: repo kökünde BTCDOMUSDT-4h-*.csv")
    a = p.parse_args()
    a.cikti = os.path.abspath(a.cikti)
    {"indir": indir, "asama1": asama1}[a.adim](a)


if __name__ == "__main__":
    main()
