"""
cvd_arsiv_denetim.py — ARSIV DENETIMI olcumu (uretim koduna dokunmaz).

Amac: "Order Flow / CVD" ailesini bu seansin 6 kisitina karsi OLCMEK.
  K1 genis stop   -> stop mesafesi / kayma maliyeti (R cinsinden)
  K2 short bacak  -> absorpsiyon LONG vs SHORT bacagi AYRI olculur
  K3 aralik devam -> ayni barlarda momentum karsilastirmasi

Veri: Binance 1m klines (taker_buy_volume), BTC 2023-01 -> 2026-04 (40 ay).
  2023-2024 parcasi git commit 647d765^ icinden kurtarildi (scratchpad).
Lookahead yok: sinyal bar KAPANISINDA uretilir, getiri i+1..i+H barlarindan.
"""
from __future__ import annotations
import glob, sys
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, "/home/user/Bot2")
from indicators import atr, ema

KAYMA = 15.85 / 1e4
SCRATCH = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/btc1m"
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")   # bu seansin TRAIN/TEST siniri


def load_1h(patterns):
    fr = []
    for pat in patterns:
        for f in sorted(glob.glob(pat)):
            d = pd.read_csv(f)
            fr.append(d[["open_time", "open", "high", "low", "close",
                         "volume", "taker_buy_volume"]].astype(float))
    m = (pd.concat(fr, ignore_index=True)
           .drop_duplicates(subset="open_time").sort_values("open_time"))
    m.index = pd.to_datetime(m["open_time"], unit="ms", utc=True)
    h = m.resample("1h").agg({"open": "first", "high": "max", "low": "min",
                              "close": "last", "volume": "sum",
                              "taker_buy_volume": "sum"}).dropna()
    h["delta"] = 2.0 * h["taker_buy_volume"] - h["volume"]
    h["buy_ratio"] = (h["taker_buy_volume"] / h["volume"]).clip(0, 1)
    return h


def resample_tf(h, rule):
    r = h.resample(rule).agg({"open": "first", "high": "max", "low": "min",
                              "close": "last", "volume": "sum",
                              "taker_buy_volume": "sum"}).dropna()
    r["delta"] = 2.0 * r["taker_buy_volume"] - r["volume"]
    r["buy_ratio"] = (r["taker_buy_volume"] / r["volume"]).clip(0, 1)
    return r


def r_getiri(df, idx, yon, sl_atr, rr, max_hold):
    """Kesitsel R: stop=sl_atr*ATR, hedef=rr*stop, max_hold bar. Lookahead yok."""
    hi, lo, cl = df["high"].values, df["low"].values, df["close"].values
    at = atr(df["high"], df["low"], df["close"], 14).values
    out = []
    n = len(cl)
    for i, d in zip(idx, yon):
        if i + 1 >= n or np.isnan(at[i]) or at[i] <= 0:
            continue
        e = cl[i]; sl_d = sl_atr * at[i]
        sl = e - d * sl_d; tp = e + d * rr * sl_d
        r = None
        for j in range(i + 1, min(i + 1 + max_hold, n)):
            if d == 1:
                if lo[j] <= sl: r = -1.0; break
                if hi[j] >= tp: r = rr; break
            else:
                if hi[j] >= sl: r = -1.0; break
                if lo[j] <= tp: r = rr; break
        if r is None:
            j = min(i + max_hold, n - 1)
            r = d * (cl[j] - e) / sl_d
        out.append({"i": i, "ts": df.index[i], "dir": d,
                    "R_ham": r, "stop_pct": sl_d / e})
    return out


def absorpsiyon(df, lb, thr, trend_ema=0):
    """Yeni lb-bar dip + agresif ALIM baskin -> long
       Yeni lb-bar tepe + agresif SATIS baskin -> short (kullanicinin tarifi)"""
    lo, hi, cl = df["low"].values, df["high"].values, df["close"].values
    br = df["buy_ratio"].values
    em = ema(df["close"], trend_ema).values if trend_ema else None
    idx, yon = [], []
    start = max(lb + 1, (trend_ema + 1) if trend_ema else 20)
    for i in range(start, len(cl)):
        if np.isnan(br[i]):
            continue
        if lo[i] <= lo[i - lb:i].min() and br[i] >= thr:
            if em is None or (not np.isnan(em[i]) and cl[i] > em[i]):
                idx.append(i); yon.append(1); continue
        if hi[i] >= hi[i - lb:i].max() and br[i] <= (1.0 - thr):
            if em is None or (not np.isnan(em[i]) and cl[i] < em[i]):
                idx.append(i); yon.append(-1)
    return idx, yon


def cvd_sapma(df, lb, trend_ema=0):
    """Kullanicinin asil tarifi: fiyat yeni tepe AMA kumulatif delta (CVD)
       onceki tepeye gore DUSUK -> absorpsiyon -> short. Ayna: long."""
    lo, hi, cl = df["low"].values, df["high"].values, df["close"].values
    cum = df["delta"].cumsum().values
    em = ema(df["close"], trend_ema).values if trend_ema else None
    idx, yon = [], []
    start = max(lb + 1, (trend_ema + 1) if trend_ema else 20)
    for i in range(start, len(cl)):
        if hi[i] >= hi[i - lb:i + 1].max():
            p = i - lb + int(np.argmax(hi[i - lb:i]))
            if cum[i] < cum[p]:
                if em is None or (not np.isnan(em[i]) and cl[i] < em[i]):
                    idx.append(i); yon.append(-1); continue
        if lo[i] <= lo[i - lb:i + 1].min():
            p = i - lb + int(np.argmin(lo[i - lb:i]))
            if cum[i] > cum[p]:
                if em is None or (not np.isnan(em[i]) and cl[i] > em[i]):
                    idx.append(i); yon.append(1)
    return idx, yon


def ozet(tr, etiket):
    if not tr:
        print(f"  {etiket:<34s} n=0"); return
    R = np.array([t["R_ham"] for t in tr])
    sp = np.array([t["stop_pct"] for t in tr])
    mal = KAYMA / sp                      # kayma maliyeti (R)
    Rn = R - mal                          # kaymali net R
    ts = np.array([t["ts"] for t in tr])
    tr_m = ts < SPLIT; te_m = ~tr_m
    z = Rn.mean() / (Rn.std(ddof=1) / np.sqrt(len(Rn))) if len(Rn) > 1 and Rn.std(ddof=1) > 0 else 0.0
    s = (f"  {etiket:<34s} n={len(R):<5d} stop%={np.median(sp)*100:5.2f} "
         f"mal={mal.mean():.3f}R  hamR={R.mean():+.4f}  netR={Rn.mean():+.4f} z={z:+.2f}")
    if tr_m.any(): s += f" | TR {Rn[tr_m].mean():+.4f}(n{tr_m.sum()})"
    if te_m.any(): s += f" | TE {Rn[te_m].mean():+.4f}(n{te_m.sum()})"
    print(s)


def kos(df, ad, sl_atr, rr, mh, lb_list, thr_list):
    print(f"\n{'='*140}\n{ad}  bar={len(df)}  {df.index[0].date()} -> {df.index[-1].date()}"
          f"   SL={sl_atr}*ATR14 RR={rr} mh={mh}\n{'-'*140}")
    print("A) ABSORPSIYON (yeni dip/tepe + agresif akis)")
    for lb in lb_list:
        for thr in thr_list:
            idx, yon = absorpsiyon(df, lb, thr)
            tr = r_getiri(df, idx, yon, sl_atr, rr, mh)
            ozet(tr, f"Absorp lb{lb} thr{thr} TUMU")
            ozet([t for t in tr if t["dir"] == 1],  f"   -> LONG bacak")
            ozet([t for t in tr if t["dir"] == -1], f"   -> SHORT bacak")
    print("\nB) CVD SAPMA (kullanicinin tarifi: tepe + dusen CVD -> short)")
    for lb in lb_list:
        idx, yon = cvd_sapma(df, lb)
        tr = r_getiri(df, idx, yon, sl_atr, rr, mh)
        ozet(tr, f"CVDsapma lb{lb} TUMU")
        ozet([t for t in tr if t["dir"] == 1],  f"   -> LONG bacak")
        ozet([t for t in tr if t["dir"] == -1], f"   -> SHORT bacak")


if __name__ == "__main__":
    h = load_1h([f"{SCRATCH}/BTCUSDT-1m-*.csv", "/home/user/Bot2/BTCUSDT-1m-*.csv"])
    print(f"BTC 1h yuklendi: {len(h)} bar  {h.index[0]} -> {h.index[-1]}")
    print(f"ort buy_ratio={h['buy_ratio'].mean():.4f}  TRAIN/TEST siniri={SPLIT.date()}")
    kos(h, "BTC 1H", 2.0, 2.0, 24, [10, 20, 40], [0.55, 0.60])
    kos(resample_tf(h, "4h"), "BTC 4H", 2.0, 2.0, 24, [10, 20], [0.55, 0.60])
    kos(resample_tf(h, "1D"), "BTC 1D", 2.0, 2.0, 20, [10, 20], [0.55, 0.60])


# ── KONTROL TESTI (ayri calistir: python3 cvd_arsiv_denetim.py kontrol) ──────
def ham_ekstrem(df, lb):
    """CVD SARTI YOK: sadece yeni lb-bar dip -> long, yeni tepe -> short."""
    lo, hi = df["low"].values, df["high"].values
    idx, yon = [], []
    for i in range(max(lb + 1, 20), len(df)):
        if lo[i] <= lo[i - lb:i + 1].min():
            idx.append(i); yon.append(1); continue
        if hi[i] >= hi[i - lb:i + 1].max():
            idx.append(i); yon.append(-1)
    return idx, yon


def kontrol():
    h = load_1h([f"{SCRATCH}/BTCUSDT-1m-*.csv", "/home/user/Bot2/BTCUSDT-1m-*.csv"])
    for rule, lbl, mh in [("1h", "1H", 24), ("4h", "4H", 24), ("1D", "1D", 20)]:
        df = h if rule == "1h" else resample_tf(h, rule)
        print(f"\n{'='*130}\nKONTROL {lbl}  bar={len(df)}   SL=2.0*ATR RR=2.0 mh={mh}\n{'-'*130}")
        for lb in [10, 20, 40]:
            i0, y0 = ham_ekstrem(df, lb)
            t0 = r_getiri(df, i0, y0, 2.0, 2.0, mh)
            i1, y1 = cvd_sapma(df, lb)
            t1 = r_getiri(df, i1, y1, 2.0, 2.0, mh)
            print(f"  --- lb{lb} ---")
            ozet([t for t in t0 if t["dir"] == 1],  "HAM yeni-dip LONG   (CVD yok)")
            ozet([t for t in t1 if t["dir"] == 1],  "CVD-filtreli LONG")
            ozet([t for t in t0 if t["dir"] == -1], "HAM yeni-tepe SHORT (CVD yok)")
            ozet([t for t in t1 if t["dir"] == -1], "CVD-filtreli SHORT")
