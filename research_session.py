"""
research_session.py

SAAT / SESSION (seans) filtresini dürüst additive metodolojiyle test eder.

HİPOTEZ: Mean-reversion (BB-fade) belirli seanslarda daha iyi çalışabilir.
  - Asya seansı (00–08 UTC): düşük hacim, range'li → reversion İYİ olabilir
  - Londra (07–16 UTC): volatilite açılışı, trend → reversion KÖTÜ olabilir
  - New York (13–22 UTC): haber + ABD akışı → karışık

YÖNTEM (research_orderflow_vwap ile birebir aynı dürüst disiplin):
  1. Baseline'ı BİR KEZ çalıştır → kanonik trade listesi.
  2. Her trade'i GİRİŞ anındaki saat (UTC) ile etiketle.
  3. Saat ve seans bazında bucket'la — alt grupların PnL toplamı = baseline.
     Önyargı yok, compounding confound yok.
  4. Bir bucket HEM TRAIN (2025) HEM TEST (2026)'te belirgin pozitifse → gerçek.
     Sadece birinde ise → gürültü, canlıya ALMA.

Run: python research_session.py
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
RISK  = 0.03
SL_M  = 3.0
TP_M  = 5.0
MH    = 48
SPLIT = pd.Timestamp("2026-01-01", tz="UTC")


def load_1h():
    files = sorted(glob.glob("/home/user/Bot2/BTCUSDT-1m-*.csv"))
    frames = []
    for f in files:
        df = pd.read_csv(f).rename(columns={"open_time": "ts"})
        frames.append(df[["ts", "open", "high", "low", "close", "volume"]].astype(float))
    m = (pd.concat(frames, ignore_index=True)
         .drop_duplicates(subset="ts").sort_values("ts"))
    m.index = pd.to_datetime(m["ts"], unit="ms", utc=True)
    m = m.drop(columns=["ts"])
    h = m.resample("1h").agg(
        {"open": "first", "high": "max", "low": "min",
         "close": "last", "volume": "sum"}
    ).dropna()
    return h


def run_baseline_annotated(df_1h):
    """Baseline trade'ler + giriş anı saati (UTC)."""
    c   = df_1h["close"].values
    h   = df_1h["high"].values
    lo  = df_1h["low"].values
    vol = df_1h["volume"].values
    upper, _, lower = bollinger_bands(df_1h["close"], 20, 2.0)
    atr_s  = atr(df_1h["high"], df_1h["low"], df_1h["close"], 14)
    vol_ma = df_1h["volume"].rolling(20).mean().values
    bb_pos = ((df_1h["close"] - lower) / (upper - lower).replace(0, np.nan)).values

    n = len(c); balance = BAL; open_t = None; trades = []
    for i in range(60, n):
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
                trades.append({**open_t["meta"], "ts_entry": open_t["ts"],
                               "dir": d, "pnl": pnl})
                open_t = None
            continue
        bpos = bb_pos[i]
        if np.isnan(bpos) or not (bpos < 0 or bpos > 1):
            continue
        direction = 1 if bpos < 0 else -1
        if np.isnan(vol_ma[i]) or vol[i] < vol_ma[i]:
            continue

        ts = df_1h.index[i]
        hour = ts.hour
        # Seans (UTC) — örtüşmeleri tek etikete indirgemek için kaba blok:
        if 0 <= hour < 7:
            sess = "Asya(00-07)"
        elif 7 <= hour < 13:
            sess = "Londra(07-13)"
        elif 13 <= hour < 21:
            sess = "NewYork(13-21)"
        else:
            sess = "Geç(21-24)"

        ep = c[i]; sl_d = SL_M * a
        sl = ep - direction * sl_d; tp = ep + direction * TP_M * a
        qty = min(round((balance * RISK) / (ep * (sl_d / ep)), 3),
                  balance * 0.5 / ep)
        if qty < 0.001:
            continue
        open_t = {"i": i, "ts": ts, "dir": direction,
                  "entry": ep, "sl": sl, "tp": tp, "qty": qty,
                  "meta": {"hour": hour, "sess": sess}}
    return trades


def summarize(trades, label):
    p = np.array([t["pnl"] for t in trades]); wr = (p > 0).mean()
    tr = [t for t in trades if t["ts_entry"] < SPLIT]
    te = [t for t in trades if t["ts_entry"] >= SPLIT]
    s_tr = (f"WR{(np.array([t['pnl'] for t in tr])>0).mean():.0%} "
            f"${sum(t['pnl'] for t in tr):>+6.0f}") if tr else "—"
    s_te = (f"WR{(np.array([t['pnl'] for t in te])>0).mean():.0%} "
            f"${sum(t['pnl'] for t in te):>+6.0f}") if te else "—"
    return (f"{label:<28} {len(p):>3}t WR{wr:.0%} ${p.sum():>+7.0f} "
            f"({p.sum()/100:>+5.1f}%) | TR {s_tr} | TE {s_te}")


def bucket_by_session(trades):
    sessions = ["Asya(00-07)", "Londra(07-13)", "NewYork(13-21)", "Geç(21-24)"]
    print(f"\n  [SEANS] (alt grupların toplamı = baseline)")
    print(f"  {'Seans':<16}{'Trade':>6}{'WR':>6}{'PnL':>9}{'avg':>8}"
          f"{'TRAIN':>15}{'TEST':>15}")
    for s in sessions:
        grp = [t for t in trades if t["sess"] == s]
        if not grp:
            continue
        pp = np.array([t["pnl"] for t in grp]); wr = (pp > 0).mean()
        tr = [t for t in grp if t["ts_entry"] < SPLIT]
        te = [t for t in grp if t["ts_entry"] >= SPLIT]
        ptr = sum(t["pnl"] for t in tr); pte = sum(t["pnl"] for t in te)
        wtr = (np.array([t["pnl"] for t in tr]) > 0).mean() if tr else 0
        wte = (np.array([t["pnl"] for t in te]) > 0).mean() if te else 0
        print(f"  {s:<16}{len(pp):>6}{wr*100:>5.0f}%{pp.sum():>+9.0f}"
              f"{pp.mean():>+8.1f}{f'W{wtr:.0%} {ptr:+.0f}':>15}"
              f"{f'W{wte:.0%} {pte:+.0f}':>15}")


def bucket_by_hour(trades):
    print(f"\n  [SAAT — UTC] (alt grupların toplamı = baseline)")
    print(f"  {'Saat':<6}{'Trade':>6}{'WR':>6}{'PnL':>9}{'avg':>8}"
          f"{'TRAIN':>14}{'TEST':>14}")
    for hr in range(24):
        grp = [t for t in trades if t["hour"] == hr]
        if not grp:
            continue
        pp = np.array([t["pnl"] for t in grp]); wr = (pp > 0).mean()
        tr = [t for t in grp if t["ts_entry"] < SPLIT]
        te = [t for t in grp if t["ts_entry"] >= SPLIT]
        ptr = sum(t["pnl"] for t in tr); pte = sum(t["pnl"] for t in te)
        flag = ""
        if ptr > 0 and pte > 0:
            flag = "  ✓ ikisinde +"
        elif ptr < 0 and pte < 0:
            flag = "  ✗ ikisinde -"
        print(f"  {hr:>02}:00{len(pp):>6}{wr*100:>5.0f}%{pp.sum():>+9.0f}"
              f"{pp.mean():>+8.1f}{ptr:>+14.0f}{pte:>+14.0f}{flag}")


def simulate_filtered(trades, allowed_sessions):
    """Sadece izin verilen seanslardaki trade'leri al, geri kalanı ATLA.
    NOT: bu sadece additive PnL toplamıdır — gerçek sıralı bakiye değil,
    ama no-overlap baseline'da trade'ler zaten ardışık, bu yüzden PnL toplamı
    karşılaştırma için geçerli."""
    grp = [t for t in trades if t["sess"] in allowed_sessions]
    p = np.array([t["pnl"] for t in grp])
    tr = [t for t in grp if t["ts_entry"] < SPLIT]
    te = [t for t in grp if t["ts_entry"] >= SPLIT]
    return p.sum(), sum(t["pnl"] for t in tr), sum(t["pnl"] for t in te), len(grp)


def main():
    df_1h = load_1h()
    print(f"BTC 1h: {len(df_1h)} bar "
          f"({df_1h.index[0]:%Y-%m-%d}→{df_1h.index[-1]:%Y-%m-%d}) [UTC]")
    print("=" * 100)

    trades = run_baseline_annotated(df_1h)
    print("\n" + summarize(trades, "BASELINE (filtre yok)"))

    print("\n" + "=" * 100)
    print("\n[1] SEANS BAZINDA")
    bucket_by_session(trades)

    print("\n" + "=" * 100)
    print("\n[2] SAAT BAZINDA (UTC) — ✓ = hem train hem test pozitif")
    bucket_by_hour(trades)

    print("\n" + "=" * 100)
    print("\n[3] SEANS FİLTRESİ SİMÜLASYONU (en iyi görünen seansları tut)")
    base_total, base_tr, base_te, base_n = simulate_filtered(
        trades, {"Asya(00-07)", "Londra(07-13)", "NewYork(13-21)", "Geç(21-24)"})
    print(f"  {'Filtre':<40}{'Trade':>6}{'Toplam':>10}{'TRAIN':>10}{'TEST':>10}")
    print(f"  {'(hepsi=baseline)':<40}{base_n:>6}{base_total:>+10.0f}"
          f"{base_tr:>+10.0f}{base_te:>+10.0f}")

    sessions = ["Asya(00-07)", "Londra(07-13)", "NewYork(13-21)", "Geç(21-24)"]
    # Tek tek her seansı çıkararak etkisini gör
    for drop in sessions:
        keep = set(sessions) - {drop}
        tot, t_tr, t_te, n = simulate_filtered(trades, keep)
        print(f"  {'- ' + drop + ' çıkar':<40}{n:>6}{tot:>+10.0f}"
              f"{t_tr:>+10.0f}{t_te:>+10.0f}")

    print("\n" + "=" * 100)
    print("\nYORUM:")
    print("  • Bir seans/saat HEM train HEM test'te belirgin NEGATİF ise → onu")
    print("    çıkarmak iki dönemde de getiriyi artırır → GERÇEK filtre.")
    print("  • Sadece tek dönemde kötü ise → gürültü; çıkarmak overfitting olur.")
    print("  • Çıkarınca toplam DÜŞÜYORSA → o seans net pozitif, dokunma.")

    print("\n" + "=" * 100)
    print("\n[4] GERÇEK OUT-OF-SAMPLE TEST (look-ahead YOK)")
    print("  Kötü saatleri SADECE 2025 (train) verisine bakarak seç,")
    print("  sonra hiç görmediğimiz 2026 (test) verisinde uygula.")
    tr_all = [t for t in trades if t["ts_entry"] < SPLIT]
    te_all = [t for t in trades if t["ts_entry"] >= SPLIT]

    # train'de net negatif olan saatleri tespit et
    bad_hours = []
    for hr in range(24):
        g = [t["pnl"] for t in tr_all if t["hour"] == hr]
        if g and sum(g) < 0:
            bad_hours.append(hr)
    print(f"\n  Train'de (2025) net negatif saatler: {bad_hours}")

    te_base = sum(t["pnl"] for t in te_all)
    te_filt = sum(t["pnl"] for t in te_all if t["hour"] not in bad_hours)
    n_base = len(te_all)
    n_filt = len([t for t in te_all if t["hour"] not in bad_hours])
    print(f"\n  TEST (2026) baseline       : {n_base:>3}t  ${te_base:>+7.0f}")
    print(f"  TEST (2026) bu saatler hariç: {n_filt:>3}t  ${te_filt:>+7.0f}")
    delta = te_filt - te_base
    print(f"  Fark: ${delta:>+7.0f}  →  "
          f"{'✓ filtre TEST''te işe yaradı' if delta > 0 else '✗ filtre TESTte ZARAR verdi (overfit)'}")

    # ters yön: train'de pozitif saatleri tut
    good_hours = [hr for hr in range(24)
                  if (g := [t['pnl'] for t in tr_all if t['hour'] == hr]) and sum(g) > 0]
    te_good = sum(t["pnl"] for t in te_all if t["hour"] in good_hours)
    n_good = len([t for t in te_all if t["hour"] in good_hours])
    print(f"\n  Train'de iyi saatleri TUT → TEST: {n_good:>3}t  ${te_good:>+7.0f} "
          f"(baseline ${te_base:+.0f})")


if __name__ == "__main__":
    main()
