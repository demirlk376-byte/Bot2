"""
research_liquidity_sweep.py — Liquidity Sweep (stop-hunt reversal) edge testi

SONUÇ (2026-06, BTC 1h 2023-2026 + ETH 1h 2025-09→2026-04): ❌ DEPLOY EDİLMEDİ.
  • BTC: TR+TE ikisinde de pozitif, PF>1.10 olan TEK config yok. En iyi
    trend-filtreli (lb50 RR3.0) PF1.11 ama TR +$816 / TE -$369 → test döneminde
    batıyor (overfit). Trend filtresiz tüm configler zararda.
  • ETH: sadece trend-filtresi KAPALI configler pozitif (PF~1.25) — bu hipotezin
    TERSİ (FVG trend filtresiyle çalışır). Tutarsız + sadece 8 ay veri = güvenilmez.
  • Kural: BTC+ETH ikisinde de TR+TE pozitif olmazsa overfit → EKLEME. Geçemedi.
  Bu dosya negatif sonucu kayda geçirmek için duruyor; tekrar test edilmesin.

HİPOTEZ:
  Bir swing low'un (son N bar'ın dibi) altında stop-loss emirleri birikir
  ("resting liquidity"). Fiyat bu seviyenin ALTINA fitil atıp stop'ları avlar,
  ama aynı mumda tekrar ÜSTÜNE kapanırsa → bu bir sweep/stop-hunt'tır. Likidite
  toplanmıştır, fiyat genelde ters yöne (yukarı) döner. Mirror: swing high
  süpürülüp altına kapanırsa short.

  Bu, mevcut FVG/IFVG ile aynı ICT ailesinden ama farklı bir mekanizma:
  FVG = imbalance retest, Sweep = stop-hunt reversal. Düşük korelasyon beklenir.

YÖNTEM (research_daytrading2.py ile aynı dürüst disiplin):
  • 1h mumlar (botun ana timeframe'i, BB/FVG ile aynı).
  • Look-ahead yok: sinyal sweep mumunun KAPANIŞINDA üretilir, sonraki barlarda
    SL/TP simüle edilir.
  • TRAIN (2026 öncesi) ve TEST (2026+) ikisinde de PF>1.10 → gerçek edge.
  • Referans: 1H BB (doğrulanmış). Onu geçemeyen config eklenmez.

Run: python research_liquidity_sweep.py
"""
from __future__ import annotations
import glob, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from indicators import atr, ema

COST  = 0.0002          # taker round-trip proxy (research_daytrading2 ile aynı)
BAL   = 10_000.0
RISK  = 0.02
SPLIT = pd.Timestamp("2026-01-01", tz="UTC")


# ── veri yükleme ──────────────────────────────────────────────────────────────

def load_1m(pattern: str) -> pd.DataFrame:
    files = sorted(glob.glob(pattern))
    if not files:
        return pd.DataFrame()
    frames = []
    for f in files:
        df = pd.read_csv(f).rename(columns={"open_time": "ts"})
        frames.append(df[["ts", "open", "high", "low", "close", "volume"]].astype(float))
    m = (pd.concat(frames, ignore_index=True)
           .drop_duplicates(subset="ts").sort_values("ts"))
    m.index = pd.to_datetime(m["ts"], unit="ms", utc=True)
    return m


def to_tf(df_1m, rule):
    return df_1m.resample(rule).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()


# ── sonuç formatı (research_daytrading2.score ile birebir) ────────────────────

def score(trades, label):
    if not trades:
        return f"{label:<54}  NO TRADES"
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
    bal = np.cumsum(p)
    dd  = abs(((bal - np.maximum.accumulate(bal)) /
               (BAL + np.maximum.accumulate(bal))).min()) * 100
    days = max((trades[-1]["ts"] - trades[0]["ts"]).days, 1)
    return (f"{label:<54} {len(p):>4}t WR{(p>0).mean():.0%} PF{pf:.2f} "
            f"${p.sum():>+7.0f}({p.sum()/100:>+5.1f}%) DD{dd:.1f}% tpd={len(p)/days:.2f} "
            f"| TR {_s(tr)} | TE {_s(te)}")


# ── Liquidity Sweep stratejisi ────────────────────────────────────────────────

def strat_sweep(df, lookback, sl_buf_atr, rr, max_hold,
                use_trend=True, ema_period=200, min_wick_atr=0.0):
    """
    Swing low/high sweep + reclaim reversal on 1h candles.

    lookback     : swing seviyesini bulmak için bakılan bar sayısı (current hariç)
    sl_buf_atr   : SL = sweep wick ± buf×ATR
    rr           : TP = entry ± rr × stop-distance
    max_hold     : sinyal mumundan sonra max kaç bar tutulur
    use_trend    : EMA200 trend filtresi (long sadece EMA üstü, short altı)
    min_wick_atr : sweep fitili en az bu kadar ATR derinliğe inmeli (0 = kapalı)
    """
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    n = len(c)
    at = atr(df["high"], df["low"], df["close"], 14).values
    em = ema(df["close"], ema_period).values if use_trend else np.full(n, np.nan)

    balance = BAL
    open_t = None
    trades = []

    start = max(lookback + 1, ema_period + 1 if use_trend else 15, 15)
    for i in range(start, n):
        # ── açık pozisyon yönetimi ──
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

        if np.isnan(at[i]) or at[i] <= 0:
            continue
        if use_trend and np.isnan(em[i]):
            continue

        # Swing seviyeleri: current bar (i) HARİÇ, önceki lookback bar.
        win_l = l[i - lookback:i]
        win_h = h[i - lookback:i]
        swing_low = win_l.min()
        swing_high = win_h.max()

        direction = 0
        # Bullish sweep: bu mumun dibi swing low'u deldi AMA kapanış üstte (reclaim).
        if l[i] < swing_low and c[i] > swing_low:
            wick = swing_low - l[i]
            if wick >= min_wick_atr * at[i]:
                if not use_trend or c[i] > em[i]:
                    direction = 1
        # Bearish sweep: tepe swing high'ı deldi ama kapanış altta.
        if direction == 0 and h[i] > swing_high and c[i] < swing_high:
            wick = h[i] - swing_high
            if wick >= min_wick_atr * at[i]:
                if not use_trend or c[i] < em[i]:
                    direction = -1
        if direction == 0:
            continue

        entry = c[i]
        if direction == 1:
            sl = l[i] - sl_buf_atr * at[i]
            sl_d = entry - sl
        else:
            sl = h[i] + sl_buf_atr * at[i]
            sl_d = sl - entry
        if sl_d <= 0:
            continue
        tp = entry + direction * rr * sl_d
        qty = min(round(balance * RISK / sl_d, 3), balance * 0.5 / entry)
        if qty < 0.001:
            continue
        open_t = {"i": i, "dir": direction, "entry": entry,
                  "sl": sl, "tp": tp, "qty": qty}
    return trades


# ── main ──────────────────────────────────────────────────────────────────────

def run_for(name, m):
    if m.empty:
        print(f"\n{name}: veri yok, atlanıyor.")
        return
    df1h = to_tf(m, "1h")
    print(f"\n{'='*120}\n{name}  (1h bars={len(df1h)}, "
          f"{df1h.index[0].date()} → {df1h.index[-1].date()})")
    print("-" * 120)

    # Referans: doğrulanmış 1H BB
    try:
        from research_daytrading import backtest as bt1h
        ref = bt1h(df1h, 20, 2.0, 3.0, 5.0 / 3.0, 48)
        print(score(ref, "REF 1H BB(20,2) SL3ATR TP1.67 mh48"))
    except Exception as e:
        print(f"REF BB çalışmadı: {e}")
    print("-" * 120)

    # Parametre taraması
    best = None
    for lb in [10, 20, 30, 50]:
        for slb in [0.1, 0.25, 0.5]:
            for rr in [1.5, 2.0, 2.5, 3.0]:
                for trend in [True, False]:
                    t = strat_sweep(df1h, lb, slb, rr, max_hold=24,
                                    use_trend=trend, min_wick_atr=0.0)
                    tag = "T" if trend else "-"
                    lbl = f"Sweep lb{lb} SLbuf{slb} RR{rr} trend{tag}"
                    line = score(t, lbl)
                    print(line)
                    # En iyi: PF, hem TR hem TE pozitif, yeterli trade
                    if t:
                        p = np.array([x["pnl"] for x in t])
                        tr = [x for x in t if x["ts"] < SPLIT]
                        te = [x for x in t if x["ts"] >= SPLIT]
                        if tr and te and len(p) >= 30:
                            tr_pos = sum(x["pnl"] for x in tr) > 0
                            te_pos = sum(x["pnl"] for x in te) > 0
                            gp = p[p > 0].sum() if (p > 0).any() else 0
                            gl = abs(p[p < 0].sum()) if (p < 0).any() else 1
                            pf = gp / gl
                            if tr_pos and te_pos and pf > 1.10:
                                if best is None or pf > best[0]:
                                    best = (pf, lbl, p.sum())
    if best:
        print(f"\n>>> {name} EN İYİ (TR+TE pozitif, PF>1.10): "
              f"{best[1]}  PF{best[0]:.2f}  ${best[2]:+.0f}")
    else:
        print(f"\n>>> {name}: TR+TE ikisinde de pozitif, PF>1.10 olan config YOK.")


def main():
    print("Veri yükleniyor…")
    btc = load_1m("/home/user/Bot2/BTCUSDT-1m-*.csv")
    eth = load_1m("/home/user/Bot2/eth_data/ETHUSDT-1m-*.csv")
    sol = load_1m("/home/user/Bot2/sol_data/SOLUSDT-1m-*.csv")

    run_for("BTC", btc)
    run_for("ETH", eth)
    run_for("SOL", sol)

    print("\n" + "=" * 120)
    print("YORUM: Sadece BTC+ETH ikisinde de TR+TE pozitif & PF>1.10 olursa deploy.")
    print("       Tek coinde çalışıp diğerinde çökerse = overfit, EKLEME.")


if __name__ == "__main__":
    main()
