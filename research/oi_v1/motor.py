"""OI_V1 motoru — MANIFEST.md'nin birebir uygulaması (sonuçlardan önce yazıldı)."""
import os
import numpy as np
import pandas as pd

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
D4 = os.path.join(KOK, "research_data", "h4_kirilim_v6", "veri")
DOI = os.path.join(KOK, "research_data", "kalabalik", "veri")
ESKI12 = "SOL ETH ADA NEAR BCH XRP DOGE TRX XLM LTC ICP BNB".split()
YENI26 = ("LINK AVAX DOT UNI ATOM FIL ETC AAVE ALGO XTZ SAND MANA AXS EGLD RUNE EOS THETA GRT CRV HBAR "
          "VET APT ARB OP INJ SUI").split()
BAS = int(pd.Timestamp("2022-01-01", tz="UTC").timestamp() * 1000)
BIT = int(pd.Timestamp("2025-08-08", tz="UTC").timestamp() * 1000)
H4 = 4 * 3_600_000
KOM, KAY_G, KAY_C = 1.0, 15.85, 0.24          # bp


def yukle(coin):
    df = pd.read_csv(os.path.join(D4, f"{coin}_4h.csv"))
    df = df.drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
    oi = pd.read_csv(os.path.join(DOI, f"{coin}_metrics_1h.csv.gz"), usecols=["t_kapanis", "sum_open_interest"])
    oi = oi.dropna().drop_duplicates("t_kapanis").set_index("t_kapanis")["sum_open_interest"]
    pc = df["close"].shift(1)
    tr = np.maximum(df["high"] - df["low"], np.maximum((df["high"] - pc).abs(), (df["low"] - pc).abs()))
    df["atr"] = tr.rolling(20).mean()
    df["oi_ac"] = df["open_time"].map(oi)                 # mum açılışındaki OI (önceki saatin kapanışı)
    df["oi_kap"] = (df["open_time"] + H4).map(oi)         # mum kapanışındaki OI
    return df


def sinyaller(df, aile, p):
    """Her mum için yön (+1 long, −1 short, 0 yok) — yalnız o mumun kapanışında bilinen bilgi."""
    c, pc = df["close"], df["close"].shift(1)
    if aile == "TC":
        r = c / pc - 1
        a = df["atr"] / pc
        doi = df["oi_kap"] / df["oi_ac"] - 1
        tasf = doi <= -p["theta"]
        yon = np.where((r <= -p["k"] * a) & tasf, 1, 0)
        if p["yon"] == "LS":
            yon = np.where((r >= p["k"] * a) & tasf, -1, yon)
    else:                                                 # OD
        N = p["N"]
        tepe = c > c.shift(1).rolling(N).max()
        dip = c < c.shift(1).rolling(N).min()
        doi = df["oi_kap"] / df["oi_kap"].shift(N) - 1
        zayif = doi <= -p["phi"]
        yon = np.where(tepe & zayif, -1, 0)
        if p["yon"] == "LS":
            yon = np.where(dip & zayif, 1, yon)
    gecerli = df["atr"].notna() & df["oi_kap"].notna() & (df["oi_ac"].notna() if aile == "TC" else True)
    return np.where(gecerli, yon, 0)


def islemler(df, aile, p, kayma_kat=1.0):
    yon = sinyaller(df, aile, p)
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    t, atr = df["open_time"].to_numpy(), df["atr"].to_numpy()
    H = p["H"]
    out, i, n = [], 0, len(df)
    while i < n - 1:
        kap = t[i] + H4
        if yon[i] == 0 or kap <= BAS or t[i + 1] >= BIT:
            i += 1
            continue
        d, g = int(yon[i]), o[i + 1]
        dist = 2.0 * atr[i]
        stop = g - d * dist
        cik, j = None, i + 1
        while j < n and j <= i + H:
            if d == 1 and l[j] <= stop:
                cik = min(o[j], stop) if j > i + 1 else stop
                break
            if d == -1 and h[j] >= stop:
                cik = max(o[j], stop) if j > i + 1 else stop
                break
            j += 1
        if cik is None:
            j = min(i + H, n - 1)
            cik = c[j]
        maliyet = g * (2 * KOM + KAY_G * kayma_kat) / 1e4 + cik * (KAY_C * kayma_kat) / 1e4
        R = (d * (cik - g) - maliyet) / dist
        out.append((t[i + 1], d, R))
        i = j + 1                                         # tek pozisyon: çıkıştan sonraki mumdan devam
    return out


def varyantlar(aile):
    v = []
    if aile == "TC":
        for k in (2, 3):
            for th in (0.03, 0.06):
                for H in (3, 6):
                    for y in ("L", "LS"):
                        v.append(dict(ad=f"TC_k{k}_t{int(th * 100)}_H{H}_{y}", k=k, theta=th, H=H, yon=y))
    else:
        for N in (20, 40):
            for ph in (0.0, 0.05):
                for H in (6, 12):
                    for y in ("S", "LS"):
                        v.append(dict(ad=f"OD_N{N}_p{int(ph * 100)}_H{H}_{y}", N=N, phi=ph, H=H, yon=y))
    return v


def bootstrap_lcb(trades, q=1.25, n=10_000, seed=20261004):
    """Haftalık toplam R → işlem başı ortalama R'nin blok bootstrap alt sınırı (4 haftalık bloklar)."""
    if not trades:
        return float("nan")
    hafta = np.array([x[0] // (7 * 86_400_000) for x in trades])
    R = np.array([x[2] for x in trades])
    hs = np.arange(hafta.min(), hafta.max() + 1)
    topR = np.zeros(len(hs)); say = np.zeros(len(hs))
    np.add.at(topR, hafta - hs[0], R); np.add.at(say, hafta - hs[0], 1)
    B = 4
    nb = int(np.ceil(len(hs) / B))
    rng = np.random.default_rng(seed)
    ort = np.empty(n)
    for k in range(n):
        bas = rng.integers(0, len(hs) - B + 1, nb)
        idx = (bas[:, None] + np.arange(B)).ravel()[:len(hs)]
        s = say[idx].sum()
        ort[k] = topR[idx].sum() / s if s else 0.0
    return float(np.percentile(ort, q))
