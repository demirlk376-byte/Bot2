"""
research_3year_realistic.py — Mevcut FINAL config ile 3 yıl gerçekçi backtest

FINAL CONFIG (şu an canlıda çalışan):
  • BB Mean-Rev: ADX<28 + SADECE HAFTA SONU (Cmt-Paz), %8 risk, 3×ATR SL, 5×ATR TP
  • ORB NY Open: limit entry orb_high/low, sabit 2:1 TP, %5 risk, 6h max-hold
  • Asia BO:     limit entry, sabit 2:1 TP, ATR-bazlı SL, %3 risk, 6h max-hold
  • Tümü: günlük %35 kayıp limiti, 2 ardışık kayıp → 4h cooldown

Başlangıç: $53 (≈2000 TL @ 38 TL/$)
Aylık ekleme: $132 (≈5000 TL @ 38 TL/$)

Kapsam: Ocak 2023 → Nisan 2026 (3 yıl 4 ay)

Gerçekçilik kısıtı: position sizing $10K'da dondurulur (market depth limiti).
$10K üzerinde balance büyür ama trade büyüklüğü artmaz.
"""
from __future__ import annotations
import glob, sys
import numpy as np
import pandas as pd
sys.path.insert(0, "/home/user/Bot2")
from indicators import bollinger_bands, atr, adx as _adx_ind

COST_TAKER   = 0.0001
LEVERAGE     = 10
MIN_LOT      = 0.001

START        = 53.0
MONTHLY_ADD  = 132.0
TL_RATE      = 38.0

BB_RISK  = 0.08; BB_SL = 3.0; BB_TP = 5.0; BB_MH = 48
ORB_RISK = 0.05; ORB_RR = 2.0; ORB_MH = 6;  ORB_HOUR = 14
ASIA_RISK= 0.03; ASIA_RR= 2.0; ASIA_SL= 1.0; ASIA_MH = 6

ADX_TRENDING   = 28.0
DAILY_MAX_LOSS = 0.35
CONSEC_LIMIT   = 2
COOLDOWN_HOURS = 4

# Gerçekçi sınır: bakiye $10K'ı geçince position size büyümez.
MAX_SIZING_BALANCE = 10_000.0


def load_months(year_months: list[str]) -> pd.DataFrame:
    frames = []
    for ym in year_months:
        for f in sorted(glob.glob(f"/home/user/Bot2/BTCUSDT-1m-{ym}.csv")):
            df = pd.read_csv(f)
            df.columns = ["ts","open","high","low","close","volume",
                          "ct","qv","count","tbv","tbqv","ign"]
            frames.append(df[["ts","open","high","low","close","volume"]].astype(float))
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True).drop_duplicates("ts").sort_values("ts")
    out.index = pd.to_datetime(out["ts"], unit="ms", utc=True)
    return out.drop(columns=["ts"])


def resample_1h(df: pd.DataFrame) -> pd.DataFrame:
    return df.resample("1h").agg(
        {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    ).dropna()


def size_qty(risk_pct, balance, free_margin, ep, sl_dist):
    if sl_dist <= 0 or free_margin <= 0 or ep <= 0:
        return 0.0, 0.0
    sizing_bal = min(balance, MAX_SIZING_BALANCE)
    risk_amt = sizing_bal * risk_pct
    qty      = risk_amt / sl_dist
    qty      = min(qty, free_margin * LEVERAGE / ep)
    qty      = round(qty, 3)
    if qty < MIN_LOT:
        return 0.0, 0.0
    margin = qty * ep / LEVERAGE
    if margin > free_margin + 1e-9:
        return 0.0, 0.0
    return qty, margin


def run_sim(df_1m: pd.DataFrame):
    df = resample_1h(df_1m)
    if len(df) < 100:
        return [], {}

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

    n         = len(close); warmup = 60
    dates_a   = np.array([ts.date()         for ts in idx])
    hours_a   = np.array([ts.hour           for ts in idx])
    month_a   = np.array([ts.to_period("M") for ts in idx])
    weekday_a = np.array([ts.weekday()      for ts in idx])

    orb_by_date  = {}
    asia_by_date = {}
    for j in range(n):
        d = dates_a[j]; h = hours_a[j]
        if h == ORB_HOUR:
            orb_by_date[d] = {"high": high_v[j], "low": low_v[j]}
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
    last_month  = None

    bb_o = orb_o = asia_o = None
    orb_traded  = set()
    asia_traded = set()
    consec   = {"bb": 0, "orb": 0, "asia": 0}
    cooldown = {"bb": None, "orb": None, "asia": None}

    trades      = []
    monthly_pnl = {}

    def free(): return balance - used_margin

    for i in range(warmup, n):
        a_val = atr_a[i]
        if np.isnan(a_val) or a_val <= 0:
            continue

        cd  = dates_a[i]; ch = hours_a[i]
        cm  = month_a[i]; wd = weekday_a[i]
        now_ts = idx[i]

        if cd != daily_date:
            daily_date  = cd
            daily_start = balance + used_margin

        if cm != last_month and last_month is not None:
            balance += MONTHLY_ADD
        last_month = cm

        for slot, pos in [("bb", bb_o), ("orb", orb_o), ("asia", asia_o)]:
            if pos is None:
                continue
            d = pos["dir"]; ep_entry = pos["entry"]
            sl = pos["sl"]; tp = pos["tp"]
            qty = pos["qty"]; held = i - pos["i"]

            ep_exit = None; reason = None
            if d == 1:
                if low_v[i]  <= sl: ep_exit, reason = sl, "sl"
                elif high_v[i] >= tp: ep_exit, reason = tp, "tp"
            else:
                if high_v[i] >= sl: ep_exit, reason = sl, "sl"
                elif low_v[i]  <= tp: ep_exit, reason = tp, "tp"
            if ep_exit is None and held >= pos["mh"]:
                ep_exit, reason = close[i], "mh"

            if ep_exit is not None:
                pnl = d * (ep_exit - ep_entry) * qty - ep_exit * qty * COST_TAKER
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

        equity = balance + used_margin
        if daily_start > 0 and (daily_start - equity) / daily_start >= DAILY_MAX_LOSS:
            continue

        adx_val    = adx_a[i]
        trending   = not np.isnan(adx_val) and adx_val >= ADX_TRENDING
        is_weekend = (wd >= 5)

        # BB — sadece hafta sonu + ranging
        if bb_o is None and is_weekend and not trending:
            cd_ok = cooldown["bb"] is None or now_ts >= cooldown["bb"]
            if cd_ok:
                if cooldown["bb"] is not None: cooldown["bb"] = None
                bpos = bb_a[i]; vm = volma_a[i]
                if not np.isnan(bpos) and (bpos < 0.0 or bpos > 1.0):
                    if np.isnan(vm) or vol[i] >= vm:
                        direction = 1 if bpos < 0.0 else -1
                        ep = close[i]; sl_dist = BB_SL * a_val
                        qty, mg = size_qty(BB_RISK, balance, free(), ep, sl_dist)
                        if qty > 0:
                            used_margin += mg
                            bb_o = {"i":i,"dir":direction,"entry":ep,
                                    "sl":ep-direction*sl_dist,"tp":ep+direction*BB_TP*a_val,
                                    "qty":qty,"margin":mg,"mh":BB_MH}

        # ORB
        if orb_o is None and cd not in orb_traded and ch > ORB_HOUR:
            cd_ok = cooldown["orb"] is None or now_ts >= cooldown["orb"]
            if cd_ok:
                if cooldown["orb"] is not None: cooldown["orb"] = None
                orb = orb_by_date.get(cd)
                if orb:
                    oh = orb["high"]; ol = orb["low"]; rng = oh - ol
                    if rng > 0:
                        cp = close[i]
                        if cp > oh:
                            ep=oh; sl=ol; tp=oh+ORB_RR*rng
                            qty,mg = size_qty(ORB_RISK,balance,free(),ep,rng)
                            if qty>0:
                                used_margin+=mg; orb_traded.add(cd)
                                orb_o={"i":i,"dir":1,"entry":ep,"sl":sl,"tp":tp,"qty":qty,"margin":mg,"mh":ORB_MH}
                        elif cp < ol:
                            ep=ol; sl=oh; tp=ol-ORB_RR*rng
                            qty,mg = size_qty(ORB_RISK,balance,free(),ep,rng)
                            if qty>0:
                                used_margin+=mg; orb_traded.add(cd)
                                orb_o={"i":i,"dir":-1,"entry":ep,"sl":sl,"tp":tp,"qty":qty,"margin":mg,"mh":ORB_MH}

        # Asia BO
        if asia_o is None and cd not in asia_traded and ch >= 8:
            cd_ok = cooldown["asia"] is None or now_ts >= cooldown["asia"]
            if cd_ok:
                if cooldown["asia"] is not None: cooldown["asia"] = None
                asia = asia_by_date.get(cd)
                if asia and asia["cnt"] >= 4:
                    ah=asia["high"]; al=asia["low"]; sl_dist=ASIA_SL*a_val
                    cp=close[i]
                    if cp > ah:
                        ep=ah; sl=ah-sl_dist; tp=ah+ASIA_RR*sl_dist
                        qty,mg=size_qty(ASIA_RISK,balance,free(),ep,sl_dist)
                        if qty>0:
                            used_margin+=mg; asia_traded.add(cd)
                            asia_o={"i":i,"dir":1,"entry":ep,"sl":sl,"tp":tp,"qty":qty,"margin":mg,"mh":ASIA_MH}
                    elif cp < al:
                        ep=al; sl=al+sl_dist; tp=al-ASIA_RR*sl_dist
                        qty,mg=size_qty(ASIA_RISK,balance,free(),ep,sl_dist)
                        if qty>0:
                            used_margin+=mg; asia_traded.add(cd)
                            asia_o={"i":i,"dir":-1,"entry":ep,"sl":sl,"tp":tp,"qty":qty,"margin":mg,"mh":ASIA_MH}

    return trades, monthly_pnl


def main():
    print("Veri yükleniyor…", flush=True)
    all_months = (
        [f"2023-{m:02d}" for m in range(1, 13)] +
        [f"2024-{m:02d}" for m in range(1, 13)] +
        [f"2025-{m:02d}" for m in range(5, 13)] +
        [f"2026-{m:02d}" for m in range(1, 5)]
    )
    df = load_months(all_months)
    print(f"  Toplam: {len(df):,} dakikalık mum")
    print("Simülasyon çalışıyor…", flush=True)
    trades, monthly_pnl = run_sim(df)

    if not trades:
        print("Trade yok!"); return

    months = sorted(monthly_pnl.keys())
    balance = START
    peak    = START
    max_dd  = 0.0

    print(f"\n{'='*78}")
    print(f"  FINAL CONFIG — BB Hafta Sonu + ORB 2:1 + Asia 2:1 — 3 Yıl 4 Ay")
    print(f"  Başlangıç: ${START:.0f} (≈{START*TL_RATE:.0f} TL)   "
          f"Aylık ekleme: ${MONTHLY_ADD:.0f} (≈{MONTHLY_ADD*TL_RATE:.0f} TL)")
    print(f"  Position sizing $10K'da dondurulur (market depth kısıtı)")
    print(f"{'='*78}")
    print(f"\n  {'Ay':<10}  {'T':>4}  {'PnL $':>8}  {'%':>7}  "
          f"{'Bakiye $':>10}  {'Bakiye TL':>12}")
    print(f"  {'-'*65}")

    for idx_m, m in enumerate(months):
        if idx_m > 0:
            balance += MONTHLY_ADD
        bal_before = balance
        pnl_m = monthly_pnl[m]
        balance += pnl_m
        pct = pnl_m / bal_before * 100 if bal_before > 0 else 0.0
        if balance > peak: peak = balance
        dd = min((peak - balance) / peak, 1.0) if peak > 0 else 0.0
        if dd > max_dd: max_dd = dd
        mt = [t for t in trades if t["month"] == m]
        em = "🟢" if pnl_m >= 0 else "🔴"
        print(f"  {str(m):<10}  {len(mt):>4}  {pnl_m:>+8.0f}  {pct:>+6.1f}%  "
              f"{balance:>10,.0f}  {balance*TL_RATE:>12,.0f}  {em}")

    pnls = [t["pnl"] for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p < 0))
    pf = gp / gl if gl > 0 else 999
    n_m = len(months)
    total_inv = START + MONTHLY_ADD * (n_m - 1)

    print(f"\n{'='*78}")
    print(f"  ÖZET — {n_m} ay")
    print(f"{'='*78}")
    print(f"  Trade: {len(trades):,}   WR: {wins/len(trades):.0%}   PF: {pf:.2f}   MaxDD: {max_dd:.1%}")
    print(f"  Toplam yatırım : ${total_inv:,.0f}  (≈{total_inv*TL_RATE:,.0f} TL)")
    print(f"  Son bakiye     : ${balance:,.0f}  (≈{balance*TL_RATE:,.0f} TL)")
    print(f"  Net kâr        : ${balance-total_inv:+,.0f}  (≈{(balance-total_inv)*TL_RATE:+,.0f} TL)")

    print(f"\n  {'Strateji':<8}  {'T':>5}  {'WR':>5}  {'PF':>5}  {'Net $':>9}  {'Net TL':>11}")
    print(f"  {'-'*52}")
    for sl in ("bb","orb","asia"):
        t_sl = [t for t in trades if t["strat"]==sl]
        if not t_sl: continue
        p_sl=[t["pnl"] for t in t_sl]; w=sum(1 for p in p_sl if p>0)
        gp_=sum(p for p in p_sl if p>0); gl_=abs(sum(p for p in p_sl if p<0))
        print(f"  {sl.upper():<8}  {len(t_sl):>5}  {w/len(t_sl):>4.0%}  "
              f"{gp_/gl_ if gl_>0 else 999:>5.2f}  {sum(p_sl):>+9.0f}  {sum(p_sl)*TL_RATE:>+11.0f}")

if __name__ == "__main__":
    main()
