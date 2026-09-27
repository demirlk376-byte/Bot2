"""
pairs_dual_twin.py — PAIRS ALT-HESAP İKİZİ + canlı-birebir ana bot ikizi, KRONOLOJİK ve AYRI HESAP.

Soru: ana bot kârını geri verirken, AYRI alt-hesapta çalışan pairs bunu dengeliyor mu?
Aday DONDURULDU (pairs_spread.py / pairs_verify.py / RESEARCH_LEDGER 2026-08-02); yeniden
optimize edilmez. Önceden sabit tüm kurallar: PAIRS_DUAL_TWIN_REPORT.md.

EXECUTION (eski aynı-kapanış dolumu YASAK):
  Günlük bar D = UTC [D 00:00, D+1 00:00) — MEXC vadeli 1h barlarından (ts = bar AÇILIŞI).
  D'nin kapanışı = 23:00 barının close'u; bilgi zamanı = D+1 00:00.
  Karar (giriş/çıkış) D kapanışından; dolum = bilgi zamanından SONRA başlayan ilk 1h barın
  AÇILIŞI = D+1 01:00 open (bilgi zamanına EŞİT olan 00:00 açılışı kullanılmaz). assert: dolum > bilgi.
  İki bacak aynı bar açılışından dolar (1h çözünürlükte bacak gecikmesi modellenemez — sınır).

HESAPLAR: ACCOUNT_A = ana bot (doğrulanmış 936 işlemlik ikizin saatlik hesap değeri, yeniden
koşulmaz), ACCOUNT_B = pairs. Ayrı equity, ayrı marjin, ayrı pozisyon; aralarında para akışı yok.
Pairs boyutu (eski semantik, normalize): her çift işlemi TOPLAM nominal = B hesabının BAŞLANGIÇ
değeri (bacak başına yarısı), bileşik YOK. 10x izole: işlem marjini = nominal/10; serbest marjin
yetmezse işlem REDDEDİLİR ve PnL'e girmez.

Kullanım (repo kökünden, çevrimdışı; yalnız data/*_fut_1h.csv ve arastirma/ altındaki ikiz kayıtları):
  python3 arastirma/pairs_dual_twin/pairs_dual_twin.py
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BURA = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KOK)

# ───────── DONDURULMUŞ ADAY (değiştirme) ─────────
PAIRS = [("ETC", "ETH"), ("ATOM", "DOT"), ("BTC", "ETH"), ("ADA", "DOT"),
         ("XLM", "XRP"), ("ALGO", "DOT"), ("ADA", "ALGO"), ("ADA", "ATOM")]
ZWIN, Z_IN, Z_OUT, Z_STOP, MAX_HOLD = 60, 2.0, 0.5, 3.5, 20
# ───────── maliyet senaryoları (stres, optimizasyon değil) ─────────
TAKER = 0.0001            # execution.py _close_position_internal / entry_fee_rate taker = 0.0001
SENARYO = {"LOW": 10.0, "BASE": 15.85, "STRESS": 25.0}      # bp adverse slippage / fill
# ───────── hesap / risk ─────────
LEV = 10.0
LIK_ESIK = 0.095          # 10x izole: 1/10 − ~%0.5 bakım marjini → bacakta ~%9.5 ters hareket
SERMAYE = 10000.0         # toplam başlangıç sermayesi (ana ikizin başlangıcı)
BOLME = pd.Timestamp("2025-01-01", tz="UTC")
PGR_MIN_DERINLIK = 0.05
EQ_CSV = os.path.join(KOK, "arastirma", "kar_geri_verme", "equity_saatlik.csv")
TWIN_CSV = os.path.join(KOK, "arastirma", "paylasim_paketi_2026-09-26", "ikiz", "ikiz_k25_cap25_islemler.csv")
H = pd.Timedelta(hours=1)
# canlı küçük sermaye fizibilitesi (probe_hedge2, RESEARCH_LEDGER:3057-3061; min 1 kontrat)
MIN_KONTRAT_USD = {"ADA": 0.21, "ATOM": 0.14, "BTC": 6.45, "ETH": 19.09, "XLM": 1.62, "XRP": 1.04}
CANLI_SERMAYE = 334.02     # 2026-09-27 VPS bakiye okuması


# ─────────────────────────── veri ───────────────────────────
def saatlik():
    coins = sorted({c for p in PAIRS for c in p})
    o, h, l, c = {}, {}, {}, {}
    for k in coins:
        d = pd.read_csv(os.path.join(KOK, "data", f"{k}_fut_1h.csv"))
        d["ts"] = pd.to_datetime(d["ts"], utc=True)
        d = d.drop_duplicates("ts").set_index("ts").sort_index()
        o[k], h[k], l[k], c[k] = d["open"], d["high"], d["low"], d["close"]
    return (pd.DataFrame(o), pd.DataFrame(h), pd.DataFrame(l), pd.DataFrame(c))


def gunluk_kapanis(C):
    """Gün D kapanışı = D 23:00 barının close'u (yalnız o bar VARSA). İndeks = D (UTC gün)."""
    son = C[C.index.hour == 23]
    son.index = son.index.normalize()
    return son


def z_tablosu(G):
    """Her çift için günlük log-oran z'si (yalnız geçmiş: rolling 60, gün D dahil)."""
    out = {}
    for a, b in PAIRS:
        sp = np.log(G[a] / G[b]).dropna()
        mu = sp.rolling(ZWIN).mean()
        sd = sp.rolling(ZWIN).std()
        out[(a, b)] = pd.DataFrame({"sp": sp, "mu": mu, "sd": sd, "z": (sp - mu) / sd})
    return out


# ─────────────────────────── kronolojik ikiz ───────────────────────────
def kos(O, Hh, L, C, Z, slip_bp, E0=1.0, ayni_kapanis=False):
    """Olay güdümlü, saat saat. ayni_kapanis=True YALNIZ eski yöntemi yeniden üretmek için
    (eski kıyas tablosu); ana hüküm hiçbir zaman onu kullanmaz."""
    s = slip_bp / 1e4
    saatler = C.index
    # bilgi anları: her gün D için D+1 00:00; o anda gün D'nin z'si bilinir
    gunler = sorted({d for t in Z.values() for d in t.index})
    bilgi = {d + pd.Timedelta(days=1): d for d in gunler}
    acik = {}            # pair -> pozisyon dict
    bekleyen = []        # (yurutme_zamani, tur, pair, bilgi dict)
    son_cikis_sinyal = {p: None for p in PAIRS}
    islemler, redler = [], []
    realized = 0.0
    eq_seri = np.empty(len(saatler))
    kullanilan_marjin = 0.0
    marj_seri = np.empty(len(saatler))
    nom_seri = np.empty(len(saatler))
    esz_seri = np.empty(len(saatler), dtype=int)
    ihlal = 0

    def dolum(px, yon, al_sat):     # al_sat: +1 alış, −1 satış
        return px * (1 + s) if al_sat > 0 else px * (1 - s)

    for hi, t in enumerate(saatler):
        # 1) bu saatin AÇILIŞINDA yürütülecek emirler
        kalan = []
        for (tz, tur, p, info) in bekleyen:
            if tz != t:
                kalan.append((tz, tur, p, info))
                continue
            a, b = p
            pa, pb = O.at[t, a], O.at[t, b]
            if not (np.isfinite(pa) and np.isfinite(pb)):
                kalan.append((tz + H, tur, p, info))     # veri yoksa bir sonraki bar
                continue
            if tz <= info["bilgi_zamani"] and not ayni_kapanis:
                ihlal += 1
            if tur == "giris":
                nom = E0
                gerek = nom / LEV
                eq_simdi = E0 + realized + _acik_pnl(acik, C, hi, t)
                if eq_simdi - kullanilan_marjin < gerek:
                    redler.append(dict(pair=f"{a}/{b}", zaman=t, neden="serbest marjin yetersiz"))
                    continue
                dA = info["dA"]
                fa = dolum(pa, dA, dA)
                fb = dolum(pb, -dA, -dA)
                acik[p] = dict(pair=f"{a}/{b}", A=a, B=b, dA=dA, dB=-dA, signal_day=info["gun"],
                               signal_time=info["bilgi_zamani"], z_giris=info["z"],
                               mu=info["mu"], sd=info["sd"], giris_t=t, fa=fa, fb=fb,
                               qa=(nom / 2) / fa, qb=(nom / 2) / fb, nom=nom, marj=gerek,
                               mae_a=0.0, mae_b=0.0, ref_a=pa, ref_b=pb)
                kullanilan_marjin += gerek
            else:
                pos = acik.pop(p, None)
                if pos is None:
                    continue
                xa = dolum(pa, pos["dA"], -pos["dA"])
                xb = dolum(pb, pos["dB"], -pos["dB"])
                brut_a = pos["dA"] * (pa - pos["ref_a"]) * pos["qa"]
                brut_b = pos["dB"] * (pb - pos["ref_b"]) * pos["qb"]
                net_a = pos["dA"] * (xa - pos["fa"]) * pos["qa"]
                net_b = pos["dB"] * (xb - pos["fb"]) * pos["qb"]
                ucret = TAKER * (pos["fa"] * pos["qa"] + pos["fb"] * pos["qb"] + xa * pos["qa"] + xb * pos["qb"])
                net = net_a + net_b - ucret
                realized += net
                kullanilan_marjin -= pos["marj"]
                islemler.append(dict(
                    pair_id=pos["pair"], A=pos["A"], B=pos["B"],
                    direction_A="long" if pos["dA"] > 0 else "short",
                    direction_B="long" if pos["dB"] > 0 else "short",
                    signal_day=pos["signal_day"].date(), signal_time=pos["signal_time"],
                    z=pos["z_giris"], rolling_mu=pos["mu"], rolling_sd=pos["sd"],
                    entry_time_A=pos["giris_t"], entry_time_B=pos["giris_t"],
                    entry_A=pos["fa"], entry_B=pos["fb"],
                    exit_signal_day=info["gun"].date(), exit_time_A=t, exit_time_B=t,
                    exit_A=xa, exit_B=xb, notional=pos["nom"],
                    gross_pair_return=(brut_a + brut_b) / pos["nom"],
                    fees=ucret / pos["nom"],
                    slippage=((brut_a + brut_b) - (net_a + net_b)) / pos["nom"],
                    net_pair_return=net / pos["nom"], pnl=net,
                    exit_reason=info["neden"], hold_days=(info["gun"] - pos["signal_day"]).days,
                    mae_A=pos["mae_a"], mae_B=pos["mae_b"]))
                son_cikis_sinyal[p] = info["gun"]
        bekleyen = kalan

        # 2) bu saatin barı boyunca: açık pozisyonların MAE'si (dolumdan sonra, dahil)
        for p, pos in acik.items():
            a, b = p
            for k, dk, fk, mk in ((a, pos["dA"], pos["fa"], "mae_a"), (b, pos["dB"], pos["fb"], "mae_b")):
                hi_, lo_ = Hh.at[t, k], L.at[t, k]
                if np.isfinite(hi_) and np.isfinite(lo_):
                    ters = (fk - lo_) / fk if dk > 0 else (hi_ - fk) / fk
                    pos[mk] = max(pos[mk], ters)

        # 3) saat sonu değerleme
        eq_seri[hi] = E0 + realized + _acik_pnl(acik, C, hi, t)
        marj_seri[hi] = kullanilan_marjin
        nom_seri[hi] = sum(x["nom"] for x in acik.values())
        esz_seri[hi] = len(acik)

        # 4) bilgi anı: bir sonraki saatin başı (t+1h) = gün D kapanışı bilindi
        bt = t + H
        if bt in bilgi:
            D = bilgi[bt]
            yurut = bt if ayni_kapanis else bt + H     # dolum: bilgi anından SONRA başlayan ilk bar
            for p in PAIRS:
                zt = Z[p]
                if D not in zt.index:
                    continue
                zz = zt.at[D, "z"]
                if p in acik:
                    pos = acik[p]
                    if any(x[2] == p for x in bekleyen):
                        continue
                    tut = (D - pos["signal_day"]).days
                    neden = None
                    if np.isfinite(zz) and abs(zz) < Z_OUT:
                        neden = "z_out"
                    elif np.isfinite(zz) and abs(zz) > Z_STOP:
                        neden = "z_stop"
                    elif tut >= MAX_HOLD:
                        neden = "max_hold"
                    if neden:
                        bekleyen.append((yurut, "cikis", p, dict(gun=D, bilgi_zamani=bt, neden=neden)))
                else:
                    if any(x[2] == p for x in bekleyen):
                        continue
                    if son_cikis_sinyal[p] is not None and D <= son_cikis_sinyal[p]:
                        continue      # eski semantik: çıkış günü j ise yeni sinyal j+1'den
                    if np.isfinite(zz) and abs(zz) >= Z_IN:
                        bekleyen.append((yurut, "giris", p, dict(
                            gun=D, bilgi_zamani=bt, z=float(zz), mu=float(zt.at[D, "mu"]),
                            sd=float(zt.at[D, "sd"]), dA=-1 if zz > 0 else +1)))

    eq = pd.Series(eq_seri, index=saatler)
    ek = pd.DataFrame({"margin": marj_seri, "gross_notional": nom_seri, "eszamanli": esz_seri},
                      index=saatler)
    return pd.DataFrame(islemler), eq, ek, pd.DataFrame(redler), ihlal, len(acik)


def _acik_pnl(acik, C, hi, t):
    tot = 0.0
    for (a, b), pos in acik.items():
        ca, cb = C.at[t, a], C.at[t, b]
        if np.isfinite(ca):
            tot += pos["dA"] * (ca - pos["fa"]) * pos["qa"]
        if np.isfinite(cb):
            tot += pos["dB"] * (cb - pos["fb"]) * pos["qb"]
    return tot


# ─────────────────────────── metrikler ───────────────────────────
def epizodlar(v, z):
    """kar_geri_verme_risk_test.epizodlar ile aynı mantık (dizi girişli)."""
    n = len(v)
    out, i, tepe = [], 0, 0
    while i < n:
        if v[i] >= v[tepe]:
            tepe = i; i += 1; continue
        j = i
        while j < n and v[j] < v[tepe]:
            j += 1
        dip = tepe + int(np.argmin(v[tepe:j]))
        out.append(dict(tepe_i=tepe, dip_i=dip, geri_i=(j if j < n else None),
                        tepe=float(v[tepe]), dip=float(v[dip]), dusus=float(1 - v[dip] / v[tepe]),
                        tepe_z=z[tepe], dip_z=z[dip], geri_z=(z[j] if j < n else None)))
        tepe = j if j < n else tepe; i = j
    return out


def pgr(v, epi):
    """PROFIT GIVEBACK — kar_geri_verme_risk_test.pgr ile AYNI formül (≥%5 epizod)."""
    say = [x for x in epi if x["dusus"] >= PGR_MIN_DERINLIK]
    pay = payda = 0.0; onceki = 0
    for x in say:
        B = float(v[onceki:x["tepe_i"] + 1].min())
        pay += np.log(x["tepe"] / x["dip"]); payda += np.log(x["tepe"] / B)
        onceki = x["tepe_i"]
    return float(pay / payda) if payda > 0 else float("nan")


def portfoy_metrik(eq):
    v = eq.to_numpy(float); z = eq.index
    epi = epizodlar(v, z)
    ay = eq.resample("ME").last()
    ay_ret = ay.pct_change()
    ay_ret.iloc[0] = ay.iloc[0] / v[0] - 1
    yil = (z[-1] - z[0]).total_seconds() / (365.25 * 86400)
    tepe = np.maximum.accumulate(v)
    dd = 1 - v / tepe
    en = max(epi, key=lambda x: x["dusus"]) if epi else None
    alti = (dd > 0).sum() / 24.0
    son = (v[-1] / v[0])
    return dict(
        final=v[-1], getiri=son - 1, cagr=son ** (1 / yil) - 1 if yil > 0 else float("nan"),
        maxdd=float(dd.max()), maxdd_usd=float((tepe - v).max()),
        en_kotu_ay=float(ay_ret.min()), medyan_ay=float(ay_ret.median()),
        pozitif_ay=float((ay_ret > 0).mean() * 100),
        getiri_dd=(son - 1) / dd.max() if dd.max() > 0 else float("nan"),
        toparlanma_gun=((en["geri_z"] - en["tepe_z"]).total_seconds() / 86400
                        if en and en["geri_z"] is not None else float("nan")),
        pgr=pgr(v, epi), sualti_gun=float(alti))


def pairs_ozet(tr, eq, E0=1.0):
    if tr.empty:
        return dict(n=0)
    p = tr["pnl"].to_numpy()
    gp, gl = p[p > 0].sum(), -p[p < 0].sum()
    yil = pd.to_datetime(tr["signal_day"]).dt.year
    sig = pd.to_datetime(tr["signal_time"])
    v = eq.to_numpy()
    tepe = np.maximum.accumulate(v)
    ay = eq.resample("ME").last()
    ay_ret = ay.diff() / ay.shift(1)
    ay_ret.iloc[0] = ay.iloc[0] / E0 - 1
    return dict(n=len(tr), ort=float(tr["net_pair_return"].mean()), pf=gp / gl if gl > 0 else float("inf"),
                wr=float((p > 0).mean() * 100), toplam=float(p.sum() / E0),
                train=float(tr.loc[(sig < BOLME).to_numpy(), "pnl"].sum() / E0),
                test=float(tr.loc[(sig >= BOLME).to_numpy(), "pnl"].sum() / E0),
                maxdd=float((1 - v / tepe).max()), en_kotu_ay=float(ay_ret.min()),
                pozitif_ay=float((ay_ret > 0).mean() * 100),
                yillar={int(y): float(tr.loc[(yil == y).to_numpy(), "pnl"].sum() / E0) for y in sorted(yil.unique())},
                cikis=tr["exit_reason"].value_counts().to_dict())


# ─────────────────────────── ana akış ───────────────────────────
def main():
    O, Hh, L, C = saatlik()
    G = gunluk_kapanis(C)
    Z = z_tablosu(G)
    sonuc = {}
    kosular = {}
    for ad, bp in SENARYO.items():
        kosular[ad] = kos(O, Hh, L, C, Z, bp)
    kosular["ESKI_AYNI_KAPANIS_4bp"] = kos(O, Hh, L, C, Z, 0.0, ayni_kapanis=True)
    kosular["YENI_SONRAKI_BAR_4bp"] = kos(O, Hh, L, C, Z, 0.0)

    ihlaller = {k: v[4] for k, v in kosular.items() if not k.startswith("ESKI")}
    tr_base, eq_base, ek_base, red_base, ihlal_base, acik_son = kosular["BASE"]
    # audit: dolum > bilgi
    if not tr_base.empty:
        assert (pd.to_datetime(tr_base["entry_time_A"]) > pd.to_datetime(tr_base["signal_time"])).all()
    tr_base.to_csv(os.path.join(BURA, "pairs_trades.csv"), index=False)

    ozet = {k: pairs_ozet(v[0], v[1]) for k, v in kosular.items()}

    # ── ana bot hesabı (doğrulanmış ikiz; yeniden koşulmaz) ──
    me = pd.read_csv(EQ_CSV, usecols=["zaman", "hesap_degeri"])
    me["zaman"] = pd.to_datetime(me["zaman"], utc=True)
    main_eq = me.set_index("zaman")["hesap_degeri"]
    ortak = main_eq.index.intersection(eq_base.index)
    main_eq = main_eq.loc[ortak]
    pe = eq_base.reindex(ortak).ffill()                       # birim E0=1 pairs hesabı
    # aylık getiriler
    m_ay = main_eq.resample("ME").last()
    m_ret = m_ay.pct_change(); m_ret.iloc[0] = m_ay.iloc[0] / main_eq.iloc[0] - 1
    p_ay = pe.resample("ME").last()
    p_ret = p_ay.diff() / p_ay.shift(1); p_ret.iloc[0] = p_ay.iloc[0] / pe.iloc[0] - 1
    ay = pd.DataFrame({"main": m_ret, "pairs": p_ret}).dropna()
    pear = float(ay["main"].corr(ay["pairs"]))
    spear = float(ay["main"].rank().corr(ay["pairs"].rank()))
    tr_ay = ay[ay.index < BOLME]
    s_m, s_p = tr_ay["main"].std(), tr_ay["pairs"].std()
    w_m = (1 / s_m) / (1 / s_m + 1 / s_p); w_p = 1 - w_m
    # iki hesap: bağımsız yollar, para akışı yok
    A_eq = w_m * SERMAYE * main_eq / main_eq.iloc[0]
    B0 = w_p * SERMAYE
    B_eq = B0 * pe / pe.iloc[0]                                # sabit nominal = B0 (bileşik yok)
    dual = A_eq + B_eq
    base = SERMAYE * main_eq / main_eq.iloc[0]
    aylik = pd.DataFrame({"main_ret": ay["main"], "pairs_ret": ay["pairs"],
                          "baseline_eq": base.resample("ME").last(), "dual_eq": dual.resample("ME").last(),
                          "A_eq": A_eq.resample("ME").last(), "B_eq": B_eq.resample("ME").last()})
    aylik["dual_ret"] = aylik["dual_eq"].pct_change()
    aylik.iloc[0, aylik.columns.get_loc("dual_ret")] = aylik["dual_eq"].iloc[0] / SERMAYE - 1
    aylik["B_pnl_usd"] = aylik["B_eq"].diff().fillna(aylik["B_eq"].iloc[0] - B0)
    aylik.to_csv(os.path.join(BURA, "combined_monthly.csv"))

    def bol(s):
        return {"TUM": s, "TRAIN": s[s.index < BOLME], "TEST": s[s.index >= BOLME]}

    metr = {ad: {k: portfoy_metrik(v) for k, v in bol(s).items()} for ad, s in (("BASELINE", base), ("DUAL", dual))}

    neg = aylik[aylik["main_ret"] < 0]
    en_kotu5 = aylik.nsmallest(5, "main_ret")[["main_ret", "pairs_ret", "dual_ret"]]

    # ── büyük düşüş epizodları (baseline) ──
    epi = sorted(epizodlar(base.to_numpy(), base.index), key=lambda x: -x["dusus"])[:5]
    dv = dual.to_numpy(); di = dual.index
    epi_rows = []
    for x in epi:
        pk, tg = dv[x["tepe_i"]], dv[x["dip_i"]]
        seg = dv[x["tepe_i"]:x["dip_i"] + 1]
        sonra = np.where(dv[x["tepe_i"]:] >= pk)[0]
        geri = sonra[sonra > 0]
        epi_rows.append(dict(
            peak=x["tepe_z"], trough=x["dip_z"], baseline_dd_pct=x["dusus"] * 100,
            dual_dd_pct=(1 - tg / pk) * 100, dual_max_dd_in_window_pct=(1 - seg.min() / pk) * 100,
            baseline_usd=x["dip"] - x["tepe"], dual_usd=tg - pk,
            baseline_recovery_days=((x["geri_z"] - x["tepe_z"]).total_seconds() / 86400 if x["geri_z"] is not None else None),
            dual_recovery_days=((di[x["tepe_i"] + geri[0]] - x["tepe_z"]).total_seconds() / 86400 if len(geri) else None)))
    pd.DataFrame(epi_rows).to_csv(os.path.join(BURA, "drawdown_episodes.csv"), index=False)

    # ── en iyi işlemleri çıkarma (BASE) ──
    cikar = {}
    t2 = tr_base.sort_values("pnl", ascending=False)
    for k in (0, 1, 3, 5, 10):
        r = t2.iloc[k:]
        sig = pd.to_datetime(r["signal_time"])
        yl = pd.to_datetime(r["signal_day"]).dt.year
        yy = {int(y): float(r.loc[(yl == y).to_numpy(), "pnl"].sum()) for y in (2023, 2024, 2025, 2026)}
        cikar[k] = dict(toplam=float(r["pnl"].sum()), test=float(r.loc[(sig >= BOLME).to_numpy(), "pnl"].sum()),
                        yil_pozitif=sum(v > 0 for v in yy.values()), yillar=yy)

    # ── çift bazında ──
    cift = {}
    for pid, g in tr_base.groupby("pair_id"):
        p = g["pnl"].to_numpy(); yl = pd.to_datetime(g["signal_day"]).dt.year
        cift[pid] = dict(n=len(g), toplam=float(p.sum()),
                         pf=float(p[p > 0].sum() / -p[p < 0].sum()) if (p < 0).any() else float("inf"),
                         yillar={int(y): float(g.loc[(yl == y).to_numpy(), "pnl"].sum()) for y in (2023, 2024, 2025, 2026)})

    # ── marjin / likidasyon ──
    lik = tr_base[(tr_base["mae_A"] >= LIK_ESIK) | (tr_base["mae_B"] >= LIK_ESIK)]
    mae_max = float(np.nanmax(tr_base[["mae_A", "mae_B"]].to_numpy())) if not tr_base.empty else float("nan")
    guvenli_kaldirac = (1 / (mae_max + 0.005)) if np.isfinite(mae_max) else float("nan")

    # ── canlı küçük sermaye fizibilitesi ──
    B_canli = w_p * CANLI_SERMAYE
    bacak = B_canli / 2
    fiz = {}
    for k, mn in MIN_KONTRAT_USD.items():
        n_k = bacak / mn
        fiz[k] = dict(kontrat=n_k, yuvarlama_hatasi=((n_k - np.floor(n_k)) / n_k if n_k >= 1 else 1.0))
    bilinmeyen = sorted({c for p in PAIRS for c in p} - set(MIN_KONTRAT_USD))
    if any(v["kontrat"] < 1 for v in fiz.values()):
        fiz_h = "NO"
    elif bilinmeyen or any(v["yuvarlama_hatasi"] > 0.10 for v in fiz.values()):
        fiz_h = "UNCERTAIN"
    else:
        fiz_h = "YES"

    # ── karar (önceden sabit) ──
    b = ozet["BASE"]
    yil4 = all(b["yillar"].get(y, 0) > 0 for y in (2023, 2024, 2025, 2026))
    bt, dt_ = metr["BASELINE"]["TEST"], metr["DUAL"]["TEST"]
    k = {
        1: b["train"] > 0, 2: b["test"] > 0, 3: yil4, 4: b["pf"] >= 1.20,
        5: pear <= 0.20, 6: float(neg["pairs_ret"].sum()) > 0,
        7: dt_["maxdd"] < bt["maxdd"], 8: dt_["getiri_dd"] >= bt["getiri_dd"],
        9: ozet["STRESS"]["ort"] >= 0, 10: len(lik) == 0,
    }
    ihlal_top = sum(ihlaller.values())
    if ihlal_top or acik_son < 0:
        hukum = "D"
    elif not all(k[i] for i in (1, 2, 3, 4)):
        hukum = "C"
    elif all(k.values()):
        hukum = "A"
    else:
        hukum = "B"

    sonuc = dict(ozet=ozet, ihlaller=ihlaller, pear=pear, spear=spear, w_m=w_m, w_p=w_p,
                 s_m=float(s_m), s_p=float(s_p), metr=metr,
                 neg=dict(n=len(neg), pairs_pozitif=int((neg["pairs_ret"] > 0).sum()),
                          pairs_toplam_usd=float(neg["B_pnl_usd"].sum()),
                          pairs_toplam_ret=float(neg["pairs_ret"].sum())),
                 en_kotu5=en_kotu5.reset_index().astype(str).to_dict("records"),
                 epizod=epi_rows, cikar=cikar, cift=cift, kriter=k, hukum=hukum,
                 red=len(red_base), max_esz=int(ek_base["eszamanli"].max()),
                 max_nom=float(ek_base["gross_notional"].max()), max_marj=float(ek_base["margin"].max()),
                 lik_n=len(lik), mae_max=mae_max, guvenli_kaldirac=guvenli_kaldirac,
                 fiz=fiz, fiz_h=fiz_h, B_canli=B_canli, bilinmeyen=bilinmeyen, ay_n=len(ay))
    with open(os.path.join(BURA, "sonuclar.json"), "w") as f:
        json.dump(sonuc, f, indent=1, default=str, ensure_ascii=False)
    yaz(sonuc)
    return sonuc


def yaz(S):
    o = S["ozet"]

    def satir(ad):
        x = o[ad]
        y = " ".join(f"{k}:{v * 100:+.1f}%" for k, v in x["yillar"].items())
        return (f"  {ad:<22s} n={x['n']:>3d} ort {x['ort'] * 100:+.3f}% PF {x['pf']:.2f} WR %{x['wr']:.1f} "
                f"toplam {x['toplam'] * 100:+.1f}% TRAIN {x['train'] * 100:+.1f}% TEST {x['test'] * 100:+.1f}% "
                f"maxDD %{x['maxdd'] * 100:.1f} en kötü ay {x['en_kotu_ay'] * 100:+.1f}% poz.ay %{x['pozitif_ay']:.0f} | {y}")
    print("== PAIRS TEK BAŞINA (getiriler pairs hesabının başlangıç değerine göre; bileşik yok)")
    for ad in ("ESKI_AYNI_KAPANIS_4bp", "YENI_SONRAKI_BAR_4bp", "LOW", "BASE", "STRESS"):
        print(satir(ad))
    print(f"  BASE çıkışları: {o['BASE']['cikis']}")
    print("\n== ÇİFT BAZINDA (BASE; betimsel, seçim yok) — $ birim hesap=1")
    for pid, c in S["cift"].items():
        print(f"  {pid:<9s} n={c['n']:>3d} toplam {c['toplam'] * 100:+.1f}% PF {c['pf']:.2f} "
              + " ".join(f"{y}:{v * 100:+.1f}%" for y, v in c["yillar"].items()))
    print("\n== EN İYİ İŞLEMLER ÇIKARILINCA (BASE)")
    for k, c in S["cikar"].items():
        print(f"  −{k:<2d} toplam {c['toplam'] * 100:+.1f}% TEST {c['test'] * 100:+.1f}% yıl+ {c['yil_pozitif']}/4")
    print(f"\n== MARJİN/LİKİDASYON (BASE): red {S['red']} · max eşzamanlı çift {S['max_esz']} · "
          f"max brüt nominal {S['max_nom']:.2f}×B0 · max marjin {S['max_marj']:.2f}×B0 · "
          f"likidasyon eşiği (%{LIK_ESIK * 100:.1f} ters bacak) aşan işlem {S['lik_n']} · "
          f"en büyük bacak MAE %{S['mae_max'] * 100:.1f} (→ güvenli kaldıraç ≈ {S['guvenli_kaldirac']:.1f}x)")
    print(f"\n== KORELASYON ({S['ay_n']} ay): Pearson {S['pear']:+.3f} Spearman {S['spear']:+.3f}")
    print(f"   TRAIN aylık std: ana {S['s_m'] * 100:.2f}% pairs {S['s_p'] * 100:.2f}% → w_main {S['w_m']:.3f} w_pairs {S['w_p']:.3f}")
    for ad in ("BASELINE", "DUAL"):
        for per in ("TUM", "TRAIN", "TEST"):
            m = S["metr"][ad][per]
            print(f"  {ad:<8s} {per:<5s} getiri {m['getiri'] * 100:+.1f}% CAGR {m['cagr'] * 100:+.1f}% maxDD %{m['maxdd'] * 100:.1f} "
                  f"(${m['maxdd_usd']:,.0f}) en kötü ay {m['en_kotu_ay'] * 100:+.1f}% medyan ay {m['medyan_ay'] * 100:+.1f}% "
                  f"poz.ay %{m['pozitif_ay']:.0f} getiri/DD {m['getiri_dd']:.2f} toparlanma {m['toparlanma_gun']:.0f}g "
                  f"PGR {m['pgr']:.3f} sualtı {m['sualti_gun']:.0f}g")
    print(f"\n== EPİZODLAR: {json.dumps(S['epizod'], default=str)[:10]}… (drawdown_episodes.csv)")
    print(f"KRİTERLER: {S['kriter']}")
    son_ozet(S)


def son_ozet(S):
    o, b, st = S["ozet"], S["ozet"]["BASE"], S["ozet"]["STRESS"]
    bt, dt = S["metr"]["BASELINE"]["TEST"], S["metr"]["DUAL"]["TEST"]
    e0 = S["epizod"][0] if S["epizod"] else {}
    etiket = {"A": "PASS", "B": "FAIL", "C": "FAIL", "D": "INVALID"}[S["hukum"]]
    print("\n" + "=" * 60)
    print(f"PAIRS DUAL TWIN: {etiket}")
    print("\nEXECUTION:\nsame-close used? NO\nnext-executable fill? YES (D+1 01:00 1h açılışı)")
    print(f"lookahead violations: {sum(S['ihlaller'].values())}")
    print("\nPAIRS BASE COST:")
    print(f"trades: {b['n']}\nPF: {b['pf']:.2f}\nTRAIN: {b['train'] * 100:+.1f}%\nTEST: {b['test'] * 100:+.1f}%")
    for y in (2023, 2024, 2025, 2026):
        print(f"{y}: {b['yillar'].get(y, 0) * 100:+.1f}%")
    print(f"maxDD: %{b['maxdd'] * 100:.1f}")
    print(f"\nPAIRS STRESS 25bp:\nPF: {st['pf']:.2f}\nTEST: {st['test'] * 100:+.1f}%\ntotal: {st['toplam'] * 100:+.1f}%")
    print(f"\nMONTHLY CORRELATION:\nPearson: {S['pear']:+.3f}\nSpearman: {S['spear']:+.3f}")
    print(f"\nMAIN NEGATIVE MONTHS:\ncount: {S['neg']['n']}\npairs positive: {S['neg']['pairs_pozitif']}")
    print(f"pairs total contribution: ${S['neg']['pairs_toplam_usd']:+,.0f} (pairs hesabı getirisi toplamı {S['neg']['pairs_toplam_ret'] * 100:+.1f}%)")
    print(f"\nTRAIN-FROZEN WEIGHTS:\nmain: {S['w_m']:.3f}\npairs: {S['w_p']:.3f}")
    print(f"\nBASELINE TEST:\nreturn: {bt['getiri'] * 100:+.1f}%\nmaxDD: %{bt['maxdd'] * 100:.1f}\nprofit giveback: {bt['pgr']:.3f}")
    print(f"\nDUAL-ACCOUNT TEST:\nreturn: {dt['getiri'] * 100:+.1f}%\nmaxDD: %{dt['maxdd'] * 100:.1f}\nprofit giveback: {dt['pgr']:.3f}")
    print(f"\nWORST DRAWDOWN:\nbaseline %{e0.get('baseline_dd_pct', float('nan')):.1f} -> dual %{e0.get('dual_dd_pct', float('nan')):.1f}")
    print(f"\nMARGIN REJECTS:\n{S['red']}")
    print(f"\nCURRENT-CAPITAL FEASIBILITY:\n{S['fiz_h']}")
    print(f"\nHÜKÜM:\n{S['hukum']}")


if __name__ == "__main__":
    main()
