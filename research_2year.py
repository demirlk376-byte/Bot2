"""
research_2year.py — 2024 vs 2025-2026 karşılaştırmalı gerçekçi backtest

"Gerçekmiş gibi" simülasyon kuralları:
  - Margin kısıtı: her pozisyon açılışında yeterli serbest bakiye kontrol edilir
  - Lot yuvarlama: min 0.001 BTC, 3 ondalık
  - ORB/Asia BO: limit entry (kırılım seviyesinde dolar, mum kapanışında değil)
  - Ücret: maker %0 entry / taker %0.01 exit (mevcut sistemle aynı)
  - Günlük kayıp limiti: %35
  - BB trending rejim filtresi: ADX>28'de BB kapalı (BUG-3 düzeltmesi)
  - Ardışık kayıp: strateji başına 2 üst üste → 4 saat cooldown

Test senaryoları:
  1) 2024 TEK BAŞINA (out-of-sample: strateji 2025+ verisiyle optimize edildi)
  2) 2025-2026 TEK BAŞINA (in-sample referans)
  3) 2 YIL KOMBİNE (Ocak 2024 – Nisan 2026)
  Her senaryo için: $200 başlangıç + aylık $100 ekleme (agresif profil)
"""
from __future__ import annotations
import glob, sys
import numpy as np
import pandas as pd
sys.path.insert(0, "/home/user/Bot2")
from indicators import bollinger_bands, atr, adx as _adx_ind

COST_MAKER = 0.0      # entry: post-only limit, MEXC maker = %0
COST_TAKER = 0.0001   # exit:  taker = %0.01
LEVERAGE    = 10
MIN_LOT     = 0.001
START       = 200.0
MONTHLY_ADD = 100.0

# Agresif profil (seçilen)
BB_RISK  = 0.08; BB_SL = 3.0; BB_TP = 5.0; BB_MH = 48
ORB_RISK = 0.05; ORB_RR = 2.0; ORB_MH = 6; ORB_HOUR = 14
ASIA_RISK= 0.03; ASIA_RR= 2.0; ASIA_SL= 1.0; ASIA_MH = 6

# ADX trending threshold — BB kapalı bu rejimde (BUG-3 düzeltmesi)
ADX_TRENDING = 28.0
DAILY_MAX_LOSS = 0.35
CONSEC_LIMIT   = 2
COOLDOWN_HOURS = 4


def load_period(year_months: list[str]) -> pd.DataFrame:
    """Belirtilen YYYY-MM listesini yükle."""
    frames = []
    for ym in year_months:
        pattern = f"/home/user/Bot2/BTCUSDT-1m-{ym}.csv"
        for f in sorted(glob.glob(pattern)):
            df = pd.read_csv(f)
            df.columns = ["ts","open","high","low","close","volume",
                          "ct","qv","count","tbv","tbqv","ign"]
            frames.append(df[["ts","open","high","low","close","volume"]].astype(float))
    if not frames:
        return pd.DataFrame()
    full = pd.concat(frames, ignore_index=True).drop_duplicates(subset="ts").sort_values("ts")
    full.index = pd.to_datetime(full["ts"], unit="ms", utc=True)
    return full.drop(columns=["ts"])


def resample_1h(df: pd.DataFrame) -> pd.DataFrame:
    return df.resample("1h").agg(
        {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    ).dropna()


def size_qty(risk_pct, balance, free_margin, ep, sl_dist):
    if sl_dist <= 0 or free_margin <= 0:
        return 0.0, 0.0
    risk_amt = balance * risk_pct
    qty = risk_amt / sl_dist
    # cap at free margin capacity
    max_qty = free_margin * LEVERAGE / ep
    qty = min(qty, max_qty)
    qty = round(qty, 3)
    if qty < MIN_LOT:
        return 0.0, 0.0
    margin = qty * ep / LEVERAGE
    if margin > free_margin + 1e-9:
        return 0.0, 0.0
    return qty, margin


def run_sim(df_1m: pd.DataFrame, label: str, monthly_add: float = 0.0):
    """Tam simülasyon — paralel 3 sleeve (BB, ORB, Asia BO)."""
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
    bb_pos  = ((df["close"] - lower_s) / (upper_s - lower_s).replace(0, np.nan))

    atr_a   = atr_s.values
    adx_a   = adx_s.values
    volma_a = vol_ma.values
    bb_a    = bb_pos.values

    n = len(close); warmup = 60
    dates_a = np.array([ts.date() for ts in idx])
    hours_a = np.array([ts.hour  for ts in idx])
    month_a = np.array([ts.to_period("M") for ts in idx])

    # ORB ve Asia range'leri önceden hesapla
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
                asia_by_date[d]["low"]  = min(asia_by_date[d]["low"], low_v[j])
                asia_by_date[d]["cnt"] += 1

    balance      = START
    used_margin  = 0.0
    daily_start  = START
    daily_date   = None

    bb_o = orb_o = asia_o = None
    orb_traded   = set()
    asia_traded  = set()

    consec  = {"bb": 0, "orb": 0, "asia": 0}
    cooldown= {"bb": None, "orb": None, "asia": None}

    trades       = []
    monthly_pnl  = {}

    def free(): return balance - used_margin

    for i in range(warmup, n):
        a_val = atr_a[i]
        if np.isnan(a_val) or a_val <= 0:
            continue

        cd = dates_a[i]; ch = hours_a[i]; cm = month_a[i]
        now_ts = idx[i]

        # Günlük reset + aylık ekleme
        if cd != daily_date:
            daily_date  = cd
            daily_start = balance + used_margin  # equity approximation

            # Aylık ekleme: ayın 1'inde
            if monthly_add > 0 and ch == 0 and cd.day == 1:
                balance += monthly_add

        # ── Pozisyon kapanış kontrolleri ──────────────────────────────
        for slot, pos in [("bb", bb_o), ("orb", orb_o), ("asia", asia_o)]:
            if pos is None:
                continue
            d = pos["dir"]; entry = pos["entry"]
            sl = pos["sl"]; tp = pos["tp"]
            qty = pos["qty"]; mh = pos["mh"]; held = i - pos["i"]

            ep_exit = None; reason = None
            if d == 1:
                if low_v[i] <= sl:   ep_exit, reason = sl,       "sl"
                elif high_v[i] >= tp: ep_exit, reason = tp,       "tp"
            else:
                if high_v[i] >= sl:  ep_exit, reason = sl,       "sl"
                elif low_v[i] <= tp:  ep_exit, reason = tp,       "tp"
            if ep_exit is None and held >= mh:
                ep_exit, reason = close[i], "mh"

            if ep_exit is not None:
                raw = d * (ep_exit - entry) * qty
                fee = entry * qty * COST_MAKER + ep_exit * qty * COST_TAKER
                pnl = raw - fee
                balance    += pnl
                used_margin -= pos["margin"]
                trades.append({"pnl": pnl, "strat": slot, "month": cm, "reason": reason})
                monthly_pnl.setdefault(cm, 0.0)
                monthly_pnl[cm] += pnl

                # Per-strategy consecutive loss tracking
                if pnl < 0:
                    consec[slot] += 1
                    if consec[slot] >= CONSEC_LIMIT:
                        import datetime as _dt
                        cooldown[slot] = now_ts + pd.Timedelta(hours=COOLDOWN_HOURS)
                else:
                    consec[slot] = 0

                if slot == "bb":   bb_o   = None
                elif slot == "orb": orb_o  = None
                else:               asia_o = None

        # Günlük kayıp limiti
        equity = balance + used_margin
        if daily_start > 0 and (daily_start - equity) / daily_start >= DAILY_MAX_LOSS:
            # Bu günün geri kalanında trade yok
            continue

        adx_val = adx_a[i]
        trending = not np.isnan(adx_val) and adx_val >= ADX_TRENDING

        # ── BB mean-reversion ────────────────────────────────────────
        if bb_o is None:
            # BUG-3 düzeltmesi: trending rejimde BB kapalı
            if not trending and cooldown["bb"] is None or (
                    cooldown["bb"] is not None and now_ts >= cooldown["bb"]):
                if cooldown["bb"] is not None and now_ts >= cooldown["bb"]:
                    cooldown["bb"] = None
                bpos = bb_a[i]
                vm   = volma_a[i]
                if not np.isnan(bpos) and (bpos < 0.0 or bpos > 1.0):
                    if np.isnan(vm) or vol[i] >= vm:
                        direction = 1 if bpos < 0.0 else -1
                        ep  = close[i]
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

        # ── ORB ─────────────────────────────────────────────────────
        if orb_o is None and cd not in orb_traded and ch > ORB_HOUR:
            if cooldown["orb"] is None or now_ts >= cooldown["orb"]:
                if cooldown["orb"] is not None and now_ts >= cooldown["orb"]:
                    cooldown["orb"] = None
                orb = orb_by_date.get(cd)
                if orb:
                    oh = orb["high"]; ol = orb["low"]; rng = oh - ol
                    if rng > 0:
                        cp = close[i]
                        if cp > oh:
                            # Limit entry at orb_high (BUG-1 düzeltmesi)
                            ep = oh; sl = ol; tp = oh + ORB_RR * rng
                            qty, mg = size_qty(ORB_RISK, balance, free(), ep, rng)
                            if qty > 0:
                                used_margin += mg
                                orb_traded.add(cd)
                                orb_o = {
                                    "i": i, "dir": 1, "entry": ep, "sl": sl, "tp": tp,
                                    "qty": qty, "margin": mg, "mh": ORB_MH,
                                }
                        elif cp < ol:
                            ep = ol; sl = oh; tp = ol - ORB_RR * rng
                            qty, mg = size_qty(ORB_RISK, balance, free(), ep, rng)
                            if qty > 0:
                                used_margin += mg
                                orb_traded.add(cd)
                                orb_o = {
                                    "i": i, "dir": -1, "entry": ep, "sl": sl, "tp": tp,
                                    "qty": qty, "margin": mg, "mh": ORB_MH,
                                }

        # ── Asia BO ─────────────────────────────────────────────────
        if asia_o is None and cd not in asia_traded and ch >= 8:
            if cooldown["asia"] is None or now_ts >= cooldown["asia"]:
                if cooldown["asia"] is not None and now_ts >= cooldown["asia"]:
                    cooldown["asia"] = None
                asia = asia_by_date.get(cd)
                if asia and asia["cnt"] >= 4:
                    ah = asia["high"]; al = asia["low"]
                    sl_dist = ASIA_SL * a_val
                    cp = close[i]
                    if cp > ah:
                        # Limit entry at asia_high (BUG-1 düzeltmesi)
                        ep = ah; sl = ah - sl_dist; tp = ah + ASIA_RR * sl_dist
                        qty, mg = size_qty(ASIA_RISK, balance, free(), ep, sl_dist)
                        if qty > 0:
                            used_margin += mg
                            asia_traded.add(cd)
                            asia_o = {
                                "i": i, "dir": 1, "entry": ep, "sl": sl, "tp": tp,
                                "qty": qty, "margin": mg, "mh": ASIA_MH,
                            }
                    elif cp < al:
                        ep = al; sl = al + sl_dist; tp = al - ASIA_RR * sl_dist
                        qty, mg = size_qty(ASIA_RISK, balance, free(), ep, sl_dist)
                        if qty > 0:
                            used_margin += mg
                            asia_traded.add(cd)
                            asia_o = {
                                "i": i, "dir": -1, "entry": ep, "sl": sl, "tp": tp,
                                "qty": qty, "margin": mg, "mh": ASIA_MH,
                            }

    return trades, monthly_pnl


def stats_block(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "wr": 0, "pf": 0, "net": 0, "avg": 0}
    p = [t["pnl"] for t in trades]
    pos_sum = sum(x for x in p if x > 0)
    neg_sum = sum(-x for x in p if x < 0)
    return {
        "n":   len(p),
        "wr":  sum(1 for x in p if x > 0) / len(p),
        "pf":  pos_sum / neg_sum if neg_sum > 0 else 999,
        "net": sum(p),
        "avg": sum(p) / len(p),
    }


def equity_curve(trades: list[dict], start: float, monthly_add: float) -> tuple[float, float]:
    """Gerçekçi equity simülasyonu: compound + aylık ekleme."""
    bal = start; peak = start; max_dd = 0.0
    current_month = None

    for t in trades:
        m = t["month"]
        if monthly_add > 0 and current_month is not None and m != current_month:
            bal += monthly_add
        current_month = m
        bal += t["pnl"]
        if bal > peak:
            peak = bal
        dd = (peak - bal) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return bal, max_dd


def print_scenario(label: str, trades: list[dict], monthly_pnl: dict,
                   start: float, monthly_add: float, invested: float):
    print(f"\n{'='*78}")
    print(f"  {label}")
    print(f"{'='*78}")

    if not trades:
        print("  Veri yok / trade yok")
        return

    final_bal, max_dd = equity_curve(trades, start, monthly_add)
    s = stats_block(trades)

    # Per-strategy stats
    strat_stats = {}
    for sl in ("bb", "orb", "asia"):
        t_sl = [t for t in trades if t["strat"] == sl]
        strat_stats[sl] = stats_block(t_sl)

    print(f"  Toplam trade : {s['n']:>5d}   WinRate: {s['wr']:>5.0%}   PF: {s['pf']:.2f}")
    print(f"  Son bakiye   : ${final_bal:>12,.0f}   Yatırılan: ${invested:,.0f}   Net kâr: ${final_bal-invested:>+,.0f}")
    print(f"  Max drawdown : {max_dd:>5.1%}   Ortalama trade: ${s['avg']:>+.1f}")
    print()
    print(f"  {'Strateji':<8s}  {'Trade':>6s}  {'WR':>6s}  {'PF':>5s}  {'Net $':>10s}")
    print(f"  {'-'*44}")
    for sl, ss in strat_stats.items():
        if ss["n"] > 0:
            print(f"  {sl.upper():<8s}  {ss['n']:>6d}  {ss['wr']:>5.0%}  {ss['pf']:>5.2f}  {ss['net']:>+10.0f}")

    # Aylık breakdown
    print()
    print(f"  {'Ay':<10s}  {'Trade':>6s}  {'Net PnL':>10s}  {'Birikimli':>12s}")
    print(f"  {'-'*44}")
    months = sorted(monthly_pnl.keys())
    bal_track = start
    for m in months:
        pnl_m = monthly_pnl[m]
        if monthly_add > 0 and months.index(m) > 0:
            bal_track += monthly_add
        bal_track += pnl_m
        month_trades = [t for t in trades if t["month"] == m]
        emoji = "🟢" if pnl_m >= 0 else "🔴"
        print(f"  {str(m):<10s}  {len(month_trades):>6d}  {pnl_m:>+10.0f}$  {bal_track:>11,.0f}$  {emoji}")


def main():
    print("Veri yükleniyor…", flush=True)

    # 2024 ayları
    months_2024 = [f"2024-{m:02d}" for m in range(1, 13)]
    # 2025-2026 ayları (mevcut veriler)
    months_2025 = [f"2025-{m:02d}" for m in range(5, 13)]
    months_2026 = [f"2026-{m:02d}" for m in range(1, 5)]
    months_25_26 = months_2025 + months_2026

    print("2024 verisi yükleniyor…", flush=True)
    df_2024 = load_period(months_2024)
    print(f"  2024: {len(df_2024):,} dakikalık mum")

    print("2025-2026 verisi yükleniyor…", flush=True)
    df_25_26 = load_period(months_25_26)
    print(f"  2025-2026: {len(df_25_26):,} dakikalık mum")

    print("\nSimülasyonlar çalışıyor…", flush=True)

    # --- SENARYO 1: 2024 tek başına ---
    print("  [1/3] 2024 simülasyonu…", flush=True)
    trades_24, mpnl_24 = run_sim(df_2024, "2024")

    # --- SENARYO 2: 2025-2026 tek başına ---
    print("  [2/3] 2025-2026 simülasyonu…", flush=True)
    trades_25, mpnl_25 = run_sim(df_25_26, "2025-2026")

    # --- SENARYO 3: 2 yıl kombine ---
    print("  [3/3] 2 yıl kombine simülasyon…", flush=True)
    df_all = pd.concat([df_2024, df_25_26]).sort_index()
    df_all = df_all[~df_all.index.duplicated(keep="first")]
    trades_all, mpnl_all = run_sim(df_all, "2 yıl kombine")

    # Yatırılan hesapları
    invested_24    = START + MONTHLY_ADD * 11   # 12 ay - 1 (ilk ay ekleme yok)
    invested_25_26 = START + MONTHLY_ADD * 11   # ~12 ay
    invested_all   = START + MONTHLY_ADD * 23   # ~24 ay

    print("\n" + "="*78)
    print("  AGRESİF PROFİL — BB%8 / ORB%5 / ASIA%3")
    print("  Başlangıç $200 + Her Ay $100 Ekleme (gerçekçi simülasyon)")
    print("  BUG-3 düzeltmesi aktif: ADX>28 trending rejimde BB kapalı")
    print("="*78)

    print_scenario(
        "SENARYO 1: SADECE 2024 (out-of-sample — strateji bu veriyle optimize edilmedi!)",
        trades_24, mpnl_24, START, MONTHLY_ADD, invested_24
    )

    print_scenario(
        "SENARYO 2: SADECE 2025-2026 (in-sample referans, ~12 ay)",
        trades_25, mpnl_25, START, MONTHLY_ADD, invested_25_26
    )

    print_scenario(
        "SENARYO 3: 2 YIL KOMBİNE (Ocak 2024 – Nisan 2026)",
        trades_all, mpnl_all, START, MONTHLY_ADD, invested_all
    )

    # Özet karşılaştırma
    print("\n" + "="*78)
    print("  ÖZET KARŞILAŞTIRMA")
    print("="*78)
    print(f"\n  {'':25s}  {'2024 (OOS)':>12s}  {'2025-26 (IS)':>13s}  {'2 yıl':>10s}")
    print(f"  {'-'*65}")
    for label, trades in [("Trade sayısı", [trades_24, trades_25, trades_all]),
                           ("WinRate", None),
                           ("Profit Factor", None),
                           ("Net kâr", None),
                           ("Max DD", None)]:
        if label == "Trade sayısı":
            vals = [f"{stats_block(t)['n']:>5d}" for t in trades]
            print(f"  {'Trade sayısı':<25s}  {vals[0]:>12s}  {vals[1]:>13s}  {vals[2]:>10s}")
        else:
            continue

    for lbl, key, fmt in [
        ("WinRate",       "wr",  lambda x: f"{x:.0%}"),
        ("Profit Factor", "pf",  lambda x: f"{x:.2f}"),
        ("Net PnL",       "net", lambda x: f"${x:+,.0f}"),
    ]:
        vals = [fmt(stats_block(t)[key]) for t in [trades_24, trades_25, trades_all]]
        print(f"  {lbl:<25s}  {vals[0]:>12s}  {vals[1]:>13s}  {vals[2]:>10s}")

    f24,  dd24  = equity_curve(trades_24,  START, MONTHLY_ADD)
    f25,  dd25  = equity_curve(trades_25,  START, MONTHLY_ADD)
    fall, ddall = equity_curve(trades_all, START, MONTHLY_ADD)
    vals_dd  = [f"{dd:.1%}" for dd in [dd24, dd25, ddall]]
    vals_fin = [f"${f:,.0f}" for f in [f24, f25, fall]]
    print(f"  {'Max Drawdown':<25s}  {vals_dd[0]:>12s}  {vals_dd[1]:>13s}  {vals_dd[2]:>10s}")
    print(f"  {'Son bakiye':<25s}  {vals_fin[0]:>12s}  {vals_fin[1]:>13s}  {vals_fin[2]:>10s}")

    print(f"\n  2024 out-of-sample testi: edge {'KANITLANDI ✓' if stats_block(trades_24)['pf'] > 1.0 else 'KANITI YOK ✗'}")
    print(f"  (PF>1.0 = strateji 2024'te de para kazandı, overfitting değil)")

if __name__ == "__main__":
    main()
