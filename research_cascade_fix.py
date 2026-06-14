"""
Kötü ayları (Kas 2025 -$174) iyi ayları (Şub 2026 +$357) bozmadan düzeltmek için
3 yeni yaklaşım:

A) RSI dönüş teyidi: bb_pos<0 için RSI < 30 VE RSI bu barda yükseliyor (turning)
   → 'düşen bıçak' yakalamaktan kaçın, gerçek dip dönüşü bekle

B) Günlük kayıp limiti: BB o günde >X$ kaybettiyse yeni BB girişi alma
   → Kasım'daki seri kayıpları kır

C) Kaskad boyut küçültme: Art arda her BB kaybından sonra pozisyon yarıya in,
   kazanınca sıfırla (full-size). Sinyal bloklamaz, sadece risk azalt.

D) BB yeniden giriş: Price must come BACK inside BB (from the outside) → enter on
   the re-cross. More lag but confirms turn.
"""
from __future__ import annotations
import glob, sys
import numpy as np
import pandas as pd

sys.path.insert(0, "/home/user/Bot2")
from indicators import bollinger_bands, atr, rsi as rsi_fn

COST = 0.0002
SL_M = 3.0; TP_M = 5.0
BAL = 10_000.0; RISK = 0.03; MH = 48


def load_all():
    files = sorted(glob.glob("/home/user/Bot2/BTCUSDT-1m-*.csv"))
    frames = []
    for f in files:
        df = pd.read_csv(f)
        df.columns = ["ts","open","high","low","close","volume","ct","qv","count","tbv","tbqv","ign"]
        frames.append(df[["ts","open","high","low","close","volume"]].astype(float))
    full = pd.concat(frames, ignore_index=True).drop_duplicates(subset="ts").sort_values("ts")
    full.index = pd.to_datetime(full["ts"], unit="ms")
    return full.drop(columns=["ts"])


def resample(df, rule):
    return df.resample(rule).agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()


def backtest(df_1h, mode="baseline", daily_loss_limit=None, rsi_turn=False, rsi_min_rise=2.0,
             cascade_size=False, reentry_mode=False):
    """
    mode: 'baseline' | ...
    daily_loss_limit: float (e.g. 50.0) → stop BB if day has lost this much
    rsi_turn: bool → require RSI to be rising (for long) or falling (for short)
    rsi_min_rise: float → minimum RSI change to count as 'turning'
    cascade_size: bool → after each consecutive BB loss, halve position size (reset on win)
    reentry_mode: bool → only enter when price comes back INSIDE BB (re-cross from outside)
    """
    close = df_1h["close"].values
    high  = df_1h["high"].values
    low_v = df_1h["low"].values
    vol   = df_1h["volume"].values
    idx   = df_1h.index

    upper_s, middle_s, lower_s = bollinger_bands(df_1h["close"], 20, 2.0)
    atr_s  = atr(df_1h["high"], df_1h["low"], df_1h["close"], 14)
    rsi_s  = rsi_fn(df_1h["close"], 14).values
    vol_ma = df_1h["volume"].rolling(20).mean().values
    bb_pos = ((df_1h["close"] - lower_s) / (upper_s - lower_s).replace(0, np.nan)).values

    upper  = upper_s.values
    lower  = lower_s.values

    n = len(close); warmup = 60
    balance = BAL
    open_t  = None
    trades  = []

    # State for daily loss limit
    daily_pnl   = {}   # date_str → float
    # State for cascade sizing
    consec_bb_losses = 0   # resets on win, increments on BB loss

    # State for re-entry mode: track if price was outside BB on prev bar
    was_outside = False  # True when previous bar was outside BB

    for i in range(warmup, n):
        a = atr_s.iloc[i]
        if np.isnan(a) or a <= 0:
            continue

        # Manage open trade
        if open_t is not None:
            d     = open_t["dir"]
            entry = open_t["entry"]
            sl    = open_t["sl"]
            tp    = open_t["tp"]
            qty   = open_t["qty"]
            held  = i - open_t["i"]

            ep = None; reason = None
            if d == 1:
                if low_v[i] <= sl:  ep, reason = sl, "sl"
                elif high[i] >= tp: ep, reason = tp, "tp"
            else:
                if high[i] >= sl:   ep, reason = sl, "sl"
                elif low_v[i] <= tp:ep, reason = tp, "tp"
            if ep is None and held >= MH:
                ep, reason = close[i], "mh"

            if ep is not None:
                pnl = d * (ep - entry) * qty - (entry + ep) * qty * COST
                balance += pnl
                date_str = str(idx[i].date())
                daily_pnl[date_str] = daily_pnl.get(date_str, 0.0) + pnl
                if cascade_size:
                    if pnl < 0:
                        consec_bb_losses += 1
                    else:
                        consec_bb_losses = 0
                trades.append({"ts": idx[i], "pnl": pnl, "reason": reason,
                               "dir": d, "entry": entry})
                open_t = None
                was_outside = bb_pos[i] < 0 or bb_pos[i] > 1
            else:
                was_outside = bb_pos[i] < 0 or bb_pos[i] > 1
            continue

        # Look for entry
        bpos = bb_pos[i]
        if np.isnan(bpos):
            was_outside = False
            continue

        direction = None
        if bpos < 0.0:   direction = 1   # below lower band
        elif bpos > 1.0: direction = -1  # above upper band
        else:
            was_outside = False
            continue

        # Volume filter
        if not np.isnan(vol_ma[i]) and vol[i] < vol_ma[i]:
            was_outside = direction is not None
            continue

        # Re-entry mode: only enter when crossing BACK inside from outside
        if reentry_mode:
            # The signal fires when bpos crossed back to [0,1] side
            # We need: previous bar was outside, current bar is (just barely) outside
            # Actually: wait for the bar where bpos first goes < 0 (touch),
            # then enter NEXT bar when bpos >= 0 (came back)
            # → redefine: enter when prev was outside (direction) and current bpos is INSIDE [0,1]
            # But current bpos < 0 means still outside... need to recheck.
            # Let's define: enter only on the bar when price first re-enters the band
            # i.e., bpos < 0 in prev bar AND bpos >= 0 now (but then direction isn't triggered)
            # Alternative simpler: enter 1 bar AFTER the first outside touch.
            # For now: skip if this is not the first bar outside (i.e., prev bar was also outside same direction)
            if i > warmup:
                prev_bpos = bb_pos[i-1]
                if not np.isnan(prev_bpos):
                    if direction == 1 and prev_bpos < 0:
                        # Previous bar was also below lower band → not a fresh entry
                        was_outside = True
                        continue
                    elif direction == -1 and prev_bpos > 1:
                        was_outside = True
                        continue

        # RSI turning filter
        if rsi_turn and i >= 1:
            rsi_now  = rsi_s[i]
            rsi_prev = rsi_s[i-1]
            if np.isnan(rsi_now) or np.isnan(rsi_prev):
                was_outside = True
                continue
            if direction == 1:
                # Long: RSI must be rising (turning from bottom)
                if rsi_now - rsi_prev < rsi_min_rise:
                    was_outside = True
                    continue
            else:
                # Short: RSI must be falling (turning from top)
                if rsi_prev - rsi_now < rsi_min_rise:
                    was_outside = True
                    continue

        # Daily loss limit
        if daily_loss_limit is not None:
            date_str = str(idx[i].date())
            if daily_pnl.get(date_str, 0.0) <= -daily_loss_limit:
                was_outside = direction is not None
                continue

        # Position sizing
        ep    = close[i]
        sl_d  = SL_M * a
        sl_p  = ep - direction * sl_d
        tp_p  = ep + direction * TP_M * a
        base_qty = round((balance * RISK) / (ep * (sl_d / ep)), 3)
        base_qty = min(base_qty, balance * 0.5 / ep)

        if cascade_size and consec_bb_losses > 0:
            # Each consecutive loss halves the size
            scale = 0.5 ** consec_bb_losses
            qty = round(base_qty * scale, 3)
            qty = max(qty, 0.001)
        else:
            qty = base_qty

        if qty < 0.001:
            was_outside = True
            continue

        open_t = {"i": i, "ts": idx[i], "dir": direction,
                  "entry": ep, "sl": sl_p, "tp": tp_p, "qty": qty}
        was_outside = True  # we just entered, prev bar was outside

    return trades


def score_split(trades, split=pd.Timestamp("2026-01-01")):
    tr = [t for t in trades if t["ts"] < split]
    te = [t for t in trades if t["ts"] >= split]

    def _s(tt):
        if not tt:
            return dict(n=0, wr=0, pnl=0, pf=0, dd=0)
        p = np.array([t["pnl"] for t in tt])
        pos = p[p > 0].sum(); neg = -p[p < 0].sum()
        pf = pos / neg if neg > 0 else float("inf")
        eq = BAL + np.cumsum(p); peak = np.maximum.accumulate(eq)
        dd = ((peak - eq) / peak).max()
        return dict(n=len(p), wr=(p>0).mean(), pnl=p.sum(), pf=pf, dd=dd)

    return _s(tr), _s(te)


def monthly(trades):
    m = {}
    for t in trades:
        m.setdefault(t["ts"].strftime("%Y-%m"), []).append(t["pnl"])
    return m


def pr(label, tr, te):
    tot = tr["pnl"] + te["pnl"]
    print(f"{label:<52s}  {tr['n']+te['n']:>3d}t {tot/100:>+6.1f}%  |  "
          f"TRAIN {tr['n']:>3d}t WR{tr['wr']:>3.0%} PF{tr['pf']:.2f} ${tr['pnl']:>+7.0f}  |  "
          f"TEST {te['n']:>3d}t WR{te['wr']:>3.0%} PF{te['pf']:.2f} ${te['pnl']:>+7.0f}  |  "
          f"maxDD {max(tr['dd'],te['dd'])*100:.1f}%")


def main():
    df_1m = load_all()
    df_1h = resample(df_1m, "1h")
    split = pd.Timestamp("2026-01-01")

    print("=" * 118)
    print("KÖTÜ AYLAR DÜZELTMESİ — RSI dönüş | Günlük kayıp | Kaskad boyut | BB yeniden giriş")
    print("Train: May–Dec 2025 | Test: Jan–Apr 2026")
    print("=" * 118)

    configs = [
        # label, daily_loss_limit, rsi_turn, rsi_min_rise, cascade_size, reentry
        ("BASELINE (vol+%3 risk, 48h)",          None,   False, 0.0, False, False),
        ("A1: RSI dönüş (+1 puan)",              None,   True,  1.0, False, False),
        ("A2: RSI dönüş (+2 puan)",              None,   True,  2.0, False, False),
        ("A3: RSI dönüş (+3 puan)",              None,   True,  3.0, False, False),
        ("A4: RSI dönüş (+5 puan)",              None,   True,  5.0, False, False),
        ("B1: Günlük limit $30",                 30.0,   False, 0.0, False, False),
        ("B2: Günlük limit $50",                 50.0,   False, 0.0, False, False),
        ("B3: Günlük limit $80",                 80.0,   False, 0.0, False, False),
        ("C1: Kaskad boyut (yarı)",              None,   False, 0.0, True,  False),
        ("C2: RSI dönüş + Kaskad boyut",         None,   True,  2.0, True,  False),
        ("C3: Günlük limit + Kaskad boyut",      50.0,   False, 0.0, True,  False),
        ("D1: BB yeniden giriş (1 mum gecikme)", None,   False, 0.0, False, True),
        ("D2: BB yeniden giriş + RSI dönüş",     None,   True,  2.0, False, True),
        ("E1: RSI+2 + Günlük$50 + Kaskad",       50.0,   True,  2.0, True,  False),
    ]

    results = {}
    for label, dll, rst, rsm, cas, ree in configs:
        trades = backtest(df_1h, daily_loss_limit=dll, rsi_turn=rst, rsi_min_rise=rsm,
                          cascade_size=cas, reentry_mode=ree)
        tr, te = score_split(trades, split)
        pr(label, tr, te)
        results[label] = (trades, tr, te)

    # Monthly detail for best candidates vs baseline
    print()
    print("─" * 118)
    print("AYLIK DAĞILIM — Baseline vs seçili adaylar")
    print("─" * 118)

    candidates = ["BASELINE (vol+%3 risk, 48h)",
                  "A2: RSI dönüş (+2 puan)",
                  "B2: Günlük limit $50",
                  "C1: Kaskad boyut (yarı)",
                  "E1: RSI+2 + Günlük$50 + Kaskad"]

    month_sets = set()
    monthly_data = {}
    for label in candidates:
        trades, _, _ = results[label]
        m = monthly(trades)
        monthly_data[label] = m
        month_sets.update(m.keys())

    col_w = 12
    header = f"{'Ay':<10s}"
    for label in candidates:
        short = label[:col_w]
        header += f"  {short:>{col_w}s}"
    print(header)

    for mo in sorted(month_sets):
        row = f"  {mo:<8s}"
        for label in candidates:
            m = monthly_data[label]
            vals = np.array(m.get(mo, [0]))
            n   = len(m.get(mo, []))
            row += f"  {vals.sum():>+8.0f}({n:>2d}t)"
        print(row)

    # Summary: total pnl + DD comparison
    print()
    print("─" * 118)
    print(f"{'Strateji':<52s}  {'Toplam $':>10s}  {'maxDD':>7s}  {'Trade':>5s}  {'WR':>5s}")
    for label, dll, rst, rsm, cas, ree in configs:
        trades, tr, te = results[label]
        total = tr["pnl"] + te["pnl"]
        n_tot = tr["n"] + te["n"]
        wr_tot = (tr["wr"]*tr["n"] + te["wr"]*te["n"]) / max(n_tot, 1)
        dd = max(tr["dd"], te["dd"])
        print(f"  {label:<50s}  {total:>+10.0f}  {dd*100:>6.1f}%  {n_tot:>5d}  {wr_tot:>4.0%}")


if __name__ == "__main__":
    main()
