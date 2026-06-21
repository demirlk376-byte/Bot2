"""
research_15m_vs_1h.py — 1h vs 15m timeframe karşılaştırması

Aynı strateji mantığı, aynı risk parametreleri, sadece timeframe farklı.
Tüm veri: 2023-01 → 2026-04 (3.5 yıl, 1m CSV'den resample).

Stratejiler: BB mean-reversion, ORB, Asia BO
($100 başlangıç, aylık $150 ekleme — kullanıcının gerçek planı)
"""
from __future__ import annotations
import glob, sys
import numpy as np
import pandas as pd
sys.path.insert(0, "/home/user/Bot2")
from indicators import bollinger_bands, atr, adx as _adx_ind

# ── Sabit parametreler ───────────────────────────────────────────────────────
COST_MAKER   = 0.0
COST_TAKER   = 0.0001
LEVERAGE     = 10
MIN_LOT      = 0.001
START        = 100.0
MONTHLY_ADD  = 150.0

BB_RISK  = 0.02; BB_SL = 3.0; BB_TP = 5.0
ORB_RISK = 0.05; ORB_RR = 2.0; ORB_HOUR = 14
ASIA_RISK= 0.03; ASIA_RR= 2.0; ASIA_SL = 1.0
ADX_TRENDING   = 28.0
DAILY_MAX_LOSS = 0.35
CONSEC_LIMIT   = 2
COOLDOWN_HOURS = 4

# Gerçekçi P&L için: pozisyon boyutu büyüdükçe büyüyen balanceı sınırla.
# Bu olmadan %5 risk × yüzlerce ticaret = astronomik compounding.
# $5000 cap: ~gerçek kullanıcı ortamını yansıtır (3.5 yıl deposits = $6500).
MAX_SIZING_BALANCE = 5000.0

# Timeframe'e göre max-hold (saat cinsinden sabit, mum sayısı değişiyor)
HOLD_HOURS_BB   = 48
HOLD_HOURS_DAY  = 6   # ORB ve Asia


def load_all_1m() -> pd.DataFrame:
    frames = []
    for f in sorted(glob.glob("/home/user/Bot2/BTCUSDT-1m-*.csv")):
        df = pd.read_csv(f, header=None, skiprows=1)
        df.columns = ["ts","open","high","low","close","volume",
                      "ct","qv","count","tbv","tbqv","ign"]
        frames.append(df[["ts","open","high","low","close","volume"]].astype(float))
    if not frames:
        raise SystemExit("Veri yok — BTCUSDT-1m-*.csv bulunamadı")
    full = pd.concat(frames, ignore_index=True).drop_duplicates("ts").sort_values("ts")
    full.index = pd.to_datetime(full["ts"], unit="ms", utc=True)
    return full.drop(columns=["ts"])


def resample(df1m: pd.DataFrame, tf: str) -> pd.DataFrame:
    return df1m.resample(tf).agg(
        {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    ).dropna()


def size_qty(risk_pct, balance, free_margin, ep, sl_dist):
    if sl_dist <= 0 or free_margin <= 0 or ep <= 0:
        return 0.0, 0.0
    eff_bal = min(balance, MAX_SIZING_BALANCE)
    qty = (eff_bal * risk_pct) / sl_dist
    qty = min(qty, free_margin * LEVERAGE / ep)
    qty = round(qty, 3)
    if qty < MIN_LOT:
        return 0.0, 0.0
    mg = qty * ep / LEVERAGE
    if mg > free_margin + 1e-9:
        return 0.0, 0.0
    return qty, mg


def run_sim(df: pd.DataFrame, tf_label: str) -> dict:
    """Tek timeframe üzerinde simülasyon — BB + ORB + Asia."""
    if len(df) < 100:
        return {}

    # candles_per_hour: hold sürelerini mum sayısına çevirmek için
    if tf_label == "1h":
        cph = 1
    elif tf_label == "15m":
        cph = 4
    else:
        cph = 1

    BB_MH   = HOLD_HOURS_BB  * cph
    DAY_MH  = HOLD_HOURS_DAY * cph

    close  = df["close"].values
    high_v = df["high"].values
    low_v  = df["low"].values
    vol    = df["volume"].values
    idx    = df.index

    upper_s, _, lower_s = bollinger_bands(df["close"], 20, 2.0)
    atr_s   = atr(df["high"], df["low"], df["close"], 14)
    adx_s   = _adx_ind(df["high"], df["low"], df["close"], 14)
    vol_ma  = df["volume"].rolling(20).mean()
    bb_pos  = (df["close"] - lower_s) / (upper_s - lower_s).replace(0, np.nan)

    atr_a   = atr_s.values
    adx_a   = adx_s.values
    volma_a = vol_ma.values
    bb_a    = bb_pos.values

    n      = len(close)
    warmup = 60 * cph   # en az 60h warmup
    dates_a = np.array([ts.date() for ts in idx])
    hours_a = np.array([ts.hour  for ts in idx])
    month_a = np.array([ts.to_period("M") for ts in idx])

    # ORB ve Asia range'lerini önceden hesapla (her gün için 1 değer)
    orb_by_date  = {}
    asia_by_date = {}
    for j in range(n):
        d = dates_a[j]; h = hours_a[j]
        if tf_label == "1h":
            if h == ORB_HOUR:
                orb_by_date[d] = {"high": high_v[j], "low": low_v[j]}
        else:  # 15m: 14:00-14:59 UTC aralığı (h==14 olan tüm mumlar)
            if h == ORB_HOUR:
                if d not in orb_by_date:
                    orb_by_date[d] = {"high": high_v[j], "low": low_v[j]}
                else:
                    orb_by_date[d]["high"] = max(orb_by_date[d]["high"], high_v[j])
                    orb_by_date[d]["low"]  = min(orb_by_date[d]["low"],  low_v[j])
        if h < 8:
            if d not in asia_by_date:
                asia_by_date[d] = {"high": high_v[j], "low": low_v[j], "cnt": 1}
            else:
                asia_by_date[d]["high"] = max(asia_by_date[d]["high"], high_v[j])
                asia_by_date[d]["low"]  = min(asia_by_date[d]["low"],  low_v[j])
                asia_by_date[d]["cnt"] += 1

    balance     = START
    used_margin = 0.0
    daily_start = START
    daily_date  = None
    peak_equity = START

    bb_o = orb_o = asia_o = None
    orb_traded  = set()
    asia_traded = set()
    consec      = {"bb": 0, "orb": 0, "asia": 0}
    cooldown    = {"bb": None, "orb": None, "asia": None}

    trades      = []
    equity_curve= []
    monthly_pnl = {}
    max_dd      = 0.0

    def free():
        return balance - used_margin

    for i in range(warmup, n):
        a_val = atr_a[i]
        if np.isnan(a_val) or a_val <= 0:
            continue

        cd = dates_a[i]; ch = hours_a[i]; cm = month_a[i]
        now_ts = idx[i]

        if cd != daily_date:
            daily_date  = cd
            daily_start = balance + used_margin

            if MONTHLY_ADD > 0 and cd.day == 1 and ch == 0:
                balance += MONTHLY_ADD

        # ── Equity & drawdown takibi ──────────────────────────────────
        eq = balance + used_margin
        equity_curve.append(eq)
        peak_equity = max(peak_equity, eq)
        dd = (peak_equity - eq) / peak_equity if peak_equity > 0 else 0.0
        max_dd = max(max_dd, dd)

        # ── Pozisyon kapanış kontrolleri ──────────────────────────────
        for slot, pos in [("bb", bb_o), ("orb", orb_o), ("asia", asia_o)]:
            if pos is None:
                continue
            d = pos["dir"]; entry = pos["entry"]
            sl = pos["sl"]; tp = pos["tp"]
            qty = pos["qty"]; held = i - pos["i"]

            ep_exit = None; reason = None
            if d == 1:
                if low_v[i] <= sl:    ep_exit, reason = sl,       "sl"
                elif high_v[i] >= tp: ep_exit, reason = tp,       "tp"
            else:
                if high_v[i] >= sl:   ep_exit, reason = sl,       "sl"
                elif low_v[i] <= tp:  ep_exit, reason = tp,       "tp"
            if ep_exit is None and held >= pos["mh"]:
                ep_exit, reason = close[i], "mh"

            if ep_exit is not None:
                raw  = d * (ep_exit - entry) * qty
                fee  = entry * qty * COST_MAKER + ep_exit * qty * COST_TAKER
                pnl  = raw - fee
                balance     += pnl
                used_margin -= pos["margin"]
                trades.append({"pnl": pnl, "strat": slot, "month": cm, "reason": reason})
                monthly_pnl.setdefault(cm, 0.0)
                monthly_pnl[cm] += pnl

                if pnl < 0:
                    consec[slot] += 1
                    if consec[slot] >= CONSEC_LIMIT:
                        cooldown[slot] = now_ts + pd.Timedelta(hours=COOLDOWN_HOURS)
                else:
                    consec[slot] = 0

                if slot == "bb":    bb_o   = None
                elif slot == "orb": orb_o  = None
                else:               asia_o = None

        # Günlük kayıp limiti
        equity = balance + used_margin
        if daily_start > 0 and (daily_start - equity) / daily_start >= DAILY_MAX_LOSS:
            continue

        adx_val  = adx_a[i]
        trending = not np.isnan(adx_val) and adx_val >= ADX_TRENDING

        # ── BB mean-reversion ─────────────────────────────────────────
        if bb_o is None and not trending:
            cd_ok = cooldown["bb"] is None or now_ts >= cooldown["bb"]
            if cd_ok:
                if cooldown["bb"] is not None and now_ts >= cooldown["bb"]:
                    cooldown["bb"] = None
                bpos = bb_a[i]; vm = volma_a[i]
                if not np.isnan(bpos) and (bpos < 0.0 or bpos > 1.0):
                    if np.isnan(vm) or vol[i] >= vm:
                        direction = 1 if bpos < 0.0 else -1
                        ep = close[i]
                        sl_dist = BB_SL * a_val
                        qty, mg = size_qty(BB_RISK, balance, free(), ep, sl_dist)
                        if qty > 0:
                            used_margin += mg
                            bb_o = {
                                "i": i, "dir": direction, "entry": ep,
                                "sl": ep - direction * sl_dist,
                                "tp": ep + direction * BB_TP * a_val,
                                "qty": qty, "margin": mg, "mh": BB_MH,
                            }

        # ── ORB ──────────────────────────────────────────────────────
        if orb_o is None and cd not in orb_traded and ch > ORB_HOUR:
            cd_ok = cooldown["orb"] is None or now_ts >= cooldown["orb"]
            if cd_ok:
                if cooldown["orb"] is not None and now_ts >= cooldown["orb"]:
                    cooldown["orb"] = None
                orb = orb_by_date.get(cd)
                if orb:
                    oh = orb["high"]; ol = orb["low"]; rng = oh - ol
                    if rng > 0:
                        cp = close[i]
                        if cp > oh:
                            ep = oh; sl = ol; tp = oh + ORB_RR * rng
                            qty, mg = size_qty(ORB_RISK, balance, free(), ep, rng)
                            if qty > 0:
                                used_margin += mg; orb_traded.add(cd)
                                orb_o = {"i":i,"dir":1,"entry":ep,"sl":sl,"tp":tp,
                                         "qty":qty,"margin":mg,"mh":DAY_MH}
                        elif cp < ol:
                            ep = ol; sl = oh; tp = ol - ORB_RR * rng
                            qty, mg = size_qty(ORB_RISK, balance, free(), ep, rng)
                            if qty > 0:
                                used_margin += mg; orb_traded.add(cd)
                                orb_o = {"i":i,"dir":-1,"entry":ep,"sl":sl,"tp":tp,
                                         "qty":qty,"margin":mg,"mh":DAY_MH}

        # ── Asia BO ──────────────────────────────────────────────────
        if asia_o is None and cd not in asia_traded and ch >= 8:
            cd_ok = cooldown["asia"] is None or now_ts >= cooldown["asia"]
            if cd_ok:
                if cooldown["asia"] is not None and now_ts >= cooldown["asia"]:
                    cooldown["asia"] = None
                asia = asia_by_date.get(cd)
                if asia and asia["cnt"] >= (4 if tf_label == "1h" else 16):
                    ah = asia["high"]; al = asia["low"]
                    sl_dist = ASIA_SL * a_val
                    cp = close[i]
                    if cp > ah:
                        ep = ah; sl = ah - sl_dist; tp = ah + ASIA_RR * sl_dist
                        qty, mg = size_qty(ASIA_RISK, balance, free(), ep, sl_dist)
                        if qty > 0:
                            used_margin += mg; asia_traded.add(cd)
                            asia_o = {"i":i,"dir":1,"entry":ep,"sl":sl,"tp":tp,
                                      "qty":qty,"margin":mg,"mh":DAY_MH}
                    elif cp < al:
                        ep = al; sl = al + sl_dist; tp = al - ASIA_RR * sl_dist
                        qty, mg = size_qty(ASIA_RISK, balance, free(), ep, sl_dist)
                        if qty > 0:
                            used_margin += mg; asia_traded.add(cd)
                            asia_o = {"i":i,"dir":-1,"entry":ep,"sl":sl,"tp":tp,
                                      "qty":qty,"margin":mg,"mh":DAY_MH}

    # ── Sonuçları hesapla ─────────────────────────────────────────────────────
    if not trades:
        return {}

    t = pd.DataFrame(trades)
    wins  = (t["pnl"] > 0).sum()
    total = len(t)
    gross_profit = t.loc[t["pnl"] > 0, "pnl"].sum()
    gross_loss   = abs(t.loc[t["pnl"] < 0, "pnl"].sum())
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    net_pnl = t["pnl"].sum()
    final_eq = balance + used_margin

    # Strateji kırılımı
    strat_res = {}
    for s in ["bb", "orb", "asia"]:
        st = t[t["strat"] == s]
        if len(st) == 0:
            strat_res[s] = {"n": 0, "wr": 0, "pf": 0, "pnl": 0}
            continue
        sw = (st["pnl"] > 0).sum()
        sp = st.loc[st["pnl"] > 0, "pnl"].sum()
        sl = abs(st.loc[st["pnl"] < 0, "pnl"].sum())
        strat_res[s] = {
            "n": len(st), "wr": sw / len(st),
            "pf": sp / sl if sl > 0 else float("inf"),
            "pnl": st["pnl"].sum(),
        }

    # Aylık kazanç
    monthly_wins = sum(1 for v in monthly_pnl.values() if v > 0)
    monthly_tot  = len(monthly_pnl)

    return {
        "tf": tf_label, "trades": total, "wins": wins,
        "wr": wins / total, "pf": pf, "net_pnl": net_pnl,
        "max_dd": max_dd, "final_eq": final_eq,
        "strat": strat_res,
        "monthly_win_rate": monthly_wins / monthly_tot if monthly_tot else 0,
        "monthly_tot": monthly_tot,
    }


def print_result(r: dict):
    tf = r["tf"]
    print(f"\n{'═'*52}")
    print(f"  TF: {tf}   Trade: {r['trades']}   WR: {r['wr']:.0%}   PF: {r['pf']:.2f}")
    print(f"  Net PnL: ${r['net_pnl']:+.2f}   Final: ${r['final_eq']:.2f}   MaxDD: {r['max_dd']:.1%}")
    print(f"  Karlı ay: {r['monthly_win_rate']:.0%} ({r['monthly_tot']} ay)")
    print(f"  {'Strateji':<8}  {'Trade':>5}  {'WR':>5}  {'PF':>5}  {'PnL':>10}")
    print(f"  {'-'*42}")
    for s, sr in r["strat"].items():
        pf_s = f"{sr['pf']:.2f}" if sr['pf'] != float("inf") else "  ∞"
        print(f"  {s.upper():<8}  {sr['n']:>5}  {sr['wr']:>4.0%}  {pf_s:>5}  ${sr['pnl']:>+9.2f}")


if __name__ == "__main__":
    print("Veri yükleniyor (1m CSV)…")
    df1m = load_all_1m()
    print(f"  {len(df1m):,} mum yüklendi ({df1m.index[0].date()} → {df1m.index[-1].date()})")

    print("\n1h resample…")
    df1h = resample(df1m, "1h")
    print(f"  {len(df1h):,} mum")

    print("15m resample…")
    df15 = resample(df1m, "15min")
    print(f"  {len(df15):,} mum")

    print("\nSimülasyon çalışıyor…")
    r1h  = run_sim(df1h,  "1h")
    r15m = run_sim(df15, "15m")

    print("\n" + "█"*52)
    print("  1h vs 15m BACKTEST KARŞILAŞTIRMASI")
    print(f"  {df1m.index[0].date()} → {df1m.index[-1].date()}")
    print(f"  Başlangıç: ${START:.0f} + aylık ${MONTHLY_ADD:.0f} ekleme")
    print("█"*52)

    print_result(r1h)
    print_result(r15m)

    # Özet karşılaştırma tablosu
    print(f"\n{'─'*52}")
    print(f"  {'Metrik':<18} {'1h':>12} {'15m':>12}  {'Fark':>8}")
    print(f"  {'─'*50}")
    metrics = [
        ("Trade sayısı",  r1h['trades'],           r15m['trades'],          "{:.0f}"),
        ("Win Rate",      r1h['wr']*100,            r15m['wr']*100,          "{:.1f}%"),
        ("Profit Factor", r1h['pf'],                r15m['pf'],              "{:.2f}"),
        ("Net PnL $",     r1h['net_pnl'],           r15m['net_pnl'],         "${:+.2f}"),
        ("Final Equity",  r1h['final_eq'],          r15m['final_eq'],        "${:.2f}"),
        ("Max DrawDown",  r1h['max_dd']*100,        r15m['max_dd']*100,      "{:.1f}%"),
        ("Karlı ay %",    r1h['monthly_win_rate']*100, r15m['monthly_win_rate']*100, "{:.0f}%"),
    ]
    for name, v1, v2, fmt in metrics:
        s1 = fmt.format(v1)
        s2 = fmt.format(v2)
        diff_pct = ((v2 - v1) / abs(v1) * 100) if v1 != 0 else 0
        arrow = "▲" if v2 > v1 else "▼"
        if name in ("Max DrawDown",):  # düşük = iyi
            arrow = "▼" if v2 > v1 else "▲"
        print(f"  {name:<18} {s1:>12} {s2:>12}  {arrow}{abs(diff_pct):>5.0f}%")
    print(f"{'─'*52}")
    print("\nNot: 15m BB max-hold 192 mum (=48h), ORB/Asia 24 mum (=6h)")
