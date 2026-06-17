"""
research_orderflow_delta.py — Order-Flow Delta edge testi (KENDİ fikrimiz)

SONUÇ (2026-06, BTC 1h 2023-2026 + ETH 1h 2025-09→2026-04): ⚠️ CANLI'YA EKLENMEDİ.
  • BTC ABSORPTION (lb20 ratio0.55, RR ailesi) sağlam görünüyor: 122-124 trade,
    PF 1.21→1.47, TR+TE ikisi de pozitif, RR'ye karşı dayanıklı.
  • AMA yıl-yıl kırılım açığa çıkardı: 2023 ✅ / 2024 ❌(PF0.58, -$384) / 2025 ✅ /
    2026 ✅. FVG'nin "her yıl pozitif" barajını geçemiyor; kâr 2025'te yoğun.
  • ETH'de Absorption sadece ~11 trade (8 ay veri, nadir koşul) → teyit edilemez.
    ETH'de DeltaDiv güçlü (PF~1.75) ama BTC'de DeltaDiv TE döneminde batıyor.
  • Karar: gerçek edge VAR ama dağınık/regime-bağımlı. Canlı para riski için
    yeterince sağlam değil. Doğru yol: funding.py gibi MONITOR modunda canlı
    sinyal loglamak, birkaç hafta forward-veri toplayıp sonra karar vermek.

FİKİR (sıfırdan, mevcut stratejilerin hiçbiri order flow kullanmıyor):
  Binance 1m CSV'de taker_buy_volume var = agresif (market-emir) alıcı hacmi.
    delta      = taker_buy - taker_sell = 2·taker_buy − volume   (mum başına)
    buy_ratio  = taker_buy / volume                              (0.5 = nötr)
  Fiyat sadece NE yaptığını söyler; delta KİMİN yaptığını söyler. İki bağımsız
  hipotez test ediyoruz:

  A) ABSORPTION (emilim):
     Fiyat yeni N-bar dibine iner AMA o mumda agresif ALIM baskın (buy_ratio
     yüksek) → satışı birisi emiyor (kurumsal alım) → long. Mirror: yeni tepe +
     agresif satış baskın → short.

  B) DELTA DIVERGENCE (uyumsuzluk):
     Fiyat yeni N-bar dibi yapar ama kümülatif delta önceki dibe göre DAHA YÜKSEK
     (satış baskısı zayıflıyor) → long. Mirror tepe için short.

YÖNTEM (research_daytrading2.py disiplini):
  • 1h mumlar. taker_buy_volume 1m'den toplanarak 1h'a taşınır.
  • Look-ahead yok: sinyal mum kapanışında üretilir, sonraki barlarda SL/TP simüle.
  • TRAIN (<2026) + TEST (≥2026) ikisinde de PF>1.10 → gerçek edge.
  • BTC + ETH ikisinde de tutmazsa = overfit, EKLEME.

Run: python research_orderflow_delta.py
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


# ── veri yükleme (taker_buy_volume DAHİL) ─────────────────────────────────────

def load_1m(pattern: str) -> pd.DataFrame:
    files = sorted(glob.glob(pattern))
    if not files:
        return pd.DataFrame()
    frames = []
    for f in files:
        df = pd.read_csv(f).rename(columns={"open_time": "ts"})
        cols = ["ts", "open", "high", "low", "close", "volume", "taker_buy_volume"]
        frames.append(df[cols].astype(float))
    m = (pd.concat(frames, ignore_index=True)
           .drop_duplicates(subset="ts").sort_values("ts"))
    m.index = pd.to_datetime(m["ts"], unit="ms", utc=True)
    return m


def to_1h(df_1m):
    h = df_1m.resample("1h").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "volume": "sum", "taker_buy_volume": "sum",
    }).dropna()
    # delta = taker_buy − taker_sell = 2·taker_buy − volume
    h["delta"] = 2.0 * h["taker_buy_volume"] - h["volume"]
    h["buy_ratio"] = (h["taker_buy_volume"] / h["volume"]).clip(0, 1)
    return h


# ── skor (research_daytrading2.score birebir) ─────────────────────────────────

def score(trades, label):
    if not trades:
        return f"{label:<52}  NO TRADES"
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
    return (f"{label:<52} {len(p):>4}t WR{(p>0).mean():.0%} PF{pf:.2f} "
            f"${p.sum():>+7.0f}({p.sum()/100:>+5.1f}%) DD{dd:.1f}% tpd={len(p)/days:.2f} "
            f"| TR {_s(tr)} | TE {_s(te)}")


def _passes(trades, min_trades=40):
    """TR+TE ikisinde de pozitif ve PF>1.10 mı?"""
    if not trades:
        return None
    p  = np.array([t["pnl"] for t in trades])
    tr = [t for t in trades if t["ts"] < SPLIT]
    te = [t for t in trades if t["ts"] >= SPLIT]
    if not tr or not te or len(p) < min_trades:
        return None
    gp = p[p > 0].sum() if (p > 0).any() else 0
    gl = abs(p[p < 0].sum()) if (p < 0).any() else 1
    pf = gp / gl
    if (sum(t["pnl"] for t in tr) > 0 and sum(t["pnl"] for t in te) > 0 and pf > 1.10):
        return (pf, p.sum())
    return None


# ── ortak pozisyon simülasyonu ────────────────────────────────────────────────

def _simulate(df, signals, sl_atr, rr, max_hold):
    """signals: i → direction (+1/-1) açılış istekleri. Tek pozisyon, ATR-SL."""
    h = df["high"].values; l = df["low"].values; c = df["close"].values
    at = atr(df["high"], df["low"], df["close"], 14).values
    n = len(c)
    balance = BAL; open_t = None; trades = []
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
        sl = entry - direction * sl_d
        tp = entry + direction * rr * sl_d
        qty = min(round(balance * RISK / sl_d, 3), balance * 0.5 / entry)
        if qty < 0.001:
            continue
        open_t = {"i": i, "dir": direction, "entry": entry, "sl": sl, "tp": tp, "qty": qty}
    return trades


# ── A: ABSORPTION ─────────────────────────────────────────────────────────────

def strat_absorption(df, lookback, ratio_thr, sl_atr, rr, max_hold,
                     use_trend=True, ema_period=200):
    l = df["low"].values; h = df["high"].values; c = df["close"].values
    br = df["buy_ratio"].values
    em = ema(df["close"], ema_period).values if use_trend else None
    n = len(c)
    sig = {}
    start = max(lookback + 1, ema_period + 1 if use_trend else 15)
    for i in range(start, n):
        if np.isnan(br[i]):
            continue
        swing_low = l[i - lookback:i].min()
        swing_high = h[i - lookback:i].max()
        # yeni dip + agresif alım baskın → long
        if l[i] <= swing_low and br[i] >= ratio_thr:
            if not use_trend or (em is not None and not np.isnan(em[i]) and c[i] > em[i]):
                sig[i] = 1; continue
        # yeni tepe + agresif satış baskın (düşük buy_ratio) → short
        if h[i] >= swing_high and br[i] <= (1.0 - ratio_thr):
            if not use_trend or (em is not None and not np.isnan(em[i]) and c[i] < em[i]):
                sig[i] = -1
    return _simulate(df, sig, sl_atr, rr, max_hold)


# ── B: DELTA DIVERGENCE ───────────────────────────────────────────────────────

def strat_delta_div(df, lookback, sl_atr, rr, max_hold,
                    use_trend=True, ema_period=200):
    l = df["low"].values; h = df["high"].values; c = df["close"].values
    # kümülatif delta
    cum = df["delta"].cumsum().values
    em = ema(df["close"], ema_period).values if use_trend else None
    n = len(c)
    sig = {}
    start = max(lookback + 1, ema_period + 1 if use_trend else 15)
    for i in range(start, n):
        win_l = l[i - lookback:i + 1]
        win_h = h[i - lookback:i + 1]
        # fiyat yeni dip mi? (pencerenin en düşüğü bu bar)
        if l[i] <= win_l.min():
            # önceki dibin indexi (bu bar hariç pencerede en düşük)
            prev = i - lookback + int(np.argmin(l[i - lookback:i]))
            # bullish divergence: fiyat daha düşük/eşit ama cum delta daha yüksek
            if cum[i] > cum[prev]:
                if not use_trend or (em is not None and not np.isnan(em[i]) and c[i] > em[i]):
                    sig[i] = 1; continue
        if h[i] >= win_h.max():
            prev = i - lookback + int(np.argmax(h[i - lookback:i]))
            if cum[i] < cum[prev]:
                if not use_trend or (em is not None and not np.isnan(em[i]) and c[i] < em[i]):
                    sig[i] = -1
    return _simulate(df, sig, sl_atr, rr, max_hold)


# ── main ──────────────────────────────────────────────────────────────────────

def run_for(name, m):
    if m.empty:
        print(f"\n{name}: veri yok, atlanıyor.")
        return
    df = to_1h(m)
    print(f"\n{'='*120}\n{name}  (1h bars={len(df)}, "
          f"{df.index[0].date()} → {df.index[-1].date()}, "
          f"ort buy_ratio={df['buy_ratio'].mean():.3f})")
    print("-" * 120)
    try:
        from research_daytrading import backtest as bt1h
        ref = bt1h(df, 20, 2.0, 3.0, 5.0 / 3.0, 48)
        print(score(ref, "REF 1H BB(20,2) SL3ATR TP1.67 mh48"))
    except Exception as e:
        print(f"REF BB: {e}")
    print("-" * 120)

    best = None
    print("A) ABSORPTION (yeni dip/tepe + agresif akış)")
    for lb in [10, 20, 40]:
        for thr in [0.55, 0.60, 0.65]:
            for rr in [1.5, 2.0, 2.5]:
                for trend in [True, False]:
                    t = strat_absorption(df, lb, thr, 2.0, rr, 24, use_trend=trend)
                    tag = "T" if trend else "-"
                    lbl = f"Absorp lb{lb} ratio{thr} RR{rr} tr{tag}"
                    print(score(t, lbl))
                    r = _passes(t)
                    if r and (best is None or r[0] > best[0]):
                        best = (r[0], "A:" + lbl, r[1])

    print("\nB) DELTA DIVERGENCE (fiyat dip ama akış güçleniyor)")
    for lb in [10, 20, 40]:
        for sl in [1.5, 2.0, 3.0]:
            for rr in [1.5, 2.0, 2.5]:
                for trend in [True, False]:
                    t = strat_delta_div(df, lb, sl, rr, 24, use_trend=trend)
                    tag = "T" if trend else "-"
                    lbl = f"DeltaDiv lb{lb} SL{sl} RR{rr} tr{tag}"
                    print(score(t, lbl))
                    r = _passes(t)
                    if r and (best is None or r[0] > best[0]):
                        best = (r[0], "B:" + lbl, r[1])

    if best:
        print(f"\n>>> {name} EN İYİ (TR+TE pozitif, PF>1.10): {best[1]}  "
              f"PF{best[0]:.2f}  ${best[2]:+.0f}")
    else:
        print(f"\n>>> {name}: TR+TE pozitif, PF>1.10 config YOK.")
    return best


def main():
    print("Veri yükleniyor (taker_buy_volume dahil)…")
    btc = load_1m("/home/user/Bot2/BTCUSDT-1m-*.csv")
    eth = load_1m("/home/user/Bot2/eth_data/ETHUSDT-1m-*.csv")
    b = run_for("BTC", btc)
    e = run_for("ETH", eth)
    print("\n" + "=" * 120)
    if b and e:
        print(f"SONUÇ: BTC {b[1]} (PF{b[0]:.2f}) + ETH {e[1]} (PF{e[0]:.2f})")
        print("       İkisi de geçti — ortak config varsa deploy değerlendir.")
    else:
        print("SONUÇ: BTC veya ETH geçemedi → overfit riski, deploy ETME.")


if __name__ == "__main__":
    main()
