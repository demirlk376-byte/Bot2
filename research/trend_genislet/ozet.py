"""trend_genislet ON_KAYIT ozeti: 3 varyant x 2 donem pkl -> olcutler, aylik tablolar, karar."""
import json, os, pickle, sys
from collections import Counter
import numpy as np
import pandas as pd

OUT = os.path.dirname(os.path.abspath(__file__))
VARY = ["T12", "T38", "T38_R1"]
DON = ["KESIF", "BAGIMSIZ"]
C0 = 10_000.0


def aylik(seri):
    s = pd.DataFrame(seri, columns=["t", "deger", "acik_poz", "acik_risk", "teminat"])
    s = s.set_index(pd.to_datetime(s.t, unit="ms")).deger.resample("ME").last().dropna()
    s = pd.concat([pd.Series([C0], index=[s.index[0] - pd.offsets.MonthEnd(1)]), s])
    return s


def olc(r):
    s = aylik(r["seri"])
    carpan = s.iloc[-1] / C0
    yil = (s.index[-1] - s.index[0]).days / 365.25
    cagr = (s.iloc[-1] / s.iloc[0]) ** (1 / yil) - 1
    mdd = float((1 - s / s.cummax()).max())
    sr = pd.DataFrame(r["seri"], columns=["t", "deger", "acik_poz", "acik_risk", "teminat"])
    ol = Counter(o["tur"] for o in r["olaylar"])
    tr = pd.DataFrame(r["islemler"])
    tavan_giris = ol.get("GIRIS_ATLANDI_RISK_TAVANI", 0)
    girisler = len(tr) + len(r["acik"])
    # 4h ciktisi uzerinde de maxDD (bilgi icin; olcut aylik)
    v = sr.deger.to_numpy()
    mdd4 = float((1 - v / np.maximum.accumulate(np.r_[C0, v])[1:]).max())
    return dict(variant=r["varyant"], period=r["donem"], mult=float(carpan), cagr=float(cagr), maxdd=mdd,
                ratio=float(cagr / mdd) if mdd > 0 else float("inf"), yil=yil,
                mean_open=float(sr.acik_poz.mean()), max_open=int(sr.acik_poz.max()),
                mean_open_risk_pct=float((sr.acik_risk / sr.deger).mean() * 100),
                max_open_risk_pct=float((sr.acik_risk / sr.deger).max() * 100),
                max_teminat_pct=float((sr.teminat / sr.deger).max() * 100),
                cap_blocked=int(tavan_giris), cap_blocked_ek=int(ol.get("EK_ATLANDI_RISK_TAVANI", 0)),
                teminat_blocked=int(ol.get("GIRIS_ATLANDI_TEMINAT", 0)), min_emir=int(ol.get("GIRIS_ATLANDI_MIN_EMIR", 0)),
                olaylar=dict(ol), trend_trades=int(girisler), trend_kapanan=int(len(tr)), trend_acik_son=len(r["acik"]),
                trend_pnl=float(tr.pnl.sum()) if len(tr) else 0.0,
                trend_acik_pnl=float(sum(a["acik_pnl"] for a in r["acik"])),
                bot_alinan=r["bot_alinan"], bot_atlanan=r["bot_atlanan"], bot_sayac=r["bot_sayac"],
                maxdd_4h=mdd4, sure_s=r["sure"])


def aylik_tablo(r):
    s = aylik(r["seri"])
    y = s.pct_change().dropna() * 100
    tab = y.groupby([y.index.year, y.index.month]).first().unstack()
    tab["YIL"] = [(1 + y[y.index.year == yy] / 100).prod() * 100 - 100 for yy in tab.index]
    return tab


def coin_pnl(r):
    tr = pd.DataFrame(r["islemler"])
    g = tr.groupby("coin").agg(n=("pnl", "size"), pnl=("pnl", "sum")) if len(tr) else pd.DataFrame(columns=["n", "pnl"])
    ac = pd.DataFrame(r["acik"])
    if len(ac):
        g = g.join(ac.groupby("coin").acik_pnl.sum(), how="outer")
    else:
        g["acik_pnl"] = 0.0
    g = g.fillna(0.0)
    g["toplam"] = g.pnl + g.acik_pnl
    g["bot12"] = [c in "SOL ETH ADA NEAR BCH XRP DOGE TRX XLM LTC ICP BNB".split() for c in g.index]
    return g.sort_values("toplam", ascending=False)


def main():
    R = {(v, d): pickle.load(open(os.path.join(OUT, f"{v}_{d}.pkl"), "rb")) for v in VARY for d in DON}
    rows = [olc(R[k]) for k in R]
    df = pd.DataFrame(rows).set_index(["variant", "period"])
    pd.set_option("display.width", 250, "display.max_columns", 40)
    print(df[["mult", "cagr", "maxdd", "ratio", "maxdd_4h", "mean_open", "max_open", "mean_open_risk_pct",
              "max_open_risk_pct", "max_teminat_pct", "cap_blocked", "cap_blocked_ek", "teminat_blocked", "min_emir",
              "trend_trades", "trend_acik_son", "trend_pnl", "trend_acik_pnl", "bot_alinan", "bot_atlanan"]].round(4).to_string())
    for k in R:
        print(k, "bot", R[k]["bot_sayac"], "olaylar", dict(Counter(o["tur"] for o in R[k]["olaylar"])))
        print("   acik son:", [(a["coin"], round(a["acik_pnl"], 1), a["son_px"] is None) for a in R[k]["acik"]])
    # karar
    karar = {}
    for v in ["T38", "T38_R1"]:
        kr = {}
        for d in DON:
            a, b = df.loc[(v, d)], df.loc[("T12", d)]
            kr[d] = dict(oran=bool(a.ratio > b.ratio), carpan=bool(a.mult > b.mult),
                         maxdd=bool(a.maxdd <= b.maxdd + 0.03),
                         detay=dict(oran=(round(a.ratio, 3), round(b.ratio, 3)), carpan=(round(a.mult, 3), round(b.mult, 3)),
                                    maxdd=(round(a.maxdd * 100, 2), round(b.maxdd * 100, 2))))
        iyi = all(all(kr[d][c] for c in ("oran", "carpan", "maxdd")) for d in DON)
        karar[v] = dict(IYI=iyi, kriter=kr)
    print(json.dumps(karar, indent=1))
    iyiler = [v for v in karar if karar[v]["IYI"]]
    if len(iyiler) == 2:
        # ikisi de IYI: orani yuksek olan (spec iki donem icin ayrica tanimlamiyor -> iki donemde de yuksekse; degilse ortalama)
        secim = max(iyiler, key=lambda v: df.loc[(v, "KESIF")].ratio + df.loc[(v, "BAGIMSIZ")].ratio)
    elif len(iyiler) == 1:
        secim = iyiler[0]
    else:
        secim = "T12"
    print("SECIM:", secim)
    tablolar = {}
    for k in R:
        t = aylik_tablo(R[k])
        tablolar[f"{k[0]}|{k[1]}"] = t
        print(f"\n=== Aylik % {k[0]} {k[1]}")
        print(t.round(1).to_string())
        t.round(2).to_csv(os.path.join(OUT, f"aylik_{k[0]}_{k[1]}.csv"))
    cp = {}
    for k in R:
        g = coin_pnl(R[k])
        g.to_csv(os.path.join(OUT, f"coin_pnl_{k[0]}_{k[1]}.csv"))
        cp[f"{k[0]}|{k[1]}"] = g
        print(f"\n=== Coin trend PnL {k}: top5 / bottom5 (closed + open at end)")
        print(g.head(5).round(1).to_string())
        print(g.tail(5).round(1).to_string())
        print("   yeni 24 coin toplam (EOS,FIL yuklenemedi):", round(g[~g.bot12].toplam.sum(), 1), " bot12 toplam:", round(g[g.bot12].toplam.sum(), 1))
    df.drop(columns=["olaylar", "bot_sayac"]).to_csv(os.path.join(OUT, "ozet.csv"))
    json.dump(dict(rows=rows, karar=karar, secim=secim), open(os.path.join(OUT, "ozet.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
