"""Donchian küme filtresi — ON_KAYIT.md. Kullanım: python analiz.py <ikiz_gercek.db>"""
import json, sqlite3, sys
import numpy as np, pandas as pd

c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
d = pd.read_sql("select symbol,side,entry_price,quantity,entry_time,exit_time,pnl_usdt,strategy_scores "
                "from trades where pnl_usdt is not null", c)
d["kol"] = d.strategy_scores.map(lambda s: json.loads(s).get("strategy"))
d = d[d.kol == "donchian"].copy()
d["sl0"] = d.strategy_scores.map(lambda s: json.loads(s)["sl0"])
d["R"] = d.pnl_usdt / ((d.entry_price - d.sl0).abs() * d.quantity)
d["t"] = pd.to_datetime(d.entry_time, format="ISO8601", utc=True)
d["z"] = pd.to_datetime(d.exit_time, format="ISO8601", utc=True)
d["mum"] = d.t.dt.floor("4h")
d["kume"] = d.groupby("mum").symbol.transform("size")
d = d.sort_values("t").reset_index(drop=True)
YARI = pd.Timestamp("2025-01-01", tz="UTC")

print(f"donchian işlemi {len(d)} · ort R {d.R.mean():+.3f}")
print("küme büyüklüğüne göre:")
for k, g in d.groupby(d.kume.clip(upper=4)):
    print(f"  {'4+' if k == 4 else k}: işlem {len(g):>3} · ayrı an {g.mum.nunique():>3} · ort R {g.R.mean():+.3f} · ΣR {g.R.sum():+.1f}"
          f" · long/short {(g.side == 'long').sum()}/{(g.side == 'short').sum()}")


def varyant(K, bekle):
    sec = d[d.kume >= K] if K else d
    if bekle:
        tut, kilit = [], pd.Timestamp(0, tz="UTC")
        for m, g in sec.groupby("mum"):
            if m < kilit:
                continue
            tut.append(g)
            kilit = m + pd.Timedelta(hours=48)
        sec = pd.concat(tut) if tut else sec.iloc[:0]
    return sec


def hesap(sec):
    """%3.5 risk, bileşik; çıkış ayına göre ay sonu değeri → en büyük düşüş ve çarpan."""
    eq, seri = 1.0, []
    for _, r in sec.sort_values("z").iterrows():
        eq *= 1 + 0.035 * r.R
        seri.append((r.z, eq))
    if not seri:
        return 1.0, 0.0
    s = pd.Series([e for _, e in seri], index=[t for t, _ in seri]).resample("ME").last().ffill()
    return eq, float((1 - s / s.cummax()).max() * 100)


print(f"\n{'varyant':<8}{'işlem':>6}{'ort R':>8}{'ΣR':>8}{'ΣR 1.yarı':>11}{'ΣR 2.yarı':>11}{'çarpan':>9}{'maxDD%':>8}  karar")
taban = None
for ad, K, b in (("TABAN", 0, False), ("K3", 3, False), ("K4", 4, False), ("K3_B2", 3, True), ("K4_B2", 4, True)):
    s = varyant(K, b)
    r1, r2 = s[s.t < YARI].R.sum(), s[s.t >= YARI].R.sum()
    x, dd = hesap(s)
    if ad == "TABAN":
        taban = (s.R.sum(), r1, r2, dd); karar = ""
    else:
        iyi = s.R.sum() > taban[0] and r1 > taban[1] and r2 > taban[2] and dd <= taban[3]
        karar = "İYİ" if iyi else "ELENDİ"
    print(f"{ad:<8}{len(s):>6}{s.R.mean():>+8.3f}{s.R.sum():>+8.1f}{r1:>+11.1f}{r2:>+11.1f}{x:>9.2f}{dd:>8.1f}  {karar}")
