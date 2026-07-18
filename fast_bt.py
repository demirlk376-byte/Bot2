"""
fast_bt.py — VEKTÖREL, HIZLI backtest. Göstergeleri BİR KEZ hesaplar, sadece
sinyaller üzerinde döner → 3 yıl saniyeler sürer (replay_recent saatlerce
sürüyordu). Sleeve başına izole, yıl-yıl PF/WR/getiri.

Doğrulanmış kazananlar: donchian (BTC 4/4 yıl +) ve squeeze (BTC+SOL 4/4 yıl +).

Veri: yerel BTCUSDT-1m-*.csv (varsa) yoksa MEXC (VPS). Coin arg ile.
Kullanım:
  python fast_bt.py donchian BTC
  python fast_bt.py squeeze SOL
  python fast_bt.py all BTC          # tüm kazananlar tek coinde
"""
from __future__ import annotations
import sys, glob
from datetime import datetime, timezone
def datetimeutc(): return datetime.now(timezone.utc).timestamp()
import numpy as np, pandas as pd

RISK = 0.02          # sleeve başına per-trade risk (R ölçeği)
BAL = 190.0
FEE = 0.0001


def load(coin: str) -> pd.DataFrame:
    files = sorted(glob.glob(f"BTCUSDT-1m-*.csv")) if coin == "BTC" else []
    if files:
        fr = []
        for f in files:
            d = pd.read_csv(f); d.columns = ["ts","o","h","l","c","v","ct","qv","n","a","b","g"]
            fr.append(d[["ts","o","h","l","c","v"]].astype(float))
        m = pd.concat(fr).drop_duplicates("ts").sort_values("ts")
        m.index = pd.to_datetime(m["ts"], unit="ms", utc=True)
        m = m.rename(columns={"o":"open","h":"high","l":"low","c":"close","v":"volume"})
        return m.drop(columns=["ts"])
    import ccxt
    ex = ccxt.mexc()
    since = int((datetimeutc() - 1200*86400)*1000)
    rows = []
    while True:
        b = ex.fetch_ohlcv(f"{coin}/USDT", "1h", since=since, limit=500)
        if not b: break
        rows += b
        if len(b) < 500: break
        since = b[-1][0] + 1
    if not rows:
        raise SystemExit(f"{coin}: MEXC 1h verisi çekilemedi")
    m = pd.DataFrame(rows, columns=["ts","open","high","low","close","volume"])
    m.index = pd.to_datetime(m["ts"], unit="ms", utc=True)
    return m.drop(columns=["ts"]).astype(float).iloc[:-1]   # 1h; sleeve'ler 4h'a resample eder


def resample(m, tf):
    return m.resample(tf).agg({"open":"first","high":"max","low":"min",
                               "close":"last","volume":"sum"}).dropna()


def atr(df, p=14):
    h,l,c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/p, adjust=False).mean()


def sim(entries, df, sl_mult, rr, max_hold, atr_arr, is_atr_sl=True, rng_sl=None):
    """entries: list (i, dir). Sadece sinyaller üzerinde döner → hızlı."""
    hi = df["high"].values; lo = df["low"].values; c = df["close"].values
    idx = df.index; n = len(c)
    trades = []
    occ = -1
    for (i, d) in entries:
        if i <= occ or i >= n-1: continue
        a = atr_arr[i]
        if is_atr_sl:
            if np.isnan(a) or a <= 0: continue
            sld = sl_mult * a
        else:
            sld = rng_sl[i]
            if sld <= 0: continue
        e = c[i]
        sl = e - d*sld; tp = e + d*rr*sld
        ep = None
        for j in range(i+1, min(i+1+max_hold, n)):
            if d == 1:
                if lo[j] <= sl: ep = sl; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= sl: ep = sl; break
                if lo[j] <= tp: ep = tp; break
            occ_j = j
        if ep is None:
            j = min(i+max_hold, n-1); ep = c[j]
        r = d*(ep-e)/sld - 2*FEE*e/sld
        trades.append({"r": r, "year": idx[i].year})
        occ = j
    return trades


def donchian(m):
    d = resample(m, "4h")
    ch = 40; ema_p = 200
    hh = d["high"].rolling(ch).max().shift(1)
    ll = d["low"].rolling(ch).min().shift(1)
    ema = d["close"].ewm(span=ema_p, adjust=False).mean()
    c = d["close"]
    long_s = (c > hh) & (c > ema)
    short_s = (c < ll) & (c < ema)
    a = atr(d).values
    ent = [(i,1) for i in np.where(long_s.values)[0]] + [(i,-1) for i in np.where(short_s.values)[0]]
    ent.sort()
    return sim(ent, d, 2.0, 2.0, 30, a)   # SL 2xATR, RR2, max-hold 30x4h=120h


def squeeze(m):
    d = resample(m, "1h")
    c = d["close"]
    bb_mid = c.rolling(20).mean(); bb_sd = c.rolling(20).std(ddof=0)
    bb_u, bb_l = bb_mid + 2*bb_sd, bb_mid - 2*bb_sd
    ema20 = c.ewm(span=20, adjust=False).mean()
    a1 = atr(d, 20)
    kc_u, kc_l = ema20 + 1.5*a1, ema20 - 1.5*a1
    in_sq = (bb_u < kc_u) & (bb_l > kc_l)
    cnt = in_sq.groupby((~in_sq).cumsum()).cumcount()   # ardışık squeeze sayısı
    was = in_sq.shift(1).fillna(False)
    release = (~in_sq) & was & (cnt.shift(1).fillna(0) >= 5)
    direction = np.where(c > ema20, 1, -1)
    # 4h MTF: 4h close vs 4h KC mid
    d4 = resample(m, "4h")
    ema20_4 = d4["close"].ewm(span=20, adjust=False).mean()
    dir4 = (d4["close"] > ema20_4).reindex(d.index, method="ffill")
    a14 = atr(d, 14).values
    ent = []
    for i in np.where(release.values)[0]:
        dd = int(direction[i])
        agree = (dir4.values[i] and dd == 1) or ((not dir4.values[i]) and dd == -1)
        if agree:
            ent.append((i, dd))
    return sim(ent, d, 2.0, 2.5, 48, a14)   # SL 2xATR, RR2.5, max-hold 48h


def report(name, trades):
    if not trades:
        print(f"  {name}: sinyal yok"); return 0.0
    df = pd.DataFrame(trades)
    r = df["r"].values
    wr = (r>0).mean(); tot = r.sum()
    gp = r[r>0].sum(); gl = -r[r<0].sum()
    pf = gp/gl if gl>0 else 9.99
    usd = tot*BAL*RISK
    print(f"  {name:10s} n={len(r):>3d} WR{wr:>3.0%} PF{pf:4.2f} tot{tot:+6.1f}R ≈${usd:+7.2f}")
    for yr in sorted(df["year"].unique()):
        ry = df[df.year==yr]["r"].values
        g1 = ry[ry>0].sum(); g2 = -ry[ry<0].sum()
        pfy = g1/g2 if g2>0 else 9.99
        print(f"      {yr}  n={len(ry):>3d} WR{(ry>0).mean():>3.0%} PF{pfy:4.2f} {ry.sum()*BAL*RISK:+7.2f}$")
    return usd


def main():
    sleeve = sys.argv[1] if len(sys.argv) > 1 else "all"
    coin = sys.argv[2] if len(sys.argv) > 2 else "BTC"
    print(f"fast_bt: {sleeve} @ {coin} — veri yükleniyor...")
    m = load(coin)
    print(f"  {len(m)} 1m bar → {m.index[0].date()}..{m.index[-1].date()}")
    print(f"\n=== {coin} ===")
    if sleeve in ("donchian","all"):
        report("donchian", donchian(m))
    if sleeve in ("squeeze","all"):
        report("squeeze", squeeze(m))


if __name__ == "__main__":
    main()
