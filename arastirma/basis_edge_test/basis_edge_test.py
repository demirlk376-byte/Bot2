"""
basis_edge_test.py — MEXC perp–spot BASIS, Donchian kötü işlemlerini giriş anında ayırıyor mu? (Stage A)

Önceden kayıtlı TEK özellik (BASIS_EDGE_REPORT.md; sonuçtan sonra DEĞİŞMEZ):
  basis_bp  = (perp_close / spot_close − 1) × 1e4, AYNI 4h bar (sinyal barı), aynı venue (MEXC)
  basis_z   = (basis_bp − median(önceki 180 bar)) / (1.4826 × MAD(önceki 180 bar))  — mevcut bar HARİÇ
  directional_basis_z = +basis_z (long) / −basis_z (short)
  CROWDED   = directional_basis_z ≥ +1.0
Hipotez: directional_basis_z ↑ → R_net ↓ (rho < 0, delta_R = CROWDED − NORMAL < 0).

Veri:
  perp  = repodaki data/{COIN}_fut_1h.csv (canlının ikizinin verisi; ts = 1h bar AÇILIŞI) → 4h
          (UTC 00/04/..; yalnız 4 saati de olan barlar)
  spot  = MEXC SPOT {COIN}USDT 4h klines (public /api/v3/klines; openTime = bar AÇILIŞI)
  işlem = doğrulanmış canlı-birebir ikiz (ikiz_k25_cap25_islemler.csv), kol = donchian.
          Donchian girişi sinyal 4h barının KAPANIŞINDA → sinyal barı açılışı = entry_time − 4h.

Kullanım (VPS'te; spot yalnız oradan indirilebilir):
  cd /opt/bot2 && git pull
  venv/bin/python arastirma/basis_edge_test/basis_edge_test.py --indir      # spot 4h → /tmp/basis_edge_test/spot_4h
  venv/bin/python arastirma/basis_edge_test/basis_edge_test.py              # Stage A analizi
Borsaya yalnız HALKA AÇIK kline isteği; API anahtarı yok, emir yok, .env okunmaz, data/ altına yazılmaz.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COINS = ("SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB")
TWIN_CSV = os.path.join(KOK, "arastirma", "paylasim_paketi_2026-09-26", "ikiz", "ikiz_k25_cap25_islemler.csv")
SPOT_DIR = "/tmp/basis_edge_test/spot_4h"
CIKTI = "/tmp/basis_edge_test"
BAS = "2023-01-01"
BIT = "2026-07-21"
B4 = pd.Timedelta(hours=4)
PENCERE = 180                   # 30 gün × 6 bar
MIN_GECERLI = 162               # önceki 180 slotun ≥ %90'ı dolu olmalı
MIN_OLCEK_BP = 0.5              # 1.4826×MAD < 0.5bp → özellik geçersiz
ESIK = 1.0
BOLME = pd.Timestamp("2025-01-01", tz="UTC")
N_BOOT = 5000
TOHUM = 20260928
ABSURT_BP = 500.0
# kapılar
MIN_KAPSAM = 0.70
MIN_TRAIN, MIN_TEST = 100, 80
MIN_CROWDED = 30
MIN_ETKI = -0.15


# ─────────────────────────── indirme (VPS) ───────────────────────────
def indir(klasor):
    import requests
    os.makedirs(klasor, exist_ok=True)
    S = requests.Session()
    S.headers.update({"User-Agent": "bot2-basis-research/1.0"})
    rapor = {}
    for c in COINS:
        sym = f"{c}USDT"
        bas = int(pd.Timestamp(BAS, tz="UTC").timestamp() * 1000)
        bit = int(pd.Timestamp(BIT, tz="UTC").timestamp() * 1000)
        rows, cur, hata = [], bas, None
        while cur < bit:
            son = min(cur + 1000 * 4 * 3600 * 1000, bit)
            for deneme in range(4):
                try:
                    r = S.get("https://api.mexc.com/api/v3/klines",
                              params={"symbol": sym, "interval": "4h", "startTime": cur,
                                      "endTime": son, "limit": 1000}, timeout=30)
                    r.raise_for_status()
                    b = r.json()
                    break
                except Exception as e:
                    hata = str(e); b = None; time.sleep(2 ** deneme)
            if b is None:
                break
            rows += b
            cur = son
            time.sleep(0.2)
        if rows:
            d = pd.DataFrame([x[:6] for x in rows], columns=["open_time", "open", "high", "low", "close", "volume"])
            d["open_time"] = pd.to_datetime(d["open_time"].astype("int64"), unit="ms", utc=True)
            d = d.drop_duplicates("open_time").sort_values("open_time")
            d.to_csv(os.path.join(klasor, f"{c}_spot_4h.csv"), index=False)
            rapor[c] = dict(n=len(d), ilk=str(d.open_time.iloc[0]), son=str(d.open_time.iloc[-1]))
        else:
            rapor[c] = dict(n=0, hata=hata)
        print(f"  {sym}: {rapor[c]}", flush=True)
    with open(os.path.join(klasor, "indirme_raporu.json"), "w") as f:
        json.dump(rapor, f, indent=1)
    return rapor


# ─────────────────────────── veri ───────────────────────────
def perp_4h(coin):
    d = pd.read_csv(os.path.join(KOK, "data", f"{coin}_fut_1h.csv"))
    d["ts"] = pd.to_datetime(d["ts"], utc=True)
    d = d.drop_duplicates("ts").set_index("ts").sort_index()
    g = d["close"].resample("4h", label="left", closed="left")
    son, adet = g.last(), g.count()
    return son[adet == 4]                                  # yalnız tam barlar; index = 4h bar AÇILIŞI


def spot_4h(klasor, coin):
    yol = os.path.join(klasor, f"{coin}_spot_4h.csv")
    if not os.path.exists(yol):
        return None
    d = pd.read_csv(yol)
    d["open_time"] = pd.to_datetime(d["open_time"], utc=True)
    dup = int(d.duplicated("open_time").sum())
    d = d.drop_duplicates("open_time").set_index("open_time").sort_index()
    s = pd.to_numeric(d["close"], errors="coerce")
    return s[(s > 0)], dup


def basis_serisi(p, s):
    """Aynı açılış zamanına sahip 4h barlar; ffill YOK."""
    ortak = p.index.intersection(s.index)
    b = (p.loc[ortak] / s.loc[ortak] - 1) * 1e4
    return b.sort_index()


def ozellik(b, acilis):
    """Sinyal barı (açılış = acilis) için basis_z; önceki 180 IZGARA slotu (mevcut hariç)."""
    if acilis not in b.index:
        return None, "sinyal barında perp/spot yok"
    onceki_slotlar = pd.date_range(acilis - PENCERE * B4, acilis - B4, freq="4h")
    onc = b.reindex(onceki_slotlar).dropna()
    if len(onc) < MIN_GECERLI:
        return None, f"önceki 30 günde yetersiz bar ({len(onc)}/{PENCERE})"
    med = float(onc.median())
    mad = float((onc - med).abs().median())
    olcek = 1.4826 * mad
    if olcek < MIN_OLCEK_BP:
        return None, "MAD çok küçük"
    return dict(basis_bp=float(b.loc[acilis]), med=med, mad=mad,
                z=(float(b.loc[acilis]) - med) / olcek, n_onceki=len(onc),
                son_onceki=onc.index.max()), None


# ─────────────────────────── istatistik ───────────────────────────
def spearman(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 3:
        return float("nan")
    return float(np.corrcoef(pd.Series(x).rank(), pd.Series(y).rank())[0, 1])


def delta(d):
    a = d.loc[d.crowded, "R_net"]; b = d.loc[~d.crowded, "R_net"]
    return (a.mean() - b.mean()) if len(a) and len(b) else float("nan")


def hafta_boot(d):
    rng = np.random.default_rng(TOHUM)
    wk = d["entry_time"].dt.tz_convert(None).dt.to_period("W").astype(str)
    g = [x for _, x in d.groupby(wk)]
    rho, dl = [], []
    for _ in range(N_BOOT):
        o = pd.concat([g[i] for i in rng.integers(0, len(g), len(g))])
        rho.append(spearman(o.directional_basis_z, o.R_net))
        dd = delta(o)
        if np.isfinite(dd):
            dl.append(dd)
    rho, dl = np.array(rho), np.array(dl)
    return dict(hafta=len(g), rho_ort=float(np.nanmean(rho)),
                rho_ga=(float(np.nanpercentile(rho, 2.5)), float(np.nanpercentile(rho, 97.5))),
                delta_ga=(float(np.percentile(dl, 2.5)), float(np.percentile(dl, 97.5))) if len(dl) else (np.nan, np.nan))


def grup(d):
    r = d["R_net"].to_numpy()
    if len(r) == 0:
        return dict(n=0)
    c = d["exit_reason"].astype(str)
    return dict(n=len(r), ort=float(r.mean()), medyan=float(np.median(r)),
                pf=float(r[r > 0].sum() / -r[r < 0].sum()) if (r < 0).any() else float("inf"),
                wr=float((r > 0).mean() * 100), toplam=float(r.sum()),
                tp=int(c.str.contains("tp").sum()), sl=int(c.str.contains("sl").sum()),
                mh=int(c.str.contains("hold").sum()))


def theil_sen(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 3:
        return float("nan")
    i, j = np.triu_indices(len(x), 1)
    dx = x[j] - x[i]
    m = dx != 0
    return float(np.median((y[j] - y[i])[m] / dx[m]))


def split_rapor(d, ad):
    cr, no = grup(d[d.crowded]), grup(d[~d.crowded])
    bs = hafta_boot(d)
    out = dict(n=len(d), rho=spearman(d.directional_basis_z, d.R_net), slope=theil_sen(d.directional_basis_z, d.R_net),
               crowded=cr, normal=no, delta=delta(d), boot=bs)
    print(f"\n  [{ad}] n={out['n']} rho {out['rho']:+.3f} (hafta-boot ort {bs['rho_ort']:+.3f}, GA "
          f"[{bs['rho_ga'][0]:+.3f}, {bs['rho_ga'][1]:+.3f}], {bs['hafta']} hafta) · Theil-Sen eğim {out['slope']:+.4f} R/σ")
    for g_ad, g in (("CROWDED (z≥+1)", cr), ("NORMAL (z<+1)", no)):
        if g.get("n"):
            print(f"    {g_ad:<15s} n={g['n']:>3d} ort R {g['ort']:+.3f} medyan {g['medyan']:+.3f} PF {g['pf']:.2f} "
                  f"WR %{g['wr']:.1f} toplam {g['toplam']:+.1f}R TP/SL/MH {g['tp']}/{g['sl']}/{g['mh']}")
        else:
            print(f"    {g_ad:<15s} n=0")
    print(f"    delta_R {out['delta']:+.3f} · hafta-kümeli %95 GA [{bs['delta_ga'][0]:+.3f}, {bs['delta_ga'][1]:+.3f}]")
    return out


# ─────────────────────────── ana akış ───────────────────────────
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--indir", action="store_true", help="MEXC spot 4h klines'ı indir (VPS)")
    ap.add_argument("--spot-dir", default=SPOT_DIR)
    ap.add_argument("--cikti", default=CIKTI)
    a = ap.parse_args(argv)
    if a.indir:
        indir(a.spot_dir)
        return "INDIRILDI"

    tw = pd.read_csv(TWIN_CSV)
    tw = tw[tw["kol"] == "donchian"].copy()
    tw["entry_time"] = pd.to_datetime(tw["entry_time"], utc=True)
    tw["coin"] = tw["symbol"].str.split("/").str[0]
    print(f"basis_edge_test · Donchian ikiz işlemi {len(tw)} (TRAIN {int((tw.entry_time < BOLME).sum())}, "
          f"TEST {int((tw.entry_time >= BOLME).sum())})")

    # ── veri kalitesi ──
    kalite, bazlar, absurt = {}, {}, []
    for c in COINS:
        p = perp_4h(c)
        sp = spot_4h(a.spot_dir, c)
        if sp is None:
            kalite[c] = dict(spot="YOK")
            continue
        s, dup = sp
        b = basis_serisi(p, s)
        bazlar[c] = b
        sicrama = int((b.diff().abs() > 200).sum())
        ab = b[b.abs() > ABSURT_BP]
        for t, v in ab.items():
            absurt.append(dict(coin=c, bar=str(t), basis_bp=float(v), perp=float(p.get(t, np.nan)),
                               spot=float(s.get(t, np.nan))))
        kalite[c] = dict(spot_ilk=str(s.index.min()), spot_son=str(s.index.max()), spot_bar=len(s),
                         spot_dup=dup, perp_ilk=str(p.index.min()), ortak_bar=len(b),
                         basis_medyan=float(b.median()), basis_p1=float(b.quantile(0.01)),
                         basis_p99=float(b.quantile(0.99)), absurt_500=len(ab), sicrama_200=sicrama)
    print("\n== VERİ KALİTESİ (MEXC perp vs MEXC spot, USDT, 4h; zaman = bar AÇILIŞI)")
    for c, k in kalite.items():
        print(f"  {c:<5s} {k}")
    if absurt:
        print(f"  |basis| > {ABSURT_BP:.0f}bp noktaları (SİLİNMEDİ; incele):")
        for x in absurt[:40]:
            print(f"    {x}")

    # ── eşleştirme ──
    satir, eksik = [], []
    ihlal = 0
    for r in tw.itertuples():
        acilis = r.entry_time - B4
        sinyal = r.entry_time
        if r.coin not in bazlar:
            eksik.append(dict(coin=r.coin, entry=str(r.entry_time), neden="spot verisi yok")); continue
        f, neden = ozellik(bazlar[r.coin], acilis)
        if f is None:
            eksik.append(dict(coin=r.coin, entry=str(r.entry_time), neden=neden)); continue
        bilgi = acilis + B4                                  # sinyal barının kapanışı
        if not (bilgi <= sinyal <= r.entry_time) or f["son_onceki"] >= acilis:
            ihlal += 1
        yon = 1 if str(r.side).lower() == "long" else -1
        dz = yon * f["z"]
        satir.append(dict(trade_id=r.Index, symbol=r.coin, side=r.side, signal_time=sinyal,
                          entry_time=r.entry_time, perp_bar_time=acilis, spot_bar_time=acilis,
                          basis_information_time=bilgi, basis_bp=f["basis_bp"],
                          trailing_median_30d=f["med"], trailing_MAD_30d=f["mad"], basis_z=f["z"],
                          directional_basis_z=dz, crowded_1sigma=dz >= ESIK, R_net=float(r.R),
                          exit_reason=r.exit_reason, split="TRAIN" if r.entry_time < BOLME else "TEST"))
    d = pd.DataFrame(satir)
    os.makedirs(a.cikti, exist_ok=True)
    yol = os.path.join(a.cikti, "basis_trade_features.csv")
    d.to_csv(yol, index=False)
    ek = pd.DataFrame(eksik)
    ek.to_csv(os.path.join(a.cikti, "basis_missing_trades.csv"), index=False)

    n_tr = int((tw.entry_time < BOLME).sum()); n_te = int((tw.entry_time >= BOLME).sum())
    v_tr = int((d.split == "TRAIN").sum()) if len(d) else 0
    v_te = int((d.split == "TEST").sum()) if len(d) else 0
    kap_tr, kap_te = v_tr / max(n_tr, 1), v_te / max(n_te, 1)
    print(f"\n== KAPSAM: TRAIN {v_tr}/{n_tr} (%{kap_tr * 100:.1f}) · TEST {v_te}/{n_te} (%{kap_te * 100:.1f}) · "
          f"lookahead ihlali {ihlal}")
    if len(ek):
        print("  eksik işlemler (coin × neden):")
        print(ek.groupby(["coin", "neden"]).size().to_string())
        ek["yil"] = pd.to_datetime(ek["entry"]).dt.year
        print("  eksik işlemler yıla göre:", ek.groupby("yil").size().to_dict())
    print(f"  işlem düzeyi CSV: {yol}")

    kalite_ok = all(k.get("spot") != "YOK" for k in kalite.values())
    veri_yeter = kap_tr >= MIN_KAPSAM and kap_te >= MIN_KAPSAM and v_tr >= MIN_TRAIN and v_te >= MIN_TEST

    def veri_blok():
        print("\n" + "=" * 60)
        print("DATA:\n")
        print(f"spot/perp coverage TRAIN: %{kap_tr * 100:.1f}")
        print(f"spot/perp coverage TEST: %{kap_te * 100:.1f}")
        print(f"valid TRAIN: {v_tr}")
        print(f"valid TEST: {v_te}")
        print(f"data quality:\n{'PASS' if kalite_ok and not ihlal else 'FAIL'}")

    if ihlal:
        veri_blok(); print("\nHÜKÜM:\nTEST INVALID (lookahead)"); return "INVALID"
    if not (kalite_ok and veri_yeter):
        veri_blok(); print("\nHÜKÜM:\nD — DATA INSUFFICIENT"); return "D"

    d["crowded"] = d["crowded_1sigma"].astype(bool)
    d["entry_time"] = pd.to_datetime(d["entry_time"], utc=True)
    print("\n== STAGE A")
    TR = split_rapor(d[d.split == "TRAIN"], "TRAIN")
    TE = split_rapor(d[d.split == "TEST"], "TEST")
    print("\n  Betimsel (karar DEĞİL):")
    for y, g in d.groupby(d.entry_time.dt.year):
        print(f"    {y}: n={len(g)} rho {spearman(g.directional_basis_z, g.R_net):+.3f} crowded n={int(g.crowded.sum())} "
              f"delta {delta(g):+.3f}")
    for c, g in d.groupby("symbol"):
        print(f"    {c:<5s} n={len(g):>3d} ort dz {g.directional_basis_z.mean():+.2f} crowded {int(g.crowded.sum()):>3d} ort R {g.R_net.mean():+.3f}")
    for s_, g in d.groupby("side"):
        print(f"    {s_:<5s} n={len(g):>3d} ort dz {g.directional_basis_z.mean():+.2f} crowded {int(g.crowded.sum()):>3d} ort R {g.R_net.mean():+.3f}")

    k = {1: TR["rho"] < 0, 2: TE["rho"] < 0, 3: TE["boot"]["rho_ort"] < 0,
         4: TR["delta"] < 0, 5: TE["delta"] < 0,
         6: TE["crowded"].get("n", 0) >= MIN_CROWDED, 7: TR["crowded"].get("n", 0) >= MIN_CROWDED,
         8: TR["delta"] <= MIN_ETKI and TE["delta"] <= MIN_ETKI, 9: TE["boot"]["delta_ga"][1] < 0}
    gecti = all(k.values())
    with open(os.path.join(a.cikti, "stage_a.json"), "w") as f:
        json.dump(dict(kalite=kalite, kapsam=[kap_tr, kap_te, v_tr, v_te], TRAIN=TR, TEST=TE,
                       kriter={str(i): bool(v) for i, v in k.items()}, gecti=gecti), f, indent=1, default=str)

    veri_blok()
    print("\nSTAGE A:\n")
    for ad, S in (("TRAIN", TR), ("TEST", TE)):
        print(f"{ad}:")
        print(f"rho: {S['rho']:+.3f}")
        print(f"crowded n: {S['crowded'].get('n', 0)}")
        print(f"crowded mean R: {S['crowded'].get('ort', float('nan')):+.3f}")
        print(f"normal mean R: {S['normal'].get('ort', float('nan')):+.3f}")
        print(f"delta R: {S['delta']:+.3f}")
        if ad == "TEST":
            print(f"week-cluster 95% CI: [{S['boot']['delta_ga'][0]:+.3f}, {S['boot']['delta_ga'][1]:+.3f}]")
        print()
    print(f"kriterler: {k}")
    print(f"\nSTAGE A:\n{'PASS' if gecti else 'FAIL'}")
    if not gecti:
        print("\nHÜKÜM:\nBASIS EDGE YOK / KANIT YETERSİZ")
        return "FAIL"
    print("\n→ Stage B (BASIS_CROWDING_HALF_RISK ikiz replay) gerekli: basis_trade_features.csv ve spot_4h/ "
          "klasörünü araştırma ortamına getir.")
    return "PASS"


if __name__ == "__main__":
    main()
