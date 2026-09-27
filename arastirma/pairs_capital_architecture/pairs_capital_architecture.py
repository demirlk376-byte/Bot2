"""
pairs_capital_architecture.py — pairs SİNYALİ DEĞİŞMEDEN sermaye/kaldıraç mimarisi testi.

Sinyal, execution ve maliyet pairs_dual_twin ile AYNI (içe aktarılır): 8 sabit çift, 1D log-oran,
ZWIN 60, z 2.0/0.5/3.5, 20 gün, dolum D+1 01:00 1h açılışı, BASE 15.85bp/dolum + 1bp taker.

ÖNCEDEN SABİT MİMARİ (sonuçtan önce; PAIRS_CAPITAL_ARCHITECTURE_REPORT.md):
  12 hücre: pairs payı {%10, %20, %30} × izole kaldıraç {1x, 3x, 5x, 10x}. Başka hücre yok.
  Pairs hesabı: çift başına ayrı izole slot. İşlem anında marjin = pairs hesap değeri / 8
  (bacak başına yarısı); nominal = marjin × kaldıraç; PnL = nominal × kaldıraçsız çift getirisi
  (ücret/kayma nominal üzerinden). Bileşik (kendi hesabı içinde); hesaplar arası para akışı YOK.
  Serbest marjin (hesap değeri − kullanılan marjin) yetmezse işlem reddedilir.
  Likidasyon (muhafazakâr MEXC izole yaklaşımı, bakım oranı MMR = %1):
    long bacak : ters hareket x ≥ (1/L − MMR)/(1 − MMR)
    short bacak: ters hareket x ≥ (1/L − MMR)/(1 + MMR)
    saatlik high/low ile, dolum anından itibaren. Değerse: o bacağın marjininin TAMAMI kaybedilir,
    karşı bacak bir sonraki 1h açılışında (kayma + ücretle) kapatılır; işlem z-çıkışına yaşatılmaz.
  Pencereler: TRAIN [ana ikiz başlangıcı, 2025-01-01), TEST [2025-01-01, son). Her pencere,
  pencere başında sabit payla yapılmış AYRI bir dağıtım (açık pozisyon devri yok).
  Ana hesap = doğrulanmış ana ikizin saatlik hesap değeri, pencere başına göre ölçeklenmiş.

Kullanım (repo kökünden, çevrimdışı):  python3 arastirma/pairs_capital_architecture/pairs_capital_architecture.py
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
sys.path.insert(0, KOK)
_spec = importlib.util.spec_from_file_location(
    "pdt", os.path.join(KOK, "arastirma", "pairs_dual_twin", "pairs_dual_twin.py"))
PDT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(PDT)

PAIRS = PDT.PAIRS
SLIP_BP = PDT.SENARYO["BASE"]
TAKER = PDT.TAKER
PAYLAR = (0.10, 0.20, 0.30)
KALDIRACLAR = (1, 3, 5, 10)
SLOT = 8
MMR = 0.01
SERMAYE = 10000.0
BOLME = PDT.BOLME
H = pd.Timedelta(hours=1)
KOMSU_L = {1: (3,), 3: (1, 5), 5: (3, 10), 10: (5,)}
KOMSU_P = {0.10: (0.20,), 0.20: (0.10, 0.30), 0.30: (0.20,)}


def lik_esik(yon, L):
    return (1 / L - MMR) / (1 - MMR) if yon > 0 else (1 / L - MMR) / (1 + MMR)


def kos(O, Hh, L_, C, Z, lev, E0, bas, bit, kara_liste=frozenset()):
    """Olay güdümlü pairs hesabı [bas, bit). kara_liste: çıkarılacak (pair, sinyal_günü) —
    yalnız yoğunlaşma kontrolü için."""
    s = SLIP_BP / 1e4
    saatler = C.index[(C.index >= bas) & (C.index < bit)]
    gunler = sorted({d for t in Z.values() for d in t.index})
    bilgi = {d + pd.Timedelta(days=1): d for d in gunler}
    acik, bekleyen, son_cikis = {}, [], {p: None for p in PAIRS}
    islem, red, likler = [], 0, []
    realized = 0.0
    kullanilan = 0.0
    eq = np.empty(len(saatler))
    ihlal = 0

    def fill(px, al):
        return px * (1 + s) if al > 0 else px * (1 - s)

    def mtm(t):
        tot = 0.0
        for (a, b), p in acik.items():
            for k, d, f, q, cl in ((a, p["dA"], p["fa"], p["qa"], p["kapA"]), (b, p["dB"], p["fb"], p["qb"], p["kapB"])):
                if cl is None:
                    c = C.at[t, k]
                    if np.isfinite(c):
                        tot += d * (c - f) * q
        return tot

    def kapat(p, t, neden, info_gun):
        """Pozisyonu t açılışında kapat (likide olmuş bacak zaten kapalı)."""
        nonlocal realized, kullanilan
        pos = acik.pop(p)
        a, b = p
        net = pos["lik_pnl"]
        ucret = TAKER * (pos["fa"] * pos["qa"] + pos["fb"] * pos["qb"])
        brut = 0.0
        for k, d, f, q, cl in ((a, pos["dA"], pos["fa"], pos["qa"], pos["kapA"]), (b, pos["dB"], pos["fb"], pos["qb"], pos["kapB"])):
            if cl is not None:
                continue
            px = O.at[t, k]
            x = fill(px, -d)
            net += d * (x - f) * q
            brut += d * (px - f) * q
            ucret += TAKER * x * q
        net -= ucret
        realized += net
        kullanilan -= pos["marj"]
        islem.append(dict(pair_id=f"{a}/{b}", signal_day=pos["gun"], signal_time=pos["bilgi"],
                          entry_time=pos["t"], exit_time=t, exit_reason=neden, lev=lev,
                          margin=pos["marj"], notional=pos["nom"], pnl=net,
                          underlying_net_return=net / pos["nom"], mae_A=pos["maeA"], mae_B=pos["maeB"],
                          liq_A=pos["kapA"] == "lik", liq_B=pos["kapB"] == "lik"))
        son_cikis[p] = info_gun

    for hi, t in enumerate(saatler):
        # 1) açılışta yürütülecekler
        kalan = []
        for (tz, tur, p, info) in bekleyen:
            if tz != t:
                kalan.append((tz, tur, p, info)); continue
            a, b = p
            if not (np.isfinite(O.at[t, a]) and np.isfinite(O.at[t, b])):
                kalan.append((tz + H, tur, p, info)); continue
            if tz <= info["bilgi"]:
                ihlal += 1
            if tur == "giris":
                deger = E0 + realized + mtm(t)
                marj = deger / SLOT
                if marj <= 0 or deger - kullanilan < marj:
                    red += 1; continue
                nom = marj * lev
                dA = info["dA"]
                fa, fb = fill(O.at[t, a], dA), fill(O.at[t, b], -dA)
                acik[p] = dict(gun=info["gun"], bilgi=info["bilgi"], t=t, dA=dA, dB=-dA, fa=fa, fb=fb,
                               qa=(nom / 2) / fa, qb=(nom / 2) / fb, nom=nom, marj=marj,
                               maeA=0.0, maeB=0.0, kapA=None, kapB=None, lik_pnl=0.0)
                kullanilan += marj
            elif tur == "cikis" and p in acik:
                kapat(p, t, info["neden"], info["gun"])
            elif tur == "lik_kapat" and p in acik:
                kapat(p, t, "liquidation", info["gun"])
        bekleyen = kalan

        # 2) bar içi: MAE + likidasyon
        for p, pos in list(acik.items()):
            a, b = p
            lik_oldu = False
            for k, d, f, q, anah, kap in ((a, pos["dA"], pos["fa"], pos["qa"], "maeA", "kapA"),
                                          (b, pos["dB"], pos["fb"], pos["qb"], "maeB", "kapB")):
                if pos[kap] is not None:
                    continue
                hi_, lo_ = Hh.at[t, k], L_.at[t, k]
                if not (np.isfinite(hi_) and np.isfinite(lo_)):
                    continue
                ters = (f - lo_) / f if d > 0 else (hi_ - f) / f
                pos[anah] = max(pos[anah], ters)
                if ters >= lik_esik(d, lev):
                    pos[kap] = "lik"
                    pos["lik_pnl"] -= pos["marj"] / 2          # o bacağın marjini tamamen gider
                    lik_oldu = True
                    likler.append(dict(pair_id=f"{a}/{b}", leg=k, side="long" if d > 0 else "short",
                                       lev=lev, entry=f, time=t, adverse=ters, threshold=lik_esik(d, lev),
                                       signal_day=pos["gun"]))
            if lik_oldu:
                bekleyen = [x for x in bekleyen if x[2] != p]
                bekleyen.append((t + H, "lik_kapat", p, dict(gun=pos["gun"], bilgi=t)))

        # 3) saat sonu değer
        eq[hi] = E0 + realized + mtm(t)

        # 4) bilgi anı (gün D kapanışı)
        bt = t + H
        if bt in bilgi:
            D = bilgi[bt]
            for p in PAIRS:
                zt = Z[p]
                if D not in zt.index:
                    continue
                zz = zt.at[D, "z"]
                if any(x[2] == p for x in bekleyen):
                    continue
                if p in acik:
                    pos = acik[p]
                    if pos["kapA"] or pos["kapB"]:
                        continue
                    neden = None
                    if np.isfinite(zz) and abs(zz) < PDT.Z_OUT:
                        neden = "z_out"
                    elif np.isfinite(zz) and abs(zz) > PDT.Z_STOP:
                        neden = "z_stop"
                    elif (D - pos["gun"]).days >= PDT.MAX_HOLD:
                        neden = "max_hold"
                    if neden:
                        bekleyen.append((bt + H, "cikis", p, dict(gun=D, bilgi=bt, neden=neden)))
                else:
                    if son_cikis[p] is not None and D <= son_cikis[p]:
                        continue
                    if np.isfinite(zz) and abs(zz) >= PDT.Z_IN and bt >= bas and (p, D) not in kara_liste:
                        bekleyen.append((bt + H, "giris", p, dict(gun=D, bilgi=bt, dA=-1 if zz > 0 else 1)))
    return (pd.Series(eq, index=saatler), pd.DataFrame(islem), red, pd.DataFrame(likler), ihlal)


def pencere_metrik(eq):
    m = PDT.portfoy_metrik(eq)
    return m


def main():
    O, Hh, L_, C = PDT.saatlik()
    G = PDT.gunluk_kapanis(C)
    Z = PDT.z_tablosu(G)
    me = pd.read_csv(PDT.EQ_CSV, usecols=["zaman", "hesap_degeri"])
    me["zaman"] = pd.to_datetime(me["zaman"], utc=True)
    main_eq = me.set_index("zaman")["hesap_degeri"]
    pencereler = {"TRAIN": (main_eq.index[0], BOLME), "TEST": (BOLME, main_eq.index[-1] + H)}

    satirlar, lik_hepsi, detay = [], [], {}
    base = {}
    for pen, (bas, bit) in pencereler.items():
        mseg = main_eq[(main_eq.index >= bas) & (main_eq.index < bit)]
        base_eq = SERMAYE * mseg / mseg.iloc[0]
        base[pen] = dict(eq=base_eq, m=pencere_metrik(base_eq))
    b_ay = base["TEST"]["eq"].resample("ME").last()
    b_ret = b_ay.pct_change(); b_ret.iloc[0] = b_ay.iloc[0] / SERMAYE - 1

    for pay in PAYLAR:
        for lev in KALDIRACLAR:
            kayit = dict(allocation=pay, leverage=lev)
            for pen, (bas, bit) in pencereler.items():
                beq = base[pen]["eq"]
                E0 = pay * SERMAYE
                peq, tr, red, lk, ihl = kos(O, Hh, L_, C, Z, lev, E0, bas, bit)
                peq = peq.reindex(beq.index).ffill().fillna(E0)
                comb = (1 - pay) * beq + peq
                m = pencere_metrik(comb)
                kayit.update({f"{pen}_{k}": v for k, v in m.items()})
                kayit[f"{pen}_liq"] = len(lk)
                kayit[f"{pen}_liq_trades"] = int((tr["liq_A"] | tr["liq_B"]).sum()) if not tr.empty else 0
                kayit[f"{pen}_reject"] = red
                kayit[f"{pen}_lookahead"] = ihl
                kayit[f"{pen}_pairs_return"] = peq.iloc[-1] / E0 - 1
                kayit[f"{pen}_pairs_trades"] = len(tr)
                if not lk.empty:
                    lk = lk.assign(allocation=pay, window=pen)
                    lik_hepsi.append(lk)
                if pen == "TEST":
                    c_ay = comb.resample("ME").last()
                    c_ret = c_ay.pct_change(); c_ret.iloc[0] = c_ay.iloc[0] / SERMAYE - 1
                    p_ay = peq.resample("ME").last()
                    p_pnl = p_ay.diff(); p_pnl.iloc[0] = p_ay.iloc[0] - E0
                    neg = b_ret < 0
                    kayit["TEST_negay_n"] = int(neg.sum())
                    kayit["TEST_negay_pairs_usd"] = float(p_pnl[neg].sum())
                    kayit["TEST_negay_pairs_pozitif"] = int((p_pnl[neg] > 0).sum())
                    w5 = b_ret.nsmallest(5).index
                    kayit["TEST_worst5_base_mean"] = float(b_ret[w5].mean())
                    kayit["TEST_worst5_comb_mean"] = float(c_ret[w5].mean())
                    # yoğunlaşma: en iyi 1/3/5 pairs işlemi çıkarılınca (yeniden koşum)
                    en_iyi = tr.sort_values("pnl", ascending=False) if not tr.empty else tr
                    for k in (1, 3, 5):
                        kl = frozenset((tuple(r.pair_id.split("/")), r.signal_day) for r in en_iyi.head(k).itertuples())
                        peq2, tr2, _, lk2, _ = kos(O, Hh, L_, C, Z, lev, E0, bas, bit, kara_liste=kl)
                        peq2 = peq2.reindex(beq.index).ffill().fillna(E0)
                        c2 = (1 - pay) * beq + peq2
                        kayit[f"TEST_minus{k}_pairs_return"] = peq2.iloc[-1] / E0 - 1
                        kayit[f"TEST_minus{k}_comb_return"] = c2.iloc[-1] / c2.iloc[0] - 1
                        kayit[f"TEST_minus{k}_comb_maxdd"] = float((1 - c2 / c2.cummax()).max())
            bm = base["TEST"]["m"]
            kayit["d_return"] = kayit["TEST_getiri"] - bm["getiri"]
            kayit["d_maxdd_pp"] = (kayit["TEST_maxdd"] - bm["maxdd"]) * 100
            kayit["d_pgr"] = kayit["TEST_pgr"] - bm["pgr"]
            kayit["USEFUL"] = bool(kayit["TEST_liq"] == 0 and kayit["TEST_pairs_return"] > 0
                                   and kayit["d_maxdd_pp"] <= -3.0
                                   and kayit["TEST_getiri"] >= 0.90 * bm["getiri"]
                                   and kayit["TEST_pgr"] <= bm["pgr"])
            satirlar.append(kayit)
            print(f"  {pay:.0%} × {lev:>2d}x  TEST getiri {kayit['TEST_getiri'] * 100:+.1f}% maxDD %{kayit['TEST_maxdd'] * 100:.1f} "
                  f"PGR {kayit['TEST_pgr']:.3f} lik TEST {kayit['TEST_liq']} TRAIN {kayit['TRAIN_liq']} "
                  f"pairs TEST {kayit['TEST_pairs_return'] * 100:+.1f}% USEFUL {kayit['USEFUL']}", flush=True)

    tab = pd.DataFrame(satirlar)
    tab.to_csv(os.path.join(BURA, "scenario_table.csv"), index=False)
    lik_df = pd.concat(lik_hepsi) if lik_hepsi else pd.DataFrame()
    lik_df.to_csv(os.path.join(BURA, "liquidation_events.csv"), index=False)

    # ── karar (önceden sabit) ──
    ihlal_top = int(tab["TEST_lookahead"].sum() + tab["TRAIN_lookahead"].sum())
    use = {(r.allocation, r.leverage): r for r in tab.itertuples()}
    guclu = {k for k, r in use.items() if r.USEFUL and r.TRAIN_liq == 0}

    def komsular(k):
        p, l = k
        return [(p, x) for x in KOMSU_L[l]] + [(x, l) for x in KOMSU_P[p]]
    komsu_ciftler = [(k, n) for k in guclu for n in komsular(k) if n in guclu]
    robust = len(komsu_ciftler) > 0
    liq_hepsi = all(r.TEST_liq > 0 for r in tab.itertuples())
    temiz = [r for r in tab.itertuples() if r.TEST_liq == 0]
    konsantr = bool(temiz) and all(r.TEST_minus3_pairs_return <= 0 for r in temiz)
    if ihlal_top:
        hukum = "D"
    elif robust:
        hukum = "A"
    elif liq_hepsi or konsantr:
        hukum = "C"
    else:
        hukum = "B"

    # ── güncel sermaye fizibilitesi (public metadata bu ortamdan erişilemiyor → bilinenler) ──
    bilinmeyen = sorted({c for p in PAIRS for c in p} - set(PDT.MIN_KONTRAT_USD))
    fiz = "UNCERTAIN" if bilinmeyen else "YES"

    ozet = dict(baseline_test=base["TEST"]["m"], baseline_train=base["TRAIN"]["m"], hukum=hukum,
                robust=robust, komsu_ciftler=[list(map(list, x)) for x in komsu_ciftler],
                useful=[list(k) for k, r in use.items() if r.USEFUL], guclu=[list(k) for k in guclu],
                liq_hepsi=liq_hepsi, konsantr=konsantr, ihlal=ihlal_top, fiz=fiz, bilinmeyen=bilinmeyen)
    with open(os.path.join(BURA, "sonuclar.json"), "w") as f:
        json.dump(ozet, f, indent=1, default=str)

    bm = base["TEST"]["m"]
    print("\n" + "=" * 60)
    print("BASELINE TEST:")
    print(f"return {bm['getiri'] * 100:+.1f}%\nmaxDD %{bm['maxdd'] * 100:.1f}\ngiveback {bm['pgr']:.3f}")
    print("\nSCENARIO TABLE:\n")
    print("allocation | leverage | TEST return | maxDD | giveback | liquidations | USEFUL")
    for r in tab.itertuples():
        print(f"{r.allocation:.0%} | {r.leverage}x | {r.TEST_getiri * 100:+.1f}% | %{r.TEST_maxdd * 100:.1f} | "
              f"{r.TEST_pgr:.3f} | {r.TEST_liq} (TRAIN {r.TRAIN_liq}) | {'YES' if r.USEFUL else 'NO'}")
    print(f"\nROBUST REGION:\n{'YES' if robust else 'NO'}")
    print(f"\nCURRENT CAPITAL FEASIBILITY:\n{fiz}")
    print(f"\nHÜKÜM:\n{hukum}")
    return tab, ozet


if __name__ == "__main__":
    main()
