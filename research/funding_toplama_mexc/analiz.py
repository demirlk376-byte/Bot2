#!/usr/bin/env python3
"""Funding toplama (delta-notr, FC_T1 dondurulmus) — UYGULAMA A.

On kayit: /home/user/sweep/research/funding_toplama_mexc/ON_KAYIT.md (birebir; parametre secimi yok).
Calistir: python3 -I analiz.py   (ciktilar yalnizca bu dosyanin klasorune yazilir)

Kural: her Pazartesi 00:00 UTC, (M-7g, M] araligindaki settlement'larin ortalamasi >= 1 bp/8s olan
(en az 3 settlement) coinlerden ortalamasi en yuksek en fazla 6 coin secilir; secili kalan tutulur,
dusen kapatilir, yeni giren acilir. Pozisyon 1000 USDT notional, sermaye 6 x 1500 = 9000 (sabit payda).
Funding: acilis Pazartesisinden KESIN sonra, kapanis Pazartesisi (ya da donem sonu) DAHIL settlement'lar.
Maliyet: her acilis ve her kapanista notional x (NORMAL 17.5 bp | STRESS 39.2 bp). Donem sonunda acik
pozisyonlar kapatilir (kapanis maliyeti son aya yazilir, pro_v9 FC_T1 ile ayni).

Sayisal not: oranlar 1e-10 tamsayi biriminde tutulur (veri 1e-10 izgarasinda); esik ve siralama tam
(Fraction) aritmetikle yapilir -> 0.0001 tabanli esitlikler float gurultusune bagli degildir.
Esitlik bozma (on kayitta tanimsiz): ortalama azalan, sonra coin adi (alfabetik) — pro_v9'daki kararli
siralamayla ayni mantik. Duyarlilik icin "mevcut pozisyon onde" varyanti da raporlanir (karar degil).
"""
from __future__ import annotations

import glob
import json
import os
import sqlite3
from fractions import Fraction

import numpy as np
import pandas as pd

ROOT = "/home/user/sweep"
DIR_A = f"{ROOT}/research_data/liquidity_sweep_v1/veri/mexc_funding"
DIR_B = f"{ROOT}/research_data/h4_kirilim_v6/veri"
DB = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/ikiz_kanit/ikiz_gercek.db"
OUT = os.path.dirname(os.path.abspath(__file__))

COINS_A = ["SOL", "ETH", "ADA", "NEAR", "BCH", "XRP", "DOGE", "TRX", "XLM", "LTC", "ICP", "BNB"]
UNIT = 1e-10                      # oran tamsayi birimi
THETA = Fraction(1, 10_000)       # 0.0001 = 1 bp / 8s  (DONDURULMUS)
THETA_U = 1_000_000               # THETA / UNIT
MIN_N = 3                         # en az settlement
TOPN = 6
NOTIONAL = 1000.0
CAPITAL = TOPN * NOTIONAL * 1.5   # 9000 (ayrilan sermaye; bosta duran dahil)
COST_BP = {"NORMAL": 5 + 2.5 + 2 * 5.0,      # 17.5 bp / islem (acilis ya da kapanis)
           "STRESS": 5 + 2.5 + 2 * 15.85}    # 39.2 bp
DAY = 86_400_000
END_EXCL = pd.Timestamp("2026-10-01")        # donem sonu: 2026-09-30 dahil (UTC); 2026-10-01 00:00 haric
END_MS = int(END_EXCL.value // 10**6) - 1    # son dahil an (ms)
START_B = pd.Timestamp("2023-01-02")         # ilk Pazartesi
CORR_MONTHS = ("2023-05", "2026-06")
CORR_MONTHS_PREREG = ("2023-04", "2026-07")  # on kayittaki genis aralik (ek bilgi)


def ms(ts: pd.Timestamp) -> int:
    return int(ts.value // 10**6)


def load_coin(path: str) -> pd.DataFrame:
    d = pd.read_csv(path)
    tcol = "settleTime" if "settleTime" in d.columns else "calc_time"
    rcol = "fundingRate" if "fundingRate" in d.columns else "last_funding_rate"
    d = d[[tcol, rcol]].dropna()
    t = ((d[tcol].astype("int64") + 30_000) // 60_000) * 60_000          # en yakin dakikaya yuvarla
    u = np.rint(d[rcol].astype(float).to_numpy() / UNIT).astype("int64")
    s = pd.DataFrame({"t": t.to_numpy(), "u": u})
    s = s.sort_values("t", kind="mergesort").drop_duplicates("t", keep="last").reset_index(drop=True)
    return s


def load_A() -> dict:
    return {c: load_coin(f"{DIR_A}/{c}.csv") for c in COINS_A}


def load_B() -> dict:
    files = sorted(glob.glob(f"{DIR_B}/*_funding.csv"))
    return {os.path.basename(f)[: -len("_funding.csv")]: load_coin(f) for f in files}


def start_A(data: dict) -> pd.Timestamp:
    first = max(int(df.t.iloc[0]) for df in data.values())
    t = pd.Timestamp(first + 7 * DAY, unit="ms")
    m = t.normalize()
    if m < t:
        m += pd.Timedelta(days=1)
    while m.weekday() != 0:
        m += pd.Timedelta(days=1)
    return m


def simulate(data: dict, start: pd.Timestamp, tiebreak: str = "alpha", arith: str = "exact"):
    """Haftalik dongu (Pazartesiler). Donus: funding defteri, islem defteri, haftalik secimler, teshis."""
    names = sorted(data)
    T = {n: data[n].t.to_numpy() for n in names}
    U = {n: data[n].u.to_numpy() for n in names}
    mondays = pd.date_range(start, pd.Timestamp(END_MS, unit="ms"), freq="W-MON")
    assert mondays[0] == start
    held: list[str] = []
    fund, trades, weeks = [], [], []
    ties_cut = 0
    knife = 0                                              # secilebilir coin-hafta: ortalama TAM olarak = esik
    for i, M in enumerate(mondays):
        m = ms(M)
        nxt = ms(mondays[i + 1]) if i + 1 < len(mondays) else END_MS
        sc = {}
        for n in names:
            a = np.searchsorted(T[n], m - 7 * DAY, side="right")
            b = np.searchsorted(T[n], m, side="right")
            k = int(b - a)
            if k >= MIN_N:
                if arith == "exact":
                    s = int(U[n][a:b].sum())
                    if s >= THETA_U * k:                   # ortalama >= 0.0001 (tam aritmetik)
                        sc[n] = Fraction(s, k)
                        knife += int(s == THETA_U * k)
                else:                                      # duyarlilik: pro_v9 tarzi float np.mean >= 1e-4
                    r = np.mean(U[n][a:b] * UNIT)
                    if r >= float(THETA):
                        sc[n] = float(r)
        if tiebreak == "alpha":
            order = sorted(sc, key=lambda n: (-sc[n], n))
        else:                                              # duyarlilik: esitlikte mevcut pozisyon onde
            order = sorted(sc, key=lambda n: (-sc[n], 0 if n in held else 1, n))
        if len(order) > TOPN and sc[order[TOPN - 1]] == sc[order[TOPN]]:
            ties_cut += 1
        sel = order[:TOPN]
        for n in held:
            if n not in sel:
                trades.append((m, n, "close"))
        for n in sel:
            if n not in held:
                trades.append((m, n, "open"))
        held = sorted(sel)
        weeks.append(dict(monday=M.strftime("%Y-%m-%d"), n_eligible=len(sc), n_held=len(held),
                          held=" ".join(held),
                          means_bp=" ".join(f"{n}:{float(sc[n]) * (UNIT if arith == 'exact' else 1) * 1e4:.3f}"
                                            for n in order[:TOPN])))
        for n in held:                                     # funding: (M, sonraki Pazartesi] ya da donem sonu
            a = np.searchsorted(T[n], m, side="right")
            b = np.searchsorted(T[n], nxt, side="right")
            for t, u in zip(T[n][a:b], U[n][a:b]):
                fund.append((int(t), n, int(u)))
    for n in held:                                         # donem sonu: kapat
        trades.append((END_MS, n, "close"))
    fund = pd.DataFrame(fund, columns=["t", "coin", "u"])
    trades = pd.DataFrame(trades, columns=["t", "coin", "side"])
    return fund, trades, pd.DataFrame(weeks), dict(ties_at_cutoff_weeks=ties_cut, n_weeks=len(mondays),
                                                    eligible_coin_weeks_mean_exactly_theta=knife)


def month_of(t_ms: pd.Series) -> pd.Series:
    return pd.to_datetime(t_ms, unit="ms").dt.strftime("%Y-%m")


def monthly(fund, trades, start, scen):
    months = pd.period_range(start.to_period("M"), pd.Timestamp(END_MS, unit="ms").to_period("M"), freq="M")
    idx = [str(p) for p in months]
    f = (fund.u * UNIT * NOTIONAL).groupby(month_of(fund.t)).sum().reindex(idx, fill_value=0.0)
    c = (trades.assign(x=NOTIONAL * COST_BP[scen] * 1e-4).groupby(month_of(trades.t)).x.sum()
         .reindex(idx, fill_value=0.0))
    df = pd.DataFrame({"funding_usdt": f, "cost_usdt": c})
    df["pnl_usdt"] = df.funding_usdt - df.cost_usdt
    df["ret_pct"] = df.pnl_usdt / CAPITAL * 100
    m0 = [p.start_time for p in months]
    m1 = [p.end_time for p in months]
    df["complete"] = [(a >= start) and (b < END_EXCL) for a, b in zip(m0, m1)]
    return df


def summarize(df, trades, weeks, start, period, scen):
    comp = df[df.complete]
    days = (END_EXCL - start).days
    return dict(
        period=period, cost=scen,
        annual_pct=round(float(df.ret_pct.mean() * 12), 4),                       # tum aylar ort. x 12
        annual_pct_complete=round(float(comp.ret_pct.mean() * 12), 4),            # tam aylar ort. x 12
        annual_pct_total_over_years=round(float(df.pnl_usdt.sum() / CAPITAL * 100 / (days / 365.25)), 4),
        pos_month_share=round(float((comp.ret_pct > 0).mean()), 4),               # tam aylar
        pos_month_share_all=round(float((df.ret_pct > 0).mean()), 4),
        worst_month_pct=round(float(df.ret_pct.min()), 4),
        worst_month=str(df.ret_pct.idxmin()),
        worst_complete_month_pct=round(float(comp.ret_pct.min()), 4),
        avg_positions=round(float(weeks.n_held.mean()), 4),
        rotations=int((trades.side == "open").sum()),                            # acilis sayisi
        closes=int((trades.side == "close").sum()),
        months=int(len(df)), complete_months=int(len(comp)),
        total_pnl_usdt=round(float(df.pnl_usdt.sum()), 4),
        total_funding_usdt=round(float(df.funding_usdt.sum()), 4),
        total_cost_usdt=round(float(df.cost_usdt.sum()), 4),
        weeks_with_zero_positions=int((weeks.n_held == 0).sum()),
        n_weeks=int(len(weeks)),
    )


def donchian_monthly() -> pd.Series:
    con = sqlite3.connect(f"file:{DB}?immutable=1", uri=True)    # salt okunur
    d = pd.read_sql("select entry_price, quantity, exit_time, pnl_usdt, strategy_scores from trades", con)
    con.close()
    js = d.strategy_scores.map(lambda s: json.loads(s) if s else {})
    d = d[js.map(lambda j: j.get("strategy") == "donchian")].copy()
    d["sl0"] = js[d.index].map(lambda j: j.get("sl0"))
    d = d.dropna(subset=["exit_time", "pnl_usdt", "sl0"])
    d["R"] = d.pnl_usdt / ((d.entry_price - d.sl0.astype(float)).abs() * d.quantity)
    d["m"] = pd.to_datetime(d.exit_time, utc=True).dt.strftime("%Y-%m")
    return d.groupby("m").R.sum()


def corr(fund_ret: pd.Series, rsum: pd.Series, lo, hi):
    idx = [str(p) for p in pd.period_range(lo, hi, freq="M")]
    a = fund_ret.reindex(idx)
    b = rsum.reindex(idx, fill_value=0.0)
    assert a.notna().all()
    return dict(pearson=round(float(np.corrcoef(a, b)[0, 1]), 4),
                spearman=round(float(a.rank().corr(b.rank())), 4), n=len(idx))


def main():
    res = dict(rows=[], monthly={}, yearly={}, diag={})
    periods = {}
    dA = load_A()
    sA = start_A(dA)
    dB = load_B()
    assert len(dB) == 38, len(dB)
    periods["A"] = (dA, sA)
    periods["B"] = (dB, START_B)
    for P, (data, start) in periods.items():
        fund, trades, weeks, diag = simulate(data, start)
        weeks.to_csv(f"{OUT}/haftalik_{P}.csv", index=False)
        diag.update(start=str(start.date()), end_incl=str(pd.Timestamp(END_MS, unit="ms")),
                    coins=sorted(data))
        tabs = {}
        for scen in ("NORMAL", "STRESS"):
            df = monthly(fund, trades, start, scen)
            tabs[scen] = df
            df.to_csv(f"{OUT}/aylik_{P}_{scen}.csv", index_label="month")
            res["rows"].append(summarize(df, trades, weeks, start, P, scen))
        res["monthly"][P] = {m: round(float(v), 4) for m, v in tabs["NORMAL"].ret_pct.items()}
        res["monthly_complete"] = res.get("monthly_complete", {})
        res["monthly_complete"][P] = {m: bool(v) for m, v in tabs["NORMAL"].complete.items()}
        for scen in ("NORMAL", "STRESS"):
            y = tabs[scen].ret_pct.groupby(tabs[scen].index.str[:4]).sum()
            res["yearly"][f"{P}_{scen}"] = {k: round(float(v), 4) for k, v in y.items()}
        # duyarlilik: esitlik bozma = mevcut pozisyon onde
        f2, t2, w2, d2 = simulate(data, start, tiebreak="incumbent")
        alt = {}
        for scen in ("NORMAL", "STRESS"):
            s2 = summarize(monthly(f2, t2, start, scen), t2, w2, start, P, scen)
            alt[scen] = {k: s2[k] for k in ("annual_pct", "pos_month_share", "worst_month_pct", "rotations")}
        diag["tiebreak_incumbent_sensitivity"] = alt
        # duyarlilik: float np.mean esigi (pro_v9 FC_T1 kodunun fiili davranisi; 21 x 1e-4 -> esik ALTI)
        f3, t3, w3, d3 = simulate(data, start, arith="float")
        alt = {}
        for scen in ("NORMAL", "STRESS"):
            s3 = summarize(monthly(f3, t3, start, scen), t3, w3, start, P, scen)
            alt[scen] = {k: s3[k] for k in ("annual_pct", "pos_month_share", "worst_month_pct", "rotations",
                                            "avg_positions")}
        diag["float_npmean_sensitivity"] = alt
        # coin bazinda funding (NORMAL defter)
        diag["funding_by_coin_usdt"] = {k: round(float(v), 2) for k, v in
                                        (fund.u * UNIT * NOTIONAL).groupby(fund.coin).sum().sort_values().items()}
        res["diag"][P] = diag
        if P == "B":
            rs = donchian_monthly()
            res["corr_donchian"] = corr(tabs["NORMAL"].ret_pct, rs, *CORR_MONTHS)
            res["corr_donchian_prereg_range"] = corr(tabs["NORMAL"].ret_pct, rs, *CORR_MONTHS_PREREG)
            res["corr_donchian_stress"] = corr(tabs["STRESS"].ret_pct, rs, *CORR_MONTHS)
            res["donchian_R_monthly"] = {k: round(float(v), 4) for k, v in rs.items()}
    # karar
    crit = {}
    rows = {(r["period"], r["cost"]): r for r in res["rows"]}
    for P in ("A", "B"):
        n, s = rows[(P, "NORMAL")], rows[(P, "STRESS")]
        crit[P] = {"c1_normal_annual_ge_8": n["annual_pct"] >= 8.0,
                   "c2_stress_annual_gt_0": s["annual_pct"] > 0.0,
                   "c3_pos_month_share_ge_75": n["pos_month_share"] >= 0.75}
    res["criteria"] = crit
    res["verdict"] = "ISE YARAR" if all(all(c.values()) for c in crit.values()) else "DEGMEZ"
    with open(f"{OUT}/sonuc.json", "w") as fh:
        json.dump(res, fh, indent=1, default=str)
    # ekran
    cols = ["period", "cost", "annual_pct", "annual_pct_complete", "annual_pct_total_over_years",
            "pos_month_share", "worst_month_pct", "worst_month", "avg_positions", "rotations", "closes",
            "months", "complete_months", "total_funding_usdt", "total_cost_usdt", "weeks_with_zero_positions"]
    print(pd.DataFrame(res["rows"])[cols].to_string(index=False))
    for P in ("A", "B"):
        print(f"\n{P} criteria:", crit[P], "| diag:",
              {k: v for k, v in res["diag"][P].items() if k not in ("coins", "funding_by_coin_usdt")})
        print(f"{P} funding by coin:", res["diag"][P]["funding_by_coin_usdt"])
    print("\nYEARLY:", json.dumps(res["yearly"], indent=0))
    print("CORR:", res["corr_donchian"], res["corr_donchian_prereg_range"], res["corr_donchian_stress"])
    print("VERDICT:", res["verdict"])
    for P in ("A", "B"):
        print(f"\nMONTHLY NORMAL {P}:")
        for m, v in res["monthly"][P].items():
            print(f"  {m} {v:+.3f}%{'' if res['monthly_complete'][P][m] else ' (eksik ay)'}")


if __name__ == "__main__":
    main()
