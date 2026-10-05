"""BTC boy öncesi ortak noktalar — ON_KAYIT.md'nin birebir uygulaması.
Kullanım: python analiz.py <veri_klasörü>"""
import json
import os
import sys

import numpy as np
import pandas as pd

V = sys.argv[1]
GUN = 86_400_000
KESIM = pd.Timestamp("2024-01-01")
ESIK, ILERI = 0.15, 14
BURA = os.path.dirname(os.path.abspath(__file__))


def gunluk_kapanis(dosya, kol="close"):
    """Saatlik vadeli → gün kapanışı (UTC 00:00'daki son saatlik kapanış), indeks = günün tarihi."""
    d = pd.read_csv(os.path.join(V, dosya))
    d["kap"] = pd.to_datetime(d["open_time"] + 3_600_000, unit="ms")
    s = d.set_index("kap")[kol]
    g = s[s.index.hour == 0]
    g.index = (g.index - pd.Timedelta(days=1)).normalize()
    return g[~g.index.duplicated(keep="last")]


def rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def ozellikler():
    s = pd.read_csv(os.path.join(V, "BTC_spot_1d.csv"))
    s.index = pd.to_datetime(s["open_time"], unit="ms").dt.normalize()
    s = s[~s.index.duplicated(keep="last")]
    c, v = s["close"], s["quote_volume"]
    F = pd.DataFrame(index=s.index)
    F["F1_ret30"] = c / c.shift(30) - 1
    F["F2_ret7"] = c / c.shift(7) - 1
    F["F3_zirveden"] = c / c.rolling(365, min_periods=200).max() - 1
    F["F4_sma200"] = c / c.rolling(200).mean() - 1
    rv = np.log(c).diff().rolling(14).std()
    F["F5_oynaklik_yuzdelik"] = rv.rolling(365, min_periods=200).apply(lambda x: (x[:-1] < x[-1]).mean(), raw=True)
    F["F6_hacim"] = v.rolling(7).mean() / v.rolling(90).mean()
    F["F7_rsi"] = rsi(c)
    # funding: gün içindeki settlement'lar → 7g ortalama
    f = pd.read_csv(os.path.join(V, "BTC_funding.csv"))
    fs = f.set_index(pd.to_datetime(f["calc_time"], unit="ms"))["last_funding_rate"]
    fg = fs.groupby((fs.index - pd.Timedelta(milliseconds=1)).normalize()).mean()   # 00:00 settlement önceki güne
    F["F8_funding7"] = fg.rolling(7, min_periods=5).mean().reindex(F.index)
    m = pd.read_csv(os.path.join(V, "BTC_metrics_1h.csv"))
    m.index = pd.to_datetime(m["t_kapanis"], unit="ms")
    mg = m[m.index.hour == 0].copy()
    mg.index = (mg.index - pd.Timedelta(days=1)).normalize()
    mg = mg[~mg.index.duplicated(keep="last")].reindex(F.index)
    oi = mg["sum_open_interest"]
    F["F9_oi7"] = oi / oi.shift(7) - 1

    def z(x):
        x7 = x.rolling(7, min_periods=5).mean()
        return (x7 - x7.rolling(90, min_periods=60).mean()) / x7.rolling(90, min_periods=60).std()
    F["F10_toptrader_z"] = z(mg["count_toptrader_long_short_ratio"])
    F["F11_perakende_z"] = z(mg["count_long_short_ratio"])
    F["F12_taker7"] = mg["sum_taker_long_short_vol_ratio"].rolling(7, min_periods=5).mean()
    dom = gunluk_kapanis("BTCDOM_fut_1h.csv").reindex(F.index)
    F["F13_btcdom14"] = dom / dom.shift(14) - 1
    F["F14_btcdom_sma50"] = dom / dom.rolling(50, min_periods=40).mean() - 1
    eth = gunluk_kapanis("ETH_fut_1h.csv").reindex(F.index)
    ethbtc = eth / c
    F["F15_ethbtc14"] = ethbtc / ethbtc.shift(14) - 1
    ileri = pd.concat([c.shift(-k) for k in range(1, ILERI + 1)], axis=1).max(axis=1)
    etiket = (ileri / c - 1 >= ESIK).astype(float)
    etiket[c.shift(-ILERI).isna()] = np.nan
    F["BOY"] = etiket
    F["close"] = c
    return F


def lift_tablosu(F, kol, sinir):
    x = F[kol]
    q = pd.cut(x, sinir, labels=False, include_lowest=True)
    taban = F["BOY"].mean()
    out = []
    for k in range(len(sinir) - 1):
        m = (q == k) & F["BOY"].notna()
        out.append(dict(dilim=k, gun=int(m.sum()), boy=int(F.loc[m, "BOY"].sum()),
                        p=float(F.loc[m, "BOY"].mean()) if m.sum() else np.nan,
                        lift=float(F.loc[m, "BOY"].mean() / taban) if m.sum() else np.nan))
    return out, taban


def bootstrap_lift(F, kol, sinir, dilim, n=10_000, seed=20261005):
    q = pd.cut(F[kol], sinir, labels=False, include_lowest=True)
    d = pd.DataFrame(dict(ay=F.index.to_period("M"), boy=F["BOY"], in_=(q == dilim).astype(float)))
    d = d.dropna(subset=["boy"])
    d["bi"] = d["boy"] * d["in_"]
    g = d.groupby("ay").agg(boy=("boy", "sum"), gun=("boy", "size"), boy_in=("bi", "sum"), gun_in=("in_", "sum"))
    a = g.to_numpy(float)
    rng = np.random.default_rng(seed)
    L = np.empty(n)
    for k in range(n):
        s = a[rng.integers(0, len(a), len(a))].sum(axis=0)
        L[k] = (s[2] / s[3]) / (s[0] / s[1]) if s[3] > 0 and s[0] > 0 else np.nan
    return L[~np.isnan(L)]


def main():
    F = ozellikler()
    kes = F.index < KESIM
    son = F["BOY"].last_valid_index()
    K, D = F[kes], F[(~kes) & (F.index <= son)]
    print(f"veri: {F.index[0].date()} → {son.date()} · keşif {K['BOY'].notna().sum()} gün, doğrulama "
          f"{D['BOY'].notna().sum()} gün")
    print(f"temel oran (boy günü payı): keşif {K['BOY'].mean():.1%} · doğrulama {D['BOY'].mean():.1%}")
    # olay başlangıçları
    b = F["BOY"].fillna(0).to_numpy()
    basl = [F.index[i] for i in range(len(b)) if b[i] == 1 and b[max(0, i - ILERI):i].sum() == 0]
    print(f"\nOLAY BAŞLANGIÇLARI ({len(basl)}):")
    kolonlar = [k for k in F.columns if k.startswith("F")]
    for t in basl:
        r = F.loc[t]
        tepe = F["close"].loc[t:t + pd.Timedelta(days=ILERI)].max() / r["close"] - 1
        print(f"  {t.date()}  +{tepe:.0%}  ret30 {r['F1_ret30']:+.0%}  zirveden {r['F3_zirveden']:+.0%}  "
              f"sma200 {r['F4_sma200']:+.0%}  fund7 {r['F8_funding7'] * 1e4 if pd.notna(r['F8_funding7']) else np.nan:+.1f}bp  "
              f"dom14 {r['F13_btcdom14'] if pd.notna(r['F13_btcdom14']) else np.nan:+.1%}")
    # keşif: dilim sınırları ve lift
    adaylar, sinirlar = [], {}
    print("\nKEŞİF — lift tabloları (dilim 0 = en düşük değerler)")
    for kol in kolonlar:
        x = K[kol].dropna()
        if len(x) < 300:
            print(f"  {kol}: keşifte yetersiz veri ({len(x)})")
            continue
        sinir = np.unique(np.r_[-np.inf, np.quantile(x, [0.2, 0.4, 0.6, 0.8]), np.inf])
        sinirlar[kol] = sinir
        tab, taban = lift_tablosu(K[K[kol].notna()], kol, sinir)
        print(f"  {kol:<22} " + " | ".join(f"{t['lift']:.2f}({t['boy']}/{t['gun']})" for t in tab))
        for t in tab:
            if t["gun"] >= 60 and t["boy"] >= 15:
                adaylar.append((kol, t["dilim"], t["lift"]))
    ust = sorted(adaylar, key=lambda a: -a[2])[:3]
    alt = sorted(adaylar, key=lambda a: a[2])[:3]
    print("\nDOĞRULAMAYA TAŞINAN — en yüksek lift:", [(k, d, round(l, 2)) for k, d, l in ust])
    print("DOĞRULAMAYA TAŞINAN — en düşük lift (kaçınılacak):", [(k, d, round(l, 2)) for k, d, l in alt])
    q_alt, q_ust = 0.83, 100 - 0.83
    sonuc = []
    print(f"\nDOĞRULAMA ({KESIM.date()} → {son.date()}, temel oran {D['BOY'].mean():.1%})")
    for tur, liste in (("yüksek", ust), ("düşük", alt)):
        for kol, dl, lk in liste:
            Dk = D[D[kol].notna()]
            tab, _ = lift_tablosu(Dk, kol, sinirlar[kol])
            L = bootstrap_lift(Dk, kol, sinirlar[kol], dl)
            lo, hi = np.percentile(L, [q_alt, q_ust]) if len(L) else (np.nan, np.nan)
            ok = (lo > 1) if tur == "yüksek" else (hi < 1)
            t = tab[dl]
            print(f"  {kol:<22} dilim {dl}  keşif lift {lk:.2f} → doğrulama {t['lift']:.2f} ({t['boy']}/{t['gun']})"
                  f"  Bonferroni %95 [{lo:.2f}, {hi:.2f}]  → {'DOĞRULANDI' if ok else 'doğrulanmadı'}")
            sonuc.append(dict(tur=tur, kol=kol, dilim=int(dl), kesif=lk, dogrulama=t["lift"], lo=lo, hi=hi, ok=bool(ok)))
    json.dump(dict(sonuc=sonuc, olaylar=[str(t.date()) for t in basl]),
              open(os.path.join(BURA, "sonuc.json"), "w"), indent=1, default=float)


main()
