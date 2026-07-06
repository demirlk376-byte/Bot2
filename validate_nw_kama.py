"""
validate_nw_kama.py — NW+KAMA CONFLUENCE definitive test (run on the VPS where
data.binance.vision is reachable). 2023-2026 1h spot -> resampled 1D and 2D.

Confluence = NW envelope extreme within the last `lb` bars + KAMA agreement NOW
(EVENT: KAMA cross in that direction | STATE: price on KAMA's side + slope).
Params are PRE-REGISTERED (the scaled sets from the 12-month local run) — no
test-set tuning. Decision bar: TRAIN PF>1.2 AND TEST PF>1.1 AND n>=30 total,
and the result must hold across NEIGHBORING configs (not one lucky cell).

Usage (VPS):  venv/bin/python validate_nw_kama.py            # BTC + ETH
              venv/bin/python validate_nw_kama.py BTCUSDT    # single coin
"""
from __future__ import annotations
import io, sys, zipfile
import numpy as np
import pandas as pd

sys.path.insert(0, "/opt/bot2" if "/opt/bot2" in __file__ else ".")
from backtest_nw_kama import nadaraya_causal, kama, _simulate
from indicators import atr as atr_fn

YEARS = [2023, 2024, 2025, 2026]
SPLIT = pd.Timestamp("2026-01-01", tz="UTC")

def load_1h_remote(sym):
    import requests, glob
    # local CSVs only if they cover >=24 months; otherwise download the full
    # 2023-2026 history (a short local set silently shrinks the test window).
    files = sorted(glob.glob(f"{sym}-1m-*.csv"))
    if files and len(files) >= 24:
        fr = []
        for f in files:
            d = pd.read_csv(f, header=None).iloc[:, :6]
            d.columns = ["ts","open","high","low","close","volume"]
            d = d[pd.to_numeric(d["ts"], errors="coerce").notna()].astype(float)
            fr.append(d)
        df = pd.concat(fr, ignore_index=True).drop_duplicates("ts").sort_values("ts")
        unit = "us" if df["ts"].iloc[0] > 1e15 else "ms"
        df.index = pd.to_datetime(df["ts"], unit=unit, utc=True)
        return df.drop(columns=["ts"]).resample("1h").agg(
            {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    base = "https://data.binance.vision/data/spot/monthly/klines"
    fr = []
    for y in YEARS:
        for m in range(1, 13):
            url = f"{base}/{sym}/1h/{sym}-1h-{y}-{m:02d}.zip"
            try:
                r = requests.get(url, timeout=30)
                if r.status_code != 200: continue
                with zipfile.ZipFile(io.BytesIO(r.content)) as z, z.open(z.namelist()[0]) as fh:
                    d = pd.read_csv(fh, header=None,
                        names=["ts","open","high","low","close","volume","ct","qv","n","a","b","c"])
                d = d[pd.to_numeric(d["ts"], errors="coerce").notna()]
                d["ts"] = pd.to_numeric(d["ts"])
                unit = "us" if d["ts"].iloc[0] > 1e15 else "ms"
                d.index = pd.to_datetime(d["ts"], unit=unit, utc=True)
                fr.append(d[["open","high","low","close","volume"]].astype(float))
            except Exception:
                continue
    return pd.concat(fr).sort_index() if fr else None

def _bands(c, h, win):
    yhat = nadaraya_causal(c, h, win)
    mae = pd.Series(np.abs(c - yhat)).rolling(win).mean().values
    return yhat, mae

def _nw_flags(c, yhat, mae, mult):
    n = len(c); L = np.zeros(n, bool); S = np.zeros(n, bool)
    for t in range(n):
        if np.isnan(yhat[t]) or np.isnan(mae[t]) or mae[t] <= 0: continue
        if c[t] < yhat[t] - mult*mae[t]: L[t] = True
        elif c[t] > yhat[t] + mult*mae[t]: S[t] = True
    return L, S

def sigs(df, mode, h, win, mult, er, lb):
    c = df["close"].values; n = len(c)
    yhat, mae = _bands(c, h, win)
    nwL, nwS = _nw_flags(c, yhat, mae, mult)
    k = kama(c, er)
    out = []; last = -99
    for t in range(1, n):
        if np.isnan(k[t]) or np.isnan(k[t-1]): continue
        up = k[t] > k[t-1]
        lo = max(0, t - lb)
        if mode == "event":
            cu = c[t-1] <= k[t-1] and c[t] > k[t]
            cd = c[t-1] >= k[t-1] and c[t] < k[t]
            if cu and up and nwL[lo:t+1].any(): out.append((t, 1))
            elif cd and (not up) and nwS[lo:t+1].any(): out.append((t, -1))
        else:
            if t - last <= 3: continue
            if up and c[t] > k[t] and nwL[lo:t+1].any(): out.append((t, 1)); last = t
            elif (not up) and c[t] < k[t] and nwS[lo:t+1].any(): out.append((t, -1)); last = t
    return out


def sigs_agree(df, h, win, mult, er, lb_unused):
    """BOTH-IN-BUY-STATE (kullanicinin tanimi): her gosterge kendi sinyalini
    vermis ve HALA gecerli olduğunda gir.
      KAMA durumu: yukari kesisim (+egim) sonrasi LONG, asagi kesisim (-egim)
        sonrasi SHORT — ters kesisime kadar surer.
      NW durumu: alt banda dokunis -> LONG, yhat'e (ortalamaya) donunce
        notrlesir; ust bant -> SHORT, mirror.
    Giris: iki durum AYNI yone dondugu ILK barda (agreement baslangici)."""
    c = df["close"].values; n = len(c)
    yhat, mae = _bands(c, h, win)
    k = kama(c, er)
    kst = 0; nst = 0; prev_agree = 0
    out = []
    for t in range(1, n):
        if np.isnan(k[t]) or np.isnan(k[t-1]) or np.isnan(yhat[t]) or np.isnan(mae[t]) or mae[t] <= 0:
            continue
        up = k[t] > k[t-1]
        if c[t-1] <= k[t-1] and c[t] > k[t] and up: kst = 1
        elif c[t-1] >= k[t-1] and c[t] < k[t] and not up: kst = -1
        if c[t] < yhat[t] - mult*mae[t]: nst = 1
        elif c[t] > yhat[t] + mult*mae[t]: nst = -1
        elif (nst == 1 and c[t] >= yhat[t]) or (nst == -1 and c[t] <= yhat[t]): nst = 0
        agree = kst if (kst != 0 and kst == nst) else 0
        if agree != 0 and prev_agree == 0:
            out.append((t, agree))
        prev_agree = agree
    return out

# PRE-REGISTERED grid (from the 12-month scaled run; no test tuning)
GRID = [
    ("event", 3, 15, 1.5, 5, 1), ("event", 3, 15, 2.0, 5, 2),
    ("event", 4, 20, 1.5, 8, 2), ("event", 5, 25, 2.0, 10, 2),
    ("state", 3, 15, 1.5, 5, 2), ("state", 4, 20, 1.5, 8, 3),
    ("state", 5, 25, 2.0, 10, 3),
    ("agree", 3, 15, 1.5, 5, 0), ("agree", 4, 20, 1.5, 8, 0),
    ("agree", 5, 25, 2.0, 10, 0), ("agree", 3, 15, 2.0, 5, 0),
]

SUMMARY = {}   # coin -> list of (config_label, ntot, pf_tr, pf_te)

def run_tf(df1h, rule, mh, coin):
    df = df1h.resample(rule).agg({"open":"first","high":"max","low":"min",
                                  "close":"last","volume":"sum"}).dropna()
    wa = atr_fn(df["high"], df["low"], df["close"], 14).values
    print(f"\n  [{coin} {rule}] {len(df)} bars {df.index[0].date()}..{df.index[-1].date()}")
    for (mode, h, win, mult, er, lb) in GRID:
        s = sigs_agree(df, h, win, mult, er, lb) if mode == "agree" else sigs(df, mode, h, win, mult, er, lb)
        tr_s = [(t, d) for (t, d) in s if df.index[t] < SPLIT]
        te_s = [(t, d) for (t, d) in s if df.index[t] >= SPLIT]
        r_tr = _simulate(df, tr_s, 2.0, 4.0, wa, mh)
        r_te = _simulate(df, te_s, 2.0, 4.0, wa, mh)
        ntot = r_tr.trades + r_te.trades
        pf_tr = r_tr.pf if r_tr.gross_loss > 0 else (9.99 if r_tr.gross_win > 0 else 0)
        pf_te = r_te.pf if r_te.gross_loss > 0 else (9.99 if r_te.gross_win > 0 else 0)
        ok = "PASS" if (pf_tr > 1.2 and pf_te > 1.1 and ntot >= 30) else "  no"
        if rule == "1D" and mode == "event":
            SUMMARY.setdefault(coin, []).append((f"h{h}w{win}m{mult}", ntot, pf_tr, pf_te))
        print(f"    {mode:<5s} h{h} w{win:<2d} m{mult} er{er:<2d} lb{lb}: "
              f"n{ntot:>3d} TR PF{pf_tr:4.2f}(n{r_tr.trades}) TE PF{pf_te:4.2f}(n{r_te.trades}) "
              f"${r_tr.pnl + r_te.pnl:+8.1f} [{ok}]")

def main():
    coins = [c.upper() for c in sys.argv[1:]] or [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
        "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT"]
    for coin in coins:
        print(f"\n# loading {coin} ...")
        df = load_1h_remote(coin)
        if df is None or len(df) < 5000:
            print(f"  insufficient data ({0 if df is None else len(df)} bars) — skipped"); continue
        run_tf(df, "2D", 12, coin)   # the requested 2-day chart
        run_tf(df, "1D", 15, coin)   # context
    print("\n" + "=" * 74)
    print("  EVENT-1D AILESI COIN OZETI (kac config train+test IKISINDE de pozitif)")
    print("=" * 74)
    grand_n = 0; coin_pass = 0
    for coin, rows in SUMMARY.items():
        both_pos = sum(1 for (_, n, tr, te) in rows if tr > 1.2 and te > 1.0 and n >= 5)
        tot_n = max((n for (_, n, _, _) in rows), default=0)
        grand_n += tot_n
        mark = "GUCLU" if both_pos >= 3 else ("kismi" if both_pos >= 2 else "zayif")
        if both_pos >= 3: coin_pass += 1
        print(f"  {coin:<10} {both_pos}/{len(rows)} config pozitif | temsili n={tot_n:<4d} [{mark}]")
    print(f"\n  Toplam temsili islem (tum coinler): ~{grand_n}/3.5yil = ~{grand_n/3.5:.0f}/yil")
    print(f"  GUCLU coin sayisi: {coin_pass}/{len(SUMMARY)}")
    print("\nKARAR: >=5 coin GUCLU ise cok-coin scanner sleeve TASARIMINA gecmeye deger.")
    print("Aksi halde kombo kitaba girmez. (Parametreler on-kayitli, test-tuning yok.)")

if __name__ == "__main__":
    main()
