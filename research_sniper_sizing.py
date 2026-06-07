"""
research_sniper_sizing.py

A+ → yüksek risk, A → normal risk sıralı backtest.

Eşikler SADECE TRAIN'DEN belirlenir. TEST'e uygulanır. Look-ahead yok.

50% balance cap meselesini de netleştirir: yüksek risk A+'da cap'i aşıyor mu?
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from indicators import bollinger_bands, atr

COST  = 0.0002
BAL   = 10_000.0
RISK_BASE  = 0.03
RISK_A     = 0.03
RISK_APLUS = 0.08
SL_M  = 3.0
TP_M  = 5.0
MH    = 48
SPLIT = pd.Timestamp("2026-01-01")


def load_1h():
    files = sorted(glob.glob("/home/user/Bot2/BTCUSDT-1m-*.csv"))
    frames = []
    for f in files:
        df = pd.read_csv(f).rename(columns={"open_time": "ts"})
        frames.append(df[["ts", "open", "high", "low", "close",
                          "volume", "taker_buy_volume"]].astype(float))
    m = (pd.concat(frames, ignore_index=True)
         .drop_duplicates(subset="ts").sort_values("ts"))
    m.index = pd.to_datetime(m["ts"], unit="ms")
    m = m.drop(columns=["ts"])
    return m.resample("1h").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last",
         "volume": "sum", "taker_buy_volume": "sum"}
    ).dropna()


def compute_indicators(df_1h):
    upper, _, lower = bollinger_bands(df_1h["close"], 20, 2.0)
    atr_s  = atr(df_1h["high"], df_1h["low"], df_1h["close"], 14)
    vol_ma = df_1h["volume"].rolling(20).mean()
    atr_pct_s = atr_s.rolling(200).apply(lambda w: (w.iloc[-1] >= w).mean(), raw=False)
    typical = (df_1h["high"] + df_1h["low"] + df_1h["close"]) / 3.0
    pv = (typical * df_1h["volume"]).rolling(168).sum()
    vv = df_1h["volume"].rolling(168).sum()
    vwap = pv / vv
    return upper, lower, atr_s, vol_ma, atr_pct_s, vwap


def run(df_1h, thresholds, risk_aplus, risk_a, skip_c=True):
    """Sıralı backtest: her bar'da grade'e göre risk uygula."""
    c   = df_1h["close"].values
    h   = df_1h["high"].values
    lo  = df_1h["low"].values
    vol = df_1h["volume"].values
    tbv = df_1h["taker_buy_volume"].values
    upper, lower, atr_s, vol_ma, atr_pct_s, vwap = compute_indicators(df_1h)

    bb_pos = ((df_1h["close"] - lower) / (upper - lower).replace(0, np.nan)).values
    vol_ma_v = vol_ma.values
    atr_pct_v = atr_pct_s.values
    vwap_v = vwap.values

    n = len(c); balance = BAL; open_t = None
    trades = []; cap_count = 0

    for i in range(200, n):
        a = atr_s.iloc[i]
        if np.isnan(a) or a <= 0:
            continue
        if open_t is not None:
            d = open_t["dir"]; entry = open_t["entry"]
            sl = open_t["sl"]; tp = open_t["tp"]; qty = open_t["qty"]
            held = i - open_t["i"]; ep = None
            if d == 1:
                if lo[i] <= sl: ep = sl
                elif h[i] >= tp: ep = tp
            else:
                if h[i] >= sl: ep = sl
                elif lo[i] <= tp: ep = tp
            if ep is None and held >= MH: ep = c[i]
            if ep is not None:
                pnl = d * (ep - entry) * qty - (entry + ep) * qty * COST
                balance += pnl
                trades.append({"ts": df_1h.index[i], "pnl": pnl,
                               "grade": open_t["grade"], "capped": open_t["capped"]})
                open_t = None
            continue

        bpos = bb_pos[i]
        if np.isnan(bpos) or not (bpos < 0 or bpos > 1):
            continue
        direction = 1 if bpos < 0 else -1
        if np.isnan(vol_ma_v[i]) or vol[i] < vol_ma_v[i]:
            continue

        overshoot  = (-bpos) if direction == 1 else (bpos - 1)
        atr_pct    = atr_pct_v[i]
        tb_ratio   = tbv[i] / vol[i] if vol[i] > 0 else 0.5
        capitulation = (1 - tb_ratio) if direction == 1 else tb_ratio
        vw = vwap_v[i]
        vwap_dev   = (c[i] - vw) / vw if (not np.isnan(vw) and vw > 0) else np.nan
        vwap_edge  = (-vwap_dev) if direction == 1 else vwap_dev

        score = 0
        if not np.isnan(atr_pct)    and atr_pct    >= thresholds["atr_pct"]:    score += 1
        if not np.isnan(overshoot)  and overshoot  <= thresholds["overshoot"]:  score += 1
        if not np.isnan(capitulation) and capitulation >= thresholds["capitulation"]: score += 1
        if not np.isnan(vwap_edge)  and vwap_edge  >= thresholds["vwap_edge"]:  score += 1
        grade = "A+" if score == 4 else "A" if score == 3 else "B" if score == 2 else "C"

        if skip_c and grade == "C":
            continue

        if grade == "A+":
            risk = risk_aplus
        elif grade == "A":
            risk = risk_a
        else:
            risk = RISK_BASE

        ep = c[i]; sl_d = SL_M * a
        sl = ep - direction * sl_d; tp = ep + direction * TP_M * a
        qty_risk = (balance * risk) / (ep * (sl_d / ep))
        qty_cap  = balance * 0.5 / ep
        capped   = qty_risk > qty_cap
        qty = round(min(qty_risk, qty_cap), 3)
        if qty < 0.001:
            continue
        if capped:
            cap_count += 1
        open_t = {"i": i, "dir": direction, "entry": ep, "sl": sl, "tp": tp,
                  "qty": qty, "grade": grade, "capped": capped}

    return trades, balance, cap_count


def summary(trades, label, start_bal=BAL):
    tr_t = [t for t in trades if t["ts"] < SPLIT]
    te_t = [t for t in trades if t["ts"] >= SPLIT]
    p    = np.array([t["pnl"] for t in trades])
    ptr  = np.array([t["pnl"] for t in tr_t])
    pte  = np.array([t["pnl"] for t in te_t])
    def ss(pp, lbl):
        if len(pp) == 0: return f"{lbl}: —"
        return (f"{lbl}: {len(pp)}t WR{(pp>0).mean():.0%} "
                f"${pp.sum():>+7.0f} ({pp.sum()/start_bal*100:>+5.1f}%)")
    print(f"\n  {label}")
    print(f"    {ss(p,'TOPLAM')} | {ss(ptr,'TR')} | {ss(pte,'TE')}")
    capped = sum(1 for t in trades if t.get("capped"))
    if capped:
        print(f"    (50% cap {capped}x defalarca devreye girdi)")


def main():
    df_1h = load_1h()
    print(f"BTC 1h: {len(df_1h)} bar ({df_1h.index[0]:%Y-%m-%d}→{df_1h.index[-1]:%Y-%m-%d})")
    print("=" * 100)

    tr_df = df_1h[df_1h.index < SPLIT]

    # Eşikleri SADECE train'den hesapla
    *_, atr_s_full, vol_ma_full, atr_pct_full, vwap_full = (
        None, None, *compute_indicators(tr_df)[2:])

    # Hızlı eşik hesabı — train trade'lerini bir geçişte topla
    upper_tr, lower_tr, atr_s_tr, vol_ma_tr, atr_pct_tr, vwap_tr = compute_indicators(tr_df)
    bb_pos_tr = ((tr_df["close"] - lower_tr) / (upper_tr - lower_tr).replace(0, np.nan))
    vol_tr    = tr_df["volume"].values
    vol_ma_tr_v = vol_ma_tr.values
    tbv_tr    = tr_df["taker_buy_volume"].values
    atr_tr_v  = atr_s_tr.values
    atr_pct_tr_v = atr_pct_tr.values
    vwap_tr_v = vwap_tr.values
    c_tr = tr_df["close"].values

    overshoots = []; atr_pcts = []; caps = []; vedges = []
    for i in range(200, len(tr_df)):
        bpos = bb_pos_tr.iloc[i]
        if np.isnan(bpos) or not (bpos < 0 or bpos > 1): continue
        d = 1 if bpos < 0 else -1
        if np.isnan(vol_ma_tr_v[i]) or vol_tr[i] < vol_ma_tr_v[i]: continue
        overshoot = (-bpos) if d == 1 else (bpos - 1)
        atr_pct = atr_pct_tr_v[i]
        tbr = tbv_tr[i] / vol_tr[i] if vol_tr[i] > 0 else 0.5
        cap = (1 - tbr) if d == 1 else tbr
        vw = vwap_tr_v[i]
        ve = (-(c_tr[i]-vw)/vw) if d==1 else ((c_tr[i]-vw)/vw) if (not np.isnan(vw) and vw>0) else np.nan
        overshoots.append(overshoot); atr_pcts.append(atr_pct)
        caps.append(cap)
        if not np.isnan(ve): vedges.append(ve)

    thresholds = {
        "atr_pct": np.median(atr_pcts),
        "overshoot": np.median(overshoots),
        "capitulation": np.median(caps),
        "vwap_edge": np.median(vedges),
    }
    print(f"\nConfluence eşikleri (SADECE train medyanı): {thresholds}")
    print("=" * 100)
    print("\n[BASELİNE] — tüm trade'ler, sabit %3 risk (mevcut strateji)")
    bl, bl_bal, bl_cap = run(df_1h, thresholds, RISK_BASE, RISK_BASE, skip_c=False)
    summary(bl, "Baseline (hepsi, %3)", BAL)

    print("\n[SNIPER — sadece C atla, A+ büyük risk]")
    for aplus_risk in [0.06, 0.08, 0.10]:
        trades, _, cap_c = run(df_1h, thresholds, aplus_risk, RISK_A, skip_c=True)
        label = f"C hariç | A+={aplus_risk:.0%} A={RISK_A:.0%}"
        summary(trades, label, BAL)

    print("\n[SNIPER — sadece A+ ve A, C+B atla]")
    for aplus_risk in [0.06, 0.08, 0.10]:
        # Only A+ and A: implement by setting skip threshold at score >= 3
        def run_ab(df_1h, thr, rp, ra):
            c   = df_1h["close"].values
            h   = df_1h["high"].values
            lo  = df_1h["low"].values
            vol = df_1h["volume"].values
            tbv = df_1h["taker_buy_volume"].values
            upper, lower, atr_s, vol_ma, atr_pct_s, vwap = compute_indicators(df_1h)
            bb_pos = ((df_1h["close"] - lower) / (upper - lower).replace(0, np.nan)).values
            vol_ma_v = vol_ma.values; atr_pct_v = atr_pct_s.values; vwap_v = vwap.values
            n = len(c); balance = BAL; open_t = None; trades = []
            for i in range(200, n):
                a = atr_s.iloc[i]
                if np.isnan(a) or a <= 0: continue
                if open_t is not None:
                    d = open_t["dir"]; entry = open_t["entry"]
                    sl = open_t["sl"]; tp = open_t["tp"]; qty = open_t["qty"]
                    held = i - open_t["i"]; ep = None
                    if d == 1:
                        if lo[i] <= sl: ep = sl
                        elif h[i] >= tp: ep = tp
                    else:
                        if h[i] >= sl: ep = sl
                        elif lo[i] <= tp: ep = tp
                    if ep is None and held >= MH: ep = c[i]
                    if ep is not None:
                        pnl = d * (ep - entry) * qty - (entry + ep) * qty * COST
                        balance += pnl
                        trades.append({"ts": df_1h.index[i], "pnl": pnl,
                                      "grade": open_t["grade"], "capped": open_t["capped"]})
                        open_t = None
                    continue
                bpos = bb_pos[i]
                if np.isnan(bpos) or not (bpos < 0 or bpos > 1): continue
                direction = 1 if bpos < 0 else -1
                if np.isnan(vol_ma_v[i]) or vol[i] < vol_ma_v[i]: continue
                overshoot  = (-bpos) if direction == 1 else (bpos - 1)
                atr_pct    = atr_pct_v[i]
                tb_ratio   = tbv[i] / vol[i] if vol[i] > 0 else 0.5
                capitulation = (1 - tb_ratio) if direction == 1 else tb_ratio
                vw = vwap_v[i]
                vwap_dev   = (c[i] - vw) / vw if (not np.isnan(vw) and vw > 0) else np.nan
                vwap_edge  = (-vwap_dev) if direction == 1 else vwap_dev
                score = 0
                if not np.isnan(atr_pct)    and atr_pct    >= thr["atr_pct"]:    score += 1
                if not np.isnan(overshoot)  and overshoot  <= thr["overshoot"]:  score += 1
                if not np.isnan(capitulation) and capitulation >= thr["capitulation"]: score += 1
                if not np.isnan(vwap_edge)  and vwap_edge  >= thr["vwap_edge"]:  score += 1
                if score < 3: continue  # sadece A+ ve A
                grade = "A+" if score == 4 else "A"
                risk = rp if grade == "A+" else ra
                ep = c[i]; sl_d = SL_M * a
                sl = ep - direction * sl_d; tp = ep + direction * TP_M * a
                qty_risk = (balance * risk) / (ep * (sl_d / ep))
                qty_cap  = balance * 0.5 / ep
                capped = qty_risk > qty_cap
                qty = round(min(qty_risk, qty_cap), 3)
                if qty < 0.001: continue
                open_t = {"i": i, "dir": direction, "entry": ep, "sl": sl, "tp": tp,
                         "qty": qty, "grade": grade, "capped": capped}
            return trades
        trades = run_ab(df_1h, thresholds, aplus_risk, RISK_A)
        label = f"Sadece A++A | A+={aplus_risk:.0%} A={RISK_A:.0%}"
        summary(trades, label, BAL)

    print("\n" + "=" * 100)
    print("\nKARAR:")
    print("  • A+ risk artışı TESTte baseline'ı belirgin geçiyorsa → sniper GERÇEK.")
    print("  • Geçmiyorsa → 50% cap meselesi: risk artışı miktarı fark etmiyor,")
    print("    cap zaten devreye giriyor. Bu durumda kaliteli seçim değil, sermaye artırma.")


if __name__ == "__main__":
    main()
