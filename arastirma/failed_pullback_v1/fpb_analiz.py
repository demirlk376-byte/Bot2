"""
fpb_analiz.py — FAILED_PULLBACK_V1 koşularının analizi (yalnız koşu çıktılarını okur).

Kullanım: python3 fpb_analiz.py <kosu_dizini>
  Dizinde {AD}_islemler.csv, {AD}_aday_sinyaller.csv, {AD}_ozsermaye.csv.gz,
  {AD}_ozet.json dosyaları beklenir (AD: A, A75, B, S, A_2x, A75_2x, B_2x, S_2x,
  S_cikis, A_f, A75_f, B_f). Eksik koşu atlanır ve rapora "koşulmadı" yazılır.
Çıktı (bu klasöre): sonuclar.json, karsilastirma.csv, aday_islemler_{B,S}.csv,
  aday_engellenen_{B,S}.csv, aday_kirilim_*.csv, a_negatif_haftalar.csv,
  a_dusus_donemleri.csv, ozsermaye_saatlik_{A,A75,B}.csv.gz
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np
import pandas as pd

BURA = os.path.dirname(os.path.abspath(__file__))
SEED = 20260930
BOOT = 5000
FEE = 0.0001
TABAN_GIRIS_BP, TABAN_CIKIS_BP = 15.85, 0.24


# ───────────────────────── küçük yardımcılar (testli) ─────────────────────────
def ayni_mum_belirsiz(side: str, S: float, T: float, high: float, low: float) -> bool:
    """Aynı mum hem stopa hem hedefe değdi mi (sıra bilinmez → stop varsayıldı)."""
    if side == "long":
        return low <= S and high >= T
    return high >= S and low <= T


def r0_usdt(e_fill: float, stop0: float, miktar: float) -> float:
    return abs(e_fill - stop0) * miktar


def net_r(pnl: float, e_fill: float, stop0: float, miktar: float) -> float:
    r0 = r0_usdt(e_fill, stop0, miktar)
    return pnl / r0 if r0 > 0 else float("nan")


def pf(x) -> float:
    x = np.asarray(x, dtype=float)
    k, z = x[x > 0].sum(), -x[x < 0].sum()
    return float(k / z) if z > 0 else float("inf")


def hafta_boot(degerler, haftalar, seed=SEED, n=BOOT):
    """Hafta-kümeli bootstrap: ortalamanın %95 GA'sı."""
    d = pd.DataFrame({"x": degerler, "w": haftalar}).dropna()
    if len(d) < 2:
        return (float("nan"), float("nan"))
    gr = [g["x"].to_numpy() for _, g in d.groupby("w")]
    rng = np.random.default_rng(seed)
    m = len(gr)
    ort = np.empty(n)
    for b in range(n):
        sec = rng.integers(0, m, m)
        v = np.concatenate([gr[i] for i in sec])
        ort[b] = v.mean()
    return (float(np.percentile(ort, 2.5)), float(np.percentile(ort, 97.5)))


# ───────────────────────── koşu okuma ────────────────────────────────────────
def oku(dizin, ad):
    y = lambda s: os.path.join(dizin, f"{ad}_{s}")
    if not os.path.exists(y("ozet.json")):
        return None
    with open(y("ozet.json")) as f:
        ozet = json.load(f)
    isl = pd.read_csv(y("islemler.csv"))
    sin = pd.read_csv(y("aday_sinyaller.csv")) if os.path.exists(y("aday_sinyaller.csv")) else pd.DataFrame()
    ozs = pd.read_csv(y("ozsermaye.csv.gz"))
    ozs["t"] = pd.to_datetime(ozs["kapanis_ms"], unit="ms", utc=True)
    for c in ("entry_time", "exit_time"):
        isl[c] = pd.to_datetime(isl[c], utc=True, format="mixed")
    isl["sc"] = isl["strategy_scores"].apply(lambda s: json.loads(s) if isinstance(s, str) else {})
    isl["strateji"] = isl["sc"].apply(lambda d: d.get("strategy", "mean_rev"))
    return dict(ad=ad, ozet=ozet, isl=isl, sin=sin, ozs=ozs)


def maliyetler(k):
    """Komisyon, kayma, funding (USDT) — işlem başına; toplamlar koşu için."""
    isl, ay = k["isl"], k["ozet"]["ayar"]
    g_bp, c_bp = float(ay["slip_giris"]), float(ay["slip_cikis"])
    aday_c = ay.get("ADAY_CIKIS_SLIP_BP")
    kom, gk, ck = [], [], []
    for _, r in isl.iterrows():
        sc = r["sc"]
        q = float(r["quantity"])
        efr = float(sc.get("entry_fee_rate", FEE))
        kom.append(r["entry_price"] * q * efr + r["exit_price"] * q * FEE)
        ie = float(sc.get("intended_entry", r["entry_price"]) or r["entry_price"])
        gk.append(abs(r["entry_price"] - ie) * q if efr > 0 else 0.0)
        bp = float(aday_c) if (aday_c not in (None, "None") and bool(r.get("aday"))) else c_bp
        ck.append(0.0 if r["exit_reason"] == "tp_hit" else r["exit_price"] * q * bp / 1e4)
    isl["komisyon"] = kom
    isl["kayma_giris"] = gk
    isl["kayma_cikis"] = ck
    isl["funding"] = isl["fees_usdt"] - isl["komisyon"]
    return isl


def ozsermaye_metrik(ozs, bas=10_000.0):
    e = ozs["ozsermaye"].to_numpy()
    tepe = np.maximum.accumulate(np.concatenate([[bas], e]))[1:]
    dd = (tepe - e) / tepe
    i = int(np.argmax(dd))
    # en uzun sualtı süresi (saat): tepe → tepeye geri dönüş
    alti = e < tepe * (1 - 1e-12)
    en_uzun = cur = 0
    for a in alti:
        cur = cur + 1 if a else 0
        en_uzun = max(en_uzun, cur)
    return dict(max_dd_pct=float(dd.max() * 100), max_dd_zaman=str(ozs["t"].iat[i]),
                sualti_en_uzun_gun=en_uzun / 24.0,
                acik_risk_ort_pct=float((ozs["acik_risk_stopa"] / ozs["ozsermaye"]).mean() * 100),
                acik_risk_max_pct=float((ozs["acik_risk_stopa"] / ozs["ozsermaye"]).max() * 100),
                marjin_ort_pct=float((ozs["marjin"] / ozs["ozsermaye"]).mean() * 100),
                marjin_max_pct=float((ozs["marjin"] / ozs["ozsermaye"]).max() * 100))


def kosu_ozeti(k, bas=10_000.0):
    isl = maliyetler(k)
    son = float(k["ozs"]["ozsermaye"].iat[-1])
    p = isl["pnl_usdt"].to_numpy()
    o = dict(kosu=k["ad"], net_usdt=son - bas, getiri_pct=(son / bas - 1) * 100,
             islem=len(isl), aday_islem=int(isl["aday"].sum()),
             beklenti_usdt=float(p.mean()) if len(p) else float("nan"),
             profit_factor=pf(p), komisyon=float(isl["komisyon"].sum()),
             kayma=float(isl["kayma_giris"].sum() + isl["kayma_cikis"].sum()),
             funding=float(isl["funding"].sum()),
             acik_kalan=int(k["ozet"].get("acik_kalan", 0)),
             kapanan_pnl_toplam=float(p.sum()))
    o.update(ozsermaye_metrik(k["ozs"], bas))
    return o


def aday_islemleri(k):
    """Aday işlemleri: sinyal defteri + DB satırı + R + işaretler."""
    isl = maliyetler(k)
    sin = k["sin"]
    if sin.empty or "pos_id" not in sin.columns:
        return pd.DataFrame()
    dol = sin[sin["sonuc"] == "dolum"].copy()
    a = isl[isl["aday"]].set_index("id")
    rows = []
    for _, s in dol.iterrows():
        if s["pos_id"] not in a.index:
            continue                                     # koşu sonunda açık kaldı
        r = a.loc[s["pos_id"]]
        side = "long" if s["yon"] == 1 else "short"
        q = float(r["quantity"])
        rows.append(dict(
            sembol=s["sembol"], yon=side,
            a_zaman=pd.to_datetime(s["a_ts"], unit="ms", utc=True),
            p_zaman=pd.to_datetime(s["p_ts"], unit="ms", utc=True),
            f_zaman=pd.to_datetime(s["f_ts"], unit="ms", utc=True),
            q_zaman=pd.to_datetime(s["q_ts"], unit="ms", utc=True),
            giris_zamani=r["entry_time"], cikis_zamani=r["exit_time"],
            P=s["P"], E_plan=s["E_plan"], E_fill=r["entry_price"], stop=s["S"], hedef=s["T"],
            miktar=q, risk_pct=s.get("risk_pct"), cikis_fiyati=r["exit_price"],
            cikis_nedeni=r["exit_reason"], komisyon=r["komisyon"], kayma_giris=r["kayma_giris"],
            kayma_cikis=r["kayma_cikis"], funding=r["funding"], net_pnl=r["pnl_usdt"],
            R0_usdt=r0_usdt(r["entry_price"], s["S"], q),
            net_R=net_r(r["pnl_usdt"], r["entry_price"], s["S"], q),
            sl_gap=bool(r.get("sl_gap", False)), kimlik=s["kimlik"]))
    d = pd.DataFrame(rows)
    if d.empty:
        return d
    d["gecersiz_risk"] = ~np.isfinite(d["net_R"])
    # cikis_zamani DB damgasıdır (asenkron kapanış kaydı → bazen +1 saat); tutuş için tutus_mum kullanılır
    return d


def _veri(onb, veri_dizini, coin):
    if coin not in onb:
        x = pd.read_csv(os.path.join(veri_dizini, f"{coin}_fut_1h.csv"))
        x["ts"] = pd.to_datetime(x["ts"], utc=True)
        onb[coin] = x.set_index("ts")
    return onb[coin]


def belirsizlik_isaretle(d, veri_dizini):
    """Çıkış mumunu VERİDEN bulur (DB exit_time kapanış geri çağrısı asenkron işlendiği
    için bazen bir damga geç yazılıyor; fiyat doğru, damga değil). Giriş mumu q+1'den
    itibaren stop/hedefe ilk değen mum = çıkış mumu; ikisine birden değdiyse işaretlenir."""
    if d.empty:
        return d
    onb, bel, mum_say = {}, [], []
    for _, r in d.iterrows():
        x = _veri(onb, veri_dizini, r["sembol"].split("/")[0])
        g = r["giris_zamani"]
        pen = x.loc[g: g + pd.Timedelta(hours=11)]           # q+1 .. q+12 (12 mum)
        b, n = False, len(pen)
        for j, (_, m) in enumerate(pen.iterrows()):
            if r["yon"] == "long":
                s_, t_ = m["low"] <= r["stop"], m["high"] >= r["hedef"]
            else:
                s_, t_ = m["high"] >= r["stop"], m["low"] <= r["hedef"]
            if s_ or t_:
                b, n = (s_ and t_), j + 1
                break
        bel.append(b)
        mum_say.append(n)
    d["ayni_mum_stop_hedef"] = bel
    d["tutus_mum"] = mum_say
    return d


def kirilim(d, anahtar):
    g = d.groupby(anahtar)
    return pd.DataFrame(dict(islem=g.size(), kazanma_orani=g["net_R"].apply(lambda x: (x > 0).mean()),
                             ort_R=g["net_R"].mean(), toplam_R=g["net_R"].sum(),
                             net_usdt=g["net_pnl"].sum(),
                             pf=g["net_pnl"].apply(pf))).reset_index()


def aday_istatistik(d):
    if d.empty:
        return dict(islem=0)
    hafta = d["giris_zamani"].dt.tz_localize(None).dt.to_period("W").astype(str)
    lo, hi = hafta_boot(d["net_R"].to_numpy(), hafta.to_numpy())
    srt = d.sort_values("net_pnl", ascending=False)
    cikar = {}
    for n in (1, 3, 5, 10):
        kalan = srt.iloc[n:]
        cikar[f"en_iyi_{n}_cikarilinca"] = dict(net_usdt=float(kalan["net_pnl"].sum()),
                                               toplam_R=float(kalan["net_R"].sum()),
                                               ort_R=float(kalan["net_R"].mean()) if len(kalan) else float("nan"))
    yil = d["giris_zamani"].dt.year
    return dict(islem=len(d), kazanma_orani=float((d["net_R"] > 0).mean()),
                ort_net_R=float(d["net_R"].mean()), toplam_net_R=float(d["net_R"].sum()),
                ort_R_GA95=[lo, hi], medyan_R=float(d["net_R"].median()),
                net_usdt=float(d["net_pnl"].sum()), pf=pf(d["net_pnl"]),
                cikis_nedeni=d["cikis_nedeni"].value_counts().to_dict(),
                ayni_mum_stop_hedef=int(d.get("ayni_mum_stop_hedef", pd.Series(dtype=bool)).sum()),
                sl_gap=int(d["sl_gap"].sum()), gecersiz_risk=int(d["gecersiz_risk"].sum()),
                yil_ort_R={int(k): float(v) for k, v in d.groupby(yil)["net_R"].mean().items()},
                yil_islem={int(k): int(v) for k, v in d.groupby(yil).size().items()},
                ort_tutus_mum=float(d["tutus_mum"].mean()), en_iyi_cikarma=cikar)


def huni(k):
    """Hazırlık → sinyal → engellenen → dolum → kapanan sayıları."""
    dizin, ad = k["dizin"], k["ad"]
    ol = pd.read_csv(os.path.join(dizin, f"{ad}_aday_olaylar.csv.gz"))
    sin = k["sin"]
    haz = ol[ol["tur"] == "hazirlik"]
    ipt = ol[ol["tur"] == "iptal"]
    return dict(hazirlik=len(haz), hazirlik_yon={("long" if int(y) == 1 else "short"): int(n)
                                               for y, n in haz["yon"].value_counts().items()},
                iptal=len(ipt), iptal_neden=ipt["neden"].value_counts().to_dict(),
                eksik_mum=int((ol["tur"] == "eksik_mum").sum()),
                sinyal=int((sin["sonuc"] != "gecersiz_seviye").sum()) if len(sin) else 0,
                gecersiz_seviye=int((sin["sonuc"] == "gecersiz_seviye").sum()) if len(sin) else 0,
                sonuc=sin["sonuc"].value_counts().to_dict() if len(sin) else {},
                engel_neden=sin.loc[sin["sonuc"] == "engellendi", "neden_kodu"].value_counts().to_dict()
                if len(sin) and "neden_kodu" in sin.columns else {},
                kapanan=int(k["isl"]["aday"].sum()))


def haftalik(ozs):
    s = ozs.set_index("t")["ozsermaye"]
    return s.resample("W-SUN").last()


def negatif_haftalar(kA, kA75, kB, dB):
    wA, wA75, wB = haftalik(kA["ozs"]), haftalik(kA75["ozs"]), haftalik(kB["ozs"])
    d = pd.DataFrame({"A": wA, "A75": wA75, "B": wB})
    once = d.shift(1)
    once.iloc[0] = 10_000.0
    fark = d - once
    neg = fark[fark["A"] < 0].copy()
    neg.columns = ["A_usdt", "A75_usdt", "B_usdt"]
    neg["B_eksi_A"] = neg["B_usdt"] - neg["A_usdt"]
    neg["B_eksi_A75"] = neg["B_usdt"] - neg["A75_usdt"]
    if not dB.empty:
        hc = dB.set_index("cikis_zamani")["net_pnl"].resample("W-SUN").sum()
        neg["aday_kapanan_pnl"] = hc.reindex(neg.index).fillna(0.0)
    return neg.reset_index().rename(columns={"t": "hafta_sonu"})


def dusus_donemleri(kA, kA75, kB, dB, n=5):
    """A'nın en büyük n tepe→dip düşüşü; aynı pencerede A75, B ve aday."""
    s = kA["ozs"].set_index("t")["ozsermaye"]
    e = s.to_numpy()
    t = s.index
    tepe_i, out, kullan = 0, [], np.zeros(len(e), bool)
    epizot = []
    i = 0
    tepe = 10_000.0
    tepe_i = 0
    dip = None
    for j in range(len(e)):
        if e[j] >= tepe:
            if dip is not None:
                epizot.append((tepe_i, dip[0], j, (tepe - dip[1]) / tepe))
            tepe, tepe_i, dip = e[j], j, None
        else:
            if dip is None or e[j] < dip[1]:
                dip = (j, e[j])
    if dip is not None:
        epizot.append((tepe_i, dip[0], len(e) - 1, (tepe - dip[1]) / tepe))
    epizot.sort(key=lambda x: -x[3])
    sA75 = kA75["ozs"].set_index("t")["ozsermaye"]
    sB = kB["ozs"].set_index("t")["ozsermaye"]
    for (a, b, c, dd) in epizot[:n]:
        t0, t1 = t[a], t[b]
        rA = e[b] / e[a] - 1
        rA75 = sA75.loc[t1] / sA75.loc[t0] - 1
        rB = sB.loc[t1] / sB.loc[t0] - 1
        ad = dB[(dB["cikis_zamani"] > t0) & (dB["cikis_zamani"] <= t1)] if not dB.empty else dB
        out.append(dict(tepe=t0, dip=t1, toparlanma=t[c] if c < len(t) else None,
                        A_dusus_pct=rA * 100, A75_pct=rA75 * 100, B_pct=rB * 100,
                        B_eksi_A75_pp=(rB - rA75) * 100, B_eksi_A_pp=(rB - rA) * 100,
                        aday_islem=len(ad), aday_pnl=float(ad["net_pnl"].sum()) if len(ad) else 0.0,
                        aday_short=int((ad["yon"] == "short").sum()) if len(ad) else 0))
    return pd.DataFrame(out)


def yillik_fark(kA75, kB):
    a = kA75["ozs"].set_index("t")["ozsermaye"].resample("YE").last()
    b = kB["ozs"].set_index("t")["ozsermaye"].resample("YE").last()
    once_a = a.shift(1).fillna(10_000.0)
    once_b = b.shift(1).fillna(10_000.0)
    return pd.DataFrame({"A75_yil_pct": (a / once_a - 1) * 100, "B_yil_pct": (b / once_b - 1) * 100,
                         "B_eksi_A75_usdt": (b - once_b) - (a - once_a)})


# ───────────────────────── ana ───────────────────────────────────────────────
def main(dizin):
    kosular = {}
    for ad in ("A", "A75", "B", "S", "A_2x", "A75_2x", "B_2x", "S_2x", "S_cikis", "A_f", "A75_f", "B_f"):
        k = oku(dizin, ad)
        if k is not None:
            k["dizin"] = dizin
            kosular[ad] = k
    sonuc = dict(kosulan=sorted(kosular), kosulmayan=[a for a in ("A", "A75", "B", "S", "A_2x", "A75_2x",
                 "B_2x", "S_2x", "S_cikis", "A_f", "A75_f", "B_f") if a not in kosular])
    tablo = [kosu_ozeti(k) for k in kosular.values()]
    pd.DataFrame(tablo).to_csv(os.path.join(BURA, "karsilastirma.csv"), index=False)
    sonuc["karsilastirma"] = tablo
    veri = os.path.join(os.path.dirname(os.path.dirname(BURA)), "data")
    aday = {}
    for ad in ("B", "S", "B_2x", "S_2x", "S_cikis", "B_f"):
        if ad not in kosular:
            continue
        d = belirsizlik_isaretle(aday_islemleri(kosular[ad]), veri)
        aday[ad] = d
        sonuc[f"aday_{ad}"] = aday_istatistik(d)
        sonuc[f"huni_{ad}"] = huni(kosular[ad])
        if not d.empty:
            sonuc[f"degismezler_{ad}"] = degismezler(kosular[ad], d, veri)
        if ad in ("B", "S"):
            d.to_csv(os.path.join(BURA, f"aday_islemler_{ad}.csv"), index=False)
            sin = kosular[ad]["sin"]
            sin[sin["sonuc"] != "dolum"].to_csv(os.path.join(BURA, f"aday_engellenen_{ad}.csv"), index=False)
            if not d.empty:
                d["yil"] = d["giris_zamani"].dt.year
                d["coin"] = d["sembol"].str.split("/").str[0]
                for an in ("yil", "coin", "yon"):
                    kirilim(d, an).to_csv(os.path.join(BURA, f"aday_kirilim_{ad}_{an}.csv"), index=False)
                d["yarim"] = np.where(d["giris_zamani"] < pd.Timestamp("2024-12-01", tz="UTC"), "1_ilk", "2_son")
                sonuc[f"aday_{ad}_yarilar"] = kirilim(d, "yarim").to_dict("records")
    if "A" in kosular:
        sonuc["A_referans_esleme"] = referans_esle(kosular["A"])
    if all(x in kosular for x in ("A", "A75", "B")):
        dB = aday.get("B", pd.DataFrame())
        nh = negatif_haftalar(kosular["A"], kosular["A75"], kosular["B"], dB)
        nh.to_csv(os.path.join(BURA, "a_negatif_haftalar.csv"), index=False)
        sonuc["A_negatif_haftalar"] = dict(
            hafta=len(nh), A_toplam=float(nh["A_usdt"].sum()), A75_toplam=float(nh["A75_usdt"].sum()),
            B_toplam=float(nh["B_usdt"].sum()), B_eksi_A=float(nh["B_eksi_A"].sum()),
            B_eksi_A75=float(nh["B_eksi_A75"].sum()),
            B_eksi_A75_pozitif_hafta=int((nh["B_eksi_A75"] > 0).sum()),
            aday_pnl=float(nh.get("aday_kapanan_pnl", pd.Series(dtype=float)).sum()))
        dd = dusus_donemleri(kosular["A"], kosular["A75"], kosular["B"], dB)
        dd.to_csv(os.path.join(BURA, "a_dusus_donemleri.csv"), index=False)
        sonuc["A_dusus_donemleri"] = dd.to_dict("records")
        sonuc["yillik_B_A75"] = {str(k.year): v for k, v in yillik_fark(kosular["A75"], kosular["B"]).to_dict("index").items()}
        for ad in ("A", "A75", "B"):
            o = kosular[ad]["ozs"]
            o[["kapanis_ms", "ozsermaye", "serbest", "marjin", "gerceklesmemis", "acik_risk_stopa",
               "acik_poz", "aday_acik"]].to_csv(os.path.join(BURA, f"ozsermaye_saatlik_{ad}.csv.gz"),
                                               index=False, compression="gzip")
    with open(os.path.join(BURA, "sonuclar.json"), "w") as f:
        json.dump(sonuc, f, indent=1, default=str)
    return sonuc


def degismezler(k, d, veri_dizini):
    """Tam koşu üzerinde davranış değişmezleri (her aday işlemi için)."""
    ay = k["ozet"]["ayar"]
    g_bp = float(ay["slip_giris"])
    sin = k["sin"]
    isl = k["isl"]
    onb, hata = {}, []
    for _, r in d.iterrows():
        coin = r["sembol"].split("/")[0]
        x = _veri(onb, veri_dizini, coin)
        q_kap = r["q_zaman"] + pd.Timedelta(hours=1)
        if r["giris_zamani"] != q_kap:
            hata.append(("giris_q_kapanisi_degil", r["kimlik"]))
        cq = float(x.loc[r["q_zaman"], "close"])
        yon = 1 if r["yon"] == "long" else -1
        if not math.isclose(r["E_fill"], cq * (1 + yon * g_bp / 1e4), rel_tol=1e-9):
            hata.append(("dolum_q_kapanisi_arti_kayma_degil", r["kimlik"]))
        c_bp = float(ay["slip_cikis"]) if ay.get("ADAY_CIKIS_SLIP_BP") in (None, "None") \
            else float(ay["ADAY_CIKIS_SLIP_BP"])
        if r["cikis_nedeni"] == "max_hold":
            c12 = float(x.loc[r["giris_zamani"] + pd.Timedelta(hours=11), "close"])   # q+12 kapanışı = q+13 açılışı
            if not math.isclose(r["cikis_fiyati"], c12 * (1 - yon * c_bp / 1e4), rel_tol=1e-9):
                hata.append(("max_hold_q12_kapanisi_degil", r["kimlik"]))
            if r["tutus_mum"] != 12:
                hata.append(("max_hold_oncesi_stop_hedef_gorulmustu", r["kimlik"]))
        elif r["cikis_nedeni"] in ("sl_hit", "tp_hit"):
            sev = r["stop"] if r["cikis_nedeni"] == "sl_hit" else r["hedef"]
            bp = c_bp if r["cikis_nedeni"] == "sl_hit" else 0.0
            if not math.isclose(r["cikis_fiyati"], sev * (1 - yon * bp / 1e4), rel_tol=1e-9):
                hata.append(("cikis_seviyede_degil", r["kimlik"]))
            if r["tutus_mum"] > 12:
                hata.append(("12_mumdan_uzun", r["kimlik"]))
    a_isl = isl[isl["aday"]]
    db_stop = dict(zip(a_isl["id"], a_isl["sl_price"]))
    db_tp = dict(zip(a_isl["id"], a_isl["tp_price"]))
    dol = sin[sin["sonuc"] == "dolum"] if "sonuc" in sin.columns else sin
    for _, s in dol.iterrows():
        if s["pos_id"] in db_stop and not (math.isclose(db_stop[s["pos_id"]], s["S"], rel_tol=1e-12)
                                           and math.isclose(db_tp[s["pos_id"]], s["T"], rel_tol=1e-12)):
            hata.append(("stop_hedef_sinyalden_farkli", s["kimlik"]))
    tekrar = int(sin["kimlik"].duplicated().sum()) if len(sin) else 0
    # öncelik: aday girişi olan damgada aynı sembolde bot girişi olmamalı (bot önce denendi)
    bot = isl[~isl["aday"]]
    cak = 0
    for _, r in d.iterrows():
        cak += int(((bot["symbol"] == r["sembol"]) & (bot["entry_time"] == r["giris_zamani"])).sum())
    return dict(aday_islem=len(d), hata_sayisi=len(hata), hatalar=hata[:20],
                ayni_hazirliktan_tekrar_deneme=tekrar, ayni_damga_ayni_sembol_bot_girisi=cak,
                max_hold_cikis=int((d["cikis_nedeni"] == "max_hold").sum()))


def referans_esle(kA):
    """A'nın kapanan işlemlerini 936'lık referansla eşle (sembol, yön, giriş zamanı)."""
    ref_y = os.path.join(os.path.dirname(BURA), "paylasim_paketi_2026-09-26", "ikiz", "ikiz_k25_cap25_islemler.csv")
    if not os.path.exists(ref_y):
        return dict(durum="referans dosyası yok")
    ref = pd.read_csv(ref_y)
    a = kA["isl"]
    def anahtar(df):
        t = pd.to_datetime(df["entry_time"], utc=True, format="mixed").dt.floor("min")
        return set(zip(df["symbol"], df["side"], t.astype(str)))
    ka, kr = anahtar(a), anahtar(ref)
    ort = ka & kr
    pnl_a = float(a["pnl_usdt"].sum())
    pnl_r = float(ref["pnl_usdt"].sum()) if "pnl_usdt" in ref.columns else float("nan")
    return dict(referans_islem=len(ref), A_islem=len(a), ortak=len(ort),
                yalniz_A=len(ka - kr), yalniz_referans=len(kr - ka),
                A_pnl=pnl_a, referans_pnl=pnl_r, pnl_farki=pnl_a - pnl_r)


if __name__ == "__main__":
    s = main(sys.argv[1])
    print(json.dumps({k: s[k] for k in ("kosulan", "kosulmayan")}, indent=1))
