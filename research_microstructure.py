"""
research_microstructure.py — Mikroyapı edge avı (KENDİ fikrimiz #2)

SONUÇ (2026-06): ✅ EDGE GERÇEK, ⚠️ ama MEXC futures `count` vermiyor.
  • WHALE SIZE (avg_size = quote_volume/count, z-spike yönünde git) katı barajı
    HER İKİ coinde geçti: BTC z2.0 SL2.0 RR2.0 PF1.17 (2023-26 HER YIL pozitif,
    512t); ETH z2.0 ailesi PF1.18-1.23 (iki dönem pozitif). Parametre ailesi
    boyunca dayanıklı = gerçek edge, sweep/delta'dan çok daha sağlam.
  • COUNT CLIMAX (retail panik fade): zayıf, geçmedi.
  • DEPLOY ENGELİ: MEXC futures kline `time,o,h,l,c,vol,amount` döner — `count`
    (işlem ADEDİ) YOK. count'suz proxy (sadece volume/quote_volume z-spike) edge'i
    KORUMUYOR (BTC 2025 zararda) → edge gerçekten balina-BÜYÜKLÜĞÜNDE, ham hacimde
    değil. Deploy için canlı watch_trades aggregator gerekir (saatlik say + avg
    size + 168h z-score, 1 hafta warmup). Ayrı bir proje.

İki YENİ standalone sinyal, Binance CSV'nin az kullanılan kolonlarından:
  • count        = mum içindeki işlem ADEDİ (retail yoğunluğu / panik proxy)
  • quote_volume = USDT cinsi hacim
  • avg_size     = quote_volume / count = ORTALAMA İŞLEM BÜYÜKLÜĞÜ
                   büyük = balina/kurumsal, küçük = retail

HİPOTEZLER:
  A) COUNT CLIMAX (retail panik fade):
     Fiyat yeni N-bar ekstremindeyken işlem ADEDİ anormal yüksek (z-score) =
     retail kapitülasyon/FOMO doruğu → TERS yöne fade (mean reversion).
  B) WHALE SIZE (akıllı para takip):
     Ortalama işlem büyüklüğü anormal yüksek = balinalar agresif → mumun
     YÖNÜNDE git (kurumsal commitment, devam).

YÖNTEM: research_daytrading2 disiplini + bu sefer YIL-YIL kırılım baştan dahil.
  • 1h mumlar. count/quote_volume 1m'den toplanır.
  • Look-ahead yok. TRAIN(<2026)+TEST(≥2026) pozitif VE her yıl pozitif → deploy.
  • BTC + ETH ikisinde de tutmazsa = overfit, EKLEME.

Run: python research_microstructure.py
"""
from __future__ import annotations
import glob, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from indicators import atr, ema

COST  = 0.0002
BAL   = 10_000.0
RISK  = 0.02
SPLIT = pd.Timestamp("2026-01-01", tz="UTC")


def load_1m(pattern: str) -> pd.DataFrame:
    files = sorted(glob.glob(pattern))
    if not files:
        return pd.DataFrame()
    frames = []
    for f in files:
        df = pd.read_csv(f).rename(columns={"open_time": "ts"})
        cols = ["ts", "open", "high", "low", "close", "volume", "quote_volume", "count"]
        frames.append(df[cols].astype(float))
    m = (pd.concat(frames, ignore_index=True)
           .drop_duplicates(subset="ts").sort_values("ts"))
    m.index = pd.to_datetime(m["ts"], unit="ms", utc=True)
    return m


def to_1h(df_1m):
    h = df_1m.resample("1h").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "volume": "sum", "quote_volume": "sum", "count": "sum",
    }).dropna()
    h["avg_size"] = h["quote_volume"] / h["count"].replace(0, np.nan)
    return h


def _zscore(s, win):
    m = s.rolling(win).mean()
    sd = s.rolling(win).std()
    return (s - m) / sd.replace(0, np.nan)


def score(trades, label):
    if not trades:
        return f"{label:<48}  NO TRADES"
    p  = np.array([t["pnl"] for t in trades])
    tr = [t for t in trades if t["ts"] < SPLIT]
    te = [t for t in trades if t["ts"] >= SPLIT]
    def _s(lst):
        if not lst: return "—"
        pp = np.array([t["pnl"] for t in lst])
        return f"W{(pp>0).mean():.0%} ${pp.sum():>+6.0f}"
    gp = p[p > 0].sum() if (p > 0).any() else 0
    gl = abs(p[p < 0].sum()) if (p < 0).any() else 1
    pf = gp / gl
    return (f"{label:<48} {len(p):>4}t WR{(p>0).mean():.0%} PF{pf:.2f} "
            f"${p.sum():>+7.0f}({p.sum()/100:>+5.1f}%) | TR {_s(tr)} | TE {_s(te)}")


def _years(trades):
    """Yıl-yıl PF/PnL stringi + her yıl pozitif mi bool."""
    if not trades:
        return "", False
    tdf = pd.DataFrame(trades)
    tdf["year"] = pd.to_datetime(tdf["ts"]).dt.year
    parts = []; all_pos = True
    for y, g in tdf.groupby("year"):
        p = g["pnl"].values
        gp = p[p > 0].sum(); gl = abs(p[p < 0].sum()) or 1
        s = p.sum()
        parts.append(f"{y}:{gp/gl:.2f}/{s:+.0f}")
        if s <= 0 and len(p) >= 5:
            all_pos = False
    return " ".join(parts), all_pos


def _simulate(df, signals, sl_atr, rr, max_hold):
    h = df["high"].values; l = df["low"].values; c = df["close"].values
    at = atr(df["high"], df["low"], df["close"], 14).values
    n = len(c); balance = BAL; open_t = None; trades = []
    for i in range(n):
        if open_t is not None:
            d = open_t["dir"]; ep = None; entry = open_t["entry"]
            if d == 1:
                if l[i] <= open_t["sl"]:   ep = open_t["sl"]
                elif h[i] >= open_t["tp"]: ep = open_t["tp"]
            else:
                if h[i] >= open_t["sl"]:   ep = open_t["sl"]
                elif l[i] <= open_t["tp"]: ep = open_t["tp"]
            if ep is None and (i - open_t["i"]) >= max_hold:
                ep = c[i]
            if ep is not None:
                pnl = (d * (ep - entry) * open_t["qty"]
                       - (entry + ep) * open_t["qty"] * COST)
                balance += pnl
                trades.append({"ts": df.index[i], "pnl": pnl})
                open_t = None
            continue
        direction = signals.get(i, 0)
        if direction == 0 or np.isnan(at[i]) or at[i] <= 0:
            continue
        entry = c[i]; sl_d = sl_atr * at[i]
        sl = entry - direction * sl_d; tp = entry + direction * rr * sl_d
        qty = min(round(balance * RISK / sl_d, 3), balance * 0.5 / entry)
        if qty < 0.001:
            continue
        open_t = {"i": i, "dir": direction, "entry": entry, "sl": sl, "tp": tp, "qty": qty}
    return trades


# ── A: COUNT CLIMAX (retail panik fade) ───────────────────────────────────────

def strat_count_climax(df, lookback, z_thr, zwin, sl_atr, rr, max_hold):
    l = df["low"].values; h = df["high"].values; c = df["close"].values
    cz = _zscore(df["count"], zwin).values
    n = len(c); sig = {}
    start = max(lookback + 1, zwin + 1)
    for i in range(start, n):
        if np.isnan(cz[i]) or cz[i] < z_thr:
            continue
        swing_low = l[i - lookback:i].min()
        swing_high = h[i - lookback:i].max()
        # yeni dipte panik adedi → long (fade aşağı climax)
        if l[i] <= swing_low:
            sig[i] = 1
        elif h[i] >= swing_high:
            sig[i] = -1
    return _simulate(df, sig, sl_atr, rr, max_hold)


# ── B: WHALE SIZE (akıllı para takip) ─────────────────────────────────────────

def strat_whale_follow(df, z_thr, zwin, sl_atr, rr, max_hold):
    c = df["close"].values; o = df["open"].values
    az = _zscore(df["avg_size"], zwin).values
    n = len(c); sig = {}
    for i in range(zwin + 1, n):
        if np.isnan(az[i]) or az[i] < z_thr:
            continue
        # balina mumu: yönünü kapanış-açılıştan al
        if c[i] > o[i]:
            sig[i] = 1
        elif c[i] < o[i]:
            sig[i] = -1
    return _simulate(df, sig, sl_atr, rr, max_hold)


def run_for(name, m):
    if m.empty:
        print(f"\n{name}: veri yok."); return []
    df = to_1h(m)
    print(f"\n{'='*120}\n{name}  (1h bars={len(df)}, "
          f"{df.index[0].date()} → {df.index[-1].date()})")
    print("-" * 120)
    winners = []

    print("A) COUNT CLIMAX (yeni ekstrem + işlem-adedi z-spike → fade)")
    for lb in [10, 20]:
        for z in [1.5, 2.0, 2.5]:
            for rr in [1.5, 2.0, 2.5]:
                t = strat_count_climax(df, lb, z, 168, 2.0, rr, 24)
                yr, allpos = _years(t)
                line = score(t, f"Count lb{lb} z{z} RR{rr}")
                print(f"{line}  [{yr}]")
                if t and len(t) >= 40:
                    p = np.array([x["pnl"] for x in t])
                    tr = sum(x["pnl"] for x in t if x["ts"] < SPLIT)
                    te = sum(x["pnl"] for x in t if x["ts"] >= SPLIT)
                    gp = p[p>0].sum() or 0; gl = abs(p[p<0].sum()) or 1
                    if tr > 0 and te > 0 and gp/gl > 1.10 and allpos:
                        winners.append((gp/gl, f"{name} A:Count lb{lb} z{z} RR{rr}", p.sum()))

    print("\nB) WHALE SIZE (ort. işlem büyüklüğü z-spike → yönünde git)")
    for z in [1.5, 2.0, 2.5, 3.0]:
        for sl in [1.5, 2.0]:
            for rr in [1.5, 2.0, 2.5]:
                t = strat_whale_follow(df, z, 168, sl, rr, 24)
                yr, allpos = _years(t)
                line = score(t, f"Whale z{z} SL{sl} RR{rr}")
                print(f"{line}  [{yr}]")
                if t and len(t) >= 40:
                    p = np.array([x["pnl"] for x in t])
                    tr = sum(x["pnl"] for x in t if x["ts"] < SPLIT)
                    te = sum(x["pnl"] for x in t if x["ts"] >= SPLIT)
                    gp = p[p>0].sum() or 0; gl = abs(p[p<0].sum()) or 1
                    if tr > 0 and te > 0 and gp/gl > 1.10 and allpos:
                        winners.append((gp/gl, f"{name} B:Whale z{z} SL{sl} RR{rr}", p.sum()))
    return winners


def main():
    print("Veri yükleniyor (count + quote_volume)…")
    btc = load_1m("/home/user/Bot2/BTCUSDT-1m-*.csv")
    eth = load_1m("/home/user/Bot2/eth_data/ETHUSDT-1m-*.csv")
    wb = run_for("BTC", btc)
    we = run_for("ETH", eth)
    print("\n" + "=" * 120)
    print("HER YIL POZİTİF + TR+TE pozitif + PF>1.10 geçenler:")
    print(f"  BTC: {[w[1] for w in wb] or 'YOK'}")
    print(f"  ETH: {[w[1] for w in we] or 'YOK'}")
    print("  → Aynı strateji ailesi İKİSİNDE de geçiyorsa deploy değerlendir.")


if __name__ == "__main__":
    main()
