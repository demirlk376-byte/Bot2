"""
analiz.py — SQUEEZE_COST_AWARE_ALLOCATION karşılaştırması (A / B / C, TRAIN / TEST, 5.13bp ve 15.85bp).

ÖNCEDEN SABİT (sonuçlar görülmeden yazıldı; bkz. SQUEEZE_COST_AWARE_ALLOCATION_REPORT.md):
  Hesap değeri: arastirma/kar_geri_verme/kar_geri_verme.py'nin saatlik() fonksiyonu (ekonomik çıkış
    işareti, ortak saatlik kapanışlar, giriş ücreti girişte, pnl_usdt çıkış işaretinde; komisyon bir kez).
  Risk eşleme (yalnız TRAIN saatlik getiri std'si):
    k_B = min(1, σ_A/σ_B)  → σ_B > σ_A ise B ortak katsayıyla küçültülür (RISK_SCALE × k_B, yeniden koşum)
    k_C = σ_B*/σ_A         → C = A'nın bütün kolları × k_C (RISK_SCALE × k_C, yeniden koşum)
    Katsayılar TEST'e bakmadan donar; tek atış, iterasyon yok; kalan fark raporlanır.
  Pencereler: TRAIN < 2025-01-01 ≤ TEST (tek koşunun alt serileri; TEST daha önce defalarca kullanıldı —
    temiz dış örneklem DEĞİL).
  Adaylık (ana maliyet 5.13bp, TEST):
    K1: (CAGR_B ≥ 1.10·CAGR_A ve maxDD_B ≤ maxDD_A)  VEYA  (maxDD_B ≤ maxDD_A − 5pp ve CAGR_B ≥ 0.95·CAGR_A)
    K2: B, risk-eşlenmiş C'yi TEST CAGR/maxDD oranında geçer
    K3: TRAIN'de ters belirgin bozulma yok: CAGR_B ≥ 0.90·CAGR_A ve maxDD_B ≤ maxDD_A + 3pp
    Belirsizlik: hafta blokları eşleştirilmiş bootstrap (5000, tohum 20260928) — K1'in kullandığı kolun
      Δ'sı (log büyüme ya da maxDD) için %95 GA.
    Hüküm: K1∧K2∧K3 ve GA yanlış işareti dışlıyor → HISTORICAL CANDIDATE
           K1∧K2∧K3 ama GA sıfırı içeriyor             → INCONCLUSIVE
           aksi                                          → REJECTED
  15.85bp stresi: aynı koşullar ayrıca raporlanır (hüküm ana maliyetten).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys

import numpy as np
import pandas as pd

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BURA = os.path.dirname(os.path.abspath(__file__))
S = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/sqca"
S = os.environ.get("SQCA_DIR", S)
REF_CSV = os.path.join(KOK, "arastirma", "paylasim_paketi_2026-09-26", "ikiz", "ikiz_k25_cap25_islemler.csv")
BOLME = pd.Timestamp("2025-01-01", tz="UTC")
CAP = 2.5
TOHUM, N_BOOT = 20260928, 5000
YIL_SAAT = 365.25 * 24

_sp = importlib.util.spec_from_file_location("kgv", os.path.join(KOK, "arastirma", "kar_geri_verme", "kar_geri_verme.py"))
KGV = importlib.util.module_from_spec(_sp); _sp.loader.exec_module(KGV)
_sp2 = importlib.util.spec_from_file_location("pdt", os.path.join(KOK, "arastirma", "pairs_dual_twin", "pairs_dual_twin.py"))
PDT = importlib.util.module_from_spec(_sp2); _sp2.loader.exec_module(PDT)
_PX = {}


def kol_of(s):
    st = str(json.loads(s).get("strategy", "")).lower()
    return "donchian" if "donch" in st else "squeeze" if "squeeze" in st else "mean_rev"


def islemler(ad):
    d = pd.read_csv(os.path.join(S, ad, f"{ad}_islemler.csv"))
    d["kol"] = d.strategy_scores.map(kol_of)
    return d


def equity(d):
    tmp = os.path.join(S, "_gecici.csv")
    d.to_csv(tmp, index=False)
    KGV.CSV = tmp
    x = KGV.hazirla()
    if not _PX:
        _PX.update(KGV.fiyatlar(sorted(set(x.coin.unique()) | {"SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB", "XRP", "DOGE", "XLM", "LTC", "TRX"})))
    x = KGV.cikis_simule(x, {c: _PX[c] for c in x.coin.unique()})
    e = KGV.saatlik(x, {c: _PX[c] for c in x.coin.unique()})
    return x, e.set_index("zaman")["hesap_degeri"]


def pencere(eq, per):
    if per == "TRAIN":
        return eq[eq.index < BOLME]
    if per == "TEST":
        return eq[eq.index >= BOLME]
    return eq


def metrik(eq, d, per, sig):
    s = pencere(eq, per)
    v = s.to_numpy()
    m = PDT.portfoy_metrik(s)
    yil = (s.index[-1] - s.index[0]).total_seconds() / (365.25 * 86400)
    if per == "TRAIN":
        dd = d[d.giris < BOLME]
    elif per == "TEST":
        dd = d[d.giris >= BOLME]
    else:
        dd = d
    ret = s.pct_change().dropna()
    # gerçekleşen risk: qty × |niyet − sl0| / giriş anındaki hesap değeri
    V = eq.reindex(dd.giris.dt.floor("h")).to_numpy()
    rr = (dd.quantity * dd.risk0).to_numpy() / V
    kol_risk = {k: float(np.nanmean(rr[(dd.kol == k).to_numpy()]) * 100) for k in ("donchian", "squeeze", "mean_rev")}
    # CAP bağlayıcılığı (squeeze): hedef risk / stop% > CAP ise nominal tavanı kısar
    sq = dd[dd.kol == "squeeze"]
    stop_pct = (sq.risk0 / sq.niyet).to_numpy()
    hedef = sig["squeeze_risk_pct"]
    cap_bag = int((hedef / stop_pct > CAP).sum()) if len(sq) else 0
    ucret = float((dd.ucret_giris + dd.ucret_cikis).sum())
    kayma = float(dd.kayma_giris_usd.sum())
    fund = float((dd.pnl_yeniden - dd.pnl_usdt).sum())        # + = ödenen funding (yeniden kurulumdan kalan)
    return dict(cagr=float(m["cagr"]), maxdd=float(m["maxdd"]), en_kotu_ay=float(m["en_kotu_ay"]),
                sualti_gun=float(m["sualti_gun"]), pgr=float(m["pgr"]), final=float(v[-1]), getiri=float(v[-1] / v[0] - 1),
                ret_std_saat=float(ret.std()), islem=len(dd), n_kol=dd.kol.value_counts().to_dict(),
                ucret_usd=ucret, kayma_usd=kayma, funding_usd=fund, maliyet_usd=ucret + kayma + fund,
                risk_kol_pct=kol_risk, squeeze_cap_baglayici=cap_bag, squeeze_n=len(sq), yil=yil)


def red_say(ad):
    y = os.path.join(S, ad, "signals_log.csv")
    if not os.path.exists(y):
        return None
    s = pd.read_csv(y, header=None, on_bad_lines="skip", dtype=str)
    txt = s.fillna("").astype(str).agg(" ".join, axis=1).str.lower()
    return int(txt.str.contains("margin|bakiye|yetersiz").sum())


def boot_esli(eqA, eqB, per, rota):
    a, b = pencere(eqA, per), pencere(eqB, per)
    ix = a.index.intersection(b.index)
    a, b = a.loc[ix], b.loc[ix]
    la, lb = np.log(a).diff().dropna(), np.log(b).diff().dropna()
    hafta = la.index.tz_convert(None).to_period("W").astype(str)
    gA = [g.to_numpy() for _, g in la.groupby(hafta)]
    gB = [g.to_numpy() for _, g in lb.groupby(hafta)]
    rng = np.random.default_rng(TOHUM)
    out = []
    for _ in range(N_BOOT):
        sec = rng.integers(0, len(gA), len(gA))
        ra = np.concatenate([gA[i] for i in sec]); rb = np.concatenate([gB[i] for i in sec])
        if rota == "buyume":
            out.append((rb.sum() - ra.sum()) / len(ra) * YIL_SAAT)
        else:
            def mdd(r):
                c = np.cumsum(r); return float(1 - np.exp(c - np.maximum.accumulate(np.maximum(c, 0))).min())
            out.append(mdd(rb) - mdd(ra))
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def karar(M, ad_a, ad_b, ad_c, eq):
    A, B, C = M[ad_a]["TEST"], M[ad_b]["TEST"], M[ad_c]["TEST"]
    At, Bt = M[ad_a]["TRAIN"], M[ad_b]["TRAIN"]
    r1 = B["cagr"] >= 1.10 * A["cagr"] and B["maxdd"] <= A["maxdd"]
    r2 = B["maxdd"] <= A["maxdd"] - 0.05 and B["cagr"] >= 0.95 * A["cagr"]
    k1 = r1 or r2
    k2 = (B["cagr"] / B["maxdd"]) > (C["cagr"] / C["maxdd"])
    k3 = Bt["cagr"] >= 0.90 * At["cagr"] and Bt["maxdd"] <= At["maxdd"] + 0.03
    rota = "buyume" if r1 or not r2 else "dd"
    ga = boot_esli(eq[ad_a], eq[ad_b], "TEST", rota)
    ga_c = boot_esli(eq[ad_c], eq[ad_b], "TEST", "buyume")
    ga_ok = (ga[0] > 0) if rota == "buyume" else (ga[1] < 0)
    if k1 and k2 and k3 and ga_ok:
        h = "HISTORICAL CANDIDATE"
    elif k1 and k2 and k3:
        h = "INCONCLUSIVE"
    else:
        h = "REJECTED"
    return dict(K1=k1, K1_rota_getiri=r1, K1_rota_dd=r2, K2=k2, K3=k3, rota=rota, ga=ga,
                ga_B_vs_C_buyume=ga_c, hukum=h)


def main():
    kosular = [x for x in sorted(os.listdir(S)) if os.path.isdir(os.path.join(S, x)) and
               os.path.exists(os.path.join(S, x, f"{x}_islemler.csv"))]
    out = {"kosular": kosular}
    # 0) referans yeniden üretimi
    if "R0" in kosular:
        ref = pd.read_csv(REF_CSV, dtype=str, keep_default_na=False)
        r0 = pd.read_csv(os.path.join(S, "R0", "R0_islemler.csv"), dtype=str, keep_default_na=False)
        cols = ["symbol", "side", "entry_price", "exit_price", "quantity", "entry_time", "exit_time", "pnl_usdt", "exit_reason"]
        ayni = len(ref) == len(r0) and all((ref[c].astype(str).values == r0[c].astype(str).values).all() for c in cols)
        if not ayni and len(ref) == len(r0):
            num = ["entry_price", "exit_price", "quantity", "pnl_usdt"]
            fark = max(float((ref[c].astype(float) - r0[c].astype(float)).abs().max()) for c in num)
            ayni_zaman = all((ref[c].values == r0[c].values).all() for c in ("symbol", "side", "entry_time", "exit_time", "exit_reason"))
            out["R0"] = dict(n_ref=len(ref), n_r0=len(r0), birebir=False, sayisal_max_fark=fark, zaman_ayni=bool(ayni_zaman))
        else:
            out["R0"] = dict(n_ref=len(ref), n_r0=len(r0), birebir=bool(ayni))
        print("R0 yeniden üretim:", out["R0"])

    sigler, D, EQ, M = {}, {}, {}, {}
    for ad in kosular:
        oz = json.load(open(os.path.join(S, ad, f"{ad}_ozet.json")))["ayar"]
        sigler[ad] = oz
        d = islemler(ad)
        x, eq = equity(d)
        D[ad], EQ[ad] = x, eq
        M[ad] = {per: metrik(eq, x, per, oz) for per in ("TUM", "TRAIN", "TEST")}
        M[ad]["red"] = red_say(ad)
        print(f"{ad}: n={len(x)} TRAIN σ_saat {M[ad]['TRAIN']['ret_std_saat']:.6f}", flush=True)
    out["M"] = M; out["ayar"] = sigler
    # risk eşleme katsayıları (TRAIN σ) — aşama 1 çıktısı
    if "A5" in M and "B5" in M:
        sA, sB = M["A5"]["TRAIN"]["ret_std_saat"], M["B5"]["TRAIN"]["ret_std_saat"]
        kB = min(1.0, sA / sB)
        out["esleme"] = dict(sigma_A=sA, sigma_B=sB, k_B=kB,
                             not_="B küçültülmez" if kB >= 1 else "B, RISK_SCALE×k_B ile yeniden koşulmalı")
        print("EŞLEME:", out["esleme"])
    if all(k in M for k in ("A5", "B5", "C5")):
        out["esleme"]["sigma_C"] = M["C5"]["TRAIN"]["ret_std_saat"]
        out["esleme"]["C_kalan_fark"] = out["esleme"]["sigma_C"] / out["esleme"]["sigma_B"] - 1
        out["karar_ana"] = karar(M, "A5", "B5", "C5", EQ)
        print("KARAR (5.13bp):", out["karar_ana"])
    if all(k in M for k in ("A15", "B15", "C15")):
        out["karar_stres"] = karar(M, "A15", "B15", "C15", EQ)
        print("STRES (15.85bp):", out["karar_stres"])
    satir = []
    for ad in kosular:
        for per in ("TRAIN", "TEST"):
            m = M[ad][per]
            satir.append(dict(kosu=ad, pencere=per, CAGR=m["cagr"], maxDD=m["maxdd"], en_kotu_ay=m["en_kotu_ay"],
                              sualti_gun=m["sualti_gun"], PGR=m["pgr"], getiri=m["getiri"],
                              maliyet_usd=m["maliyet_usd"], ucret_usd=m["ucret_usd"], kayma_usd=m["kayma_usd"],
                              funding_usd=m["funding_usd"], islem=m["islem"], n_kol=m["n_kol"],
                              risk_donch_pct=m["risk_kol_pct"]["donchian"], risk_sq_pct=m["risk_kol_pct"]["squeeze"],
                              risk_bb_pct=m["risk_kol_pct"]["mean_rev"], sq_cap_baglayici=m["squeeze_cap_baglayici"],
                              sq_n=m["squeeze_n"], marjin_red_tum=M[ad]["red"], sigma_saat=m["ret_std_saat"]))
    pd.DataFrame(satir).to_csv(os.path.join(BURA, "karsilastirma_tablosu.csv"), index=False)
    with open(os.path.join(BURA, "sonuclar.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    return out, EQ, M


if __name__ == "__main__":
    main()
